"""Общие помощники тестов среза 008 (T-8003): мессенджер.

Имена и поведение — `tests/CONTRACT-008.md` (шапка «Правила для всех тестов среза», разделы 1.2, 1.4, 2.2, 3.4, 4.4,
5.1-5.7, 7.1, 8.1, 12, 14.3; решения контракта К8-К14, К16-К20). Образец — `support_feed.py`. Кода `messenger` может
ещё не быть, поэтому на уровне модуля нет импортов из `apps.messenger`, `config.asgi`, `channels`: модели берутся
лениво (`support.model("messenger.Chat")`), службы и задания среза импортируются внутри функций. Сбор тестов
(`pytest --collect-only`) проходит до появления кода.

Фикстур `@pytest.fixture` здесь нет (как в `support_kb.py`, `support_lists.py`, `support_feed.py`): подмены — обычные
функции и контекстные менеджеры, тест передаёт им `monkeypatch` параметром.

Повторный экспорт из `support_kb`, `support_notify`, `support_org` (раздел 5.7 разрешает «как в `support_kb`»):
`Session`, `capture_sql`, `assert_for_update`, `email_of`, `phone_of`, `moscow`, `moscow_text`, подмены ClamAV
`scan_clean`, `scan_found`, `scan_unavailable`, разбор кадров `Fragment`, `WsClient`, `ws_run`, `_application`.

Секреты и персональные данные: адреса и телефоны собираются из частей (`email_of`, `phone_of`); в именах переменных
нет слов `secret`, `token`, `key`, `password`; значения в сообщения об ошибках не попадают.
"""
import asyncio
import contextlib
import hashlib
import importlib
import io
import mimetypes
from types import SimpleNamespace
from unittest import mock

from django.conf import settings as django_settings
from django.db import connection, connections
from django.utils import timezone

from tests import support
from tests.support_kb import Session  # noqa: F401  («сотрудник и клиент», как в срезе 005)
from tests.support_kb import assert_for_update, capture_sql  # noqa: F401  (проверка по SQL, раздел 5.7)
from tests.support_kb import email_of, phone_of  # noqa: F401  (адреса и телефоны из частей)
from tests.support_kb import moscow, moscow_text  # noqa: F401  (время по Москве)
from tests.support_notify import Fragment, WsClient, _application, ws_run  # noqa: F401  (кадры и соединение)
from tests.support_notify import run_jobs as _notify_run_jobs
from tests.support_org import scan_clean, scan_found, scan_unavailable  # noqa: F401  (подмена ClamAV)

# --- числа и константы среза (раздел 1.4, 5.7) ----------------------------------------------------------------

# точки расширения, которые добавляет мессенджер; `unit_form_parts` — последняя (раздел 1.4)
POINTS_008 = ("unit_form_parts",)
# назначения файлов ядра после среза 008 (раздел 2.1): `messenger` — последнее
PURPOSES_008 = ("photo", "attachment", "knowledge", "lists", "feed", "messenger", "task")
# виды чата (`Chat.Kind`, раздел 2.2)
CHAT_KINDS = ("personal", "group", "department", "general")

MESSENGER_MODULE = "Мессенджер"
_ALL_DEFAULT = ("portal", "email")
# формат `TABLE` из `test_notify_catalog.py`: код, название, модуль, order, обязательность, каналы по умолчанию,
# события, внешний текст (раздел 7.1); склейки в 8-кортеж не входят — они в MESSENGER_COALESCE
MESSENGER_KINDS = (
    ("messenger.message", "Новое сообщение в чате", MESSENGER_MODULE, 80, False, _ALL_DEFAULT, (),
     "Новое сообщение в чате"),
    ("messenger.mention", "Упомянул вас в чате", MESSENGER_MODULE, 81, False, _ALL_DEFAULT, (),
     "Вас упомянули в чате"),
)
MESSENGER_CODES = ("messenger.message", "messenger.mention")
MESSENGER_TITLES = {row[0]: row[1] for row in MESSENGER_KINDS}
# виды с `coalesce_text` (раздел 7.1: склейка только у `messenger.message`, имя функции — `message_coalesce_text`)
MESSENGER_COALESCE = frozenset({"messenger.message"})

# шесть кодов журнала (раздел 8.1)
AUDIT_CODES = (
    "messenger.chat_deleted",
    "messenger.department_chat_deleted",
    "messenger.unit_chat_deleted",
    "messenger.general_changed",
    "messenger.retention_changed",
    "messenger.retention_purged",
)

