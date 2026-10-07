"""Импорт сотрудников из файла (PLAN-002, «Загрузка сотрудников из таблицы», FR-136…142).

Здесь: разбор файла CSV/XLSX (`parse_file`), проверка строк (`_check_rows`), предпросмотр (`make_preview`),
выполнение (`confirm`) и образцы (`sample_csv`, `sample_xlsx`). Файл разбирается в памяти и нигде не сохраняется (FR-141).
"""
import csv
import io
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError, transaction
from django.db.models.functions import Lower

from apps.core.models import User, UserState
from apps.core.services import accounts, audit, roles, table_file
from apps.core.services.permissions import forget_users

from . import structure
from .errors import OrgError

REQUIRED_COLUMNS = ("Почта", "Фамилия", "Имя", "Должность")
OPTIONAL_COLUMNS = ("Отчество", "Телефон", "Внутренний телефон", "Место работы", "Подразделение", "Руководитель")

MAX_BYTES = 1_048_576
MAX_ROWS = 1000
MAX_PARTS = 100
MAX_UNPACKED = 20 * 1024 * 1024
NAME_LIMIT = 150
SEPARATOR = " / "

# название колонки -> латинское имя ключа строки (раздел 2 контракта)
_KEYS = {
    "Почта": "email", "Фамилия": "last_name", "Имя": "first_name", "Должность": "position",
    "Отчество": "middle_name", "Телефон": "phone", "Внутренний телефон": "internal_phone",
    "Место работы": "workplace", "Подразделение": "unit_path", "Руководитель": "head_raw",
}
# пределы длин по полям `User` (дополнение 27)
_LIMITS = {"email": 254, "full_name": 255, "position": 255, "workplace": 255, "phone": 64, "internal_phone": 32}


@dataclass
class ParsedFile:
    """Результат разбора: формат по содержимому, строки данных, названия лишних колонок."""

    file_format: str
    rows: list[dict] = field(default_factory=list)
    not_loaded: list[str] = field(default_factory=list)


def _norm_header(text) -> str:
    """Заголовок для сравнения: без пробельных знаков (и внутри слова), в нижнем регистре, «ё» как «е»."""
    return "".join(str(text or "").split()).lower().replace("ё", "е")


# --- разбор файла -----------------------------------------------------------------------------

# тексты отказов чтения таблицы: свои, срез 002 (ключи — `table_file.read`, дополнение 36 контракта)
_TEXTS = {
    "too_big": "Файл больше 1 МБ: разделите его на части.",
    "bad_format": "Не удалось прочитать таблицу XLSX: файл повреждён.",
    "bad_format_archive": "Это архив, но не таблица XLSX. Загрузите CSV (UTF-8) или XLSX.",
    "bad_format_csv": "Не удалось прочитать CSV: слишком длинное значение или нарушена разметка.",
    "not_utf8": "Файл не в кодировке UTF-8: сохраните таблицу как CSV UTF-8 или XLSX.",
    "too_many_rows": "В файле больше 1000 строк: разделите его на части.",
    "zip_bomb": "Файл отклонён: слишком много частей или слишком большой объём внутри.",
    "xml_bomb": "Файл отклонён: внутри таблицы опасная XML-конструкция.",
}
_NUL_TEXT = "Файл не в кодировке UTF-8 (или содержит нулевые байты)."


def parse_file(content: bytes) -> ParsedFile:
    """Разбирает файл сотрудников. Порядок отказов: размер, формат, оглавление XLSX, разбор, колонки, строки."""
    try:
        table = table_file.read(content, max_bytes=MAX_BYTES, max_rows=MAX_ROWS, max_parts=MAX_PARTS,
                                max_unpacked=MAX_UNPACKED, texts=_TEXTS)
    except table_file.TableFileError as error:
        message = _NUL_TEXT if error.code == "not_utf8" and b"\x00" in content else error.message
        raise OrgError(error.code, message) from None
    file_format, header = table.file_format, table.header
    columns, not_loaded = {}, []
    for index, title in enumerate(header):
        title = str(title or "")
        key = _norm_header(title)
        if not key:
            continue
        for name in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
            if _norm_header(name) == key and name not in columns:
                columns[name] = index
                break
        else:  # лишняя или повторная колонка: не читается, предпросмотр называет её (FR-138)
            not_loaded.append(title.strip())
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise OrgError("missing_columns", "В файле нет обязательных колонок: " + ", ".join(missing) + ". Загрузите таблицу CSV (UTF-8) или XLSX по образцу.")
    data = table.rows
    try:
        table_file.check_rows(data, MAX_ROWS, _TEXTS)
    except table_file.TableFileError as error:
        raise OrgError(error.code, error.message) from None
    rows = []
    for raw in data:
        row = {}
        for name, key in _KEYS.items():
            index = columns.get(name)
            row[key] = str(raw[index]) if index is not None and index < len(raw) else ""
        rows.append(row)
    return ParsedFile(file_format=file_format, rows=rows, not_loaded=not_loaded)


