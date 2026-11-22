"""Список задач: видимость, пресеты, фильтры, сортировки, страницы (срез 009, T-9204; FR-685, FR-686, NFR-712).

Один запрос с видимостью (автор, участник, управляемые узлы автора и исполнителя на момент просмотра) и
`deleted_at IS NULL`; ключи фильтров и сортировок — из белого списка, значения уходят параметрами. «Просрочены» —
календарная дата по Москве и статус не «Готово» (правило списка, отличное от момента уведомления).
"""
import datetime

from django.db.models import F, Q

from apps.core.widgets import moscow_today
from apps.org.services import structure
from apps.tasks.models import Task
from apps.tasks.services import access

PRESETS = ("mine", "authored", "subordinate", "work", "overdue")
DEADLINE_FILTERS = ("today", "week", "overdue", "none")
SORTS = ("deadline", "updated")
PER_PAGE = (20, 50)


def _visible(viewer) -> Q:
    """Условие видимости задач зрителем (без удалённых — отдельно)."""
    managed = structure.subtree_member_ids(access.managed_units(viewer))
    condition = Q(author=viewer) | Q(assignee=viewer) | Q(members__user=viewer)
    if managed:
        ids = sorted(managed)
        condition |= Q(author_id__in=ids) | Q(assignee_id__in=ids)
    return condition


def _base(viewer):
    return Task.objects.filter(_visible(viewer)).filter(deleted_at__isnull=True).distinct()


def _deadline_condition(value: str) -> Q | None:
    today = moscow_today()
    if value == "today":
        return Q(deadline=today)
    if value == "week":
        return Q(deadline__gt=today, deadline__lte=today + datetime.timedelta(days=7))
    if value == "overdue":
        return Q(deadline__lt=today) & ~Q(status=Task.Status.DONE)
    if value == "none":
        return Q(deadline__isnull=True)
    return None


def rows(viewer, *, preset="mine", filters=None, sort="", page=1, per_page=20) -> dict:
    """Страница списка: `rows`, `total`, `pages`, `page`, `per_page`."""
    filters = dict(filters or {})
    if preset not in PRESETS:
        preset = "mine"
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = 20
    if per_page not in PER_PAGE:
        per_page = 20
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1

    query = _base(viewer)
    if preset == "mine":
        query = query.filter(assignee=viewer)
    elif preset == "authored":
        query = query.filter(author=viewer)
    elif preset == "subordinate":
        managed = structure.subtree_member_ids(access.managed_units(viewer)) - {viewer.pk}
        query = query.filter(assignee_id__in=sorted(managed))
    elif preset == "work":
        query = query.filter(status=Task.Status.IN_PROGRESS)
    else:  # overdue
        query = query.filter(deadline__lt=moscow_today()).exclude(status=Task.Status.DONE)

    status = filters.get("status")
    if status in Task.Status.values:
        query = query.filter(status=status)
    deadline_filter = filters.get("deadline")
    if deadline_filter in DEADLINE_FILTERS:
        query = query.filter(_deadline_condition(deadline_filter))
    assignee = filters.get("assignee")
    if assignee not in (None, ""):
        try:
            query = query.filter(assignee_id=int(assignee))
        except (TypeError, ValueError):
            pass
    category = filters.get("category")
    if category == "none":
        query = query.filter(category__isnull=True)
    elif category not in (None, ""):
        try:
            query = query.filter(category_id=int(category))
        except (TypeError, ValueError):
            pass

    if sort == "updated":
        query = query.order_by("-updated_at", "-pk")
    else:  # по умолчанию и sort=deadline
        query = query.order_by(F("deadline").asc(nulls_last=True), "-updated_at", "-pk")

    total = query.count()
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page
    return {"rows": list(query[offset:offset + per_page]), "total": total, "pages": pages, "page": page,
            "per_page": per_page}