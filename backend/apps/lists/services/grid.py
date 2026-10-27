"""Сервис: отбор, фильтры, сортировка, страницы (срез 006; PLAN-006, «Таблица записей» и «Значения по типам»).

`read` разбирает GET-параметры таблицы (CONTRACT-006, 10.3) строго и молча отбрасывает лишнее; `records` собирает
набор записей выражениями ORM; `page` отдаёт страницу в 50 строк с признаком «есть следующая» и число найденного;
`columns` — столбцы сотрудника. Код поля попадает в запрос только как `Field.code` из схемы списка и только параметром
(NFR-509): в `KeyTextTransform`, `values__contains`, но не в текст SQL и не из ввода.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.db.models import (
    BigIntegerField, Case, CharField, DecimalField, Exists, F, IntegerField, OuterRef, Q, Subquery, Value, When)
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.db.models.functions import Cast
from django.http import Http404

from apps.core.extensions import ParsedQuery
from apps.core.models import User
from apps.core.widgets import MOSCOW, moscow_today, parse_date
from apps.lists.models import Field, List, Record, RecordFile, UserView
from apps.lists.services import access, schema, search

PAGE_SIZE = 50
PRESETS = ("all", "expiring", "mine", "archive")
DEFAULT_THRESHOLD = 30

_TEXT_TYPES = ("string", "text")
_RANGE_TYPES = ("number", "money", "date", "datetime")
_REFERENCE_TYPES = ("choice", "person", "unit", "record")
_DECIMAL = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_ID = re.compile(r"\d{1,18}")
_PAGE = re.compile(r"\d{1,6}")
_MAX_TEXT = 200
_STORE_MOMENT = "%Y-%m-%dT%H:%M:00Z"


@dataclass(frozen=True)
class Filter:
    """Принятый фильтр: `kind` — `contains` (подстрока), `ids` (все id по «и»), `bool` (`yes`/`no`), `from`, `to`,
    `files` (`yes`/`no`); `field` — `None` у фильтра по названию; `value` — разобранное значение (текст, список id,
    `Decimal`, строка хранения даты, `yes`/`no`)."""

    field: Field | None
    kind: str
    value: object


@dataclass(frozen=True)
class GridParams:
    """Разобранные параметры таблицы.

    `sort` — код видимого поля, `title`, `number` или пустая строка (порядок по `number`); `dir` без допустимого
    `sort` всегда `asc`. `search` — разбор строки `q` (`hint` непустой — условие поиска не применяется).
    `fields` — видимые поля списка; `values` — принятые значения фильтров по именам параметров (`f.<код>`,
    `f.<код>.from`…) для показа в форме."""

    preset: str = "all"
    sort: str = ""
    dir: str = "asc"
    q: str = ""
    search: ParsedQuery | None = None
    page: int = 1
    filters: tuple = ()
    fields: tuple = ()
    values: dict | None = None


@dataclass(frozen=True)
class Page:
    """Страница таблицы: до 50 строк, признак следующей страницы и число найденного (`count()` того же набора)."""

    rows: list
    has_next: bool
    found: int


def _check_read(lst, viewer) -> None:
    if not access.can_read(viewer, lst):
        raise Http404("Список не найден")


def presets(fields) -> list[str]:
    """Отборы, предлагаемые списку: «Все» и «Архив» всегда, «Истекает» — при видимом поле-сроке, «Закреплено за мной» —
    при видимом поле «сотрудник»."""
    offered = {"all", "archive"}
    if any(_is_deadline(field) for field in fields):
        offered.add("expiring")
    if any(field.type == "person" for field in fields):
        offered.add("mine")
    return [name for name in PRESETS if name in offered]


def _is_deadline(field: Field) -> bool:
    return field.type == "date" and bool((field.settings or {}).get("deadline"))


# --- разбор параметров -----------------------------------------------------------------------------------

def _decimal(text: str):
    text = text.strip()
    if len(text) > 40 or not _DECIMAL.fullmatch(text):
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None


def _moment(text: str):
    """«ДД.ММ.ГГГГ ЧЧ:ММ» по Москве → строка хранения в UTC."""
    try:
        local = datetime.strptime(text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=MOSCOW)
    except ValueError:
        return None
    return local.astimezone(timezone.utc).strftime(_STORE_MOMENT)


def _bound(field: Field, text: str):
    if field.type in ("number", "money"):
        return _decimal(text)
    if field.type == "date":
        day = parse_date(text)
        return day.isoformat() if day else None
    return _moment(text)


def _texts(params, name: str) -> list[str]:
    return [item.strip() for item in params.getlist(name) if item and item.strip()]


def _read_filters(params, fields) -> tuple[list[Filter], dict]:
    found: list[Filter] = []
    shown: dict = {}

    def keep(name, items, field, kind, parsed):
        for text, value in zip(items, parsed):
            found.append(Filter(field, kind, value))
        if parsed:
            shown[name] = items[:len(parsed)]

    title = [text[:_MAX_TEXT] for text in _texts(params, "f.title")]
    keep("f.title", title, None, "contains", title)
    for field in fields:
        name = f"f.{field.code}"
        if field.type in _TEXT_TYPES:
            items = [text[:_MAX_TEXT] for text in _texts(params, name)]
            keep(name, items, field, "contains", items)
        elif field.type in _REFERENCE_TYPES:
            items = [text for text in _texts(params, name) if _ID.fullmatch(text)]
            if items:
                found.append(Filter(field, "ids", [int(text) for text in items]))
                shown[name] = items
        elif field.type == "bool":
            items = [text for text in _texts(params, name) if text in ("yes", "no")]
            if items:
                found.append(Filter(field, "bool", items[0]))
                shown[name] = items[:1]
        elif field.type == "file":
            items = [text for text in _texts(params, f"{name}.files") if text in ("yes", "no")]
            if items:
                found.append(Filter(field, "files", items[0]))
                shown[f"{name}.files"] = items[:1]
        if field.type in _RANGE_TYPES:
            for edge in ("from", "to"):
                items = _texts(params, f"{name}.{edge}")
                parsed = [(item, _bound(field, item)) for item in items[:1]]
                if parsed and parsed[0][1] is not None:
                    found.append(Filter(field, edge, parsed[0][1]))
                    shown[f"{name}.{edge}"] = [parsed[0][0]]
    return found, shown


def sortable(field: Field, viewer) -> bool:
    if field.type == "file":
        return False
    if field.type == "record":
        return field.target_id is not None and access.can_read(viewer, List(pk=field.target_id))
    if field.type == "unit":
        return apps.is_installed("apps.org")
    return True


def read(params, lst, viewer) -> GridParams:
    """Параметры таблицы из `QueryDict`; коды — только из видимых полей списка, чужое и неверное — молча отбрасывается."""
    _check_read(lst, viewer)
    fields = schema.visible_fields(lst)
    preset = params.get("preset", "all")
    if preset not in presets(fields):
        preset = "all"
    by_code = {field.code: field for field in fields}
    sort = params.get("sort", "")
    if sort in ("title", "number"):
        pass
    elif sort in by_code and sortable(by_code[sort], viewer):
        pass
    else:
        sort = ""
    direction = "desc" if sort and params.get("dir") == "desc" else "asc"
    text = (params.get("q") or "").strip()
    parsed = search.parse_local(text) if text else None
    page = params.get("page", "")
    filters, shown = _read_filters(params, fields)
    return GridParams(
        preset=preset, sort=sort, dir=direction, q=text, search=parsed,
        page=int(page) if _PAGE.fullmatch(page) and int(page) >= 1 else 1,
        filters=tuple(filters), fields=tuple(fields), values=shown)


# --- набор записей ---------------------------------------------------------------------------------------

def _text_of(field: Field):
    return KeyTextTransform(field.code, "values")


def _first_text(field: Field):
    return KeyTextTransform(0, KeyTransform(field.code, "values"))


def _preset(gp: GridParams, viewer) -> tuple[dict, Q]:
    """Аннотации и условие отбора; срок сравнивается текстом (индексируемо), «сегодня» — по Москве."""
    if gp.preset == "archive":
        return {}, Q(archived=True)
    live = Q(archived=False)
    notes: dict = {}
    if gp.preset == "expiring":
        today = moscow_today()
        either = Q(pk__in=[])
        for index, field in enumerate(gp.fields):
            if _is_deadline(field):
                steps = [item for item in (field.settings.get("thresholds") or []) if isinstance(item, int)]
                limit = today + timedelta(days=max(steps) if steps else DEFAULT_THRESHOLD)
                notes[f"griddue{index}"] = _text_of(field)
                either |= Q(**{f"griddue{index}__lte": limit.isoformat()})
        return notes, live & either
    if gp.preset == "mine":
        either = Q(pk__in=[])
        for field in gp.fields:
            if field.type == "person":
                either |= Q(values__contains={field.code: [viewer.pk]})
        return notes, live & either
    return notes, live


def _apply_filter(queryset, index: int, item: Filter):
    """Условие одного фильтра; выражение поля — аннотация со служебным именем (код поля только параметром)."""
    field = item.field
    alias = f"gridf{index}"
    if field is None:
        return queryset.filter(title__icontains=item.value)
    if item.kind == "contains":
        return queryset.annotate(**{alias: _text_of(field)}).filter(**{f"{alias}__icontains": item.value})
    if item.kind == "ids":
        for value in item.value:
            queryset = queryset.filter(values__contains={field.code: [value]})
        return queryset
    if item.kind == "bool":
        hit = Q(values__contains={field.code: True})
        return queryset.filter(hit if item.value == "yes" else ~hit)
    if item.kind == "files":
        has = Exists(RecordFile.objects.filter(record_id=OuterRef("pk"), field_id=field.pk))
        return queryset.filter(has if item.value == "yes" else ~has)
    lookup = "gte" if item.kind == "from" else "lte"
    expression = _text_of(field)
    if field.type == "number":
        expression = Cast(expression, DecimalField(max_digits=30, decimal_places=15))
    elif field.type == "money":
        expression = Cast(expression, DecimalField(max_digits=15, decimal_places=2))
    return queryset.annotate(**{alias: expression}).filter(**{f"{alias}__{lookup}": item.value})


def _sort_expression(queryset, gp: GridParams):
    """`(набор с аннотациями, выражение сортировки)` по полю из `gp.sort`."""
    field = next(item for item in gp.fields if item.code == gp.sort)
    kind = field.type
    if kind in ("number", "money"):
        digits = (30, 15) if kind == "number" else (15, 2)
        return queryset, Cast(_text_of(field), DecimalField(max_digits=digits[0], decimal_places=digits[1]))
    if kind in ("string", "text", "date", "datetime", "bool"):
        return queryset, _text_of(field)
    queryset = queryset.annotate(gridfirst=_first_text(field))
    if kind == "choice":
        whens = [When(gridfirst=str(pk), then=Value(order)) for pk, order in field.choices.values_list("pk", "order")]
        return queryset, Case(*whens, default=Value(None), output_field=IntegerField())
    if kind == "person":
        names = User.objects.filter(pk=OuterRef("gridid")).values("full_name")[:1]
        return queryset.annotate(gridid=Cast(F("gridfirst"), BigIntegerField())), Subquery(names)
    if kind == "unit":
        from apps.org.services import structure

        whens = [When(gridfirst=str(unit.id), then=Value(unit.name)) for unit in structure.all_units()]
        return queryset, Case(*whens, default=Value(None), output_field=CharField())
    titles = Record.objects.filter(pk=OuterRef("gridid"), list_id=field.target_id).values("title")[:1]
    return queryset.annotate(gridid=Cast(F("gridfirst"), BigIntegerField())), Subquery(titles)


def records(lst, viewer, gp: GridParams):
    """Записи списка по отбору, фильтрам, поиску и сортировке; без среза страницы (его делает `page`).

    Последний ключ порядка — `number` по возрастанию в обоих направлениях: порядок устойчив."""
    _check_read(lst, viewer)
    notes, condition = _preset(gp, viewer)
    queryset = Record.objects.filter(list_id=lst.pk).annotate(**notes).filter(condition)
    for index, item in enumerate(gp.filters):
        queryset = _apply_filter(queryset, index, item)
    found = None if gp.search is None else search.record_condition(
        gp.search, [lst.pk], archived=gp.preset == "archive")
    if found is not None:
        queryset = queryset.filter(found)
    if gp.sort in ("", "number"):
        return queryset.order_by("-number" if gp.sort and gp.dir == "desc" else "number")
    if gp.sort == "title":
        key = F("title")
    else:
        queryset, key = _sort_expression(queryset, gp)
    ordering = key.desc(nulls_last=True) if gp.dir == "desc" else key.asc(nulls_last=True)
    return queryset.order_by(ordering, "number")


def page(queryset, gp: GridParams) -> Page:
    """Страница `gp.page`: 50 строк; 51-я строка выбирается только ради признака «есть следующая»."""
    start = (gp.page - 1) * PAGE_SIZE
    rows = list(queryset[start:start + PAGE_SIZE + 1])
    return Page(rows=rows[:PAGE_SIZE], has_next=len(rows) > PAGE_SIZE, found=queryset.count())


def columns(lst, viewer) -> list[str]:
    """Столбцы сотрудника: `UserView.columns` без скрытых и удалённых кодов; нет строки (или в ней ничего не
    осталось) — `title` и видимые поля с `show_in_table` по порядку."""
    _check_read(lst, viewer)
    fields = schema.visible_fields(lst)
    visible = {field.code for field in fields}
    saved = UserView.objects.filter(user_id=viewer.pk, list_id=lst.pk).values_list("columns", flat=True).first()
    chosen: list[str] = []
    for code in saved or []:
        if (code == "title" or code in visible) and code not in chosen:
            chosen.append(code)
    if chosen:
        return chosen
    return ["title"] + [field.code for field in fields if field.show_in_table]
