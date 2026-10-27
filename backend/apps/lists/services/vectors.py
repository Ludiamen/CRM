"""Сервис: вектор поиска записи (срез 006).

Единственное место расчёта вектора (PLAN-006, «Поиск» → «Вектор записи»; CONTRACT-006, 5.6): название записи —
вес A, значения видимых полей «строка» и «многострочный текст» — вес C, не больше 100 000 знаков. Скрытые поля,
числа и прочие типы в вектор не входят. Служба без актора, прав не проверяет; вызывается из транзакции записи
(создание, сохранение, архив, возврат, загрузка) и заданием `refresh_vectors` (скрыть и показать поле)."""
from django.db import connection

from apps.lists.models import List, Record
from apps.lists.services import schema

BODY_LIMIT = 100000
TEXT_TYPES = ("string", "text")

# Литерал с параметрами: три массива — `%s`, имена таблиц и столбцов — буквально.
_SQL = (
    "UPDATE lists_record AS r SET search = setweight(to_tsvector('russian', v.title), 'A') || "
    "setweight(to_tsvector('russian', v.body), 'C') "
    "FROM unnest(%s::bigint[], %s::text[], %s::text[]) AS v(id, title, body) WHERE r.id = v.id"
)


def _clean(text) -> str:
    """Строка без символа NUL: его не принимает `text` в PostgreSQL."""
    return str(text).replace("\x00", "")


def _body(record: Record, codes: list[str]) -> str:
    parts = []
    for code in codes:
        value = (record.values or {}).get(code)
        if value is None or value == "":
            continue
        parts.append(_clean(value))
    return " ".join(parts)[:BODY_LIMIT]


def refresh(record_ids) -> None:
    """Пересчитывает вектор записей по номерам: название и значения видимых текстовых полей их списков."""
    ids = list(dict.fromkeys(record_ids))
    if not ids:
        return
    records = list(Record.objects.filter(pk__in=ids).only("id", "list_id", "title", "values").order_by("id"))
    if not records:
        return
    codes_of: dict[int, list[str]] = {}
    for lst in List.objects.filter(pk__in={record.list_id for record in records}):
        codes_of[lst.pk] = [field.code for field in schema.visible_fields(lst) if field.type in TEXT_TYPES]
    titles = [_clean(record.title) for record in records]
    bodies = [_body(record, codes_of.get(record.list_id, [])) for record in records]
    with connection.cursor() as cursor:
        cursor.execute(_SQL, [[record.pk for record in records], titles, bodies])
