"""Выдача файла из закрытого тома через nginx (PLAN-005, «Вложения и картинки»; CONTRACT-005, 3.5).

Ответ с пустым телом и заголовком `X-Accel-Redirect`: файл отдаёт nginx из `location /protected/attachments/`.
Обе выдачи с `nosniff` и `Cache-Control: no-store`. Права и состояние файла (чистый) проверяет зовущий.
"""
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponse

from apps.core.models import StoredFile
from apps.core.services import files

IMAGE_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def _response(stored: StoredFile, content_type: str) -> HttpResponse:
    response = HttpResponse(b"", content_type=content_type)
    # Путь — по состоянию файла под томом `protected` (`attachments/<id>` у чистого)
    relative = files.attachment_path(stored).relative_to(settings.PROTECTED_ROOT)
    response["X-Accel-Redirect"] = f"/protected/{relative.as_posix()}"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


def download(stored: StoredFile, filename: str) -> HttpResponse:
    """Скачивание: `attachment` с именем в `filename*=UTF-8''…`, тип `application/octet-stream`."""
    response = _response(stored, "application/octet-stream")
    response["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(filename, safe="")
    return response


def inline_image(stored: StoredFile, image_format: str) -> HttpResponse:
    """Показ картинки: тип из `image_format` (`png`, `jpeg`, `gif`, `webp`), без `Content-Disposition`."""
    return _response(stored, IMAGE_TYPES[image_format])
