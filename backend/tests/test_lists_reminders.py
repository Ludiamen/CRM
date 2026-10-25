"""T-6115: обход задания сроков и получатели напоминаний (FR-509, FR-523, FR-529, FR-530, FR-544, NFR-511).
Сценарий 8 спеки среза 006.

Задание `reminders.run(today)` (шаги 1-5 плана, «Сроки и напоминания») и `tasks.remind_deadlines()` — синхронно,
настоящие база и модуль `notify` (`dispatch.create`). Дата «сегодня» передаётся явно, часы фикстурой `clock` стоят на
том же московском дне. Гонки — без потоков: подмена `reminders.select_candidates` (решение 45 задач) и SQL по
помощникам (`list_locks`, `assert_for_update`). Код среза на уровне модуля не импортируется (шапка CONTRACT-006).
"""
import logging
import re
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_lists as ls
from tests.support import model

pytestmark = pytest.mark.django_db

KIND = "lists.deadline"
TODAY = date(2026, 11, 1)
PINNED = "/me/#lists-pinned"


# --- помощники файла --------------------------------------------------------------------------------------

def _at(day: date):
    """Утро московского дня `day` — время запуска задания (08:00)."""
    return ls.moscow(day.year, day.month, day.day, 8, 0)


def _run(clock, day: date):
    """Часы на утро дня `day` и обход сроков за этот день."""
    clock.set(_at(day))
    return ls.run_reminders(day)


def _world(thresholds=(30, 7), *, due_name: str = "Действует до", extra_person: bool = False):
    """Список с одним полем-сроком, видимым полем «сотрудник» (несколько) и автором записей."""
    author = support.make_employee()
    lst = ls.make_list(created_by=author)
    due = ls.add_field(lst, "date", due_name, deadline=True, thresholds=thresholds)
    owner = ls.add_field(lst, "person", "Ответственный", multiple=True)
    data = SimpleNamespace(lst=lst, due=due, owner=owner, author=author, owner2=None)
    if extra_person:
        data.owner2 = ls.add_field(lst, "person", "Заместитель", multiple=True)
    return data


def _record(world, due_date, *, people=(), people2=(), title: str = "Лицензия", archived: bool = False):
    values = {}
    if due_date is not None:
        values[world.due.code] = due_date.isoformat()
    if people:
        values[world.owner.code] = [person.pk for person in people]
    if people2:
        values[world.owner2.code] = [person.pk for person in people2]
    return ls.make_record(world.lst, title, values, archived=archived, created_by=world.author)


def _editor(lst):
    role = factories.make_role()
    ls.grant_list(lst, role, "edit")
    return support.make_employee(roles=[role])


def _reader(lst):
    role = factories.make_role()
    ls.grant_list(lst, role, "read")
    return support.make_employee(roles=[role])


def _ref(record, field, threshold: int) -> str:
    return f"lists.record:{record.pk}:{field.pk}:{threshold}"


def _notes(user=None, kind: str = KIND):
    notes = model("notify.Notification").objects.filter(kind=kind)
    if user is not None:
        notes = notes.filter(user=user)
    return notes


def _refs(user) -> list[str]:
    return sorted(_notes(user).values_list("object_ref", flat=True))


def _marks(record, field=None) -> list[tuple]:
    rows = model("lists.ReminderSent").objects.filter(record=record)
    if field is not None:
        rows = rows.filter(field=field)
    return sorted(rows.values_list("threshold_days", "due_date", "notified"), key=lambda row: (row[1], row[0]))


def _expiring_text(world, record, due_date) -> str:
    return f"Истекает срок: {world.lst.name} — {record.title}: {world.due.name} {due_date:%d.%m.%Y}"


def _reached_text(world, record, due_date) -> str:
    return f"Срок наступил: {world.lst.name} — {record.title}: {world.due.name} {due_date:%d.%m.%Y}"


def _tasks():
    from apps.lists import tasks

    return tasks


# --- пороги и дни -----------------------------------------------------------------------------------------

