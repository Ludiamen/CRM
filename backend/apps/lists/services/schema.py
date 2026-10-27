"""Сервис: списки и поля (срез 006).

Здесь схема списков: создание, переименование и удаление списка, добавление поля, порядок полей (PLAN-006, «Раздел и
настройка списка», «Поля и изменение схемы»; CONTRACT-006, 5.3). Каждая служба, принимающая актора, сама проверяет
право управлять (`lists.manage`): нет права — `PermissionDenied`. Изменение схемы идёт под исключительным замком
списка `access.lock_list(list_id, shared=False)` (CONTRACT-006, 5.2); схема читается после замка. Каждое изменение —
запись журнала с «было / стало» (FR-542); значений полей записей в журнал не попадает.
"""
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.http import Http404
from django.utils import timezone

from apps.core.services import audit
from apps.lists.models import Field, List, Record
from apps.lists.services import access, values
from apps.lists.services.errors import ListsError

LIST_TYPE = "lists.list"
FIELD_TYPE = "lists.field"

NAME_LIMIT = 100
DESCRIPTION_LIMIT = 500
FIELD_NAME_LIMIT = 100
HINT_LIMIT = 200
FIELDS_LIMIT = 50
CURRENCIES = ("RUB", "USD", "EUR")
MAX_THRESHOLDS = 3

# Свойства по типам (план, «Значения по типам», абзац «Свойства по типам»; FR-508).
_TYPES = frozenset(Field.Type.values)
_NO_REQUIRED = frozenset({"file", "bool"})
_MULTIPLE = frozenset({"person", "unit", "record", "choice", "file"})
_DEFAULT = frozenset({"string", "number", "money", "date", "bool", "choice"})
_UNIQUE = frozenset({"string", "number"})
_DEADLINE = frozenset({"date"})


# --- общие помощники -------------------------------------------------------------------------------------------

def _require_manage(actor) -> None:
    """Схему меняет только управляющий (`lists.manage`)."""
    if not access.can_manage(actor):
        raise PermissionDenied


def _too_long(field: str, limit: int) -> ListsError:
    return ListsError("too_long", field=field, params={"limit": limit})


def _clean_text(text, field: str, limit: int, *, required: bool) -> str:
    """Обрезанная по краям строка; пустая у обязательного — отказ `required`, длиннее предела — `too_long`."""
    text = "" if text is None else str(text).strip()
    if required and not text:
        raise ListsError("required", field=field)
    if len(text) > limit:
        raise _too_long(field, limit)
    return text


def _constraint_failed(error: IntegrityError, constraint: str) -> bool:
    return constraint in str(error)


# --- списки ----------------------------------------------------------------------------------------------------

def create_list(*, name, description, actor) -> List:
    """Создаёт список (управляющий): название до 100 знаков, описание до 500; дубль названия без учёта регистра —
    `name_taken` у поля `name`, в том числе по ограничению базы. Наборов прав у нового списка нет. Журнал
    `lists.list_created`."""
    _require_manage(actor)
    name = _clean_text(name, "name", NAME_LIMIT, required=True)
    description = _clean_text(description, "description", DESCRIPTION_LIMIT, required=False)
    now = timezone.now()
    with transaction.atomic():
        if List.objects.filter(name__iexact=name).exists():
            raise ListsError("name_taken", field="name")
        try:
            with transaction.atomic():
                lst = List.objects.create(name=name, description=description, created_by=actor, created_at=now,
                                          updated_at=now)
        except IntegrityError as error:
            if _constraint_failed(error, "lists_list_name_ci_uniq"):
                raise ListsError("name_taken", field="name") from None
            raise
        audit.record("lists.list_created", actor=actor, object_type=LIST_TYPE, object_id=lst.pk,
                     after={"name": lst.name, "description": lst.description})
    return lst


def update_list(lst, *, name, description, actor) -> List:
    """Переименование и описание списка; журнал `lists.list_changed` — только изменённые `name`, `description` с
    «было / стало» (ничего не изменилось — записи нет)."""
    _require_manage(actor)
    name = _clean_text(name, "name", NAME_LIMIT, required=True)
    description = _clean_text(description, "description", DESCRIPTION_LIMIT, required=False)
    with transaction.atomic():
        current = List.objects.filter(pk=lst.pk).first()
        if current is None:
            raise Http404("Список не найден")
        before, after = {}, {}
        if current.name != name:
            before["name"], after["name"] = current.name, name
        if current.description != description:
            before["description"], after["description"] = current.description, description
        if after:
            if "name" in after and List.objects.filter(name__iexact=name).exclude(pk=current.pk).exists():
                raise ListsError("name_taken", field="name")
            current.name, current.description, current.updated_at = name, description, timezone.now()
            try:
                with transaction.atomic():
                    current.save(update_fields=["name", "description", "updated_at"])
            except IntegrityError as error:
                if _constraint_failed(error, "lists_list_name_ci_uniq"):
                    raise ListsError("name_taken", field="name") from None
                raise
            audit.record("lists.list_changed", actor=actor, object_type=LIST_TYPE, object_id=current.pk,
                         before=before, after=after)
    lst.name, lst.description, lst.updated_at = current.name, current.description, current.updated_at
    return lst