# --- проверка строк ---------------------------------------------------------------------------

def _load_taken(emails) -> dict:
    """Адреса портала (в нижнем регистре) из `emails` одним запросом: адрес -> `True`, если запись уволена."""
    emails = {e for e in emails if e}
    if not emails:
        return {}
    found = User.objects.annotate(key=Lower("email")).filter(key__in=emails).values_list("key", "state")
    return {key: state == UserState.DISMISSED for key, state in found}


def _load_tree() -> dict:
    """Дерево узлов в памяти: кортеж `name_key` от корня до узла -> `(название, вид)`."""
    from apps.org.models import Unit
    units = {u.pk: u for u in Unit.objects.only("id", "parent_id", "name", "name_key", "kind")}
    tree = {}

    def key_of(unit):
        parts = []
        while unit is not None:
            parts.append(unit.name_key)
            unit = units.get(unit.parent_id)
        return tuple(reversed(parts))

    for unit in units.values():
        tree[key_of(unit)] = (unit.name, unit.kind)
    return tree


def _row_result(number: int, source: dict) -> dict:
    """Начальная строка результата: поля после обрезки пробелов, почта в нижнем регистре."""
    row = {"number": number}
    for key in ("email", "last_name", "first_name", "middle_name", "position", "phone", "internal_phone",
                "workplace", "unit_path"):
        row[key] = str(source.get(key) or "").strip()
    row["email"] = row["email"].lower()
    head_raw = " ".join(str(source.get("head_raw") or "").split()).lower().replace("ё", "е")
    row["head"] = head_raw == "да"
    row.update(result="will_create", code="", reason="", hint="")
    return row


def _fail(row: dict, code: str, reason: str, result: str = "error", hint: str = ""):
    row.update(result=result, code=code, reason=reason, hint=hint)


def _check_fields(row: dict):
    """Почта, ФИО, должность и длины полей. Возвращает `(код, причина)` или `None`."""
    if not row["email"]:
        return "email_missing", "Не указана почта."
    try:
        validate_email(row["email"])
    except ValidationError:
        return "email_invalid", "Почта указана неверно: нужен вид имя@домен."
    if not row["last_name"]:
        return "last_name_missing", "Не указана фамилия."
    if not row["first_name"]:
        return "first_name_missing", "Не указано имя."
    if not row["position"]:
        return "position_missing", "Не указана должность."
    full_name = " ".join(p for p in (row["last_name"], row["first_name"], row["middle_name"]) if p)
    lengths = {"email": row["email"], "full_name": full_name, "position": row["position"],
               "workplace": row["workplace"], "phone": row["phone"], "internal_phone": row["internal_phone"]}
    titles = {"email": "Почта", "full_name": "ФИО", "position": "Должность", "workplace": "Место работы",
              "phone": "Телефон", "internal_phone": "Внутренний телефон"}
    for name, value in lengths.items():
        if len(value) > _LIMITS[name]:
            return "too_long", f"{titles[name]} длиннее {_LIMITS[name]} знаков."
    return None


def _check_path(row: dict, tree: dict, planned: dict):
    """Путь подразделения. Возвращает `(ошибка | None, новые узлы строки)`; новые узлы — `[(ключ, путь)]`."""
    path = row["unit_path"]
    if not path:
        return None, []
    parts = [" ".join(part.split()) for part in path.split("/")]
    if any(not part for part in parts):
        return ("path_invalid", "Путь подразделения содержит пустую часть: части разделяются « / »."), []
    if any(len(part) > NAME_LIMIT for part in parts):
        return ("too_long", f"Часть пути подразделения длиннее {NAME_LIMIT} знаков."), []
    keys = tuple(structure.name_key(part) for part in parts)
    root = next((key for key in tree if len(key) == 1), None)
    if root is None or keys[0] != root[0]:
        return ("path_root_mismatch", "Путь должен начинаться с названия корневого отдела."), []
    shown = [tree[root][0]]
    new = []
    for depth in range(2, len(keys) + 1):
        key = keys[:depth]
        if key in tree:
            if tree[key][1] == "team":
                return ("path_team", "На пути подразделения стоит команда: укажите отдел."), []
            shown.append(tree[key][0])
        else:
            shown.append(planned[key] if key in planned else parts[depth - 1])
            new.append((key, SEPARATOR.join(shown)))
    return None, new


