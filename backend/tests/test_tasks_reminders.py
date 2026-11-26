"""T-9112: напоминания задач — моменты, тихие часы, ручные, «Отложить», пересчёт, снятие, идемпотентность
(FR-687, FR-688, FR-689, FR-690, NFR-715).

Источники: PLAN-009 «Напоминания» (момент срока — конец рабочего дня, нерабочая дата — первый рабочий день после;
`auto_soon` — начало предыдущего рабочего дня, `auto_due` — начало дня срока, `auto_overdue` — начало следующего
рабочего дня; каждый момент сдвигается `notify.services.quiet.next_start`; `None` первый раз оставляет `pending`,
повторный — отмена с записью `tasks.reminder_failed`; ручные «за N рабочих дней»/«на дату», не больше 10, «Отложить»
на 1 рабочий день; смена срока/состава пересчитывает, завершение и удаление снимают); CONTRACT-009: 5.1
(`reminders.plan`/`set_manual`/`postpone`/`cancel_all`, задание `tasks_reminders(now=…)`), 5.3 (точки подмены
`apps.tasks.services.reminders.quiet.next_start`), 6.2 (`POST /tasks/<id>/remind/`,
`POST /tasks/reminders/<id>/postpone/`), 8 (все правила файла), 10.1 (`tasks.reminder_set`, `tasks.reminder_failed`),
12.1 (тексты отказов напоминаний).

Тесты зовут задание синхронно с `now=…`; «сейчас» — аргумент, а не часы машины. Код среза импортируется внутри
тестов, модели берутся через `support.model`: `pytest --collect-only` проходит до появления кода. Секретов и ПДн нет:
ФИО вымышленные, почта и телефоны не создаются.
"""
import datetime
import importlib
from datetime import date, time, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime.datetime(2026, 11, 22, 12, 0, tzinfo=MSK)      # воскресенье
DEADLINE = date(2026, 11, 18)                                  # среда
DAY_START = time(9, 0)

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки отказа (помощник только этого файла) -------------------------------------------------------

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
        for child in self.children:
            parts.append(child.text() if isinstance(child, _Node) else child)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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


def _refusals(response) -> list[tuple[str, str, str]]:
    return [(node.attrs["data-error"], node.attrs.get("data-code", ""), node.text())
            for node in _tree(response).walk() if "data-error" in node.attrs]


def _refused(response, field: str, code: str, text: str) -> None:
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    found = _refusals(response)
    assert (field, code, text) in found, f"нет отказа {field}/{code}/{text!r}: {found}"
    assert text in response.content.decode("utf-8")


# --- помощники напоминаний -------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.tasks.services.{name}")


def _job(now):
    """`tasks_reminders(now=…)` — синхронно, без очереди."""
    from apps.tasks.tasks import tasks_reminders

    return tasks_reminders(now=now)


def _rows(task):
    return tasks_helpers.reminders_of(task)


def _by_kind(task):
    """Моменты по видам: `{kind: {user_id: moment}}` (у одного вида один получатель на строку)."""
    result = {}
    for row in _rows(task):
        result.setdefault(row.kind, {})[row.user_id] = row.moment
    return result


def _pending(task):
    return [row for row in _rows(task) if row.state == "pending"]


