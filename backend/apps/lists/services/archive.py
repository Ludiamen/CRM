"""Сервис: архив записей и удаление навсегда (срез 006; FR-523, FR-524, FR-544).

«В архив», «Вернуть» и групповой архив — под разделяемым замком списка (`access.lock_list`, CONTRACT-006, 5.2), затем
`SELECT … FOR UPDATE` записи; журнал — `lists.record_archived`, `lists.record_restored` (в `after`), `lists.record_purged`
(в `before`): только список, номер и название, без значений полей. Право служба перепроверяет сама: нет права —
`PermissionDenied`, список не читается — `Http404`. Заданий очистки записей нет: архив бессрочен (FR-544)."""
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.core.models import StoredFile
from apps.core.services import audit
from apps.core.services import files as core_files
from apps.lists.models import Record, RecordFile
from apps.lists.services import access, history, links, vectors
from apps.lists.services.errors import ListsError

RECORD_TYPE = "lists.record"
BULK_LIMIT = 50


class BulkResult(NamedTuple):
    """Итог группового «В архив»: сколько записей перенесено и сколько пропущено."""

    archived: int
    skipped: int


# --- права ------------------------------------------------------------------------------------------------------

def _require_edit(actor, lst):
    """Список не читается — `Http404`; читается, но не правится — `PermissionDenied`. Возвращает список."""
    current = access.get_list(actor, lst.pk)
    if not access.can_edit(actor, current):
        raise PermissionDenied("Нет права править записи списка")
    return current


def _locked_record(lst, number: int) -> Record:
    """Запись под `FOR UPDATE` после разделяемого замка списка; нет записи — `Http404`."""
    access.lock_list(lst.pk, shared=True)
    record = Record.objects.select_for_update().filter(list_id=lst.pk, number=number).first()
    if record is None:
        raise Http404("Запись не найдена")
    return record


def _journal(action: str, record, lst, actor, *, side: str) -> None:
    data = {"list": lst.name, "number": record.number, "title": record.title}
    audit.record(action, actor=actor, object_type=RECORD_TYPE, object_id=record.pk, **{side: data})


# --- в архив и обратно ----------------------------------------------------------------------------------------

def _set_archived(lst, number: int, archived: bool, actor) -> tuple[Record, bool]:
    """Одна запись, одна транзакция: возвращает запись и признак «состояние изменено»."""
    with transaction.atomic():
        record = _locked_record(lst, number)
        if record.archived == archived:
            return record, False
        record.archived = archived
        record.archived_at = timezone.now() if archived else None
        record.archived_by = actor if archived else None
        record.save(update_fields=["archived", "archived_at", "archived_by"])
        vectors.refresh([record.pk])
        history.write(record, "archived" if archived else "restored", [], actor)
        _journal("lists.record_archived" if archived else "lists.record_restored", record, lst, actor,
                 side="after")
    return record, True


def archive(lst, number: int, *, actor) -> Record:
    """Переносит запись в архив: флаги, событие истории `archived`, вектор, журнал. Уже в архиве — без изменений."""
    current = _require_edit(actor, lst)
    return _set_archived(current, number, True, actor)[0]


def restore(lst, number: int, *, actor) -> Record:
    """Возвращает запись из архива (обратное к `archive`). Не в архиве — без изменений."""
    current = _require_edit(actor, lst)
    return _set_archived(current, number, False, actor)[0]


def bulk_archive(lst, numbers, *, actor) -> BulkResult:
    """Групповое «В архив» над отмеченными (FR-521): больше 50 номеров — `bulk_too_many` до любых изменений.

    Каждая запись — своя транзакция; пропускаются записи уже в архиве и удалённые навсегда."""
    current = _require_edit(actor, lst)
    numbers = list(numbers)
    if len(numbers) > BULK_LIMIT:
        raise ListsError("bulk_too_many")
    done = skipped = 0
    for number in dict.fromkeys(numbers):
        try:
            _, changed = _set_archived(current, number, True, actor)
        except Http404:
            changed = False
        if changed:
            done += 1
        else:
            skipped += 1
    return BulkResult(done, skipped)


# --- удалить навсегда -----------------------------------------------------------------------------------------

def _refusal(record, actor) -> ListsError | None:
    """Отказ `record_referenced`, если на запись ссылаются; ссылки — на записи читаемых управляющим списков."""
    found = links.referrers(record, actor)
    if not found.rows and not found.hidden:
        return None
    refs = [{"title": row.title, "number": row.number, "text": f"{row.title} — №{row.number}",
             "url": f"/lists/{row.list_id}/{row.number}/"} for row in found.rows]
    text = ", ".join(ref["text"] for ref in refs)
    if refs and found.hidden:
        text = f"{text} и ещё {found.hidden}"
    elif not refs:
        text = str(found.hidden)
    return ListsError("record_referenced", params={"links": text, "hidden": found.hidden, "refs": refs})


def purge(lst, number: int, *, actor) -> None:
    """Удаляет запись из архива навсегда (управляющий): отказ при ссылках, иначе одна транзакция — файлы, запись и её
    каскад, журнал; файлы с диска стираются после фиксации. Запись не в архиве — `PermissionDenied`."""
    current = access.get_list(actor, lst.pk)
    if not access.can_manage(actor):
        raise PermissionDenied("Нет права управлять списками")
    with transaction.atomic():
        record = _locked_record(current, number)
        if not record.archived:
            raise PermissionDenied("Удалить навсегда можно только запись в архиве")
        refusal = _refusal(record, actor)
        if refusal is not None:
            raise refusal
        attached = list(RecordFile.objects.filter(record=record).select_related("file"))
        paths = [core_files.attachment_path(item.file) for item in attached]
        stored_ids = [item.file_id for item in attached]
        RecordFile.objects.filter(record=record).delete()
        StoredFile.objects.filter(pk__in=stored_ids).delete()
        _journal("lists.record_purged", record, current, actor, side="before")
        record.delete()
        transaction.on_commit(lambda: core_files.remove_paths(paths))
