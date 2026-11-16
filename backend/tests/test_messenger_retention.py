"""T-8119: тесты срока хранения и ночного задания мессенджера (FR-662, FR-670, FR-671, NFR-703, NFR-706).

Источники: TASKS-008 T-8119 (точный список имён), PLAN-008 «Срок хранения и ночное задание» (граница
`created_at < now − N лет`, 29 февраля → 28 февраля; правка срок не продлевает; четыре идемпотентных шага пачками по
1 000, пересчёт `last_message_at`, непривязанные файлы старше 24 часов, чаты отдела с несуществующим `unit_id`,
одна запись `messenger.retention_purged` только при удалении больше нуля; cron `55 23 * * *`, очередь `maintenance`,
`job_timeout=600`), CONTRACT-008: 1.2 (запись cron), 2.2 (`Chat.unit_id` — число без внешнего ключа), 5.4
(`retention.boundary`, `retention.run`), 5.6 (SQL — `capture_sql`), 5.7 (`support_messenger.run_retention`, `attach`,
`post`), 8.1 (`messenger.retention_purged`, `messenger.unit_chat_deleted`), 10.2 (`/settings/messenger/`), 13.1
(текст отказа «Срок хранения — от 1 до 10 лет»).

Задание выполняется синхронно: `support_messenger.run_retention(NOW)` — `tasks.retention_night(now)`; «сейчас» —
аргумент, а не часы машины. Диск стирается после фиксации — проверка через `django_capture_on_commit_callbacks`.
Пачки — три выборки с `LIMIT 1000` в `capture_sql`. Журнал — `core.AuditEvent`. Код среза на уровне модуля не
импортируется: модели — через `support.model`, службы и задание — ленивыми импортами внутри тестов, поэтому
`pytest --collect-only` проходит до появления кода. Секретов и ПДн нет: адреса и телефоны не создаются, ФИО и
тексты — вымышленные.
"""
import ast
import json
import pathlib
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.conf import settings as django_settings

from tests import support
from tests import support_messenger as sm
from tests.support import BACKEND_DIR

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
BOUNDARY = datetime(2023, 11, 16, 12, 0, tzinfo=UTC)      # NOW − 3 года (срок по умолчанию)
OLD = BOUNDARY - timedelta(days=1)                        # три года и один день
YOUNG = BOUNDARY + timedelta(days=1)
DAY = timedelta(days=1)
SETTINGS_URL = "/settings/messenger/"
RETENTION_RANGE = "Срок хранения — от 1 до 10 лет"
PURGED = "messenger.retention_purged"
UNIT_PURGED = "messenger.unit_chat_deleted"
CRON_PATH = BACKEND_DIR / "config" / "cron.py"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- модели среза и общий журнал (ленивые помощники) ------------------------------------------------------------

def _Message():
    return support.model("messenger.Message")


def _Chat():
    return support.model("messenger.Chat")


def _Attachment():
    return support.model("messenger.MessageAttachment")


def _StoredFile():
    return support.model("core.StoredFile")


def _Settings():
    return support.model("messenger.MessengerSettings")


def _Unit():
    return support.model("org.Unit")


def _audit(action: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _journal_values(event) -> dict:
    """Ключи «было / стало» одной записи журнала одним словарём (раздел 8.1)."""
    return {**(event.before or {}), **(event.after or {})}


def _attachment_paths(attachment) -> list[pathlib.Path]:
    """Путь оригинала (по состоянию файла) и эскиза вложения на диске."""
    from apps.core.services import files

    paths = [pathlib.Path(files.attachment_path(attachment.file))]
    if attachment.thumb:
        paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / attachment.thumb)
    return paths


def _chat(author, friend, title: str = "Срок хранения"):
    return sm.group(author, [friend], title=title)


# --- разбор разметки страницы настроек (помощник только этого файла; образец — test_feed_settings.py) -----------