def test_reminder_exactly_30_days_before_deadline_creates_expiring_notification(clock):
    """FR-530: до даты ровно 30 календарных дней (порог поля) — каждому получателю одно уведомление «Истекает срок: …»
    с порогом 30 в `object_ref`, в базе отметка порога; сценарий 8 п. 2."""
    world = _world()
    owner, editor = support.make_employee(), _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    record = _record(world, due_date, people=[owner])

    result = _run(clock, TODAY)

    assert result.failed == [] and result.notified == 2
    for user in (owner, editor):
        notes = list(_notes(user))
        assert len(notes) == 1
        assert notes[0].object_ref == _ref(record, world.due, 30)
        assert notes[0].text == _expiring_text(world, record, due_date)
    assert _notes().count() == 2
    assert _marks(record) == [(30, due_date, True)]


def test_reminder_counts_days_from_moscow_today_at_utc_midnight(clock):
    """FR-530: дни считаются от сегодняшней даты по Москве, а не по UTC. Часы стоят на 01:00 по Москве — 22:00 UTC
    предыдущих суток (T-6106-1: поздний час UTC годится для проверки дат); задание — `tasks.remind_deadlines()`."""
    world = _world(thresholds=(30,))
    editor = _editor(world.lst)
    in_thirty = _record(world, date(2026, 12, 1), title="Через тридцать")  # по Москве 30 дней, по UTC — 31
    reached = _record(world, date(2026, 11, 1), title="Сегодня")  # по Москве срок наступил, по UTC остался день
    clock.set(ls.moscow(2026, 11, 1, 1, 0))

    _tasks().remind_deadlines()

    assert _refs(editor) == sorted([_ref(in_thirty, world.due, 30), _ref(reached, world.due, 0)])
    assert _notes(editor).get(object_ref=_ref(reached, world.due, 0)).text.startswith("Срок наступил: ")
    assert _marks(in_thirty) == [(30, date(2026, 12, 1), True)]


def test_reminder_exactly_7_days_notifies_again_and_30_day_threshold_not_repeated(clock):
    """FR-530: по порогу 30 уведомление идёт в свой день, через 23 дня (осталось 7) — второе по порогу 7; порог 30 не
    повторяется; сценарий 8 п. 3."""
    world = _world(thresholds=(30, 7))
    editor = _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    record = _record(world, due_date)

    _run(clock, TODAY)
    assert _refs(editor) == [_ref(record, world.due, 30)]
    result = _run(clock, TODAY + timedelta(days=23))

    assert result.notified == 1
    assert _refs(editor) == sorted([_ref(record, world.due, 30), _ref(record, world.due, 7)])
    assert _notes(editor).get(object_ref=_ref(record, world.due, 7)).text == _expiring_text(world, record, due_date)
    assert _marks(record) == [(7, due_date, True), (30, due_date, True)]


def test_reminder_on_deadline_day_creates_deadline_reached_notification(clock):
    """FR-530: в день срока — «Срок наступил: …» с порогом 0 в `object_ref`; сценарий 8 п. 4."""
    world = _world(thresholds=(30, 7))
    editor = _editor(world.lst)
    due_date = TODAY
    record = _record(world, due_date)

    _run(clock, due_date - timedelta(days=30))
    _run(clock, due_date - timedelta(days=7))
    result = _run(clock, due_date)

    assert result.notified == 1
    assert _refs(editor) == sorted([_ref(record, world.due, threshold) for threshold in (30, 7, 0)])
    reached = _notes(editor).get(object_ref=_ref(record, world.due, 0))
    assert reached.text == _reached_text(world, record, due_date)
    assert (0, due_date, True) in _marks(record)


def test_reminder_second_run_same_day_creates_no_duplicates(clock):
    """FR-530, NFR-511: повторный запуск за тот же день не создаёт ни уведомлений, ни отметок; сценарий 8 п. 5 (на
    днях порогов 30 и 7 и в день срока)."""
    world = _world(thresholds=(30, 7))
    owner, editor = support.make_employee(), _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    record = _record(world, due_date, people=[owner])

    for day in (TODAY, TODAY + timedelta(days=23), due_date):
        first = _run(clock, day)
        notes_before, marks_before = _notes().count(), _marks(record)
        second = _run(clock, day)
        assert first.notified == 2 and first.failed == []
        assert second.notified == 0 and second.failed == []
        assert _notes().count() == notes_before and _marks(record) == marks_before
    assert _notes(owner).count() == 3 and _notes(editor).count() == 3


