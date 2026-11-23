"""Отчётные даты поручения (срез 010, T-10204; FR-705, 717; CONTRACT-010, раздел 7, К21).

Периодичность не хранится: `build`/`rebuild` получают её из формы. Ряд начинается строго после даты постановки и
обрезается строго до срока; дата, равная сроку, не создаётся. Даты с отчётами переживают пересборку.
"""
import calendar
import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.widgets import moscow_today
from apps.instructions.models import InstructionReportDate
from apps.instructions.texts import InstructionsError

PERIODICITIES = ("weekly", "monthly", "quarterly")


def _local_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.datetime.strptime(value.strip(), pattern).date()
            except ValueError:
                continue
        raise InstructionsError("date_past", "dates") from None
    raise InstructionsError("date_past", "dates")


def _add_months(day: datetime.date, months: int) -> datetime.date:
    total = day.year * 12 + day.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day.day, last))


def _series(created_on: datetime.date, deadline: datetime.date, periodicity: str) -> list[datetime.date]:
    if periodicity not in PERIODICITIES:
        raise InstructionsError("periodicity_invalid", "periodicity")
    days = []
    index = 1
    while index <= 500:
        if periodicity == "weekly":
            day = created_on + datetime.timedelta(days=7 * index)
        elif periodicity == "monthly":
            day = _add_months(created_on, index)
        else:
            day = _add_months(created_on, 3 * index)
        if day >= deadline:
            break
        days.append(day)
        index += 1
    return days


@transaction.atomic
def build(instruction, *, periodicity="", dates=()) -> list[InstructionReportDate]:
    """Построить ряд отчётных дат из периодичности и/или списка; существующие не дублируются."""
    created_on = timezone.localtime(instruction.created_at).date()
    days = _series(created_on, instruction.deadline, periodicity) if periodicity else []
    for value in dates or ():
        day = _local_date(value)
        if day <= moscow_today():
            raise InstructionsError("date_past", "dates")
        if day >= instruction.deadline:
            raise InstructionsError("date_not_before_deadline", "dates")
        days.append(day)
    unique = sorted(set(days))
    rows = []
    for position, day in enumerate(unique):
        row, _ = InstructionReportDate.objects.get_or_create(
            instruction=instruction, due_date=day, defaults={"position": position})
        rows.append(row)
    return rows


def _has_report(date) -> bool:
    return date.reports.exists()


@transaction.atomic
def rebuild(instruction, *, deadline=None, periodicity=None, dates=None) -> list[InstructionReportDate]:
    """Пересобрать будущие даты без отчётов; даты с отчётами сохраняются."""
    if deadline is not None:
        instruction.deadline = _local_date(deadline)
        instruction.save(update_fields=["deadline"])
    generated = set(_series(timezone.localtime(instruction.created_at).date(), instruction.deadline,
                            periodicity)) if periodicity else set()
    for value in dates or ():
        generated.add(_local_date(value))
    existing = list(InstructionReportDate.objects.filter(instruction=instruction))
    reported = [row for row in existing if _has_report(row)]
    if periodicity and reported and any(row.due_date not in generated for row in reported):
        raise InstructionsError("dates_locked", "periodicity")
    today = moscow_today()
    for row in existing:
        if not _has_report(row) and row.due_date >= today:
            row.delete()
    if periodicity:
        build(instruction, periodicity=periodicity)
    for value in dates or ():
        build(instruction, dates=(value,))
    return list(InstructionReportDate.objects.filter(instruction=instruction).order_by("due_date", "pk"))


def next_open(instruction):
    """Ближайшая дата без решения `accepted`; все приняты — `None`."""
    return (InstructionReportDate.objects.filter(instruction=instruction)
            .exclude(state="accepted").order_by("due_date", "pk").first())


def state_of(instruction) -> str:
    """Код состояния поручения по ближайшей незакрытой дате или сроку (FR-717)."""
    if instruction.closed_at is not None or instruction.deleted_at is not None:
        return "done"
    today = moscow_today()
    nearest = next_open(instruction)
    nearest_day = nearest.due_date if nearest is not None else None
    if instruction.deadline < today or (nearest_day is not None and nearest_day < today):
        return "overdue"
    if nearest is not None:
        if nearest.state == "review":
            return "review"
        if nearest.state == "returned":
            return "returned"
        if nearest.state == "waiting" and nearest.due_date <= today:
            return "waiting"
        return "control"
    if instruction.deadline <= today:
        return "waiting"
    return "control"


STATE_TITLES = {
    "control": "На контроле",
    "waiting": "Ждёт отчёта",
    "review": "Отчёт на проверке",
    "returned": "Возвращено",
    "overdue": "Просрочено",
    "done": "Исполнено",
}