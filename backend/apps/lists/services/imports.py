"""Сервис: загрузка записей из таблицы — файл, сопоставление, предпросмотр, подтверждение, образец (срез 006).

Шаги по плану («Загрузка из таблицы и образец»; FR-533…FR-535, FR-542, NFR-504; CONTRACT-006, 5.2, 5.7, 12, 15.5, 15.6),
всё под правом «правит» (нет права — `PermissionDenied`, список не читается — `Http404`). Файл не хранится: строки лежат в
`ImportJob.rows`, до подтверждения в базе ничего не меняется. Справочники загружаются в память один раз на проход
(`values.import_lookups`, И5), апостроф перед знаком формулы снимает эта служба (`values.parse` его не трогает, И5),
значения скрытых полей не присылаются (И7). Значения ячеек в журнал не пишутся.
"""
import io
from datetime import timedelta
from urllib.parse import quote

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from apps.core.services import audit, table_file
from apps.core.services.audit_search import FORMULA_START
from apps.lists.models import Change, Field, ImportJob, List, Record, UniqueValue
from apps.lists.services import access, history, records, schema, unique, values, vectors
from apps.lists.services.errors import ListsError
from apps.lists.texts import TABLE_FILE_TEXTS, TEXTS

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_PARTS = 100
MAX_UNPACKED = 50 * 1024 * 1024
JOB_AGE = timedelta(days=1)
TITLE = "title"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TABLE_CODES = {"too_big": "import_too_big", "too_many_rows": "import_too_many_rows"}
_TYPE_FORMAT = {"date": "ДД.ММ.ГГГГ", "datetime": "ДД.ММ.ГГГГ ЧЧ:ММ", "money": "1234,50"}


# --- права и задание ------------------------------------------------------------------------------------------

def require_edit(actor, list_id: int) -> List:
    """Список читается (иначе 404) и правится (иначе 403)."""
    lst = access.get_list(actor, list_id)
    if not access.can_edit(actor, lst):
        raise PermissionDenied("Нет права править записи списка")
    return lst


def get_job(user, lst, job_id) -> ImportJob:
    """Задание по паре «номер, список» и автору, не старше суток; иначе `Http404`. Право «правит» — каждый раз заново."""
    require_edit(user, lst.pk)
    job = ImportJob.objects.filter(
        pk=job_id, list_id=lst.pk, created_by=user, created_at__gte=timezone.now() - JOB_AGE).first()
    if job is None:
        raise Http404("Задание не найдено")
    return job


# --- файл -----------------------------------------------------------------------------------------------------

def _plain(value) -> str:
    """Ячейка строкой без символа NUL (его не принимает `jsonb`)."""
    return str(value if value is not None else "").replace("\x00", "")


def upload(lst, actor, *, name: str, content: bytes) -> ImportJob:
    """Читает файл с пределами плана и заводит задание в состоянии `mapping`; отказ — `ListsError` у поля `file`."""
    require_edit(actor, lst.pk)
    try:
        table = table_file.read(content, max_bytes=MAX_BYTES, max_rows=MAX_ROWS, max_parts=MAX_PARTS,
                                max_unpacked=MAX_UNPACKED, texts=TABLE_FILE_TEXTS)
        table_file.check_rows(table.rows, MAX_ROWS, TABLE_FILE_TEXTS)
    except table_file.TableFileError as error:
        raise ListsError(_TABLE_CODES.get(error.code, "import_bad_format"), field="file") from None
    if not table.header or not any(str(cell).strip() for cell in table.header):
        raise ListsError("import_bad_format", field="file")
    rows = [{"row": number, "cells": [_plain(cell) for cell in cells]} for number, cells in enumerate(table.rows, 2)]
    return ImportJob.objects.create(
        list=lst, created_by=actor, created_at=timezone.now(), file_name=_plain(name)[:255],
        file_format=table.file_format, header=[_plain(cell) for cell in table.header], rows=rows)


# --- сопоставление --------------------------------------------------------------------------------------------

def _mappable(lst) -> dict:
    """Видимые поля без «файл»: код -> `Field`."""
    return {field.code: field for field in schema.visible_fields(lst) if field.type != "file"}


def _unprotect(text: str) -> str:
    """Одиночный апостроф перед знаком из `FORMULA_START` снимается (обратная сторона защиты выгрузки, F2 Ф2)."""
    if text[:1] == "'" and text[1:2] and text[1:2] in FORMULA_START:
        return text[1:]
    return text