def test_reminder_moved_deadline_recounts_thresholds_and_old_date_marks_neither_block_nor_refire(clock):
    """FR-530: срок перенесли — пороги считаются от новой даты заново; отметки старой даты ни не мешают новому
    уведомлению по тому же порогу (прежнее не прочитано), ни сами не срабатывают повторно; сценарий 8 п. 6."""
    world = _world(thresholds=(30, 7))
    editor = _editor(world.lst)
    old_due, new_due = TODAY + timedelta(days=30), TODAY + timedelta(days=90)
    record = _record(world, old_due)

    _run(clock, TODAY)
    assert _notes(editor).count() == 1
    model("lists.Record").objects.filter(pk=record.pk).update(values={world.due.code: new_due.isoformat()})

    quiet = _run(clock, TODAY)
    assert quiet.notified == 0 and _notes(editor).count() == 1

    result = _run(clock, TODAY + timedelta(days=60))  # до новой даты 30 дней
    assert result.notified == 1
    assert _notes(editor).filter(object_ref=_ref(record, world.due, 30)).count() == 2
    assert _notes(editor).filter(text=_expiring_text(world, record, new_due)).count() == 1
    assert _notes(editor).filter(text=_expiring_text(world, record, old_due)).count() == 1
    assert (30, old_due, True) in _marks(record) and (30, new_due, True) in _marks(record)

    again = _run(clock, TODAY + timedelta(days=60))
    assert again.notified == 0 and _notes(editor).count() == 2
    _run(clock, TODAY + timedelta(days=83))  # до новой даты 7 дней
    assert _notes(editor).filter(object_ref=_ref(record, world.due, 7)).count() == 1
    assert _notes(editor).filter(text=_expiring_text(world, record, old_due)).count() == 1


def test_reminder_skips_archived_record_and_hidden_deadline_field(clock):
    """FR-509, FR-523, FR-530: запись в архиве и скрытое поле-срок не обрабатываются — ни уведомлений, ни отметок;
    такая же запись с видимым сроком уведомление получает; сценарий 8 п. 7."""
    world = _world(thresholds=(30,))
    hidden = ls.add_field(world.lst, "date", "Скрытый срок", deadline=True, thresholds=[30], hidden=True)
    editor = _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    control = _record(world, due_date, title="Живая")
    archived = _record(world, due_date, title="В архиве", archived=True)
    in_hidden = ls.make_record(world.lst, "Скрытое поле", {hidden.code: due_date.isoformat()}, created_by=world.author)

    result = _run(clock, TODAY)

    assert result.failed == [] and result.notified == 1
    assert _refs(editor) == [_ref(control, world.due, 30)]
    assert _marks(archived) == [] and _marks(in_hidden) == []
    assert _marks(control) == [(30, due_date, True)]


def test_reminder_after_missed_days_sends_one_notification_by_nearest_threshold_and_marks_others_not_notified(clock):
    """FR-530: задание не работало, до срока 5 дней при порогах 30 и 7 — одно уведомление по ближайшему порогу 7,
    порог 30 отмечается как пропущенный (`notified=False`); сценарий 8 п. 8."""
    world = _world(thresholds=(30, 7))
    owner, editor = support.make_employee(), _editor(world.lst)
    due_date = TODAY + timedelta(days=5)
    record = _record(world, due_date, people=[owner])

    result = _run(clock, TODAY)

    assert result.notified == 2
    for user in (owner, editor):
        assert _refs(user) == [_ref(record, world.due, 7)]
    assert _marks(record) == [(7, due_date, True), (30, due_date, False)]
    assert _run(clock, TODAY + timedelta(days=1)).notified == 0
    assert _notes().count() == 2


