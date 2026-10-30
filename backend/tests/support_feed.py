"""Общие помощники тестов среза 007 (T-7101): живая лента.

Имена и поведение — `tests/CONTRACT-007.md` (разделы 1.1, 1.2, 1.4, 3.3, 3.4, 5.8, 5.9, 7.1, 15; решения задач 5, 7,
12, 15, 49, 51, 52; решения контракта К19, К21-К24). Образец — `support_lists.py`. Кода `feed` может ещё не быть,
поэтому на уровне модуля нет импортов из `apps.feed`, `config.asgi`, `channels`: модели берутся лениво
(`support.model("feed.Post")`), службы среза импортируются внутри функций. Сбор тестов (`pytest --collect-only`)
проходит до появления кода.

Фикстур `@pytest.fixture` здесь нет (как в `support_kb.py` и `support_lists.py`): подмены — обычные функции и
контекстные менеджеры, тест передаёт им `monkeypatch` параметром.

Повторный экспорт из `support_kb`, `support_org`, `support_lists` (раздел 5.9 разрешает «как в `support_kb`»):
`Session`, `capture_sql`, `sql_of`, `assert_for_update`, `assert_skip_locked`, `email_of`, `phone_of`, `moscow`,
`moscow_text`, `fail_file_write`, подмены ClamAV `scan_clean`, `scan_found`, `scan_unavailable`.

Секреты и персональные данные: адреса и телефоны собираются из частей (`email_of`, `phone_of`); в именах переменных
нет слов `secret`, `token`, `key`, `password`.
"""
import asyncio
import contextlib
import hashlib
import importlib
import io
import itertools
import json
import mimetypes
import re
import secrets
from datetime import datetime, timedelta
from html.parser import HTMLParser
from types import SimpleNamespace
from typing import Callable, NamedTuple
from unittest import mock

from django.conf import settings as django_settings
from django.db import connection, connections
from django.utils import timezone

from tests import factories, support
from tests.support_kb import Session  # noqa: F401  («сотрудник и клиент», как в срезе 005)
from tests.support_kb import assert_for_update, assert_skip_locked, capture_sql, sql_of  # noqa: F401  (раздел 5.9)
from tests.support_kb import email_of, phone_of  # noqa: F401  (адреса и телефоны из частей)
from tests.support_kb import fail_file_write  # noqa: F401  (сбой `core.uploads.write_file`, раздел 5.8)
from tests.support_kb import moscow, moscow_text  # noqa: F401  (время по Москве)
from tests.support_notify import Fragment, WsClient, _application, ws_run  # noqa: F401  (разбор и соединение)
from tests.support_org import scan_clean, scan_found, scan_unavailable  # noqa: F401  (подмена ClamAV)

# --- числа и константы среза (раздел 1.4, 5.9; `impact.md` «Общее») ----------------------------------------------

PERMISSIONS_007 = ("feed.post_all", "feed.moderate")
TITLES_007 = {"feed.post_all": "Писать всем", "feed.moderate": "Модерировать ленту"}
# держатели после установки (К24): «Писать всем» — три встроенные роли, «Модерировать ленту» — только администратор
HOLDERS_007 = {
    "feed.post_all": (support.ADMIN_ROLE, support.MANAGER_ROLE, support.STAFF_ROLE),
    "feed.moderate": (support.ADMIN_ROLE,),
}

POINTS_007 = ("home_body",)
KIND_FIELDS_007 = ("channels", "coalesce_text")
# хвост INSTALLED_APPS: список (а не кортеж), чтобы `settings.INSTALLED_APPS[-6:] == APPS_TAIL` было верным
APPS_TAIL = ["apps.servicedesk", "apps.notify", "apps.knowledge", "apps.lists", "apps.search", "apps.feed"]

