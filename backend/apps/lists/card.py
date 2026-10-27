"""Раздел «Закреплённое» карточки сотрудника (срез 006; PLAN-006, «Связи», FR-525; CONTRACT-006, 3.2)."""
from apps.core import extensions
from apps.lists.services import links


def card_sections(viewer, person) -> list[extensions.CardSection]:
    """Точка ядра `card_sections`: раздел `lists-pinned` на вкладке профиля, порядок 70 (после «Заявок»).

    Строки считает `links.pinned(viewer, person)`: права смотрящего и состояние `person` учтены там; нет строк —
    раздела нет (пустой список)."""
    rows = links.pinned(viewer, person)
    if not rows:
        return []
    return [extensions.CardSection("lists-pinned", "profile", 70, "lists/_card_pinned.html", {"rows": rows})]
