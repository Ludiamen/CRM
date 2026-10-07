"""Публичный интерфейс сервис-деска: ответственный по заявке (PLAN-003, «Где живёт код»; CONTRACT-003, 6.8).

Ответственного ставят и снимают только эти функции (и `reconcile`). Первое появление ответственного ставит
`assigned_once`, двигает «новую» заявку в «в работе» и ставит письмо «взята в работу» (письмо откладывает сама
`letters.send`). Каждое изменение пишет событие ленты, журнал и событие шины.
"""
from dataclasses import dataclass

from django.db import transaction
from django.http import Http404

from apps.core.services import audit

from ..models import Priority, Status
from . import access, dictionaries, events, letters, replies, tickets
from .errors import ServiceDeskError

BULK_LIMIT = 100
BULK_ACTIONS = ("assign", "transfer", "priority")


@dataclass(frozen=True)
class Skipped:
    """Пропущенная заявка группового действия: номер (`None` у недоступной), код причины и её сообщение."""

    number: int | None
    code: str
    message: str


@dataclass(frozen=True)
class BulkResult:
    """Итог группового действия: номера выполненных и пропущенных заявок в порядке входа."""

    done: list[int]
    skipped: list[Skipped]


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def _guard(ticket, actor) -> None:
    """Блокирует заявку и проверяет по порядку 6.1: `no_access`, затем `ticket_closed`."""
    tickets._lock(ticket)
    if not access.can_work(actor, ticket):
        raise _error("no_access", "нет доступа")
    tickets.require_open(ticket)


def _require_participant(user, ticket) -> None:
    if user is None or not access.is_participant(user, ticket.queue_id):
        raise _error("not_participant", "Ответственным может быть только участник очереди заявки")


def _set_assignee(ticket, user, *, actor, ip=None) -> None:
    """Ставит ответственного `user`: событие ленты, журнал `ticket.assigned`, статус и письмо при первом появлении, шина."""
    before = ticket.assignee
    first = not ticket.assigned_once
    ticket.assignee = user
    ticket.assigned_once = True
    ticket.save(update_fields=["assignee", "assigned_once", "updated_at"])
    before_name, before_id = (before.full_name, before.pk) if before is not None else ("", None)
    replies.add_event(ticket, "assignee_changed", actor=actor, data={
        "before": before_name, "after": user.full_name, "before_id": before_id, "after_id": user.pk})
    audit.record("ticket.assigned", actor=actor, object_type="ticket", object_id=ticket.number,
                 before={"assignee": before_name, "assignee_id": before_id},
                 after={"assignee": user.full_name, "assignee_id": user.pk}, ip=ip)
    if first:
        if ticket.kind == Status.Kind.NEW:
            tickets.set_status(ticket, dictionaries.default_status(Status.Kind.IN_PROGRESS), actor=actor,
                               reason="assigned")
        letters.send(ticket, "ticket.assigned")
    events.assignee_changed(ticket, before_id=before_id, after_id=user.pk)


def clear_assignee(ticket, *, actor, reason: str, ip=None) -> bool:
    """Снимает ответственного: событие ленты `assignee_changed` (`after_id=None`), журнал `ticket.assignee_removed` с
    `after["reason"]` (`manual`, `queue_changed`, `not_participant`) и событие шины.

    Общий помощник `unassign`, `transfer.transfer`, `transfer.change_category` и `closing.reopen`. Отказов
    `ticket_closed` и `no_access` не проверяет (это дело вызывающего), письма и статуса не трогает; `actor=None` —
    система. Возвращает `False`, если ответственного не было.
    """
    with transaction.atomic():
        before = ticket.assignee
        if before is None:
            return False
        ticket.assignee = None
        ticket.save(update_fields=["assignee", "updated_at"])
        replies.add_event(ticket, "assignee_changed", actor=actor, data={
            "before": before.full_name, "after": "", "before_id": before.pk, "after_id": None})
        audit.record("ticket.assignee_removed", actor=actor, object_type="ticket", object_id=ticket.number,
                     before={"assignee": before.full_name, "assignee_id": before.pk},
                     after={"assignee": "", "assignee_id": None, "reason": reason}, ip=ip)
        events.assignee_changed(ticket, before_id=before.pk, after_id=None)
    return True


