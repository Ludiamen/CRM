"""Публичный интерфейс сервис-деска: загрузка заявителей из таблицы (PLAN-003, «Подразделения-клиенты, заявители и
загрузка таблицы», FR-261…266; CONTRACT-003, 6.23).

Структура повторяет `org.services.staff_import`: разбор файла (`parse_file`), проверка строк, предпросмотр
(`make_preview`), выполнение (`confirm`) и образцы. Чтение CSV и XLSX — общий модуль ядра `table_file`. Файл разбирается
в памяти и нигде не сохраняется. Журнал — без адресов и ФИО (FR-289).
"""
import csv
import io
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Exists, OuterRef

from apps.core.services import audit, table_file

from ..models import ClientUnit, Requester, RequesterImport, Ticket, name_key
from . import dictionaries, settings
from .errors import ServiceDeskError

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_PARTS = 100
MAX_UNPACKED = 20 * 1024 * 1024
EMAIL_LIMIT = 254
NAME_LIMIT = 255
UNIT_LIMIT = 150

COLUMNS = ("Почта", "Фамилия", "Имя", "Отчество", "Подразделение")
REQUIRED = ("Почта",)
# название колонки -> ключ строки (раздел 6.23 контракта)
_KEYS = {"Почта": "email", "Фамилия": "last_name", "Имя": "first_name", "Отчество": "middle_name",
         "Подразделение": "unit"}

_FORMAT_TEXT = "Файл должен быть таблицей CSV или XLSX"
# тексты отказов чтения таблицы (раздел 14.1; дополнение 36 (а): три вида `bad_format` — один текст)
_TEXTS = {
    "too_big": "Файл больше 2 МБ",
    "bad_format": _FORMAT_TEXT,
    "bad_format_archive": _FORMAT_TEXT,
    "bad_format_csv": _FORMAT_TEXT,
    "not_utf8": "Файл должен быть в кодировке UTF-8",
    "too_many_rows": "В файле больше 2000 строк",
    "zip_bomb": "Файл не принят: после распаковки он слишком велик",
    "xml_bomb": "Файл не принят: небезопасное содержимое",
}

_REASONS = {
    "email_missing": "ошибка: не указана почта",
    "email_invalid": "ошибка: неверный формат почты",
    "foreign_domain": "ошибка: почта не из корпоративного домена",
    "email_repeated": "ошибка: повтор почты",
    "unit_archived": "ошибка: подразделение в архиве",
    "too_long": "ошибка: значение слишком длинное",
}
_ROW_FAILED = "ошибка: не удалось сохранить строку"
_DELETE_REASON = "загрузка таблицы"
_EMPTY = "—"


@dataclass
class ParsedFile:
    """Результат разбора: формат по содержимому, строки данных, названия лишних колонок."""

    file_format: str
    rows: list[dict] = field(default_factory=list)
    not_loaded: list[str] = field(default_factory=list)


def _norm_header(text) -> str:
    """Заголовок для сравнения: без пробельных знаков, в нижнем регистре, «ё» как «е»."""
    return "".join(str(text or "").split()).lower().replace("ё", "е")


# --- разбор файла -----------------------------------------------------------------------------

def parse_file(content: bytes) -> ParsedFile:
    """Разбирает файл. Порядок отказов: размер, формат, оглавление XLSX, разбор, колонки, число строк."""
    try:
        table = table_file.read(content, max_bytes=MAX_BYTES, max_rows=MAX_ROWS, max_parts=MAX_PARTS,
                                max_unpacked=MAX_UNPACKED, texts=_TEXTS)
    except table_file.TableFileError as error:
        raise ServiceDeskError(error.code, error.message) from None
    columns, not_loaded = {}, []
    for index, title in enumerate(table.header):
        title = str(title or "")
        key = _norm_header(title)
        if not key:
            continue
        for name in COLUMNS:
            if _norm_header(name) == key and name not in columns:
                columns[name] = index
                break
        else:  # лишняя или повторная колонка: не читается, предпросмотр называет её
            not_loaded.append(title.strip())
    if "Почта" not in columns:
        raise ServiceDeskError("missing_columns", "В файле нет колонки «Почта»")
    try:
        table_file.check_rows(table.rows, MAX_ROWS, _TEXTS)
    except table_file.TableFileError as error:
        raise ServiceDeskError(error.code, error.message) from None
    rows = []
    for raw in table.rows:
        row = {}
        for name, key in _KEYS.items():
            index = columns.get(name)
            row[key] = str(raw[index]) if index is not None and index < len(raw) else ""
        rows.append(row)
    return ParsedFile(file_format=table.file_format, rows=rows, not_loaded=not_loaded)


