"""Файлы ядра: путь фото сотрудника (T-2216, FR-132, NFR-105, NFR-108; CONTRACT-002 § 3, ADR-0007).

Загрузка проверяется Pillow по содержимому и ложится в `incoming/`; антивирус и перекодирование делает
задание `core.tasks.scan_file`. Чистое фото хранится в `photos/<id>-512.jpg` и `-96.jpg`, найденное —
в `quarantine/<id>`. Всё под `settings.PROTECTED_ROOT`; в журнал событий путь и содержимое не попадают.
"""
import hashlib
import io
import logging
import os
import pathlib

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.core.models import StoredFile, User

from . import audit

logger = logging.getLogger(__name__)

QUEUE = "files"
# Повторы проверки при недоступном антивирусе: около суток (план, «Путь фото»)
RETRY_MAX = 24
RETRY_INTERVALS = [60, 300, 900] + [3600] * 21

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000
SIZES = (512, 96)
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
JPEG_QUALITY = 85

MESSAGES = {
    "bad_format": "Фото должно быть изображением PNG или JPEG.",
    "too_big": "Фото больше 5 МБ: уменьшите размер файла.",
    "too_many_pixels": "В фото больше 40 млн точек: уменьшите разрешение.",
}


class PhotoError(Exception):
    """Загрузка фото отклонена; `code` — `bad_format`, `too_big` или `too_many_pixels`."""

    def __init__(self, code: str):
        super().__init__(MESSAGES[code])
        self.code = code


# --- пути и адреса -----------------------------------------------------------------------------

def photo_path(stored: StoredFile, size: int | None = None) -> pathlib.Path:
    """Путь файла под `PROTECTED_ROOT`: по размеру (512 или 96) или, без размера, по состоянию проверки."""
    root = pathlib.Path(settings.PROTECTED_ROOT)
    if size is not None:
        if size not in SIZES:
            raise ValueError(f"размер фото: 512 или 96, получено {size}")
        return root / "photos" / f"{stored.pk}-{size}.jpg"
    if stored.status == StoredFile.Status.PENDING:
        return root / "incoming" / str(stored.pk)
    if stored.status == StoredFile.Status.QUARANTINE:
        return root / "quarantine" / str(stored.pk)
    raise ValueError("у чистого файла путь зависит от размера")


def photo_url(user: User, size: int) -> str | None:
    """Адрес чистого `photo` сотрудника (номер файла в адресе меняется вместе с фото) или `None`."""
    if size not in SIZES:
        raise ValueError(f"размер фото: 512 или 96, получено {size}")
    stored = user.photo
    if stored is None or stored.status != StoredFile.Status.CLEAN:
        return None
    return f"/staff/{user.pk}/photo/{stored.pk}/{size}/"


def _clean_paths(stored: StoredFile) -> list[pathlib.Path]:
    return [photo_path(stored, size) for size in SIZES]


def remove_paths(paths) -> None:
    """Стирает файлы с диска; отсутствующий файл не ошибка."""
    for path in paths:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _stored_paths(stored: StoredFile) -> list[pathlib.Path]:
    """Файлы записи на диске, кроме файла в карантине."""
    if stored.status == StoredFile.Status.CLEAN:
        return _clean_paths(stored)
    if stored.status == StoredFile.Status.PENDING:
        return [photo_path(stored)]
    return []


# --- загрузка ----------------------------------------------------------------------------------

def _check(data: bytes) -> str:
    """Проверяет содержимое; возвращает `content_type` или бросает `PhotoError`."""
    if len(data) > MAX_PHOTO_BYTES:
        raise PhotoError("too_big")
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt, (width, height) = image.format, image.size
            if fmt in FORMATS and width * height > MAX_PHOTO_PIXELS:
                raise PhotoError("too_many_pixels")
            if fmt in FORMATS:
                image.verify()
    except PhotoError:
        raise
    except Image.DecompressionBombError:
        raise PhotoError("too_many_pixels") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        raise PhotoError("bad_format") from None
    if fmt not in FORMATS:
        raise PhotoError("bad_format")
    return FORMATS[fmt]