def take(ticket, *, actor, ip=None) -> bool:
    """Берёт заявку себе (участник очереди); `False` — `actor` уже ответственный."""
    with transaction.atomic():
        _guard(ticket, actor)
        _require_participant(actor, ticket)
        if ticket.assignee_id == actor.pk:
            return False
        _set_assignee(ticket, actor, actor=actor, ip=ip)
    return True


def assign(ticket, user, *, actor, ip=None) -> bool:
    """Назначает `user` (участника очереди заявки); `False` — он уже ответственный."""
    with transaction.atomic():
        _guard(ticket, actor)
        _require_participant(user, ticket)
        if ticket.assignee_id == user.pk:
            return False
        _set_assignee(ticket, user, actor=actor, ip=ip)
    return True


def unassign(ticket, *, actor, ip=None) -> bool:
    """Снимает ответственного вручную: письма нет, `assigned_once` и статус не меняются; `False` — снимать некого."""
    with transaction.atomic():
        _guard(ticket, actor)
        return clear_assignee(ticket, actor=actor, reason="manual", ip=ip)


def apply_default_assignee(ticket, *, actor=None, ip=None) -> bool:
    """Назначает ответственного по умолчанию категории, если ответственного нет, а он сейчас участник очереди.

    Назначает как первое появление (с письмом, если `assigned_once` был ложен). Зовёт `transfer.change_category`.
    """
    with transaction.atomic():
        tickets._lock(ticket)
        category = ticket.category
        default = category.default_assignee if category is not None else None
        if ticket.assignee_id is not None or default is None or not access.is_participant(default, ticket.queue_id):
            return False
        _set_assignee(ticket, default, actor=actor, ip=ip)
    return True


def _bulk_one(ticket, action: str, actor, ip, params: dict) -> None:
    """Одно групповое действие над одной заявкой: те же функции, что в карточке (через имя модуля — точка подмены)."""
    if action == "assign":
        assign(ticket, params.get("user"), actor=actor, ip=ip)
    elif action == "transfer":
        from . import transfer

        transfer.transfer(ticket, params.get("queue_id"), reason=params.get("reason", ""), actor=actor, ip=ip)
    else:
        priority = Priority.objects.filter(pk=params.get("priority_id")).first()
        if priority is None:
            raise _error("archived_value", "Значение в архиве: выберите другое")
        tickets.update_fields(ticket, actor=actor, ip=ip, priority=priority)


def bulk(numbers, action, *, actor, ip=None, **params) -> BulkResult:
    """Групповое действие `assign`, `transfer` или `priority` над заявками (FR-241).

    Повторы номеров убираются с сохранением порядка, затем проверяется предел в 100 разных номеров (`bulk_limit`, до
    любой работы). Каждая заявка — в своей точке сохранения; невидимая и несуществующая — `Skipped(None, "no_access")`.
    """
    if action not in BULK_ACTIONS:
        raise _error("bad_action", "Неизвестное групповое действие")
    unique = list(dict.fromkeys(numbers))
    if len(unique) > BULK_LIMIT:
        raise _error("bulk_limit", "За один раз можно обработать не больше 100 заявок")
    done, skipped = [], []
    for number in unique:
        try:
            with transaction.atomic():
                ticket = tickets.get_for(actor, number)
                _bulk_one(ticket, action, actor, ip, params)
        except Http404:
            skipped.append(Skipped(None, "no_access", "нет доступа"))
        except ServiceDeskError as refused:
            skipped.append(Skipped(number, refused.code, refused.message))
        else:
            done.append(number)
    return BulkResult(done=done, skipped=skipped)
