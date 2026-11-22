"""Колонки четырёх досок (срез 009, T-9205/T-9206; FR-679…684).

Каждая функция возвращает список колонок `{"key", "title", "tasks", "count"}` в порядке доски. «Стадии» —
четыре статуса; «Сроки» — `overdue`/`today`/`week`/`none` без «Готово» и без срока дальше семи дней; «Мой план» —
личные колонки владельца (три создаются лениво), задача без колонки — в первой; «Категории» — по `position`,
«Без категории» (`key="none"`) последней.
"""
import datetime

from django.db.models import Q

from apps.core.widgets import moscow_today
from apps.tasks.models import PlanColumn, Task, TaskCategory
from apps.tasks.services import access, list as task_list, plan

STATUS_TITLES = ((Task.Status.NEW, "Новая"), (Task.Status.IN_PROGRESS, "В работе"),
                 (Task.Status.WAITING, "Ждёт"), (Task.Status.DONE, "Готово"))
DEADLINE_TITLES = (("overdue", "Просрочены"), ("today", "Сегодня"), ("week", "На неделе"), ("none", "Без срока"))


def _column(key, title, tasks) -> dict:
    rows = list(tasks)
    return {"key": key, "title": title, "tasks": rows, "count": len(rows)}


def visible_tasks(viewer):
    """Видимые неудалённые задачи зрителя (тот же набор, что у списка)."""
    return task_list._base(viewer)


def status_columns(viewer) -> list[dict]:
    """«Стадии»: четыре колонки-статуса с числом задач."""
    base = visible_tasks(viewer)
    return [_column(key, title, base.filter(status=key)) for key, title in STATUS_TITLES]


def deadline_columns(viewer) -> list[dict]:
    """«Сроки»: группы по дате; «Готово» и срок дальше семи дней не показываются."""
    today = moscow_today()
    soon = today + datetime.timedelta(days=7)
    base = visible_tasks(viewer).exclude(status=Task.Status.DONE).filter(
        Q(deadline__isnull=True) | Q(deadline__lte=soon))
    groups = {
        "overdue": base.filter(deadline__lt=today),
        "today": base.filter(deadline=today),
        "week": base.filter(deadline__gt=today, deadline__lte=soon),
        "none": base.filter(deadline__isnull=True),
    }
    return [_column(key, title, groups[key].order_by("deadline", "pk")) for key, title in DEADLINE_TITLES]


def plan_columns(viewer, owner=None) -> list[dict]:
    """«Мой план»: колонки владельца; задача без колонки показывается в первой."""
    owner = owner or viewer
    columns = plan.ensure_defaults(owner)
    base = visible_tasks(viewer).filter(assignee=owner)
    if owner.pk != viewer.pk:
        # Чужой план — только чтение: карточки те же, права двигать проверяет `access.can_move`.
        pass
    result = []
    first = columns[0]
    for index, column in enumerate(columns):
        tasks = base.filter(plan_column=column)
        if index == 0:
            tasks = base.filter(Q(plan_column=column) | Q(plan_column__isnull=True))
        result.append(_column(str(column.pk), column.title, tasks.order_by("deadline", "pk")))
    orphan = base.filter(plan_column__isnull=True)
    if not columns:
        result.append(_column("none", "Без колонки", orphan))
    return result


def category_columns(viewer) -> list[dict]:
    """«Категории»: справочник по `position`, «Без категории» последней."""
    base = visible_tasks(viewer)
    result = [_column(str(category.pk), category.title, base.filter(category=category))
              for category in TaskCategory.objects.order_by("position", "pk")]
    result.append(_column("none", "Без категории", base.filter(category__isnull=True)))
    return result