def test_reminder_record_created_with_date_inside_threshold_notified_on_next_run(clock):
    """FR-530: запись создана с датой внутри порога (до срока 10 дней при порогах 30 и 7) — при ближайшем запуске
    уведомление по порогу 30, порог 7 наступит позже сам."""
    world = _world(thresholds=(30, 7))
    editor = _editor(world.lst)
    _run(clock, TODAY)
    due_date = TODAY + timedelta(days=10)
    record = _record(world, due_date)

    result = _run(clock, TODAY)

    assert result.notified == 1
    assert _refs(editor) == [_ref(record, world.due, 30)]
    assert _marks(record) == [(30, due_date, True)]
    _run(clock, TODAY + timedelta(days=3))  # осталось 7 дней
    assert _refs(editor) == sorted([_ref(record, world.due, 30), _ref(record, world.due, 7)])


def test_reminder_deadline_day_missed_entirely_gives_no_deadline_reached(clock):
    """FR-530: срок, день которого задание пропустило целиком (дата вчера, раньше), уведомления «Срок наступил» не
    даёт — просроченная дата не обрабатывается (решение плана)."""
    world = _world(thresholds=(30, 7))
    editor = _editor(world.lst)
    yesterday = _record(world, TODAY - timedelta(days=1), title="Вчера")
    long_ago = _record(world, TODAY - timedelta(days=5), title="Давно")

    result = _run(clock, TODAY)

    assert result.failed == [] and result.notified == 0
    assert _notes().count() == 0 and _notes(editor).count() == 0
    assert _marks(yesterday) == [] and _marks(long_ago) == []


def test_reminder_custom_thresholds_and_two_deadline_fields_notify_by_own_thresholds(clock):
    """FR-529, FR-530: у каждого поля-срока свои пороги (первое — 10, второе — 45 и 3); уведомление идёт по порогам
    своего поля, `object_ref` различает поля."""
    world = _world(thresholds=(10,), due_name="Срок A")
    second = ls.add_field(world.lst, "date", "Срок B", deadline=True, thresholds=[45, 3])
    editor = _editor(world.lst)
    first = ls.make_record(world.lst, "Первая", {
        world.due.code: (TODAY + timedelta(days=10)).isoformat(),
        second.code: (TODAY + timedelta(days=3)).isoformat()}, created_by=world.author)
    other = ls.make_record(world.lst, "Вторая", {
        world.due.code: (TODAY + timedelta(days=30)).isoformat(),
        second.code: (TODAY + timedelta(days=45)).isoformat()}, created_by=world.author)

    result = _run(clock, TODAY)

    assert result.failed == [] and result.notified == 3
    assert _refs(editor) == sorted([
        _ref(first, world.due, 10), _ref(first, second, 3), _ref(other, second, 45)])
    assert _marks(first, second) == [(3, TODAY + timedelta(days=3), True), (45, TODAY + timedelta(days=3), False)]
    assert _marks(other, world.due) == []


# --- получатели -------------------------------------------------------------------------------------------

def test_reminder_recipients_are_active_employees_from_visible_employee_fields_and_edit_set(clock):
    """FR-530: получатели — действующие сотрудники из видимых полей «сотрудник» записи (хотя бы одного из двух полей)
    и действующие из набора «Правят»; читающий список, не указанный в записи, и посторонний — нет."""
    world = _world(thresholds=(30,), extra_person=True)
    in_first, in_second = support.make_employee(), support.make_employee()
    editor, reader, stranger = _editor(world.lst), _reader(world.lst), support.make_employee()
    due_date = TODAY + timedelta(days=30)
    record = _record(world, due_date, people=[in_first], people2=[in_second])

    result = _run(clock, TODAY)

    assert result.notified == 3
    for user in (in_first, in_second, editor):
        assert _refs(user) == [_ref(record, world.due, 30)]
        assert _notes(user).get().text == _expiring_text(world, record, due_date)
    assert _notes(reader).count() == 0 and _notes(stranger).count() == 0
    assert _notes().count() == 3


