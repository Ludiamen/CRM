"""Публичный интерфейс сервис-деска: закрытие, открытие заново и автозакрытие заявок (PLAN-003, «Где живёт код»; CONTRACT-003, 6.11).

Журнал закрытия, автозакрытия и открытия пишет этот модуль, а не `tickets.set_status` (при причинах `close`, `autoclose`,
`reopen` тот журнал не пишет). Модели `org` не импортируются.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.services import audit

from ..models import Status, Ticket
from . import access, assignment, dictionaries, events, letters, queues, replies, tickets
from . import settings as sd_settings
from .errors import Batch, ServiceDeskError

logger = logging.getLogger(__name__)

MAX_RESOLUTION = 10_000
NOT_CLOSED_TEXT = "Заявка не закрыта: открывать заново нечего"


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def _lock(ticket) -> None:
    """Блокирует строку заявки и перечитывает состояние объекта (6.1)."""
    Ticket.objects.select_for_update().filter(pk=ticket.pk).first()
    ticket.refresh_from_db()


def close(ticket, status, resolution, *, actor, ip=None) -> None:
    """Закрывает заявку выбранным статусом вида «закрыта» с текстом решения (FR-249).

    Событие ленты «статус: было → стало» пишет `tickets.set_status`, сверх него — `closed`; журнал `ticket.closed`,
    событие шины и письмо заявителю (после фиксации).
    """
    resolution = (resolution or "").strip()
    with transaction.atomic():
        _lock(ticket)
        if not access.can_work(actor, ticket):
            raise _error("no_access", "нет доступа")
        tickets.require_open(ticket)
        if status not in dictionaries.closing_statuses():
            raise _error("bad_status", "Этот статус нельзя выбрать здесь")
        if not resolution:
            raise _error("resolution_required", "Напишите решение")
        if len(resolution) > MAX_RESOLUTION:
            raise _error("resolution_too_long", "Решение не длиннее 10 000 знаков")
        before = ticket.status
        tickets.set_status(ticket, status, actor=actor, reason="close", ip=ip)
        ticket.closed_at = timezone.now()
        ticket.closed_by = actor
        ticket.resolution = resolution
        ticket.waiting_since = None
        ticket.save(update_fields=["closed_at", "closed_by", "resolution", "waiting_since", "updated_at"])
        replies.add_event(ticket, "closed", actor=actor, data={
            "status": status.name, "status_id": status.pk, "resolution": resolution})
        audit.record("ticket.closed", actor=actor, object_type="ticket", object_id=ticket.number,
                     before={"status": before.name}, after={"status": status.name}, ip=ip)
        events.ticket_closed(ticket)
        letters.send(ticket, "ticket.closed")


def _final_queue(ticket):
    """Если узел заявки больше не очередь — (id и название очереди по умолчанию, прежнее название), иначе `None`."""
    if queues.is_queue(ticket.queue_id):
        return None
    default_id = queues.default_unit_id()
    if default_id is None or default_id == ticket.queue_id:
        return None
    names = {unit.id: unit.name for unit in queues.marked_units()}
    return default_id, names.get(default_id, ""), ticket.queue.name


def reopen(ticket, *, actor, ip=None, via="manual") -> None:
    """Открывает закрытую заявку заново «в работе» (FR-251, FR-252); `via` — `manual` или `mail` (`actor=None`).

    Узел, переставший быть очередью, заменяется очередью по умолчанию (событие `queue_changed` с причиной
    `queue_unmarked`); ответственный, не участник итоговой очереди, снимается через `assignment.clear_assignee`.
    """
    with transaction.atomic():
        _lock(ticket)
        if actor is not None and not access.can_work(actor, ticket):
            raise _error("no_access", "нет доступа")
        if ticket.kind != Status.Kind.CLOSED:
            raise _error("ticket_open", NOT_CLOSED_TEXT)
        before = ticket.status
        moved = _final_queue(ticket)
        status = dictionaries.default_status(Status.Kind.IN_PROGRESS)
        tickets.set_status(ticket, status, actor=actor, reason="reopen", ip=ip)
        ticket.closed_at = None
        ticket.closed_by = None
        ticket.resolution = ""
        fields = ["closed_at", "closed_by", "resolution", "updated_at"]
        if moved is not None:
            old_id = ticket.queue_id
            ticket.queue_id = moved[0]
            fields.append("queue")
        ticket.save(update_fields=fields)
        if moved is not None:
            ticket.refresh_from_db(fields=["queue"])
            replies.add_event(ticket, "queue_changed", actor=actor, data={
                "from": moved[2], "to": moved[1], "from_id": old_id, "to_id": moved[0], "reason": "queue_unmarked"})
        if ticket.assignee_id is not None and not access.is_participant(ticket.assignee, ticket.queue_id):
            assignment.clear_assignee(ticket, actor=actor, ip=ip,
                                      reason="queue_changed" if moved is not None else "not_participant")
        replies.add_event(ticket, "reopened", actor=actor, data={
            "via": via, "status": status.name, "status_id": status.pk})
        audit.record("ticket.reopened", actor=actor, object_type="ticket", object_id=ticket.number,
                     before={"status": before.name}, after={"status": status.name, "via": via}, ip=ip)
        letters.send(ticket, "ticket.reopened")


def within_reopen_term(ticket) -> bool:
    """Закрыта ли заявка в пределах срока открытия заново: `closed_at + reopen_days >= now` (срок — из настроек)."""
    if ticket.closed_at is None:
        return False
    return ticket.closed_at + timedelta(days=sd_settings.get().reopen_days) >= timezone.now()


def autoclose_one(ticket_id, *, now=None) -> bool:
    """Автозакрытие одной заявки под замком с повторной проверкой; `False`, если закрывать не нужно (6.11)."""
    now = now or timezone.now()
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
        days = sd_settings.get().autoclose_days
        if (ticket is None or ticket.kind != Status.Kind.WAITING or ticket.waiting_since is None
                or ticket.waiting_since > now - timedelta(days=days)):
            return False
        status = Status.objects.filter(system_code="autoclosed").first()
        if status is None:
            logger.error("Автозакрытие заявки пропущено: нет статуса «Закрыта автоматически»")
            return False
        before = ticket.status
        tickets.set_status(ticket, status, actor=None, reason="autoclose")
        ticket.closed_at = now
        ticket.closed_by = None
        ticket.save(update_fields=["closed_at", "closed_by", "updated_at"])
        replies.add_event(ticket, "autoclosed", data={"status": status.name, "status_id": status.pk, "days": days})
        audit.record("ticket.autoclosed", actor=None, object_type="ticket", object_id=ticket.number,
                     before={"status": before.name}, after={"status": status.name})
        events.ticket_closed(ticket)
        letters.send(ticket, "ticket.autoclosed")
    return True


def autoclose_batch(*, limit=50, after=None) -> Batch:
    """Порция автозакрытия: заявки вида «ждёт» старше срока по `(waiting_since, id)` строго после курсора `after`."""
    limit_time = timezone.now() - timedelta(days=sd_settings.get().autoclose_days)
    found = Ticket.objects.filter(kind=Status.Kind.WAITING, waiting_since__lte=limit_time)
    if after is not None:
        since, last_id = after
        found = found.filter(Q(waiting_since__gt=since) | Q(waiting_since=since, id__gt=last_id))
    chosen = list(found.order_by("waiting_since", "id").values_list("waiting_since", "id")[:limit])
    done = sum(1 for _, ticket_id in chosen if autoclose_one(ticket_id))
    last = chosen[-1] if chosen else None
    return Batch(done=done, more=len(chosen) == limit, last_id=last[1] if last else None, last=last)
