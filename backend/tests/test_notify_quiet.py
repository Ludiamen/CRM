"""T-4110: тихие часы сотрудника — рабочий календарь, «свои часы», «без тихих часов», срок сводки (FR-323, FR-329,
FR-330). Сценарии 4 и 7 спеки среза 004.

Служба `quiet` считает по Москве: `is_working` и `next_start` берут календарь среза 002
(`apps.org.services.calendar`), свои дни и интервал или «без тихих часов». Срок сводки (`digest_due_at`)
ставят `dispatch.plan_digest` и `dispatch.replan_digest` (CONTRACT-004, 6.4, 6.6, 6.7). Код среза 004 на уровне
модуля не импортируется: имена берутся внутри тестов (CONTRACT-004, шапка). Помощники, нужные только этому файлу
(календарь, строка настроек, час по Москве), лежат здесь.
"""
import datetime
import importlib
import logging
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
UTC = datetime.timezone.utc
DISPATCH_LOGGER = "apps.notify.services.dispatch"
# проверено скриптом: 2026-06-15 — понедельник (день 0), 06-16 вторник, 06-17 среда, 06-18 четверг, 06-19 пятница,
# 06-20 суббота, 06-21 воскресенье; 06-11 четверг, 06-12 пятница, 06-13 суббота, 06-14 воскресенье
MON, TUE, WED, THU, FRI, SAT, SUN = (date(2026, 6, 15) + timedelta(days=i) for i in range(7))
PREV_THU, PREV_FRI, PREV_SAT = date(2026, 6, 11), date(2026, 6, 12), date(2026, 6, 13)
WEEK = [0, 1, 2, 3, 4]


# --- помощники только этого файла -------------------------------------------------------------------

def at(day: date, hour: int = 0, minute: int = 0) -> datetime.datetime:
    """Момент по Москве."""
    return datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)


def _quiet():
    return importlib.import_module("apps.notify.services.quiet")


def _dispatch():
    return importlib.import_module("apps.notify.services.dispatch")


def _prefs_service():
    return importlib.import_module("apps.notify.services.prefs")


def _calendar(*, weekdays=WEEK, start=time(9, 0), end=time(18, 0)):
    """Одна строка рабочего календаря: дни недели и границы рабочего дня (без загруженных лет)."""
    WorkCalendar = model("org.WorkCalendar")
    row = WorkCalendar.objects.first() or WorkCalendar.objects.create()
    row.work_weekdays, row.day_start, row.day_end = list(weekdays), start, end
    row.save()
    return row


def _seed_year(year: int, days: dict):
    """Загруженный год с особыми днями `{date: kind}` напрямую в базе."""
    by = support.make_employee()
    now = datetime.datetime.now(UTC)
    model("org.CalendarYear").objects.create(
        year=year, loaded_at=now, loaded_by=by, file_name=f"cal{year}.csv",
        totals={k: 0 for k in ("holidays_on_weekdays", "moved_days_off", "moved_workdays", "short_days", "work_days")})
    SpecialDay = model("org.SpecialDay")
    SpecialDay.objects.bulk_create([
        SpecialDay(date=day, kind=kind, origin="file", changed_by=by, changed_at=now) for day, kind in days.items()])


def _own(user=None, *, days, start, end):
    """Строка настроек сотрудника в режиме «Свои часы» (создаётся напрямую в базе)."""
    user = user or support.make_employee()
    return model("notify.UserNotifySettings").objects.create(
        user=user, quiet_mode="own", own_days=list(days), own_start=start, own_end=end)


def _none_mode(user=None):
    user = user or support.make_employee()
    return model("notify.UserNotifySettings").objects.create(user=user, quiet_mode="none")


def _held(user, channel: str = "telegram"):
    """Доставка в состоянии `held` (накоплена в тихие часы) у нового уведомления сотрудника."""
    note = model("notify.Notification").objects.create(user=user, kind="test.held", text="Накоплено", url="/me/")
    return model("notify.Delivery").objects.create(notification=note, channel=channel, state="held", due_at=None)


def _row(user):
    return model("notify.UserNotifySettings").objects.get(user=user)


# --- «По рабочему календарю компании» ----------------------------------------------------------------