def test_reminder_skips_dismissed_employee_and_employee_only_in_hidden_field(clock):
    """FR-509, FR-530: уволенный сотрудник из записи и из набора «Правят» уведомления не получает; сотрудник, указанный
    только в скрытом поле «сотрудник», — тоже; действующий из видимого поля — получает; сценарий 8 п. 9."""
    world = _world(thresholds=(30,))
    hidden_owner = ls.add_field(world.lst, "person", "Скрытый ответственный", multiple=True, hidden=True)
    active, gone = support.make_employee(), support.make_employee(state="dismissed")
    only_hidden, gone_editor = support.make_employee(), _editor(world.lst)
    model("core.User").objects.filter(pk=gone_editor.pk).update(state="dismissed")
    due_date = TODAY + timedelta(days=30)
    record = ls.make_record(world.lst, "Лицензия", {
        world.due.code: due_date.isoformat(), world.owner.code: [active.pk, gone.pk],
        hidden_owner.code: [only_hidden.pk]}, created_by=world.author)

    result = _run(clock, TODAY)

    assert result.notified == 1
    assert _refs(active) == [_ref(record, world.due, 30)]
    for user in (gone, only_hidden, gone_editor):
        assert _notes(user).count() == 0
    assert _notes().count() == 1


def test_reminder_manager_outside_edit_set_and_fields_gets_nothing(clock):
    """FR-530: управляющий (право `lists.manage`) получает напоминание, только если он в наборе «Правят» или указан в
    поле «сотрудник»; вне их — ничего."""
    world = _world(thresholds=(30,))
    outside = ls.as_manager().user
    in_field = ls.as_manager().user
    in_set = ls.as_manager().user
    ls.grant_list(world.lst, in_set.roles.get(), "edit")
    due_date = TODAY + timedelta(days=30)
    record = _record(world, due_date, people=[in_field])

    result = _run(clock, TODAY)

    assert result.notified == 2
    assert _notes(outside).count() == 0
    assert _refs(in_field) == [_ref(record, world.due, 30)]
    assert _refs(in_set) == [_ref(record, world.due, 30)]


def test_reminder_employee_in_field_and_edit_set_gets_one_notification_per_record_field_threshold(clock):
    """FR-530: сотрудник, указанный в записи (в двух полях сразу) и входящий в набор «Правят», получает одно
    уведомление на запись, поле-срок и порог: две записи и два срока — четыре, без повторов; повторный запуск не
    добавляет."""
    world = _world(thresholds=(30,), extra_person=True)
    second = ls.add_field(world.lst, "date", "Срок B", deadline=True, thresholds=[30])
    both = _editor(world.lst)
    due_text = (TODAY + timedelta(days=30)).isoformat()
    records = [ls.make_record(world.lst, f"Запись {number}", {
        world.due.code: due_text, second.code: due_text,
        world.owner.code: [both.pk], world.owner2.code: [both.pk]}, created_by=world.author) for number in (1, 2)]

    result = _run(clock, TODAY)

    wanted = sorted(_ref(record, field, 30) for record in records for field in (world.due, second))
    assert result.notified == 4
    assert _refs(both) == wanted and _notes(both).count() == 4
    assert _run(clock, TODAY).notified == 0
    assert _notes(both).count() == 4


def test_reminder_employee_in_field_without_list_read_right_still_notified(clock):
    """FR-530: сотрудник из записи без права на список получает напоминание со ссылкой в «Закреплённое» его карточки;
    читающий список и правящий — со ссылкой на карточку записи; сценарий 8 п. 11."""
    world = _world(thresholds=(30,))
    no_rights, reader, editor = support.make_employee(), _reader(world.lst), _editor(world.lst)
    record = _record(world, TODAY + timedelta(days=30), people=[no_rights, reader])
    card = f"/lists/{world.lst.pk}/{record.number}/"

    result = _run(clock, TODAY)

    assert result.notified == 3
    assert _notes(no_rights).get().url == PINNED
    assert _notes(reader).get().url == card
    assert _notes(editor).get().url == card
    assert _notes(no_rights).get().object_ref == _ref(record, world.due, 30)


