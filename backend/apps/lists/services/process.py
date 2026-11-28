"""Служба процесса списка (срез 015; PLAN-015, «Настройка процесса»; CONTRACT-015).

Единственное место настройки процесса, стадий, прав стадии и обязательных полей. Права — `lists.manage`;
замок списка исключительный. Включение переводит на первую открытую стадию только записи без стадии и
повышает их версию без строк истории; журнал — с автором включившего.
"""
from datetime import time

from django.db import transaction
from django.db.models import F, Max
from django.http import Http404
from django.utils import timezone

from apps.core.services import audit
from apps.lists.models import (Field, List, ListProcess, ProcessStage, ProcessStageAccess, ProcessStageField,
                               Record)
from apps.lists.services import access
from apps.lists.services.errors import ListsError

PERIODS = {"daily", "weekly", "monthly"}
MODES = {"manual", "schedule"}
KINDS = {"open", "closed"}


def _require_manage(actor) -> None:
    from django.core.exceptions import PermissionDenied

    if not access.can_manage(actor):
        raise PermissionDenied


def _clean_title(text, *, limit: int = 100, field: str = "title") -> str:
    value = "" if text is None else str(text).strip()
    if not value:
        raise ListsError("required", field=field)
    if len(value) > limit:
        raise ListsError("too_long", field=field, params={"limit": limit})
    return value


def _parse_time(raw):
    if raw in (None, ""):
        return None
    if isinstance(raw, time):
        return raw
    value = str(raw).strip()
    try:
        hours, minutes = value.split(":", 1)
        return time(int(hours), int(minutes))
    except (ValueError, TypeError):
        raise ListsError("stage_schedule_invalid") from None


def get_process(lst) -> ListProcess | None:
    return ListProcess.objects.filter(list_id=lst.pk).first()


def ensure(lst, actor) -> ListProcess:
    """Строка процесса для вкладки: создаётся выключенной, автор пуст."""
    _require_manage(actor)
    process, _ = ListProcess.objects.get_or_create(list_id=lst.pk)
    return process


def process_title(process: ListProcess, lst: List) -> str:
    return process.title.strip() or lst.name


def visible_stages(lst) -> list[ProcessStage]:
    return list(ProcessStage.objects.filter(process__list_id=lst.pk).order_by("order", "pk"))


def stage_of(lst, stage_id) -> ProcessStage:
    stage = ProcessStage.objects.select_related("process").filter(pk=stage_id, process__list_id=lst.pk).first()
    if stage is None:
        raise Http404("Стадия не найдена")
    return stage


def first_open(lst) -> ProcessStage | None:
    return ProcessStage.objects.filter(process__list_id=lst.pk, kind=ProcessStage.Kind.OPEN).order_by(
        "order", "pk").first()


def _audit(action: str, *, actor, lst, before=None, after=None):
    audit.record(action, actor=actor, object_type="lists.process", object_id=lst.pk,
                 before=before or {}, after=after or {})


def _changed(before: dict, after: dict) -> bool:
    return before != after


