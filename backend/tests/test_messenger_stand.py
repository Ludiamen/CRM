"""T-8123: сброс стенда `messenger` и команда стенда `e2e_messenger_age` (FR-651, FR-662, FR-670).

План: «Проверка» → «данные установки и стенд» (миграция создаёт `MessengerSettings(3, включён)` и «Общий чат»;
повторный запуск ничего не дублирует; `stand_reset` возвращает срок 3, включает общий чат, стирает чаты, сообщения,
файлы и эскизы). CONTRACT-008: 1.3 (точка `stand_reset` модуля `messenger`: транзакция, таблицы, файлы,
восстановление, порядок, `require_stand`; решения контракта К4 и К8), 2.2-2.3 (модели и данные установки), 14.1
(команда `e2e_messenger_age`: проверка стенда первой строкой, сдвиг `Message.created_at`, строка
`messenger_age: aged=<N>`), 15.1 (место `messenger` в точке `stand_reset`).

Сброс проверяется прямым вызовом `apps.messenger.stand.stand_reset()` (команда `e2e_reset_stand` здесь не
запускается: она чистит все таблицы ядра); данные сброса создаются и читаются через соединение `migrate`, как в
`test_feed_stand.py` и `test_lists_stand.py` (у соединений разные транзакции, поэтому фабрики `support_messenger`,
пишущие через `default`, здесь не годятся — временные помощники внутри файла). Всё, что идёт «после фиксации»
(стирание файлов и эскизов с диска), проверяется внутри `django_capture_on_commit_callbacks(execute=True)`. Том
`protected` — временный каталог фикстуры `protected_root`. Команда `e2e_messenger_age` работает на соединении
`default`; время ставит фикстура `clock`. Код среза импортируется внутри функций: сбор (`pytest --collect-only`)
проходит до появления моделей, миграций и `stand_reset` Этапа 3.
"""
import contextlib
import re
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.models.signals import post_save
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support
from tests import support_messenger as sm

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
AGE_LINE = re.compile(r"messenger_age: aged=(\d+)\n")
GENERAL_TITLE = "Общий чат"


# --- помощники сброса (свои: фабрики support_messenger пишут через `default`) --------------------------------------

def _on(label: str):
    return support.model(label).objects.using("migrate")


def _person(name: str):
    """Сотрудник, созданный через `migrate` (на `default` строка не видна: у соединений разные транзакции)."""
    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name=name, state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _stored(status: str, data: bytes, *, purpose: str = "messenger", write: bool = True):
    """`StoredFile` через `migrate` и путь его файла на диске (`incoming/`, `attachments/`, `quarantine/`)."""
    from apps.core.services import files as core_files

    stored = _on("core.StoredFile").create(
        purpose=purpose, owner=None, size=len(data), sha256="0" * 64, content_type="application/octet-stream",
        status=status, scanned_at=timezone.now() if status != "pending" else None)
    path = core_files.attachment_path(stored)  # путь зависит от состояния проверки
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return stored, path


def _attachment(stored, name: str, uploaded_by, *, message=None, thumb: str = ""):
    return _on("messenger.MessageAttachment").create(message=message, file=stored, name=name, thumb=thumb,
                                                     uploaded_by=uploaded_by, uploaded_at=timezone.now())