# --- замки, гонки, сбои -----------------------------------------------------------------------------------

def test_reminder_takes_shared_list_lock_then_record_for_update_and_reads_marks_after_lock(clock):
    """FR-530, NFR-511: на запись — разделяемый замок списка первым (`access.lock_list(shared=True)`), затем
    `SELECT … FOR UPDATE` строки записи; отметки `ReminderSent` читаются заново после этого замка; исключительного
    замка списка нет."""
    world = _world(thresholds=(30,))
    _editor(world.lst)
    _record(world, TODAY + timedelta(days=30))
    clock.set(_at(TODAY))

    sqls = ls.sql_of(ls.run_reminders, TODAY)

    locks = ls.list_locks(sqls)
    assert locks and locks[0] == ls.ListLock("shared", ls.list_no(world.lst.pk)), locks
    assert all(lock.kind == "shared" for lock in locks)
    lock_at = next(n for n, sql in enumerate(sqls) if "pg_advisory_xact_lock_shared" in sql)
    update_at = sqls.index(ls.assert_for_update(sqls, "lists_record"))
    assert lock_at < update_at
    marks_table = model("lists.ReminderSent")._meta.db_table
    reads_after = [n for n, sql in enumerate(sqls)
                   if n > update_at and sql.lstrip().upper().startswith("SELECT") and marks_table in sql]
    assert reads_after, "после замка записи отметки порогов не читались"


def test_reminder_mark_inserted_by_other_run_between_select_and_lock_gives_no_duplicate_or_error(clock, monkeypatch):
    """NFR-511: другой запуск вставил отметку порога между выборкой и замком — повторной отметки и уведомления нет,
    ошибки нет, сбоев в итоге нет."""
    world = _world(thresholds=(30,))
    _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    record = _record(world, due_date)
    Mark = model("lists.ReminderSent")

    def other_run(candidates):
        for candidate in candidates:
            Mark.objects.create(record_id=candidate.record_id, field_id=candidate.field_id, threshold_days=30,
                                due_date=candidate.due_date, notified=True)

    selections = ls.act_between_select_and_lock(monkeypatch, other_run)

    result = _run(clock, TODAY)

    assert len(selections) == 1 and [c.record_id for c in selections[0]] == [record.pk]
    assert result.failed == [] and result.notified == 0
    assert _notes().count() == 0
    assert Mark.objects.filter(record=record).count() == 1


def test_reminder_record_deleted_or_archived_between_select_and_lock_skipped_without_error(clock, monkeypatch):
    """FR-523, NFR-511: запись, удалённая или перенесённая в архив между выборкой и замком, пропускается без ошибки
    и без отметок; соседняя запись обработана."""
    world = _world(thresholds=(30,))
    editor = _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    deleted = _record(world, due_date, title="Удалят")
    archived = _record(world, due_date, title="Архивируют")
    control = _record(world, due_date, title="Останется")
    Record = model("lists.Record")

    def meanwhile(candidates):
        Record.objects.filter(pk=deleted.pk).delete()
        ls.archive(Record.objects.get(pk=archived.pk))

    selections = ls.act_between_select_and_lock(monkeypatch, meanwhile)

    result = _run(clock, TODAY)

    assert sorted(c.record_id for c in selections[0]) == sorted([deleted.pk, archived.pk, control.pk])
    assert result.failed == [] and result.notified == 1
    assert _refs(editor) == [_ref(control, world.due, 30)]
    assert _marks(archived) == [] and _marks(control) == [(30, due_date, True)]
    assert not model("lists.ReminderSent").objects.filter(record_id=deleted.pk).exists()


