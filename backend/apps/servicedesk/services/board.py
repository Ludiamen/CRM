"""Доска заявок: колонки-статусы, сортировка, порция и перенос (PLAN-013, T-13010/T-13012).

Доска — режим списка заявок, а не отдельная сущность. Колонки — неархивные статусы видов «новая»,
«в работе», «ждёт ответа заявителя» по порядку справочника и последняя колонка «Закрытые».
"""
from dataclasses import dataclass, replace

from django.db.models import Q

from ..models import Status, Ticket
from . import access, dictionaries, listing

OPEN_KINDS = (Status.Kind.NEW, Status.Kind.IN_PROGRESS, Status.Kind.WAITING)
CLOSED_KEY = "closed"
PAGE_SIZE = 50


class BoardError(Exception):
    """Ошибка доски: код и русский текст."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _status_columns(status_ids=None) -> tuple[list, bool]:
    """Открытые статусы по порядку и признак показывать «Закрытые»."""
    queryset = Status.objects.filter(archived=False).order_by("order", "name")
    if status_ids:
        queryset = queryset.filter(pk__in=status_ids)
        show_closed = Status.objects.filter(archived=False, kind=Status.Kind.CLOSED, pk__in=status_ids).exists()
    else:
        show_closed = True
    return list(queryset.filter(kind__in=OPEN_KINDS)), show_closed


def _base(viewer, filters: listing.Filters | None, queue: int | None, preset: str | None = None):
    queryset = access.visible_tickets(viewer)
    if preset in listing.PRESETS:
        queryset = listing._apply_preset(queryset, viewer, preset)
    if filters is not None:
        queryset = listing._apply_filters(queryset, filters)
    if queue is not None:
        queryset = queryset.filter(queue_id=queue)
    return queryset


def _rows(viewer, queryset, offset: int, limit: int):
    rows = list(queryset.order_by("sla_solution_due", "priority_order", "-last_message_at", "number")
                .select_related("assignee", "priority", "queue", "status")[offset:offset + limit])
    for ticket in rows:
        ticket.can_work = access.can_work(viewer, ticket)
    return rows


def _closed_rows(viewer, queryset, offset: int, limit: int):
    rows = list(queryset.order_by("-closed_at", "-number")
                .select_related("assignee", "priority", "queue", "status")[offset:offset + limit])
    for ticket in rows:
        ticket.can_work = access.can_work(viewer, ticket)
    return rows


def _column(viewer, key: str, title: str, queryset, offset: int, limit: int, *, closed: bool = False) -> dict:
    rows = _closed_rows(viewer, queryset, offset, limit) if closed else _rows(viewer, queryset, offset, limit)
    total = queryset.count()
    return {"key": key, "title": title, "tickets": rows, "count": total,
            "has_more": offset + len(rows) < total, "offset": offset + len(rows)}


def columns(viewer, filters: listing.Filters | None = None, *, queue: int | None = None,
            status_ids=None, limit: int = PAGE_SIZE, preset: str | None = None) -> list[dict]:
    """Колонки доски с первой порцией и общим числом заявок."""
    if filters is not None and filters.status is not None and not status_ids:
        status_ids = [filters.status]
        filters = replace(filters, status=None)
    base = _base(viewer, filters, queue, preset)
    statuses, show_closed = _status_columns(status_ids)
    result = [_column(viewer, str(status.pk), status.name, base.filter(status=status), 0, limit)
              for status in statuses]
    if show_closed:
        result.append(_column(viewer, CLOSED_KEY, "Закрытые", base.filter(kind=Status.Kind.CLOSED), 0, limit, closed=True))
    return result


def column(viewer, key: str, filters: listing.Filters | None = None, *, queue: int | None = None,
           offset: int = 0, limit: int = PAGE_SIZE, preset: str | None = None) -> dict:
    """Следующая порция одной колонки; неизвестный ключ — `bad_column`."""
    base = _base(viewer, filters, queue, preset)
    if key == CLOSED_KEY:
        return _column(viewer, CLOSED_KEY, "Закрытые", base.filter(kind=Status.Kind.CLOSED), offset, limit, closed=True)
    try:
        status_id = int(key)
    except (TypeError, ValueError):
        raise BoardError("bad_column", "Колонка не найдена") from None
    status = Status.objects.filter(pk=status_id, archived=False, kind__in=OPEN_KINDS).first()
    if status is None:
        raise BoardError("bad_column", "Колонка не найдена")
    return _column(viewer, key, status.name, base.filter(status=status), offset, limit)


def move(actor, ticket, status, *, expected: str | None = None) -> bool:
    """Перенести карточку в открытый статус; закрытие — отдельной формой."""
    if not access.can_work(actor, ticket):
        raise BoardError("no_access", "нет доступа")
    if status.kind == Status.Kind.CLOSED:
        raise BoardError("close_required", "Закройте заявку через форму решения")
    if status.archived or not dictionaries.manual_statuses().filter(pk=status.pk).exists():
        raise BoardError("bad_status", "Этот статус нельзя выбрать здесь")
    if expected is not None and expected != ticket.updated_at.isoformat():
        raise BoardError("board_conflict", "Заявку изменили: обновите доску")
    from . import tickets

    tickets.set_status_manual(ticket, status, actor=actor)
    return True


def can_close(actor, ticket) -> bool:
    """Закрытие доступно тому, кто может работать с заявкой."""
    return access.can_work(actor, ticket)
