"""Публичный интерфейс сервис-деска: список заявок, пресеты, счётчик и пункты меню (CONTRACT-003, 6.21).

Список всегда строится поверх `access.visible_tickets`; общее число не считается при выдаче страницы, его даёт
`count` по кнопке. Модели `org` не импортируются: очередь читается по имени связи `queue`.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from ..models import Status, Ticket
from . import access, queues, search

PRESETS = ("mine", "unassigned", "my_queues", "waiting", "closed", "all")
SORTS = ("number", "created", "last_message", "priority")
OPEN_KINDS = (Status.Kind.NEW, Status.Kind.IN_PROGRESS, Status.Kind.WAITING)
PAGE_SIZE = 50

_SORT_FIELDS = {
    "number": ("number",),
    "created": ("created_at", "number"),
    "last_message": ("last_message_at", "number"),
    "priority": ("priority__order", "number"),
}


@dataclass(frozen=True)
class Filters:
    """Условия фильтра списка (все необязательные, сочетаются через «и»)."""

    queue: int | None = None
    category: int | None = None
    priority: int | None = None
    status: int | None = None
    kind: str | None = None
    assignee: int | str | None = None
    client_unit: int | None = None
    source: int | None = None
    created_from: date | None = None
    created_to: date | None = None
    q: str | None = None


@dataclass(frozen=True)
class Page:
    """Страница списка: до `PAGE_SIZE` строк, признак следующей страницы и подсказка поиска."""

    rows: list
    has_next: bool
    page: int
    preset: str
    hint: str


def my_queue_ids(user) -> frozenset[int]:
    """Отмеченные узлы среди узлов работы `user`; у держателя «Все заявки» — все отмеченные."""
    marked = {unit.id for unit in queues.marked_units()}
    access_scope = access.scope(user)
    if access_scope.has_all:
        return frozenset(marked)
    return frozenset(marked & access_scope.work_units)


def default_preset(user) -> str:
    """«Мои очереди» у участника очереди и держателя «Все заявки», иначе «Мои»."""
    if access.scope(user).has_all or my_queue_ids(user):
        return "my_queues"
    return "mine"


def _start_of_day(day: date) -> datetime:
    """Начало дня по поясу портала."""
    return timezone.make_aware(datetime.combine(day, time.min))


def _apply_preset(queryset, user, preset: str):
    if preset == "mine":
        return queryset.filter(assignee=user, kind__in=OPEN_KINDS)
    if preset == "unassigned":
        return queryset.filter(queue_id__in=my_queue_ids(user), assignee__isnull=True, kind__in=OPEN_KINDS)
    if preset == "my_queues":
        return queryset.filter(queue_id__in=my_queue_ids(user), kind__in=OPEN_KINDS)
    if preset == "waiting":
        return queryset.filter(kind=Status.Kind.WAITING)
    if preset == "closed":
        return queryset.filter(kind=Status.Kind.CLOSED)
    return queryset


def _apply_filters(queryset, filters: Filters | None):
    if filters is None:
        return queryset
    for name in ("queue", "category", "priority", "status", "client_unit", "source"):
        value = getattr(filters, name)
        if value is not None:
            queryset = queryset.filter(**{f"{name}_id": value})
    if filters.kind:
        queryset = queryset.filter(kind=filters.kind)
    if filters.assignee == "none":
        queryset = queryset.filter(assignee__isnull=True)
    elif filters.assignee is not None:
        queryset = queryset.filter(assignee_id=filters.assignee)
    if filters.created_from is not None:
        queryset = queryset.filter(created_at__gte=_start_of_day(filters.created_from))
    if filters.created_to is not None:
        queryset = queryset.filter(created_at__lt=_start_of_day(filters.created_to + timedelta(days=1)))
    if filters.q:
        queryset = search.apply(queryset, filters.q)
    return queryset


def _base(user, preset: str | None, filters: Filters | None):
    """Выбранный пресет и заявки: видимые, по пресету, по фильтру."""
    chosen = preset if preset in PRESETS else default_preset(user)
    queryset = _apply_filters(_apply_preset(access.visible_tickets(user), user, chosen), filters)
    return chosen, queryset


def build(user, *, preset: str | None = None, filters: Filters | None = None, sort: str = "number",
          descending: bool = True, page: int = 1) -> Page:
    """Страница списка: одна выборка с 51-й строкой, без общего числа."""
    chosen, queryset = _base(user, preset, filters)
    fields = _SORT_FIELDS.get(sort, _SORT_FIELDS["number"])
    prefix = "-" if descending else ""
    queryset = queryset.select_related("status", "priority", "category", "assignee", "client_unit", "queue",
                                     "closed_by")
    queryset = queryset.order_by(*[prefix + field for field in fields])
    page = page if isinstance(page, int) and page >= 1 else 1
    start = (page - 1) * PAGE_SIZE
    rows = list(queryset[start:start + PAGE_SIZE + 1])
    hint = search.parse(filters.q).hint if filters is not None and filters.q else ""
    return Page(rows=rows[:PAGE_SIZE], has_next=len(rows) > PAGE_SIZE, page=page, preset=chosen, hint=hint)


def count(user, *, preset: str | None = None, filters: Filters | None = None) -> int:
    """Общее число заявок по тем же условиям (кнопка «показать количество»)."""
    return _base(user, preset, filters)[1].count()


def badge(user) -> int:
    """Счётчик пункта «Заявки»: открытые без ответственного в моих очередях и мои открытые от заявителя (два COUNT)."""
    unassigned = Ticket.objects.filter(queue_id__in=my_queue_ids(user), assignee__isnull=True,
                                       kind__in=OPEN_KINDS).count()
    mine = Ticket.objects.filter(assignee=user, kind__in=OPEN_KINDS,
                                 last_message_from=Ticket.MessageFrom.REQUESTER).count()
    return unassigned + mine


def menu_items() -> list[dict]:
    """Пункты меню для точки `menu_items`: «Заявки» (виден по `access.menu_visible`, со счётчиком) и «Сервис-деск»."""
    return [
        {"permissions": ("servicedesk.all",), "url": "/tickets/", "title": "Заявки", "icon": "icons/tickets.html",
         "order": 5, "visible": access.menu_visible, "badge": badge},
        {"permissions": ("servicedesk.manage",), "url": "/servicedesk/", "title": "Сервис-деск",
         "icon": "icons/servicedesk.html", "order": 65},
    ]


def card_link(viewer, employee_id: int) -> str | None:
    """Ссылка «Заявки» из карточки сотрудника, если пункт меню виден `viewer`, иначе `None`."""
    if not access.menu_visible(viewer):
        return None
    return f"/tickets/?preset=all&assignee={employee_id}"