def test_reminder_field_hidden_or_date_changed_between_select_and_lock_rechecked_under_lock(clock, monkeypatch):
    """FR-509, FR-530, NFR-511: поле скрыли (в одном списке) или дату сменили на далёкую (в другом) между выборкой и
    замком — под замком проверка повторяется: уведомлений и отметок по ним нет; третий список не тронут."""
    hidden_world = _world(thresholds=(30,))
    moved_world = _world(thresholds=(30,))
    control_world = _world(thresholds=(30,))
    due_date = TODAY + timedelta(days=30)
    editors = {name: _editor(w.lst) for name, w in
               (("hidden", hidden_world), ("moved", moved_world), ("control", control_world))}
    hidden_rec = _record(hidden_world, due_date)
    moved_rec = _record(moved_world, due_date)
    control_rec = _record(control_world, due_date)

    def meanwhile(candidates):
        model("lists.Field").objects.filter(pk=hidden_world.due.pk).update(hidden=True)
        model("lists.Record").objects.filter(pk=moved_rec.pk).update(
            values={moved_world.due.code: (TODAY + timedelta(days=200)).isoformat()})

    selections = ls.act_between_select_and_lock(monkeypatch, meanwhile)

    result = _run(clock, TODAY)

    assert {c.record_id for c in selections[0]} == {hidden_rec.pk, moved_rec.pk, control_rec.pk}
    assert result.failed == [] and result.notified == 1
    assert _notes(editors["hidden"]).count() == 0 and _notes(editors["moved"]).count() == 0
    assert _refs(editors["control"]) == [_ref(control_rec, control_world.due, 30)]
    assert _marks(hidden_rec) == [] and _marks(moved_rec) == []


def test_reminder_failure_of_one_record_logged_with_number_and_class_loop_continues_and_task_fails_at_end(
        clock, monkeypatch, caplog):
    """FR-530, NFR-511: сбой одной записи — в журнал приложения (логгер `apps.lists.reminders`: номер записи и имя
    класса исключения), обход продолжается и остальные записи получают уведомления, итог называет запись в `failed`,
    а `tasks.remind_deadlines()` после обхода завершается `RuntimeError` с номером записи."""
    from apps.lists.services import reminders

    filler = _world(thresholds=(30,))
    for _ in range(5):  # номера записей и их id расходятся
        _record(filler, None)
    world = _world(thresholds=(30,))
    editor = _editor(world.lst)
    due_date = TODAY + timedelta(days=30)
    bad = _record(world, due_date, title="Сбойная")
    good_one = _record(world, due_date, title="Первая хорошая")
    good_two = _record(world, due_date, title="Вторая хорошая")
    real = reminders.notify_record

    def flaky(candidate, today, *args, **kwargs):
        if candidate.record_id == bad.pk:
            raise ValueError("сбой записи")
        return real(candidate, today, *args, **kwargs)

    monkeypatch.setattr(reminders, "notify_record", flaky)
    caplog.set_level(logging.ERROR, logger="apps.lists.reminders")
    named = re.compile(rf"(?<!\d)({bad.number}|{bad.pk})(?!\d)")

    result = _run(clock, TODAY)

    assert [i for i in result.failed if i in (bad.number, bad.pk)] == result.failed and len(result.failed) == 1
    assert _refs(editor) == sorted([_ref(good_one, world.due, 30), _ref(good_two, world.due, 30)])
    logged = [r for r in caplog.records if r.name == "apps.lists.reminders" and r.levelno >= logging.ERROR]
    assert logged and any("ValueError" in r.getMessage() and named.search(r.getMessage()) for r in logged)
    assert _marks(bad) == []
    with pytest.raises(RuntimeError) as failure:
        _tasks().remind_deadlines()
    assert named.search(str(failure.value))


# --- без notify, сроки без порогов, хранение --------------------------------------------------------------