_ALL_DEFAULT = ("portal", "email")
# формат `TABLE` из `test_notify_catalog.py`: код, название, модуль, order, обязательность, каналы по умолчанию,
# события, внешний текст (раздел 7.1; без `channels` и склейки — они в FEED_CHANNELS и FEED_COALESCE)
FEED_KINDS = (
    ("feed.for_you", "Запись для вас", "Лента", 70, False, _ALL_DEFAULT, (), "Новая запись в ленте для вас"),
    ("feed.mention", "Вас упомянули", "Лента", 71, False, _ALL_DEFAULT, (), "Вас упомянули в ленте"),
    ("feed.comment", "Новый комментарий", "Лента", 72, False, _ALL_DEFAULT, (), "Новый комментарий в ленте"),
    ("feed.important", "Важная запись", "Лента", 73, False, _ALL_DEFAULT, (), "Новая важная запись в ленте"),
    ("feed.invite", "Приглашение на событие", "Лента", 74, False, _ALL_DEFAULT, (),
     "Приглашение на событие в ленте"),
    ("feed.event_changed", "Событие изменено", "Лента", 75, False, _ALL_DEFAULT, (), "Событие в ленте изменено"),
    ("feed.event_reminder", "Напоминание о событии", "Лента", 76, False, _ALL_DEFAULT, (),
     "Скоро событие в ленте"),
    ("feed.like", "Нравится", "Лента", 77, False, ("portal",), (), ""),
)
FEED_CODES = [row[0] for row in FEED_KINDS]
FEED_TITLES = {row[0]: row[1] for row in FEED_KINDS}
FEED_MODULE = "Лента"
FEED_LIKE = "feed.like"
FEED_BOXED = [code for code in FEED_CODES if code != FEED_LIKE]   # семь видов с флажками внешних каналов
FEED_CHANNELS = {code: (("portal",) if code == FEED_LIKE else None) for code in FEED_CODES}
FEED_COALESCE = frozenset({"feed.comment", "feed.like"})

# формат `LISTS_JOBS` из `test_sd_deploy.py`: функция, очередь, интервал, строка cron по UTC, job_timeout
FEED_JOBS = {
    "feed_reminders": ("remind_events", "notify", None, "* * * * *", 120),
    "feed_retention": ("retention_night", "maintenance", None, "35 23 * * *", 600),
}
MENU_FEED = {"url": "/", "title": "Лента", "order": 0, "icon": "icons/feed.html"}
MENU_FEED_SETTINGS = {"url": "/settings/feed/", "title": "Настройки ленты", "order": 63, "icon": "icons/gear.html"}
FEED_SEARCH = ("feed", "Лента", 60)

_MARKER_RE = re.compile(r"@\[\d+\]")
_FILE_STATUSES = ("pending", "clean", "quarantine")
_post_counter = itertools.count(1)


# --- вход ролями (раздел 5.9) -------------------------------------------------------------------------------

def _employee_with_role(role, **extra):
    roles = list(extra.pop("roles", ())) + ([role] if role is not None else [])
    return support.make_employee(roles=roles, **extra)


def _session_with(codes: tuple[str, ...], **extra) -> Session:
    """Сотрудник с новой ролью с правами `codes` (строки прав создаются, если их ещё нет); кэш прав сброшен сразу
    (сигнал ядра сбрасывает его только после фиксации); вошёл."""
    from django.core.cache import cache

    from apps.core.services import permissions

    if codes:
        Permission = support.model("core.Permission")
        for code in codes:
            Permission.objects.get_or_create(code=code, defaults={"title": TITLES_007.get(code, code)})
        role = factories.make_role(permissions=codes)
    else:
        role = None
    user = _employee_with_role(role, **extra)
    cache.delete(permissions._key(user.pk))
    return Session(user, support.logged_in(user))


def as_writer(**extra) -> Session:
    """Сотрудник с ролью с правом `feed.post_all` («Писать всем»); вошёл."""
    return _session_with(("feed.post_all",), **extra)


def as_plain(**extra) -> Session:
    """Сотрудник без ролей (права «Писать всем» нет); вошёл."""
    return _session_with((), **extra)


def as_moderator(**extra) -> Session:
    """Сотрудник с ролью с правом `feed.moderate` («Модерировать ленту»); вошёл."""
    return _session_with(("feed.moderate",), **extra)