def upload_photo(user: User, uploaded, *, actor, ip=None) -> StoredFile:
    """Принимает фото: проверка Pillow, `StoredFile(pending)` и `photo_pending`; проверка — заданием после фиксации.

    Прежний ожидающий файл удаляется (с диска и из `StoredFile`), файл в карантине остаётся.
    """
    from apps.core import tasks

    data = uploaded.read(MAX_PHOTO_BYTES + 1)
    content_type = _check(data)
    with transaction.atomic():
        owner = User.objects.select_for_update().get(pk=user.pk)
        previous = owner.photo_pending
        stored = StoredFile.objects.create(
            purpose=StoredFile.Purpose.PHOTO, owner=owner, size=len(data),
            sha256=hashlib.sha256(data).hexdigest(), content_type=content_type)
        path = photo_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        User.objects.filter(pk=owner.pk).update(photo_pending=stored)
        user.photo_pending = stored
        user.photo_pending_id = stored.pk
        if previous is not None and previous.status == StoredFile.Status.PENDING:
            remove_paths(_stored_paths(previous))
            previous.delete()
        audit.record("photo.uploaded", actor=actor, object_type="user", object_id=user.pk,
                     after={"file_id": str(stored.pk), "size": stored.size, "content_type": content_type}, ip=ip)
        tasks.enqueue_scan(stored.pk)
    return stored


# --- итог проверки (зовёт задание под блокировкой) ----------------------------------------------

def _encode(source: pathlib.Path, target: StoredFile) -> None:
    """Перекодирует исходник в два JPEG: вписан в квадрат, без EXIF, с поворотом, белый фон вместо прозрачного."""
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode in ("RGBA", "LA", "P", "PA"):
            image = image.convert("RGBA")
            ground = Image.new("RGBA", image.size, (255, 255, 255, 255))
            ground.alpha_composite(image)
            image = ground
        image = image.convert("RGB")
        photos = pathlib.Path(settings.PROTECTED_ROOT) / "photos"
        photos.mkdir(parents=True, exist_ok=True)
        for size in SIZES:
            variant = image.copy()
            variant.thumbnail((size, size), Image.Resampling.LANCZOS)
            final = photo_path(target, size)
            temp = final.with_name(final.name + ".tmp")
            variant.save(temp, "JPEG", quality=JPEG_QUALITY)
            os.replace(temp, final)


def finish_clean(stored: StoredFile, owner: User) -> list[pathlib.Path]:
    """Итог «чисто»: два JPEG, `photo` переключается, прежнее фото удаляется. Возвращает файлы для стирания."""
    source = photo_path(stored)
    try:
        _encode(source, stored)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError, Image.DecompressionBombError):
        logger.warning("photo: файл %s не перекодирован, в карантин", stored.pk)
        remove_paths(_clean_paths(stored))
        finish_quarantine(stored, owner, "image-decode-error")
        return []
    previous = owner.photo
    stored.status = StoredFile.Status.CLEAN
    stored.content_type = "image/jpeg"
    stored.scanned_at = timezone.now()
    stored.save(update_fields=["status", "content_type", "scanned_at"])
    User.objects.filter(pk=owner.pk).update(photo=stored, photo_pending=None)
    leftovers = [source]
    if previous is not None and previous.pk != stored.pk:
        leftovers += _stored_paths(previous)
        previous.delete()
    audit.record("photo.checked", actor=None, object_type="user", object_id=owner.pk,
                 after={"file_id": str(stored.pk), "result": "clean"})
    return leftovers


def finish_quarantine(stored: StoredFile, owner: User, signature: str) -> None:
    """Итог «найдено»: файл переносится в `quarantine/`, сигнатура — в запись и журнал; `photo` не меняется."""
    source = photo_path(stored)
    stored.status = StoredFile.Status.QUARANTINE
    stored.signature = signature
    stored.scanned_at = timezone.now()
    target = photo_path(stored)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        os.replace(source, target)
    stored.save(update_fields=["status", "signature", "scanned_at"])
    logger.info("photo: файл %s в карантине, сигнатура %s", stored.pk, signature)
    audit.record("photo.checked", actor=None, object_type="user", object_id=owner.pk,
                 after={"file_id": str(stored.pk), "result": "quarantine", "signature": signature})


# --- удаление ----------------------------------------------------------------------------------

def delete_photo(user: User, *, actor, ip=None) -> None:
    """Удаляет `photo` и `photo_pending` с файлами, кроме файла в карантине; без фото — тихо ничего."""
    with transaction.atomic():
        owner = User.objects.select_for_update().get(pk=user.pk)
        rows = [row for row in (owner.photo, owner.photo_pending) if row is not None]
        if not rows:
            return
        User.objects.filter(pk=owner.pk).update(photo=None, photo_pending=None)
        user.photo = user.photo_pending = None
        removable = [row for row in rows if row.status != StoredFile.Status.QUARANTINE]
        paths = [path for row in removable for path in _stored_paths(row)]
        ids = [str(row.pk) for row in removable]
        for row in removable:
            row.delete()
        if ids:
            audit.record("photo.deleted", actor=actor, object_type="user", object_id=user.pk,
                         before={"files": ids}, ip=ip)
    remove_paths(paths)