def can_delete_list(lst) -> ListsError | None:
    """Почему список нельзя удалить, или `None`: есть записи (в том числе в архиве) — `list_has_records`; есть поле
    другого списка с целью на этот — `list_referenced` (первое по названию списка и поля); поле этого же списка на
    себя не мешает (FR-509)."""
    if Record.objects.filter(list_id=lst.pk).exists():
        return ListsError("list_has_records")
    blocker = (Field.objects.filter(target_id=lst.pk).exclude(list_id=lst.pk).select_related("list")
               .order_by("list__name", "name", "pk").first())
    if blocker is not None:
        return ListsError("list_referenced", params={"field": blocker.name, "list": blocker.list.name})
    return None


def delete_list(lst, *, actor) -> None:
    """Удаляет список вместе с полями (управляющий): исключительный замок списка, затем `FOR UPDATE` строки списка;
    запреты — `can_delete_list`. Журнал `lists.list_deleted` (название)."""
    _require_manage(actor)
    with transaction.atomic():
        access.lock_list(lst.pk, shared=False)
        current = List.objects.select_for_update().filter(pk=lst.pk).first()
        if current is None:
            raise Http404("Список не найден")
        refusal = can_delete_list(current)
        if refusal is not None:
            raise refusal
        name, pk = current.name, current.pk
        current.delete()
        audit.record("lists.list_deleted", actor=actor, object_type=LIST_TYPE, object_id=pk, before={"name": name})


# --- поля ------------------------------------------------------------------------------------------------------

def _checked_thresholds(thresholds) -> list[int]:
    """Пороги срока: до трёх целых 1…365 без повторов (FR-529); пустые строки формы пропускаются."""
    result: list[int] = []
    for item in thresholds or ():
        if isinstance(item, str):
            item = item.strip()
            if item == "":
                continue
            if not (item.isascii() and item.isdigit()):
                raise ListsError("thresholds_bad", field="thresholds")
            item = int(item)
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 365 or item in result:
            raise ListsError("thresholds_bad", field="thresholds")
        result.append(item)
    if len(result) > MAX_THRESHOLDS:
        raise ListsError("thresholds_bad", field="thresholds")
    return result


def _not_allowed(prop: str) -> ListsError:
    return ListsError("property_not_allowed", field=prop)


def _has_default(default) -> bool:
    return default is not None and default is not False and default != "" and default != []


def _shown_default(field: Field, default, actor) -> str:
    """Значение по умолчанию строкой показа для журнала."""
    if isinstance(default, dict):
        return "сегодня"
    return values.display(field, default, actor)


