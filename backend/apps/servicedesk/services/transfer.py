"""Публичный интерфейс сервис-деска: передача в очередь и смена категории (PLAN-003, «Где живёт код»; CONTRACT-003, 6.9).

Узлы очередей — числа `queue_id`, модели `org` не импортируются. Снятие ответственного — общий помощник
`assignment.clear_assignee` (дополнение 22).
"""
from dataclasses import dataclass

from django.db import transaction

from apps.core.services import audit
from apps.org.services.refs import UnitRef

from . import access, assignment, events, queues, replies, tickets
from .errors import ServiceDeskError

REASON_LIMIT = 500


@dataclass(frozen=True)
class TransferResult:
    """Итог передачи: сменилась ли очередь, снят ли ответственный, видна ли заявка `actor` после передачи."""

    queue_changed: bool
    assignee_removed: bool
    visible_after: bool


@dataclass(frozen=True)
class CategoryResult:
    """Итог смены категории; `needs_confirmation` — очередь другая, а подтверждения нет (ничего не изменено)."""

    needs_confirmation: bool
    new_queue_id: int | None
    applied: bool
    queue_changed: bool
    assignee_removed: bool
    assignee_set: bool


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def target_queues(ticket) -> list[UnitRef]:
    """Отмеченные узлы, кроме текущей очереди заявки."""
    return [unit for unit in queues.marked_units() if unit.id != ticket.queue_id]


def _queue_name(unit_id: int) -> str:
    for unit in queues.marked_units():
        if unit.id == unit_id:
            return unit.name
    return ""


def _move(ticket, queue_id: int, *, actor, ip, reason_text, event_extra=None) -> bool:
    """Меняет очередь, пишет событие ленты (`transferred` или `queue_changed`) и журнал `ticket.transferred`.

    Возвращает `True`, если ответственный снят (он не участник новой очереди).
    """
    old_id, old_name, new_name = ticket.queue_id, ticket.queue.name, _queue_name(queue_id)
    ticket.queue_id = queue_id
    ticket.save(update_fields=["queue", "updated_at"])
    data = {"from": old_name, "to": new_name, "from_id": old_id, "to_id": queue_id}
    if reason_text is None:
        replies.add_event(ticket, "queue_changed", actor=actor, data=data)
    else:
        replies.add_event(ticket, "transferred", actor=actor, data={**data, "reason_text": reason_text})
    audit.record("ticket.transferred", actor=actor, object_type="ticket", object_id=ticket.number,
                 before={"queue": old_name, "queue_id": old_id},
                 after={"queue": new_name, "queue_id": queue_id, "reason_given": bool(reason_text)}, ip=ip)
    ticket.refresh_from_db(fields=["queue", "assignee"])
    assignee = ticket.assignee
    removed = False
    if assignee is not None and not access.is_participant(assignee, queue_id):
        removed = assignment.clear_assignee(ticket, actor=actor, reason="queue_changed", ip=ip)
    events.ticket_transferred(ticket, from_queue_id=old_id, actor_id=actor.pk if actor is not None else None)
    return removed


def transfer(ticket, queue_id, *, reason="", actor, ip=None) -> TransferResult:
    """Передаёт заявку в другую очередь; ответственный, не участник новой очереди, снимается (FR-239)."""
    with transaction.atomic():
        tickets._lock(ticket)
        if not access.can_work(actor, ticket):
            raise _error("no_access", "нет доступа")
        tickets.require_open(ticket)
        if queue_id is None:
            raise _error("queue_required", "Выберите очередь")
        if not queues.is_queue(queue_id):
            raise _error("not_queue", "Этот узел не отмечен очередью сервис-деска")
        if queue_id == ticket.queue_id:
            raise _error("same_queue", "Заявка уже в этой очереди")
        reason = str(reason or "").strip()
        if len(reason) > REASON_LIMIT:
            raise _error("reason_too_long", "Причина передачи не длиннее 500 знаков")
        removed = _move(ticket, queue_id, actor=actor, ip=ip, reason_text=reason)
    return TransferResult(queue_changed=True, assignee_removed=removed, visible_after=access.can_work(actor, ticket))


def change_category(ticket, category, *, confirmed=False, actor, ip=None) -> CategoryResult:
    """Меняет категорию заявки; очередь новой категории другая — только с подтверждением (FR-240).

    При смене очереди ответственный, не участник новой очереди, снимается; ответственного нет — назначается
    ответственный по умолчанию новой категории. Та же категория — ничего не пишется.
    """
    with transaction.atomic():
        tickets._lock(ticket)
        if not access.can_work(actor, ticket):
            raise _error("no_access", "нет доступа")
        tickets.require_open(ticket)
        tickets._check_active(category)
        new_queue_id = category.queue_id if category.queue_id is not None else queues.default_unit_id()
        if new_queue_id is None:
            raise _error("no_queue", "Очередь заявки не определена: задайте очередь по умолчанию в настройках сервис-деска")
        queue_changed = new_queue_id != ticket.queue_id
        if ticket.category_id == category.pk:
            return CategoryResult(False, new_queue_id, True, False, False, False)
        if queue_changed and not confirmed:
            return CategoryResult(True, new_queue_id, False, False, False, False)
        old = ticket.category
        ticket.category = category
        ticket.save(update_fields=["category", "updated_at"])
        replies.add_event(ticket, "category_changed", actor=actor, data={
            "before": old.name if old else "", "after": category.name,
            "before_id": old.pk if old else None, "after_id": category.pk})
        audit.record("ticket.updated", actor=actor, object_type="ticket", object_id=ticket.number,
                     before={"category": old.name if old else ""}, after={"category": category.name}, ip=ip)
        removed = False
        if queue_changed:
            removed = _move(ticket, new_queue_id, actor=actor, ip=ip, reason_text=None)
        assigned = False
        if ticket.assignee_id is None:
            assigned = assignment.apply_default_assignee(ticket, actor=actor, ip=ip)
    return CategoryResult(False, new_queue_id, True, queue_changed, removed, assigned)