# два пункта меню (раздел 3.4), формат прежних помощников (`url`, `title`, `icon`, `order`, `permissions`); ключ
# словаря — адрес пункта: `MENU_008["/messenger/"]["order"] == 1`. `visible` и `badge` — функции портала, в словаре
# их нет; баджем служит признак `live_badge`, его сверяет тест
MENU_008 = {
    "/messenger/": {"permissions": (), "url": "/messenger/", "title": "Мессенджер", "icon": "icons/chat.html",
                    "order": 1, "live_badge": "messenger"},
    "/settings/messenger/": {"permissions": ("settings.portal",), "url": "/settings/messenger/",
                             "title": "Настройки мессенджера", "icon": "icons/gear.html", "order": 64},
}

# формат `FEED_JOBS`/`LISTS_JOBS` из `test_sd_deploy.py`: функция, очередь, интервал, строка cron по UTC, job_timeout
JOBS_008 = {"messenger_retention": ("retention_night", "maintenance", None, "55 23 * * *", 600)}

_FILE_STATUSES = ("pending", "clean", "quarantine")
_BUS_EVENTS = ("unit.deleted", "access.changed")
_APP = "apps.messenger"


# --- вход ролями и сотрудники (раздел 5.7) ---------------------------------------------------------------------

def _person(value):
    """Сотрудник из `Session` или самого пользователя."""
    return value.user if isinstance(value, Session) else value


def make_user(state: str = "active", **extra) -> Session:
    """Действующий сотрудник с паролем и клиентом (`Session`), как `support.make_employee`.

    `state` — `core.User` состояние: `"active"` (по умолчанию), `"dismissed"`, `"invited"`; вошёл только действующий
    (уволенному и приглашённому вход закрыт прежними слоями ядра), у остальных клиент не вошёл. Прочие именованные
    доводы уходят в `support.make_employee` (например `full_name`, `email`)."""
    user = support.make_employee(state=state, **extra)
    client = support.logged_in(user) if state == "active" else support.make_client()
    return Session(user, client)


def as_admin(**extra) -> Session:
    """Администратор портала (роль «Администратор портала», `support.ADMIN_ROLE`); вошёл."""
    user = support.make_admin(**extra)
    return Session(user, support.logged_in(user))


def unit(name: str, parent=None):
    """Узел `org` через `org.services.structure.create_unit` с актором-администратором портала.

    `parent=None` — узел верхнего уровня (родитель — корневой отдел, `support_org.root_unit()`). Услуга `create_unit`
    пишет журнал `unit.created`, поэтому актор — настоящий администратор."""
    from apps.org.services import structure

    from tests import support_org

    actor = support.make_admin()
    parent = parent if parent is not None else support_org.root_unit()
    return structure.create_unit(kind="department", name=name, parent=parent, actor=actor)


# --- чаты (раздел 2.2, 5.7) ------------------------------------------------------------------------------------

def personal(a, b):
    """Личный диалог двух сотрудников: `pair_key = "<меньший id>:<больший id>"` и строки `ChatMember` обоих.

    Строка берётся `get_or_create` по `pair_key` (уникальный индекс раздела 2.2), поэтому повторный вызов даёт тот же
    чат. `created_by` — первый из собеседников; участники — оба, без `is_creator`."""
    Chat, ChatMember = support.model("messenger.Chat"), support.model("messenger.ChatMember")
    first, second = _person(a), _person(b)
    low, high = sorted((first.pk, second.pk))
    now = timezone.now()
    chat, created = Chat.objects.get_or_create(
        kind="personal", pair_key=f"{low}:{high}",
        defaults={"title": "", "created_by": first, "created_at": now})
    if created:
        for user, is_creator in ((first, False), (second, False)):
            ChatMember.objects.get_or_create(chat=chat, user=user,
                                             defaults={"is_creator": is_creator, "joined_at": now})
    return chat


def group(creator, members, title: str = "Группа"):
    """Групповой чат: `title`, создатель с `is_creator=True`, участники (создатель входит сам).

    `members` — сотрудники (`Session` или `core.User`); повтор и сам создатель в списке не мешают — строки
    `ChatMember` уникальны по паре «чат, сотрудник»."""
    Chat, ChatMember = support.model("messenger.Chat"), support.model("messenger.ChatMember")
    creator = _person(creator)
    now = timezone.now()
    chat = Chat.objects.create(kind="group", title=title, created_by=creator, created_at=now)
    seen = set()
    for person, is_creator in ((creator, True), *((_person(member), False) for member in members)):
        if person.pk in seen:
            continue
        seen.add(person.pk)
        ChatMember.objects.create(chat=chat, user=person, is_creator=is_creator, joined_at=now)
    return chat


