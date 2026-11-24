"""Расчёт и применение сроков SLA (PLAN-011, FR-734…737)."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.org.services import calendar
from apps.org.models import WorkCalendar

from ..models import SlaBinding, SlaCycle, SlaLevel

MSK = ZoneInfo("Europe/Moscow")
OFF = {"off", "holiday", "day_off"}


def _schedule(level):
    if isinstance(level, dict):
        return level
    return {
        "workdays": list(level.workdays),
        "day_start": level.day_start.strftime("%H:%M"),
        "day_end": level.day_end.strftime("%H:%M"),
        "all_day": bool(level.all_day),
    }


def _at(day, value):
    if isinstance(value, str):
        value = time.fromisoformat(value)
    return datetime.combine(day, value, tzinfo=MSK)


def day_intervals(level, day):
    """Возвращает рабочие интервалы даты по расписанию уровня и календарю компании."""
    schedule = _schedule(level)
    kind = calendar.day_kind(day)
    if day.weekday() not in schedule["workdays"] or kind in OFF:
        return []
    if schedule.get("all_day"):
        return [(_at(day, time.min), _at(day + timedelta(days=1), time.min))]
    row = WorkCalendar.objects.first() or WorkCalendar.objects.create()
    start = max(time.fromisoformat(schedule["day_start"]), row.day_start)
    end = min(time.fromisoformat(schedule["day_end"]), row.day_end)
    if kind == "short":
        end = min(end, (datetime.combine(day, row.day_end) - timedelta(hours=1)).time())
    if start >= end:
        return []
    return [(_at(day, start), _at(day, end))]


def _local(moment):
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("нужно время с часовым поясом")
    return moment.astimezone(MSK)


def deadline(start, minutes, level):
    """Срок через `minutes` рабочих минут; нулевой срок нормализуется к началу работы."""
    point = _local(start)
    remaining = max(0, int(minutes))
    for _ in range(2000):
        intervals = day_intervals(level, point.date())
        for begin, end in intervals:
            cursor = max(point, begin)
            if cursor >= end:
                continue
            available = int((end - cursor).total_seconds() // 60)
            if remaining <= available:
                return cursor + timedelta(minutes=remaining)
            remaining -= available
        point = datetime.combine(point.date() + timedelta(days=1), time.min, tzinfo=MSK)
    raise ValueError("не удалось найти рабочее время")


def minutes_between(a, b, level):
    """Рабочие минуты от `a` до `b`, со знаком при обратном направлении."""
    if a == b:
        return 0
    if a > b:
        return -minutes_between(b, a, level)
    left, right = _local(a), _local(b)
    total = 0
    day = left.date()
    while day <= right.date():
        for begin, end in day_intervals(level, day):
            total += max(0, int((min(right, end) - max(left, begin)).total_seconds() // 60))
        day += timedelta(days=1)
    return total


def level_for(ticket):
    """Находит активный уровень: сначала привязка к критичности, затем к категории."""
    binding = (SlaBinding.objects.select_related("level")
               .filter(kind=SlaBinding.Kind.PRIORITY, priority_id=ticket.priority_id,
                       level__archived=False).order_by("level__priority", "level_id").first())
    if binding is not None:
        return binding.level
    if ticket.category_id is None:
        return None
    binding = (SlaBinding.objects.select_related("level")
               .filter(kind=SlaBinding.Kind.CATEGORY, category_id=ticket.category_id,
                       level__archived=False).order_by("level__priority", "level_id").first())
    return binding.level if binding else None


def _snapshot(level, started, reaction_due, solution_due):
    end = max(reaction_due, solution_due).astimezone(MSK).date()
    days = {}
    day = started.astimezone(MSK).date()
    while day <= end:
        kind = calendar.day_kind(day)
        days[day.isoformat()] = kind if kind != "work" else (
            "work" if day.weekday() in level.workdays else "off")
        day += timedelta(days=1)
    return {**_schedule(level), "days": days, "extended": False}


def _cycle_values(ticket, level, started):
    reaction_due = deadline(started, level.reaction_minutes, level)
    solution_due = deadline(started, level.solution_minutes, level)
    return {
        "level": level, "level_title": level.title,
        "queue": ticket.queue, "queue_name": ticket.queue.name if ticket.queue else "",
        "category": ticket.category, "category_name": ticket.category.name if ticket.category else "",
        "assignee": ticket.assignee,
        "assignee_name": ticket.assignee.full_name if ticket.assignee else "",
        "schedule": _snapshot(level, started, reaction_due, solution_due),
        "cycle_started_at": started, "reaction_due": reaction_due, "solution_due": solution_due,
    }


def apply_level_to_ticket(ticket):
    """Применяет активный уровень и создаёт либо обновляет текущий цикл."""
    level = level_for(ticket)
    if level is None:
        return None
    started = ticket.sla_cycle_started_at or ticket.created_at
    values = _cycle_values(ticket, level, started)
    ticket.sla = level
    ticket.sla_cycle_started_at = started
    ticket.sla_reaction_due = values["reaction_due"]
    ticket.sla_solution_due = values["solution_due"]
    ticket.save(update_fields=["sla", "sla_cycle_started_at", "sla_reaction_due", "sla_solution_due", "updated_at"])
    cycle = (SlaCycle.objects.filter(ticket=ticket, is_current=True).first())
    if cycle is None:
        number = (SlaCycle.objects.filter(ticket=ticket).order_by("-number")
                  .values_list("number", flat=True).first() or 0) + 1
        cycle = SlaCycle.objects.create(ticket=ticket, number=number, is_current=True, **values)
    else:
        for key, value in values.items():
            setattr(cycle, key, value)
        cycle.save(update_fields=list(values))
    return cycle


def recalculate(ticket):
    """Пересчитывает текущий цикл до первого ответа; без уровня очищает сроки."""
    cycle = SlaCycle.objects.filter(ticket=ticket, is_current=True).first()
    if cycle is not None and cycle.first_response_at is not None:
        return cycle
    level = level_for(ticket)
    if level is None:
        ticket.sla = None
        ticket.sla_cycle_started_at = None
        ticket.sla_reaction_due = ticket.sla_solution_due = None
        ticket.save(update_fields=["sla", "sla_cycle_started_at", "sla_reaction_due", "sla_solution_due", "updated_at"])
        if cycle is not None:
            cycle.is_current = False
            cycle.save(update_fields=["is_current"])
        return None
    if ticket.sla_cycle_started_at is None:
        ticket.sla_cycle_started_at = ticket.created_at
    return apply_level_to_ticket(ticket)
