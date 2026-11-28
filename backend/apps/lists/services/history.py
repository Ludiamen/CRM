"""Сервис: события истории записи (срез 006; FR-522).

Служба только добавляет строки `Change`: изменять и удалять строки нечем, они уходят лишь каскадом при удалении записи
навсегда (PLAN-006, «История записи»). Служба без актора-права: право проверяет вызывающая служба (CONTRACT-006, 5.4).
"""
from typing import NamedTuple

from apps.lists.models import Change, Field, Record
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


def make(record, kind: str, changes, actor, *, via_import: bool = False) -> Change:
    """Строка истории без записи в базу — для пакетной вставки (`Change.objects.bulk_create`, загрузка таблицы)."""
    return Change(record=record, kind=kind, actor=actor, changes=list(changes or []), via_import=via_import)


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
        entry = {
            "field": field.code, "name": field.name,
            "before": values_service.display(field, before, viewer),
            "after": values_service.display(field, after, viewer)}
        if field.type == "record":
            entry["ids"] = sorted({pk for pk in (before or []) + (after or []) if isinstance(pk, int)})
        entries.append(entry)
    return entries


def page(record, offset: int = 0) -> HistoryPage:
    """Страница истории: 50 строк, новые сверху (`at`, `id` по убыванию); неверное смещение — как 0."""
    offset = offset if isinstance(offset, int) and offset > 0 else 0
    rows = list(Change.objects.filter(record=record).select_related("actor").order_by("-at", "-id")[
        offset:offset + PAGE_SIZE + 1])
    more = len(rows) > PAGE_SIZE
    return HistoryPage(rows[:PAGE_SIZE], offset + PAGE_SIZE if more else None)


def for_viewer(rows, lst, viewer) -> list:
    """Строки истории для смотрящего: ссылки на записи нечитаемого списка **или стадии** заменяются
    «запись недоступного списка» с пометкой `unavailable` (FR-514, FR-527, FR-861).

    Для старых строк без `ids` безопасная политика — маскировать все значения поля-ссылки: какая именно
    запись была названа, неизвестно. Цели загружаются одним запросом; отсутствующая запись тоже считается
    недоступной."""
    record_codes = {field.code for field in Field.objects.filter(list=lst, type="record")}
    closed = {field.code for field in Field.objects.filter(list=lst, type="record").select_related("target")
              if not access.can_read(viewer, field.target)}
    ids = {pk for row in rows for item in row.changes or [] for pk in item.get("ids") or ()}
    found = {record.pk: record for record in Record.objects.filter(pk__in=ids).select_related("list")}
    hidden_ids = {pk for pk, record in found.items() if not access.can_read_record(viewer, record)}
    ids_without_record = ids - set(found)
    legacy = any(item.get("field") in record_codes and "ids" not in item
                 for row in rows for item in row.changes or [])
    if not closed and not hidden_ids and not ids_without_record and not legacy:
        return rows
    def hide(item):
        code = item.get("field")
        if code in closed:
            return True
        if code in record_codes and "ids" not in item:
            return True
        return bool((set(item.get("ids") or ()) & (hidden_ids | ids_without_record)))
    for row in rows:
        if not any(hide(item) for item in row.changes or []):
            continue
        row.changes = [
            {**item, "before": UNAVAILABLE if item.get("before") else "",
             "after": UNAVAILABLE if item.get("after") else "", "unavailable": True}
            if hide(item) else item
            for item in row.changes]
    return rows
    for row in rows:
        if not any(item.get("field") in closed or hidden_ids.intersection(item.get("ids") or ())
                   for item in row.changes or []):
            continue
        row.changes = [
            {**item, "before": UNAVAILABLE if item.get("before") else "",
             "after": UNAVAILABLE if item.get("after") else "", "unavailable": True}
            if item.get("field") in closed or hidden_ids.intersection(item.get("ids") or ()) else item
            for item in row.changes]
    return rows
