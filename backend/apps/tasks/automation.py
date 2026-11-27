"""Регистрация задачи в движке автоматизации (PLAN-013, T-13024/T-13031…T-13033)."""
from apps.core.services import permissions

from .models import Task, TaskCategory, TaskComment
from .services import access

TRIGGERS = (
    ("task_created", "Задача создана"),
    ("task_field_changed", "Изменено поле задачи"),
    ("task_status_changed", "Изменён статус задачи"),
    ("task_threshold", "Порог срока задачи"),
    ("approval_started", "Согласование запущено"),
    ("approval_stage_completed", "Этап согласования завершён"),
    ("approval_completed", "Маршрут согласован"),
    ("approval_rejected", "Маршрут отклонён"),
    ("approval_returned", "Маршрут возвращён"),
    ("approval_cancelled", "Маршрут отменён"),
)


def subject():
    from apps.automation.extensions import Subject

    return Subject(
        type="task", title="Задача",
        load=lambda pk: Task.objects.select_related("assignee", "author", "category").filter(
            pk=pk, deleted_at__isnull=True).first(),
        can_view=access.visible, can_work=access.can_change_status,
        values=_values, queue_id=lambda task: None, author_id=lambda task: task.author_id,
        assign=_assign, create_task=_create_task, change_status=_change_status, comment=_comment,
        validate_condition=_validate_condition, validate_scope=_validate_scope,
        threshold_tick=_threshold_tick,
    )


def triggers():
    from apps.automation.extensions import Trigger

    fields = ("status", "category", "assignee", "author", "has_deadline", "changed_field")
    return [Trigger("task", code, title, code, fields) for code, title in TRIGGERS]


def actions():
    return []


def recipients():
    from apps.automation.extensions import Recipient

    return [
        Recipient("task", "assignee", "Исполнитель", lambda rule, task: [task.assignee_id]),
        Recipient("task", "author", "Автор задачи", lambda rule, task: [task.author_id]),
    ]


def _values(task) -> dict:
    return {
        "id": task.pk,
        "number": task.pk,
        "status": task.status,
        "status_name": task.get_status_display(),
        "category": task.category_id,
        "category_name": task.category.title if task.category_id else "",
        "assignee": task.assignee_id,
        "assignee_name": task.assignee.full_name,
        "author": task.author_id,
        "author_name": task.author.full_name,
        "has_deadline": task.deadline is not None,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "queue_name": "",
        "priority_name": "",
    }


def _validate_scope(rule) -> str | None:
    return None


def _threshold_tick():
    """Пороги задач: вызов задания tasks без импорта `apps.tasks` из автоматизации."""
    from .tasks import tasks_automation_tick

    return tasks_automation_tick()


def _active_user(user_id):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk=user_id, state__in=("active", "blocked")).first()


def _validate_condition(field, op, value) -> str | None:
    values = value if isinstance(value, (list, tuple, set)) else (value,)
    for item in values:
        if field == "status" and item not in Task.Status.values:
            return "Неизвестный статус задачи"
        if field == "category" and (item is not None and not TaskCategory.objects.filter(pk=item).exists()):
            return "Категория не найдена"
        if field in ("assignee", "author") and not _active_user(item):
            return "Сотрудник уволен или не найден"
        if field == "has_deadline" and not isinstance(item, bool):
            return "«Есть срок» — да или нет"
    return None


def _assign(actor, task, mode: str, employee_id) -> str | None:
    if mode != "employee":
        return "Для задачи доступно назначение конкретному сотруднику"
    user = _active_user(employee_id)
    if user is None:
        return "Сотрудник уволен или не найден"
    from .services import tasks as task_service
    from .services.errors import TasksError

    try:
        task_service.update(actor, task, assignee=user)
    except TasksError as exc:
        return exc.message
    return None


def _create_task(actor, task, params: dict) -> str | None:
    if not permissions.has_permission(actor, "tasks.use"):
        return "Нет права работать с задачами"
    from datetime import timedelta

    from django.utils import timezone

    from .services import tasks as task_service

    due_days = int(params.get("due_days") or 0)
    deadline = timezone.localdate() + timedelta(days=due_days) if due_days else None
    assignee = actor
    chosen = params.get("assignee", "author")
    if isinstance(chosen, int) or (isinstance(chosen, str) and chosen.isdigit()):
        user = _active_user(int(chosen))
        if user is None:
            return "Исполнитель уволен или не найден"
        assignee = user
    title = str(params.get("title") or "Задача по задаче №{number}").format(
        number=task.pk, status=task.get_status_display(), queue="", assignee=task.assignee.full_name,
        priority="", url=f"/tasks/{task.pk}/")
    description = str(params.get("description") or "").format(
        number=task.pk, status=task.get_status_display(), queue="", assignee=task.assignee.full_name,
        priority="", url=f"/tasks/{task.pk}/")
    task_service.create(actor, title=title, description=description, deadline=deadline, assignee=assignee)
    return None


def _change_status(actor, task, status) -> str | None:
    if status not in Task.Status.values:
        return "Неизвестный статус задачи"
    from .services import tasks as task_service
    from .services.errors import TasksError

    try:
        task_service.change_status(actor, task, status)
    except TasksError as exc:
        return exc.message
    return None


def _comment(actor, task, text: str) -> str | None:
    if getattr(actor, "state", "") == "dismissed":
        return "Автор правила уволен"
    TaskComment.objects.create(task=task, author=actor, text=text)
    return None