def department_chat(unit_obj):
    """Чат отдела: `kind="department"`, `unit_id` узла и две системные записи (раздел 5.7).

    Название у чата отдела пусто — его даёт `page.chat_title(chat)` через `unit_refs` (раздел 5.4), поэтому
    переименование узла видно сразу. Системные записи — «Создал чат» и «К чату присоединились сотрудники отдела
    «<название>»» (раздел 5.2), автор у них пуст (`is_system=True`)."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")
    now = timezone.now()
    chat = Chat.objects.create(kind="department", title="", unit_id=unit_obj.pk, created_at=now,
                               last_message_at=now)
    Message.objects.create(chat=chat, author=None, is_system=True, text="Создал чат", created_at=now)
    Message.objects.create(chat=chat, author=None, is_system=True,
                           text=f"К чату присоединились сотрудники отдела «{unit_obj.name}»", created_at=now)
    return chat


def general():
    """«Общий чат»: единственная строка `kind="general"` (`get_or_create`, раздел 2.3)."""
    Chat = support.model("messenger.Chat")
    now = timezone.now()
    chat, _ = Chat.objects.get_or_create(kind="general",
                                         defaults={"title": "Общий чат", "created_at": now})
    return chat


def _set_vector(message) -> None:
    """Вектор сообщения своим SQL помощника (раздел 5.4): `to_tsvector('russian', …)` без маркеров `@[u…]`/`@[c…]`,
    текст — параметром. У удалённого и системного текста нет — вектор пуст."""
    Message = support.model("messenger.Message")
    assert Message._meta.db_table == "messenger_message"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE messenger_message SET search = to_tsvector('russian', "
            "regexp_replace(%s, '@\\[[uc][0-9]{1,9}\\]', ' ', 'g')) WHERE id = %s",
            [message.text, message.pk])
    message.refresh_from_db(fields=["search"])


def _invalidate_unread() -> None:
    """Сброс кэша чисел (5 с, раздел 5.3): фабрика пишет строки в обход службы отправки."""
    try:
        from apps.messenger.services import unread
    except ImportError:
        return
    invalidate = getattr(unread, "invalidate", None)
    if invalidate is not None:
        invalidate(None)


def post(chat, author, text: str = "Текст", quote=None, files=(),
         *, created_at=None, edited_at=None, deleted_at=None):
    """Сообщение прямой записью, без служб: `messenger.Message` и вектор помощника (`_set_vector`).

    `quote` — сообщение этого же чата (один уровень), `files` — готовые строки `MessageAttachment` (их `message`
    становится этим сообщением). `created_at` по умолчанию — `timezone.now()` (с фикстурой `clock` — часы теста).
    `last_message_at` чата поднимается до времени сообщения, кэш чисел сбрасывается: иначе список и числа после
    записи в обход `messages.send` показывали бы прежнее."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")
    now = timezone.now()
    created_at = created_at or now
    message = Message.objects.create(chat=chat, author=_person(author), is_system=False, text=text, quote=quote,
                                     created_at=created_at, edited_at=edited_at, deleted_at=deleted_at)
    _set_vector(message)
    if files:
        MessageAttachment = support.model("messenger.MessageAttachment")
        for attachment in files:
            MessageAttachment.objects.filter(pk=attachment.pk).update(message=message)
    if chat.last_message_at is None or created_at > chat.last_message_at:
        Chat.objects.filter(pk=chat.pk).update(last_message_at=created_at)
        chat.last_message_at = created_at
    _invalidate_unread()
    return message


def read(chat, user, at):
    """Строка `ChatRead` с указанным временем (`update_or_create` по уникальной паре «чат, сотрудник»).

    Правило `min(max(прежняя, at), now())` — дело службы `read.mark`; помощник пишет ровно переданное время."""
    ChatRead = support.model("messenger.ChatRead")
    at = at or timezone.now()
    row, _ = ChatRead.objects.update_or_create(chat=chat, user=_person(user), defaults={"last_read_at": at})
    return row


