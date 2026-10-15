"""Четыре вида уведомлений сервис-деска (PLAN-004, «События и получатели»; CONTRACT-004, § 4.3, § 15.1–15.2).

Каждый вид сам решает, кому и о чём уведомлять (FR-314): получатель видит заявку (`access.can_work`), не совершал
действие (`actor_id`, FR-315) и состоит в состоянии `active` или `blocked`. Состояние заявки — ответственный, очередь,
вид статуса — читается из базы по `data["number"]`; данные события говорят, кто совершил действие, откуда и куда.
"""
import re

from django.contrib.auth import get_user_model

from apps.core.extensions import Draft, NotificationKind
from apps.org.services import structure

from .models import Queue, Ticket

NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
REQUESTER_REPLIED = "servicedesk.requester_replied"
REPLY_FAILED = "servicedesk.reply_failed"

SUBJECT_LIMIT = 100
OBJECT_PREFIX = "servicedesk.ticket:"
_REF = re.compile(r"servicedesk\.ticket:([0-9]{1,18})")
RECIPIENT_STATES = ("active", "blocked")
NEW_IN_QUEUE_EVENTS = ("servicedesk.ticket_created", "servicedesk.ticket_transferred", "servicedesk.ticket_reopened")
ALL_CHANNELS = ("portal", "email", "push", "telegram", "max")

REASON_TEXTS = {
    "quarantine": "вложение в карантине",
    "encrypted": "вложение — архив с паролем",
}


def _subject(text: str) -> str:
    """Тема для текста уведомления: больше 100 знаков (по символам) — первые 99 и «…»."""
    text = text or ""
    return text if len(text) <= SUBJECT_LIMIT else text[:SUBJECT_LIMIT - 1] + "…"


def _ticket(data: dict):
    """Заявка по номеру из данных события; нет номера или заявки — `None`."""
    number = data.get("number")
    if number is None:
        return None
    return Ticket.objects.select_related("queue", "assignee").filter(number=number).first()


def _drafts(ticket, user_ids, text: str, *, skip=None) -> list[Draft]:
    """Черновики тем, кто активен или заблокирован, видит заявку и не совершал действие; порядок — как в `user_ids`."""
    from .services import access

    wanted = [pk for pk in dict.fromkeys(user_ids) if pk != skip]
    if not wanted:
        return []
    users = get_user_model().objects.filter(pk__in=wanted, state__in=RECIPIENT_STATES)
    by_id = {user.pk: user for user in users}
    url, ref = f"/tickets/{ticket.number}/", f"{OBJECT_PREFIX}{ticket.pk}"
    return [Draft(user_id=pk, text=text, url=url, object_ref=ref)
            for pk in wanted if pk in by_id and access.can_work(by_id[pk], ticket)]


def _new_in_queue(event: str, data: dict) -> list[Draft]:
    if event not in NEW_IN_QUEUE_EVENTS:
        return []
    ticket = _ticket(data)
    if ticket is None or ticket.assignee_id is not None:
        return []
    text = f"Новая заявка #{ticket.number} в очереди «{ticket.queue.name}»: {_subject(ticket.subject)}"
    members = [person.id for person in structure.direct_members(ticket.queue_id)]
    return _drafts(ticket, members, text, skip=data.get("actor_id"))


def _assigned(event: str, data: dict) -> list[Draft]:
    if event not in ("servicedesk.ticket_created", "servicedesk.assignee_changed"):
        return []
    ticket = _ticket(data)
    after = data.get("assignee_after_id")
    if ticket is None or after is None:
        return []
    text = f"Вам назначена заявка #{ticket.number}: {_subject(ticket.subject)}"
    return _drafts(ticket, [after], text, skip=data.get("actor_id"))


def _requester_replied(event: str, data: dict) -> list[Draft]:
    if event != "servicedesk.reply_received":
        return []
    ticket = _ticket(data)
    if ticket is None or ticket.assignee_id is None:
        return []
    text = f"Заявитель ответил в заявке #{ticket.number}: {_subject(ticket.subject)}"
    return _drafts(ticket, [ticket.assignee_id], text, skip=data.get("actor_id"))


