"""Проверки загрузки файлов в ядре (PLAN-005, «Вложения и картинки; проверки файлов в ядре»; CONTRACT-005, 3.5).

Исполняемые файлы и архивы с паролем по заголовкам (без распаковки), формат картинки по содержимому,
приём файла в закрытый том (`store`) и перенос после проверки антивирусом (`move`). Части без моделей
сервис-деска, перенесённые из `servicedesk/services/attachments.py`: заявки и статьи используют одни проверки.
"""
import hashlib
import os
import re
import shutil
import struct
import uuid
import zipfile
from io import BytesIO

from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.core import tasks as core_tasks
from apps.core.models import StoredFile

from . import files

__all__ = ["EXECUTABLE_EXTENSIONS", "ImageTooLarge", "is_executable", "is_encrypted_archive", "reject_reason",
           "detect_image", "store", "move", "write_file"]

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


# --- причина отказа -----------------------------------------------------------------------------------

def reject_reason(name: str, data: bytes, size: int, max_file: int) -> str:
    """`"too_big"`, `"executable"`, `"encrypted"` или `""` (чисто); порядок: размер, исполняемый, архив с паролем.

    Размер ровно `max_file` принимается; `max_file` передаёт вызывающий (20 МБ у статей, `MAX_FILE` у заявок).
    """
    if size > max_file:
        return "too_big"
    if is_executable(name, data):
        return "executable"
    if is_encrypted_archive(data):
        return "encrypted"
    return ""


# --- картинки -----------------------------------------------------------------------------------------

class ImageTooLarge(Exception):
    """Картинка с числом точек больше предела (или «бомба» Pillow): отказ загрузки, не ошибка сервера."""


_IMAGE_FORMATS = {"PNG": "png", "JPEG": "jpeg", "GIF": "gif", "WEBP": "webp"}


def detect_image(data: bytes) -> str:
    """Формат картинки по содержимому: `png`, `jpeg`, `gif`, `webp`; не картинка (в том числе повреждённая) — `""`.

    Число точек больше `files.MAX_PHOTO_PIXELS` и `Image.DecompressionBombError` — `ImageTooLarge`.
    """
    try:
        with Image.open(BytesIO(data)) as image:
            fmt, (width, height) = image.format, image.size
            if fmt not in _IMAGE_FORMATS:
                return ""
            if width * height > files.MAX_PHOTO_PIXELS:
                raise ImageTooLarge
            image.verify()
    except ImageTooLarge:
        raise
    except Image.DecompressionBombError:
        raise ImageTooLarge from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        return ""
    return _IMAGE_FORMATS[fmt]


# --- запись и перенос ---------------------------------------------------------------------------------

def write_file(path, data: bytes) -> None:
    """Пишет файл на диск, создавая каталог. Единственная точка записи `store` (её подменяют тесты сбоя диска)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def store(data: bytes, name: str, purpose: str) -> StoredFile:
    """Строка `StoredFile` (`owner` пусто, `pending`) и файл в `incoming/<id>`; проверка антивирусом — после фиксации.

    Зовётся в транзакции зовущего. Тип содержимого — `image/<формат>` по содержимому, иначе `application/octet-stream`.
    Сбой записи — исключение; файл без строки (откат) зовущий стирает сам, строка при этом откатывается.
    """
    image_format = detect_image(data)
    stored = StoredFile.objects.create(
        purpose=purpose, owner=None, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        content_type=f"image/{image_format}" if image_format else "application/octet-stream")
    write_file(files.attachment_path(stored), data)
    core_tasks.enqueue_scan(stored.pk)
    return stored


def move(stored: StoredFile, status: str, signature: str = "") -> list:
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