def without_post_all(role) -> None:
    """Снимает `feed.post_all` у роли средствами ядра (`roles.update_role`); `role` — `core.Role` или её название.
    Кэш прав держателей роли сбрасывается сразу. Действующий для журнала — новый администратор."""
    from django.core.cache import cache

    from apps.core.services import permissions, roles

    if isinstance(role, str):
        role = support.model("core.Role").objects.get(name=role)
    codes = [code for code in roles.permission_codes(role) if code != "feed.post_all"]
    roles.update_role(role, role.name, codes, actor=support.make_admin())
    for user_id in role.users.values_list("pk", flat=True):
        cache.delete(permissions._key(user_id))


# --- фабрики: записи, события, важное, комментарии, отметки (раздел 5.9) ------------------------------------------

def _plain_text(text: str) -> str:
    """Текст без маркеров `@[id]` (в вектор они не идут, план «Поиск»)."""
    return " ".join(_MARKER_RE.sub(" ", text).split())


def set_post_vector(post) -> None:
    """Вектор записи своим SQL помощника (план «Поиск»): название и место события с весом A, текст без маркеров
    с весом B, конфигурация `russian`. Всё, что вводит человек, уходит в SQL параметрами."""
    Post = support.model("feed.Post")
    assert Post._meta.db_table == "feed_post"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE feed_post SET search = "
            "setweight(to_tsvector('russian', coalesce(event_title, '') || ' ' || coalesce(event_place, '')), 'A') || "
            "setweight(to_tsvector('russian', %s), 'B') WHERE id = %s",
            [_plain_text(post.text), post.pk])
    post.refresh_from_db(fields=["search"])


def set_comment_vector(feed_comment) -> None:
    """Вектор комментария: `FeedComment.search` — вектор текста без маркеров (вес B не задаётся)."""
    FeedComment = support.model("feed.FeedComment")
    assert FeedComment._meta.db_table == "feed_feedcomment"
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE feed_feedcomment SET search = to_tsvector('russian', %s) WHERE comment_id = %s",
            [_plain_text(feed_comment.comment.text), feed_comment.pk])
    feed_comment.refresh_from_db(fields=["search"])


def _midnight_after(moment: datetime, days_ahead: int) -> datetime:
    """Полночь Europe/Moscow через `days_ahead` дней после дня момента."""
    local = moment.astimezone(moscow(2000, 1, 1).tzinfo)
    day = local.date() + timedelta(days=days_ahead)
    return moscow(day.year, day.month, day.day)


def _recipient_rows(post, to, mentions, published_at) -> None:
    Recipient = support.model("feed.Recipient")
    for item in to:
        if item == "all":
            continue
        label = getattr(getattr(item, "_meta", None), "label_lower", None)
        if label == "core.user":
            Recipient.objects.create(post=post, kind="user", user=item, via="to", published_at=published_at)
        elif label == "org.unit":
            Recipient.objects.create(post=post, kind="unit", unit_id=item.pk, via="to", published_at=published_at)
        elif isinstance(item, str) and re.fullmatch(r"u\d+", item):
            Recipient.objects.create(post=post, kind="unit", unit_id=int(item[1:]), via="to",
                                     published_at=published_at)
        elif isinstance(item, str) and re.fullmatch(r"p\d+", item):
            Recipient.objects.create(post=post, kind="user", user_id=int(item[1:]), via="to",
                                     published_at=published_at)
        else:
            raise TypeError(f"to: 'all', core.User, org.Unit, 'u<id>' или 'p<id>', получено {item!r}")
    for person in mentions:
        Recipient.objects.create(post=post, kind="user", user=person, via="mention", published_at=published_at)


