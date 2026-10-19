"""Поставщик «Заявки» сквозного поиска (PLAN-005, «Сквозной поиск» → поставщики; CONTRACT-005, 4.4).

Поверх `services/search.py` и `access.visible_tickets`. Заявка по номеру — отдельный запрос по уникальному индексу,
закреплённой строкой первой страницы сверх основных; смещение считается по основному запросу без неё. Запрос поиска уходит
параметром (`SearchQuery`, тип `raw`). Модели `org` не импортируются: очередь читается по связи `queue`.
"""
from django.contrib.postgres.search import SearchQuery

from apps.core.extensions import ParsedQuery, SearchProvider, SearchRow

from . import access
from . import search as ticket_search

COUNT_CAP = 1000
ORDER = 10


def _main(user, parsed: ParsedQuery):
    """Основная выборка: видимые заявки по тексту без заявки с номером запроса, номер вниз."""
    if not parsed.raw:
        return access.visible_tickets(user).none()
    query = SearchQuery(parsed.raw, config=ticket_search.CONFIG, search_type="raw")
    queryset = access.visible_tickets(user).filter(search=query)
    if parsed.number is not None:
        queryset = queryset.exclude(number=parsed.number)
    return queryset


def _row(ticket, *, pinned: bool = False) -> SearchRow:
    state, queue = ticket.status.name, ticket.queue.name
    return SearchRow(title=f"#{ticket.number} {ticket.subject}", subtitle=f"{state}, {queue}",
                     url=f"/tickets/{ticket.number}/", template="search/rows/_ticket.html",
                     context={"state": state, "queue": queue}, pinned=pinned)


def available(user) -> bool:
    """Группа показывается тому, кому доступен пункт меню «Заявки»."""
    return access.menu_visible(user)


def search(user, parsed: ParsedQuery, limit: int, offset: int) -> list[SearchRow]:
    """`limit + 1` основных строк со смещением `offset` (лишнюю отрезает сборка); при `offset == 0` над ними — заявка
    по номеру с `pinned=True` (CONTRACT-005, раздел 17, п. 73)."""
    if parsed.hint:
        return []
    rows = []
    if offset == 0 and parsed.number is not None:
        pinned = access.visible_tickets(user).filter(number=parsed.number).select_related("status", "queue")[:1]
        rows.extend(_row(ticket, pinned=True) for ticket in pinned)
    main = _main(user, parsed).select_related("status", "queue").order_by("-number")[offset:offset + limit + 1]
    rows.extend(_row(ticket) for ticket in main)
    return rows


def count(user, parsed: ParsedQuery) -> tuple[int, bool]:
    """Число видимых заявок группы с потолком: читается `COUNT_CAP + 1` строк, больше потолка — `(1000, True)`."""
    if parsed.hint:
        return 0, False
    numbers = list(_main(user, parsed).order_by("-number").values_list("number", flat=True)[:COUNT_CAP + 1])
    total = len(numbers)
    if parsed.number is not None and access.visible_tickets(user).filter(number=parsed.number).exists():
        total += 1
    if total > COUNT_CAP:
        return COUNT_CAP, True
    return total, False


def search_providers() -> list[SearchProvider]:
    """Запись точки `search_providers`: группа «Заявки»."""
    return [SearchProvider(key="tickets", title="Заявки", order=ORDER, search=search, count=count, available=available)]
