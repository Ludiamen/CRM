"""Публичный интерфейс сервис-деска: вложения заявок (PLAN-003, «Где живёт код»; CONTRACT-003, 6.18).

Единая функция приёма `accept` для трёх каналов (письмо, форма, ответ исполнителя), проверки
исполняемых файлов и архивов с паролем (живут в `core.services.uploads`, прежние имена реэкспортируются),
итог проверки антивирусом для точки `file_purposes` ядра и выдача файла и исходного письма. Файлы лежат в томе `protected`.
"""
import hashlib
import re
import uuid
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404

from apps.core import tasks as core_tasks
from apps.core.extensions import FilePurpose
from apps.core.models import StoredFile
from apps.core.services import audit, files, uploads
from apps.core.services.uploads import EXECUTABLE_EXTENSIONS, is_encrypted_archive, is_executable  # noqa: F401

from ..models import Attachment, InboundMail, TicketEntry
from . import replies
from .errors import ServiceDeskError
from .mail_parse import Part, clean_filename

__all__ = ["Part", "Download", "MAX_FILE", "MAX_MAIL", "MAX_FILES", "MAX_TOTAL", "EXECUTABLE_EXTENSIONS"]

MAX_FILE = 20 * 1024 * 1024
MAX_MAIL = 50 * 1024 * 1024
MAX_FILES = 10
MAX_TOTAL = 50 * 1024 * 1024
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

_PRECHECK_MESSAGES = {
    "too_many_files": "Файлов не больше 10",
    "total_too_big": "Файлы вместе не больше 50 МБ",
}


class Download(NamedTuple):
    """Что отдать браузеру: внутренний путь для nginx, имя файла и тип."""

    accel_path: str
    filename: str
    content_type: str


# --- входной файл формы -------------------------------------------------------------------------------

def from_upload(uploaded):
    """`Part` из загруженного файла формы: имя после `clean_filename`, байты, тип из загрузки."""
    data = uploaded.read()
    content_type = getattr(uploaded, "content_type", "") or "application/octet-stream"
    return Part(name=clean_filename(getattr(uploaded, "name", ""), 1), data=data, content_type=content_type)


_CORE_REASONS = {"": "", "executable": Attachment.Rejected.EXECUTABLE.value,
                 "encrypted": Attachment.Rejected.ENCRYPTED.value}


def reason_of(name: str, data: bytes) -> str:
    """Значение `Attachment.Rejected` по содержимому и имени, без учёта размера: коды ядра переведены в свои."""
    return _CORE_REASONS[uploads.reject_reason(name, data, 0, 0)]


# --- приём --------------------------------------------------------------------------------------------

def _refuse_file(name: str, reason: str) -> ServiceDeskError:
    return ServiceDeskError("file_rejected", f"файл «{name}» не принят: {Attachment.REJECT_TITLES[reason]}")


def precheck(parts) -> None:
    """Проверка без базы до записи чего-либо: число, сумма, затем каждый файл (размер, исполняемый, пароль)."""
    parts = list(parts)
    if len(parts) > MAX_FILES:
        raise ServiceDeskError("too_many_files", _PRECHECK_MESSAGES["too_many_files"])
    if sum(len(part.data) for part in parts) > MAX_TOTAL:
        raise ServiceDeskError("total_too_big", _PRECHECK_MESSAGES["total_too_big"])
    for part in parts:
        if len(part.data) > MAX_FILE:
            raise _refuse_file(part.name, "too_big")
        reason = reason_of(part.name, part.data)
        if reason:
            raise _refuse_file(part.name, reason)


def _content_type(value: str) -> str:
    """Тип содержимого без управляющих знаков, первые 255 знаков (пустой — `application/octet-stream`)."""
    return _CONTROL_RE.sub("", value or "")[:255] or "application/octet-stream"


def accept(entry, parts, *, strict: bool = True, mail_size: int | None = None) -> list:
    """Принимает файлы к элементу ленты; возвращает `Attachment` в порядке `parts`, в том числе не принятые.

    `strict=True` (форма, ответ, заявка от исполнителя): сначала `precheck`, отказ — до записи файлов.
    `strict=False` (письмо): не принятые остаются перечнем, заявка создаётся. Зовётся в транзакции зовущего;
    проверка принятых файлов ставится после её фиксации.
    """
    parts = list(parts)
    if strict:
        precheck(parts)
    ticket = entry.ticket
    letter_too_big = mail_size is not None and mail_size > MAX_MAIL
    written = []
    result = []
    try:
        with transaction.atomic():
            for part in parts:
                size = len(part.data)
                if letter_too_big:
                    reason = Attachment.Rejected.MAIL_TOO_BIG.value
                elif size > MAX_FILE:
                    reason = Attachment.Rejected.TOO_BIG.value
                else:
                    reason = reason_of(part.name, part.data)
                stored = None
                if not reason:
                    stored = StoredFile.objects.create(
                        purpose=StoredFile.Purpose.ATTACHMENT, owner=None, size=size,
                        sha256=hashlib.sha256(part.data).hexdigest(), content_type=_content_type(part.content_type))
                    path = files.attachment_path(stored)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(part.data)
                    written.append(path)
                    core_tasks.enqueue_scan(stored.pk)
                result.append(Attachment.objects.create(
                    ticket=ticket, entry=entry, file=stored, name=part.name, size=size, inline=part.inline,
                    rejected=reason))
    except Exception:
        # Записанные файлы без строк базы не нужны
        files.remove_paths(written)
        raise
    return result