def _stand_data(author, reader, protected_root) -> dict:
    """По одной строке во всех таблицах `messenger` через `migrate`: личный диалог с участниками и отметкой прочтения,
    групповой чат, чат отдела с системной записью, сообщения с цитатой, настройка со сроком 7 лет и выключенным общим
    чатом, четыре вложения во всех состояниях проверки (одно — без файла на диске, у одного — эскиз).

    `kept` — файлы других назначений (`attachment`, `knowledge`), `stray` — эскиз другого среза в общем каталоге
    `attachments/thumbs/`, `neighbour` — файл вне каталога эскизов: сброс не трогает ни их, ни сам каталог (К4)."""
    now = timezone.now()
    Chat, ChatMember, ChatRead = (_on(f"messenger.{name}") for name in ("Chat", "ChatMember", "ChatRead"))
    Message = _on("messenger.Message")
    low, high = sorted((author.pk, reader.pk))
    personal = Chat.create(kind="personal", title="", pair_key=f"{low}:{high}", created_by=author, created_at=now,
                           last_message_at=now)
    ChatMember.create(chat=personal, user=author, is_creator=True, joined_at=now)
    ChatMember.create(chat=personal, user=reader, is_creator=False, joined_at=now)
    ChatRead.create(chat=personal, user=reader, last_read_at=now)
    group = Chat.create(kind="group", title="Группа стенда", created_by=author, created_at=now)
    ChatMember.create(chat=group, user=author, is_creator=True, joined_at=now)
    department = Chat.create(kind="department", title="", unit_id=424242, created_at=now, last_message_at=now)
    Message.create(chat=department, author=None, is_system=True, text="Создал чат", created_at=now)
    first = Message.create(chat=personal, author=author, is_system=False, text="Сообщение стенда", created_at=now)
    Message.create(chat=personal, author=reader, is_system=False, text="Ответ с цитатой", quote=first,
                   created_at=now)
    _on("messenger.MessengerSettings").filter(pk=1).update(
        retention_years=7, general_chat_enabled=False, updated_by=author, updated_at=now)

    files = []
    plan = (("pending", "счёт.txt", b"pending body", True), ("clean", "схема.png", b"clean body", True),
            ("quarantine", "образец.txt", b"quarantine body", True), ("clean", "без файла.txt", b"ghost", False))
    for status, name, body, write in plan:
        stored, path = _stored(status, body, write=write)
        thumb = ""
        thumb_path = None
        if name == "схема.png":
            thumb = f"attachments/thumbs/{stored.pk}.jpg"
            thumb_path = protected_root / thumb
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(b"thumb of the schema")
        row = _attachment(stored, name, author, thumb=thumb)
        files.append({"stored": stored, "path": path, "write": write, "thumb": thumb_path, "row": row})

    kept = []
    for purpose in ("attachment", "knowledge"):
        stored, path = _stored("clean", purpose.encode(), purpose=purpose)
        kept.append({"stored": stored, "path": path, "body": purpose.encode()})
    stray = protected_root / "attachments" / "thumbs" / "999999.jpg"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"thumb of another slice")
    neighbour = protected_root / "attachments" / "other-slice-file"
    neighbour.parent.mkdir(parents=True, exist_ok=True)
    neighbour.write_bytes(b"original of another module")

    return {"personal": personal, "group": group, "department": department, "files": files, "kept": kept,
            "stray": stray, "neighbour": neighbour}


@contextlib.contextmanager
def _commit_callbacks(capture):
    """После фиксации: исполняет `on_commit` обоих соединений; алиас стирания файлов (`migrate`, К-9 CONTRACT-006)
    проверяет тест стирания файлов."""
    with capture(using="default", execute=True) as on_default, \
            capture(using="migrate", execute=True) as on_migrate:
        yield on_default, on_migrate


def _counts(*labels: str) -> dict[str, int]:
    return {label: _on(f"messenger.{label}").count() for label in labels}


def _row_state() -> tuple[list, list]:
    """Снимок данных установки: строки настройки (номер, значения) и «Общий чат» (название и прочие поля)."""
    settings_rows = list(_on("messenger.MessengerSettings").order_by("pk").values_list(
        "pk", "retention_years", "general_chat_enabled", "updated_by_id", "updated_at"))
    general_rows = list(_on("messenger.Chat").filter(kind="general").order_by("pk").values_list(
        "title", "created_by_id", "unit_id", "pair_key"))
    return settings_rows, general_rows


# --- сброс стенда (прямой вызов функции точки, контракт 1.3) -------------------------------------------------------

