"""Загрузка файла, привязка и «убрать» (срез 008, T-8215; CONTRACT-008, 5.4, 10.2, 12.5).

PLAN-008 «Файлы и эскизы». Загрузка — по одному, до 20 МБ, исполняемые файлы и архивы с паролем отклоняются,
картинка больше 40 Мп — тот же отказ типа; не больше 10 файлов к сообщению (считая уже прикреплённые и присланные
в `have`) и не больше 30 непривязанных у сотрудника. Строка `StoredFile` назначения `messenger` создаётся
«проверяется», файл — в `incoming/`; строка `MessageAttachment` пока без сообщения. Привязка — условный `UPDATE`
с проверкой числа строк: меньше присланного — откат и «Файл не найден». «Убрать» — только свой непривязанный:
строки в транзакции, диск после фиксации.
"""
import pathlib

from django.conf import settings as django_settings
from django.http import Http404
from django.db import transaction
from django.utils import timezone

from apps.core.models import StoredFile
from apps.core.services import thumbs, uploads
from apps.messenger.models import MessageAttachment
from apps.messenger.services.errors import MessengerError

PURPOSE = "messenger"
MAX_FILE = 20 * 1024 * 1024
MAX_FILES = 10
MAX_UNBOUND = 30
_REFUSALS = {"too_big": "file_too_big", "executable": "file_type", "encrypted": "file_type"}


def upload(user, uploaded, chat, have=()) -> MessageAttachment:
    """Загрузить один файл заранее: предел 10 к сообщению, 30 непривязанных, размер и тип (FR-662)."""
    if uploaded is None:
        raise MessengerError("file_missing", field="file")
    have_ids = _ids(have)
    attached = MessageAttachment.objects.filter(message__chat=chat).count()
    if attached + len(have_ids) >= MAX_FILES:
        raise MessengerError("files_limit", field="file")
    if MessageAttachment.objects.filter(uploaded_by=user, message__isnull=True).count() >= MAX_UNBOUND:
        raise MessengerError("too_many_unbound", field="file")

    name = str(uploaded.name)[:255]
    data = uploaded.read()
    reason = uploads.reject_reason(name, data, len(data), MAX_FILE)
    if reason:
        raise MessengerError(_REFUSALS[reason], field="file")
    try:
        uploads.detect_image(data)
    except uploads.ImageTooLarge:
        raise MessengerError("file_type", field="file") from None
    with transaction.atomic():
        stored = uploads.store(data, name, PURPOSE)
        attachment = MessageAttachment.objects.create(
            message=None, file=stored, name=name, uploaded_by=user, uploaded_at=timezone.now())
    return attachment


def bind(user, ids, message) -> None:
    """Привязать файлы условным `UPDATE`: меньше строк, чем прислано, — `file_missing` и откат (FR-662)."""
    file_ids = _ids(ids)
    if not file_ids:
        return
    if len(file_ids) > MAX_FILES:
        raise MessengerError("files_limit", field="files")
    bound = MessageAttachment.objects.filter(
        pk__in=file_ids, message__isnull=True, uploaded_by=user).update(message=message)
    if bound != len(file_ids):
        raise MessengerError("file_missing", field="files")


def remove(attachment, user) -> None:
    """Убрать свой непривязанный файл: строки в транзакции, файл и эскиз с диска после фиксации (FR-662)."""
    if attachment.message_id is not None or attachment.uploaded_by_id != getattr(user, "pk", None):
        raise Http404("Файл не найден")
    paths = [core_path(attachment)]
    if attachment.thumb:
        paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / attachment.thumb)
    with transaction.atomic():
        stored_id = attachment.file_id
        attachment.delete()
        StoredFile.objects.filter(pk=stored_id).delete()
        transaction.on_commit(lambda: _erase(paths))


def still_waiting(stored) -> bool:
    """Файл ещё ждёт проверки: он `pending` и у него есть строка вложения мессенджера (CONTRACT-008, 5.4)."""
    return stored.status == StoredFile.Status.PENDING and MessageAttachment.objects.filter(file=stored).exists()


def clean(stored) -> list:
    """Итог «чисто»: перенос в `attachments/<id>` и эскиз; сбой эскиза не откладывает «чистый» (FR-662)."""
    leftovers = uploads.move(stored, StoredFile.Status.CLEAN)
    relative = ""
    try:
        relative = thumbs.build(core_path_stored(stored), stored.pk)
    except Exception:  # noqa: BLE001 — сбой эскиза не отменяет перенос и проверку
        _remove_partial_thumbs(stored.pk)
    if relative:
        MessageAttachment.objects.filter(file=stored).update(thumb=relative)
    return leftovers


def found(stored, signature: str) -> list:
    """Итог «найдено»: пометка карантина с переносом файла; эскиза нет."""
    return uploads.move(stored, StoredFile.Status.QUARANTINE, signature)


def file_purposes() -> list:
    """Описание назначения «вложение сообщения чата» для точки `file_purposes` ядра."""
    from apps.core.extensions import FilePurpose

    return [FilePurpose(purpose=PURPOSE, still_waiting=still_waiting, clean=clean, found=found)]


def core_path_stored(stored) -> pathlib.Path:
    """Путь файла `StoredFile` под томом `protected` (для эскиза)."""
    from apps.core.services import files as core_files

    return core_files.attachment_path(stored)


def _remove_partial_thumbs(stored_id) -> None:
    folder = pathlib.Path(django_settings.PROTECTED_ROOT) / "attachments" / "thumbs"
    for path in folder.glob(f"{stored_id}.*"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def core_path(attachment) -> pathlib.Path:
    """Путь оригинала в томе `protected` (CONTRACT-008, 1.3)."""
    from apps.core.services import files as core_files

    return core_files.attachment_path(attachment.file)


def _erase(paths) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _ids(values) -> list[int]:
    result: list[int] = []
    for value in values or ():
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result