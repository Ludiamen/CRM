"""Публичный интерфейс сервис-деска: события сервис-деска (PLAN-003, «Где живёт код»).

Публикуются шиной ядра; ключи данных — по CONTRACT-003, 3.1 и 6.13.
"""
from apps.core import events as bus

TICKET_CREATED = "servicedesk.ticket_created"
ASSIGNEE_CHANGED = "servicedesk.assignee_changed"
REPLY_RECEIVED = "servicedesk.reply_received"
TICKET_CLOSED = "servicedesk.ticket_closed"
TICKET_TRANSFERRED = "servicedesk.ticket_transferred"
TICKET_REOPENED = "servicedesk.ticket_reopened"
REPLY_NOT_SENT = "servicedesk.reply_not_sent"
MAIL_FAILED = "servicedesk.mail_failed"
OBJECT_VIEWED = "object.viewed"


def ticket_created(ticket, *, actor_id: int | None, channel: str) -> None:
    """Новая заявка: ответственного «до» нет, «после» — текущий; `actor_id` — создатель-сотрудник или `None`."""
    bus.publish(TICKET_CREATED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=None, assignee_after_id=ticket.assignee_id, actor_id=actor_id, channel=channel)


def assignee_changed(ticket, *, before_id: int | None, after_id: int | None, actor_id: int | None) -> None:
    """Смена ответственного: «до» и «после» передаёт вызывающий; `actor_id` — `None` у сверки и системы."""
    bus.publish(ASSIGNEE_CHANGED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=before_id, assignee_after_id=after_id, actor_id=actor_id)


def reply_received(ticket, *, via: str, author_kind: str, entry_id: int) -> None:
    """Письмо заявителя в заявке: «до» и «после» — текущий ответственный; `actor_id` всегда `None`."""
    bus.publish(REPLY_RECEIVED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=ticket.assignee_id, assignee_after_id=ticket.assignee_id, actor_id=None,
                via=via, author_kind=author_kind, entry_id=entry_id)


def ticket_closed(ticket, *, actor_id: int | None) -> None:
    """Закрытие заявки: «до» и «после» — ответственный на момент закрытия; `actor_id` — `None` у автозакрытия."""
    bus.publish(TICKET_CLOSED, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=ticket.assignee_id, assignee_after_id=ticket.assignee_id, actor_id=actor_id)


def ticket_transferred(ticket, *, from_queue_id: int, actor_id: int | None) -> None:
    """Перенос в другую очередь (передача и смена категории): ответственный «после» — на момент публикации."""
    bus.publish(TICKET_TRANSFERRED, number=ticket.number, from_queue_id=from_queue_id, to_queue_id=ticket.queue_id,
                actor_id=actor_id, assignee_after_id=ticket.assignee_id)


def ticket_reopened(ticket, *, via: str, actor_id: int | None) -> None:
    """Заявка открыта заново (`via` — `mail` или `manual`); очередь и ответственный — после возможного переноса."""
    bus.publish(TICKET_REOPENED, number=ticket.number, queue_id=ticket.queue_id, via=via, actor_id=actor_id,
                assignee_id=ticket.assignee_id)


def reply_not_sent(ticket, *, entry_id: int, reason: str, author_id: int | None) -> None:
    """Ответ не отправлен (карантин, архив с паролем, закрытая заявка): действие системы, `actor_id=None`."""
    bus.publish(REPLY_NOT_SENT, number=ticket.number, entry_id=entry_id, reason=reason, author_id=author_id,
                actor_id=None)


def mail_failed(ticket, *, mail_kind: str, entry_id: int | None) -> None:
    """Письмо по заявке не доставлено; `entry_id` — `None`, если у письма нет элемента ленты; `actor_id=None`."""
    bus.publish(MAIL_FAILED, number=ticket.number, mail_kind=mail_kind, entry_id=entry_id, actor_id=None)


def object_viewed(user, ticket) -> None:
    """Сотрудник открыл карточку заявки (общее событие `object.viewed`; ссылка — по первичному ключу заявки)."""
    bus.publish(OBJECT_VIEWED, object_ref=f"servicedesk.ticket:{ticket.pk}", user_id=user.pk)


def register() -> None:
    """Подписки приложения на события шины (вызывается из `ServicedeskConfig.ready()`):
    `mail.failed` -> `replies.on_mail_failed`, `access.changed` -> `reconcile.on_access_changed`.
    """
    from . import reconcile, replies

    bus.subscribe("mail.failed", replies.on_mail_failed)
    bus.subscribe("access.changed", reconcile.on_access_changed)