def save_settings(lst, actor, *, title: str = "", launch_mode: str = "manual", period: str = "",
                  weekday=None, monthday=None, time_value=None, template: str = "", enabled=None) -> ListProcess:
    """Сохраняет настройки процесса; `enabled=True/False` включает/выключает, `None` — не менять."""
    _require_manage(actor)
    title = "" if title is None else str(title).strip()
    if len(title) > 100:
        raise ListsError("too_long", field="title", params={"limit": 100})
    if launch_mode not in MODES:
        raise ListsError("stage_schedule_invalid")
    if launch_mode == "manual":
        period, weekday, monthday, time_value = "", None, None, None
    else:
        if period not in PERIODS:
            raise ListsError("stage_schedule_invalid")
        time_value = _parse_time(time_value)
        if time_value is None:
            raise ListsError("stage_schedule_invalid")
        if period == "daily":
            weekday = monthday = None
        elif period == "weekly":
            try:
                weekday = int(weekday)
            except (TypeError, ValueError):
                raise ListsError("stage_schedule_invalid") from None
            if not 1 <= weekday <= 7:
                raise ListsError("stage_schedule_invalid")
            monthday = None
        else:
            try:
                monthday = int(monthday)
            except (TypeError, ValueError):
                raise ListsError("stage_schedule_invalid") from None
            if not 1 <= monthday <= 28:
                raise ListsError("stage_schedule_invalid")
            weekday = None
    template = "" if template is None else str(template).strip()
    if len(template) > 200:
        raise ListsError("too_long", field="title_template", params={"limit": 200})

    with transaction.atomic():
        access.lock_list(lst.pk, shared=False)
        process, _ = ListProcess.objects.get_or_create(list_id=lst.pk)
        before = {"enabled": process.enabled, "title": process.title, "launch_mode": process.launch_mode,
                  "period": process.schedule_period, "weekday": process.schedule_weekday,
                  "monthday": process.schedule_monthday, "time": str(process.schedule_time or ""),
                  "template": process.title_template}
        stages = visible_stages(lst)
        turning_on = enabled is True and not process.enabled
        if turning_on:
            if not stages or not any(stage.kind == ProcessStage.Kind.OPEN for stage in stages):
                raise ListsError("stage_last_open")
            process.author = actor
        now = timezone.now()
        moved = 0
        if turning_on:
            first = first_open(lst)
            moved = Record.objects.filter(list_id=lst.pk, archived=False, stage__isnull=True).update(
                stage=first, version=F("version") + 1, updated_by=actor, updated_at=now)
        process.title = title
        process.launch_mode = launch_mode
        process.schedule_period = period
        process.schedule_weekday = weekday
        process.schedule_monthday = monthday
        process.schedule_time = time_value
        process.title_template = template
        if enabled is not None:
            process.enabled = bool(enabled)
        process.updated_at = now
        process.save()
        after = {"enabled": process.enabled, "title": process.title, "launch_mode": process.launch_mode,
                 "period": process.schedule_period, "weekday": process.schedule_weekday,
                 "monthday": process.schedule_monthday, "time": str(process.schedule_time or ""),
                 "template": process.title_template}
        if turning_on:
            _audit("lists.process_enabled", actor=actor, lst=lst,
                   before={"enabled": False}, after={"enabled": True, "moved": moved})
        elif enabled is False and before["enabled"]:
            _audit("lists.process_disabled", actor=actor, lst=lst,
                   before={"enabled": True}, after={"enabled": False})
        if _changed(before, after):
            _audit("lists.process_changed", actor=actor, lst=lst, before=before, after=after)
    return process


def add_stage(lst, actor, *, title: str, kind: str = "open") -> ProcessStage:
    _require_manage(actor)
    title = _clean_title(title)
    if kind not in KINDS:
        raise ListsError("stage_schedule_invalid")
    with transaction.atomic():
        access.lock_list(lst.pk, shared=False)
        process, _ = ListProcess.objects.get_or_create(list_id=lst.pk)
        if ProcessStage.objects.filter(process=process, title__iexact=title).exists():
            raise ListsError("stage_title_uniq", field="title")
        order = (ProcessStage.objects.filter(process=process).aggregate(top=Max("order"))["top"] or 0) + 1
        stage = ProcessStage.objects.create(process=process, title=title, order=order, kind=kind)
        _audit("lists.process_stage_changed", actor=actor, lst=lst,
               after={"stage": stage.pk, "title": stage.title, "order": stage.order, "kind": stage.kind})
    return stage


def _stage_locked(stage, actor) -> ProcessStage:
    _require_manage(actor)
    access.lock_list(stage.process.list_id, shared=False)
    return ProcessStage.objects.select_related("process").get(pk=stage.pk)


def update_stage(stage, actor, *, title: str, kind: str) -> ProcessStage:
    _require_manage(actor)
    title = _clean_title(title)
    if kind not in KINDS:
        raise ListsError("stage_schedule_invalid")
    with transaction.atomic():
        stage = _stage_locked(stage, actor)
        if ProcessStage.objects.filter(process=stage.process, title__iexact=title).exclude(pk=stage.pk).exists():
            raise ListsError("stage_title_uniq", field="title")
        if stage.kind == ProcessStage.Kind.OPEN and kind == ProcessStage.Kind.CLOSED:
            others = ProcessStage.objects.filter(process=stage.process, kind=ProcessStage.Kind.OPEN).exclude(pk=stage.pk)
            if not others.exists():
                raise ListsError("stage_last_open")
        before = {"title": stage.title, "kind": stage.kind}
        stage.title, stage.kind = title, kind
        stage.save(update_fields=["title", "kind"])
        _audit("lists.process_stage_changed", actor=actor, lst=stage.process.list,
               before=before, after={"title": stage.title, "kind": stage.kind})
    return stage