# --- проверка строк ---------------------------------------------------------------------------

def _full_name(source: dict) -> str:
    """ФИО из непустых «Фамилия», «Имя», «Отчество» через пробел."""
    return " ".join(part for part in (str(source.get(key) or "").strip()
                                      for key in ("last_name", "first_name", "middle_name")) if part)


def _fail(row: dict, code: str):
    row.update(result="error", code=code, reason=_REASONS[code])


def _check_rows(sources: list[dict]) -> tuple[list[dict], list[str]]:
    """Проверка строк без записи (для `make_preview`; её же — перепроверка в `confirm`).

    Возвращает `(rows, new_units)`: строки по контракту 6.23 и названия подразделений, которых нет в справочнике
    (по первому написанию, без повторов, только из годных строк). Адреса читаются одним запросом, справочник
    подразделений — одним, домены — по разу на домен.
    """
    emails = {str(s.get("email") or "").strip().lower() for s in sources} - {""}
    existing = {r.email: r for r in Requester.objects.select_related("client_unit").filter(email__in=emails)}
    units = {u.name_key: u for u in ClientUnit.objects.all()}
    domains, seen, planned, rows = {}, set(), {}, []
    for number, source in enumerate(sources, start=1):
        row = {"number": number, "email": str(source.get("email") or "").strip().lower(),
               "last_name": str(source.get("last_name") or "").strip(),
               "first_name": str(source.get("first_name") or "").strip(),
               "middle_name": str(source.get("middle_name") or "").strip(),
               "unit": " ".join(str(source.get("unit") or "").split()),
               "result": "", "code": "", "reason": "", "changes": {}, "origin_change": False}
        rows.append(row)
        email, unit_text = row["email"], row["unit"]
        if not email:
            _fail(row, "email_missing")
            continue
        repeated = email in seen
        seen.add(email)
        if len(email) > EMAIL_LIMIT:
            _fail(row, "too_long")
            continue
        try:
            validate_email(email)
        except ValidationError:
            _fail(row, "email_invalid")
            continue
        domain = email.rsplit("@", 1)[1]
        if domain not in domains:
            domains[domain] = settings.accepts_domain(domain)
        if not domains[domain]:
            _fail(row, "foreign_domain")
            continue
        if repeated:
            _fail(row, "email_repeated")
            continue
        name = _full_name(row)
        if len(name) > NAME_LIMIT or len(unit_text) > UNIT_LIMIT:
            _fail(row, "too_long")
            continue
        target = units.get(name_key(unit_text)) if unit_text else None
        if target is not None and target.archived:
            _fail(row, "unit_archived")
            continue
        unit_name = target.name if target is not None else planned.setdefault(name_key(unit_text), unit_text) \
            if unit_text else ""
        record = existing.get(email)
        if record is None:
            row.update(result="will_add", reason="будет добавлен")
            continue
        changes = {}
        if name and name != record.full_name:
            changes["name"] = {"before": record.full_name, "after": name}
        if unit_text and (target is None or target.pk != record.client_unit_id):
            changes["unit"] = {"before": record.client_unit.name if record.client_unit_id else "",
                               "after": unit_name}
        row["changes"] = changes
        row["origin_change"] = record.origin == Requester.Origin.TICKET
        if changes:
            parts = []
            if "name" in changes:
                parts.append(f"ФИО: {changes['name']['before'] or _EMPTY} → {changes['name']['after']}")
            if "unit" in changes:
                parts.append(f"подразделение: {changes['unit']['before'] or _EMPTY} → {changes['unit']['after']}")
            row.update(result="will_update", reason="будет обновлён: " + "; ".join(parts))
        else:
            row.update(result="unchanged", reason="без изменений")
    new_units = [name for key, name in planned.items() if key not in units]
    return rows, new_units