def attach(chat, name: str = "схема.png", data: bytes | None = None, *, status: str = "clean", uploaded_by=None,
           write: bool = False, thumb: bool = False, monkeypatch=None):
    """Строки `StoredFile(purpose="messenger")` и `MessageAttachment` (файл ещё не привязан к сообщению).

    `status` — `"pending"` («проверяется»), `"clean"` («чистый»), `"quarantine"` («карантин»); `scanned_at` — только
    у проверенного. Загрузивший — `uploaded_by`, иначе создатель чата, иначе первый участник, иначе новый сотрудник.
    С `write=True` байты пишутся на диск по `core.services.files.attachment_path` (`incoming/`, `attachments/`,
    `quarantine/` под `PROTECTED_ROOT`; нужна фикстура `protected_root`). С `thumb=True` пишется эскиз
    `attachments/thumbs/<id StoredFile>.jpg` и заполняется `MessageAttachment.thumb`. ClamAV при создании строк не
    зовётся; если тесту нужна подмена `apps.integrations.clamav.services.scan`, он передаёт `monkeypatch` — помощник
    ставит `scan_clean`/`scan_found`/`scan_unavailable` по `status` (раздел 5.6)."""
    if status not in _FILE_STATUSES:
        raise ValueError(f"status: pending, clean или quarantine, получено {status!r}")
    if data is None:
        if name.lower().endswith(".png"):
            from tests.support_org import png_bytes

            data = png_bytes()
        else:
            data = b"file body"
    if monkeypatch is not None:
        if status == "clean":
            scan_clean(monkeypatch)
        elif status == "quarantine":
            scan_found(monkeypatch)
        else:
            scan_unavailable(monkeypatch)
    now = timezone.now()
    stored = support.model("core.StoredFile").objects.create(
        purpose="messenger", owner=None, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream", status=status,
        scanned_at=now if status != "pending" else None)
    if write:
        from apps.core.services import files

        path = files.attachment_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    thumb_path = ""
    if thumb:
        import pathlib

        thumb_path = f"attachments/thumbs/{stored.pk}.jpg"
        full = pathlib.Path(django_settings.PROTECTED_ROOT) / thumb_path
        full.parent.mkdir(parents=True, exist_ok=True)
        from tests.support_org import jpeg_bytes

        full.write_bytes(jpeg_bytes(32, 32))
    uploader = _person(uploaded_by) if uploaded_by is not None else _chat_uploader(chat)
    return support.model("messenger.MessageAttachment").objects.create(
        message=None, file=stored, name=name, thumb=thumb_path, uploaded_by=uploader, uploaded_at=now)


def _chat_uploader(chat):
    """Загрузивший по умолчанию: создатель чата, затем первый участник, затем новый сотрудник."""
    if chat.created_by_id:
        return chat.created_by
    member = chat.members.order_by("id").first()
    if member is not None:
        return member.user
    return support.make_employee()


# --- выключение модуля в тестах (раздел 4.4, решения 10 и 12 задач) ---------------------------------------------

def _is_messenger(func) -> bool:
    return getattr(func, "__module__", "").startswith(_APP)


@contextlib.contextmanager
def without_messenger():
    """«Без `messenger`»: из всех точек реестра на время блока снимаются функции, у которых `__module__` начинается
    с `apps.messenger`; снимаются подписки шины `unit.deleted`/`access.changed`; `django.apps.apps.is_installed`
    отвечает «нет» для `apps.messenger`; `config.asgi` перезагружается, поэтому маршрутов `/ws/messenger/` нет.

    `INSTALLED_APPS` не перезагружается; по выходу из блока — в том числе по исключению — регистрации, подписки и
    `is_installed` возвращаются, `config.asgi` перезагружается заново (раздел 4.4, как `support_feed.without_feed`)."""
    from django.apps import apps as registry

    from apps.core import events, extensions

    saved_points = {point: list(funcs) for point, funcs in extensions._registry.items()}
    for funcs in extensions._registry.values():
        funcs[:] = [func for func in funcs if not _is_messenger(func)]
    saved_events = {}
    for name in _BUS_EVENTS:
        saved_events[name] = list(events.subscribers(name))
        for handler in saved_events[name]:
            if _is_messenger(handler):
                events.unsubscribe(name, handler)
    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        return False if app_name == _APP else real(app_name)

    registry.is_installed = is_installed
    module = importlib.import_module("config.asgi")
    try:
        yield importlib.reload(module)
    finally:
        registry.is_installed = real
        importlib.reload(module)
        for point, funcs in saved_points.items():
            extensions._registry[point][:] = funcs
        for name, handlers in saved_events.items():
            for handler in events.subscribers(name):
                events.unsubscribe(name, handler)
            for handler in handlers:
                events.subscribe(name, handler)


