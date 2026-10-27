"""Сервис: списки и поля (срез 006).

Здесь схема списков: создание, переименование и удаление списка, добавление поля, порядок полей (PLAN-006, «Раздел и
настройка списка», «Поля и изменение схемы»; CONTRACT-006, 5.3). Каждая служба, принимающая актора, сама проверяет
право управлять (`lists.manage`): нет права — `PermissionDenied`. Изменение схемы идёт под исключительным замком
списка `access.lock_list(list_id, shared=False)` (CONTRACT-006, 5.2); схема читается после замка. Каждое изменение —
запись журнала с «было / стало» (FR-542); значений полей записей в журнал не попадает.
"""
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, Count, F, Func, IntegerField, Max, Value, When
from django.db.models.fields.json import KeyTransform
from django.http import Http404
from django.utils import timezone

from apps.core.services import audit
from apps.lists.models import Change, Choice, Field, List, Record, RecordFile, UniqueValue
from apps.lists.services import access, unique, values
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


def visible_fields(lst) -> list[Field]:
    """Поля списка с `hidden=False` по `order` (CONTRACT-006, 5.3; места V1–V20 раздела 6)."""
    return list(Field.objects.filter(list_id=lst.pk, hidden=False).order_by("order", "pk"))


def all_fields(lst) -> list[Field]:
    """Все поля списка по `order`, со скрытыми (места A1–A9 раздела 6)."""
    return list(Field.objects.filter(list_id=lst.pk).order_by("order", "pk"))


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


# --- изменение поля --------------------------------------------------------------------------------------------

_CHANGEABLE = frozenset({"name", "hint", "type", "required", "multiple", "unique", "show_in_table", "default",
                         "currency", "target", "deadline", "thresholds"})
MISMATCH_LIMIT = 10


def has_data(field: Field) -> bool:
    """«Поле с данными» (план, «Поля и изменение схемы»): ключ в `values` записи этого списка (в том числе в
    архиве), строка `RecordFile` поля или изменение с этим кодом в истории записей этого списка. Отбор по списку
    обязателен: код `f3` есть в каждом списке."""
    return (Record.objects.filter(list_id=field.list_id, values__has_key=field.code).exists()
            or RecordFile.objects.filter(field=field).exists()
            or Change.objects.filter(record__list_id=field.list_id,
                                     changes__contains=[{"field": field.code}]).exists())


def _is_empty(value) -> bool:
    return value is None or value == [] or (isinstance(value, str) and not value.strip())


def _snapshot(field: Field) -> dict:
    """Изменяемые свойства поля для сравнения «было / стало»."""
    settings = field.settings or {}
    return {
        "name": field.name, "hint": field.hint, "type": field.type, "required": field.required,
        "multiple": field.multiple, "unique": field.unique, "show_in_table": field.show_in_table,
        "default": field.default, "currency": settings.get("currency"), "target": field.target,
        "deadline": bool(settings.get("deadline")), "thresholds": list(settings.get("thresholds") or []),
    }


def _unique_repeats(field: Field, actor) -> ListsError | None:
    """Повторы нормализованных значений по всем записям списка (и в архиве): первые 10 пар «№номер — значение»."""
    groups: dict[str, list] = {}
    rows = Record.objects.filter(list_id=field.list_id).order_by("number").values_list("number", "values")
    for number, data in rows.iterator():
        raw = (data or {}).get(field.code)
        norm = unique.normalize(field, raw)
        if norm is not None:
            groups.setdefault(norm, []).append((number, raw))
    repeated = sorted((item for group in groups.values() if len(group) > 1 for item in group), key=lambda x: x[0])
    if not repeated:
        return None
    items = "; ".join(f"№{number} — {values.display(field, raw, actor)}" for number, raw in repeated[:MISMATCH_LIMIT])
    return ListsError("unique_repeats", field="unique", params={"items": items})


def _required_missing(field: Field) -> ListsError | None:
    """Записи списка (и архива) без значения: первые 10 номеров через «, »."""
    rows = Record.objects.filter(list_id=field.list_id).order_by("number").values_list("number", "values")
    missing = [number for number, data in rows.iterator() if _is_empty((data or {}).get(field.code))]
    if not missing:
        return None
    items = ", ".join(f"№{number}" for number in missing[:MISMATCH_LIMIT])
    return ListsError("required_missing", field="required", params={"items": items})