def _missing_stats(file_emails: set) -> tuple[int, int]:
    """Записи «таблица», адресов которых нет в файле: `(без заявок — будут удалены, с заявками — сменят отметку)`."""
    absent = Requester.objects.filter(origin=Requester.Origin.TABLE).exclude(email__in=file_emails).annotate(
        has_tickets=Exists(Ticket.objects.filter(requester=OuterRef("pk"))))
    flags = list(absent.values_list("has_tickets", flat=True))
    return flags.count(False), flags.count(True)


def _file_emails(rows: list[dict]) -> set:
    """Адреса всех непустых строк файла (в том числе строк с ошибкой), строчными."""
    return {row["email"] for row in rows if row["email"]}


# --- предпросмотр и выполнение ----------------------------------------------------------------

def make_preview(content: bytes, *, file_name: str, actor, ip=None) -> RequesterImport:
    """Предпросмотр загрузки: разбор файла, проверка строк, запись `RequesterImport` (state="preview").

    Заявителей, подразделения и журнал не трогает; файл не хранится.
    """
    parsed = parse_file(content)
    rows, new_units = _check_rows(parsed.rows)
    count = lambda result: sum(1 for row in rows if row["result"] == result)  # noqa: E731
    would_delete, origin_changed = _missing_stats(_file_emails(rows))
    summary = {"added": count("will_add"), "updated": count("will_update"), "unchanged": count("unchanged"),
               "errors": count("error"), "deleted": 0, "would_delete": would_delete,
               "origin_changed": origin_changed, "not_loaded": list(parsed.not_loaded)}
    return RequesterImport.objects.create(
        created_by=actor, file_name=(file_name or "")[:255], file_format=parsed.file_format,
        state=RequesterImport.State.PREVIEW, delete_missing=False, rows=rows, summary=summary, new_units=new_units)


def apply_row(row: dict, *, actor) -> str:
    """Записывает одну годную строку: создаёт заявителя или обновляет его. Возвращает `added`, `updated`, `unchanged`.

    Точка подмены раздела 3.5: `confirm` зовёт её в своей точке сохранения на каждую строку. Подразделение строки
    должно уже быть в справочнике (`confirm` создаёт недостающие).
    """
    email = str(row["email"]).strip().lower()
    unit_text = " ".join(str(row.get("unit") or "").split())
    unit = ClientUnit.objects.get(name_key=name_key(unit_text)) if unit_text else None
    name = _full_name(row)
    record = Requester.objects.select_for_update(of=("self",)).select_related("client_unit").filter(email=email).first()
    if record is None:
        record = Requester.objects.create(email=email, full_name=name, client_unit=unit,
                                          origin=Requester.Origin.TABLE)
        audit.record("requester.created", actor=actor, object_type="requester", object_id=record.pk,
                     before={}, after={"origin": Requester.Origin.TABLE.value,
                                       "client_unit": unit.name if unit else ""})
        return "added"
    before, after = {}, {}
    name_changed = bool(name) and name != record.full_name
    unit_changed = unit is not None and unit.pk != record.client_unit_id
    if unit_changed:
        before["client_unit"] = record.client_unit.name if record.client_unit_id else ""
        after["client_unit"] = unit.name
        record.client_unit = unit
    if name_changed:
        after["name_changed"] = True
        record.full_name = name
    if record.origin == Requester.Origin.TICKET:
        before["origin"], after["origin"] = Requester.Origin.TICKET.value, Requester.Origin.TABLE.value
        record.origin = Requester.Origin.TABLE
    if not after:
        return "unchanged"
    record.save()
    audit.record("requester.updated", actor=actor, object_type="requester", object_id=record.pk,
                 before=before, after=after)
    return "updated" if name_changed or unit_changed else "unchanged"


