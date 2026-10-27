"""Сервис: связи записей — «Закреплённое», подразделение и роль, «Ссылаются на эту запись» (срез 006).

Правила — PLAN-006, «Связи» (FR-525…FR-527), CONTRACT-006, 3.2, 3.3 и 5.5. Службы без актора: права смотрящего
учитывают только `pinned` и `referrers` (фильтр чтения); `unit_usage` и `role_usage` — точки расширения ядра
(`unit_usage`, `role_usage`), считают всё без фильтра, в том числе записи в архиве и скрытые поля (FR-509).
Значения в JSON ищутся по `Field.code` из схемы, код в запрос попадает ключом словаря, а не текстом SQL (NFR-509).
"""
from functools import reduce
from operator import or_
from typing import NamedTuple

from django.db.models import Q

from apps.lists.models import Access, Field, List, Record, UserView
from apps.lists.services import access
from apps.lists.texts import TEXTS


class Referrers(NamedTuple):
    """Ссылающиеся записи: `rows` — записи читаемых смотрящим списков, `hidden` — число остальных."""

    rows: list
    hidden: int


class PinnedRow(NamedTuple):
    """Строка «Закреплённого»: запись, её список, поле «сотрудник» и признак «ссылка на запись разрешена»."""

    record: Record
    list: List
    field: Field
    link: bool


def _any_of(conditions: list):
    return reduce(or_, conditions)


# --- ссылки между записями (FR-527) ---------------------------------------------------------------------------

def referrers(record, viewer) -> Referrers:
    """Записи, чьи поля «запись другого списка» (в том числе скрытые, в том числе этого же списка) содержат `record`.

    `viewer=None` — все записи без фильтра чтения (запрет удаления навсегда, FR-524). Иначе `rows` — записи списков,
    которые `viewer` читает (`access.can_read`), `hidden` — число остальных. Порядок — по списку и номеру."""
    fields = list(Field.objects.filter(type=Field.Type.RECORD, target_id=record.list_id))
    if not fields:
        return Referrers([], 0)
    condition = _any_of([Q(list_id=field.list_id, values__contains={field.code: [record.pk]}) for field in fields])
    found = list(Record.objects.filter(condition).select_related("list").order_by("list_id", "number"))
    if viewer is None:
        return Referrers(found, 0)
    readable: dict[int, bool] = {}
    rows = []
    for item in found:
        if item.list_id not in readable:
            readable[item.list_id] = access.can_read(viewer, item.list)
        if readable[item.list_id]:
            rows.append(item)
    return Referrers(rows, len(found) - len(rows))


# --- «Закреплённое» (FR-525) ------------------------------------------------------------------------------------

def pinned(viewer, person) -> list[PinnedRow]:
    """Строки раздела «Закреплённое» сотрудника `person` для смотрящего `viewer`.

    Порядок аргументов — как у `card_sections(viewer, person)` и в тестах T-6113 (в таблице 5.5 контракта записано
    `pinned(person, viewer)` — расхождение, см. отчёт T-6211).

    Записи не в архиве, где видимое поле «сотрудник» любого списка содержит `person`; по строке на пару «запись, поле».
    Смотрит сам сотрудник — все строки, ссылка (`link`) только у списков, которые он читает; смотрит другой — только
    строки читаемых им списков, со ссылкой. Состояние `person` не проверяется (уволенному раздел показывается так же)."""
    fields = list(Field.objects.filter(type=Field.Type.PERSON, hidden=False).order_by("list_id", "order", "pk"))
    if not fields:
        return []
    by_list: dict[int, list[Field]] = {}
    for field in fields:
        by_list.setdefault(field.list_id, []).append(field)
    condition = _any_of([Q(list_id=field.list_id, values__contains={field.code: [person.pk]}) for field in fields])
    records = list(Record.objects.filter(condition, archived=False).select_related("list"))
    own = viewer is not None and viewer.pk == person.pk
    readable: dict[int, bool] = {}
    rows = []
    for record in sorted(records, key=lambda item: (item.list.name.casefold(), item.list_id, item.number)):
        if record.list_id not in readable:
            readable[record.list_id] = viewer is not None and access.can_read(viewer, record.list)
        can_open = readable[record.list_id]
        if not own and not can_open:
            continue
        for field in by_list[record.list_id]:
            if person.pk in (record.values or {}).get(field.code, ()):
                rows.append(PinnedRow(record, record.list, field, can_open))
    return rows


# --- подразделение и роль (FR-526) ------------------------------------------------------------------------------

def _list_names(query) -> str:
    """Названия списков по алфавиту через «, » без повторов."""
    return ", ".join(sorted(set(query.values_list("list__name", flat=True)), key=lambda name: (name.casefold(), name)))


def unit_usage(unit_id: int) -> str | None:
    """Точка `unit_usage`: причина, по которой узел нельзя удалить, или `None`.

    «подразделение указано в N записях списков» — записи (в том числе в архиве, в том числе скрытые поля; запись с
    узлом в двух полях — одна); если узел есть и в наборах прав — через «; » «указано в правах списков: <названия>»."""
    reasons = []
    fields = list(Field.objects.filter(type=Field.Type.UNIT))
    if fields:
        condition = _any_of([Q(list_id=field.list_id, values__contains={field.code: [unit_id]}) for field in fields])
        count = Record.objects.filter(condition).count()
        if count:
            reasons.append(TEXTS["unit_in_records"].format(count=count))
    names = _list_names(Access.objects.filter(unit_id=unit_id))
    if names:
        reasons.append(TEXTS["unit_in_access"].format(names=names))
    return "; ".join(reasons) or None


def role_usage(role) -> str | None:
    """Точка `role_usage`: готовая фраза «Нельзя удалить: указано в правах списков: <названия>.» или `None`."""
    names = _list_names(Access.objects.filter(role_id=getattr(role, "pk", role)))
    return TEXTS["role_in_access"].format(names=names) if names else None


# --- подписчик события ядра -------------------------------------------------------------------------------------

def on_user_dismissed(**data) -> None:
    """Подписчик `core.user_dismissed` (подключает `ListsConfig.ready()`): удаляет выбор столбцов уволенного.

    Записи, где он указан, не меняются (FR-525)."""
    UserView.objects.filter(user_id=data["user_id"]).delete()
