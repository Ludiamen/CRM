"""Регистрация заявки в движке автоматизации (PLAN-013, T-13021…T-13033)."""
from datetime import timedelta

from apps.core.services import permissions
from apps.org.services import structure

from .models import Category, Priority, Queue, Source, Status, Ticket, TicketEntry
from .services import access, assignment, dictionaries, queues

OPEN_KINDS = (Status.Kind.NEW, Status.Kind.IN_PROGRESS, Status.Kind.WAITING)

TRIGGERS = (
    ("ticket_created", "Заявка создана"),
    ("reply_received", "Ответ заявителя"),
    ("ticket_field_changed", "Изменено поле заявки"),
    ("ticket_status_changed", "Изменён статус заявки"),
    ("ticket_transferred", "Заявка передана"),
    ("ticket_closed", "Заявка закрыта"),
    ("sla_threshold", "Порог SLA"),
)


def subject():
    from apps.automation.extensions import Subject

    return Subject(
        type="ticket", title="Заявка",
        load=lambda pk: Ticket.objects.select_related(
            "status", "queue", "category", "priority", "assignee", "source").filter(pk=pk).first(),
        can_view=access.can_view, can_work=access.can_work,
        values=_values, queue_id=lambda ticket: ticket.queue_id,
        author_id=lambda ticket: ticket.created_by_id,
        assign=_assign, create_task=_create_task, change_status=_change_status, comment=_comment,
        validate_condition=_validate_condition, validate_scope=_validate_scope,
    )


def triggers():
    from apps.automation.extensions import Trigger

    fields = ("queue", "category", "priority", "status", "status_kind", "assignee", "source",
              "changed_field", "sla_deadline")
    return [Trigger("ticket", code, title, code, fields) for code, title in TRIGGERS]


def actions():
    return []


def recipients():
    from apps.automation.extensions import Recipient

    return [
        Recipient("ticket", "assignee", "Ответственный", lambda rule, ticket: [ticket.assignee_id]
                  if ticket.assignee_id else []),
        Recipient("ticket", "observers", "Наблюдатели очереди", _observers),
        Recipient("ticket", "queue_head", "Руководитель очереди", _heads),
        Recipient("ticket", "author", "Автор заявки", lambda rule, ticket: [ticket.created_by_id]
                  if ticket.created_by_id else []),
    ]


def _observers(rule, ticket):
    from .models import QueueObserver

    return list(QueueObserver.objects.filter(queue__unit_id=ticket.queue_id, removed_at__isnull=True)
                .values_list("user_id", flat=True))


def _heads(rule, ticket):
    return [person.pk for person in structure.heads_of_unit(ticket.queue_id)]


def _values(ticket) -> dict:
    return {
        "number": ticket.number,
        "id": ticket.number,
        "status": ticket.status_id,
        "status_name": ticket.status.name,
        "status_kind": ticket.kind,
        "queue": ticket.queue_id,
        "queue_name": ticket.queue.name,
        "category": ticket.category_id,
        "category_name": ticket.category.name if ticket.category_id else "",
        "priority": ticket.priority_id,
        "priority_name": ticket.priority.name,
        "assignee": ticket.assignee_id,
        "assignee_name": ticket.assignee.full_name if ticket.assignee_id else "",
        "source": ticket.source_id,
        "source_name": ticket.source.name,
    }


def _validate_scope(rule) -> str | None:
    if rule.scope == "queue" and not queues.is_queue(rule.queue_id):
        return "Узел не отмечен очередью"
    return None


def _active_user(user_id):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk=user_id, state__in=("active", "blocked")).first()


def _validate_condition(field, op, value) -> str | None:
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    for item in values:
        if field == "queue" and not Queue.objects.filter(unit_id=item).exists():
            return "Очередь не найдена"
        if field == "category" and not Category.objects.filter(pk=item, archived=False).exists():
            return "Категория в архиве или не найдена"
        if field == "priority" and not Priority.objects.filter(pk=item, archived=False).exists():
            return "Критичность в архиве или не найдена"
        if field == "status" and not Status.objects.filter(pk=item, archived=False).exists():
            return "Статус в архиве или не найден"
        if field == "source" and not Source.objects.filter(pk=item, archived=False).exists():
            return "Источник в архиве или не найден"
        if field == "assignee" and not _active_user(item):
            return "Сотрудник уволен или не найден"
        if field == "status_kind" and item not in Status.Kind.values:
            return "Неизвестный вид статуса"
    return None


def _assign(actor, ticket, mode: str, employee_id) -> str | None:
    if ticket.kind == Status.Kind.CLOSED:
        return "Заявка закрыта"
    if mode == "employee":
        user = _active_user(employee_id)
        if user is None or not access.is_participant(user, ticket.queue_id):
            return "Сотрудник не участник очереди"
        assignment.assign(ticket, user, actor=actor)
        return None
    if mode == "queue_head":
        heads = [person for person in structure.heads_of_unit(ticket.queue_id) if _active_user(person.pk)]
        if not heads:
            return "Нет руководителя очереди"
        user = min(heads, key=lambda person: (
            Ticket.objects.filter(queue_id=ticket.queue_id, assignee=person, kind__in=OPEN_KINDS).count(),
            person.full_name, person.pk))
        assignment.assign(ticket, user, actor=actor)
        return None
    if mode == "distribution":
        from .services import distribution

        if distribution.assign_or_notify(ticket, actor=actor, reason="automation") is None:
            return "Нет доступного исполнителя"
        return None
    return "Неизвестный режим назначения"


def _create_task(actor, ticket, params: dict) -> str | None:
    if not permissions.has_permission(actor, "tasks.use"):
        return "Нет права работать с задачами"
    from apps.core import extensions

    providers = extensions.registered("ticket_task_create")
    if not providers:
        return "Задачи недоступны"
    due_days = int(params.get("due_days") or 0)
    deadline = None
    if due_days:
        from django.utils import timezone

        deadline = timezone.localdate() + timedelta(days=due_days)
    assignee = actor
    chosen = params.get("assignee", "author")
    if chosen == "ticket_assignee" and ticket.assignee_id:
        assignee = ticket.assignee
    elif isinstance(chosen, int) or (isinstance(chosen, str) and chosen.isdigit()):
        assignee = _active_user(int(chosen))
        if assignee is None:
            return "Исполнитель уволен или не найден"
    title = _format(params.get("title") or "Задача по заявке №{number}", ticket)
    description = _format(params.get("description") or "Заявка №{number}: {url}", ticket)
    try:
        providers[0](actor, ticket.number, title=title, description=description, deadline=deadline,
                     assignee=assignee)
    except Exception as exc:
        return str(exc) or "Задача не создана"
    return None


def _format(text: str, ticket) -> str:
    values = _values(ticket)
    return str(text).format(
        number=values["number"], status=values["status_name"], queue=values["queue_name"],
        assignee=values["assignee_name"] or "не назначен", priority=values["priority_name"],
        url=f"/tickets/{values['number']}/")


def _change_status(actor, ticket, status_id) -> str | None:
    status = dictionaries.manual_statuses().filter(pk=status_id).first()
    if status is None:
        return "Статус недоступен для ручной смены"
    from .services import tickets

    if ticket.status_id == status.pk:
        return "Статус уже стоит"
    tickets.set_status_manual(ticket, status, actor=actor)
    return None


def _comment(actor, ticket, text: str) -> str | None:
    TicketEntry.objects.create(ticket=ticket, kind=TicketEntry.Kind.COMMENT, author=None, text=text,
                               event="automation")
    return None
