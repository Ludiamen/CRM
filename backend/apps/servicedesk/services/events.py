"""Публичный интерфейс сервис-деска: события сервис-деска (PLAN-003, «Где живёт код»).

Публикуются шиной ядра; ключи данных — по CONTRACT-003, 3.1 и 6.13. С среза 013 у каждого события есть
`event_id` по CONTRACT-013, раздел 3.
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
TICKET_FIELD_CHANGED = "servicedesk.ticket_field_changed"
TICKET_STATUS_CHANGED = "servicedesk.ticket_status_changed"
SLA_THRESHOLD = "servicedesk.sla_threshold"


def ticket_created(ticket, *, actor_id: int | None, channel: str) -> None:
    """Новая заявка: ответственного «до» нет, «после» — текущий; `actor_id` — создатель-сотрудник или `None`."""
    bus.publish(TICKET_CREATED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=None, assignee_after_id=ticket.assignee_id, actor_id=actor_id, channel=channel,
                event_id=f"created:{ticket.number}")


def assignee_changed(ticket, *, before_id: int | None, after_id: int | None, actor_id: int | None) -> None:
    """Смена ответственного: «до» и «после» передаёт вызывающий; `actor_id` — `None` у сверки и системы."""
    bus.publish(ASSIGNEE_CHANGED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=before_id, assignee_after_id=after_id, actor_id=actor_id,
                event_id=f"assignee:{ticket.number}:{ticket.updated_at.isoformat()}")


def reply_received(ticket, *, via: str, author_kind: str, entry_id: int) -> None:
    """Письмо заявителя в заявке: «до» и «после» — текущий ответственный; `actor_id` всегда `None`."""
    bus.publish(REPLY_RECEIVED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=ticket.assignee_id, assignee_after_id=ticket.assignee_id, actor_id=None,
                via=via, author_kind=author_kind, entry_id=entry_id, event_id=f"reply:{entry_id}")


def ticket_closed(ticket, *, actor_id: int | None) -> None:
    """Закрытие заявки: «до» и «после» — ответственный на момент закрытия; `actor_id` — `None` у автозакрытия."""
    moment = ticket.closed_at.isoformat() if ticket.closed_at is not None else ticket.updated_at.isoformat()
    bus.publish(TICKET_CLOSED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id,
                assignee_before_id=ticket.assignee_id, assignee_after_id=ticket.assignee_id, actor_id=actor_id,
                closed_at=moment, event_id=f"close:{ticket.number}:{moment}")


def ticket_transferred(ticket, *, from_queue_id: int, actor_id: int | None, entry_id: int | None = None) -> None:
    """Перенос в другую очередь (передача и смена категории): ответственный «после» — на момент публикации."""
    event_id = f"transfer:{entry_id}" if entry_id is not None else f"transfer:{ticket.number}:{ticket.updated_at.isoformat()}"
    bus.publish(TICKET_TRANSFERRED, pk=ticket.pk, number=ticket.number, from_queue_id=from_queue_id, to_queue_id=ticket.queue_id,
                actor_id=actor_id, assignee_after_id=ticket.assignee_id, event_id=event_id)


def ticket_reopened(ticket, *, via: str, actor_id: int | None) -> None:
    """Заявка открыта заново (`via` — `mail` или `manual`); очередь и ответственный — после возможного переноса."""
    bus.publish(TICKET_REOPENED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id, via=via, actor_id=actor_id,
                assignee_id=ticket.assignee_id, event_id=f"reopen:{ticket.number}:{ticket.updated_at.isoformat()}")


def ticket_status_changed(ticket, *, before_id: int | None, after_id: int, entry_id: int,
                          actor_id: int | None, reason: str = "") -> None:
    """Смена статуса: `entry_id` — событие ленты, по нему строится `event_id`."""
    bus.publish(TICKET_STATUS_CHANGED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id,
                before_id=before_id, after_id=after_id, reason=reason, actor_id=actor_id,
                event_id=f"status:{entry_id}")


def ticket_field_changed(ticket, *, changed: list, audit_id: int, actor_id: int | None) -> None:
    """Изменение полей заявки: одно событие со списком изменённых полей."""
    bus.publish(TICKET_FIELD_CHANGED, pk=ticket.pk, number=ticket.number, queue_id=ticket.queue_id, changed=list(changed),
                actor_id=actor_id, event_id=f"update:{audit_id}")


def sla_threshold(ticket, *, cycle_id: int, deadline: str, kind: str) -> None:
    """Порог SLA: один раз на цикл, срок и вид; `event_id` защищает от повтора."""
    bus.publish(SLA_THRESHOLD, pk=ticket.pk, number=ticket.number, cycle_id=cycle_id, deadline=deadline, kind=kind,
                actor_id=None, event_id=f"sla:{cycle_id}:{deadline}:{kind}")


def reply_not_sent(ticket, *, entry_id: int, reason: str, author_id: int | None) -> None:
    """Ответ не отправлен (карантин, архив с паролем, закрытая заявка): действие системы, `actor_id=None`."""
    bus.publish(REPLY_NOT_SENT, pk=ticket.pk, number=ticket.number, entry_id=entry_id, reason=reason, author_id=author_id,
                actor_id=None, event_id=f"reply-not-sent:{entry_id}:{reason}")


def mail_failed(ticket, *, mail_kind: str, entry_id: int | None) -> None:
    """Письмо по заявке не доставлено; `entry_id` — `None`, если у письма нет элемента ленты; `actor_id=None`."""
    bus.publish(MAIL_FAILED, pk=ticket.pk, number=ticket.number, mail_kind=mail_kind, entry_id=entry_id, actor_id=None,
                event_id=f"mail-failed:{ticket.number}:{mail_kind}:{entry_id}")


def object_viewed(user, ticket) -> None:
    """Сотрудник открыл карточку заявки (общее событие `object.viewed`; ссылка — по первичному ключу заявки)."""
    bus.publish(OBJECT_VIEWED, object_ref=f"servicedesk.ticket:{ticket.pk}", user_id=user.pk)


def register() -> None:
    """Подписки приложения на события шины (вызывается из `ServicedeskConfig.ready()`):
    `mail.failed` -> `replies.on_mail_failed`, `access.changed` -> `reconcile.on_access_changed`.
    """
    from . import distribution, reconcile, replies

    bus.subscribe("mail.failed", replies.on_mail_failed)
    bus.subscribe("access.changed", reconcile.on_access_changed)
    bus.subscribe("availability.changed", distribution.on_availability_changed)