def test_calendar_mode_holiday_is_quiet():
    """FR-323: праздник на будний день — тихие часы режима «по календарю»; соседний обычный день в те же часы рабочий."""
    quiet = _quiet()
    _calendar()
    _seed_year(2026, {PREV_FRI: "holiday"})
    assert quiet.is_working(None, at(PREV_FRI, 12, 0)) is False
    assert quiet.is_working(None, at(PREV_THU, 12, 0)) is True
    row = model("notify.UserNotifySettings").objects.create(user=support.make_employee(), quiet_mode="calendar")
    assert quiet.is_working(row, at(PREV_FRI, 12, 0)) is False


def test_calendar_mode_transferred_working_day_is_working():
    """FR-323: перенесённый рабочий день в субботу — рабочее время, обычная суббота — тихие часы."""
    quiet = _quiet()
    _calendar()
    _seed_year(2026, {PREV_SAT: "workday"})
    assert quiet.is_working(None, at(PREV_SAT, 12, 0)) is True
    assert quiet.is_working(None, at(SAT, 12, 0)) is False


def test_calendar_mode_short_day_ends_earlier():
    """FR-323: сокращённый день заканчивается на час раньше (17:00 при конце 18:00; конец не входит в рабочее время)."""
    quiet = _quiet()
    _calendar()
    _seed_year(2026, {PREV_THU: "short"})
    assert quiet.is_working(None, at(PREV_THU, 16, 59)) is True
    assert quiet.is_working(None, at(PREV_THU, 17, 0)) is False
    assert quiet.is_working(None, at(WED, 17, 0)) is True, "обычный день работает до 18:00"


def test_calendar_mode_next_start_skips_holidays():
    """FR-323: начало ближайшего рабочего времени пропускает праздники и выходные: в четверг после конца дня при
    празднике в пятницу и в понедельник — вторник 09:00."""
    quiet = _quiet()
    _calendar()
    _seed_year(2026, {PREV_FRI: "holiday", MON: "holiday"})
    result = quiet.next_start(None, at(PREV_THU, 19, 0))
    assert result == at(TUE, 9, 0)
    assert result.utcoffset() == timedelta(hours=3)


def test_calendar_mode_next_start_none_when_no_working_day_in_400_days():
    """FR-323: если за 400 суток рабочего дня нет (в календаре нет рабочих дней недели), `next_start` отдаёт `None`."""
    quiet = _quiet()
    _calendar(weekdays=[])
    assert quiet.is_working(None, at(WED, 12, 0)) is False
    assert quiet.next_start(None, at(WED, 12, 0)) is None


def test_calendar_mode_no_next_start_means_no_digest_planned_and_warning_logged(clock, caplog):
    """FR-323, FR-330: рабочего дня за 400 суток нет — срок сводки не ставится, возвращается `None`, а в журнал
    приложения (логгер `apps.notify.services.dispatch`) пишется предупреждение без почты сотрудника."""
    _calendar(weekdays=[])
    clock.set(at(WED, 12, 0))
    user = support.make_employee()
    with caplog.at_level(logging.WARNING, logger=DISPATCH_LOGGER):
        assert _dispatch().plan_digest(user.pk) is None
    assert _row(user).digest_due_at is None
    warnings = [r for r in caplog.records if r.name == DISPATCH_LOGGER and r.levelno == logging.WARNING]
    assert warnings, "предупреждение о том, что сводку планировать некуда"
    assert all(user.email not in r.getMessage() for r in warnings)


# --- «Свои часы» ---------------------------------------------------------------------------------------

def test_own_hours_midnight_interval_monday_2000_is_working():
    """FR-323: при «с 20:00 до 08:00» в отмеченный понедельник 20:00 — рабочее время (начало входит)."""
    row = _own(days=[0], start=time(20, 0), end=time(8, 0))
    assert _quiet().is_working(row, at(MON, 20, 0)) is True
    assert _quiet().is_working(row, at(MON, 19, 59)) is False