def _remove_missing(file_emails: set, *, actor, ip) -> tuple[int, int]:
    """Флажок «удалить»: записи «таблица» вне файла без заявок удаляются, с заявками — получают отметку «заявка».

    Возвращает `(удалено, сменили отметку)`. Записи с отметкой «заявка» не трогаются.
    """
    deleted = switched = 0
    absent = Requester.objects.select_for_update().filter(origin=Requester.Origin.TABLE).exclude(
        email__in=file_emails).order_by("pk")
    for record in list(absent):
        number = record.pk
        if Ticket.objects.filter(requester=record).exists():
            record.origin = Requester.Origin.TICKET
            record.save()
            audit.record("requester.updated", actor=actor, object_type="requester", object_id=number, ip=ip,
                         before={"origin": Requester.Origin.TABLE.value},
                         after={"origin": Requester.Origin.TICKET.value})
            switched += 1
        else:
            record.delete()
            audit.record("requester.deleted", actor=actor, object_type="requester", object_id=number, ip=ip,
                         before={"origin": Requester.Origin.TABLE.value}, after={"reason": _DELETE_REASON})
            deleted += 1
    return deleted, switched


_APPLY = ("will_add", "will_update")


def confirm(item, *, delete_missing=False, actor, ip=None) -> RequesterImport:
    """Выполнение загрузки в одной транзакции; строка — в своей точке сохранения. Повторный вызов ничего не делает."""
    with transaction.atomic():
        item = RequesterImport.objects.select_for_update().get(pk=item.pk)
        if item.state == RequesterImport.State.DONE:
            return item
        rows, new_units = _check_rows(item.rows)
        for name in new_units:
            dictionaries.create("client_unit", name=name, actor=actor, ip=ip)
        for row in rows:
            if row["result"] not in _APPLY and not (row["result"] == "unchanged" and row["origin_change"]):
                continue
            try:
                with transaction.atomic():
                    row["result"] = apply_row(row, actor=actor)
            except Exception:  # сбой строки — строка `error`, остальные идут дальше (дополнение 33 (г))
                row.update(result="error", code="row_failed", reason=_ROW_FAILED)
        for row in rows:
            row["result"] = {"will_add": "added", "will_update": "updated"}.get(row["result"], row["result"])
        deleted = switched = 0
        if delete_missing:
            deleted, switched = _remove_missing(_file_emails(rows), actor=actor, ip=ip)
        count = lambda result: sum(1 for row in rows if row["result"] == result)  # noqa: E731
        totals = {"added": count("added"), "updated": count("updated"), "unchanged": count("unchanged"),
                  "errors": count("error"), "deleted": deleted, "origin_changed": switched}
        item.rows = [{"number": row["number"], "result": row["result"],
                      "reason": row["reason"] if row["result"] == "error" else ""} for row in rows]
        item.summary = {**totals, "not_loaded": list(item.summary.get("not_loaded", []))}
        item.delete_missing, item.state, item.new_units = bool(delete_missing), RequesterImport.State.DONE, new_units
        item.save(update_fields=["rows", "summary", "delete_missing", "state", "new_units"])
        audit.record("requester_import.completed", actor=actor, object_type="requester_import", object_id=item.pk,
                     ip=ip, after={"file_name": item.file_name, "delete_missing": item.delete_missing,
                                   "totals": totals})
    return item


# --- образцы ----------------------------------------------------------------------------------

def _sample_table() -> list[list[str]]:
    """Заголовки и две вымышленные строки."""
    return [list(COLUMNS),
            ["ivan.petrov@example.com", "Петров", "Иван", "Сергеевич", "Бухгалтерия"],
            ["anna.sidorova@example.com", "Сидорова", "Анна", "", "Склад"]]


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
