"""Название и логотип портала (T-223, FR-048, FR-049, NFR-010).

Логотип — только PNG или JPEG, до 1 МБ и до 512×512 px; формат определяется по
содержимому (Pillow), а не по имени файла. SVG не принимается: в нём можно
исполнить скрипт. Файл хранится под сгенерированным именем с расширением по
формату; из `/media/` он отдаётся с `nosniff` и выводится только через `<img>`.
"""
import io
import secrets
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.core.models import PortalSettings

from . import audit

DEFAULT_NAME = "Портал ИТ-отдела"
MAX_NAME_LENGTH = 100
MAX_LOGO_BYTES = 1024 * 1024
MAX_LOGO_SIDE = 512
FORMATS = {"PNG": "png", "JPEG": "jpg"}


class PortalSettingsError(Exception):
    """Ошибки формы: {поле: сообщение}."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def get() -> PortalSettings:
    """Единственная строка настроек (создаётся миграцией)."""
    return PortalSettings.objects.get()


def _check_logo(data: bytes) -> str:
    """Проверяет содержимое логотипа; возвращает расширение файла или бросает ValueError с объяснением."""
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Логотип больше 1 МБ: уменьшите размер файла.")
    try:
        # разбор только разрешёнными форматами (проверка безопасности 2026-10-23)
        with Image.open(io.BytesIO(data), formats=tuple(FORMATS)) as image:
            fmt, (width, height) = image.format, image.size
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ValueError("Логотип должен быть изображением PNG или JPEG.") from None
    if fmt not in FORMATS:
        raise ValueError("Логотип должен быть изображением PNG или JPEG.")
    if width > MAX_LOGO_SIDE or height > MAX_LOGO_SIDE:
        raise ValueError(f"Размер логотипа {width}×{height} px: допустимо не больше {MAX_LOGO_SIDE}×{MAX_LOGO_SIDE} px.")
    return FORMATS[fmt]


def _logo_state(row: PortalSettings) -> str:
    return "задан" if row.logo else "по умолчанию"


def update(*, name: str | None = None, logo=None, reset: bool = False, actor, ip=None) -> PortalSettings:
    """Меняет название и/или логотип; «Вернуть по умолчанию» — `reset=True`.

    `logo` — загруженный файл (с `.read()`). Ошибки — `PortalSettingsError`, ничего не меняя.
    """
    errors, extension, data = {}, "", b""
    if not reset:
        if name is not None:
            name = name.strip()
            if not name:
                errors["name"] = "Название портала не может быть пустым."
            elif len(name) > MAX_NAME_LENGTH:
                errors["name"] = f"Название портала: не больше {MAX_NAME_LENGTH} символов."
        if logo:
            data = logo.read(MAX_LOGO_BYTES + 1)
            try:
                extension = _check_logo(data)
            except ValueError as e:
                errors["logo"] = str(e)
    if errors:
        raise PortalSettingsError(errors)
    with transaction.atomic():
        row = PortalSettings.objects.select_for_update().get()
        before = {"name": row.name, "logo": _logo_state(row)}
        old_logo = row.logo.name if row.logo else ""
        if reset:
            row.name, row.logo = DEFAULT_NAME, ""
            logo_note = "сброшен" if old_logo else "по умолчанию"
        else:
            if name is not None:
                row.name = name
            logo_note = _logo_state(row)
            if data:
                row.logo.save(f"logo-{secrets.token_hex(8)}.{extension}", ContentFile(data), save=False)
                logo_note = "заменён"
        changed = row.name != before["name"] or logo_note in ("заменён", "сброшен")
        row.updated_at = timezone.now()
        row.save()
        if changed:
            audit.record("portal_settings.updated", actor=actor, object_type="portal_settings", object_id=row.pk,
                         before=before, after={"name": row.name, "logo": logo_note}, ip=ip)
    if old_logo and (reset or data):
        row.logo.storage.delete(old_logo)
    return row