def _multiple_in_use(field: Field) -> bool:
    """Есть запись (в том числе в архиве) с двумя и более значениями; у «файла» — с двумя и более файлами."""
    if field.type == "file":
        return (RecordFile.objects.filter(field=field).values("record_id").annotate(n=Count("pk"))
                .filter(n__gt=1).exists())
    node = KeyTransform(field.code, "values")
    kind = Func(node, function="jsonb_typeof", output_field=CharField())
    length = Func(node, function="jsonb_array_length", output_field=IntegerField())
    found = (Record.objects.filter(list_id=field.list_id).annotate(_kind=kind)
             .annotate(_n=Case(When(_kind="array", then=length), default=Value(0), output_field=IntegerField()))
             .filter(_n__gt=1))
    return found.exists()


def update_field(field, *, actor, **changes) -> Field:
    """Изменяет поле (управляющий) под исключительным замком списка; ключи `changes` — имена параметров `add_field`.

    У поля с данными разрешены название, подсказка, «показывать в таблице», значение по умолчанию, срок и пороги,
    включение «несколько значений»; тип, валюта и целевой список — `field_locked` у поля `type`, `currency` или
    `target` (FR-509). Пустое поле меняет и их: свойства, недоступные новому типу, сбрасываются, значения списка
    значений старого типа удаляются. «Уникальное» включается без повторов по всем записям (`unique_repeats`, первые
    10) — строки `UniqueValue` создаются здесь же; выключение стирает их. «Обязательное» — без пустых (`required_missing`,
    первые 10). «Несколько» выключается без записей с двумя значениями (`multiple_in_use`). Свойство не своего типа —
    `property_not_allowed`. Ничего не изменилось — записи журнала нет; иначе `lists.field_changed` с «было / стало»
    только изменённых свойств."""
    _require_manage(actor)
    unknown = set(changes) - _CHANGEABLE
    if unknown:
        raise TypeError(f"update_field: неизвестные свойства {sorted(unknown)}")
    with transaction.atomic():
        access.lock_list(field.list_id, shared=False)
        current = Field.objects.select_related("list", "target").filter(pk=field.pk).first()
        if current is None:
            raise Http404("Поле не найдено")
        lst = current.list
        old = _snapshot(current)
        new = dict(old)

        # тип
        if "type" in changes:
            new["type"] = str(getattr(changes["type"], "value", changes["type"]))
        if new["type"] not in _TYPES:
            raise _not_allowed("type")
        kind = new["type"]
        retyped = kind != old["type"]
        data_known: list = []

        def with_data() -> bool:
            if not data_known:
                data_known.append(has_data(current))
            return data_known[0]

        if retyped and with_data():
            raise ListsError("field_locked", field="type")

        # свойства не своего типа: проверяются явно присланные значения (как в add_field)
        if changes.get("required") and kind in _NO_REQUIRED:
            raise _not_allowed("required")
        if changes.get("multiple") and kind not in _MULTIPLE:
            raise _not_allowed("multiple")
        if "default" in changes and _has_default(changes["default"]) and kind not in _DEFAULT:
            raise _not_allowed("default")
        if changes.get("unique") and kind not in _UNIQUE:
            raise _not_allowed("unique")
        if changes.get("deadline") and kind not in _DEADLINE:
            raise _not_allowed("deadline")
        if changes.get("currency") and kind != "money":
            raise _not_allowed("currency")
        if changes.get("target") is not None and kind != "record":
            raise _not_allowed("target")

        # сброс свойств, которых нет у нового типа (пустое поле)
        if retyped:
            new["default"] = None
            if kind in _NO_REQUIRED:
                new["required"] = False
            if kind not in _MULTIPLE:
                new["multiple"] = False
            if kind not in _UNIQUE:
                new["unique"] = False
            if kind != "money":
                new["currency"] = None
            if kind != "record":
                new["target"] = None
            if kind not in _DEADLINE:
                new["deadline"], new["thresholds"] = False, []

        if "name" in changes:
            new["name"] = _clean_text(changes["name"], "name", FIELD_NAME_LIMIT, required=True)
        if "hint" in changes:
            new["hint"] = _clean_text(changes["hint"], "hint", HINT_LIMIT, required=False)
        for prop in ("required", "multiple", "unique", "show_in_table"):
            if prop in changes:
                new[prop] = bool(changes[prop])
        if "default" in changes:
            new["default"] = changes["default"] if _has_default(changes["default"]) else None

        # валюта и целевой список
        if changes.get("currency") and changes["currency"] != new["currency"]:
            if changes["currency"] not in CURRENCIES:
                raise ListsError("currency_bad", field="currency")
            if not retyped and with_data():
                raise ListsError("field_locked", field="currency")
            new["currency"] = changes["currency"]
        if kind == "money" and not new["currency"]:
            new["currency"] = "RUB"
        if changes.get("target") is not None and (new["target"] is None or changes["target"].pk != new["target"].pk):
            if not retyped and with_data():
                raise ListsError("field_locked", field="target")
            new["target"] = changes["target"]
        if kind == "record" and new["target"] is None:
            raise ListsError("target_required", field="target")

        # срок и пороги: при выключенном «сроке» пороги не хранятся; «30 и 7» подставляет только форма
        if "deadline" in changes:
            new["deadline"] = bool(changes["deadline"])
        if changes.get("thresholds") and not new["deadline"]:
            raise _not_allowed("thresholds")
        if not new["deadline"]:
            new["thresholds"] = []
        elif "thresholds" in changes:
            new["thresholds"] = _checked_thresholds(changes["thresholds"])
        elif not old["deadline"]:
            new["thresholds"] = []

        diff = [prop for prop in old if prop == "target" and (old[prop] and old[prop].pk) != (new[prop] and new[prop].pk)
                or prop != "target" and old[prop] != new[prop]]
        if not diff:
            return field

        if "name" in diff and Field.objects.filter(list_id=current.list_id, name__iexact=new["name"]).exclude(
                pk=current.pk).exists():
            raise ListsError("field_name_taken", field="name")

        # проверки по записям списка, в том числе в архиве
        if "unique" in diff and new["unique"]:
            refusal = _unique_repeats(current, actor)
            if refusal is not None:
                raise refusal
        if "required" in diff and new["required"]:
            refusal = _required_missing(current)
            if refusal is not None:
                raise refusal
        if "multiple" in diff and not new["multiple"] and not retyped and _multiple_in_use(current):
            raise ListsError("multiple_in_use", field="multiple")

        before = {}
        after = {"list": lst.name, "field": new["name"]}
        for prop in diff:
            before[_AUDIT_KEY.get(prop, prop)] = _audit_value(prop, old, current, actor)
        # значение по умолчанию «стало» показывается по новому типу
        settings = dict(current.settings or {})
        settings.pop("currency", None)
        settings.pop("deadline", None)
        settings.pop("thresholds", None)
        if new["currency"]:
            settings["currency"] = new["currency"]
        if new["deadline"]:
            settings["deadline"], settings["thresholds"] = True, new["thresholds"]
        current.name, current.hint, current.type = new["name"], new["hint"], new["type"]
        current.required, current.multiple, current.unique = new["required"], new["multiple"], new["unique"]
        current.show_in_table, current.default = new["show_in_table"], new["default"]
        current.target, current.settings = new["target"], settings
        for prop in diff:
            after[_AUDIT_KEY.get(prop, prop)] = _audit_value(prop, new, current, actor)
        try:
            with transaction.atomic():
                current.save()
        except IntegrityError as error:
            if _constraint_failed(error, "lists_field_list_name_ci_uniq"):
                raise ListsError("field_name_taken", field="name") from None
            raise
        if retyped and old["type"] == "choice":
            Choice.objects.filter(field=current).delete()
        if old["unique"] and not new["unique"]:
            UniqueValue.objects.filter(field=current).delete()
        if new["unique"] and not old["unique"]:
            for record in Record.objects.filter(list_id=current.list_id, values__has_key=current.code):
                if unique.normalize(current, record.values.get(current.code)) is not None:
                    unique.sync(record, [current])
        audit.record("lists.field_changed", actor=actor, object_type=FIELD_TYPE, object_id=current.pk,
                     before=before, after=after)
    for attr in ("name", "hint", "type", "required", "multiple", "unique", "show_in_table", "default", "settings"):
        setattr(field, attr, getattr(current, attr))
    field.target = current.target
    return field