@MIGRATE
def test_stand_reset_returns_retention_and_general_on(protected_root, django_capture_on_commit_callbacks):
    """FR-651, FR-670: после сброса — срок хранения 3 года, общий чат включён, `updated_by`/`updated_at` пусты (правку
    администратора 7 лет и выключение сброс не сохраняет); «Общий чат» (`kind="general"`, название «Общий чат») снова
    есть, даже если общий сброс ядра стёр его строку; повторный запуск даёт то же состояние и ничего не дублирует
    (раздел 1.3, «Восстановление»; 2.3)."""
    from apps.messenger.stand import stand_reset

    author = _person("Администратор Стенда")
    _on("messenger.MessengerSettings").filter(pk=1).update(
        retention_years=7, general_chat_enabled=False, updated_by=author, updated_at=timezone.now())
    _on("messenger.Chat").filter(kind="general").delete()
    assert _on("messenger.MessengerSettings").get(pk=1).retention_years == 7
    assert not _on("messenger.Chat").filter(kind="general").exists(), "тест не стёр «Общий чат»"

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    settings_rows, general_rows = _row_state()
    assert settings_rows == [(1, 3, True, None, None)], settings_rows
    assert general_rows == [(GENERAL_TITLE, None, None, "")], general_rows
    first = _counts("Chat", "ChatMember", "ChatRead", "Message", "MessageAttachment", "MessengerSettings")
    assert first == {"Chat": 1, "ChatMember": 0, "ChatRead": 0, "Message": 0, "MessageAttachment": 0,
                     "MessengerSettings": 1}, first

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    assert _row_state() == (settings_rows, general_rows), "повторный сброс изменил данные установки"
    assert _counts("Chat", "ChatMember", "ChatRead", "Message", "MessageAttachment", "MessengerSettings") == first, \
        "повторный сброс задвоил строки"


@MIGRATE
def test_stand_reset_wipes_chats_messages_files_and_thumbs_after_commit(
        protected_root, django_capture_on_commit_callbacks):
    """FR-662: стираются все строки таблиц `messenger` (личный, групповой и отдельский чаты, участники, отметки
    прочтения, сообщения с цитатой и системная запись, настройка — и создаётся заново) и `core.StoredFile` назначения
    «messenger» вместе со всеми вложениями; файлы оригиналов во всех состояниях проверки и эскиз стираются с диска
    только после фиксации (`on_commit` соединения `migrate`), а каталог `attachments/thumbs/` целиком не стирается:
    эскиз другого среза остаётся (К4); файлы других назначений и файл соседнего модуля не тронуты; сотрудники и роли
    остаются (раздел 1.3, «Таблицы» и «Файлы»)."""
    from apps.messenger.stand import stand_reset

    author, reader = _person("Автор Стенда"), _person("Читатель Стенда")
    data = _stand_data(author, reader, protected_root)
    assert _counts("Chat", "ChatMember", "ChatRead", "Message", "MessageAttachment") == {
        "Chat": 4, "ChatMember": 3, "ChatRead": 1, "Message": 3, "MessageAttachment": 4}
    assert [item["path"].exists() for item in data["files"]] == [True, True, True, False]
    assert data["files"][1]["thumb"].exists()

    with _commit_callbacks(django_capture_on_commit_callbacks) as (on_default, on_migrate):
        stand_reset()
        assert _counts("Chat", "ChatMember", "ChatRead", "Message", "MessageAttachment") == {
            "Chat": 1, "ChatMember": 0, "ChatRead": 0, "Message": 0, "MessageAttachment": 0}, \
            "после сброса остались строки мессенджера (чат остаётся только «Общий чат»)"
        assert not _on("core.StoredFile").filter(purpose="messenger").exists(), "StoredFile мессенджера остался"
        for item in data["files"]:
            assert item["path"].exists() == item["write"], "файл на диске тронут до фиксации"
        assert data["files"][1]["thumb"].exists(), "эскиз стёрт до фиксации"
    assert on_migrate, "стирание файлов с диска не поставлено в on_commit соединения migrate"

    for item in data["files"]:
        assert not item["path"].exists(), f"файл мессенджера остался на диске: {item['row'].name}"
        if item["thumb"] is not None:
            assert not item["thumb"].exists(), "эскиз вложения остался на диске"
    assert data["stray"].exists(), "каталог attachments/thumbs/ стёрт целиком (в нём эскизы других срезов)"
    assert data["neighbour"].read_bytes() == b"original of another module", "тронут файл вне каталога эскизов"
    for kept in data["kept"]:
        assert _on("core.StoredFile").filter(pk=kept["stored"].pk).exists(), f"StoredFile {kept['body']!r} стёрт"
        assert kept["path"].read_bytes() == kept["body"], f"файл {kept['body']!r} тронут"

    assert _on("core.User").filter(pk__in=[author.pk, reader.pk]).count() == 2, "сотрудник стёрт"
    assert _on("core.Role").filter(is_builtin=True).count() >= 3, "роли стёрты (их стирает команда e2e_reset_stand)"
    settings_rows, general_rows = _row_state()
    assert settings_rows == [(1, 3, True, None, None)] and general_rows == [(GENERAL_TITLE, None, None, "")], \
        "сброс не вернул данные установки"


