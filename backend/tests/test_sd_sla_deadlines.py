"""T-11102: расчёт рабочих сроков SLA (FR-734, FR-735, NFR-733).

Служба SLA ещё не реализована: импорт выполняется внутри тестов, поэтому
коллекция этого файла остаётся доступной до появления apps.servicedesk.services.sla.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests.support import model
from tests.support_servicedesk import make_level


pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")


def moment(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=MSK)


def calendar_settings(*, weekdays=(0, 1, 2, 3, 4), start=time(9), end=time(18)):
    row = model("org.WorkCalendar").objects.get()
    row.work_weekdays = list(weekdays)
    row.day_start = start
    row.day_end = end
    row.save(update_fields=("work_weekdays", "day_start", "day_end"))
    return row


def loaded_year(year, days=None):
    employee = support.make_employee()
    model("org.CalendarYear").objects.create(
        year=year,
        loaded_by=employee,
        file_name=f"calendar-{year}.csv",
        totals={},
    )
    special_day = model("org.SpecialDay")
    for day, kind in (days or {}).items():
        special_day.objects.create(
            date=day,
            kind=kind,
            origin="manual",
            changed_by=employee,
        )


def test_friday_evening_moves_reaction_to_next_workday():
    from apps.servicedesk.services.sla import deadline

    level = make_level(reaction_minutes=30, day_start=time(9), day_end=time(18))
    assert deadline(moment(2026, 6, 5, 17, 50), 30, level) == moment(2026, 6, 8, 9, 20)


def test_weekend_is_skipped():
    from apps.servicedesk.services.sla import deadline

    level = make_level(reaction_minutes=60)
    assert deadline(moment(2026, 6, 5, 18), 60, level) == moment(2026, 6, 8, 10)


def test_calendar_holiday_is_skipped():
    from apps.servicedesk.services.sla import deadline

    holiday = date(2026, 6, 8)
    loaded_year(2026, {holiday: "holiday"})
    level = make_level(reaction_minutes=60)
    assert deadline(moment(2026, 6, 5, 18), 60, level) == moment(2026, 6, 9, 10)


def test_day_off_is_skipped_but_moved_workday_counts_on_saturday():
    from apps.servicedesk.services.sla import deadline

    day_off = date(2026, 6, 6)
    workday = date(2026, 6, 13)
    loaded_year(2026, {day_off: "day_off", workday: "workday"})
    level = make_level(reaction_minutes=60, workdays=(5,))
    assert deadline(moment(2026, 6, 6, 9), 60, level) == moment(2026, 6, 13, 10)


def test_level_saturday_is_still_skipped_when_calendar_calls_it_weekend():
    from apps.servicedesk.services.sla import deadline

    level = make_level(reaction_minutes=60, workdays=(4, 5))
    assert deadline(moment(2026, 6, 5, 17, 30), 60, level) == moment(2026, 6, 12, 9, 30)


def test_short_day_uses_calendar_end_minus_hour_without_shortening_level():
    from apps.servicedesk.services.sla import deadline

    short = date(2026, 6, 8)
    loaded_year(2026, {short: "short"})
    level = make_level(reaction_minutes=180, day_start=time(9), day_end=time(12))
    assert deadline(moment(2026, 6, 8, 9), 180, level) == moment(2026, 6, 8, 12)


def test_all_day_has_24_working_hours_and_skips_holidays():
    from apps.servicedesk.services.sla import deadline

    holiday = date(2026, 6, 9)
    loaded_year(2026, {holiday: "holiday"})
    level = make_level(reaction_minutes=60, all_day=True)
    assert deadline(moment(2026, 6, 8, 23, 30), 60, level) == moment(2026, 6, 10, 0, 30)


def test_empty_intersection_is_skipped():
    from apps.servicedesk.services.sla import deadline

    calendar_settings(end=time(10))
    short = date(2026, 6, 8)
    loaded_year(2026, {short: "short"})
    level = make_level(reaction_minutes=5, day_start=time(9), day_end=time(17))
    assert deadline(moment(2026, 6, 8, 9), 5, level) == moment(2026, 6, 9, 9, 5)


def test_year_boundary_uses_calendar_days_in_next_year():
    from apps.servicedesk.services.sla import deadline

    loaded_year(2026)
    loaded_year(2027)
    level = make_level(reaction_minutes=60)
    assert deadline(moment(2026, 12, 31, 17, 30), 60, level) == moment(2027, 1, 1, 9, 30)


def test_leap_day_and_non_leap_year_are_calendar_transitions():
    from apps.servicedesk.services.sla import deadline

    level = make_level(reaction_minutes=60)
    assert deadline(moment(2028, 2, 28, 17, 30), 60, level) == moment(2028, 2, 29, 9, 30)
    assert deadline(moment(2027, 2, 26, 17, 30), 60, level) == moment(2027, 3, 1, 9, 30)


def test_minutes_between_counts_work_minutes_and_is_symmetric_by_magnitude():
    from apps.servicedesk.services.sla import minutes_between

    level = make_level()
    a, b = moment(2026, 6, 5, 17, 30), moment(2026, 6, 8, 9, 30)
    assert minutes_between(a, b, level) == 60
    assert minutes_between(b, a, level) == -minutes_between(a, b, level)


def test_minutes_between_skips_weekend_and_holiday():
    from apps.servicedesk.services.sla import minutes_between

    holiday = date(2026, 6, 8)
    loaded_year(2026, {holiday: "holiday"})
    level = make_level()
    # пятница 17:00–18:00 = 60 минут, понедельник 8 июня — праздник, вторник 09:00–10:00 = 60 минут
    assert minutes_between(moment(2026, 6, 5, 17), moment(2026, 6, 9, 10), level) == 120


def test_zero_work_minutes_outside_hours_moves_to_next_workday_start():
    from apps.servicedesk.services.sla import deadline

    level = make_level(reaction_minutes=5)
    assert deadline(moment(2026, 6, 8, 20), 0, level) == moment(2026, 6, 9, 9)


def test_minimum_and_thirty_day_deadlines_do_not_overflow():
    from apps.servicedesk.services.sla import deadline

    level = make_level(reaction_minutes=5)
    assert deadline(moment(2026, 6, 8, 9), 5, level) == moment(2026, 6, 8, 9, 5)
    due = deadline(moment(2026, 6, 8, 9), 43_200, level)
    assert isinstance(due, datetime)
    assert due > moment(2026, 6, 8, 9)