_AUDIT_KEY = {"name": "field", "deadline": "thresholds"}


def _audit_value(prop: str, state: dict, field: Field, actor):
    """Значение свойства для журнала «было / стало» (`state` — снимок свойств, `field` — поле для показа умолчания)."""
    value = state[prop]
    if prop == "type":
        return Field.Type(value).label
    if prop == "default":
        return _shown_default(field, value, actor) if value is not None else ""
    if prop == "target":
        return value.name if value is not None else ""
    if prop in ("currency", "hint", "name"):
        return value or ""
    if prop == "thresholds" or prop == "deadline":
        return list(state["thresholds"]) if state["deadline"] else []
    return value


# --- скрыть, показать, удалить поле -----------------------------------------------------------------------------

_VECTOR_TYPES = ("string", "text")


def _set_hidden(field, hidden: bool, *, actor) -> None:
    """Общая часть `hide_field` и `show_field`: признак `hidden` под исключительным замком списка. У поля «строка» и
    «многострочный текст» — `List.vectors_stale_since = now` и после фиксации задание `refresh_vectors` (И2); у прочих
    типов вектор от поля не зависит — признака и задания нет (Н11). Признак уже такой — ничего не меняется."""
    _require_manage(actor)
    with transaction.atomic():
        access.lock_list(field.list_id, shared=False)
        current = Field.objects.select_related("list").filter(pk=field.pk).first()
        if current is None:
            raise Http404("Поле не найдено")
        if current.hidden == hidden:
            field.hidden = hidden
            return
        Field.objects.filter(pk=current.pk).update(hidden=hidden)
        if current.type in _VECTOR_TYPES:
            List.objects.filter(pk=current.list_id).update(vectors_stale_since=timezone.now())
            transaction.on_commit(lambda: _enqueue_refresh(current.list_id, current.pk))
        audit.record("lists.field_hidden" if hidden else "lists.field_shown", actor=actor, object_type=FIELD_TYPE,
                     object_id=current.pk,
                     before={"list": current.list.name, "field": current.name, "hidden": not hidden},
                     after={"list": current.list.name, "field": current.name, "hidden": hidden})
    field.hidden = hidden