def _audit(action: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _notes(user=None, kind: str | None = None):
    rows = support.model("notify.Notification").objects.filter(kind__startswith="tasks.")
    if user is not None:
        rows = rows.filter(user=getattr(user, "user", user))
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _seed_year(year: int, days: dict | None = None):
    """Загруженный год календаря напрямую в базе: без года особые дни не видны `day_kind` (CONTRACT-009, 8)."""
    by = support.make_employee(full_name="Календарь Напоминаний")
    now = timezone.now()
    support.model("org.CalendarYear").objects.create(
        year=year, loaded_at=now, loaded_by=by, file_name=f"cal{year}.csv", totals={})
    support.model("org.SpecialDay").objects.bulk_create([
        support.model("org.SpecialDay")(date=day, kind=kind, origin="file", changed_by=by, changed_at=now)
        for day, kind in (days or {}).items()])


def _prefs(user, **fields):
    """Настройки уведомлений сотрудника (тихие часы): строка `UserNotifySettings`, иначе значения по умолчанию."""
    row, _ = support.model("notify.UserNotifySettings").objects.update_or_create(user=user, defaults=fields)
    return row


def _next_start(user, moment):
    """`quiet.next_start` по сохранённым настройкам сотрудника (что и должна сделать служба напоминаний)."""
    from apps.notify.services import quiet

    return quiet.next_start(_prefs(user), moment)


def _pair():
    """Постановщик и исполнитель — разные сотрудники (иначе «свои действия» мешают уведомлениям)."""
    return (tasks_helpers.staff_user(full_name="Постановщик Напоминаний"),
            tasks_helpers.staff_user(full_name="Исполнитель Напоминаний"))


# --- FR-687: моменты автоматических напоминаний -----------------------------------------------------------------

def test_auto_moments_on_working_day_and_recipients_are_assignee_and_coexecutor():
    """FR-687: `plan` ставит три автоматических напоминания (`auto_soon` — начало предыдущего рабочего дня,
    `auto_due` — начало дня срока, `auto_overdue` — начало следующего рабочего дня) исполнителю и соисполнителю,
    состояние `pending`; постановщик напоминаний не получает."""
    author, assignee = _pair()
    coexecutor = tasks_helpers.staff_user(full_name="Соисполнитель Напоминаний")
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE)
    tasks_helpers.add_member(task, coexecutor)

    _svc("reminders").plan(task)

    rows = _rows(task)
    assert {row.kind for row in rows} == {"auto_soon", "auto_due", "auto_overdue"}
    assert {row.user_id for row in rows} == {assignee.pk, coexecutor.pk}
    expected = {
        "auto_soon": datetime.datetime(2026, 11, 17, 9, 0, tzinfo=MSK),
        "auto_due": datetime.datetime(2026, 11, 18, 9, 0, tzinfo=MSK),
        "auto_overdue": datetime.datetime(2026, 11, 19, 9, 0, tzinfo=MSK),
    }
    for row in rows:
        assert row.moment == expected[row.kind], f"{row.kind} у {row.user_id}: {row.moment}"
        assert row.state == "pending"
    assert author.pk not in {row.user_id for row in rows}


def test_holiday_deadline_and_several_days_off_move_moments_to_working_days():
    """FR-687: срок — праздник: момент срока — конец первого рабочего дня после, `auto_due` — его начало; несколько
    нерабочих дней подряд (праздник и перенесённый выходной) сдвигают все три момента на рабочие дни."""
    _seed_year(2026, {date(2026, 11, 18): "holiday", date(2026, 11, 19): "day_off"})
    _, assignee = _pair()
    holiday_task = tasks_helpers.make_task(assignee=assignee, deadline=date(2026, 11, 19),
                                           title="Срок в праздник")
    _svc("reminders").plan(holiday_task)
    single = _by_kind(holiday_task)
    assert single["auto_due"][assignee.pk] == datetime.datetime(2026, 11, 20, 9, 0, tzinfo=MSK), (
        "нерабочий срок — первый рабочий день после")
    assert single["auto_soon"][assignee.pk] == datetime.datetime(2026, 11, 17, 9, 0, tzinfo=MSK)
    assert single["auto_overdue"][assignee.pk] == datetime.datetime(2026, 11, 23, 9, 0, tzinfo=MSK), (
        "просрочка — следующий рабочий день, а не суббота")

    two_off_task = tasks_helpers.make_task(assignee=assignee, deadline=date(2026, 11, 18),
                                           title="Срок в два нерабочих дня")
    _svc("reminders").plan(two_off_task)
    double = _by_kind(two_off_task)
    assert double["auto_due"][assignee.pk] == datetime.datetime(2026, 11, 20, 9, 0, tzinfo=MSK)
    assert double["auto_soon"][assignee.pk] == datetime.datetime(2026, 11, 17, 9, 0, tzinfo=MSK)
    assert double["auto_overdue"][assignee.pk] == datetime.datetime(2026, 11, 23, 9, 0, tzinfo=MSK)


def test_past_deadline_is_planned_and_job_sends_without_breaking():
    """FR-687, NFR-715: срок в прошлом — `plan` считает моменты по правилам (они в прошлом), задание отправляет
    созревшие напоминания, не падает и не оставляет `pending`; задача остаётся на месте."""
    author, assignee = _pair()
    past = date(2026, 11, 10)                                  # вторник
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=past)
    _svc("reminders").plan(task)
    moments = _by_kind(task)
    assert moments["auto_due"][assignee.pk] == datetime.datetime(2026, 11, 10, 9, 0, tzinfo=MSK)
    assert moments["auto_soon"][assignee.pk] == datetime.datetime(2026, 11, 9, 9, 0, tzinfo=MSK)
    assert moments["auto_overdue"][assignee.pk] == datetime.datetime(2026, 11, 11, 9, 0, tzinfo=MSK)

    _job(NOW)

    assert not _pending(task), "созревшие напоминания остались pending"
    assert _notes(kind="tasks.overdue").filter(user=assignee).exists(), "просрочка не ушла исполнителю"
    assert support.model("tasks.Task").objects.filter(pk=task.pk).exists()