def make_post(author, kind: str = "post", *, to=(), mentions=(), text: str = "Текст записи", published_at=None,
              important_until=None, event=None, edited_at=None):
    """Запись прямой записью, без служб.

    `to`: `"all"` (`to_all=True`, строки нет), объект `core.User`, объект `org.Unit` или строки `"u<id>"` (узел),
    `"p<id>"` (человек); строки `Recipient(via="to")` с копией `published_at`. `mentions` — сотрудники: маркеры
    `@[id]` дописываются в текст, строки `via="mention"`. Вектор — `set_post_vector`. `published_at` по умолчанию —
    `timezone.now()` (с фикстурой `clock` — часы теста). У важной `important_until` по умолчанию — срок «День» от
    момента публикации (полночь по Москве после следующего дня). `event` — словарь `title`, `place`, `start`, `end`
    (`end` по умолчанию — `start + 1 ч`); `remind_at = start - 1 ч`, если до начала не меньше часа, иначе пусто."""
    Post = support.model("feed.Post")
    to = tuple(to) if not isinstance(to, (str, bytes)) else (to,)
    now = timezone.now()
    published_at = published_at or now
    if mentions:
        text = (text + " " + " ".join(f"@[{person.pk}]" for person in mentions)).strip()
    fields = dict(author=author, kind=kind, text=text, to_all="all" in to, published_at=published_at,
                  edited_at=edited_at)
    if kind == "important":
        fields["important_until"] = important_until or _midnight_after(published_at, 2)
    elif important_until is not None:
        fields["important_until"] = important_until
    if kind == "event":
        if event is None:
            raise ValueError("kind='event' требует event={'title', 'place', 'start', 'end'}")
        start = event["start"]
        end = event.get("end") or start + timedelta(hours=1)
        fields.update(event_title=event["title"], event_place=event["place"], event_start=start, event_end=end,
                      remind_at=(start - timedelta(hours=1)) if start - now >= timedelta(hours=1) else None)
    post = Post.objects.create(**fields)
    _recipient_rows(post, to, mentions, published_at)
    set_post_vector(post)
    return post


def make_event(author, *, start, end=None, title: str = "Событие", place: str = "Корпус 1", to=(), **extra):
    """Запись `kind="event"`; `end` по умолчанию — `start + 1 ч`; `remind_at` — по правилу плана от текущего времени."""
    return make_post(author, "event", to=to, event={"title": title, "place": place, "start": start, "end": end},
                     **extra)


def make_important(author, *, until=None, to=(), **extra):
    """Запись `kind="important"`; `until` — `important_until`, по умолчанию срок «День» от текущего времени."""
    return make_post(author, "important", to=to, important_until=until, **extra)


def comment(post, author, text: str = "Комментарий", *, created_at=None, mentions=()):
    """`core.Comment` (`object_ref="feed.post:<id>"`) и `FeedComment` прямой записью; вектор — SQL помощника.

    `mentions` — сотрудники: маркеры `@[id]` дописываются в текст, и упомянутый становится адресатом записи
    (`Recipient(via="mention")` записи, если такой строки ещё нет; FR-611, план «Упоминание в комментарии»)."""
    if mentions:
        text = (text + " " + " ".join(f"@[{person.pk}]" for person in mentions)).strip()
        Recipient = support.model("feed.Recipient")
        for person in mentions:
            Recipient.objects.get_or_create(post=post, kind="user", user=person, via="mention",
                                            defaults={"published_at": post.published_at})
    core_comment = support.model("core.Comment").objects.create(
        object_ref=f"feed.post:{post.pk}", author=author, text=text, created_at=created_at or timezone.now())
    feed_comment = support.model("feed.FeedComment").objects.create(comment=core_comment, post=post)
    set_comment_vector(feed_comment)
    return core_comment


def like(target, user):
    """«Нравится»: `target` — `Post` (`PostLike`) или `core.Comment` (`CommentLike`, `post` — запись комментария)."""
    label = target._meta.label_lower
    now = timezone.now()
    if label == "feed.post":
        return support.model("feed.PostLike").objects.create(post=target, user=user, created_at=now)
    if label == "core.comment":
        post_id = support.model("feed.FeedComment").objects.get(comment=target).post_id
        return support.model("feed.CommentLike").objects.create(comment=target, post_id=post_id, user=user,
                                                                created_at=now)
    raise TypeError(f"target: feed.Post или core.Comment, получено {label}")