class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(response.content.decode("utf-8", "replace"))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; `_` в имени атрибута — дефис, `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


# --- разбор config/cron.py (помощник только этого файла; образец — test_feed_deploy.py) ------------------------

def _cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в `config/cron.py` разбором дерева: функция, очередь, cron, интервал, имя,
    `job_timeout`, признак «под проверкой `apps.is_installed("apps.messenger")`»."""
    tree = ast.parse(CRON_PATH.read_text(encoding="utf-8"))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    constants = {node.targets[0].id: node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    def guarded(node) -> bool:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, ast.If):
                test = ast.unparse(current.test).replace("'", '"').replace(" ", "")
                if re.fullmatch(r'(\w+\.)*is_installed\("apps\.messenger"\)', test):
                    return True
            current = parents.get(current)
        return False

    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            first = node.args[0] if node.args else None
            target = aliases.get(first.id, first.id) if isinstance(first, ast.Name) else None
            options = {kw.arg: value(kw.value) for kw in node.keywords}
            found.append({"target": target, "queue": options.get("queue_name"), "cron": options.get("cron"),
                          "interval": options.get("interval"), "name": options.get("name"),
                          "job_timeout": options.get("job_timeout"), "guarded": guarded(node)})
    return found


# --- настройка срока ------------------------------------------------------------------------------------------

def test_setting_zero_eleven_and_abc_refused():
    """FR-670 (CONTRACT-008, 10.2, 13.1): `POST /settings/messenger/` со сроком 0, 11 и не числом отвечает 200 с
    причиной «Срок хранения — от 1 до 10 лет» у поля `retention_years`; значение и журнал не меняются."""
    admin = sm.as_admin()
    assert _Settings().objects.get(pk=1).retention_years == 3
    for bad in ("0", "11", "abc"):
        response = admin.client.post(SETTINGS_URL, {"retention_years": bad, "confirm": "1"})
        assert response.status_code == 200, f"срок {bad!r}: {response.status_code}"
        errors = _q(_tree(response), data_error="retention_years", data_code="retention_range")
        assert len(errors) == 1, f"срок {bad!r}: ошибок у поля {len(errors)}"
        assert RETENTION_RANGE in errors[0].text(), f"срок {bad!r}: {errors[0].text()!r}"
        assert _Settings().objects.get(pk=1).retention_years == 3, f"срок {bad!r} изменил значение"
    assert _audit("messenger.retention_changed") == [], "отказ не должен писать журнал"


# --- граница срока --------------------------------------------------------------------------------------------

def test_message_three_years_and_one_day_deleted_with_files_and_audit_count(
        protected_root, django_capture_on_commit_callbacks):
    """FR-670, FR-671 (CONTRACT-008, 5.4, 8.1): сообщение старше срока на день удаляется вместе с вложениями,
    строками `StoredFile` и файлами на диске после фиксации; ровно одна запись `messenger.retention_purged` с
    числом удалённых сообщений, без текста переписки."""
    author, friend = sm.make_user(full_name="Автор Срока"), sm.make_user(full_name="Собеседник Срока")
    chat = _chat(author, friend)
    attached = [sm.attach(chat, "старая-схема.png", status="clean", write=True, thumb=True),
                sm.attach(chat, "старый-акт.txt", status="pending", write=True)]
    marker = "Текст-метка-срока"
    message = sm.post(chat, author, text=marker, files=attached, created_at=OLD)

    paths = [path for attachment in attached for path in _attachment_paths(attachment)]
    stored_ids = [attachment.file_id for attachment in attached]
    assert len(paths) == 3 and all(path.exists() for path in paths)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert sm.run_retention(NOW) == 1, "старое сообщение не удалено"
    assert callbacks, "стирание диска должно стоять после фиксации"
    assert all(path.exists() for path in paths), "до фиксации файлы должны остаться"

    assert not _Message().objects.filter(pk=message.pk).exists()
    assert not _Attachment().objects.filter(pk__in=[attachment.pk for attachment in attached]).exists()
    assert not _StoredFile().objects.filter(pk__in=stored_ids).exists()
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in paths), "файлы и эскизы не стёрты с диска"

    rows = _audit(PURGED)
    assert len(rows) == 1, f"записей журнала: {len(rows)}"
    row = rows[0]
    assert (row.object_type, row.object_id, row.actor_id) == ("messenger.settings", "1", None)
    assert row.after == {"messages": 1} and not row.before
    assert marker not in json.dumps([row.before, row.after], ensure_ascii=False)


def test_exactly_three_years_kept():
    """FR-670: граница строгая — `created_at < now − N лет`; сообщение ровно трёхлетней давности остаётся,
    задание ничего не удаляет и журнала не пишет."""
    author, friend = sm.make_user(), sm.make_user()
    chat = _chat(author, friend)
    message = sm.post(chat, author, text="Ровно три года", created_at=BOUNDARY)

    assert sm.run_retention(NOW) == 0, "сообщение ровно на границе удалено"
    assert _Message().objects.filter(pk=message.pk).exists()
    assert _audit(PURGED) == []


def test_second_run_writes_no_audit_and_no_errors():
    """NFR-706 (CONTRACT-008, 5.4): повторный запуск идемпотентен — ничего не находит, не пишет журнал и не падает;
    первая запись `retention_purged` с числом остаётся одна, свежее сообщение цело."""
    author, friend = sm.make_user(), sm.make_user()
    chat = _chat(author, friend)
    first = sm.post(chat, author, text="Старое первое", created_at=OLD)
    second = sm.post(chat, author, text="Старое второе", created_at=OLD - DAY)
    survivor = sm.post(chat, author, text="Свежее", created_at=YOUNG)

    assert sm.run_retention(NOW) == 2
    assert sm.run_retention(NOW) == 0, "повторный запуск что-то удалил"
    assert not _Message().objects.filter(pk__in=[first.pk, second.pk]).exists()
    assert _Message().objects.filter(pk=survivor.pk).exists()
    rows = _audit(PURGED)
    assert len(rows) == 1 and rows[0].after == {"messages": 2}


def test_calendar_boundary_february_29_becomes_28():
    """FR-670 (CONTRACT-008, 5.4): год вычитается заменой года календарно; 29 февраля становится 28 февраля,
    а в високосный год остаётся 29-м."""
    from apps.messenger.services import retention

    leap = datetime(2028, 2, 29, 10, 30, tzinfo=UTC)
    assert retention.boundary(NOW, 3) == BOUNDARY
    assert retention.boundary(leap, 1) == datetime(2027, 2, 28, 10, 30, tzinfo=UTC)
    assert retention.boundary(leap, 3) == datetime(2025, 2, 28, 10, 30, tzinfo=UTC)
    assert retention.boundary(leap, 4) == datetime(2024, 2, 29, 10, 30, tzinfo=UTC)


# --- пачки и пересчёт последнего сообщения ---------------------------------------------------------------------

def test_batches_of_1000_and_last_message_at_recalculated():
    """FR-670 (CONTRACT-008, 5.4): 2 501 старое сообщение удаляются тремя выборками с `LIMIT 1000`;
    `last_message_at` затронутых чатов пересчитывается по оставшимся (свежее сообщение) или становится пустым."""
    author, friend = sm.make_user(), sm.make_user()
    chat = _chat(author, friend, "Чат с пачками")
    young = sm.post(chat, author, text="Свежее сообщение", created_at=YOUNG)

    Message, Chat = _Message(), _Chat()
    Message.objects.bulk_create([
        Message(chat=chat, author=author.user, is_system=False, text="",
                created_at=OLD - timedelta(microseconds=index))
        for index in range(2500)])
    Chat.objects.filter(pk=chat.pk).update(last_message_at=YOUNG)

    empty_chat = _chat(author, friend, "Чат без свежих")
    old = sm.post(empty_chat, author, text="Одно старое", created_at=OLD - DAY)
    Chat.objects.filter(pk=empty_chat.pk).update(last_message_at=old.created_at)

    with sm.capture_sql() as sqls:
        assert sm.run_retention(NOW) == 2501
    selects = [sql for sql in sqls
               if sql.lstrip().upper().startswith("SELECT") and "messenger_message" in sql
               and re.search(r"\bLIMIT\s+1000\b", sql)]
    assert len(selects) == 3, f"выборок пачками по 1000: {len(selects)}"

    assert _Message().objects.filter(chat=chat).count() == 1
    assert _Message().objects.filter(pk=young.pk).exists()
    chat.refresh_from_db()
    assert chat.last_message_at == YOUNG, f"last_message_at: {chat.last_message_at}"
    empty_chat.refresh_from_db()
    assert empty_chat.last_message_at is None, f"пустой чат: {empty_chat.last_message_at}"
    assert [row.after for row in _audit(PURGED)] == [{"messages": 2501}]


# --- непривязанные файлы -------------------------------------------------------------------------------------

def test_unbound_attachment_older_than_24h_removed(protected_root, django_capture_on_commit_callbacks):
    """FR-662, FR-670 (CONTRACT-008, 5.4): непривязанное вложение старше 24 часов удаляется вместе со строкой,
    `StoredFile` и файлами на диске; свежее и привязанное остаются, в число сообщений журнала чистка не входит."""
    author, friend = sm.make_user(), sm.make_user()
    chat = _chat(author, friend)
    stale = sm.attach(chat, "старый-без-сообщения.png", status="clean", write=True, thumb=True)
    fresh = sm.attach(chat, "свежий-без-сообщения.png", status="clean", write=True)
    bound = sm.attach(chat, "привязанный.png", status="clean", write=True)
    survivor = sm.post(chat, author, text="Свежее сообщение", files=[bound], created_at=YOUNG)

    Attachment = _Attachment()
    Attachment.objects.filter(pk=stale.pk).update(uploaded_at=NOW - timedelta(hours=25))
    Attachment.objects.filter(pk=fresh.pk).update(uploaded_at=NOW - timedelta(hours=23))
    Attachment.objects.filter(pk=bound.pk).update(uploaded_at=NOW - timedelta(hours=48))

    stale_paths = _attachment_paths(stale)
    kept_paths = _attachment_paths(fresh) + _attachment_paths(bound)
    with django_capture_on_commit_callbacks(execute=True):
        assert sm.run_retention(NOW) == 0, "чистка непривязанных не входит в число сообщений"
    assert not Attachment.objects.filter(pk=stale.pk).exists()
    assert not _StoredFile().objects.filter(pk=stale.file_id).exists()
    assert not any(path.exists() for path in stale_paths), "файл и эскиз не стёрты"
    assert Attachment.objects.filter(pk__in=[fresh.pk, bound.pk]).count() == 2
    assert all(path.exists() for path in kept_paths)
    assert _Message().objects.filter(pk=survivor.pk).exists()
    assert _audit(PURGED) == []


# --- чаты отдела с исчезнувшим узлом -------------------------------------------------------------------------

def test_department_chat_with_missing_unit_removed_by_night_job(protected_root, django_capture_on_commit_callbacks):
    """FR-650, FR-670 (CONTRACT-008, 2.2, 5.4, 8.1): чат отдела с `unit_id`, которого нет в `org.Unit` (сбой
    обработчика `unit.deleted`), удаляется ночным заданием вместе с сообщениями и файлами; журнал —
    `messenger.unit_chat_deleted` с номером узла, без текста переписки."""
    author = sm.make_user(full_name="Автор Отдела")
    unit = sm.unit("Исчезнувший отдел")
    chat = sm.department_chat(unit)
    attachment = sm.attach(chat, "файл-отдела.png", status="clean", write=True)
    marker = "Текст-метка-отдела"
    message = sm.post(chat, author, text=marker, files=[attachment])
    paths = _attachment_paths(attachment)
    chat_pk, unit_pk, unit_name = chat.pk, unit.pk, unit.name
    stored_id = attachment.file_id

    _Unit().objects.filter(pk=unit_pk).delete()   # обход обработчика шины: чат остался с несуществующим unit_id
    assert not _Unit().objects.filter(pk=unit_pk).exists()
    assert _Chat().objects.filter(pk=chat_pk).exists()

    with django_capture_on_commit_callbacks(execute=True):
        sm.run_retention(NOW)

    assert not _Chat().objects.filter(pk=chat_pk).exists(), "чат отдела с исчезнувшим узлом остался"
    assert not _Message().objects.filter(pk=message.pk).exists()
    assert not _Message().objects.filter(chat_id=chat_pk).exists()
    assert not _Attachment().objects.filter(pk=attachment.pk).exists()
    assert not _StoredFile().objects.filter(pk=stored_id).exists()
    assert not any(path.exists() for path in paths)

    rows = _audit(UNIT_PURGED)
    assert len(rows) == 1, f"записей unit_chat_deleted: {len(rows)}"
    row = rows[0]
    assert row.object_type == "messenger.chat" and row.object_id == str(chat_pk)
    values = _journal_values(row)
    assert int(values.get("unit_id")) == unit_pk
    assert values.get("chat_title") in ("", unit_name), f"chat_title: {values.get('chat_title')!r}"
    assert marker not in json.dumps([row.before, row.after], ensure_ascii=False)


# --- правка и новые сообщения срок не продлевают ---------------------------------------------------------------

def test_retention_not_extended_by_edit():
    """FR-670: `created_at` решает срок — правка старого сообщения (и свежее сообщение в том же чате) его не
    продлевает; старое удаляется, свежее остаётся, журнал считает только удалённое."""
    author, friend = sm.make_user(), sm.make_user()
    chat = _chat(author, friend)
    old = sm.post(chat, author, text="Старого коснулась правка", created_at=OLD,
                  edited_at=NOW - timedelta(hours=1))
    fresh = sm.post(chat, author, text="Свежее рядом", created_at=YOUNG)

    assert sm.run_retention(NOW) == 1
    assert not _Message().objects.filter(pk=old.pk).exists(), "правка продлила срок старому сообщению"
    assert _Message().objects.filter(pk=fresh.pk).exists()
    assert [row.after for row in _audit(PURGED)] == [{"messages": 1}]


# --- расписание -----------------------------------------------------------------------------------------------

def test_cron_entry_55_23_maintenance():
    """FR-670, NFR-706 (CONTRACT-008, 1.2): двадцать первая запись `config/cron.py` —
    `apps.messenger.tasks.retention_night` в очереди `maintenance`, cron «55 23 * * *», `job_timeout=600`, под
    проверкой `apps.is_installed("apps.messenger")`; других записей на эту минуту нет."""
    function, queue, interval, cron, timeout = sm.JOBS_008["messenger_retention"]
    assert (function, queue, interval, cron, timeout) == ("retention_night", "maintenance", None, "55 23 * * *", 600)

    entries = _cron_registrations()
    item = next((entry for entry in entries if entry["name"] == "messenger_retention"), None)
    assert item, "нет задания messenger_retention"
    assert item["target"] == "apps.messenger.tasks.retention_night", f"функция задания: {item['target']}"
    assert item["queue"] == "maintenance"
    assert item["cron"] == "55 23 * * *" and item["interval"] is None
    assert item["job_timeout"] == 600
    assert item["guarded"], "запись messenger_retention вне проверки apps.is_installed"
    assert [entry["name"] for entry in entries if entry["cron"] == "55 23 * * *"] == ["messenger_retention"]