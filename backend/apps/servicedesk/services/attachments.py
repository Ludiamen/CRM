"""Публичный интерфейс сервис-деска: вложения заявок (PLAN-003, «Где живёт код»; CONTRACT-003, 6.18).

Единая функция приёма `accept` для трёх каналов (письмо, форма, ответ исполнителя), своя проверка
исполняемых файлов и архивов с паролем по заголовкам (без распаковки), итог проверки антивирусом
для точки `file_purposes` ядра и выдача файла и исходного письма. Файлы лежат в томе `protected`.
"""
import hashlib
import os
import re
import shutil
import struct
import uuid
import zipfile
from io import BytesIO
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.core import tasks as core_tasks
from apps.core.extensions import FilePurpose
from apps.core.models import StoredFile
from apps.core.services import audit, files

from ..models import Attachment, InboundMail, TicketEntry
from . import replies
from .errors import ServiceDeskError
from .mail_parse import Part, clean_filename

__all__ = ["Part", "Download", "MAX_FILE", "MAX_MAIL", "MAX_FILES", "MAX_TOTAL", "EXECUTABLE_EXTENSIONS"]

MAX_FILE = 20 * 1024 * 1024
MAX_MAIL = 50 * 1024 * 1024
MAX_FILES = 10
MAX_TOTAL = 50 * 1024 * 1024

EXECUTABLE_EXTENSIONS = ("exe", "com", "scr", "pif", "bat", "cmd", "msi", "msp", "vbs", "vbe", "js", "jse", "wsf",
                         "wsh", "ps1", "hta", "cpl", "jar", "lnk", "reg", "sh")

# Корневые записи контейнера OLE у установщика (MSI) и обновления (MSP); у старых `.doc`/`.xls` — другие
_MSI_CLSIDS = {uuid.UUID("000C1084-0000-0000-C000-000000000046").bytes_le,
               uuid.UUID("000C1086-0000-0000-C000-000000000046").bytes_le}
_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
_MACHO_THIN = {bytes.fromhex(h) for h in ("FEEDFACE", "FEEDFACF", "CEFAFEDE", "CFFAEDFE")}
_MACHO_FAT = {bytes.fromhex(h) for h in ("CAFEBABE", "BEBAFECA", "CAFEBABF", "BFBAFECA")}
# У универсального Mach-O после `CAFEBABE` стоит число архитектур (малое), у класса Java — версия (45 и больше)
_FAT_MAX_ARCHES = 30
_7Z_SIGNATURE = bytes.fromhex("377ABCAF271C")
_7Z_AES = bytes.fromhex("06F10701")
_RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
_RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
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


# --- исполняемые файлы --------------------------------------------------------------------------------

def _is_pe(data: bytes) -> bool:
    if data[:2] != b"MZ" or len(data) < 0x40:
        return False
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    return data[offset:offset + 4] == b"PE\0\0"


def _is_macho(data: bytes) -> bool:
    magic = data[:4]
    if magic in _MACHO_THIN:
        return True
    if magic in _MACHO_FAT and len(data) >= 8:
        return struct.unpack_from(">I", data, 4)[0] <= _FAT_MAX_ARCHES
    return False


def _ole_root_clsid(data: bytes) -> bytes | None:
    """CLSID корневой записи контейнера OLE или `None`, если это не OLE или заголовок обрезан."""
    if data[:8] != _OLE_MAGIC or len(data) < 0x200:
        return None
    shift = struct.unpack_from("<H", data, 0x1E)[0]
    sector = struct.unpack_from("<I", data, 0x30)[0]
    if shift > 16:
        return None
    start = (sector + 1) << shift
    chunk = data[start + 0x50:start + 0x60]
    return chunk if len(chunk) == 16 else None


def _zip_names(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            return archive.namelist()
    except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError):
        return []


def _last_extension(name: str) -> str:
    stem, dot, extension = (name or "").rpartition(".")
    return extension.lower() if dot and stem else ""


def is_executable(name: str, data: bytes) -> bool:
    """Исполняемый ли файл: по содержимому (PE, ELF, Mach-O, `#!`, MSI, JAR) или по последнему расширению."""
    if _last_extension(name) in EXECUTABLE_EXTENSIONS:
        return True
    head = data[:8]
    if data[:4] == b"\x7fELF" or data[:2] == b"#!" or _is_pe(data) or _is_macho(data):
        return True
    if head == _OLE_MAGIC:
        return _ole_root_clsid(data) in _MSI_CLSIDS
    if data[:2] == b"PK":
        return "META-INF/MANIFEST.MF" in _zip_names(data)
    return False


# --- архивы с паролем ---------------------------------------------------------------------------------

