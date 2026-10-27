"""Сервис: разбор, проверка и показ значений (срез 006).

`parse` — разбор ввода формы и ячейки загрузки по таблице «Значения по типам» плана (CONTRACT-006, 2.3, 5.4);
`display` — строка показа значения (CONTRACT-006, 5.4, 12.4). Служба ничего не пишет в базу и не знает о записи:
уникальность, обязательность и скрытые поля проверяют `records` и `unique`.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone

from django.apps import apps
from django.contrib.auth import get_user_model

from apps.core.widgets import MOSCOW, parse_date
from apps.lists.models import Choice, Field, Record
from apps.lists.services import access
from apps.lists.services.errors import ListsError

STRING_LIMIT = 500
TEXT_LIMIT = 10000
MAX_DIGITS = 15
MAX_MONEY_INTEGER = 13
MAX_PICK = 20

# Знак, которым ввод помечает истинное значение флажка; всё остальное — «ключа нет».
TRUE_FORM = frozenset({"on", "true", "1", "yes", "да"})
CURRENCY_SIGNS = {"RUB": "₽", "USD": "$", "EUR": "€"}
NUMBER_RE = re.compile(r"^([+-]?)(\d*)(?:[.,](\d*))?$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
REFERENCE_TYPES = ("choice", "person", "unit", "record")


@dataclass(frozen=True)
class Parsed:
    """Итог разбора: `value` — значение в форме хранения (`None` — пусто), `error` — `ListsError` или `None`."""

    value: object = None
    error: ListsError | None = None


def _fail(field: Field, code: str, **params) -> Parsed:
    return Parsed(None, ListsError(code, field=field.code, params=params or None))


def _limit_text(limit: int) -> str:
    return f"{limit:,}".replace(",", " ")


# --- разбор ------------------------------------------------------------------------------------------------

def parse(field: Field, raw, *, old=None, viewer, source: str = "form", lookups=None) -> Parsed:
    """Разбор ввода `raw` (строка или список строк) поля `field`; `old` — сохранённое значение (правило «старое
    остаётся»); `source` — `"form"` или `"import"` (правила загрузки, FR-533); `lookups` — справочники загрузки из
    `import_lookups` (расширение контракта 5.4, решение Opus), без них справочники берутся запросами.
    Апостроф перед знаком формулы здесь не снимается: это делает `imports.preview` (решение Opus И5)."""
    kind = field.type
    if kind in REFERENCE_TYPES:
        return _parse_reference(field, raw, old, viewer, source, lookups)
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if len(raw) == 1 else "\n".join(str(item) for item in raw)
    text = "" if raw is None else str(raw)
    if kind == "string":
        return _parse_string(field, text)
    if kind == "text":
        return _parse_text(field, text)
    if kind == "number":
        return _parse_decimal(field, text, money=False)
    if kind == "money":
        return _parse_decimal(field, text, money=True)
    if kind == "date":
        return _parse_date(field, text)
    if kind == "datetime":
        return _parse_datetime(field, text, source)
    if kind == "bool":
        return _parse_bool(field, text, source)
    return Parsed(None, None)  # «файл» значений не хранит


def _parse_string(field: Field, text: str) -> Parsed:
    text = text.strip()
    if not text:
        return Parsed()
    if "\n" in text or "\r" in text:
        return _fail(field, "line_break")
    if len(text) > STRING_LIMIT:
        return _fail(field, "too_long", limit=_limit_text(STRING_LIMIT))
    return Parsed(text)


def _parse_text(field: Field, text: str) -> Parsed:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return Parsed()
    if len(text) > TEXT_LIMIT:
        return _fail(field, "too_long", limit=_limit_text(TEXT_LIMIT))
    return Parsed(text)


def _parse_decimal(field: Field, text: str, *, money: bool) -> Parsed:
    text = re.sub(r"[   ]", "", text)
    if not text:
        return Parsed()
    match = NUMBER_RE.match(text)
    if not match or not (match.group(2) or match.group(3)):
        return _fail(field, "bad_number")
    sign, integer, raw_fraction = match.group(1), match.group(2).lstrip("0"), match.group(3) or ""
    fraction = raw_fraction.rstrip("0")
    significant = len(integer) + len(fraction) if integer else len(fraction.lstrip("0"))
    if money:
        if len(integer) > MAX_MONEY_INTEGER or len(raw_fraction) > 2:
            return _fail(field, "money_digits")
    elif len(integer) > MAX_DIGITS or len(fraction) > MAX_DIGITS or significant > MAX_DIGITS:
        return _fail(field, "number_digits")
    negative = sign == "-" and (integer or fraction)
    prefix = "-" if negative else ""
    if money:
        return Parsed(f"{prefix}{integer or '0'}.{fraction.ljust(2, '0')}")
    return Parsed(f"{prefix}{integer or '0'}" + (f".{fraction}" if fraction else ""))


def _parse_date(field: Field, text: str) -> Parsed:
    if not text.strip():
        return Parsed()
    day = parse_date(text)
    if day is None:
        return _fail(field, "bad_date")
    return Parsed(day.isoformat())


def _parse_datetime(field: Field, text: str, source: str) -> Parsed:
    text = text.strip()
    if not text:
        return Parsed()
    parts = text.split()
    if len(parts) == 1 and parse_date(text) is not None and source == "import":
        return _fail(field, "import_time_missing")
    if len(parts) != 2:
        return _fail(field, "bad_datetime")
    day, clock = parse_date(parts[0]), TIME_RE.match(parts[1])
    if day is None or clock is None:
        return _fail(field, "bad_datetime")
    hour, minute = int(clock.group(1)), int(clock.group(2))
    if hour > 23 or minute > 59:
        return _fail(field, "bad_datetime")
    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MOSCOW)
    return Parsed(moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"))


def _parse_bool(field: Field, text: str, source: str) -> Parsed:
    word = text.strip().lower()
    if source == "import":
        if word == "да":
            return Parsed(True)
        if word in ("", "нет"):
            return Parsed()
        return _fail(field, "value_unavailable")
    return Parsed(True) if word in TRUE_FORM else Parsed()


# --- ссылочные типы ----------------------------------------------------------------------------------------

def _as_list(raw, source: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(item) for item in raw]
    else:
        items = [str(raw)]
    if source == "import":
        items = [part for item in items for part in item.split(";")]
    return [item.strip() for item in items if item and item.strip()]


def _old_ids(old) -> set[int]:
    if not isinstance(old, (list, tuple)):
        return set()
    return {item for item in old if isinstance(item, int) and not isinstance(item, bool)}


def _parse_reference(field: Field, raw, old, viewer, source: str, lookups=None) -> Parsed:
    items = _as_list(raw, source)
    if not items:
        return Parsed()
    if source == "import":
        ids, error = _resolve_import(field, items, viewer, lookups)
        if error is not None:
            return Parsed(None, error)
    else:
        ids = []
        for item in items:
            if not (item.isascii() and item.isdigit()):
                return _fail(field, "value_unavailable")
            ids.append(int(item))
    ids = list(dict.fromkeys(ids))
    if not field.multiple and len(ids) > 1:
        return _fail(field, "value_unavailable")
    checked = [pk for pk in ids if pk not in _old_ids(old)]
    if checked and not _all_selectable(field, checked, viewer):
        return _fail(field, "value_unavailable")
    return Parsed(ids)


def _all_selectable(field: Field, ids: list[int], viewer) -> bool:
    """Можно ли выбрать все `ids` (правило «старое остаётся» уже применено вызывающим)."""
    wanted = set(ids)
    kind = field.type
    if kind == "choice":
        found = Choice.objects.filter(field=field, pk__in=wanted, archived=False).values_list("pk", flat=True)
        return wanted == set(found)
    if kind == "person":
        found = get_user_model().objects.filter(pk__in=wanted, state="active").values_list("pk", flat=True)
        return wanted == set(found)
    if kind == "unit":
        if not apps.is_installed("apps.org"):
            return True
        from apps.org.services import structure

        return wanted == set(structure.unit_refs(wanted))
    if kind == "record":
        target = field.target
        if target is None or not access.can_read(viewer, target):
            return False
        found = Record.objects.filter(pk__in=wanted, list=target, archived=False).values_list("pk", flat=True)
        return wanted == set(found)
    return False


def _not_found(field: Field, value: str, code: str = "import_not_found") -> tuple[None, ListsError]:
    return None, ListsError(code, field=field.code, params={"value": value})


def _resolve_import(field: Field, items: list[str], viewer, lookups=None):
    """Значения загрузки (названия, почта, пути) -> id; второй результат — отказ или `None`."""
    resolvers = {"choice": _import_choice, "person": _import_person, "unit": _import_unit, "record": _import_record}
    ids = []
    for item in items:
        pk, error = resolvers[field.type](field, item, viewer, lookups)
        if error is not None:
            return None, error
        ids.append(pk)
    return ids, None


def _import_choice(field: Field, value: str, viewer, lookups=None):
    if lookups is not None:
        found = lookups.choices.get(field.pk, {}).get(value.casefold(), [])
    else:
        found = [(c.pk, c.archived) for c in Choice.objects.filter(field=field, title__iexact=value)]
    if not found:
        return _not_found(field, value)
    live = [pk for pk, archived in found if not archived]
    if not live:
        return None, ListsError("value_unavailable", field=field.code)
    return live[0], None


def _import_person(field: Field, value: str, viewer, lookups=None):
    if lookups is not None:
        found = list(lookups.emails.get(value.casefold(), []))
        outside = value.casefold() in lookups.inactive_emails
        if not found:
            found = list(lookups.names.get(value.casefold(), []))[:2]
    else:
        users = get_user_model().objects.filter(state="active")
        found = list(users.filter(email__iexact=value).values_list("pk", flat=True)[:2])
        outside = False
        if not found:
            outside = get_user_model().objects.filter(email__iexact=value).exists()
            found = list(users.filter(full_name__iexact=value).values_list("pk", flat=True)[:2])
    if not found and outside:
        return None, ListsError("value_unavailable", field=field.code)
    if not found:
        return _not_found(field, value)
    if len(found) > 1:
        return _not_found(field, value, "import_ambiguous")
    return found[0], None


def _unit_paths() -> list[tuple[int, str, str]]:
    """Узлы как `(id, название, путь словами от корня через « / »)`."""
    from apps.org.services import structure

    refs = structure.all_units()
    names = {ref.id: ref.name for ref in refs}
    result = []
    for ref in refs:
        chain = [names.get(int(part), "") for part in ref.path.strip("/").split("/") if part]
        result.append((ref.id, ref.name, " / ".join(chain)))
    return result


def _import_unit(field: Field, value: str, viewer, lookups=None):
    if not apps.is_installed("apps.org"):
        return _not_found(field, value)
    wanted = value.casefold()
    if lookups is not None:
        found = list(lookups.unit_paths.get(wanted, [])) or list(lookups.unit_names.get(wanted, []))
    else:
        paths = _unit_paths()
        found = [pk for pk, name, path in paths if path.casefold() == wanted]
        if not found:
            found = [pk for pk, name, path in paths if name.casefold() == wanted]
    if not found:
        return _not_found(field, value)
    if len(found) > 1:
        return _not_found(field, value, "import_ambiguous")
    return found[0], None


def _import_record(field: Field, value: str, viewer, lookups=None):
    target = field.target
    if target is None:
        return _not_found(field, value)
    if lookups is not None:
        if field.pk not in lookups.records:
            return None, ListsError("value_unavailable", field=field.code)
        by_number, by_title = lookups.records[field.pk]
        if (value.isascii() and value.isdigit()) and int(value) in by_number:
            return by_number[int(value)], None
        found = by_title.get(value.casefold(), [])[:2]
        if not found:
            return _not_found(field, value)
        if len(found) > 1:
            return _not_found(field, value, "import_ambiguous")
        return found[0], None
    if not access.can_read(viewer, target):
        return None, ListsError("value_unavailable", field=field.code)
    live = Record.objects.filter(list=target, archived=False)
    if (value.isascii() and value.isdigit()):
        by_number = live.filter(number=int(value)).values_list("pk", flat=True).first()
        if by_number:
            return by_number, None
    found = list(live.filter(title__iexact=value).values_list("pk", flat=True)[:2])
    if not found:
        return _not_found(field, value)
    if len(found) > 1:
        return _not_found(field, value, "import_ambiguous")
    return found[0], None


# --- справочники загрузки ----------------------------------------------------------------------------------

@dataclass
class ImportLookups:
    """Справочники загрузки, собранные один раз (`import_lookups`): действующие сотрудники, узлы, значения списков
    значений, записи читаемых целевых списков не в архиве. Ключи текстов — `casefold()`."""

    emails: dict
    inactive_emails: set
    names: dict
    unit_paths: dict
    unit_names: dict
    choices: dict
    records: dict


def import_lookups(lst, fields, viewer) -> ImportLookups:
    """Справочники для разбора `fields` (видимые поля списка `lst`) с `source="import"`; `lst` не нужен для запросов,
    оставлен для единообразия вызова. Целевой список, который `viewer` не читает, в справочник записей не попадает
    (разбор даст `value_unavailable`)."""
    fields = list(fields)
    types = {field.type for field in fields}
    emails: dict = {}
    names: dict = {}
    inactive: set = set()
    if "person" in types:
        for pk, email, full_name, state in get_user_model().objects.values_list("pk", "email", "full_name", "state"):
            if state == "active":
                emails.setdefault((email or "").casefold(), []).append(pk)
                names.setdefault((full_name or "").casefold(), []).append(pk)
            else:
                inactive.add((email or "").casefold())
    unit_paths: dict = {}
    unit_names: dict = {}
    if "unit" in types and apps.is_installed("apps.org"):
        for pk, name, path in _unit_paths():
            unit_paths.setdefault(path.casefold(), []).append(pk)
            unit_names.setdefault(name.casefold(), []).append(pk)
    choices: dict = {}
    for field in fields:
        if field.type == "choice":
            table: dict = {}
            for pk, title, archived in Choice.objects.filter(field=field).values_list("pk", "title", "archived"):
                table.setdefault(title.casefold(), []).append((pk, archived))
            choices[field.pk] = table
    records: dict = {}
    readable: dict[int, bool] = {}
    for field in fields:
        target = field.target if field.type == "record" else None
        if target is None:
            continue
        if target.pk not in readable:
            readable[target.pk] = access.can_read(viewer, target)
        if not readable[target.pk]:
            continue
        by_number: dict = {}
        by_title: dict = {}
        for pk, number, title in Record.objects.filter(list=target, archived=False).values_list(
                "pk", "number", "title"):
            by_number[number] = pk
            by_title.setdefault(title.casefold(), []).append(pk)
        records[field.pk] = (by_number, by_title)
    return ImportLookups(emails, inactive, names, unit_paths, unit_names, choices, records)


# --- показ -------------------------------------------------------------------------------------------------

def display(field: Field, value, viewer) -> str:
    """Строка показа значения; пустое значение — пустая строка. Несколько значений — через «; »."""
    if value is None or value == "" or value == []:
        return ""
    kind = field.type
    if kind in ("string", "text"):
        return str(value)
    if kind == "number":
        return str(value).replace(".", ",")
    if kind == "money":
        return _display_money(field, value)
    if kind == "date":
        return _display_date(value)
    if kind == "datetime":
        return _display_datetime(value)
    if kind == "bool":
        return "Да" if value else "Нет"
    if kind in REFERENCE_TYPES and isinstance(value, (list, tuple)):
        return "; ".join(_display_references(field, list(value), viewer))
    return ""


def _display_money(field: Field, value) -> str:
    text = str(value)
    sign = "-" if text.startswith("-") else ""
    integer, _, fraction = text.lstrip("-").partition(".")
    if not (integer.isascii() and integer.isdigit()):
        return text
    grouped = f"{int(integer):,}".replace(",", " ")
    sign_of_currency = CURRENCY_SIGNS.get((field.settings or {}).get("currency", "RUB"), "₽")
    return f"{sign}{grouped},{fraction.ljust(2, '0')[:2]} {sign_of_currency}"


def _display_date(value) -> str:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return str(value)


def _display_datetime(value) -> str:
    try:
        moment = datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt_timezone.utc)
    except ValueError:
        return str(value)
    return moment.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")


def _display_references(field: Field, ids: list, viewer) -> list[str]:
    kind = field.type
    if kind == "choice":
        titles = dict(Choice.objects.filter(field=field, pk__in=ids).values_list("pk", "title"))
        return [titles[pk] for pk in ids if pk in titles]
    if kind == "person":
        users = {u.pk: u for u in get_user_model().objects.filter(pk__in=ids)}
        return [users[pk].full_name + (" (уволен)" if users[pk].state == "dismissed" else "")
                for pk in ids if pk in users]
    if kind == "unit":
        refs = {}
        if apps.is_installed("apps.org"):
            from apps.org.services import structure

            refs = structure.unit_refs(ids)
        return [refs[pk].name if pk in refs else f"узел №{pk}" for pk in ids]
    records = {r.pk: r for r in Record.objects.filter(pk__in=ids).select_related("list")}
    readable: dict[int, bool] = {}
    result = []
    for pk in ids:
        record = records.get(pk)
        if record is None:
            continue
        if record.list_id not in readable:
            readable[record.list_id] = viewer is not None and access.can_read(viewer, record.list)
        if not readable[record.list_id]:
            result.append("запись недоступного списка")
            continue
        result.append(f"{record.title} — №{record.number}" + (" (в архиве)" if record.archived else ""))
    return result
