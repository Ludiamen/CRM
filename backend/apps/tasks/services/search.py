"""Поиск задач и раздел карточки сотрудника (срез 009, T-9214; FR-697, FR-698; CONTRACT-009, 11).

Группа «Задачи» (order 62): номер, название, исполнитель, срок, статус и отрывок; только видимые неудалённые
задачи, слова — параметрами, потолок 300. Раздел карточки сотрудника — видимые смотрящему задачи, где сотрудник
автор, исполнитель, соисполнитель или наблюдатель.
"""
from django.db.models import Q

from apps.core.extensions import CardSection, SearchProvider, SearchRow
from apps.tasks.models import Task, TaskMember
from apps.tasks.services import access, list as task_list

CEILING = 300


def available(user) -> bool:
    """Группа доступна сотруднику с `tasks.use`."""
    from apps.core.services import permissions

    return permissions.has_permission(user, "tasks.use")


def _worded(user, parsed):
    query = task_list._base(user)
    raw = (parsed.raw or "").strip()
    text = (getattr(parsed, "text", "") or "").strip()
    number = getattr(parsed, "number", None)
    if number is None and (text.isdigit() or raw.isdigit()):
        number = int(text or raw)
    if number is not None:
        return query.filter(pk=number)
    words = [word for word in (parsed.words or []) if word]
    if not words and not parsed.raw:
        return query.none()
    condition = Q()
    for word in words:
        condition &= (Q(title__icontains=word) | Q(description__icontains=word)
                      | Q(comments__text__icontains=word))
    if words:
        query = query.filter(condition)
    return query.distinct()


def search(user, parsed, limit: int, offset: int) -> list:
    """Строки выдачи задач: номер, название, исполнитель, срок, статус и отрывок."""
    from apps.core.services import text as core_text

    if not available(user):
        return []
    limit = min(int(limit), CEILING)
    rows = _worded(user, parsed).select_related("assignee").order_by("-updated_at", "-pk")[offset:offset + limit]
    result = []
    for task in rows:
        snippet = core_text.snippet(task.description or task.title, 100)
        title = (f"#{task.pk} {task.title} · {task.assignee.full_name} · "
                 f"{task.deadline.strftime('%d.%m.%Y') if task.deadline else 'без срока'} · "
                 f"{task.get_status_display()} — {snippet}")
        result.append(SearchRow(title=title, subtitle="Задачи", url=f"/tasks/{task.pk}/"))
    return result


def count(user, parsed) -> tuple[int, bool]:
    """Число найденных задач с потолком 300."""
    if not available(user):
        return 0, False
    total = _worded(user, parsed).count()
    return min(total, CEILING), total > CEILING


def search_providers() -> list:
    """Запись точки `search_providers`: группа «Задачи» (order 62)."""
    return [SearchProvider(key="tasks", title="Задачи", order=62, search=search, count=count, available=available)]


def card_section(viewer, person) -> list:
    """Раздел «Задачи» карточки сотрудника: видимые смотрящему задачи этого сотрудника."""
    member_ids = TaskMember.objects.filter(user=person).values_list("task_id", flat=True)
    query = Task.objects.filter(
        Q(author=person) | Q(assignee=person) | Q(pk__in=member_ids), deleted_at__isnull=True).distinct()
    rows = [task for task in query.select_related("assignee") if access.visible(viewer, task)]
    if not rows:
        return []
    return [CardSection("tasks", "profile", 75, "tasks/_card_section.html",
                        {"tasks": rows, "url": f"/tasks/?assignee={person.pk}"})]