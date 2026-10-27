"""Сервис: события истории записи (срез 006; FR-522).

Служба только добавляет строки `Change`: изменять и удалять строки нечем, они уходят лишь каскадом при удалении записи
навсегда (PLAN-006, «История записи»). Служба без актора-права: право проверяет вызывающая служба (CONTRACT-006, 5.4).
"""
from typing import NamedTuple

from apps.lists.models import Change
from apps.lists.services import values as values_service

PAGE_SIZE = 50
TITLE_NAME = "Название"


class HistoryPage(NamedTuple):
    """Страница истории: `rows` — не больше 50 строк `Change`, `next_offset` — смещение следующей страницы или `None`."""

    rows: list
    next_offset: int | None


def write(record, kind: str, changes, actor, *, via_import: bool = False) -> Change:
    """Добавляет строку истории записи: единственный `INSERT`; время — `timezone.now()` по умолчанию модели.

    `changes` — список `{"field", "name", "before", "after"}` строками показа на момент изменения (у событий без
    изменений полей — пустой список)."""
    return Change.objects.create(
        record=record, kind=kind, actor=actor, changes=list(changes or []), via_import=via_import)


def build_changes(fields, old_values: dict, new_values: dict, viewer, *, old_title=None, new_title=None) -> list[dict]:
    """Изменённые поля по `fields` («было / стало» строками показа) в порядке полей; «Название» — первым.

    `old_values`, `new_values` — значения в форме хранения; поле без ключа — пусто. Значения скрытых полей сюда не
    попадают: вызывающий передаёт только поля, которые правились."""
    entries = []
    if old_title is not None and new_title is not None and old_title != new_title:
        entries.append({"field": "title", "name": TITLE_NAME, "before": old_title, "after": new_title})
    for field in fields:
        before, after = old_values.get(field.code), new_values.get(field.code)
        if before == after or (not before and not after):
            continue
        entries.append({
            "field": field.code, "name": field.name,
            "before": values_service.display(field, before, viewer),
            "after": values_service.display(field, after, viewer)})
    return entries


def page(record, offset: int = 0) -> HistoryPage:
    """Страница истории: 50 строк, новые сверху (`at`, `id` по убыванию); неверное смещение — как 0."""
    offset = offset if isinstance(offset, int) and offset > 0 else 0
    rows = list(Change.objects.filter(record=record).select_related("actor").order_by("-at", "-id")[
        offset:offset + PAGE_SIZE + 1])
    more = len(rows) > PAGE_SIZE
    return HistoryPage(rows[:PAGE_SIZE], offset + PAGE_SIZE if more else None)
