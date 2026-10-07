"""Публичный интерфейс сервис-деска: события сервис-деска (PLAN-003, «Где живёт код»).

Публикуются шиной ядра; ключи данных — по CONTRACT-003, 3.1 и 6.13.
"""
from apps.core import events as bus

TICKET_CREATED = "servicedesk.ticket_created"
ASSIGNEE_CHANGED = "servicedesk.assignee_changed"
REPLY_RECEIVED = "servicedesk.reply_received"
TICKET_CLOSED = "servicedesk.ticket_closed"


def ticket_created(ticket) -> None:
    """Новая заявка: ответственного «до» нет, «после» — текущий."""
    bus.publish(TICKET_CREATED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=None, assignee_after_id=ticket.assignee_id)


def assignee_changed(ticket, *, before_id: int | None, after_id: int | None) -> None:
    """Смена ответственного: «до» и «после» передаёт вызывающий."""
    bus.publish(ASSIGNEE_CHANGED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=before_id, assignee_after_id=after_id)


def reply_received(ticket) -> None:
    """Письмо заявителя в заявке: «до» и «после» — текущий ответственный."""
    bus.publish(REPLY_RECEIVED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=ticket.assignee_id, assignee_after_id=ticket.assignee_id)


def ticket_closed(ticket) -> None:
    """Закрытие заявки: «до» и «после» — ответственный на момент закрытия."""
    bus.publish(TICKET_CLOSED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=ticket.assignee_id, assignee_after_id=ticket.assignee_id)


def register() -> None:
    """Подписки приложения на события шины (вызывается из `ServicedeskConfig.ready()`):
    `mail.failed` -> `replies.on_mail_failed`, `access.changed` -> `reconcile.on_access_changed`.
    """
    from . import reconcile, replies

    bus.subscribe("mail.failed", replies.on_mail_failed)
    bus.subscribe("access.changed", reconcile.on_access_changed)
