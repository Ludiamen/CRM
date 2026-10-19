"""T-5123: склейка уведомлений в `notify.dispatch.create` (FR-435). Сценарий 5 («Уведомления») спеки среза 005.

Вид с `coalesce=True`: пока у получателя есть непрочитанное уведомление того же вида по тому же `object_ref`, новое
не создаётся (нет записи, доставок и всплывающего окна); перед циклом черновиков берутся транзакционные замки
`pg_advisory_xact_lock(hashtextextended('<user_id>:<код вида>:<object_ref>', 0))` по возрастанию строки ключа
(CONTRACT-005, 4.1, 3.2, 7.2; раздел 16 «Поправка к решению 18» — гонки без потоков). Тестовый вид регистрируется
внутри `extensions.empty()` помощником `support_notify.register_kind`; «прочитано» по статье — настоящий вид
`knowledge.comment_on_my_article` и настоящее событие `object.viewed`. Код среза на уровне модуля не импортируется.
"""
import datetime
import logging
import re
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests import support_kb as kb
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
WORK = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=MSK)         # среда, рабочее время
KIND = "test.coalesced"
PLAIN_KIND = "test.plain"
REF = "knowledge.article:15"
OTHER_REF = "knowledge.article:16"
LOCK_SQL = "pg_advisory_xact_lock"
OTHER_TEXT = "1:test.coalesced:knowledge.article:16"


# --- помощники только этого файла ------------------------------------------------------------------------

@pytest.fixture
def env(bus, clock):
    """Каталог видов и подписки шины пусты, часы стоят в рабочем времени."""
    from apps.core import extensions

    with extensions.empty():
        clock.set(WORK)
        yield bus


def _register(*, code=KIND, coalesce=True, channels=("portal", "email")):
    """Тестовый вид; `coalesce=False` — вид без поля (прежний вызов с именованными аргументами)."""
    from apps.core.extensions import NotificationKind

    extra = {"coalesce": True} if coalesce else {}
    kind = NotificationKind(code=code, title="Тестовый вид", module="test", events=("test.happened",),
                            external_text="Есть новое", default_channels=tuple(channels), **extra)
    notify.register_kind(kind)
    return kind


def _draft(user, ref: str = REF, text: str = "Событие"):
    from apps.core.extensions import Draft

    return Draft(user_id=user.pk, text=text, url="/test/", object_ref=ref)


def _create(capture, code: str, drafts) -> list[int]:
    """`dispatch.create` внутри `capture(execute=True)`: рассылка после фиксации выполняется."""
    from apps.notify.services import dispatch

    with capture(execute=True):
        return dispatch.create(code, drafts)


def _notes(user=None, kind=None):
    rows = model("notify.Notification").objects.all()
    if user is not None:
        rows = rows.filter(user=user)
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _deliveries(user=None):
    rows = model("notify.Delivery").objects.all()
    return rows.filter(notification__user=user) if user is not None else rows


def _read(note) -> None:
    """«Прочитано» по определению контракта 4.1: `read_at` не пусто."""
    model("notify.Notification").objects.filter(pk=note.pk).update(read_at=WORK)


