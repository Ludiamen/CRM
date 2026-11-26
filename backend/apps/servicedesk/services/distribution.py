"""Автораспределение заявок очереди (SPEC-012, FR-759…765; PLAN-012).

Контракт этапа 1: режимы очереди, выбор кандидата и возврат в очередь. Реализация — T-12204…T-12207.
"""
from django.db import transaction
from django.db.models import Count

from apps.core.services import audit
from apps.core.widgets import moscow_today

from ..models import QueueRule, Status, Ticket
from . import access, assignment
from .errors import ServiceDeskError

MODE_OFF = QueueRule.Mode.OFF
MODE_EVENLY = QueueRule.Mode.EVENLY
MODE_STRICTLY = QueueRule.Mode.STRICTLY
MODE_ALL = QueueRule.Mode.ALL
MODES = QueueRule.Mode.values


def mode_for(queue_id: int) -> str:
    """Режим очереди `queue_id`; нет правила — `off`."""
    return QueueRule.objects.filter(queue__unit_id=queue_id).values_list("mode", flat=True).first() or MODE_OFF


def set_mode(queue_id: int, mode: str, *, actor, ip=None) -> QueueRule:
    """Сменить режим очереди с журналом; разрешено `servicedesk.manage` или руководителю очереди."""
    if mode not in MODES:
        raise ServiceDeskError("queue_rule_mode", "Выберите режим очереди")
    if not _can_manage(actor, queue_id):
        raise ServiceDeskError("no_access", "нет доступа")
    with transaction.atomic():
        rule, _ = QueueRule.objects.select_for_update().get_or_create(queue_id=_queue_pk(queue_id))
        before = rule.mode
        if before != mode:
            rule.mode = mode
            rule.updated_by = actor
            rule.save(update_fields=["mode", "updated_by", "updated_at"])
            audit.record("servicedesk.queue_rule_changed", actor=actor, object_type="queue",
                         object_id=queue_id, before={"mode": before}, after={"mode": mode}, ip=ip)
    return rule


def assign_or_notify(ticket, *, actor=None, ip=None, reason: str = "create"):
    """Назначить ответственного по режиму или уведомить всех; вернуть id ответственного либо `None`."""
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if locked.assignee_id is not None or locked.kind == Status.Kind.CLOSED:
            return locked.assignee_id
        rule = QueueRule.objects.select_for_update().filter(queue__unit_id=locked.queue_id).first()
        mode = rule.mode if rule is not None else MODE_OFF
        # Явный ответственный категории или уровня важнее режима (FR-760).
        default = getattr(getattr(locked, "category", None), "default_assignee", None)
        if default is None and locked.sla_id is not None:
            default = getattr(locked.sla, "default_assignee", None)
        if default is not None and access.is_participant(default, locked.queue_id):
            assignment._set_assignee(locked, default, actor=actor, ip=ip)
            ticket.refresh_from_db(fields=["assignee", "assigned_once", "status", "kind"])
            return default.pk
        if mode == MODE_OFF:
            return None
        candidates = access.eligible_assignees(locked.queue_id)
        if mode == MODE_ALL:
            # Ответственного нет; уведомление о новой заявке отправит общий ticket_created после фиксации.
            return None
        person = choose_evenly(locked.queue_id, candidates) if mode == MODE_EVENLY else choose_strictly(rule, candidates)
        if person is None:
            return None
        user = _user(person.id)
        assignment._set_assignee(locked, user, actor=actor, ip=ip)
        if mode == MODE_STRICTLY:
            rule.last_assignee_id = user.pk
            rule.save(update_fields=["last_assignee", "updated_at"])
        audit.record("ticket.distributed", actor=actor, object_type="ticket", object_id=locked.number,
                     before={"assignee_id": None}, after={"assignee_id": user.pk, "reason": reason}, ip=ip)
        # Вызывающий объект мог быть создан до распределения: обновляем его для ticket_created/писем.
        try:
            ticket.refresh_from_db(fields=["assignee", "assigned_once", "status", "kind"])
        except Exception:
            pass
        return user.pk


def return_ticket(ticket, *, actor=None, reason: str = "manual", ip=None):
    """Вернуть заявку в очередь и распределить по режиму; закрытые не трогать."""
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if locked.kind == Status.Kind.CLOSED:
            return None
        if locked.assignee_id is not None:
            assignment.clear_assignee(locked, actor=actor, reason=reason, ip=ip)
        locked.refresh_from_db()
        return assign_or_notify(locked, actor=actor, reason=reason, ip=ip)


def choose_evenly(unit_id: int, candidates, *, open_by_user=None):
    """Кандидат с наименьшим числом открытых заявок этой очереди; tie-break — ФИО и id."""
    from apps.org.services import availability
    people = [p for p in candidates if p.id not in availability.unavailable_ids([x.id for x in candidates])]
    if not people:
        return None
    if open_by_user is None:
        counts = dict(Ticket.objects.filter(queue_id=unit_id, kind__in=(
            Status.Kind.NEW, Status.Kind.IN_PROGRESS, Status.Kind.WAITING),
            assignee_id__in=[p.id for p in people]).values("assignee_id").annotate(n=Count("id"))
                       .values_list("assignee_id", "n"))
    else:
        counts = open_by_user
    return min(people, key=lambda p: (counts.get(p.id, 0), p.full_name, p.id))


def choose_strictly(rule: QueueRule, candidates):
    """Следующий после `rule.last_assignee` в постоянном порядке (ФИО, id); выбывших пропустить."""
    from apps.org.services import availability
    unavailable = availability.unavailable_ids([p.id for p in candidates])
    people = sorted([p for p in candidates if p.id not in unavailable], key=lambda p: (p.full_name, p.id))
    if not people:
        return None
    if rule.last_assignee_id is None:
        return people[0]
    for index, person in enumerate(people):
        if person.id == rule.last_assignee_id:
            return people[(index + 1) % len(people)]
    return people[0]


def on_availability_changed(*, user_id, until=None, actor_id=None):
    """Возвращает открытые заявки сотрудника при установке действующей недоступности."""
    from datetime import date

    if isinstance(until, date):
        until_date = until
    else:
        try:
            until_date = date.fromisoformat(until) if until else None
        except (TypeError, ValueError):
            until_date = None
    if until_date is None or until_date < moscow_today():
        return
    for ticket in Ticket.objects.filter(assignee_id=user_id).exclude(kind=Status.Kind.CLOSED).order_by("pk"):
        return_ticket(ticket, actor=None, reason="unavailable")


def _queue_pk(unit_id):
    from ..models import Queue
    return Queue.objects.values_list("pk", flat=True).get(unit_id=unit_id)


def _user(user_id):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.get(pk=user_id)


def _can_manage(actor, unit_id):
    from apps.core.services import permissions
    return (permissions.has_permission(actor, "servicedesk.manage")
            or unit_id in __import__("apps.org.services.structure", fromlist=["managed_units"]).managed_units(actor))
