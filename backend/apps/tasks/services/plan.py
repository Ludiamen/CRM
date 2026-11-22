"""Личные колонки «Моего плана» (срез 009, T-9207; FR-682; CONTRACT-009, 6.2, 7).

Три колонки «Сегодня», «На этой неделе», «Потом» создаются лениво при первом открытии. Правит колонки только
владелец; удаление переносит задачи в первую, последнюю удалить нельзя. Перенос карточки меняет только
`plan_column` и пишет журнал «было/стало».
"""
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.services import audit
from apps.tasks.models import PlanColumn, Task
from apps.tasks.services.errors import TasksError

DEFAULT_TITLES = ("Сегодня", "На этой неделе", "Потом")
TITLE_MAX = 100


def columns_of(user) -> list[PlanColumn]:
    """Колонки владельца по порядку."""
    return list(PlanColumn.objects.filter(user=user).order_by("position", "pk"))


def ensure_defaults(user) -> list[PlanColumn]:
    """Создать три колонки при первом открытии; существующие не трогает."""
    columns = columns_of(user)
    if columns:
        return columns
    for position, title in enumerate(DEFAULT_TITLES):
        PlanColumn.objects.get_or_create(user=user, title=title, defaults={"position": position})
    return columns_of(user)


def _clean_title(value) -> str:
    title = (value or "").strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise TasksError("column_title_range", "title")
    return title


def _own(user, column) -> PlanColumn:
    if column.user_id != getattr(user, "pk", None):
        raise TasksError("plan_forbidden", "column")
    return column


@transaction.atomic
def add_column(user, title) -> PlanColumn:
    """Добавить колонку в конец."""
    title = _clean_title(title)
    if PlanColumn.objects.filter(user=user, title=title).exists():
        raise TasksError("column_title_taken", "title")
    position = (PlanColumn.objects.filter(user=user).aggregate(top=Max("position"))["top"] or 0) + 1
    return PlanColumn.objects.create(user=user, title=title, position=position)


@transaction.atomic
def rename_column(user, column, title, position=None) -> PlanColumn:
    """Переименовать свою колонку и при желании задать её место в порядке."""
    _own(user, column)
    title = _clean_title(title)
    if PlanColumn.objects.filter(user=user, title=title).exclude(pk=column.pk).exists():
        raise TasksError("column_title_taken", "title")
    column.title = title
    column.save(update_fields=["title"])
    if position is not None:
        try:
            position = max(0, int(position))
        except (TypeError, ValueError):
            position = None
    if position is not None:
        columns = [item for item in columns_of(user) if item.pk != column.pk]
        position = min(position, len(columns))
        columns.insert(position, column)
        for index, item in enumerate(columns):
            if item.position != index:
                item.position = index
                item.save(update_fields=["position"])
    return column


@transaction.atomic
def delete_column(user, column) -> PlanColumn:
    """Удалить свою колонку; задачи уходят в первую, последнюю удалить нельзя."""
    _own(user, column)
    columns = columns_of(user)
    if len(columns) <= 1:
        raise TasksError("column_last", "column")
    first = next(item for item in columns if item.pk != column.pk)
    Task.objects.filter(plan_column=column).update(plan_column=first, updated_at=timezone.now())
    column.delete()
    return first


@transaction.atomic
def move_task(user, task, column) -> Task:
    """Перенести задачу в свою колонку; статус не меняется, пишется журнал."""
    _own(user, column)
    before = task.plan_column.title if task.plan_column_id else ""
    task.plan_column = column
    task.updated_at = timezone.now()
    task.save(update_fields=["plan_column", "updated_at"])
    audit.record("tasks.changed", actor=user, object_type="tasks.task", object_id=task.pk,
                 before={"plan_column": before}, after={"plan_column": column.title})
    return task