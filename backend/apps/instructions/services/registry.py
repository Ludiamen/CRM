"""Реестр поручений (срез 010, T-10207; FR-713, 717; CONTRACT-010, раздел 11, К23).

Видимость — участники и руководители цепочки; администратор чужих не видит. Пресеты `mine`, `control`,
`subordinate`, `overdue`; фильтры и сортировки — из белого списка, значения — параметрами SQL. Строка — `Instruction`
с вычисленным `.state` и `.state_title`.
"""
import datetime
import math

from django.db.models import Q

from apps.core.services import roles
from apps.core.widgets import moscow_today
from apps.instructions.models import Instruction
from apps.instructions.services import access, dates

PER_PAGE = (20, 50)
PRESETS = ("mine", "control", "subordinate", "overdue")
STATES = ("control", "waiting", "review", "returned", "overdue", "done")


def _visible(viewer):
    managed = sorted(access.managed_units(viewer))
    query = (Q(author=viewer) | Q(controller=viewer) | Q(assignee=viewer) | Q(members__user=viewer))
    if not roles.is_active_admin(viewer) and managed:
        query |= (Q(assignee__memberships__unit_id__in=managed)
                  | Q(author__memberships__unit_id__in=managed))
    return Instruction.objects.filter(query, deleted_at__isnull=True).distinct()


def _apply_filters(queryset, filters: dict, viewer):
    today = moscow_today()
    filters = filters or {}
    if filters.get("basis"):
        queryset = queryset.filter(basis_kind_id=filters["basis"])
    if filters.get("assignee"):
        queryset = queryset.filter(assignee_id=filters["assignee"])
    if filters.get("q"):
        text = str(filters["q"]).strip()
        by_number = Q(pk=int(text)) if text.isdigit() else Q(pk=-1)
        queryset = queryset.filter(Q(title__icontains=text) | by_number)
    deadline = filters.get("deadline")
    if deadline == "overdue":
        queryset = queryset.filter(deadline__lt=today)
    elif deadline == "today":
        queryset = queryset.filter(deadline=today)
    elif deadline == "week":
        queryset = queryset.filter(deadline__gte=today,
                                   deadline__lte=today + datetime.timedelta(days=7))
    elif deadline == "month":
        queryset = queryset.filter(deadline__gte=today,
                                   deadline__lte=today + datetime.timedelta(days=30))
    return queryset


def _preset(queryset, preset: str, viewer):
    if preset == "control":
        return queryset.filter(controller=viewer)
    if preset == "mine":
        return queryset.filter(Q(assignee=viewer) | Q(members__user=viewer)).distinct()
    if preset == "subordinate":
        managed = sorted(access.managed_units(viewer))
        if not managed:
            return queryset.none()
        return queryset.extra(
            where=["instructions_instruction.assignee_id IN ("
                   "SELECT user_id FROM org_membership WHERE unit_id = ANY(%s))"],
            params=[managed]).exclude(assignee=viewer)
    return queryset


def rows(viewer, *, preset="mine", filters=None, sort="", page=1, per_page=20) -> dict:
    """Страница реестра: строки с состоянием, всего, страницы."""
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
    queryset = _preset(_apply_filters(_visible(viewer), filters, viewer), preset, viewer)
    ordered = list(queryset.order_by("pk"))
    for row in ordered:
        state = dates.state_of(row)
        row.state = state
        row.state_title = dates.STATE_TITLES[state]
    state_filter = (filters or {}).get("state")
    if state_filter in STATES:
        ordered = [row for row in ordered if row.state == state_filter]
    if preset == "overdue":
        ordered = [row for row in ordered if row.state == "overdue"]
    if sort == "updated":
        ordered.sort(key=lambda row: (row.updated_at, row.pk))
    else:
        ordered.sort(key=lambda row: (row.deadline is None, row.deadline, row.updated_at, row.pk))
    total = len(ordered)
    pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    return {"rows": ordered[start:start + per_page], "total": total, "pages": pages, "page": page,
            "per_page": per_page}