def auto_mapping(lst, header) -> dict:
    """Номер столбца (строкой) -> код поля или `title` по названию без учёта регистра и крайних пробелов."""
    names = {"название": TITLE}
    for code, field in _mappable(lst).items():
        names.setdefault(field.name.strip().casefold(), code)
    found: dict = {}
    taken: set = set()
    for number, cell in enumerate(header):
        code = names.get(_unprotect(str(cell)).strip().casefold())
        if code is not None and code not in taken:
            found[str(number)] = code
            taken.add(code)
    return found


def _clean_mapping(lst, mapping) -> dict:
    by_code = _mappable(lst)
    clean: dict = {}
    for key, code in (mapping or {}).items():
        key = str(key)
        if key.isascii() and key.isdigit() and (code == TITLE or code in by_code):
            clean[key] = code
    return clean


# --- проверка строк -------------------------------------------------------------------------------------------

def _lookups_for(lst, mapping, actor):
    """Справочники загрузки для сопоставленных полей: один раз на проход (И5)."""
    by_code = _mappable(lst)
    mapped = [by_code[code] for _, code in sorted((int(key), code) for key, code in mapping.items())
              if code in by_code]
    return values.import_lookups(lst, mapped, actor)


def _evaluate(lst, rows, mapping, actor, lookups=None) -> list:
    """Проверяет строки по свежим данным: список пар (строка для `rows`, внутреннее для подтверждения).

    Справочники и владельцы уникальных значений собираются один раз на проход; ничего не пишется."""
    by_code = _mappable(lst)
    visible = list(by_code.values())
    columns = sorted((int(key), code) for key, code in mapping.items() if code == TITLE or code in by_code)
    mapped = [by_code[code] for _, code in columns if code in by_code]
    if lookups is None:
        lookups = _lookups_for(lst, mapping, actor)
    unique_fields = [field for field in dict.fromkeys(mapped) if field.unique]
    stage = []
    for item in rows:
        cells = item.get("cells") or []
        texts: dict = {}
        for index, code in columns:
            if code not in texts:
                texts[code] = _unprotect(cells[index]) if index < len(cells) else ""
        title = texts.get(TITLE, "").strip()
        parsed: dict = {}
        error = ""
        for code, text in texts.items():
            if code == TITLE:
                continue
            field = by_code[code]
            result = values.parse(field, text, viewer=actor, source="import", lookups=lookups)
            if result.error is not None:
                error = f"{field.name}: {result.error.message}"
                break
            parsed[code] = result.value
        if not error and len(title) > records.TITLE_LIMIT:
            error = "Название: " + ListsError("too_long", params={"limit": str(records.TITLE_LIMIT)}).message
        stage.append({"item": item, "texts": texts, "title": title, "parsed": parsed, "error": error})
    owners: dict = {}
    for field in unique_fields:
        norms = set()
        for entry in stage:
            if not entry["error"] and entry["parsed"].get(field.code) is not None:
                norm = unique.normalize(field, entry["parsed"][field.code])
                if norm:
                    norms.add(norm)
        owners[field.code] = unique.find_owners(lst, field, norms)
    seen: dict = {}
    out = []
    for entry in stage:
        number = entry["item"]["row"]
        result, reason, owner = "will_create", entry["error"], None
        pending: dict = {}
        if reason:
            result = "error"
        else:
            found: dict = {}
            for field in unique_fields:
                norm = unique.normalize(field, entry["parsed"].get(field.code)) if field.code in entry["parsed"] else None
                if not norm:
                    continue
                if (field.code, norm) in seen:
                    reason = ListsError("import_repeat_in_file", params={"row": seen[(field.code, norm)]}).message
                    break
                pending[(field.code, norm)] = number
                record = owners.get(field.code, {}).get(norm)
                if record is not None:
                    found[record.pk] = record
            if reason:
                result = "error"
            elif len(found) > 1:
                result, reason = "error", ListsError("import_two_records").message
            elif found:
                owner = next(iter(found.values()))
                if owner.archived:
                    result, reason = "error", TEXTS["record_archived"]
                else:
                    result = "will_update"
            else:
                if not entry["title"]:
                    result, reason = "error", TEXTS["import_no_title"]
                else:
                    for field in visible:
                        if field.required and entry["parsed"].get(field.code) is None:
                            result, reason = "error", f"{field.name}: {TEXTS['required']}"
                            break
        if result != "error":
            seen.update(pending)
        public = {"row": number, "cells": entry["item"].get("cells") or [], "result": result, "reason": reason,
                  "number": owner.number if result == "will_update" else None}
        out.append((public, {**entry, "owner": owner if result == "will_update" else None, "fields": by_code}))
    return out