# --- FR-689: личные тихие часы ---------------------------------------------------------------------------------

def test_quiet_hours_shift_each_moment_by_personal_mode_calendar_own_none():
    """FR-689: каждый момент сдвигается `notify.next_start` по личным настройкам получателя: режим «календарь» и
    «без тихих часов» оставляют момент, «свои часы» (10:00–19:00) переносят на 10:00 того же рабочего дня."""
    author, _ = _pair()
    calendar_user = tasks_helpers.staff_user(full_name="Тихие Часы Календарь")
    own_user = tasks_helpers.staff_user(full_name="Тихие Часы Свои")
    none_user = tasks_helpers.staff_user(full_name="Тихие Часы Нет")
    _prefs(calendar_user, quiet_mode="calendar")
    _prefs(own_user, quiet_mode="own", own_days=[0, 1, 2, 3, 4], own_start=time(10, 0), own_end=time(19, 0))
    _prefs(none_user, quiet_mode="none")

    base_task = tasks_helpers.make_task(author=author, assignee=calendar_user, deadline=DEADLINE)
    own_task = tasks_helpers.make_task(author=author, assignee=own_user, deadline=DEADLINE)
    none_task = tasks_helpers.make_task(author=author, assignee=none_user, deadline=DEADLINE)
    for task in (base_task, own_task, none_task):
        _svc("reminders").plan(task)

    base = {kind: moments[calendar_user.pk] for kind, moments in _by_kind(base_task).items()}
    assert base["auto_due"] == datetime.datetime(2026, 11, 18, 9, 0, tzinfo=MSK)
    for kind, moment in base.items():
        assert _by_kind(own_task)[kind][own_user.pk] == _next_start(own_user, moment), (
            f"{kind}: режим «свои часы» не сдвинул момент")
        assert _by_kind(none_task)[kind][none_user.pk] == moment, f"{kind}: режим «нет» сдвинул момент"
    assert _by_kind(own_task)["auto_due"][own_user.pk] == datetime.datetime(2026, 11, 18, 10, 0, tzinfo=MSK)


def test_next_start_none_keeps_pending_then_cancels_with_reminder_failed(monkeypatch):
    """FR-689, NFR-715: `quiet.next_start` вернул `None` — напоминание остаётся `pending` до следующего цикла; на
    повторе `None` оно отменяется, в журнале появляется `tasks.reminder_failed`, задача не ломается."""
    author, assignee = _pair()
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE)
    _svc("reminders").plan(task)
    monkeypatch.setattr("apps.tasks.services.reminders.quiet.next_start", lambda prefs, moment: None)

    due = datetime.datetime(2026, 11, 17, 9, 5, tzinfo=MSK)     # auto_soon уже созрело
    _job(due)
    soon = next(row for row in _rows(task) if row.kind == "auto_soon")
    assert soon.state == "pending", "первый `None` должен оставить напоминание pending"
    assert _audit("tasks.reminder_failed") == [], "первый `None` не должен писать журнал"

    _job(due + datetime.timedelta(minutes=5))
    task.refresh_from_db()
    assert support.model("tasks.TaskReminder").objects.get(pk=soon.pk).state == "cancelled", (
        "повторный `None` должен отменить напоминание")
    failed = _audit("tasks.reminder_failed")
    assert len(failed) == 1, f"записей tasks.reminder_failed: {len(failed)}"
    assert failed[0].object_id == str(task.pk)
    assert support.model("tasks.Task").objects.filter(pk=task.pk).exists(), "задача сломалась"


# --- FR-688: ручные напоминания, лимит и «Отложить» -------------------------------------------------------------