def test_own_hours_midnight_interval_tuesday_0759_is_working():
    """FR-323 (решение 32): при «с 20:00 до 08:00» вторник 07:59 — рабочее время понедельника, хотя вторник не отмечен."""
    row = _own(days=[0], start=time(20, 0), end=time(8, 0))
    assert _quiet().is_working(row, at(TUE, 7, 59)) is True


def test_own_hours_midnight_interval_tuesday_0800_is_quiet():
    """FR-323 (решение 32): конец интервала в рабочее время не входит — вторник ровно 08:00 уже тихие часы."""
    row = _own(days=[0], start=time(20, 0), end=time(8, 0))
    assert _quiet().is_working(row, at(TUE, 8, 0)) is False
    assert _quiet().is_working(row, at(TUE, 12, 0)) is False


def test_own_hours_midnight_interval_belongs_to_start_day():
    """FR-323: ночной интервал относится ко дню начала: при отмеченном только вторнике утро вторника (хвост
    интервала понедельника) тихое, а вечер вторника и утро среды — рабочие; понедельник с вечера не работает."""
    quiet = _quiet()
    row = _own(days=[1], start=time(20, 0), end=time(8, 0))
    assert quiet.is_working(row, at(TUE, 7, 59)) is False, "понедельник не отмечен: хвост его интервала не считается"
    assert quiet.is_working(row, at(TUE, 21, 0)) is True
    assert quiet.is_working(row, at(WED, 7, 59)) is True
    assert quiet.is_working(row, at(WED, 8, 0)) is False
    assert quiet.is_working(row, at(MON, 21, 0)) is False


def test_own_hours_same_day_interval_inside_and_outside():
    """FR-323: интервал внутри суток «с 10:00 до 12:00»: начало входит, конец нет, неотмеченный день тихий."""
    quiet = _quiet()
    row = _own(days=WEEK, start=time(10, 0), end=time(12, 0))
    assert quiet.is_working(row, at(WED, 10, 0)) is True
    assert quiet.is_working(row, at(WED, 11, 59)) is True
    assert quiet.is_working(row, at(WED, 9, 59)) is False
    assert quiet.is_working(row, at(WED, 12, 0)) is False
    assert quiet.is_working(row, at(SAT, 11, 0)) is False, "суббота не отмечена"


def test_own_hours_ignore_holidays():
    """FR-323: в режиме «Свои часы» праздники не учитываются (в отличие от календаря компании), а перенесённый
    рабочий день не делает неотмеченную субботу рабочей."""
    quiet = _quiet()
    _calendar()
    _seed_year(2026, {WED: "holiday", PREV_SAT: "workday"})
    row = _own(days=WEEK, start=time(9, 0), end=time(18, 0))
    assert quiet.is_working(row, at(WED, 12, 0)) is True
    assert quiet.is_working(None, at(WED, 12, 0)) is False, "для календаря компании тот же день — праздник"
    assert quiet.is_working(row, at(PREV_SAT, 12, 0)) is False


# --- «Без тихих часов» ------------------------------------------------------------------------------------

def test_none_mode_is_always_working():
    """FR-323: «Без тихих часов» — любое время рабочее: ночь, суббота, праздник."""
    quiet = _quiet()
    _calendar()
    _seed_year(2026, {WED: "holiday"})
    row = _none_mode()
    for moment in (at(WED, 12, 0), at(SAT, 3, 0), at(MON, 23, 59), at(SUN, 0, 0)):
        assert quiet.is_working(row, moment) is True, moment


def test_none_mode_next_start_is_now():
    """FR-323: при «Без тихих часов» ближайшее начало — сам момент."""
    moment = at(SAT, 3, 30)
    assert _quiet().next_start(_none_mode(), moment) == moment


def test_own_hours_next_start_inside_interval_is_now():
    """FR-323: внутри «своих часов» ближайшее начало — сам момент."""
    row = _own(days=WEEK, start=time(10, 0), end=time(12, 0))
    moment = at(WED, 11, 0)
    assert _quiet().next_start(row, moment) == moment