def _no_bus_errors(caplog) -> None:
    bad = [r.getMessage() for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, bad


def _lock_statements(sqls) -> list[int]:
    """Номера запросов, в которых есть вызов замка."""
    return [i for i, sql in enumerate(sqls) if LOCK_SQL in sql]


def _notification_inserts(sqls) -> list[int]:
    return [i for i, sql in enumerate(sqls) if re.search(r'INSERT INTO "?notify_notification"?\b', sql)]


def _locks_found(sqls):
    """Замки по помощнику `support_kb.advisory_locks`; если запрос с замком есть, а помощник его не прочёл
    (например, параметры не подставлены) — отказ с текстом запроса."""
    found = kb.advisory_locks(sqls)
    if not found and _lock_statements(sqls):
        pytest.fail("помощник advisory_locks не прочёл замок; запрос: " + sqls[_lock_statements(sqls)[0]][:200])
    return found


# --- пропуск при непрочитанном ---------------------------------------------------------------------------

def test_coalesce_kind_skips_new_notification_while_same_kind_same_object_unread(env, django_capture_on_commit_callbacks,
                                                                                caplog):
    """FR-435: у получателя есть непрочитанное того же вида по тому же объекту — нового нет: нет записи, номера в
    списке, получатель не в `recipients` (число непрочитанного прежнее); получатель без записи в том же вызове
    получает уведомление как обычно."""
    from apps.notify.services import reading

    _register()
    holder, fresh = support.make_employee(), support.make_employee()
    first = _create(django_capture_on_commit_callbacks, KIND, [_draft(holder, text="Первое")])
    assert len(first) == 1
    created = _create(django_capture_on_commit_callbacks, KIND,
                      [_draft(holder, text="Второе"), _draft(fresh, text="Второе")])
    fresh_note = _notes(fresh).get()
    assert created == [fresh_note.pk]
    assert fresh_note.text == "Второе" and fresh_note.object_ref == REF
    held = list(_notes(holder))
    assert [row.pk for row in held] == first
    assert held[0].text == "Первое" and held[0].read_at is None
    assert reading.unread_count(holder.pk) == 1
    assert _create(django_capture_on_commit_callbacks, KIND, [_draft(holder, text="Третье")]) == []
    assert _notes(holder).count() == 1
    _no_bus_errors(caplog)


def test_coalesce_skip_creates_no_deliveries_and_no_popup(env, django_capture_on_commit_callbacks):
    """FR-435: пропущенный черновик не даёт доставок и всплывающего окна: после второго вызова доставок прежнее
    число, заданий нет, кадра в группу получателя не уходит (после первого вызова кадр был)."""
    from apps.notify.services import reading

    _register(channels=("portal", "email"))
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        await conn.receive()                                    # кадр с числом при подключении
        first = await hub.do(_create, django_capture_on_commit_callbacks, KIND, [_draft(user, text="Первое")])
        assert len(first) == 1
        frame = await conn.receive()
        assert frame is not None, "после первого уведомления кадра нет"
        assert notify.ws_fragments(frame)["notify-count"].attrs["data-count"] == "1"
        before = await hub.do(lambda: sorted(_deliveries(user).values_list("pk", "channel", "state")))
        assert before and {channel for _, channel, _ in before} == {"email"}
        second = await hub.do(_create, django_capture_on_commit_callbacks, KIND, [_draft(user, text="Второе")])
        assert second == []
        assert await conn.receive(timeout=1.0) is None, "кадр о пропущенном уведомлении ушёл"
        after = await hub.do(lambda: sorted(_deliveries(user).values_list("pk", "channel", "state")))
        assert after == before

    notify.ws_run(scenario)
    assert _notes(user).count() == 1
    assert reading.unread_count(user.pk) == 1
    assert notify.queued() == []


def test_coalesce_kind_creates_notification_after_previous_was_read(env, django_capture_on_commit_callbacks):
    """FR-435: после прочтения (`read_at` не пусто) следующее событие создаёт новую запись и доставки."""
    _register()
    user = support.make_employee()
    first = _create(django_capture_on_commit_callbacks, KIND, [_draft(user, text="Первое")])
    assert len(first) == 1
    assert _create(django_capture_on_commit_callbacks, KIND, [_draft(user, text="Второе")]) == []
    _read(_notes(user).get())
    second = _create(django_capture_on_commit_callbacks, KIND, [_draft(user, text="Третье")])
    assert len(second) == 1 and second != first
    rows = {row.pk: row for row in _notes(user)}
    assert set(rows) == {first[0], second[0]}
    assert rows[first[0]].read_at is not None and rows[second[0]].read_at is None
    assert rows[second[0]].text == "Третье" and rows[second[0]].object_ref == REF
    assert _deliveries(user).filter(notification_id=second[0]).count() == 1
    assert _create(django_capture_on_commit_callbacks, KIND, [_draft(user, text="Четвёртое")]) == []
    assert _notes(user).count() == 2


def test_coalesce_is_per_object_and_per_recipient(env, django_capture_on_commit_callbacks):
    """FR-435: склейка отдельно по получателю и по `object_ref`: другой получатель или другой объект при том же виде —
    запись создаётся; повтор у того же получателя по тому же объекту — нет."""
    _register()
    one, two = support.make_employee(), support.make_employee()
    assert len(_create(django_capture_on_commit_callbacks, KIND, [_draft(one, REF)])) == 1
    assert len(_create(django_capture_on_commit_callbacks, KIND, [_draft(two, REF)])) == 1
    assert len(_create(django_capture_on_commit_callbacks, KIND, [_draft(one, OTHER_REF)])) == 1
    assert _create(django_capture_on_commit_callbacks, KIND, [_draft(one, REF), _draft(two, REF)]) == []
    assert _create(django_capture_on_commit_callbacks, KIND, [_draft(one, OTHER_REF)]) == []
    assert sorted(_notes(one).values_list("object_ref", flat=True)) == [REF, OTHER_REF]
    assert list(_notes(two).values_list("object_ref", flat=True)) == [REF]


def test_object_viewed_for_article_marks_unread_notification_read(django_capture_on_commit_callbacks):
    """FR-435: показ статьи (`object.viewed` с `knowledge.article:<id>`) отмечает непрочитанное уведомление
    получателя; после этого новый комментарий создаёт новую запись; просмотр другим сотрудником ничего не меняет."""
    from apps.core import events
    from apps.notify.services import reading

    code = "knowledge.comment_on_my_article"
    article = kb.make_published()
    author, stranger = article.author, support.make_employee()
    ref = f"knowledge.article:{article.pk}"
    first = _create(django_capture_on_commit_callbacks, code, [_draft(author, ref, "Комментарий")])
    assert len(first) == 1
    assert _create(django_capture_on_commit_callbacks, code, [_draft(author, ref, "Ещё")]) == []
    with django_capture_on_commit_callbacks(execute=True):
        events.publish("object.viewed", object_ref=ref, user_id=stranger.pk)
    assert reading.unread_count(author.pk) == 1
    with django_capture_on_commit_callbacks(execute=True):
        events.publish("object.viewed", object_ref=ref, user_id=author.pk)
    assert reading.unread_count(author.pk) == 0
    assert _notes(author).get().read_at is not None
    second = _create(django_capture_on_commit_callbacks, code, [_draft(author, ref, "После прочтения")])
    assert len(second) == 1 and second != first
    assert reading.unread_count(author.pk) == 1


# --- замки (гонки без потоков) ---------------------------------------------------------------------------

def test_two_simultaneous_events_create_single_notification(env, django_capture_on_commit_callbacks):
    """FR-435: два события об одной статье дают одно уведомление. Механизм: проверка «есть непрочитанное» идёт под
    замком ключа `<user_id>:<код>:<object_ref>`, взятым до первой записи `Notification`; второй вызов (который при
    гонке ждал бы замок) видит запись первого и ничего не создаёт."""
    from apps.notify.services import dispatch

    _register()
    user = support.make_employee()
    lock_text = f"{user.pk}:{KIND}:{REF}"

    def call(text):
        with django_capture_on_commit_callbacks(execute=True):
            return dispatch.create(KIND, [_draft(user, text=text)])

    first_sqls = kb.sql_of(call, "Первое")
    first_ids = list(_notes(user).values_list("pk", flat=True))
    second_sqls = kb.sql_of(call, "Второе")
    assert len(first_ids) == 1
    assert _notes(user).count() == 1
    assert [(lock.kind, lock.key) for lock in _locks_found(first_sqls)] == [("exclusive", lock_text)]
    assert [(lock.kind, lock.key) for lock in _locks_found(second_sqls)] == [("exclusive", lock_text)]
    assert _locks_found(first_sqls)[0].key == dispatch.coalesce_key(user.pk, KIND, REF)
    inserts = _notification_inserts(first_sqls)
    assert len(inserts) == 1
    assert _lock_statements(first_sqls)[-1] < inserts[0], "замок взят после записи уведомления"
    assert _notification_inserts(second_sqls) == []


def test_opposite_recipient_order_in_two_events_does_not_deadlock_and_both_handled(env,
                                                                                  django_capture_on_commit_callbacks):
    """FR-435: два события с получателями в противоположном порядке берут замки в одном порядке — по возрастанию
    строки ключа, одним проходом до первой записи, — поэтому взаимной блокировки нет; обе обработки завершаются,
    у каждого получателя ровно одно уведомление."""
    from apps.notify.services import dispatch

    _register()
    one, two, three = (support.make_employee() for _ in range(3))

    def call(*users):
        with django_capture_on_commit_callbacks(execute=True):
            return dispatch.create(KIND, [_draft(user) for user in users])

    expected = sorted(f"{user.pk}:{KIND}:{REF}" for user in (one, two, three))
    first_sqls = kb.sql_of(call, one, three, two)
    second_sqls = kb.sql_of(call, two, three, one)
    first_locks, second_locks = _locks_found(first_sqls), _locks_found(second_sqls)
    assert [lock.key for lock in first_locks] == expected
    assert [lock.key for lock in second_locks] == expected
    assert {lock.kind for lock in first_locks + second_locks} == {"exclusive"}
    inserts = _notification_inserts(first_sqls)
    assert len(inserts) == 3
    assert _lock_statements(first_sqls)[-1] < inserts[0], "замки взяты не одним проходом до первой записи"
    for user in (one, two, three):
        assert _notes(user).count() == 1, user.pk
    assert _notification_inserts(second_sqls) == []


def test_lock_key_uses_hashtextextended_and_is_equal_across_processes(env, django_capture_on_commit_callbacks):
    """FR-435: замок — `SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))` с ключом `<user_id>:<код>:<object_ref>`
    единственным параметром; хэш считает база, поэтому в двух разных соединениях ключ даёт одно число
    (в отличие от `hash()` Python)."""
    from django.db import connection

    from apps.notify.services import dispatch

    _register()
    user = support.make_employee()
    expected_text = f"{user.pk}:{KIND}:{REF}"

    def call():
        with django_capture_on_commit_callbacks(execute=True):
            return dispatch.create(KIND, [_draft(user)])

    sqls = kb.sql_of(call)
    locks = _locks_found(sqls)
    assert len(locks) == 1
    assert locks[0].kind == "exclusive"
    lock_text = locks[0].key
    assert lock_text == expected_text == dispatch.coalesce_key(user.pk, KIND, REF)
    statement = re.fullmatch(r"SELECT pg_advisory_xact_lock\(hashtextextended\('(.*)', 0\)\)", sqls[_lock_statements(sqls)[0]])
    assert statement is not None and statement.group(1) == lock_text
    assert not any("pg_advisory_lock" in sql.replace(LOCK_SQL, "") for sql in sqls), "замок не транзакционный"

    query = "SELECT hashtextextended(%s, 0)"
    with connection.cursor() as cursor:
        cursor.execute(query, [lock_text])
        here = cursor.fetchone()[0]
    other = connection.copy()
    try:
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            other_pid = cursor.fetchone()[0]
            cursor.execute(query, [lock_text])
            there = cursor.fetchone()[0]
    finally:
        other.close()
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        assert cursor.fetchone()[0] != other_pid, "второе соединение — тот же процесс базы"
        cursor.execute(query, [OTHER_TEXT])
        different = cursor.fetchone()[0]
    assert here == there
    assert here != different


# --- виды без склейки и порядок ---------------------------------------------------------------------------

def test_kinds_without_coalesce_create_two_records_for_two_events(env, django_capture_on_commit_callbacks):
    """FR-435: вид без `coalesce` (по умолчанию ложь) работает как в срезе 004: два события — две записи и две
    доставки у получателя, замков нет."""
    from apps.core.extensions import NotificationKind

    assert NotificationKind(code="x", title="x", module="x").coalesce is False
    _register(code=PLAIN_KIND, coalesce=False)
    user = support.make_employee()

    def two_calls():
        first = _create(django_capture_on_commit_callbacks, PLAIN_KIND, [_draft(user, text="Первое")])
        second = _create(django_capture_on_commit_callbacks, PLAIN_KIND, [_draft(user, text="Второе")])
        return first, second

    with kb.capture_sql() as sqls:
        first, second = two_calls()
    assert len(first) == 1 and len(second) == 1 and first != second
    assert [row.pk for row in _notes(user).order_by("pk")] == first + second
    assert _deliveries(user).count() == 2
    assert kb.advisory_locks(sqls) == []
    assert not _lock_statements(sqls)


def test_records_and_deliveries_keep_drafts_order_with_coalesce_enabled(env, django_capture_on_commit_callbacks):
    """FR-435: при включённой склейке записи и доставки идут в порядке черновиков (не в порядке замков и не по
    номеру получателя); пропущенный черновик из порядка выпадает."""
    _register()
    users = [support.make_employee() for _ in range(5)]
    skipped = users[3]
    assert len(_create(django_capture_on_commit_callbacks, KIND, [_draft(skipped, text="Прежнее")])) == 1
    order = [users[4], users[1], skipped, users[2], users[0]]
    created = _create(django_capture_on_commit_callbacks, KIND, [_draft(user, text=f"Для {user.pk}") for user in order])
    expected_users = [users[4], users[1], users[2], users[0]]
    assert len(created) == 4
    assert created == sorted(created)
    by_pk = dict(_notes().values_list("pk", "user_id"))
    assert [by_pk[pk] for pk in created] == [user.pk for user in expected_users]
    deliveries = list(_deliveries().filter(notification_id__in=created).order_by("pk"))
    assert [row.notification_id for row in deliveries] == created
    assert {row.channel for row in deliveries} == {"email"}
    assert _deliveries(skipped).count() == 1                    # только доставка прежней записи