def test_manual_days_and_on_date_moments_and_audit():
    """FR-688: ручное «за N рабочих дней до срока» — начало рабочего дня N рабочих дней до момента срока;
    «на дату» — начало рабочего дня выбранной даты; строки вида `manual` у поставившего, состояние `pending`,
    в журнале `tasks.reminder_set` с номером задачи и моментом."""
    author, assignee = _pair()
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE)
    service = _svc("reminders")

    two_days = service.set_manual(assignee, task, days=2)
    one_day = service.set_manual(assignee, task, days=1)
    on_date = service.set_manual(assignee, task, on=date(2026, 12, 1))

    assert (two_days.kind, two_days.user_id, two_days.state) == ("manual", assignee.pk, "pending")
    assert two_days.moment == datetime.datetime(2026, 11, 16, 9, 0, tzinfo=MSK)
    assert one_day.moment == datetime.datetime(2026, 11, 17, 9, 0, tzinfo=MSK)
    assert on_date.moment == datetime.datetime(2026, 12, 1, 9, 0, tzinfo=MSK)

    events = _audit("tasks.reminder_set")
    assert len(events) == 3, f"записей tasks.reminder_set: {len(events)}"
    moments = {event.after.get("moment") for event in events}
    assert "2026-11-16T09:00" in str(moments) or any("16.11.2026" in str(value) for value in moments), moments


def test_manual_limit_ten_days_range_and_deadline_required_refusals():
    """FR-688, CONTRACT-009 12.1: одиннадцатое ручное напоминание — «Не больше 10 напоминаний на задачу»
    (`reminders_limit`), `days=0` — «Число рабочих дней — от 1 до 30» (`reminder_days_range`), «за N рабочих дней»
    без срока — «Для «за N рабочих дней» нужен срок задачи» (`reminder_deadline_required`); поле `reminder`, 200."""
    _, assignee = _pair()
    task = tasks_helpers.make_task(assignee=assignee, deadline=DEADLINE)
    client = support.logged_in(assignee)
    service = _svc("reminders")
    for days in range(1, 11):
        service.set_manual(assignee, task, days=days)

    response = client.post(f"/tasks/{task.pk}/remind/", {"days": "3"}, **support.HX)
    _refused(response, "reminder", "reminders_limit", "Не больше 10 напоминаний на задачу")

    zero = client.post(f"/tasks/{task.pk}/remind/", {"days": "0"}, **support.HX)
    _refused(zero, "reminder", "reminder_days_range", "Число рабочих дней — от 1 до 30")

    no_deadline = tasks_helpers.make_task(assignee=assignee, deadline=None, title="Без срока")
    required = client.post(f"/tasks/{no_deadline.pk}/remind/", {"days": "2"}, **support.HX)
    _refused(required, "reminder", "reminder_deadline_required", "Для «за N рабочих дней» нужен срок задачи")


def test_postpone_moves_one_working_day_and_only_then_sends():
    """FR-688: «Отложить» ставит `postponed_to` — следующий рабочий день от момента срабатывания; до этого срока
    задание уведомления не создаёт, после — создаёт одно «Срок наступил» и помечает `sent`."""
    author, assignee = _pair()
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE)
    _svc("reminders").plan(task)
    due = next(row for row in _rows(task) if row.kind == "auto_due" and row.user_id == assignee.pk)

    _svc("reminders").postpone(assignee, due)
    due.refresh_from_db()
    assert due.postponed_to == datetime.datetime(2026, 11, 19, 9, 0, tzinfo=MSK), (
        f"postponed_to: {due.postponed_to}")

    _job(datetime.datetime(2026, 11, 18, 12, 0, tzinfo=MSK))
    assert not _notes(kind="tasks.due").filter(user=assignee).exists(), "отложенное напоминание ушло раньше срока"

    _job(datetime.datetime(2026, 11, 19, 10, 0, tzinfo=MSK))
    due.refresh_from_db()
    assert due.state == "sent"
    assert _notes(kind="tasks.due").filter(user=assignee).count() == 1


# --- FR-690: пересчёт и снятие ---------------------------------------------------------------------------------