def test_own_hours_next_start_outside_interval_is_next_start_day():
    """FR-323: вне «своих часов» ближайшее начало — первое начало интервала отмеченного дня строго позже момента:
    сегодня позже, на следующий отмеченный день или через выходные."""
    quiet = _quiet()
    row = _own(days=[0, 2], start=time(10, 0), end=time(12, 0))
    assert quiet.next_start(row, at(MON, 9, 0)) == at(MON, 10, 0)
    assert quiet.next_start(row, at(MON, 13, 0)) == at(WED, 10, 0)
    assert quiet.next_start(row, at(WED, 12, 0)) == at(WED + timedelta(days=5), 10, 0), "следующий понедельник"
    result = quiet.next_start(row, at(TUE, 11, 0))
    assert result == at(WED, 10, 0) and result.utcoffset() == timedelta(hours=3)


# --- проверка ввода «своих часов» -------------------------------------------------------------------------

def test_own_hours_rejects_equal_start_and_end():
    """FR-323: «с» равно «до» — отказ `own_same_time` с полем `own_end`."""
    from apps.notify.services import NotifyError

    with pytest.raises(NotifyError) as error:
        _quiet().validate_own_hours([0, 1], time(9, 0), time(9, 0))
    assert error.value.code == "own_same_time" and error.value.field == "own_end"


def test_own_hours_rejects_no_days():
    """FR-323: ни одного дня — отказ `own_no_days` с полем `own_days`."""
    from apps.notify.services import NotifyError

    with pytest.raises(NotifyError) as error:
        _quiet().validate_own_hours([], time(9, 0), time(18, 0))
    assert error.value.code == "own_no_days" and error.value.field == "own_days"


def test_own_hours_accepts_start_later_than_end():
    """FR-323: «с» позже «до» допустимо (интервал через полночь); дни возвращаются по возрастанию без повторов."""
    result = _quiet().validate_own_hours([2, 0, 2], time(20, 0), time(8, 0))
    assert result == ([0, 2], time(20, 0), time(8, 0))


# --- пояс ------------------------------------------------------------------------------------------------

def test_times_are_computed_in_moscow_zone():
    """FR-323 (NFR-307): время считается по Москве, а не по поясу переданного момента: 06:30 UTC — 09:30 по Москве
    (рабочее по календарю), 05:30 UTC — 08:30 (тихое); 08:00 UTC — 11:00 по Москве (внутри «своих часов» 10-12)."""
    quiet = _quiet()
    _calendar()
    assert quiet.is_working(None, datetime.datetime(2026, 6, 15, 6, 30, tzinfo=UTC)) is True
    assert quiet.is_working(None, datetime.datetime(2026, 6, 15, 5, 30, tzinfo=UTC)) is False
    row = _own(days=[0], start=time(10, 0), end=time(12, 0))
    assert quiet.is_working(row, datetime.datetime(2026, 6, 15, 8, 0, tzinfo=UTC)) is True
    moment = datetime.datetime(2026, 6, 15, 12, 0, tzinfo=UTC)  # 15:00 по Москве, понедельник
    assert quiet.next_start(row, moment) == at(MON + timedelta(days=7), 10, 0)
    night = _own(days=[0], start=time(20, 0), end=time(8, 0))
    assert quiet.is_working(night, datetime.datetime(2026, 6, 15, 17, 30, tzinfo=UTC)) is True, "20:30 по Москве"


# --- накопление и срок сводки -----------------------------------------------------------------------------

