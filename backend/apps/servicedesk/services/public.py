"""Публичная служба сервис-деска для других модулей (PLAN-005, «Связь с заявками и карточка заявки»; CONTRACT-005, 4.2).

Единственное, что `knowledge` вызывает у сервис-деска. Только заявки, видимые смотрящему (`access.visible_tickets`);
данных заявителя, адресов, переписки и вложений в `TicketBrief` нет.
"""
from typing import NamedTuple

from ..models import Status
from . import access


class TicketBrief(NamedTuple):
    """Краткая справка о заявке: номер, тема, название состояния и решение."""

    number: int
    subject: str
    state: str
    closed_with_resolution: bool
    resolution: str


def _brief(row) -> TicketBrief:
    resolution = row.resolution or ""
    return TicketBrief(number=row.number, subject=row.subject, state=row.status.name,
                       closed_with_resolution=row.kind == Status.Kind.CLOSED and bool(resolution.strip()),
                       resolution=resolution)


def briefs(user, numbers) -> dict[int, TicketBrief]:
    """Справки о видимых `user` заявках из `numbers` одним запросом; невидимые и несуществующие номера пропускаются."""
    wanted = list(numbers)
    if not wanted:
        return {}
    rows = access.visible_tickets(user).filter(number__in=wanted).select_related("status")
    return {row.number: _brief(row) for row in rows}


def ticket_brief(user, number: int) -> TicketBrief | None:
    """Справка о заявке `number`, если её видит `user`, иначе `None`."""
    return briefs(user, [number]).get(number)
