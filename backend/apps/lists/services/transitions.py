"""Переход записи по стадиям (срез 015; PLAN-015, «Переход»; CONTRACT-015, раздел 5).

Порядок: замок списка → `FOR UPDATE` записи → чтение записи по актуальным правам → повтор по
`(record, base_version, to_stage_key)` → версия → ожидаемая стадия → права/видимость целевой → итоговые
значения и обязательные поля → запись. Повтор ищется по числовому ключу до загрузки целевой стадии.
"""
from typing import NamedTuple

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from apps.core.services import audit
from apps.lists.models import ProcessStage, Record, RecordFile, StageMove
from apps.lists.services import access, history, records as records_service, schema, unique, values as values_service
from apps.lists.services.errors import (ListsError, StageChanged, StageForbidden, StageRequired,
                                        ValuesInvalid, VersionConflict)

STAGE_FIELD = "stage"
STAGE_NAME = "Стадия"


class MoveResult(NamedTuple):
    record: Record
    stage: ProcessStage
    version: int
    repeated: bool


def _expected(value):
    """Ожидаемая стадия: отсутствие — `None`, пустая строка — тоже `None` (ожидали «без стадии»), цифры — номер."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    if text.isascii() and text.isdigit():
        return int(text)
    raise StageChanged()


def _filled(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple)):
        return any(str(item).strip() for item in value)
    return bool(str(value).strip())


def _effective(locked, data, actor):
    """Сохранённые значения плюс присланные; отсутствие сохраняет, явная пустота удаляет."""
    fields = {field.code: field for field in schema.all_fields(locked.list) if not field.hidden}
    result = dict(locked.values or {})
    errors = {}
    for code, raw in (data or {}).items():
        field = fields.get(code)
        if field is None or field.type == "file":
            continue
        parsed = values_service.parse(field, raw, old=result.get(code), viewer=actor, source="form")
        if parsed.error is not None:
            errors[code] = parsed.error
        elif parsed.value is None:
            result.pop(code, None)
        else:
            result[code] = parsed.value
    return result, errors


def _required_names(stage, record, values) -> list[str]:
    """Названия незаполненных обязательных полей стадии; файл заполнен, если у записи есть файл поля."""
    if stage is None:
        return []
    names = []
    for item in stage.required_fields.select_related("field").all():
        field = item.field
        if field.hidden:
            continue
        if field.type == "file":
            if not RecordFile.objects.filter(record_id=record.pk, field_id=field.pk).exists():
                names.append(field.name)
        elif not _filled(values.get(field.code)):
            names.append(field.name)
    return names


def move(record, target_stage, *, base_version: int, expected_stage, values=None, title=None,
         actor) -> MoveResult:
    """Переход; `target_stage` — стадия или её номер (повтор ищется по номеру до загрузки стадии)."""
    target_key = target_stage.pk if hasattr(target_stage, "pk") else int(target_stage)
    with transaction.atomic():
        access.lock_list(record.list_id, shared=True)
        access.clear_cache(actor)
        locked = Record.objects.select_for_update().select_related("list").filter(pk=record.pk).first()
        if locked is None:
            raise Http404("Запись не найдена")
        if not access.can_read_record(actor, locked):
            raise Http404("Запись не найдена")

        repeated = StageMove.objects.filter(record=locked, base_version=base_version,
                                            to_stage_key=target_key).first()
        if repeated is not None:
            found = ProcessStage.objects.filter(pk=target_key).first()
            return MoveResult(locked, found, locked.version, True)

        if locked.version != base_version:
            raise VersionConflict(locked.updated_by, locked.updated_at)
        if (locked.stage_id or None) != _expected(expected_stage):
            raise StageChanged()
        target_stage = (ProcessStage.objects.select_related("process")
                        .filter(pk=target_key, process__list_id=locked.list_id).first())
        if target_stage is None or not target_stage.process.enabled:
            raise ListsError("stage_absent")
        if not access.can_read_stage(actor, locked.list, target_stage.pk):
            raise StageForbidden()
        if not access.can_edit_record(actor, locked):
            raise StageForbidden()
        if locked.stage_id == target_stage.pk:
            return MoveResult(locked, target_stage, locked.version, True)

        current = locked.stage
        old_values = dict(locked.values or {})
        old_title = locked.title
        effective, errors = _effective(locked, values, actor)
        visible_fields = [field for field in schema.all_fields(locked.list) if not field.hidden]
        for field in visible_fields:
            if field.required and not _filled(effective.get(field.code)):
                errors.setdefault(field.code, ListsError("required", field=field.code))
        if not errors:
            records_service._precheck_unique(locked, locked.list, visible_fields, effective, errors, actor)
        if errors:
            raise ValuesInvalid(errors)
        missing = _required_names(target_stage, locked, effective)
        for name in _required_names(current, locked, effective):
            if name not in missing:
                missing.append(name)
        if missing:
            raise StageRequired(missing)

        changes = history.build_changes(visible_fields, old_values, effective, actor,
                                        old_title=old_title, new_title=old_title)
        if title is not None:
            new_title = str(title).strip()
            if not new_title:
                raise ListsError("required", field="title")
            if len(new_title) > 200:
                raise ListsError("too_long", field="title", params={"limit": 200})
            if new_title != old_title:
                changes.append({"field": "title", "name": "Название", "before": old_title, "after": new_title})
                locked.title = new_title
        old_stage = current
        locked.values = effective
        locked.stage = target_stage
        locked.version += 1
        locked.updated_by = actor
        locked.updated_at = timezone.now()
        locked.save(update_fields=["title", "values", "stage", "version", "updated_by", "updated_at"])
        records_service._sync_unique(locked, schema.all_fields(locked.list), actor)
        from apps.lists.services import vectors

        vectors.refresh([locked.pk])
        try:
            with transaction.atomic():
                StageMove.objects.create(
                    record=locked, base_version=base_version,
                    from_stage_key=old_stage.pk if old_stage else None,
                    to_stage_key=target_stage.pk,
                    from_stage=old_stage, to_stage=target_stage,
                    from_title=old_stage.title if old_stage else "Без стадии",
                    to_title=target_stage.title, actor=actor)
        except IntegrityError:
            return MoveResult(locked, target_stage, locked.version, True)
        changes.insert(0, {"field": STAGE_FIELD, "name": STAGE_NAME,
                           "before": old_stage.title if old_stage else "Без стадии",
                           "after": target_stage.title})
        history.write(locked, "stage", changes, actor)
        audit.record("lists.record_stage_changed", actor=actor, object_type="lists.record",
                     object_id=locked.pk,
                     before={"stage": old_stage.pk if old_stage else None},
                     after={"stage": target_stage.pk, "list": locked.list_id, "number": locked.number})
    return MoveResult(locked, target_stage, locked.version, False)