def _zip_encrypted(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            return any(item.flag_bits & 0x1 or item.compress_type == 99 for item in archive.infolist())
    except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError):
        return False


def _vint(data: bytes, pos: int):
    """Число RAR5 переменной длины: (значение, новая позиция) или `None` при обрыве."""
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            return None
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
    return None


def _rar5_encrypted(data: bytes) -> bool:
    """RAR5: блок шифрования архива (тип 4) или запись шифрования (тип 1) в дополнении заголовка файла."""
    pos = len(_RAR5_SIGNATURE)
    for _ in range(10000):
        pos += 4  # контрольная сумма заголовка
        parsed = _vint(data, pos)
        if parsed is None:
            return False
        size, body = parsed
        end = body + size
        if end > len(data):
            return False
        header = _vint(data, body)
        if header is None:
            return False
        htype, cursor = header
        flags = _vint(data, cursor)
        if flags is None:
            return False
        flags, cursor = flags
        extra = 0
        if flags & 0x1:
            parsed = _vint(data, cursor)
            if parsed is None:
                return False
            extra, cursor = parsed
        data_size = 0
        if flags & 0x2:
            parsed = _vint(data, cursor)
            if parsed is None:
                return False
            data_size, cursor = parsed
        if htype == 4:
            return True
        if htype in (2, 3) and extra and _rar5_extra_has_encryption(data, end - extra, end):
            return True
        if htype == 5:
            return False
        pos = end + data_size
    return False


def _rar5_extra_has_encryption(data: bytes, pos: int, end: int) -> bool:
    while pos < end:
        parsed = _vint(data, pos)
        if parsed is None:
            return False
        size, cursor = parsed
        kind = _vint(data, cursor)
        if kind is None:
            return False
        if kind[0] == 1:
            return True
        pos = cursor + size
    return False


def _rar4_encrypted(data: bytes) -> bool:
    """RAR4: флаг шифрования заголовков в главном заголовке (0x0080) или флаг пароля (0x0004) у файла."""
    pos = len(_RAR4_SIGNATURE)
    for _ in range(10000):
        if pos + 7 > len(data):
            return False
        htype, flags, size = struct.unpack_from("<BHH", data, pos + 2)
        if size < 7:
            return False
        if htype == 0x73 and flags & 0x0080:
            return True
        if htype in (0x74, 0x7A) and flags & 0x0004:
            return True
        if htype == 0x7B:
            return False
        add = 0
        if flags & 0x8000 and pos + 11 <= len(data):
            add = struct.unpack_from("<I", data, pos + 7)[0]
        pos += size + add
    return False


def _7z_encrypted(data: bytes) -> bool:
    """7z: кодек AES (`06F10701`) в простом заголовке или в описании сжатого блока заголовка.

    Заголовок, сжатый без пароля, не виден: его проверяет второй рубеж — clamd.
    """
    if len(data) < 32:
        return False
    offset, size = struct.unpack_from("<QQ", data, 12)
    header = data[32 + offset:32 + offset + size]
    index = header.find(_7Z_AES)
    while index != -1:
        # перед идентификатором кодека — байт флагов, младшие четыре бита которого — длина идентификатора (4)
        if index > 0 and header[index - 1] & 0x0F == 4:
            return True
        index = header.find(_7Z_AES, index + 1)
    return False


def is_encrypted_archive(data: bytes) -> bool:
    """Архив с паролем по заголовкам, без распаковки: ZIP, RAR4, RAR5, 7z."""
    try:
        if data[:2] == b"PK":
            return _zip_encrypted(data)
        if data.startswith(_RAR5_SIGNATURE):
            return _rar5_encrypted(data)
        if data.startswith(_RAR4_SIGNATURE):
            return _rar4_encrypted(data)
        if data.startswith(_7Z_SIGNATURE):
            return _7z_encrypted(data)
    except (struct.error, ValueError, IndexError):
        return False
    return False


def reason_of(name: str, data: bytes) -> str:
    """Значение `Attachment.Rejected` по содержимому и имени, без учёта размера: сначала исполняемый, затем архив."""
    if is_executable(name, data):
        return Attachment.Rejected.EXECUTABLE.value
    if is_encrypted_archive(data):
        return Attachment.Rejected.ENCRYPTED.value
    return ""


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
    """Копирует файл из `incoming/` в папку нового состояния; прежний путь возвращает для стирания после фиксации."""
    source = files.attachment_path(stored)
    stored.status = status
    stored.scanned_at = timezone.now()
    update = ["status", "scanned_at"]
    if signature:
        stored.signature = signature
        update.append("signature")
    target = files.attachment_path(stored)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    shutil.copyfile(source, temp)
    os.replace(temp, target)
    stored.save(update_fields=update)
    return [source]


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
