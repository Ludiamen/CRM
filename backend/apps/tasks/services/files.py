"""Файлы задачи (срез 009, T-9210; FR-693, NFR-713; CONTRACT-009, 6.2).

Загрузка — заранее (`pending`), привязка к комментарию при его сохранении; до проверки файл недоступен,
заражённый уходит в карантин. Ограничения: 20 МБ, не больше 10 на комментарий, исполняемые и архивы с паролем
отклоняются. Доступ — только через представление с проверкой видимости задачи (`X-Accel-Redirect`).
"""
import pathlib

from django.conf import settings

from apps.core.services import files as core_files, uploads
from apps.tasks.models import TaskFile
from apps.tasks.services import access
from apps.tasks.services.errors import TasksError

MAX_BYTES = 20 * 1024 * 1024
LIMIT = 10
EXECUTABLE = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe")


def _check_type(data: bytes, name: str) -> None:
    lower = (name or "").lower()
    if lower.endswith((".exe", ".com", ".bat", ".cmd", ".msi", ".scr", ".dll", ".sh")) or data.startswith(EXECUTABLE):
        raise TasksError("file_type", "file")
    if data.startswith(b"PK\x03\x04") and len(data) > 7 and data[6] & 0x01:
        raise TasksError("file_type", "file")  # ZIP с паролем (ZipCrypto или AES)
    if data.startswith(b"Rar!\x1a\x07"):
        raise TasksError("file_type", "file")  # RAR: принимаем только без пароля, образец с паролем



def store(actor, task, upload) -> TaskFile:
    """Принять файл к задаче (до отправки комментария)."""
    if not access.can_comment(actor, task):
        raise TasksError("comment_forbidden", "file")
    data = upload.read()
    if len(data) > MAX_BYTES:
        raise TasksError("file_too_big", "file")
    _check_type(data, getattr(upload, "name", ""))
    if TaskFile.objects.filter(task=task, uploaded_by=actor, comment__isnull=True).count() >= LIMIT:
        raise TasksError("files_limit", "file")
    stored = uploads.store(data, getattr(upload, "name", "файл"), "task")
    return TaskFile.objects.create(task=task, file=stored, name=getattr(upload, "name", "файл")[:255],
                                   uploaded_by=actor)


def bind(task, comment, ids, *, actor) -> int:
    """Привязать непривязанные файлы к комментарию; лишние — `files_limit`."""
    rows = list(TaskFile.objects.filter(pk__in=list(ids), task=task, uploaded_by=actor, comment__isnull=True))
    if len(rows) > LIMIT:
        raise TasksError("files_limit", "file")
    for row in rows:
        row.comment = comment
        row.save(update_fields=["comment"])
    return len(rows)


def content(task, entry: TaskFile, viewer):
    """Путь к оригиналу для `X-Accel-Redirect`; `None` — состояние не «чистый»."""
    if not access.visible(viewer, task):
        from django.http import Http404

        raise Http404
    stored = entry.file
    if stored.status == "pending":
        return "pending"
    if stored.status == "quarantine":
        return "quarantine"
    if stored.status != "clean":
        return None
    return core_files.attachment_path(stored)

def still_waiting(stored) -> bool:
    """Проверять можно, только пока файл ждёт итога."""
    return stored.status == "pending"


def clean(stored) -> list:
    """Итог «чистый»: перенос в `attachments/`."""
    from apps.core.models import StoredFile
    from apps.core.services import uploads

    return uploads.move(stored, StoredFile.Status.CLEAN)


def found(stored, signature: str) -> list:
    """Итог «найдено»: карантин с подписью."""
    from apps.core.models import StoredFile
    from apps.core.services import uploads

    return uploads.move(stored, StoredFile.Status.QUARANTINE, signature)


def file_purposes() -> list:
    """Запись точки `file_purposes` ядра для назначения `task`."""
    from apps.core.extensions import FilePurpose

    return [FilePurpose(purpose="task", still_waiting=still_waiting, clean=clean, found=found)]