def add_field(lst, *, name, type, actor, hint="", required=False, multiple=False, unique=False,
              show_in_table=False, default=None, currency=None, target=None, deadline=False,
              thresholds=()) -> Field:
    """Добавляет поле (управляющий), код `f<next_field_no>` под исключительным замком списка.

    Свойство не своего типа — `property_not_allowed` у этого свойства (FR-508); название обязательно, уникально в
    списке без учёта регистра, до 100 знаков; предел 50 полей считается со скрытыми (`fields_limit`); у «денег»
    валюта по умолчанию `RUB`; у «записи другого списка» нужен `target` — объект `List` (`target_required`); пороги
    срока — только у даты со «сроком»; новое «обязательное» в списке с записями — `required_new_with_records`
    (FR-509); `order` — последний + 1. Значение по умолчанию схема проверяет только по правилу шести типов: его
    разбор — `values.parse` на форме. Журнал `lists.field_created`."""
    _require_manage(actor)
    type = str(getattr(type, "value", type))
    name = _clean_text(name, "name", FIELD_NAME_LIMIT, required=True)
    hint = _clean_text(hint, "hint", HINT_LIMIT, required=False)
    if type not in _TYPES:
        raise _not_allowed("type")
    if required and type in _NO_REQUIRED:
        raise _not_allowed("required")
    if multiple and type not in _MULTIPLE:
        raise _not_allowed("multiple")
    if _has_default(default) and type not in _DEFAULT:
        raise _not_allowed("default")
    if unique and type not in _UNIQUE:
        raise _not_allowed("unique")
    if deadline and type not in _DEADLINE:
        raise _not_allowed("deadline")
    if currency and type != "money":
        raise _not_allowed("currency")
    if target is not None and type != "record":
        raise _not_allowed("target")
    if thresholds and not deadline:
        raise _not_allowed("thresholds")
    settings: dict = {}
    if type == "money":
        currency = currency or "RUB"
        if currency not in CURRENCIES:
            raise ListsError("currency_bad", field="currency")
        settings["currency"] = currency
    if type == "record" and target is None:
        raise ListsError("target_required", field="target")
    if deadline:
        settings["deadline"] = True
        settings["thresholds"] = _checked_thresholds(thresholds)
    default = default if _has_default(default) else None

    with transaction.atomic():
        access.lock_list(lst.pk, shared=False)
        current = List.objects.filter(pk=lst.pk).first()
        if current is None:
            raise Http404("Список не найден")
        rows = Field.objects.filter(list_id=current.pk)
        if rows.count() >= FIELDS_LIMIT:
            raise ListsError("fields_limit")
        if rows.filter(name__iexact=name).exists():
            raise ListsError("field_name_taken", field="name")
        if required and Record.objects.filter(list_id=current.pk).exists():
            raise ListsError("required_new_with_records", field="required")
        order = (rows.aggregate(last=Max("order"))["last"] or 0) + 1
        number = current.next_field_no
        List.objects.filter(pk=current.pk).update(next_field_no=F("next_field_no") + 1)
        try:
            with transaction.atomic():
                field = Field.objects.create(
                    list=current, code=f"f{number}", name=name, hint=hint, type=type, required=bool(required),
                    multiple=bool(multiple), unique=bool(unique), show_in_table=bool(show_in_table),
                    default=default, order=order, target=target, settings=settings)
        except IntegrityError as error:
            if _constraint_failed(error, "lists_field_list_name_ci_uniq"):
                raise ListsError("field_name_taken", field="name") from None
            raise
        after = {"list": current.name, "field": field.name, "type": Field.Type(type).label}
        for prop in ("required", "multiple", "unique", "show_in_table"):
            if getattr(field, prop):
                after[prop] = True
        if field.default is not None:
            after["default"] = _shown_default(field, field.default, actor)
        if field.hint:
            after["hint"] = field.hint
        if type == "money":
            after["currency"] = settings["currency"]
        if target is not None:
            after["target"] = target.name
        if deadline:
            after["thresholds"] = list(settings["thresholds"])
        audit.record("lists.field_created", actor=actor, object_type=FIELD_TYPE, object_id=field.pk, after=after)
    lst.next_field_no = number + 1
    return field


def _locked_fields(list_id: int) -> list[Field]:
    """Все строки `Field` списка (в том числе скрытые) по порядку; читается после исключительного замка."""
    return list(Field.objects.filter(list_id=list_id).order_by("order", "pk"))


def move_field(field, direction, *, actor) -> None:
    """Меняет `order` поля с соседом по всем полям списка (со скрытыми): `direction` — `"up"` или `"down"`; у края
    списка ничего не происходит."""
    _require_manage(actor)
    if direction not in ("up", "down"):
        raise ValueError("direction: up или down")
    with transaction.atomic():
        access.lock_list(field.list_id, shared=False)
        rows = _locked_fields(field.list_id)
        position = next((i for i, row in enumerate(rows) if row.pk == field.pk), None)
        if position is None:
            raise Http404("Поле не найдено")
        neighbour = position - 1 if direction == "up" else position + 1
        if not 0 <= neighbour < len(rows):
            return
        rows[position], rows[neighbour] = rows[neighbour], rows[position]
        for number, row in enumerate(rows, start=1):
            if row.order != number:
                Field.objects.filter(pk=row.pk).update(order=number)
    field.order = next(number for number, row in enumerate(rows, start=1) if row.pk == field.pk)


def set_order(lst, codes, *, actor) -> None:
    """Новый порядок полей по списку кодов: `codes` — коды всех строк `Field` списка, в том числе скрытых, без
    `title` (системное «Название» всегда первое). Чужой, пропущенный, повторный код и `title` — `bad_order` без
    изменений."""
    _require_manage(actor)
    codes = list(codes or [])
    with transaction.atomic():
        access.lock_list(lst.pk, shared=False)
        rows = _locked_fields(lst.pk)
        by_code = {row.code: row for row in rows}
        if len(codes) != len(rows) or set(codes) != set(by_code):
            raise ListsError("bad_order")
        for number, code in enumerate(codes, start=1):
            if by_code[code].order != number:
                Field.objects.filter(pk=by_code[code].pk).update(order=number)