def delete_stage(stage, actor) -> None:
    with transaction.atomic():
        stage = _stage_locked(stage, actor)
        records = Record.objects.filter(stage=stage).count()
        if records:
            raise ListsError("stage_has_records", params={"count": records})
        total = ProcessStage.objects.filter(process=stage.process).count()
        if total <= 1:
            raise ListsError("stage_last_open")
        if stage.kind == ProcessStage.Kind.OPEN:
            others = ProcessStage.objects.filter(process=stage.process, kind=ProcessStage.Kind.OPEN).exclude(pk=stage.pk)
            if not others.exists():
                raise ListsError("stage_last_open")
        before = {"stage": stage.pk, "title": stage.title, "order": stage.order, "kind": stage.kind}
        stage.delete()
        _audit("lists.process_stage_deleted", actor=actor, lst=stage.process.list, before=before)


def move_stage(stage, direction: str, actor) -> None:
    if direction not in {"up", "down"}:
        raise ListsError("stage_schedule_invalid")
    with transaction.atomic():
        stage = _stage_locked(stage, actor)
        stages = list(ProcessStage.objects.filter(process=stage.process).order_by("order", "pk"))
        index = next(i for i, item in enumerate(stages) if item.pk == stage.pk)
        other_index = index - 1 if direction == "up" else index + 1
        if other_index < 0 or other_index >= len(stages):
            return None
        other = stages[other_index]
        first_order, second_order = stage.order, other.order
        # временное значение выше всех: уникальность (process, order) не срабатывает на промежуточном шаге
        temporary = max(item.order for item in stages) + 1
        ProcessStage.objects.filter(pk=stage.pk).update(order=temporary)
        ProcessStage.objects.filter(pk=other.pk).update(order=first_order)
        ProcessStage.objects.filter(pk=stage.pk).update(order=second_order)
        _audit("lists.process_stage_moved", actor=actor, lst=stage.process.list,
               before={"stage": stage.pk, "order": first_order},
               after={"stage": stage.pk, "order": second_order})
    return None


def _parse_subjects(pairs) -> list[tuple[str, int]]:
    """Строки `role:<id>` / `unit:<id>`; чужие — отказ."""
    result = []
    for raw in pairs or ():
        kind, _, number = str(raw).partition(":")
        if kind not in {"role", "unit"} or not number.isascii() or not number.isdigit():
            raise ListsError("stage_access_empty")
        result.append((kind, int(number)))
    return result


def save_stage_access(stage, actor, *, narrow: bool, read=(), edit=()) -> None:
    """Заменяет наборы прав стадии; `narrow=False` — «как у списка» (строк нет)."""
    _require_manage(actor)
    readers, editors = _parse_subjects(read), _parse_subjects(edit)
    if narrow and not readers and not editors:
        raise ListsError("stage_access_empty")
    with transaction.atomic():
        stage = _stage_locked(stage, actor)
        ProcessStageAccess.objects.filter(stage=stage).delete()
        if narrow:
            for level, pairs in (("read", readers), ("edit", editors)):
                for kind, number in pairs:
                    ProcessStageAccess.objects.create(
                        stage=stage, level=level,
                        role_id=number if kind == "role" else None,
                        unit_id=number if kind == "unit" else None)
        _audit("lists.process_stage_access_changed", actor=actor, lst=stage.process.list,
               after={"stage": stage.pk, "narrow": bool(narrow), "read": len(readers), "edit": len(editors)})
    return None


def save_stage_fields(stage, actor, codes) -> None:
    _require_manage(actor)
    codes = [str(code) for code in codes or ()]
    with transaction.atomic():
        stage = _stage_locked(stage, actor)
        fields = list(Field.objects.filter(list_id=stage.process.list_id, code__in=codes, hidden=False))
        if len(fields) != len(set(codes)):
            raise ListsError("stage_field_hidden")
        ProcessStageField.objects.filter(stage=stage).delete()
        ProcessStageField.objects.bulk_create([ProcessStageField(stage=stage, field=field) for field in fields])
        _audit("lists.process_stage_fields_changed", actor=actor, lst=stage.process.list,
               after={"stage": stage.pk, "fields": [field.code for field in fields]})
    return None


def hide_field(field, actor) -> int:
    """Убирает скрытое поле из наборов обязательных стадий списка; возвращает число затронутых стадий."""
    count = 0
    stages = ProcessStage.objects.filter(process__list_id=field.list_id, required_fields__field=field)
    for stage in stages:
        count += 1
    if count:
        ProcessStageField.objects.filter(field=field).delete()
        audit.record("lists.process_stage_fields_changed", actor=actor, object_type="lists.process",
                     object_id=field.list_id, before={"field": field.code, "stages": count},
                     after={"field": field.code, "stages": 0})
    return count