def _reply_failed(event: str, data: dict) -> list[Draft]:
    if event == "servicedesk.reply_not_sent":
        reason = REASON_TEXTS.get(data.get("reason"))
        if reason is None:
            return []
        number_text = "Ответ по заявке #{} не отправлен: " + reason
    elif event == "servicedesk.mail_failed":
        number_text = "Письмо по заявке #{} не доставлено"
    else:
        return []
    ticket = _ticket(data)
    if ticket is None or ticket.assignee_id is None:
        return []
    return _drafts(ticket, [ticket.assignee_id], number_text.format(ticket.number), skip=data.get("actor_id"))


def _in_queue(user) -> bool:
    """Прямой участник хотя бы одного узла-очереди (руководитель и заместитель этого узла — тоже)."""
    unit_ids = [unit.id for unit in structure.units_of(user)]
    return bool(unit_ids) and Queue.objects.filter(unit_id__in=unit_ids).exists()


def _new_in_queue_available(user) -> bool:
    return _in_queue(user)


def _menu_available(user) -> bool:
    """Виден пункт меню «Заявки»: участник очереди, держатель «Все заявки» или ответственный по заявке."""
    from .services import access

    return access.menu_visible(user)


def _still_relevant(user_id: int, object_ref: str, *, unassigned_only: bool) -> bool:
    """Сотрудник не уволен и видит заявку по свежим правам; для «новой в очереди» ещё без ответственного и не закрыта."""
    from .services import access

    match = _REF.fullmatch(object_ref or "")
    if match is None:
        return False
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or user.state == "dismissed":
        return False
    ticket = Ticket.objects.filter(pk=int(match.group(1))).first()
    if ticket is None:
        return False
    access.scope(user, fresh=True)
    if not access.can_work(user, ticket):
        return False
    if unassigned_only:
        return ticket.assignee_id is None and ticket.kind != "closed"
    return True


def _relevant_new_in_queue(user_id: int, object_ref: str) -> bool:
    return _still_relevant(user_id, object_ref, unassigned_only=True)


def _relevant_other(user_id: int, object_ref: str) -> bool:
    return _still_relevant(user_id, object_ref, unassigned_only=False)


def notification_kinds() -> list[NotificationKind]:
    """Функция точки `notification_kinds`: четыре вида сервис-деска, свежие объекты при каждом вызове."""
    return [
        NotificationKind(
            code=NEW_IN_QUEUE, title="Новая заявка в моей очереди", module="Сервис-деск",
            events=NEW_IN_QUEUE_EVENTS, build=_new_in_queue, external_text="Новая заявка в вашей очереди",
            default_channels=ALL_CHANNELS, available=_new_in_queue_available,
            still_relevant=_relevant_new_in_queue, order=10),
        NotificationKind(
            code=ASSIGNED, title="Мне назначили заявку", module="Сервис-деск",
            events=("servicedesk.ticket_created", "servicedesk.assignee_changed"), build=_assigned,
            external_text="Вам назначена заявка", default_channels=ALL_CHANNELS, available=_menu_available,
            still_relevant=_relevant_other, order=20),
        NotificationKind(
            code=REQUESTER_REPLIED, title="Заявитель ответил", module="Сервис-деск",
            events=("servicedesk.reply_received",), build=_requester_replied,
            external_text="Заявитель ответил по вашей заявке", default_channels=ALL_CHANNELS,
            available=_menu_available, still_relevant=_relevant_other, order=30),
        NotificationKind(
            code=REPLY_FAILED, title="Ответ заявителю не ушёл", module="Сервис-деск",
            events=("servicedesk.reply_not_sent", "servicedesk.mail_failed"), build=_reply_failed,
            external_text="Ответ заявителю не ушёл", default_channels=ALL_CHANNELS, available=_menu_available,
            still_relevant=_relevant_other, order=40),
    ]
