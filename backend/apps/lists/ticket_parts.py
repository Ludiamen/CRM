"""Части карточки заявки: связанные записи списков (срез 006; PLAN-006, «Связь с заявками»; CONTRACT-006, 3.2, 5.7)."""
from apps.core.extensions import TicketCardPart
from apps.lists.services import tickets

ORDER = 20  # после частей `knowledge` (порядок 10)


def render(request, ref) -> str | None:
    """Фрагмент раздела «Записи списков» или `None` (оболочку рисует сервис-деск)."""
    return tickets.render(request, ref)


def ticket_card_parts() -> list[TicketCardPart]:
    """Запись точки `ticket_card_parts`: раздел `lists-records`."""
    return [TicketCardPart(key="lists-records", kind="section", order=ORDER, render=render)]
