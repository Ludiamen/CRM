"""Сервис: события истории записи (срез 006; FR-522).

Служба только добавляет строки `Change`: изменять и удалять строки нечем, они уходят лишь каскадом при удалении записи
навсегда (PLAN-006, «История записи»). Служба без актора-права: право проверяет вызывающая служба (CONTRACT-006, 5.4).
"""
from typing import NamedTuple

from apps.lists.models import Change, Field
from apps.lists.services import access
from apps.lists.services import values as values_service

PAGE_SIZE = 50
TITLE_NAME = "Название"
UNAVAILABLE = "запись недоступного списка"


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


def for_viewer(rows, lst, viewer) -> list:
    """Строки страницы истории для смотрящего: значения полей-ссылок на записи списка, которого он не читает, —
    «запись недоступного списка» с пометкой `unavailable` (FR-514, FR-527).

    Строки показа сохранены на момент изменения глазами автора. У поля «запись» один целевой список, и сменить его у
    поля с историей нельзя (`schema.has_data`), поэтому решение принимается по полю. Строки `Change` не меняются:
    подменяется только `changes` загруженных объектов для вывода."""
    closed = {field.code for field in Field.objects.filter(list=lst, type="record").select_related("target")
              if not access.can_read(viewer, field.target)}
    if not closed:
        return rows
    for row in rows:
        if any(item.get("field") in closed for item in row.changes or []):
            row.changes = [
                {**item, "before": UNAVAILABLE if item.get("before") else "",
                 "after": UNAVAILABLE if item.get("after") else "", "unavailable": True}
                if item.get("field") in closed else item
                for item in row.changes]
    return rows