# --- миграция данных messenger 0002, задания (раздел 2.3, 5.7) --------------------------------------------------

def _alias(using: str | None) -> str:
    if using is None:
        return "migrate" if "migrate" in connections.databases else "default"
    return using


def run_seed(using: str | None = None, *, stand: bool = False) -> None:
    """`seed(django.apps.apps, SimpleNamespace(connection=…), stand=stand)` миграции `messenger 0002`; `using` по
    умолчанию — `migrate`, если он настроен, иначе `default` (как `support_feed.run_seed`)."""
    from django.apps import apps

    module = importlib.import_module("apps.messenger.migrations.0002_initial_data")
    module.seed(apps, SimpleNamespace(connection=connections[_alias(using)]), stand=stand)


def run_retention(now) -> int:
    """`apps.messenger.tasks.retention_night(now)` синхронно (время — параметром, раздел 1.4); число удалённых
    сообщений."""
    from apps.messenger import tasks

    return tasks.retention_night(now)


def run_jobs(queue: str = "notify") -> int:
    """Задания RQ очереди синхронно в этом процессе — `support_notify.run_jobs(queue)` (раздел 1.4)."""
    return _notify_run_jobs(queue)


# --- соединение /ws/messenger/ (раздел 5.5, решение К3) ---------------------------------------------------------

async def ws_client(user, query: str = "chat=1", *, hub=None, origin: str | None = "http://testserver") -> WsClient:
    """Соединение с `/ws/messenger/` внутри сценария `support_notify.ws_run`.

    `user` — `Session` (кука сессии берётся из его клиента) или `None` (без входа). `query` — строка запроса в
    `query_string` (`"chat=<id>"`: путь соединения номера чата не несёт, решение К3). `hub` — `WsHub` сценария:
    соединение закроется по выходу из `ws_run`. Возвращает `WsClient` после ответа на `websocket.connect`
    (`.accepted`, `.close_code`)."""
    from asgiref.testing import ApplicationCommunicator

    path = "/ws/messenger/"
    headers = [(b"host", b"testserver")]
    if origin is not None:
        headers.append((b"origin", origin.encode("latin-1")))
    client = getattr(user, "client", None)
    if client is not None:
        morsel = client.cookies.get(django_settings.SESSION_COOKIE_NAME)
        if morsel is not None:
            headers.append((b"cookie", f"{django_settings.SESSION_COOKIE_NAME}={morsel.value}".encode("latin-1")))
    scope = {"type": "websocket", "path": path, "raw_path": path.encode("latin-1"),
             "query_string": query.lstrip("?").encode("utf-8"), "headers": headers, "client": ("127.0.0.1", 50000),
             "server": ("testserver", 80), "scheme": "ws", "subprotocols": []}
    conn = WsClient(ApplicationCommunicator(_application(), scope))
    if hub is not None:
        hub._clients.append(conn)
    await conn._comm.send_input({"type": "websocket.connect"})
    message = await conn._next_output(2.0)
    if message is None:
        raise AssertionError(f"соединение {path}: нет ответа приложения за 2 с")
    if message["type"] == "websocket.accept":
        conn.accepted = True
    elif message["type"] == "websocket.close":
        conn.accepted = False
        conn._note_close(message)
        conn._finished = True
    else:
        raise AssertionError(f"соединение {path}: первый ответ — {message['type']}")
    return conn


# --- подмены слоя каналов (раздел 5.6, решение К16) -------------------------------------------------------------

_LAYER_FACTORIES = ("apps.messenger.services.live.get_channel_layer", "apps.notify.services.live.get_channel_layer")


class _DownLayer:
    """Слой, у которого `group_send` и `send` через `delay` секунд поднимают `TimeoutError`."""

    def __init__(self, delay: float):
        self.delay = delay

    async def group_send(self, group, message):
        await asyncio.sleep(self.delay)
        raise TimeoutError("слой publish недоступен (подмена теста)")

    async def send(self, channel, message):
        await asyncio.sleep(self.delay)
        raise TimeoutError("слой publish недоступен (подмена теста)")


@contextlib.contextmanager
def layer_down(delay: float = 0.0):
    """Слой `publish` недоступен (раздел 5.6): фабрики `get_channel_layer` (`messenger.services.live`,
    `notify.services.live`) отдают слой, у которого `group_send` и `send` через `delay` секунд (по умолчанию сразу)
    поднимают `TimeoutError`. Отправка не падает — служба предупреждает в журнал и сохраняет сообщение."""
    layer = _DownLayer(delay)
    patches = [mock.patch(target, lambda *args, **kwargs: layer, create=True) for target in _LAYER_FACTORIES]
    for patch in patches:
        patch.start()
    try:
        yield layer
    finally:
        for patch in reversed(patches):
            patch.stop()