def _check_rows(parsed_rows: list[dict], *, taken: dict, tree: dict):
    """Проверка строк разобранного файла (для `make_preview`, T-2218; её же — перепроверка в `confirm`).

    `parsed_rows` — `ParsedFile.rows`; `taken` — результат `_load_taken` по адресам этих строк;
    `tree` — результат `_load_tree` (в памяти не меняется). Возвращает `(rows, new_units)`:
    `rows` — строки по контракту (`number` с 1, `result`, `code`, `reason`, `hint`), `new_units` — пути
    создаваемых отделов «ИТ-отдел / Сеть», каждый один раз, только из строк «будет создан».
    """
    rows, seen, planned, new_units = [], set(), {}, []
    for number, source in enumerate(parsed_rows, start=1):
        row = _row_result(number, source)
        rows.append(row)
        problem = _check_fields(row)
        if problem:
            _fail(row, *problem)
            continue
        email = row["email"]
        if email in taken:
            if taken[email]:
                _fail(row, "email_taken_dismissed", "Такая почта уже есть.",
                      "skipped", "dismissed")
            else:
                _fail(row, "email_taken", "Такая почта уже есть в портале.", "skipped")
            continue
        if email in seen:
            _fail(row, "email_repeated", "Такая почта уже есть в файле выше.", "skipped")
            continue
        head_raw = " ".join(str(source.get("head_raw") or "").split()).lower().replace("ё", "е")
        if head_raw not in ("", "да", "нет"):
            _fail(row, "head_invalid", "В колонке «Руководитель» допустимо «да», «нет» или пусто.")
            continue
        if row["head"] and not row["unit_path"]:
            _fail(row, "head_without_unit", "Руководитель указан, а подразделение нет.")
            continue
        problem, new = _check_path(row, tree, planned)
        if problem:
            _fail(row, *problem)
            continue
        seen.add(email)
        for key, path in new:
            if key not in planned:
                planned[key] = path.rsplit(SEPARATOR, 1)[-1]
                new_units.append(path)
    return rows, new_units


def _summary(rows: list[dict], new_units: list[str], not_loaded: list[str]) -> dict:
    """Ожидаемые итоги для `StaffImport.summary` до выполнения."""
    count = lambda result: sum(1 for row in rows if row["result"] == result)  # noqa: E731
    return {"created": count("will_create"), "skipped": count("skipped"), "errors": count("error"),
            "units_created": len(new_units), "not_loaded": list(not_loaded), "new_units": list(new_units)}


# --- предпросмотр и выполнение ----------------------------------------------------------------

_ROW_FAILED = "Не удалось создать запись: ошибка при сохранении, строка пропущена."
_KEPT = ("number", "email", "result", "reason")


def make_preview(content: bytes, *, file_name: str, actor, ip=None):
    """Предпросмотр загрузки: разбор файла, проверка строк, запись `StaffImport` (state="preview"). Ничего не создаёт."""
    from apps.org.models import StaffImport
    parsed = parse_file(content)
    emails = [str(source.get("email") or "").strip().lower() for source in parsed.rows]
    rows, new_units = _check_rows(parsed.rows, taken=_load_taken(emails), tree=_load_tree())
    return StaffImport.objects.create(
        created_by=actor, file_name=(file_name or "")[:255], file_format=parsed.file_format,
        state=StaffImport.State.PREVIEW, rows=rows, summary=_summary(rows, new_units, parsed.not_loaded))


def _recheck(rows: list[dict]) -> list[dict]:
    """Перепроверка строк «будет создан» по свежим данным; остальные строки остаются как в предпросмотре."""
    pending = [row for row in rows if row["result"] == "will_create"]
    sources = [{**row, "head_raw": "да" if row["head"] else ""} for row in pending]
    checked, _ = _check_rows(sources, taken=_load_taken([row["email"] for row in pending]), tree=_load_tree())
    fresh = {row["number"]: new for row, new in zip(pending, checked)}
    return [{**fresh[row["number"]], "number": row["number"]} if row["number"] in fresh else row for row in rows]


def _unit_chain(path: str, cache: dict, actor, ip):
    """Узлы пути строки от корня; недостающие создаёт. Возвращает `(узел строки, [(ключ, узел) новых])`."""
    from apps.org.models import Unit
    parts = [" ".join(part.split()) for part in path.split("/")]
    keys = tuple(structure.name_key(part) for part in parts)
    unit, created = structure.root(), []
    for depth in range(2, len(keys) + 1):
        key = keys[:depth]
        if key in cache:
            unit = cache[key]
            continue
        found = Unit.objects.filter(parent=unit, name_key=key[-1]).first()
        if found is None:
            found = structure.create_unit(kind="department", name=parts[depth - 1], parent=unit, actor=actor, ip=ip)
            created.append((key, found))
        unit = found
    return unit, created