def test_own_hours_event_outside_hours_holds_external_deliveries(
        clock, bus, bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-323, FR-329: событие вне «своих часов» не отправляет Web Push, Telegram и MAX — их доставки `held` без срока
    и без постановки в очередь; письмо ждёт срока (создано + задержка) и по обходу тоже становится `held`; срок
    сводки — начало ближайшего интервала."""
    from apps.core import events, extensions
    from apps.core.extensions import Draft, NotificationKind

    user = support.make_employee()
    clock.set(at(WED, 15, 0))
    _own(user, days=WEEK, start=time(10, 0), end=time(12, 0))
    notify.subscribe(user)
    ChatBinding = model("notify.ChatBinding")
    ChatBinding.objects.create(user=user, channel="telegram", chat_id="1001")
    ChatBinding.objects.create(user=user, channel="max", chat_id="2002")
    event = "test.quiet_happened"
    kind = NotificationKind(
        code="test.quiet", title="Тестовый вид", module="Тест", events=(event,),
        default_channels=("portal", "email", "push", "telegram", "max"),
        build=lambda name, data: [Draft(user_id=data["user_id"], text="Вне часов", url="/me/", object_ref="t:1")])
    with extensions.empty():
        notify.register_kind(kind)
        with django_capture_on_commit_callbacks(execute=True):
            events.publish(event, user_id=user.pk)
    note = model("notify.Notification").objects.get(user=user, kind=kind.code)
    by_channel = {d.channel: d for d in model("notify.Delivery").objects.filter(notification=note)}
    assert sorted(by_channel) == ["email", "max", "telegram", "webpush"]
    for channel in ("webpush", "telegram", "max"):
        delivery = by_channel[channel]
        assert (delivery.state, delivery.due_at, delivery.enqueued_at) == ("held", None, None), channel
    delay = model("notify.NotifySettings").objects.get(pk=1).email_delay_minutes
    assert by_channel["email"].state == "waiting" and by_channel["email"].due_at == note.created_at + timedelta(minutes=delay)
    assert notify.queued() == [], "в тихие часы ничего не ставится в очередь отправки"
    assert _row(user).digest_due_at == at(THU, 10, 0)
    clock.advance(minutes=delay + 1)  # срок письма наступил, но тихие часы ещё идут
    with django_capture_on_commit_callbacks(execute=True):
        importlib.import_module("apps.notify.services.mail").send_due()
    email = model("notify.Delivery").objects.get(pk=by_channel["email"].pk)
    assert (email.state, email.due_at, email.mail_id) == ("held", None, None)
    assert _row(user).digest_due_at == at(THU, 10, 0)


def test_changing_quiet_mode_recalculates_digest_due_at(clock):
    """FR-330: смена режима пересчитывает срок сводки при накопленных доставках: прежний срок заменяется
    началом ближайшего рабочего времени по новым часам (а не берётся меньшее)."""
    user = support.make_employee()
    clock.set(at(MON, 11, 0))
    model("notify.UserNotifySettings").objects.create(user=user, digest_due_at=at(MON, 12, 0))
    _held(user)
    assert _prefs_service().save(user, quiet_mode="own", own_days=[0], own_start=time(14, 0), own_end=time(16, 0)) is True
    row = _row(user)
    assert row.quiet_mode == "own"
    assert row.digest_due_at == at(MON, 14, 0)


def test_switch_to_none_sets_digest_due_at_now(clock):
    """FR-330: переход на «Без тихих часов» при накопленных доставках ставит срок сводки «сейчас»."""
    user = support.make_employee()
    now = at(SAT, 11, 0)
    clock.set(now)
    model("notify.UserNotifySettings").objects.create(user=user, digest_due_at=at(MON, 9, 0))
    _held(user)
    assert _prefs_service().save(user, quiet_mode="none") is True
    row = _row(user)
    assert row.quiet_mode == "none"
    assert row.digest_due_at == now


def test_switch_to_none_without_held_deliveries_plans_no_digest(clock):
    """FR-330: накопленных доставок нет — после смены режима срока сводки нет (прежний срок снят), сводка не планируется."""
    user = support.make_employee()
    clock.set(at(SAT, 11, 0))
    model("notify.UserNotifySettings").objects.create(user=user, digest_due_at=at(MON, 9, 0))
    assert _prefs_service().save(user, quiet_mode="none") is True
    assert _row(user).digest_due_at is None
    assert _dispatch().replan_digest(user.pk) is None


def test_employee_without_settings_row_is_in_calendar_mode():
    """FR-323: у сотрудника без строки настроек действует режим «по календарю»: `row_of` даёт `None`, `quiet`
    считает по календарю компании, строки не создаётся."""
    quiet = _quiet()
    _calendar()
    user = support.make_employee()
    assert _prefs_service().row_of(user.pk) is None
    assert quiet.is_working(None, at(MON, 12, 0)) is True
    assert quiet.is_working(None, at(SAT, 12, 0)) is False
    assert quiet.next_start(None, at(SAT, 12, 0)) == at(MON, 9, 0)
    assert not model("notify.UserNotifySettings").objects.filter(user=user).exists()