def attach(target, name: str = "схема.png", data: bytes | None = None, *, status: str = "clean", uploaded_by=None,
           write: bool = False, thumb: bool = False):
    """Строки `StoredFile(purpose="feed", owner=None)` и `FeedFile`.

    `target` — `Post`, `core.Comment` (тогда и `post` его записи) или `None` (непривязанный файл, нужен
    `uploaded_by` или создаётся сотрудник). `status` — `"pending"` («проверяется»), `"clean"` («чистый»),
    `"quarantine"` («карантин»); `scanned_at` — только у проверенного. С `write=True` байты пишутся на диск по
    `files.attachment_path` (`incoming/`, `attachments/`, `quarantine/` под `PROTECTED_ROOT`; нужна фикстура
    `protected_root`). С `thumb=True` пишется файл эскиза `attachments/thumbs/<id StoredFile>.jpg` и заполняется
    `FeedFile.thumb` (путь относительно `PROTECTED_ROOT`). ClamAV подменяют `scan_clean`, `scan_found`,
    `scan_unavailable`."""
    if status not in _FILE_STATUSES:
        raise ValueError(f"status: pending, clean или quarantine, получено {status!r}")
    post = comment_obj = None
    default_user = None
    if target is not None:
        label = target._meta.label_lower
        if label == "feed.post":
            post, default_user = target, target.author
        elif label == "core.comment":
            comment_obj, default_user = target, target.author
            post = support.model("feed.FeedComment").objects.get(comment=target).post
        else:
            raise TypeError(f"target: feed.Post, core.Comment или None, получено {label}")
    if data is None:
        if name.lower().endswith(".png"):
            from tests.support_org import png_bytes

            data = png_bytes()
        else:
            data = b"file body"
    now = timezone.now()
    stored = support.model("core.StoredFile").objects.create(
        purpose="feed", owner=None, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
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
    uploader = uploaded_by or default_user or support.make_employee()
    return support.model("feed.FeedFile").objects.create(
        post=post, comment=comment_obj, file=stored, name=name, thumb=thumb_path, uploaded_by=uploader,
        uploaded_at=now)


# --- выключение модулей (раздел 3.4, решения 22 и 52 задач) ---------------------------------------------------

@contextlib.contextmanager
def without_feed():
    """«Без `feed`»: из всех точек реестра на время блока снимаются функции, у которых `__module__` начинается
    с `apps.feed`; прочие регистрации остаются; `INSTALLED_APPS` не перезагружается."""
    from apps.core import extensions

    saved = {point: list(funcs) for point, funcs in extensions._registry.items()}
    for funcs in extensions._registry.values():
        funcs[:] = [f for f in funcs if not getattr(f, "__module__", "").startswith("apps.feed")]
    try:
        yield
    finally:
        for point, funcs in saved.items():
            extensions._registry[point][:] = funcs


@contextlib.contextmanager
def without_org():
    """«Без `org`»: `django.apps.apps.is_installed("apps.org")` ложен, прочие ответы как были. Для `notify` —
    прежний `support_lists.without_app(monkeypatch, "apps.notify")`."""
    from django.apps import apps as registry

    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        return False if app_name == "apps.org" else real(app_name)

    registry.is_installed = is_installed
    try:
        yield
    finally:
        registry.is_installed = real


@contextlib.contextmanager
def reload_asgi_without_feed():
    """Перезагружает `config.asgi` с подменой `django.apps.apps.is_installed` (для `"apps.feed"` ложно) и отдаёт
    модуль; после блока подмена снимается и модуль перезагружается заново (решение 52 задач)."""
    from django.apps import apps as registry

    module = importlib.import_module("config.asgi")
    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        return False if app_name == "apps.feed" else real(app_name)

    registry.is_installed = is_installed
    try:
        yield importlib.reload(module)
    finally:
        registry.is_installed = real
        importlib.reload(module)


# --- миграция данных feed 0002, задания (раздел 2.3, 5.9; решение 5 и 25 задач) --------------------------------

def _alias(using: str | None) -> str:
    if using is None:
        return "migrate" if "migrate" in connections.databases else "default"
    return using


def run_seed(using: str | None = None, *, stand: bool = False) -> None:
    """`seed(django.apps.apps, SimpleNamespace(connection=…), stand=stand)` миграции `feed 0002`; `using` по
    умолчанию — `migrate`, если он настроен, иначе `default`."""
    from django.apps import apps

    module = importlib.import_module("apps.feed.migrations.0002_initial_data")
    module.seed(apps, SimpleNamespace(connection=connections[_alias(using)]), stand=stand)


def run_reminders(now):
    """`apps.feed.tasks.remind_events(now)` синхронно; возвращает `RunResult(reminded, failed)`."""
    from apps.feed import tasks

    return tasks.remind_events(now)


def run_retention(now) -> int:
    """`apps.feed.services.retention.run(now)` синхронно; возвращает число удалённых записей."""
    from apps.feed.services import retention

    return retention.run(now)


# --- соединение /ws/feed/ (раздел 11, решение 7 задач) -----------------------------------------------------------

async def ws_client(user, query: str = "", *, hub=None, origin: str | None = "http://testserver") -> WsClient:
    """Соединение с `/ws/feed/` внутри сценария `support_notify.ws_run`.

    `user` — `Session` (кука сессии берётся из его клиента) или `None` (без входа). `query` — строка запроса в
    `query_string`. `hub` — `WsHub` сценария: соединение закроется по выходу из `ws_run`. Возвращает `WsClient`
    после ответа на `websocket.connect` (`.accepted`, `.close_code`)."""
    from asgiref.testing import ApplicationCommunicator

    path = "/ws/feed/"
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


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


async def send_sync(client, ids, since) -> None:
    """Сообщение клиента `{"sync": {"ids": [...], "since": ISO}}`."""
    await client.send(json.dumps({"sync": {"ids": list(ids), "since": _iso(since)}}))


async def send_add(client, ids, since=None) -> None:
    """Сообщение клиента `{"add": [...], "since": ISO}`; при `since=None` ключ `since` не посылается."""
    payload = {"add": list(ids)}
    if since is not None:
        payload["since"] = _iso(since)
    await client.send(json.dumps(payload))


# --- подмены слоя каналов (раздел 5.8, решения 40 и К21) -----------------------------------------------------------

_LAYER_FACTORIES = ("apps.feed.services.live.get_channel_layer", "apps.notify.services.live.get_channel_layer")


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
    """Слой `publish` недоступен: обе фабрики `get_channel_layer` (`feed.services.live`, `notify.services.live`)
    отдают слой, у которого `group_send` и `send` через `delay` секунд (по умолчанию сразу) поднимают
    `TimeoutError`. Фабрика принимает любые аргументы."""
    layer = _DownLayer(delay)
    patches = [mock.patch(target, lambda *args, **kwargs: layer) for target in _LAYER_FACTORIES]
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
def layer_spy(passthrough: bool = True):
    """Шпион слоя `publish`: оборачивает обе фабрики `get_channel_layer`, запоминает аргументы фабрики и каждое
    `group_send(group, message)`; при `passthrough=True` отправка идёт в настоящий слой."""
    from channels.layers import get_channel_layer as real_factory

    spy = LayerSpy()

    def factory(*args, **kwargs):
        spy.aliases.append(args[0] if args else kwargs.get("alias"))
        return _SpyLayer(spy, real_factory(*args, **kwargs), passthrough)

    patches = [mock.patch(target, factory) for target in _LAYER_FACTORIES]
    for patch in patches:
        patch.start()
    try:
        yield spy
    finally:
        for patch in reversed(patches):
            patch.stop()


# --- подмены «между выборкой и замком» и гонок (раздел 5.8, решения 6, 15, 45, 50 задач) ---------------------------

def act_between_select_and_lock(monkeypatch, which: str, action: Callable) -> list:
    """После настоящей выборки зовёт `action(...)` и возвращает выборку как была; возвращает список выданных выборок.

    `"reminders"` — оборачивает `apps.feed.services.reminders.select_due`: `action(post_id)`, номер или `None`
    (при `None` `action` не зовётся); `"retention"` — `apps.feed.services.retention.select_batch`: `action(ids)`."""
    if which == "reminders":
        module = importlib.import_module("apps.feed.services.reminders")
        name = "select_due"
    elif which == "retention":
        module = importlib.import_module("apps.feed.services.retention")
        name = "select_batch"
    else:
        raise ValueError(f"which: reminders или retention, получено {which!r}")
    issued, real = [], getattr(module, name)

    def wrapper(*args, **kwargs):
        result = real(*args, **kwargs)
        issued.append(list(result) if isinstance(result, (list, tuple)) else result)
        if which == "retention" or result is not None:
            action(result)
        return result

    monkeypatch.setattr(module, name, wrapper)
    return issued


def delete_post_between_check_and_insert(monkeypatch) -> list:
    """Оборачивает `apps.feed.services.comments.post_for_comment`: после настоящей проверки удаляет запись
    (`Post.objects.filter(pk=…).delete()`) и возвращает объект. Возвращает список удалённых номеров."""
    from apps.feed.services import comments

    deleted, real = [], comments.post_for_comment

    def wrapper(*args, **kwargs):
        post = real(*args, **kwargs)
        support.model("feed.Post").objects.filter(pk=post.pk).delete()
        deleted.append(post.pk)
        return post

    monkeypatch.setattr(comments, "post_for_comment", wrapper)
    return deleted


def mark_created_between_check_and_insert(monkeypatch) -> list:
    """Подменяет `apps.feed.services.likes.find_mark`: отвечает «отметки нет», хотя строка уже есть. Возвращает
    список вызовов `(kind, target_id, user_id)`."""
    from apps.feed.services import likes

    calls: list = []

    def fake(kind, target_id, user_id):
        calls.append((kind, target_id, user_id))
        return False

    monkeypatch.setattr(likes, "find_mark", fake)
    return calls


# --- SQL (раздел 5.9) -------------------------------------------------------------------------------------------

@contextlib.contextmanager
def queries_with_params():
    """Контекст: список пар «SQL до подстановки, параметры» запросов соединения `default` (для проверок «значение —
    параметр»)."""
    pairs: list[tuple] = []

    def wrapper(execute, sql, params, many, context):
        pairs.append((sql if isinstance(sql, str) else str(sql), params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        yield pairs


# --- картинки в памяти (раздел 5.9, строка T-7101) --------------------------------------------------------------

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


# --- страницы среза и разбор разметки (раздел 5.9) --------------------------------------------------------------

def feed_pages(post) -> tuple[str, ...]:
    """Адреса страниц среза для проверок «по-русски» и «без `style=`»."""
    return ("/", f"/feed/{post.pk}/", f"/feed/{post.pk}/edit/", "/settings/feed/")


_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})


class _PartParser(HTMLParser):
    """Первый элемент с нужным `id` на любой глубине: тег, атрибуты, текст поддерева."""

    def __init__(self, wanted: str):
        super().__init__(convert_charrefs=True)
        self.wanted = wanted
        self.found: Fragment | None = None
        self._root = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if self.found is not None:
            return
        if self._root is None:
            values = {name: ("" if value is None else value) for name, value in attrs}
            if values.get("id") == self.wanted:
                if tag in _VOID:
                    self.found = Fragment(tag, values, "")
                else:
                    self._root, self._depth = (tag, values, []), 1
        elif tag not in _VOID:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.found is None and self._root is None:
            values = {name: ("" if value is None else value) for name, value in attrs}
            if values.get("id") == self.wanted:
                self.found = Fragment(tag, values, "")

    def handle_endtag(self, tag):
        if self._root is None or tag in _VOID or self.found is not None:
            return
        self._depth -= 1
        if self._depth == 0:
            root_tag, values, parts = self._root
            self._root = None
            self.found = Fragment(root_tag, values, "".join(parts).strip())

    def handle_data(self, data):
        if self._root is not None:
            self._root[2].append(data)


def post_part(html: str, post_id: int, part: str = "") -> Fragment | None:
    """Часть записи по `id` `feed-post-<id>[-<part>]` в разметке (на любой глубине); `None`, если её нет.
    Возвращает `support_notify.Fragment(tag, attrs, text)`."""
    wanted = f"feed-post-{post_id}" + (f"-{part}" if part else "")
    parser = _PartParser(wanted)
    parser.feed(html)
    parser.close()
    if parser.found is None and parser._root is not None:   # элемент не закрыт: отдаём собранное
        root_tag, values, parts = parser._root
        return Fragment(root_tag, values, "".join(parts).strip())
    return parser.found