def _create_row(row: dict, *, staff, cache: dict, send_invites: bool, actor, ip) -> list:
    """Выполняет одну годную строку (вызывать внутри точки сохранения). Возвращает новые узлы `[(ключ, узел)]`."""
    unit, created = (None, [])
    if row["unit_path"]:
        unit, created = _unit_chain(row["unit_path"], cache, actor, ip)
    full_name = " ".join(p for p in (row["last_name"], row["first_name"], row["middle_name"]) if p)
    user = accounts.create_user(
        email=row["email"], full_name=full_name, position=row["position"], phone=row["phone"],
        internal_phone=row["internal_phone"], workplace=row["workplace"], role_ids=[staff.pk],
        actor=actor, ip=ip, invite=send_invites)
    if unit is not None:
        from apps.org.models import Membership
        mark = Membership.Mark.HEAD if row["head"] else Membership.Mark.NONE
        Membership.objects.create(user=user, unit=unit, mark=mark, created_by=actor)
        audit.record("membership.added", actor=actor, object_type="user", object_id=user.pk, ip=ip,
                     after={"unit": unit.name, "unit_id": unit.pk, "mode": "", "mark": mark.value})
        forget_users([user.pk])
    return created


def confirm(item, *, send_invites: bool, actor, ip=None):
    """Выполнение загрузки в одной транзакции; строка — в своей точке сохранения. Повторный вызов ничего не делает."""
    from apps.org.models import StaffImport
    with transaction.atomic():
        item = StaffImport.objects.select_for_update().get(pk=item.pk)
        if item.state == StaffImport.State.DONE:
            return item
        structure.lock_root()
        staff = roles.staff_role()
        rows = _recheck(item.rows)
        tree, cache, units_created = _load_tree(), {}, 0
        for row in rows:
            if row["result"] != "will_create":
                continue
            try:
                with transaction.atomic():
                    created = _create_row(row, staff=staff, cache=cache, send_invites=send_invites, actor=actor, ip=ip)
            except (DatabaseError, accounts.AccountError, OrgError) as error:
                known = isinstance(error, (accounts.AccountError, OrgError))
                row.update(result="error", code="row_failed", reason=str(error) if known else _ROW_FAILED)
                tree, cache = _load_tree(), {}
                continue
            for key, unit in created:
                cache[key] = unit
                tree[key] = (unit.name, unit.kind)
            units_created += len(created)
            row.update(result="created", code="", reason="")
        count = lambda result: sum(1 for row in rows if row["result"] == result)  # noqa: E731
        summary = {"created": count("created"), "skipped": count("skipped"), "errors": count("error"),
                   "units_created": units_created, "not_loaded": list(item.summary.get("not_loaded", []))}
        item.rows = [{key: row[key] for key in _KEPT} for row in rows]
        item.summary, item.send_invites, item.state = summary, bool(send_invites), StaffImport.State.DONE
        item.save(update_fields=["rows", "summary", "send_invites", "state"])
        audit.record("staff_import.completed", actor=actor, object_type="staff_import", object_id=item.pk, ip=ip,
                     after={"file_name": item.file_name, "send_invites": item.send_invites,
                            "created": summary["created"], "skipped": summary["skipped"],
                            "errors": summary["errors"], "units_created": summary["units_created"]})
    return item


# --- образцы ----------------------------------------------------------------------------------

def _sample_table() -> list[list[str]]:
    """Заголовки и две вымышленные строки; корень берётся из базы, чтобы строки годились для загрузки."""
    from apps.org.models import Unit
    root = Unit.objects.filter(is_root=True).values_list("name", flat=True).first() or "ИТ-отдел"
    return [
        list(REQUIRED_COLUMNS + OPTIONAL_COLUMNS),
        ["ivan.petrov@example.com", "Петров", "Иван", "Системный администратор", "Сергеевич", "+7 900 111-22-33",
         "201", "Кабинет 12", f"{root} / Сеть", "да"],
        ["anna.sidorova@example.com", "Сидорова", "Анна", "Инженер поддержки", "", "", "202", "Кабинет 14",
         f"{root} / Сеть", "нет"],
    ]


def sample_csv() -> bytes:
    """Образец CSV: UTF-8 с BOM, разделитель «;»."""
    out = io.StringIO()
    csv.writer(out, delimiter=";", lineterminator="\r\n").writerows(_sample_table())
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def sample_xlsx() -> bytes:
    """Образец XLSX: тот же заголовок и те же две строки."""
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    for line in _sample_table():
        sheet.append(line)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