@MIGRATE
def test_stand_reset_runs_in_migration_transaction(protected_root, django_capture_on_commit_callbacks):
    """FR-670: всё стирание и `seed(stand=True)` идут под алиасом `migrate` в одной `transaction.atomic`: в SQL
    соединения `migrate` стоит `SAVEPOINT` (вложенная в тестовую транзакцию `atomic`) раньше первого `DELETE` строк
    мессенджера и `RELEASE SAVEPOINT` позже последнего `DELETE`/`INSERT`, откатов нет; на соединении `default` нет ни
    одного запроса к таблицам мессенджера и `core_storedfile` (раздел 1.3, «Транзакция»)."""
    from apps.messenger.stand import stand_reset

    _stand_data(_person("Автор Стенда"), _person("Читатель Стенда"), protected_root)
    with CaptureQueriesContext(connections["migrate"]) as migrate_log, \
            CaptureQueriesContext(connections["default"]) as default_log:
        with _commit_callbacks(django_capture_on_commit_callbacks):
            stand_reset()
    sqls = [query["sql"] for query in migrate_log.captured_queries]
    deletes = [i for i, sql in enumerate(sqls) if sql.startswith("DELETE FROM") and "messenger_" in sql]
    inserts = [i for i, sql in enumerate(sqls) if sql.startswith("INSERT INTO") and "messenger_" in sql]
    assert deletes, "сброс ничего не стёр на соединении migrate"
    assert inserts, "seed не создал данные установки на соединении migrate"
    opened = [i for i, sql in enumerate(sqls) if sql.startswith("SAVEPOINT")]
    released = [i for i, sql in enumerate(sqls) if sql.startswith("RELEASE SAVEPOINT")]
    assert opened and released, "стирание и seed не завёрнуты в transaction.atomic(using=migrate)"
    assert opened[0] < deletes[0], "первое стирание раньше входа в транзакцию"
    writes = [i for i, sql in enumerate(sqls) if sql.startswith(("DELETE FROM", "INSERT INTO"))]
    assert released[-1] > max(writes), "стирание или seed выполнены после выхода из транзакции"
    assert not [sql for sql in sqls if sql.startswith("ROLLBACK")], "сброс откатывался"
    on_default = [query["sql"] for query in default_log.captured_queries
                  if "messenger_" in query["sql"] or "core_storedfile" in query["sql"]]
    assert not on_default, f"запросы к таблицам сброса на соединении default: {on_default[:2]}"


# --- порядок регистрации точки (раздел 1.3, «Порядок»; 15.1) -------------------------------------------------------

def test_stand_reset_runs_last_and_before_feed():
    """FR-651: в точке `stand_reset` функция `apps.messenger.stand.stand_reset` зарегистрирована ровно один раз и
    последней, сразу после `apps.feed.stand.stand_reset`; команда `e2e_reset_stand` зовёт функции в обратном порядке,
    поэтому мессенджер стирается первым, лента — второй (К8; раздел 1.3)."""
    from apps.core import extensions
    from apps.messenger.stand import stand_reset

    registered = list(extensions.registered("stand_reset"))
    names = [func.__module__ for func in registered]
    assert registered.count(stand_reset) == 1, "stand_reset модуля messenger не зарегистрирован ровно один раз"
    assert registered[-1] is stand_reset, "stand_reset модуля messenger не последний"
    assert names[-2] == "apps.feed.stand", f"перед messenger стоит {names[-2]}, а не feed"
    call_order = [func.__module__ for func in reversed(registered)]
    assert call_order[0] == "apps.messenger.stand", "messenger вызывается не первым"
    assert call_order[1] == "apps.feed.stand", "feed вызывается не вторым"


# --- команда e2e_messenger_age (контракт 14.1) --------------------------------------------------------------------

def _age(*args) -> str:
    out = StringIO()
    call_command("e2e_messenger_age", *args, stdout=out)
    return out.getvalue()


@contextlib.contextmanager
def _message_saves():
    """Считает `post_save` модели `Message`: сдвиг прямой записью (`update`) его не шлёт, `save()` — шлёт."""
    Message = support.model("messenger.Message")
    calls = []

    def receiver(sender, instance, **kwargs):
        calls.append(instance.pk)

    post_save.connect(receiver, sender=Message, weak=False, dispatch_uid="t8123-message-save-spy")
    try:
        yield calls
    finally:
        post_save.disconnect(sender=Message, dispatch_uid="t8123-message-save-spy")


