"""Срез 010 «Поручения»: отчётные даты и статусы (T-10104; FR-705, FR-717).

`apps.instructions.services.dates` — CONTRACT-010, раздел 7 и К21. Код среза импортируется внутри тестов: сбор
проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.utils import timezone

from tests import support
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

DAY = datetime.date
UTC = datetime.timezone.utc


def dates():
    from apps.instructions.services import dates as module
    return module


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def _at(day):
    return datetime.datetime.combine(day, datetime.time(10), tzinfo=UTC)


def _instr(created_on, deadline, **extra):
    row = ins.make_instruction(deadline=deadline, **extra)
    support.model("instructions.Instruction").objects.filter(pk=row.pk).update(created_at=_at(created_on))
    row.refresh_from_db()
    return row


def _report(row, date_obj=None, decision="pending", state=None):
    report = support.model("instructions.InstructionReport").objects.create(
        instruction=row, date=date_obj, author=row.assignee, text="Отчёт", decision=decision)
    if date_obj is not None and state is not None:
        date_obj.state = state
        date_obj.closed_at = timezone.now() if state == "accepted" else None
        date_obj.save(update_fields=["state", "closed_at"])
    return report


def _due(rows):
    return [row.due_date for row in rows]


def test_weekly_starts_next_week_and_is_cut_strictly_before_deadline():
    """FR-705: еженедельно — тот же день недели, начиная со следующего дня после постановки; ряд обрезается
    строго до срока (дата, равная сроку, не создаётся)."""
    row = _instr(DAY(2026, 1, 5), DAY(2026, 2, 2))  # понедельник
    built = dates().build(row, periodicity="weekly")
    assert _due(built) == [DAY(2026, 1, 12), DAY(2026, 1, 19), DAY(2026, 1, 26)]
    assert support.model("instructions.InstructionReportDate").objects.filter(instruction=row).count() == 3


def test_date_equal_to_deadline_is_not_created():
    """FR-705, FR-706: дата, равная сроку, не создаётся — итоговый отчёт «к сроку» один."""
    row = _instr(DAY(2026, 1, 5), DAY(2026, 1, 12))
    assert dates().build(row, periodicity="weekly") == []
    assert not support.model("instructions.InstructionReportDate").objects.filter(instruction=row).exists()


def test_monthly_same_day_and_last_day_of_short_month():
    """FR-705: ежемесячно — то же число; 31-е в коротком месяце — последний день месяца."""
    row = _instr(DAY(2026, 1, 31), DAY(2026, 5, 1))
    assert _due(dates().build(row, periodicity="monthly")) == [
        DAY(2026, 2, 28), DAY(2026, 3, 31), DAY(2026, 4, 30)]


def test_leap_day_and_non_leap_february():
    """FR-705: 29 февраля в високосный год сохраняется, в невисокосный — 28 февраля."""
    leap = _instr(DAY(2024, 1, 29), DAY(2024, 4, 1))
    assert _due(dates().build(leap, periodicity="monthly")) == [DAY(2024, 2, 29), DAY(2024, 3, 29)]
    plain = _instr(DAY(2025, 1, 29), DAY(2025, 4, 1))
    assert _due(dates().build(plain, periodicity="monthly")) == [DAY(2025, 2, 28), DAY(2025, 3, 29)]


def test_quarterly_starts_next_quarter():
    """FR-705: ежеквартально — то же число через три месяца от постановки."""
    row = _instr(DAY(2026, 1, 15), DAY(2026, 12, 31))
    assert _due(dates().build(row, periodicity="quarterly")) == [
        DAY(2026, 4, 15), DAY(2026, 7, 15), DAY(2026, 10, 15)]


def test_manual_dates_reject_past_and_deadline_and_collapse_duplicates():
    """FR-705: прошедшая дата — `date_past`; дата не раньше срока — `date_not_before_deadline`; совпадающие даты
    схлопываются, ряд периодичности и список дат дают одну строку."""
    today = ins._today()
    row = _instr(today, today + datetime.timedelta(days=30))
    err = _err(lambda: dates().build(row, dates=[today - datetime.timedelta(days=1)]))
    assert (err.code, err.field) == ("date_past", "dates")
    err = _err(lambda: dates().build(row, dates=[row.deadline]))
    assert (err.code, err.field) == ("date_not_before_deadline", "dates")

    first = today + datetime.timedelta(days=7)
    built = dates().build(row, dates=[first, first])
    assert _due(built) == [first]


def test_periodicity_invalid():
    """FR-705: периодичность — только еженедельно, ежемесячно или ежеквартально."""
    row = _instr(ins._today(), ins._today() + datetime.timedelta(days=30))
    err = _err(lambda: dates().build(row, periodicity="daily"))
    assert (err.code, err.field) == ("periodicity_invalid", "periodicity")


def test_rebuild_keeps_dates_with_reports_and_regenerates_future():
    """FR-705: смена срока пересобирает только будущие даты без отчётов; дата с принятым отчётом сохраняется."""
    today = ins._today()
    row = _instr(today, today + datetime.timedelta(days=28))
    built = dates().build(row, periodicity="weekly")
    first = built[0]
    _report(row, first, decision="accepted", state="accepted")

    row.deadline = today + datetime.timedelta(days=42)
    row.save(update_fields=["deadline"])
    rebuilt = dates().rebuild(row, deadline=row.deadline, periodicity="weekly")
    assert _due(rebuilt) == [today + datetime.timedelta(days=7), today + datetime.timedelta(days=14),
                             today + datetime.timedelta(days=21), today + datetime.timedelta(days=28),
                             today + datetime.timedelta(days=35)]
    assert support.model("instructions.InstructionReportDate").objects.get(pk=first.pk).state == "accepted"


def test_rebuild_keeps_early_report_to_future_date():
    """FR-705: отчёт, отправленный заранее к будущей дате, переживает пересборку."""
    today = ins._today()
    row = _instr(today, today + datetime.timedelta(days=21))
    built = dates().build(row, periodicity="weekly")
    future = built[-1]
    _report(row, future, state="review")
    row.deadline = today + datetime.timedelta(days=35)
    row.save(update_fields=["deadline"])
    rebuilt = dates().rebuild(row, deadline=row.deadline, periodicity="weekly")
    assert future.due_date in _due(rebuilt)
    assert support.model("instructions.InstructionReportDate").objects.get(pk=future.pk).state == "review"


def test_periodicity_change_with_reports_is_locked():
    """FR-705, К21: смена периодичности при датах с отчётами отклоняется (`dates_locked`)."""
    row = _instr(DAY(2026, 1, 5), DAY(2026, 3, 2))
    built = dates().build(row, periodicity="weekly")
    _report(row, built[0], state="review")
    err = _err(lambda: dates().rebuild(row, periodicity="monthly"))
    assert (err.code, err.field) == ("dates_locked", "periodicity")


def test_next_open_is_nearest_not_accepted_or_none():
    """FR-717: `next_open` — ближайшая дата без `accepted`; все приняты — `None`."""
    row = _instr(DAY(2026, 1, 5), DAY(2026, 2, 2))
    assert dates().next_open(row) is None
    built = dates().build(row, periodicity="weekly")
    assert dates().next_open(row).pk == built[0].pk
    _report(row, built[0], decision="accepted", state="accepted")
    assert dates().next_open(row).pk == built[1].pk
    _report(row, built[1], decision="accepted", state="accepted")
    _report(row, built[2], decision="accepted", state="accepted")
    assert dates().next_open(row) is None


def test_state_of_follows_dates_and_deadline():
    """FR-717: «На контроле», «Ждёт отчёта», «Отчёт на проверке», «Возвращено», «Просрочено», «Исполнено»;
    «Просрочено» по сроку или ближайшей дате выше остальных, кроме «Исполнено»."""
    today = ins._today()
    assert dates().state_of(_instr(today, today + datetime.timedelta(days=5))) == "control"
    assert dates().state_of(_instr(today, today)) == "waiting"
    assert dates().state_of(_instr(today, today - datetime.timedelta(days=1))) == "overdue"

    row = _instr(today, today + datetime.timedelta(days=20))
    due_today = ins.add_report_date(row, today, position=0)
    assert dates().state_of(row) == "waiting"
    due_today.due_date = today - datetime.timedelta(days=1)
    due_today.save(update_fields=["due_date"])
    assert dates().state_of(row) == "overdue"

    future = _instr(today, today + datetime.timedelta(days=20))
    due = ins.add_report_date(future, today + datetime.timedelta(days=5))
    _report(future, due, state="review")
    assert dates().state_of(future) == "review"
    due.state = "returned"
    due.save(update_fields=["state"])
    assert dates().state_of(future) == "returned"
    due.state = "accepted"
    due.closed_at = timezone.now()
    due.save(update_fields=["state", "closed_at"])
    assert dates().state_of(future) == "control"

    future.closed_at = timezone.now()
    future.save(update_fields=["closed_at"])
    assert dates().state_of(future) == "done"


def test_past_date_under_review_is_overdue_by_priority():
    """FR-717: «Просрочено» по ближайшей дате выше остальных, кроме «Исполнено» — даже если отчёт на проверке."""
    today = ins._today()
    row = _instr(today, today + datetime.timedelta(days=20))
    due = ins.add_report_date(row, today - datetime.timedelta(days=1))
    _report(row, due, state="review")
    assert dates().state_of(row) == "overdue"