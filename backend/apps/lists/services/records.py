"""Сервис: создание и сохранение записей (срез 006; FR-504, FR-508, FR-515…FR-517, FR-522).

`create` и `save` идут в одной транзакции под разделяемым замком списка (`access.lock_list`, CONTRACT-006, 5.2): порядок
замков — замок списка, строка списка (`next_number`, только `create`), строка записи (только `save`); схема читается
после замка. Отказы полей — `ValuesInvalid` (в том числе `unique_taken`, ответ Opus О2), отказы записи — `RecordGone`,
`RecordArchived`, `VersionConflict`. Право «правит» служба перепроверяет сама: нет права — `PermissionDenied`, список не
читается — `Http404` (CONTRACT-006, шапка раздела 5). Значения полей в журнал приложения не пишутся.
"""
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.lists.models import List, Record
from apps.lists.services import access, history, schema, unique, values, vectors
from apps.lists.services.errors import (ListsError, RecordArchived, RecordGone, ValuesInvalid, VersionConflict)

TITLE_LIMIT = 200


class SaveResult(NamedTuple):
    """Итог `save`: запись и признак «значения изменились» (без изменений — ни версии, ни события)."""

    record: Record
    changed: bool


# --- права ---------------------------------------------------------------------------------------------------

def _require_edit(actor, lst) -> None:
    """Список не читается — `Http404`, читается, но не правится — `PermissionDenied` (CONTRACT-006, шапка раздела 5)."""
    current = access.get_list(actor, lst.pk)
    if not access.can_edit(actor, current):
        raise PermissionDenied("Нет права править записи списка")


# --- проверка присланного --------------------------------------------------------------------------------------

def _filled(raw) -> bool:
    """Прислано непустое значение (строка или список строк)."""
    if raw is None:
        return False
    if isinstance(raw, (list, tuple)):
        return any(str(item).strip() for item in raw)
    return bool(str(raw).strip())


def _parse_title(data: dict):
    """Название записи: возвращает (название, отказ)."""
    title = str(data.get("title") or "").strip()
    if not title:
        return title, ListsError("required", field="title")
    if len(title) > TITLE_LIMIT:
        return title, ListsError("too_long", field="title", params={"limit": str(TITLE_LIMIT)})
    return title, None


def _parse_values(data: dict, fields, hidden_fields, old_values: dict, actor, *, source: str, lookups=None):
    """Разбор значений видимых полей: возвращает (новые значения видимых полей, отказы по кодам).

    Скрытое поле с присланным непустым значением — отказ `field_hidden_meanwhile` (FR-517); пустое и отсутствующее
    скрытое поле пропускается, скрытое на обязательность не проверяется (FR-509)."""
    errors: dict[str, ListsError] = {}
    parsed: dict = {}
    for field in fields:
        if field.type == "file":
            continue
        result = values.parse(field, data.get(field.code), old=old_values.get(field.code), viewer=actor, source=source,
                              lookups=lookups)
        if result.error is not None:
            errors[field.code] = result.error
        elif result.value is None and field.required:
            errors[field.code] = ListsError("required", field=field.code)
        else:
            parsed[field.code] = result.value
    for field in hidden_fields:
        if _filled(data.get(field.code)):
            errors[field.code] = ListsError("field_hidden_meanwhile", field=field.code)
    return parsed, errors


def _precheck_unique(record, lst, fields, new_values: dict, errors: dict) -> None:
    """Предварительная проверка уникальности (тот же запрос, что у предпросмотра загрузки): понятный отказ со ссылкой на
    запись-владельца; гонку держит ограничение базы в `unique.sync` (FR-508)."""
    for field in fields:
        if not field.unique or field.code in errors:
            continue
        norm_value = unique.normalize(field, new_values.get(field.code))
        if norm_value is None:
            continue
        owner = unique.find_owners(lst, field, [norm_value]).get(norm_value)
        if owner is not None and (record is None or owner.pk != record.pk):
            errors[field.code] = ListsError(
                "unique_taken", field=field.code,
                params={"number": owner.number, "url": f"/lists/{lst.pk}/{owner.number}/"})


def _sync_unique(record, all_fields) -> None:
    """`unique.sync` по всем полям; отказ ограничения — `ValuesInvalid` у поля (ответ Opus О2)."""
    try:
        unique.sync(record, all_fields)
    except ListsError as error:
        if isinstance(error, ValuesInvalid):
            raise
        raise ValuesInvalid({error.field: error}) from None


