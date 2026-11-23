"""Лестница напоминаний поручений (срез 010, T-10208; FR-709, 710; CONTRACT-010, раздел 8, К22).

Пороги зависят от длины срока; моменты — начало рабочего дня, сдвиг по тихим часам. Своя лестница `ladder`
используется целиком (`d<offset>`), умолчание настроек — только применимые к длине срока пороги.
"""
import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.instructions.models import InstructionReminder, InstructionReportDate
from apps.instructions.services import settings as settings_service
from apps.instructions.texts import InstructionsError

MSK = ZoneInfo("Europe/Moscow")
DEFAULT_OFFSETS = settings_service.DEFAULT_LADDER["offsets"]


def _add_months(day, months):
    import calendar

    total = day.year * 12 + day.month - 1 + months
    year, month = divmod(total, 12)
    month += 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _work_start(day):
    return datetime.datetime.combine(day, datetime.time(9), tzinfo=MSK)


def _is_work(day) -> bool:
    from apps.org.services import calendar

    return calendar.day_kind(day) not in ("off", "holiday", "day_off")


def _prev_work(day, count):
    current = day
    for _ in range(count):
        current -= datetime.timedelta(days=1)
        while not _is_work(current):
            current -= datetime.timedelta(days=1)
    return current


def _next_work(day):
    current = day + datetime.timedelta(days=1)
    while not _is_work(current):
        current += datetime.timedelta(days=1)
    return current


def _due_day(day):
    while not _is_work(day):
        day += datetime.timedelta(days=1)
    return day


def _length_offsets(instruction) -> list[int]:
    ladder = instruction.ladder or {}
    if ladder.get("offsets"):
        return [int(item) for item in ladder["offsets"]]
    created_on = timezone.localtime(instruction.created_at).date()
    if instruction.deadline <= _add_months(created_on, 1):
        allowed = 3
    elif instruction.deadline <= _add_months(created_on, 6):
        allowed = 14
    else:
        allowed = 60
    return [offset for offset in settings_service.get().default_ladder.get("offsets", DEFAULT_OFFSETS)
            if offset <= allowed]


def _flags(instruction) -> tuple[bool, bool]:
    ladder = instruction.ladder or {}
    settings_ladder = settings_service.get().default_ladder or {}
    return (ladder.get("due", settings_ladder.get("due", True)),
            ladder.get("overdue", settings_ladder.get("overdue", True)))


def _recipients(instruction) -> list:
    from apps.instructions.models import InstructionMember

    people = {instruction.assignee_id: instruction.assignee}
    for row in InstructionMember.objects.filter(instruction=instruction).select_related("user"):
        people[row.user_id] = row.user
    return list(people.values())


def _quiet(user, moment):
    from apps.notify.services import dispatch, quiet

    return quiet.next_start(dispatch.user_prefs(user.pk), moment)


def _store(instruction, user, kind, stage, moment, date=None):
    start = _quiet(user, moment) or moment
    row, _ = InstructionReminder.objects.get_or_create(
        instruction=instruction, date=date, user=user, kind=kind, stage=stage, state="pending",
        defaults={"moment": start})
    return row


def plan(instruction) -> list:
    """Поставить напоминания лестницы и отчётных дат получателям."""
    InstructionReminder.objects.filter(instruction=instruction, state="pending").delete()
    created_on = timezone.localtime(instruction.created_at).date()
    rows = []
    due_day = _due_day(instruction.deadline)
    for offset in _length_offsets(instruction):
        day = _prev_work(due_day, offset)
        if _work_start(day) <= instruction.created_at:
            continue
        for user in _recipients(instruction):
            rows.append(_store(instruction, user, "deadline", f"d{offset}", _work_start(day)))
    due_flag, overdue_flag = _flags(instruction)
    if due_flag and due_day >= created_on:
        for user in _recipients(instruction):
            rows.append(_store(instruction, user, "deadline", "due", _work_start(due_day)))
    if overdue_flag:
        for user in _recipients(instruction):
            rows.append(_store(instruction, user, "deadline", "overdue", _work_start(_next_work(due_day))))
    for date_row in InstructionReportDate.objects.filter(instruction=instruction):
        for offset, stage in ((3, "r3"), (1, "r1")):
            day = _prev_work(date_row.due_date, offset)
            if day < created_on:
                continue
            for user in _recipients(instruction):
                rows.append(_store(instruction, user, "report", stage, _work_start(day), date=date_row))
    return rows


def rebuild(instruction):
    """Пересчитать будущие напоминания, не трогая отправленные."""
    InstructionReminder.objects.filter(instruction=instruction, state="pending").delete()
    return plan(instruction)


def cancel_all(instruction, *, reason="") -> int:
    """Снять все `pending`-напоминания."""
    return InstructionReminder.objects.filter(instruction=instruction, state="pending").update(state="cancelled")


def due(now):
    """Напоминания с наступившим моментом."""
    return list(InstructionReminder.objects.filter(state="pending", moment__lte=now).select_related(
        "instruction", "user", "date").order_by("moment", "pk"))


def set_ladder(actor, instruction, ladder):
    """Править лестницу поручения (автор/контролёр), только будущие `pending`."""
    from apps.instructions.services import access

    if not access.can_edit_ladder(actor, instruction):
        raise InstructionsError("edit_forbidden", "ladder")
    instruction.ladder = settings_service.validate_ladder(ladder)
    instruction.save(update_fields=["ladder"])
    rebuild(instruction)
    return instruction