def rejected_of(ticket_or_entry) -> list:
    """Не принятые вложения заявки или элемента ленты (по `id`), для карточки и подтверждения."""
    field = "entry" if isinstance(ticket_or_entry, TicketEntry) else "ticket"
    return list(Attachment.objects.filter(**{field: ticket_or_entry}).exclude(rejected="").order_by("id"))


def pending_for(entry) -> bool:
    """Есть ли у элемента вложение, чей файл ещё ждёт проверки."""
    return Attachment.objects.filter(entry=entry, file__status=StoredFile.Status.PENDING).exists()


# --- итог проверки антивирусом (точка `file_purposes`) -------------------------------------------------

def file_purposes() -> list:
    """Описание назначения «вложение» для точки `file_purposes` ядра."""
    return [FilePurpose(purpose=StoredFile.Purpose.ATTACHMENT.value, still_waiting=still_waiting, clean=on_clean,
                        found=on_found)]


def still_waiting(stored) -> bool:
    """Файл ещё ждёт проверки: он `pending` и у него есть строка `Attachment`."""
    return stored.status == StoredFile.Status.PENDING and Attachment.objects.filter(file=stored).exists()


def _move(stored, status: str, signature: str = "") -> list:
    """Перенос файла после проверки — `uploads.move`; прежний путь возвращает для стирания после фиксации."""
    return uploads.move(stored, status, signature)


def _notify_reply_entries(entries) -> None:
    """Для ответов, у которых не осталось ждущих файлов, зовёт `replies.on_files_checked`."""
    seen = set()
    for entry in entries:
        if entry.pk in seen or entry.kind != TicketEntry.Kind.REPLY:
            continue
        seen.add(entry.pk)
        if not pending_for(entry):
            replies.on_files_checked(entry.pk)


def on_clean(stored) -> list:
    """Итог «чисто»: файл в `attachments/<id>`, статус `clean`, `scanned_at`; затем проверка ответа исполнителя."""
    leftovers = _move(stored, StoredFile.Status.CLEAN)
    _notify_reply_entries([a.entry for a in Attachment.objects.filter(file=stored).select_related("entry")])
    return leftovers


def on_found(stored, signature: str) -> list:
    """Итог «найдено»: архив с паролем (`Heuristics.Encrypted.*`) — отказ вложения, иначе карантин."""
    items = list(Attachment.objects.filter(file=stored).select_related("ticket", "entry"))
    if signature.startswith("Heuristics.Encrypted."):
        leftovers = [files.attachment_path(stored)]
        for item in items:
            replies.add_event(item.ticket, "attachment_rejected", data={"name": item.name, "reason": "encrypted"})
        Attachment.objects.filter(file=stored).update(file=None, rejected=Attachment.Rejected.ENCRYPTED.value)
        stored.delete()
    else:
        leftovers = _move(stored, StoredFile.Status.QUARANTINE, signature)
        for item in items:
            replies.add_event(item.ticket, "attachment_quarantined", data={"name": item.name})
            audit.record("ticket.attachment_quarantined", actor=None, object_type="ticket",
                         object_id=item.ticket.number, after={"file_id": str(stored.pk), "signature": signature})
    _notify_reply_entries([item.entry for item in items])
    return leftovers


# --- выдача -------------------------------------------------------------------------------------------

def download(user, number, file_id) -> Download:
    """Файл вложения заявки, видимой смотрящему: только чистый; иначе `Http404`."""
    from . import tickets  # внутри функции: `tickets` сам зовёт вложения

    ticket = tickets.get_for(user, number)
    try:
        file_id = uuid.UUID(str(file_id))
    except (ValueError, ValidationError):
        raise Http404
    item = (Attachment.objects.filter(ticket=ticket, file_id=file_id, file__status=StoredFile.Status.CLEAN)
            .order_by("id").first())
    if item is None:
        raise Http404
    return Download(f"/protected/attachments/{file_id}", item.name, "application/octet-stream")


def source_mail(user, number, inbound_id) -> Download:
    """Исходное письмо `.eml`: письмо этой заявки, файл не стёрт, все вложения чистые и ни одно не отклонено."""
    from . import tickets

    ticket = tickets.get_for(user, number)
    inbound = InboundMail.objects.filter(pk=inbound_id, ticket=ticket).first()
    if inbound is None or inbound.raw_deleted:
        raise Http404
    for item in Attachment.objects.filter(entry__inbound=inbound).select_related("file"):
        if item.rejected or item.file is None or item.file.status != StoredFile.Status.CLEAN:
            raise Http404
    return Download(f"/protected/inbound/{inbound.pk}.eml", f"mail-{inbound.pk}.eml", "application/octet-stream")