def test_reminder_without_notify_creates_no_notifications_and_still_cleans_up(clock, monkeypatch):
    """FR-530: без приложения `notify` напоминания пропускаются без ошибки (уведомлений нет), а уборка шага 5
    выполняется: строки `ImportJob` старше суток и отметки `ReminderSent` со сроком старше года удалены, свежие
    остались."""
    world = _world(thresholds=(30,))
    _editor(world.lst)
    _record(world, TODAY + timedelta(days=30))
    old_mark_record = _record(world, TODAY - timedelta(days=400), title="Давний срок")
    fresh_mark_record = _record(world, TODAY - timedelta(days=100), title="Недавний срок")
    clock.set(_at(TODAY))
    now = timezone.now()
    Mark, Job = model("lists.ReminderSent"), model("lists.ImportJob")
    Mark.objects.create(record=old_mark_record, field=world.due, threshold_days=30,
                        due_date=TODAY - timedelta(days=400), notified=True)
    Mark.objects.create(record=fresh_mark_record, field=world.due, threshold_days=30,
                        due_date=TODAY - timedelta(days=100), notified=True)
    make_job = lambda name, created: Job.objects.create(  # noqa: E731
        list=world.lst, created_by=world.author, created_at=created, file_name=name, file_format="csv",
        state="done", header=[], mapping={}, rows=[], summary={})
    old_job = make_job("старая.csv", now - timedelta(days=2))
    fresh_job = make_job("свежая.csv", now - timedelta(hours=1))
    ls.without_app(monkeypatch, "apps.notify")

    result = ls.run_reminders(TODAY)

    assert result.failed == [] and result.notified == 0
    assert _notes().count() == 0
    assert not Job.objects.filter(pk=old_job.pk).exists() and Job.objects.filter(pk=fresh_job.pk).exists()
    assert not Mark.objects.filter(record=old_mark_record).exists()
    assert Mark.objects.filter(record=fresh_mark_record).count() == 1


def test_reminder_deadline_field_without_thresholds_notifies_only_on_deadline_day(clock):
    """FR-529, FR-530: у поля-срока без порогов уведомление приходит только в день срока («Срок наступил»);
    за 30, 7 и 1 день — нет."""
    world = _world(thresholds=())
    editor = _editor(world.lst)
    records = {days: _record(world, TODAY + timedelta(days=days), title=f"Через {days}") for days in (30, 7, 1, 0)}

    result = _run(clock, TODAY)

    assert result.failed == [] and result.notified == 1
    assert _refs(editor) == [_ref(records[0], world.due, 0)]
    assert _notes(editor).get().text == _reached_text(world, records[0], TODAY)
    assert _marks(records[0]) == [(0, TODAY, True)]
    for days in (30, 7, 1):
        assert _marks(records[days]) == []


def test_reminder_task_deletes_no_records_history_or_files(clock, protected_root, django_capture_on_commit_callbacks):
    """FR-544: задание сроков ничего не удаляет — ни записи (в том числе в архиве и с просроченным сроком), ни
    историю, ни файлы (строки и байты на диске); счётчики до и после двух запусков те же."""
    from apps.core.services import files as core_files

    world = _world(thresholds=(30, 7))
    attachments = ls.add_field(world.lst, "file", "Файлы", multiple=True)
    _editor(world.lst)
    current = _record(world, TODAY + timedelta(days=30), title="Идёт")
    overdue = _record(world, TODAY - timedelta(days=500), title="Просрочена")
    archived = _record(world, TODAY + timedelta(days=30), title="В архиве", archived=True)
    clock.set(_at(TODAY))
    Change = model("lists.Change")
    for record in (current, overdue, archived):
        Change.objects.create(record=record, kind="created", changes=[], actor=world.author, at=timezone.now())
    attached = ls.attach_file(current, attachments, "акт.pdf", write=True)
    attached_archived = ls.attach_file(archived, attachments, "договор.pdf", write=True)
    paths = [core_files.attachment_path(item.file) for item in (attached, attached_archived)]
    assert all(path.exists() for path in paths)

    def snapshot():
        return {label: model(label).objects.count()
                for label in ("lists.Record", "lists.Change", "lists.RecordFile", "core.StoredFile")}

    before = snapshot()
    with django_capture_on_commit_callbacks(execute=True):
        _run(clock, TODAY)
        _run(clock, TODAY + timedelta(days=23))

    assert snapshot() == before
    assert all(path.exists() for path in paths)
    assert model("lists.Record").objects.filter(pk__in=[current.pk, overdue.pk, archived.pk]).count() == 3