def _ordered(errors: dict[str, ListsError], title_error) -> dict[str, ListsError]:
    ordered = {"title": title_error} if title_error is not None else {}
    ordered.update(errors)
    return ordered


# --- создание ---------------------------------------------------------------------------------------------------

def create(lst, data: dict, actor, *, via_import: bool = False, lookups=None) -> Record:
    """Создаёт запись списка: замок списка (разделяемый) → `FOR UPDATE` строки списка → проверки → `Record` →
    `unique.sync` → `vectors.refresh` → событие `created`.

    `data` — «код → строка или список строк» и `"title"`. При `via_import=True` вектор не считается: его пересчитывает
    `imports.confirm` пакетно в конце (CONTRACT-006, 5.4, К-4). `lookups` — справочники загрузки
    (`values.import_lookups`, один раз на файл): без них справочники берутся запросами, как прежде."""
    _require_edit(actor, lst)
    source = "import" if via_import else "form"
    with transaction.atomic():
        access.lock_list(lst.pk, shared=True)
        locked = List.objects.select_for_update().filter(pk=lst.pk).first()
        if locked is None:
            raise Http404
        every = schema.all_fields(locked)
        visible = [field for field in every if not field.hidden]
        hidden = [field for field in every if field.hidden]
        title, title_error = _parse_title(data)
        new_values, errors = _parse_values(data, visible, hidden, {}, actor, source=source, lookups=lookups)
        stored = {code: value for code, value in new_values.items() if value is not None}
        _precheck_unique(None, locked, visible, stored, errors)
        if title_error is not None or errors:
            raise ValuesInvalid(_ordered(errors, title_error))
        number = locked.next_number
        List.objects.filter(pk=locked.pk).update(next_number=number + 1)
        now = timezone.now()
        record = Record.objects.create(
            list=locked, number=number, title=title, values=stored, created_at=now, created_by=actor,
            updated_at=now, updated_by=actor)
        _sync_unique(record, every)
        if not via_import:
            vectors.refresh([record.pk])
        history.write(record, "created", [], actor, via_import=via_import)
    return record


# --- сохранение ---------------------------------------------------------------------------------------------------

def save(lst, number: int, data: dict, *, base_version: int, actor) -> SaveResult:
    """Сохраняет запись по номеру: замок списка (разделяемый) → `FOR UPDATE` записи → проверки → значения.

    Порядок отказов: запись удалена (`RecordGone`) или в архиве (`RecordArchived`), затем версия (`VersionConflict`),
    затем значения. Без изменений ничего не пишется (FR-522); значения скрытых полей служба не трогает."""
    _require_edit(actor, lst)
    with transaction.atomic():
        access.lock_list(lst.pk, shared=True)
        record = Record.objects.select_for_update().filter(list_id=lst.pk, number=number).first()
        if record is None:
            next_number = List.objects.filter(pk=lst.pk).values_list("next_number", flat=True).first()
            if next_number is None or number >= next_number:
                raise Http404("Запись не найдена")
            raise RecordGone()
        if record.archived:
            raise RecordArchived()
        if record.version != base_version:
            raise VersionConflict(record.updated_by, record.updated_at)
        every = schema.all_fields(lst)
        visible = [field for field in every if not field.hidden]
        hidden = [field for field in every if field.hidden]
        old_values = dict(record.values or {})
        title, title_error = _parse_title(data)
        parsed, errors = _parse_values(data, visible, hidden, old_values, actor, source="form")
        new_values = dict(old_values)
        for code, value in parsed.items():
            if value is None:
                new_values.pop(code, None)
            else:
                new_values[code] = value
        if not errors:
            _precheck_unique(record, lst, visible, new_values, errors)
        if title_error is not None or errors:
            raise ValuesInvalid(_ordered(errors, title_error))
        if title == record.title and new_values == old_values:
            return SaveResult(record, False)
        entries = history.build_changes(visible, old_values, new_values, actor, old_title=record.title, new_title=title)
        record.title = title
        record.values = new_values
        record.version += 1
        record.updated_by = actor
        record.updated_at = timezone.now()
        record.save(update_fields=["title", "values", "version", "updated_by", "updated_at"])
        _sync_unique(record, every)
        vectors.refresh([record.pk])
        history.write(record, "changed", entries, actor)
    return SaveResult(record, True)
