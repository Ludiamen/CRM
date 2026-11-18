"""Срок хранения и ночное задание (срез 008, T-8220; CONTRACT-008, 5.4, 8.1).

PLAN-008 «Срок хранения и ночное задание». Граница — `created_at < now − N лет` (год вычитается календарно,
29 февраля становится 28-м в невисокосный год); правка сообщения срок не продлевает (граница по `created_at`).
Удаление пачками по 1 000: сообщения, вложения, строки `StoredFile`, файлы и эскизы после фиксации; `last_message_at`
чатов пересчитывается. Отдельно убираются непривязанные вложения старше 24 часов и чаты отдела с несуществующим
`unit_id` (страховка обработчика `unit.deleted`). Журнал `messenger.retention_purged` — одна запись с числом
удалённых сообщений и только при удалении больше нуля.
"""
import pathlib
from datetime import timedelta

from django.apps import apps
from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from apps.core.models import StoredFile
from apps.core.services import audit
from apps.core.services import files as core_files
from apps.messenger.models import Chat, Message, MessageAttachment
from apps.messenger.services import messenger_settings

BATCH = 1000
UNBOUND_AGE = timedelta(hours=24)


def boundary(now, years: int):
    """Граница срока: `now − years`, календарно; 29 февраля в невисокосный год — 28 февраля (FR-670)."""
    try:
        return now.replace(year=now.year - years)
    except ValueError:
        return now.replace(year=now.year - years, day=28)


def count_older(now, years: int) -> int:
    """Сколько сообщений старше новой границы: число для второго шага уменьшения срока."""
    return Message.objects.filter(created_at__lt=boundary(now, years)).count()


def run(now=None) -> int:
    """Ночное задание: удалить просроченное, непривязанные старше суток и чаты исчезнувших отделов (FR-670)."""
    now = now or timezone.now()
    years = messenger_settings.get().retention_years
    edge = boundary(now, years)
    removed = _purge_messages(edge)
    _purge_unbound(now - UNBOUND_AGE)
    _purge_orphan_departments()
    if removed:
        audit.record("messenger.retention_purged", object_type="messenger.settings", object_id="1",
                     after={"messages": removed})
    return removed


def _purge_messages(edge) -> int:
    """Пачки по 1 000: сообщения, вложения, файлы и эскизы, пересчёт `last_message_at`."""
    total = 0
    while True:
        ids = list(Message.objects.filter(created_at__lt=edge).order_by("id")
                   .values_list("pk", flat=True)[:BATCH])
        if not ids:
            break
        with transaction.atomic():
            chat_ids = set(Message.objects.filter(pk__in=ids).values_list("chat_id", flat=True))
            attachments = list(MessageAttachment.objects.filter(message_id__in=ids).select_related("file"))
            _remove_attachments(attachments)
            Message.objects.filter(pk__in=ids).delete()
            for chat_id in chat_ids:
                _recalculate_last(chat_id)
        total += len(ids)
        if len(ids) < BATCH:
            break
    return total


def _purge_unbound(edge) -> None:
    """Непривязанные вложения старше суток: строка, файл, эскиз; в число удалённых сообщений не входят (FR-662)."""
    rows = list(MessageAttachment.objects.filter(message__isnull=True, uploaded_at__lt=edge)
                .select_related("file"))
    if rows:
        with transaction.atomic():
            _remove_attachments(rows)


def _remove_attachments(rows) -> None:
    """Удалить строки вложений и `StoredFile`, пути — на стирание после фиксации."""
    paths: list[pathlib.Path] = []
    stored_ids: list[int] = []
    for attachment in rows:
        paths.append(core_files.attachment_path(attachment.file))
        stored_ids.append(attachment.file_id)
        if attachment.thumb:
            paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / attachment.thumb)
    MessageAttachment.objects.filter(pk__in=[row.pk for row in rows]).delete()
    if stored_ids:
        StoredFile.objects.filter(pk__in=stored_ids).delete()
    if paths:
        transaction.on_commit(lambda: core_files.remove_paths(paths))


def _recalculate_last(chat_id: int) -> None:
    last = (Message.objects.filter(chat_id=chat_id, deleted_at__isnull=True)
            .order_by("-created_at", "-id").values_list("created_at", flat=True).first())
    Chat.objects.filter(pk=chat_id).update(last_message_at=last)


def _purge_orphan_departments() -> None:
    """Чаты отдела с `unit_id`, которого нет в структуре: удалить той же службой, что и обработчик шины."""
    from apps.messenger.services import department

    chats = list(Chat.objects.filter(kind=Chat.Kind.DEPARTMENT).values_list("unit_id", flat=True))
    if not chats:
        return
    if apps.is_installed("apps.org"):
        from apps.org.services import structure

        existing = set(structure.unit_refs([unit for unit in chats if unit is not None]))
    else:
        existing = set()
    for unit_id in dict.fromkeys(unit for unit in chats if unit is not None):
        if unit_id not in existing:
            department.on_unit_deleted(unit_id, name="", actor_id=None)