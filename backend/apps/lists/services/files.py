"""Сервис: файлы записи поверх ядра (срез 006; PLAN-006, «Файлы записи»; CONTRACT-006, 5.7, 5.8, 12).

Проверки содержимого, запись в закрытый том и перенос после проверки антивирусом — в `core.services.uploads`; здесь —
правила записи списка: право, предел числа файлов, одиночное поле, строка `RecordFile`, событие истории и запись
`FilePurpose("lists")` для точки `file_purposes`. И прикрепление, и удаление идут под разделяемым замком списка
(`access.lock_list`), затем `SELECT … FOR UPDATE` записи. Версия записи не меняется (FR-517); журнал событий не
пишется. Право служба перепроверяет сама: нет права — `PermissionDenied`, список не читается — `Http404`.
"""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from apps.core.extensions import FilePurpose
from apps.core.models import StoredFile
from apps.core.services import files as core_files
from apps.core.services import uploads
from apps.lists.models import Field, Record, RecordFile
from apps.lists.services import access, history
from apps.lists.services.errors import ListsError, RecordArchived

PURPOSE = StoredFile.Purpose.LISTS.value
MAX_FILE = 20 * 1024 * 1024
MAX_FILES = 20
_REFUSALS = {"too_big": "file_too_big", "executable": "file_type_refused", "encrypted": "file_type_refused"}


def _require_edit(actor, lst):
    """Список не читается — `Http404`; читается, но не правится — `PermissionDenied`. Возвращает список."""
    current = access.get_list(actor, lst.pk)
    if not access.can_edit(actor, current):
        raise PermissionDenied("Нет права править записи списка")
    return current


def _locked_record(lst, number: int) -> Record:
    """Запись под `FOR UPDATE` после разделяемого замка списка: нет — `Http404`, в архиве — `RecordArchived`."""
    access.lock_list(lst.pk, shared=True)
    record = Record.objects.select_for_update().filter(list_id=lst.pk, number=number).first()
    if record is None:
        raise Http404("Запись не найдена")
    if record.archived:
        raise RecordArchived()
    return record


def _file_field(lst, code: str) -> Field:
    """Поле «файл» списка по коду. Пустой код и поле другого типа — `bad_file_field`; нет поля, чужое или скрытое — 404."""
    if not code:
        raise ListsError("bad_file_field", field="field")
    field = Field.objects.filter(list_id=lst.pk, code=code).first()
    if field is None or field.hidden:
        raise Http404("Поля нет")
    if field.type != Field.Type.FILE:
        raise ListsError("bad_file_field", field="field")
    return field


def attach(lst, number: int, *, field_code: str, name: str, data: bytes, actor) -> RecordFile:
    """Прикрепляет один файл к сохранённой записи: пределы и проверки содержимого, `StoredFile` и строка `RecordFile`.

    Отказ — `ListsError` с кодом `files_limit`, `field_has_file`, `file_too_big`, `file_type_refused` или `write_failed`
    (поле отказа `"file"`), `bad_file_field` (поле `"field"`); запись в архиве — `RecordArchived`. Транзакция при
    отказе откатывается, запись и диск целы."""
    current = _require_edit(actor, lst)
    with transaction.atomic():
        record = _locked_record(current, number)
        field = _file_field(current, field_code)
        if RecordFile.objects.filter(record=record).count() >= MAX_FILES:
            raise ListsError("files_limit", field="file")
        if not field.multiple and RecordFile.objects.filter(record=record, field=field).exists():
            raise ListsError("field_has_file", field="file")
        reason = uploads.reject_reason(name, data, len(data), MAX_FILE)
        if reason:
            raise ListsError(_REFUSALS[reason], field="file")
        try:
            stored = uploads.store(data, name, PURPOSE)
        except OSError:
            # Сбой записи файла — отказ с сообщением, не 500; исключение откатывает строки, диск `store` уже чист
            raise ListsError("write_failed", field="file") from None
        try:
            made = RecordFile.objects.create(record=record, field=field, file=stored, name=name, uploaded_by=actor)
            history.write(record, "file_added",
                          [{"field": field.code, "name": field.name, "before": "", "after": name}], actor)
        except Exception:
            # Файл на диске без строки (транзакция откатывается) не нужен
            core_files.remove_paths([core_files.attachment_path(stored)])
            raise
        return made


def remove(lst, number: int, file_id: int, *, actor) -> None:
    """Удаляет файл записи: строки `RecordFile` и `StoredFile` — в транзакции, файл с диска — после фиксации.

    `file_id` — `RecordFile.pk`; файл не этой записи — `Http404`; запись в архиве — `RecordArchived`."""
    current = _require_edit(actor, lst)
    with transaction.atomic():
        record = _locked_record(current, number)
        item = RecordFile.objects.select_related("file", "field").filter(pk=file_id, record=record).first()
        if item is None:
            raise Http404("Файла нет")
        stored = item.file
        path = core_files.attachment_path(stored)
        history.write(record, "file_removed",
                      [{"field": item.field.code, "name": item.field.name, "before": item.name, "after": ""}], actor)
        item.delete()
        stored.delete()
        transaction.on_commit(lambda: core_files.remove_paths([path]))


# --- итог проверки антивирусом (точка `file_purposes`) -------------------------------------------------

def still_waiting(stored) -> bool:
    """Файл ещё ждёт проверки: он `pending` и у него есть строка `RecordFile`."""
    return stored.status == StoredFile.Status.PENDING and RecordFile.objects.filter(file=stored).exists()


def clean(stored) -> list:
    """Итог «чисто»: файл в `attachments/<id>`, статус `clean`; возвращает прежние пути для стирания после фиксации."""
    return uploads.move(stored, StoredFile.Status.CLEAN)


def found(stored, signature: str) -> list:
    """Итог «найдено»: архив с паролем (`Heuristics.Encrypted.*`) — отказ (строки удаляются), иначе карантин."""
    if signature.startswith("Heuristics.Encrypted."):
        leftovers = [core_files.attachment_path(stored)]
        RecordFile.objects.filter(file=stored).delete()
        stored.delete()
        return leftovers
    return uploads.move(stored, StoredFile.Status.QUARANTINE, signature)


def file_purposes() -> list:
    """Описание назначения «файл записи списка» для точки `file_purposes` ядра."""
    return [FilePurpose(purpose=PURPOSE, still_waiting=still_waiting, clean=clean, found=found)]
