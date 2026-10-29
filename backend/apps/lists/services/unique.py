"""Сервис: таблица уникальных значений (срез 006).

Уникальность держит ограничение базы (`list`, `field`, `norm_value`), а не проверка в коде (план, «Уникальность»).
Службы без актора: прав не проверяют (CONTRACT-006, шапка раздела 5).
"""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from apps.lists.models import UniqueValue
from apps.lists.services.errors import ListsError


def normalize(field, value) -> str | None:
    """Нормализованное значение уникального поля; `value` — значение в форме хранения (CONTRACT-006, 2.3, О3).

    Строка — `strip()` и `lower()`; число — каноническая десятичная строка («100.0» и «100» совпадают). Пусто и
    типы, у которых уникальности нет, — `None` (строка `UniqueValue` не создаётся)."""
    if value is None or isinstance(value, (list, dict, bool)):
        return None
    if field.type == "string":
        text = str(value).strip().lower()
        return text or None
    if field.type == "number":
        text = str(value).strip()
        if not text:
            return None
        try:
            number = Decimal(text)
        except InvalidOperation:
            return text
        if not number.is_finite():
            return text
        canonical = format(number.normalize(), "f")
        return "0" if canonical in ("-0", "0") else canonical
    return None


def find_owners(lst, field, norm_values) -> dict:
    """Предварительная проверка до вставки: нормализованное значение → запись-владелец (в том числе в архиве).

    Значений нет — пустой словарь; чужие списки и поля не смотрятся. Точка подмены теста гонки; ею же пользуется
    предпросмотр загрузки (решения 28 и 45)."""
    values = [value for value in norm_values if value]
    if not values:
        return {}
    rows = UniqueValue.objects.filter(list=lst, field=field, norm_value__in=values).select_related("record")
    return {row.norm_value: row.record for row in rows}


def _taken(record, field, norm_value) -> ListsError:
    """Отказ «Такое значение уже есть в списке» со ссылкой на запись-владельца (её номер — из той же таблицы)."""
    owner = (UniqueValue.objects.filter(list_id=record.list_id, field=field, norm_value=norm_value)
             .select_related("record").first())
    number = owner.record.number if owner else ""
    return ListsError(
        "unique_taken", field=field.code,
        params={"number": number, "url": f"/lists/{record.list_id}/{number}/" if owner else f"/lists/{record.list_id}/"})


def rows_for(record, fields) -> list:
    """Строки `UniqueValue` записи по уникальным полям `fields` — без записи в базу (пакетная вставка загрузки)."""
    found = []
    for field in fields:
        if not field.unique:
            continue
        norm_value = normalize(field, (record.values or {}).get(field.code))
        if norm_value is not None:
            found.append(UniqueValue(list_id=record.list_id, field=field, norm_value=norm_value, record=record))
    return found


def sync(record, fields) -> None:
    """Перезаписывает строки `UniqueValue` записи по уникальным полям из `fields` (видимым и скрытым — FR-508).

    Для каждого поля строка удаляется и вставляется заново, пустое значение строки не даёт. Удаление и вставка идут
    во вложенной точке сохранения: `IntegrityError` по ограничению превращается в `ListsError("unique_taken")` у поля,
    а внешняя транзакция остаётся рабочей, прежняя строка записи — на месте."""
    for field in fields:
        if not field.unique:
            continue
        norm_value = normalize(field, (record.values or {}).get(field.code))
        try:
            with transaction.atomic():
                UniqueValue.objects.filter(record=record, field=field).delete()
                if norm_value is not None:
                    UniqueValue.objects.create(list_id=record.list_id, field=field, norm_value=norm_value, record=record)
        except IntegrityError:
            raise _taken(record, field, norm_value) from None