def preview(job: ImportJob, mapping, actor) -> ImportJob:
    """Сопоставление и проверка: заполняет `rows`, `state="preview"`; записей не меняет."""
    lst = require_edit(actor, job.list_id)
    if job.state == ImportJob.State.DONE:
        raise Http404("Загрузка уже выполнена")
    clean = _clean_mapping(lst, mapping)
    job.mapping = clean
    job.rows = [public for public, _ in _evaluate(lst, job.rows, clean, actor)]
    job.state = ImportJob.State.PREVIEW
    job.save(update_fields=["mapping", "rows", "state"])
    return job


def counts(job: ImportJob) -> dict:
    """Число строк по итогам проверки."""
    found = {"will_create": 0, "will_update": 0, "error": 0}
    for row in job.rows:
        if row.get("result") in found:
            found[row["result"]] += 1
    return found


# --- подтверждение --------------------------------------------------------------------------------------------

CHUNK = 250


class _Batch:
    """Накопитель порции: строки `UniqueValue`, записи с устаревшими строками и события истории — на пакетную вставку."""

    def __init__(self):
        self.unique_rows: list = []
        self.stale: list = []
        self.changes: list = []
        self.touched: list = []
        self.created = 0
        self.updated = 0

    def flush(self) -> None:
        """Одна пачка вставок; `IntegrityError` ограничения уникальности — `ListsError` (порция откатывается вызывающим)."""
        try:
            if self.stale:
                UniqueValue.objects.filter(record_id__in=self.stale).delete()
            if self.unique_rows:
                UniqueValue.objects.bulk_create(self.unique_rows)
        except IntegrityError:
            raise ListsError("unique_taken") from None
        if self.changes:
            Change.objects.bulk_create(self.changes)


def _apply_row(locked, entry, result, actor, every, batch: _Batch, counter: list) -> None:
    """Создаёт или обновляет одну строку без проверки прав и замков; вставки уникальности и истории — в `batch`."""
    if result == "will_create":
        stored = {code: value for code, value in entry["parsed"].items() if value is not None}
        record = records.create_locked(locked, counter[0], entry["title"], stored, actor)
        counter[0] += 1
        batch.unique_rows.extend(unique.rows_for(record, every))
        batch.changes.append(history.make(record, "created", [], actor, via_import=True))
        batch.touched.append(record.pk)
        batch.created += 1
        return
    record = Record.objects.select_for_update().filter(pk=entry["owner"].pk, list_id=locked.pk).first()
    if record is None or record.archived:
        raise ListsError("record_archived")
    old = dict(record.values or {})
    new = dict(old)
    for code, value in entry["parsed"].items():
        if not entry["texts"][code].strip():
            continue  # пустая ячейка значения не меняет
        if value is None:
            new.pop(code, None)
        else:
            new[code] = value
    title = entry["title"] or record.title
    batch.touched.append(record.pk)
    batch.updated += 1
    if title == record.title and new == old:
        return
    shown = [entry["fields"][code] for code in entry["parsed"]]
    entries = history.build_changes(shown, old, new, actor, old_title=record.title, new_title=title)
    records.update_locked(record, title, new, actor)
    batch.stale.append(record.pk)
    batch.unique_rows.extend(unique.rows_for(record, every))
    batch.changes.append(history.make(record, "imported", entries, actor, via_import=True))