def _enqueue_refresh(list_id: int, field_id: int) -> None:
    """Ставит задание пересчёта векторов в очередь `maintenance` (после фиксации транзакции)."""
    import django_rq

    from apps.lists import tasks  # отложенный импорт: `tasks` зовёт `vectors`, а тот — `schema`

    django_rq.get_queue("maintenance").enqueue(tasks.refresh_vectors, list_id, field_id, job_timeout=600)


def hide_field(field, *, actor) -> None:
    """Скрывает поле (управляющий): признак `hidden`, журнал `lists.field_hidden`; пересчёт векторов — заданием."""
    _set_hidden(field, True, actor=actor)


def show_field(field, *, actor) -> None:
    """Показывает скрытое поле (управляющий): признак `hidden`, журнал `lists.field_shown`; пересчёт — заданием."""
    _set_hidden(field, False, actor=actor)


def delete_field(field, *, actor) -> None:
    """Удаляет пустое поле (управляющий) под исключительным замком списка; поле с данными (`has_data`) —
    `field_has_data`. Журнал `lists.field_deleted` (`before`: список, поле, тип)."""
    _require_manage(actor)
    with transaction.atomic():
        access.lock_list(field.list_id, shared=False)
        current = Field.objects.select_related("list").filter(pk=field.pk).first()
        if current is None:
            raise Http404("Поле не найдено")
        if has_data(current):
            raise ListsError("field_has_data")
        before = {"list": current.list.name, "field": current.name, "type": Field.Type(current.type).label}
        pk = current.pk
        current.delete()
        audit.record("lists.field_deleted", actor=actor, object_type=FIELD_TYPE, object_id=pk, before=before)
