"""Сервис ленты: эскизы картинок (T-7227; PLAN-007, «Файлы и эскизы» → «Эскиз»).

Эскиз строится после «чистого» итога проверки: один файл не больше 1280 px по большей
стороне, JPEG (у PNG с прозрачностью — WebP), без EXIF (`exif_transpose` до сохранения),
у GIF — первый кадр; большой JPEG уменьшается уже при декодировании (`Image.draft`).
Путь — `PROTECTED_ROOT/attachments/thumbs/<id StoredFile>.jpg|webp`, запись через
временный файл. Файл не картинка — пустая строка без файла; сбой построения
(повреждённая картинка, нехватка памяти, диск) поднимает исключение наверх — его ловит
обработчик `clean` назначения `feed` отдельно от переноса файла (CONTRACT-007, 5.5, 5.7).
"""
import logging
import pathlib

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

__all__ = ["MAX_SIDE", "build"]

logger = logging.getLogger(__name__)

MAX_SIDE = 1280
JPEG_QUALITY = 85
# разбор только разрешённых форматов (как в core.services.uploads.detect_image)
_FORMATS = ("JPEG", "PNG", "GIF", "WEBP")
# заголовок не читается или формат не опознан — файл не картинка, не сбой
_NOT_IMAGE = (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError)


def _has_alpha(image) -> bool:
    """Есть ли прозрачность: режим с альфа-каналом или палитра с прозрачным индексом."""
    if image.mode in ("RGBA", "LA", "PA"):
        return True
    return image.mode == "P" and "transparency" in image.info


def build(source_path, stored_id) -> str:
    """Построить эскиз исходника; вернуть путь относительно `PROTECTED_ROOT` или `""`.

    `attachments/thumbs/<stored_id>.jpg` (WebP — у картинки с прозрачностью). Не картинка —
    `""` и файла нет. Повреждённая картинка и прочие сбои построения — исключение наверх:
    его ловит обработчик `clean` отдельно от переноса, файл остаётся «чистым» без эскиза.
    """
    root = pathlib.Path(settings.PROTECTED_ROOT)
    try:
        opened = Image.open(source_path, formats=_FORMATS)
    except _NOT_IMAGE:
        return ""
    with opened:
        if opened.format not in _FORMATS:
            return ""
        # JPEG уменьшается уже при декодировании: эскиз тогда строится дешевле (план, F3 Ф24)
        opened.draft("RGB", (MAX_SIDE, MAX_SIDE))
        image = ImageOps.exif_transpose(opened)
        alpha = _has_alpha(image)
        image = image.convert("RGBA" if alpha else "RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        target = root / "attachments" / "thumbs" / f"{stored_id}{'.webp' if alpha else '.jpg'}"
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp")
        image.save(temp, "WEBP" if alpha else "JPEG", quality=JPEG_QUALITY)
        temp.replace(target)
    return target.relative_to(root).as_posix()