def _run_chunk(locked, chunk, actor, every, counter: list, summary: dict, touched: list) -> None:
    """Порция в одной точке сохранения; при ошибке строки порция откатывается (с ней — счётчик номеров) и повторяется
    по одной строке, каждая в своей точке сохранения: строки с ошибками не загружаются, остальные загружаются (FR-534)."""
    start = counter[0]
    batch = _Batch()
    try:
        with transaction.atomic():
            for result, entry in chunk:
                _apply_row(locked, entry, result, actor, every, batch, counter)
            batch.flush()
    except (ListsError, IntegrityError):
        counter[0] = start
    else:
        summary["created"] += batch.created
        summary["updated"] += batch.updated
        touched.extend(batch.touched)
        return
    for result, entry in chunk:
        start = counter[0]
        single = _Batch()
        try:
            with transaction.atomic():
                _apply_row(locked, entry, result, actor, every, single, counter)
                single.flush()
        except (ListsError, IntegrityError):
            counter[0] = start
            summary["errors"] += 1
        else:
            summary["created"] += single.created
            summary["updated"] += single.updated
            touched.extend(single.touched)


def confirm(lst, job_id, actor) -> dict:
    """Выполняет загрузку: замок списка (разделяемый) → `FOR UPDATE` задания → `FOR UPDATE` списка (5.2) — по одному разу
    на всё подтверждение; поля читаются один раз. Строки идут порциями по `CHUNK` в точке сохранения, каждая
    перепроверяется по свежим данным; ошибка строки откатывает порцию (и счётчик номеров), порция повторяется по одной
    строке. История и значения уникальности — пакетно; `next_number` обновляется один раз; вектор — в конце. Повтор —
    прежний итог (решение 63)."""
    require_edit(actor, lst.pk)
    with transaction.atomic():
        access.lock_list(lst.pk, shared=True)
        job = (ImportJob.objects.select_for_update()
               .filter(pk=job_id, list_id=lst.pk, created_by=actor, created_at__gte=timezone.now() - JOB_AGE).first())
        if job is None:
            raise Http404("Задание не найдено")
        if job.state == ImportJob.State.DONE:
            return dict(job.summary)
        if job.state != ImportJob.State.PREVIEW:
            raise Http404("Задание не проверено")
        locked = List.objects.select_for_update().filter(pk=lst.pk).first()
        if locked is None:
            raise Http404("Список не найден")
        every = schema.all_fields(locked)
        summary = {"created": 0, "updated": 0, "errors": 0}
        touched: list[int] = []
        lookups = _lookups_for(locked, job.mapping, actor)
        todo = []
        for public, entry in _evaluate(locked, job.rows, job.mapping, actor, lookups):
            if public["result"] == "error":
                summary["errors"] += 1
            else:
                todo.append((public["result"], entry))
        counter = [locked.next_number]
        for index in range(0, len(todo), CHUNK):
            _run_chunk(locked, todo[index:index + CHUNK], actor, every, counter, summary, touched)
        if counter[0] != locked.next_number:
            List.objects.filter(pk=locked.pk).update(next_number=counter[0])
        vectors.refresh(touched)
        job.state, job.rows, job.summary = ImportJob.State.DONE, [], summary
        job.save(update_fields=["state", "rows", "summary"])
        audit.record("lists.import_done", actor=actor, object_type="lists.import", object_id=job.pk,
                     after={"list": locked.name, "file": job.file_name, **summary})
    return summary


# --- образец --------------------------------------------------------------------------------------------------

def _safe(value):
    """Текстовая ячейка с защитой от формул (правило `FORMULA_START`)."""
    text = str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def sample(lst) -> bytes:
    """XLSX-образец: первый лист — «Название» и видимые поля кроме «файл»; второй — «Подсказки» (FR-535)."""
    from openpyxl import Workbook

    fields = list(_mappable(lst).values())
    book = Workbook()
    data = book.active
    data.title = "Данные"
    data.append([_safe("Название")] + [_safe(field.name) for field in fields])
    hints = book.create_sheet("Подсказки")
    hints.append(["Поле", "Тип", "Обязательное", "Уникальное", "Значения", "Формат"])
    hints.append([_safe("Название"), "Строка", "Да", "Нет", "", ""])
    for field in fields:
        choices = ""
        if field.type == "choice":
            titles = [choice.title for choice in field.choices.filter(archived=False).order_by("order", "pk")]
            choices = _safe("; ".join(titles)) if titles else ""
        hints.append([_safe(field.name), Field.Type(field.type).label, "Да" if field.required else "Нет",
                      "Да" if field.unique else "Нет", choices, _TYPE_FORMAT.get(field.type, "")])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def sample_filename(lst) -> str:
    """Значение `filename*` заголовка ответа: «<список> — образец.xlsx» в процентной записи."""
    return quote(f"{lst.name} — образец.xlsx")