def test_deadline_change_recomputes_autos_and_days_keeps_on_date_and_removal_cancels_autos():
    """FR-690: смена срока пересчитывает автоматические и ручные «за N рабочих дней», «на дату» не меняется; снятие
    срока снимает автоматические и ручные «за N», а «на дату» остаётся `pending`."""
    author, assignee = _pair()
    days_task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE, title="С пересчётом")
    date_task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE, title="На дату")
    service, task_service = _svc("reminders"), _svc("tasks")
    from apps.core.widgets import moscow_today

    manual_on = moscow_today() + timedelta(days=40)
    service.set_manual(assignee, days_task, days=2)
    service.set_manual(assignee, date_task, on=manual_on)
    for task in (days_task, date_task):
        service.plan(task)

    new_deadline = moscow_today() + timedelta(days=30)
    while new_deadline.weekday() not in (1, 2, 3, 4):
        new_deadline += timedelta(days=1)
    manual_day = new_deadline
    for _ in range(2):
        manual_day -= timedelta(days=1)
        while manual_day.weekday() >= 5:
            manual_day -= timedelta(days=1)
    task_service.update(author, days_task, deadline=new_deadline)
    task_service.update(author, date_task, deadline=new_deadline)

    recomputed = _by_kind(days_task)
    def moments(day, hour=9):
        return datetime.datetime.combine(day, datetime.time(hour), tzinfo=MSK)
    assert recomputed["auto_due"][assignee.pk] == moments(new_deadline)
    assert recomputed["auto_soon"][assignee.pk] == moments(new_deadline - timedelta(days=1))
    assert recomputed["auto_overdue"][assignee.pk] == moments(new_deadline + timedelta(days=1))
    manual_days = [row for row in _rows(days_task) if row.kind == "manual"]
    assert [row.moment for row in manual_days] == [moments(manual_day)]
    manual_date = [row for row in _rows(date_task) if row.kind == "manual"]
    assert [row.moment for row in manual_date] == [moments(manual_on)], (
        "ручное «на дату» пересчитано вместе со сроком")

    task_service.update(author, days_task, deadline=None)
    task_service.update(author, date_task, deadline=None)
    assert not [row for row in _rows(days_task) if row.kind.startswith("auto") and row.state == "pending"]
    assert not [row for row in _rows(days_task) if row.kind == "manual" and row.state == "pending"], (
        "ручное «за N рабочих дней» не снято при снятии срока")
    assert [row for row in _rows(date_task) if row.kind == "manual" and row.state == "pending"], (
        "ручное «на дату» снято вместе со сроком")


def test_assignee_and_members_change_changes_recipients():
    """FR-690: смена состава меняет получателей — напоминания прежнего соисполнителя снимаются, новому ставятся,
    исполнитель остаётся получателем."""
    author, assignee = _pair()
    first = tasks_helpers.staff_user(full_name="Первый Соисполнитель")
    second = tasks_helpers.staff_user(full_name="Второй Соисполнитель")
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE)
    tasks_helpers.add_member(task, first)
    _svc("reminders").plan(task)
    assert {row.user_id for row in _pending(task)} == {assignee.pk, first.pk}

    _svc("tasks").update(author, task, members=[second])

    assert {row.user_id for row in _pending(task)} == {assignee.pk, second.pk}
    assert not [row for row in _rows(task) if row.user_id == first.pk and row.state == "pending"], (
        "напоминания прежнего соисполнителя остались")


def test_completion_and_deletion_cancel_all_reminders():
    """FR-689: перевод в «Готово» и мягкое удаление снимают все напоминания задачи — `pending` не остаётся,
    повторное задание ничего не отправляет."""
    author, assignee = _pair()
    done_task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE, title="Завершаемая")
    deleted_task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE, title="Удаляемая")
    service = _svc("reminders")
    for task in (done_task, deleted_task):
        service.plan(task)
        service.set_manual(assignee, task, days=1)

    _svc("tasks").change_status(assignee, done_task, "done")
    _svc("tasks").soft_delete(author, deleted_task)

    assert not _pending(done_task), "завершение не сняло напоминания"
    assert not _pending(deleted_task), "удаление не сняло напоминания"
    assert _job(NOW) == 0, "задание отправило или посчитало снятые напоминания"
    assert not _notes().filter(user=assignee).exists(), "задание отправило снятые напоминания"


# --- NFR-715: идемпотентность ----------------------------------------------------------------------------------

def test_job_is_idempotent_and_marks_sent():
    """NFR-715: задание выбирает `pending` с наступившим моментом, создаёт по уведомлению и помечает `sent`;
    повторный запуск не создаёт второго уведомления и не трогает журнал."""
    author, assignee = _pair()
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=DEADLINE)
    _svc("reminders").plan(task)
    now = datetime.datetime(2026, 11, 19, 10, 0, tzinfo=MSK)   # все три момента наступили

    first = _job(now)
    assert first >= 1
    created = _notes(user=assignee).count()
    assert created == 3, f"уведомлений исполнителю после первого запуска: {created}"
    assert not _pending(task)
    assert {row.state for row in _rows(task)} == {"sent"}

    second = _job(now)
    assert second == 0, f"повторный запуск вернул {second}"
    assert _notes(user=assignee).count() == created, "повторный запуск задвоил уведомления"