class LayerSpy:
    """Итог `layer_spy`: `aliases` — аргументы фабрики (ожидается `"publish"`), `calls` — пары `(group, message)`,
    `by_group` — словарь «группа → список сообщений»."""

    def __init__(self):
        self.aliases: list = []
        self.calls: list[tuple] = []
        self.by_group: dict[str, list] = {}


class _SpyLayer:
    def __init__(self, spy: LayerSpy, real, passthrough: bool):
        self._spy, self._real, self._passthrough = spy, real, passthrough

    async def group_send(self, group, message):
        self._spy.calls.append((group, message))
        self._spy.by_group.setdefault(group, []).append(message)
        if self._passthrough and self._real is not None:
            await self._real.group_send(group, message)

    def __getattr__(self, name):
        return getattr(self._real, name)


@contextlib.contextmanager
def layer_spy(passthrough: bool = False):
    """Шпион слоя `publish` (раздел 5.6): запоминает аргументы фабрики и каждое `group_send(group, message)` без
    отправки (`passthrough=False` по умолчанию — раздел 5.6 говорит «без отправки»); при `passthrough=True` сообщение
    уходит и в настоящий слой."""
    from channels.layers import get_channel_layer as real_factory

    spy = LayerSpy()

    def factory(*args, **kwargs):
        spy.aliases.append(args[0] if args else kwargs.get("alias"))
        return _SpyLayer(spy, real_factory(*args, **kwargs), passthrough)

    patches = [mock.patch(target, factory, create=True) for target in _LAYER_FACTORIES]
    for patch in patches:
        patch.start()
    try:
        yield spy
    finally:
        for patch in reversed(patches):
            patch.stop()


# --- SQL (раздел 5.7) -------------------------------------------------------------------------------------------

@contextlib.contextmanager
def queries_with_params():
    """Контекст: список пар «SQL до подстановки, параметры» запросов соединения `default` (для проверок «значение —
    параметр», NFR-703; таблицы среза — `messenger_chat`, `messenger_message`, `messenger_chatmember`,
    `messenger_chatread`)."""
    pairs: list[tuple] = []

    def wrapper(execute, sql, params, many, context):
        pairs.append((sql if isinstance(sql, str) else str(sql), params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        yield pairs


# --- картинки в памяти (раздел 5.7, строка T-8003) --------------------------------------------------------------

def images() -> dict[str, bytes]:
    """Картинки в памяти: `jpeg_exif` (JPEG с ориентацией EXIF 6), `png_alpha` (PNG с прозрачностью), `gif_frames`
    (GIF из трёх кадров), `huge` (больше 40 Мп, `support_org.huge_pixels_png()`), `broken` (повреждённая картинка)."""
    from PIL import Image

    from tests import support_org

    exif = Image.Exif()
    exif[0x0112] = 6
    out = io.BytesIO()
    Image.new("RGB", (120, 80), (40, 120, 200)).save(out, "JPEG", exif=exif.tobytes())
    jpeg_exif = out.getvalue()

    out = io.BytesIO()
    Image.new("RGBA", (64, 64), (200, 80, 40, 100)).save(out, "PNG")
    png_alpha = out.getvalue()

    frames = [Image.new("P", (32, 32), color) for color in (1, 100, 200)]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    gif_frames = out.getvalue()

    return {"jpeg_exif": jpeg_exif, "png_alpha": png_alpha, "gif_frames": gif_frames,
            "huge": support_org.huge_pixels_png(), "broken": png_alpha[:40] + b"\x00broken\x00" * 8}


# --- страницы среза (раздел 5.7, имя — решение К10) --------------------------------------------------------------

def messenger_pages(chat=None) -> tuple[str, ...]:
    """Адреса страниц среза для проверок «по-русски» и «без `style=`» (разделы 1.1, 10.1, 12).

    `chat` — чат, беседа которого проверяется: адрес `/messenger/chats/<id>/` без номера не открыть, поэтому без
    чата помощник поднимает `ValueError`, а не отдаёт неполный список."""
    if chat is None:
        raise ValueError("messenger_pages: передайте чат среза — /messenger/chats/<id>/ проверяется по номеру")
    return ("/messenger/", f"/messenger/chats/{chat.pk}/", "/messenger/notifications/", "/settings/messenger/")