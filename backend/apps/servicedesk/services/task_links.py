"""Связь заявки с задачей со стороны сервис-деска (SPEC-012, FR-773…777).

Сервис-деск не импортирует `tasks`: он регистрирует на точке `ticket_task_seed` безопасный seed заявки и
`ticket_task_brief` — краткую справку, а задачи регистрируют `ticket_task_create` и `ticket_task_list`.
Так граница «модуль-приложение» сохраняется при включённом и выключенном модуле задач.
"""
from apps.core import extensions
from apps.core.services import permissions

from ..models import Ticket, TicketEntry
from . import access


def seed(actor, number: int):
    """Данные для предзаполнения задачи; только `can_work` заявки и `tasks.use`.

    Возвращает `None` для наблюдателя, не участника очереди и сотрудника без `tasks.use`.
    """
    ticket = Ticket.objects.filter(number=number).select_related("assignee").first()
    if ticket is None or not access.can_work(actor, ticket) or not permissions.has_permission(actor, "tasks.use"):
        return None
    last = (TicketEntry.objects.filter(ticket=ticket, kind=TicketEntry.Kind.INCOMING)
            .order_by("-at", "-pk").values_list("text", flat=True).first() or "")
    description = f"/tickets/{ticket.number}/"
    if last:
        description += f"\n\n{last}"
    assignee = ticket.assignee
    if assignee is not None and getattr(assignee, "state", None) == "dismissed":
        assignee = None
    return {"title": ticket.subject, "description": description, "assignee": assignee, "number": ticket.number}


def brief(actor, number: int):
    """Краткая справка заявки для карточки задачи; только `can_view`."""
    ticket = Ticket.objects.filter(number=number).select_related("status").first()
    if ticket is None or not access.can_view(actor, ticket):
        return None
    return {"number": ticket.number, "subject": ticket.subject, "kind": ticket.kind,
            "status": ticket.status.name, "url": f"/tickets/{ticket.number}/"}


def task_seed(actor, number: int):
    """Совместимое имя seed для представлений сервис-деска."""
    return seed(actor, number)


def tasks_for(actor, number: int, *, ticket=None) -> list[dict]:
    """Видимые смотрящему задачи заявки через зарегистрированную точку задач."""
    if ticket is None:
        ticket = Ticket.objects.filter(number=number).first()
    if ticket is None or not access.can_view(actor, ticket):
        return []
    providers = extensions.registered("ticket_task_list")
    return providers[0](actor, number) if providers else []
