"""Создание задачи из заявки и связь с ней (SPEC-012, FR-773…777).

Модуль задач не импортирует `servicedesk`: seed и краткая справка заявки приходят через точки
`ticket_task_seed` / `ticket_task_brief`, которые регистрирует сервис-деск.
"""
from apps.core import extensions
from apps.core.services import permissions
from apps.tasks.models import Task
from apps.tasks.services import access as task_access
from apps.tasks.services import tasks as task_service
from apps.tasks.services.errors import TasksError


def _provider(point: str):
    providers = extensions.registered(point)
    return providers[0] if providers else None


def _seed(actor, number: int):
    provider = _provider("ticket_task_seed")
    return provider(actor, number) if provider is not None else None


def seed_for_ticket(actor, number: int):
    """Seed заявки для формы (делегат точки `ticket_task_seed`)."""
    return _seed(actor, number)


def create_from_ticket(actor, number: int, **fields):
    """Создать задачу из видимой заявки; исполнитель по умолчанию — её ответственный, иначе автор."""
    if not permissions.has_permission(actor, "tasks.use"):
        raise TasksError("task_ticket_hidden", "ticket")
    seed = _seed(actor, number)
    if seed is None:
        raise TasksError("task_ticket_hidden", "ticket")
    assignee = fields.pop("assignee", None) or seed["assignee"] or actor
    if assignee.pk != getattr(seed.get("assignee"), "pk", None) and not task_access.can_set_task(actor, assignee):
        raise TasksError("task_assignee_forbidden", "assignee")
    task = task_service.create(
        actor, title=fields.pop("title", seed["title"]),
        description=fields.pop("description", seed["description"]),
        deadline=fields.pop("deadline", None), assignee=assignee,
        members=fields.pop("members", ()), category=fields.pop("category", None),
        plan_column=fields.pop("plan_column", None), assignee_authorized=True,
        ticket_number=number,
    )
    from apps.core.services import audit
    audit.record("servicedesk.task_created", actor=actor, object_type="ticket", object_id=str(number),
                 after={"task_id": task.pk, "assignee_id": assignee.pk})
    return task


def list_tasks(actor, number: int) -> list[dict]:
    """Видимые смотрящему неудалённые задачи заявки: номер, название, статус, ссылка."""
    result = []
    for task in Task.objects.filter(ticket_number=number, deleted_at__isnull=True).select_related("assignee"):
        if not task_access.visible(actor, task):
            continue
        result.append({"id": task.pk, "number": task.pk, "title": task.title,
                       "status": task.get_status_display(), "link": f"/tasks/{task.pk}/"})
    return result


def ticket_for_task(actor, task):
    """Актуальная справка заявки для карточки задачи; `None`, если заявка скрыта."""
    if not task.ticket_number:
        return None
    provider = _provider("ticket_task_brief")
    return provider(actor, task.ticket_number) if provider is not None else None


def tasks_for_ticket(actor, number: int) -> list[dict]:
    """Список задач заявки для карточки (делегат `list_tasks`)."""
    return list_tasks(actor, number)
