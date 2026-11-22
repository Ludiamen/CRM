"""Справочник категорий задач (срез 009, T-9208; FR-683; CONTRACT-009, 6.2).

Ведёт администратор под `settings.portal`; удаление снимает категорию у задач (`SET_NULL`), задачи остаются.
Новая задача без выбора — «Без категории».
"""
from django.db import transaction
from django.db.models import Max

from apps.tasks.models import TaskCategory
from apps.tasks.services.errors import TasksError

TITLE_MAX = 100


def all() -> list[TaskCategory]:
    """Категории по порядку."""
    return list(TaskCategory.objects.order_by("position", "pk"))


def _clean_title(value) -> str:
    title = (value or "").strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise TasksError("category_title_range", "title")
    return title


@transaction.atomic
def add(actor, title) -> TaskCategory:
    """Добавить категорию в конец справочника."""
    title = _clean_title(title)
    if TaskCategory.objects.filter(title=title).exists():
        raise TasksError("category_title_taken", "title")
    position = (TaskCategory.objects.aggregate(top=Max("position"))["top"] or 0) + 1
    return TaskCategory.objects.create(title=title, position=position)


@transaction.atomic
def rename(actor, category, title, position=None) -> TaskCategory:
    """Переименовать категорию и при желании задать её порядок."""
    title = _clean_title(title)
    if TaskCategory.objects.filter(title=title).exclude(pk=category.pk).exists():
        raise TasksError("category_title_taken", "title")
    category.title = title
    fields = ["title"]
    if position is not None:
        try:
            category.position = max(0, int(position))
            fields.append("position")
        except (TypeError, ValueError):
            pass
    category.save(update_fields=fields)
    return category


@transaction.atomic
def delete(actor, category) -> None:
    """Удалить категорию; у задач она снимается, задачи остаются."""
    category.delete()


@transaction.atomic
def set_for_task(actor, task, category) -> None:
    """Сменить категорию задачи (права полей проверяет служба задач)."""
    from apps.tasks.services import tasks as service

    service.update(actor, task, category=category)