def _messages(chat) -> dict:
    """Состояние сообщений чата: время создания, текст, автор и системность."""
    return {row.pk: row for row in support.model("messenger.Message").objects.filter(chat=chat)}


def _age_data(clock) -> dict:
    """Сейчас 2026-03-10 12:00 (Москва): личный диалог, два сообщения, сообщение с вложением и системная запись —
    четыре строки `Message` с одним временем создания."""
    clock.set(sm.moscow(2026, 3, 10, 12))
    author, reader = sm.make_user(), sm.make_user()
    chat = sm.personal(author, reader)
    attachment = sm.attach(chat, "схема.png", uploaded_by=author)
    written = [sm.post(chat, author, "Первое"), sm.post(chat, reader, "Второе"),
               sm.post(chat, author, "С файлом", files=[attachment])]
    system = support.model("messenger.Message").objects.create(
        chat=chat, author=None, is_system=True, text="Создал чат", created_at=timezone.now())
    return {"author": author, "reader": reader, "chat": chat, "messages": written + [system]}


@PLAIN
def test_e2e_messenger_age_shifts_by_days_and_prints_line(monkeypatch, clock):
    """FR-670: `e2e_messenger_age --days N` сдвигает `created_at` всех сообщений (двух обычных, сообщения с вложением и
    системной записи) ровно на N суток раньше прямой записью, без `save()`; текст, автор и признак системности
    прежние, `Chat.last_message_at` не пересчитывается (службы не вызываются); вывод — ровно одна строка
    `messenger_age: aged=<сообщений>` (раздел 14.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _age_data(clock)
    before = _messages(data["chat"])
    assert len(before) == 4, "тест создал не четыре сообщения"
    chat_before = support.model("messenger.Chat").objects.get(pk=data["chat"].pk)

    with _message_saves() as saved:
        text = _age("--days", "30")

    assert saved == [], "команда звала save() модели Message"
    assert AGE_LINE.fullmatch(text), repr(text)
    assert AGE_LINE.fullmatch(text).group(1) == "4", text
    after = _messages(data["chat"])
    assert set(after) == set(before), "набор сообщений изменился"
    for pk, was in before.items():
        moved = after[pk]
        assert moved.created_at == was.created_at - timedelta(days=30), f"сообщение {pk} не состарено"
        assert (moved.text, moved.author_id, moved.is_system) == (was.text, was.author_id, was.is_system), pk
    chat_after = support.model("messenger.Chat").objects.get(pk=data["chat"].pk)
    assert chat_after.last_message_at == chat_before.last_message_at, "команда пересчитала last_message_at"

    text = _age("--days", "1")

    assert AGE_LINE.fullmatch(text).group(1) == "4", text
    for pk, was in before.items():
        assert _messages(data["chat"])[pk].created_at == was.created_at - timedelta(days=31), pk


@PLAIN
def test_stand_command_refused_without_e2e_stand(monkeypatch, clock, django_assert_num_queries):
    """FR-670: `require_stand()` модуля `stand` без `E2E_STAND=1` (нет переменной, «0», пусто) бросает
    `CommandError(REFUSAL)` раньше любого запроса к базе, и команда `e2e_messenger_age` тоже (проверка стенда —
    первая строка `handle`, даже при `--days 1`): `created_at` сообщений не меняется; с `E2E_STAND=1`
    `require_stand()` не бросает; `REFUSAL` — текст контракта (разделы 1.3, 14.1)."""
    from apps.messenger import stand

    assert stand.REFUSAL == REFUSAL
    data = _age_data(clock)
    before = {pk: row.created_at for pk, row in _messages(data["chat"]).items()}
    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                stand.require_stand()
        assert str(refused.value) == REFUSAL, repr(value)
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                _age("--days", "1")
        assert str(refused.value) == REFUSAL, repr(value)
    assert {pk: row.created_at for pk, row in _messages(data["chat"]).items()} == before, \
        "отказавшая команда сдвинула сообщения"
    monkeypatch.setenv("E2E_STAND", "1")
    assert stand.require_stand() is None