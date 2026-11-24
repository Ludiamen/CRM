"""Расчёт и применение сроков SLA (PLAN-011, FR-734…737)."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.org.services import calendar
from apps.org.models import WorkCalendar

from ..models import SlaBinding, SlaCycle, SlaLevel
from .errors import ServiceDeskError

MSK = ZoneInfo("Europe/Moscow")
OFF = {"off", "holiday", "day_off"}

TITLE_RANGE = "Название уровня — от 1 до 100 знаков"
MINUTES_RANGE = "Срок — от 5 минут до 720 часов"
REACTION_GT_SOLUTION = "Срок реакции не может быть больше срока решения"
DAYS_EMPTY = "Выберите хотя бы один рабочий день"
INTERVAL_EMPTY = "Укажите непустой рабочий интервал"
ASSIGNEE_DISMISSED = "Сотрудник уволен: ответственным по уровню его не назначить"


def _level_error(code, message):
    raise ServiceDeskError(code, message)


def _clean_level_values(values):
    """Normalize and validate values before they reach model constraints."""
    title = str(values.get("title", "") or "").strip()
    if not 1 <= len(title) <= 100:
        _level_error("sla_title_range", TITLE_RANGE)
    try:
        reaction = int(values.get("reaction_minutes", 60))
        solution = int(values.get("solution_minutes", 240))
    except (TypeError, ValueError):
        _level_error("sla_minutes_range", MINUTES_RANGE)
    if not 5 <= reaction <= 43200 or not 5 <= solution <= 43200:
        _level_error("sla_minutes_range", MINUTES_RANGE)
    if reaction > solution:
        _level_error("sla_reaction_gt_solution", REACTION_GT_SOLUTION)
    try:
        priority = int(values.get("priority", 0) or 0)
    except (TypeError, ValueError):
        _level_error("sla_priority_range", "Приоритет — от 0 до 99")
    if not 0 <= priority <= 99:
        _level_error("sla_priority_range", "Приоритет — от 0 до 99")
    try:
        workdays = sorted({int(day) for day in (values.get("workdays") or [])})
    except (TypeError, ValueError):
        workdays = []
    if not workdays or any(day not in range(7) for day in workdays):
        _level_error("sla_days_empty", DAYS_EMPTY)
    all_day = bool(values.get("all_day", False))
    day_start = values.get("day_start", time(9))
    day_end = values.get("day_end", time(18))
    if isinstance(day_start, str):
        try:
            day_start = time.fromisoformat(day_start)
        except ValueError:
            day_start = None
    if isinstance(day_end, str):
        try:
            day_end = time.fromisoformat(day_end)
        except ValueError:
            day_end = None
    if not all_day and (day_start is None or day_end is None or day_start >= day_end):
        _level_error("sla_interval_empty", INTERVAL_EMPTY)
    assignee = values.get("default_assignee")
    if assignee is not None and getattr(assignee, "state", None) != "active":
        _level_error("sla_assignee_dismissed", ASSIGNEE_DISMISSED)
    return {
        "title": title, "priority": priority,
        "reaction_minutes": reaction, "solution_minutes": solution,
        "workdays": workdays, "day_start": day_start or time(9),
        "day_end": day_end or time(18), "all_day": all_day,
        "default_assignee": assignee,
    }


def _level_snapshot(level):
    return {
        "title": level.title, "priority": level.priority,
        "reaction_minutes": level.reaction_minutes, "solution_minutes": level.solution_minutes,
        "workdays": list(level.workdays), "day_start": level.day_start.strftime("%H:%M"),
        "day_end": level.day_end.strftime("%H:%M"), "all_day": level.all_day,
        "default_assignee": level.default_assignee.full_name if level.default_assignee_id else "",
    }


@transaction.atomic
def create_level(*, actor=None, ip=None, **values):
    fields = _clean_level_values(values)
    level = SlaLevel.objects.create(**fields)
    audit.record("servicedesk.sla_level_created", actor=actor, ip=ip,
                 object_type="servicedesk", object_id=level.pk, after=_level_snapshot(level))
    return level


@transaction.atomic
def update_level(level, *, actor=None, ip=None, **values):
    level = SlaLevel.objects.select_for_update().get(pk=level.pk)
    current = {
        "title": level.title, "priority": level.priority,
        "reaction_minutes": level.reaction_minutes, "solution_minutes": level.solution_minutes,
        "workdays": level.workdays, "day_start": level.day_start, "day_end": level.day_end,
        "all_day": level.all_day, "default_assignee": level.default_assignee,
    }
    fields = _clean_level_values({**current, **values})
    before = _level_snapshot(level)
    for key, value in fields.items():
        setattr(level, key, value)
    level.save()
    after = _level_snapshot(level)
    if before != after:
        audit.record("servicedesk.sla_level_changed", actor=actor, ip=ip,
                     object_type="servicedesk", object_id=level.pk, before=before, after=after)
    return level


@transaction.atomic
def archive_level(level, *, actor=None, ip=None):
    level = SlaLevel.objects.select_for_update().get(pk=level.pk)
    was_archived = level.archived
    level.archived = not was_archived
    level.save(update_fields=["archived", "updated_at"])
    audit.record("servicedesk.sla_level_archived", actor=actor, ip=ip,
                 object_type="servicedesk", object_id=level.pk,
                 before={"archived": was_archived}, after={"archived": level.archived})
    return level


restore_level = archive_level


def _binding_snapshot(binding):
    return {
        "level": binding.level_id, "kind": binding.kind,
        "category": binding.category.name if binding.category_id else "",
        "priority": binding.priority.name if binding.priority_id else "",
    }


@transaction.atomic
def bind_level(level, *, category=None, priority=None, actor=None, ip=None):
    if (category is None) == (priority is None):
        raise ValueError("передайте ровно category или priority")
    kind = SlaBinding.Kind.CATEGORY if category is not None else SlaBinding.Kind.PRIORITY
    lookup = {"level": level, "kind": kind}
    fields = {"category": category, "priority": priority}
    binding = SlaBinding.objects.create(**lookup, **fields)
    audit.record("servicedesk.binding_changed", actor=actor, ip=ip,
                 object_type="servicedesk", object_id=level.pk,
                 after=_binding_snapshot(binding))
    return binding


def create_binding(level, **kwargs):
    return bind_level(level, **kwargs)


@transaction.atomic
def set_bindings(level, *, categories=(), priorities=(), actor=None, ip=None):
    """Replace all level bindings, recording one event per added/removed row."""
    desired = {(SlaBinding.Kind.CATEGORY, int(item.pk if hasattr(item, "pk") else item), None)
               for item in categories}
    desired |= {(SlaBinding.Kind.PRIORITY, None, int(item.pk if hasattr(item, "pk") else item))
                for item in priorities}
    current = {(row.kind, row.category_id, row.priority_id): row
               for row in SlaBinding.objects.filter(level=level)}
    for key, row in current.items():
        if key not in desired:
            before = _binding_snapshot(row)
            row.delete()
            audit.record("servicedesk.binding_changed", actor=actor, ip=ip,
                         object_type="servicedesk", object_id=level.pk, before=before, after={})
    for kind, category_id, priority_id in desired:
        if (kind, category_id, priority_id) in current:
            continue
        row = SlaBinding.objects.create(level=level, kind=kind, category_id=category_id,
                                        priority_id=priority_id)
        audit.record("servicedesk.binding_changed", actor=actor, ip=ip,
                     object_type="servicedesk", object_id=level.pk,
                     after=_binding_snapshot(row))
    return list(SlaBinding.objects.filter(level=level).select_related("category", "priority"))


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
