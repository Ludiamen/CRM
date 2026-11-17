"""Отправка, правка, удаление и цитата сообщения (срез 008, T-8209; CONTRACT-008, 2.2, 5.2).

PLAN-008 «Отправка, правка, удаление, цитата». Текст после среза пробелов не пуст, NUL удаляется, предел —
4 000 знаков, упоминаний — 20 разных людей. Цитата — сообщение этого же чата (один уровень; ссылка `SET_NULL`).
Правка — только автором и только живого сообщения; удаление — мягкое (`deleted_at`, пустой текст и вектор),
вложения и файлы удаляются в транзакции, диск — после фиксации. `last_message_at` пересчитывается по живому
последнему сообщению. Вектор поиска — `to_tsvector('russian', …)` без маркеров `@[u…]`/`@[c…]`.
"""
import pathlib

from django.conf import settings as django_settings
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import StoredFile
from apps.core.services import files as core_files
from apps.messenger.models import Chat, Message, MessageAttachment
from apps.messenger.services import live, mentions, unread
from apps.messenger.services.errors import MessengerError

TEXT_LIMIT = 4000
FILES_LIMIT = 10


def clean_text(text: str) -> str:
    """NUL удаляется, пробелы по краям срезаются; переносы строк и абзацы сохраняются (FR-652)."""
    return (text or "").replace("\x00", "").strip()


def check_text(text: str) -> str:
    """Проверить текст сообщения; возвращает очищенный или поднимает отказ у поля `text`."""
    if not text:
        raise MessengerError("empty_text", field="text")
    if len(text) > TEXT_LIMIT:
        raise MessengerError("too_long", field="text")
    people, _ = mentions.extract(text)
    if mentions.over_limit(people):
        raise MessengerError("mentions_limit", field="text")
    return text


def send(chat, author, text, quote=None, files=()) -> Message:
    """Отправить сообщение: проверить текст, цитату и вложения, записать в одной транзакции (FR-652–654)."""
    clean = check_text(clean_text(text))
    quoted = _quote(chat, quote)
    attachment_ids = _file_ids(files)
    now = timezone.now()
    with transaction.atomic():
        message = Message.objects.create(chat=chat, author=author, is_system=False, text=clean,
                                         quote=quoted, created_at=now)
        if attachment_ids:
            _bind_files(message, author, attachment_ids)
        _set_vector(message, clean)
        Chat.objects.filter(pk=chat.pk).update(last_message_at=now)
        unread.invalidate(None)
        transaction.on_commit(lambda: live.enqueue(chat.pk, message.pk, "new", owner_id=author.pk))
    return message


def edit(message, author, text) -> Message:
    """Правит автор живого сообщения: новый текст, `edited_at`, пересчёт вектора (FR-656)."""
    if message.author_id != getattr(author, "pk", None):
        raise PermissionDenied
    clean = check_text(clean_text(text))
    now = timezone.now()
    with transaction.atomic():
        message.text = clean
        message.edited_at = now
        message.save(update_fields=["text", "edited_at"])
        _set_vector(message, clean)
        unread.invalidate(None)
        transaction.on_commit(lambda: live.enqueue(message.chat_id, message.pk, "edit",
                                                   owner_id=author.pk))
    return message


def delete(message, author) -> Message:
    """Удаляет автор: мягкая запись, пустой текст и вектор, вложения и файлы, пересчёт `last_message_at` (FR-657)."""
    if message.author_id != getattr(author, "pk", None):
        raise PermissionDenied
    now = timezone.now()
    with transaction.atomic():
        attachments = list(MessageAttachment.objects.filter(message=message).select_related("file"))
        paths: list[pathlib.Path] = []
        stored_ids: list[int] = []
        for attachment in attachments:
            paths.append(core_files.attachment_path(attachment.file))
            stored_ids.append(attachment.file_id)
            if attachment.thumb:
                paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / attachment.thumb)
        MessageAttachment.objects.filter(message=message).delete()
        if stored_ids:
            StoredFile.objects.filter(pk__in=stored_ids).delete()
        message.deleted_at = now
        message.text = ""
        message.save(update_fields=["deleted_at", "text"])
        _set_vector(message, "")
        _recalculate_last(message.chat_id)
        unread.invalidate(None)
        transaction.on_commit(lambda: live.enqueue(message.chat_id, message.pk, "delete",
                                                   owner_id=author.pk))
        if paths:
            transaction.on_commit(lambda: core_files.remove_paths(paths))
    return message


def _quote(chat, value) -> Message | None:
    """Цитата — сообщение этого же чата; нет номера, нет строки или другой чат — отказ `message_missing` (FR-654)."""
    if value in (None, "", 0):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise MessengerError("message_missing", field="quote") from None
    message = Message.objects.filter(pk=number).first()
    if message is None or message.chat_id != chat.pk:
        raise MessengerError("message_missing", field="quote")
    return message


def _file_ids(values) -> list[int]:
    """Номера файлов из формы: положительные целые без повторов, не больше десяти."""
    result: list[int] = []
    for value in values or ():
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    if len(result) > FILES_LIMIT:
        raise MessengerError("files_limit", field="files")
    return result


def _bind_files(message, author, attachment_ids: list[int]) -> None:
    """Привязывает непривязанные файлы автора; чужой или уже привязанный — отказ `file_missing` (FR-662)."""
    rows = list(MessageAttachment.objects.filter(pk__in=attachment_ids, uploaded_by=author, message__isnull=True))
    if len(rows) != len(attachment_ids):
        raise MessengerError("file_missing", field="files")
    MessageAttachment.objects.filter(pk__in=[row.pk for row in rows]).update(message=message)


def _set_vector(message, text: str) -> None:
    """Вектор поиска без маркеров упоминаний; текст уходит параметром (NFR-703)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE messenger_message SET search = to_tsvector('russian', "
            "regexp_replace(%s, '@\\[[uc][0-9]{1,9}\\]', ' ', 'g')) WHERE id = %s",
            [text, message.pk])
    message.refresh_from_db(fields=["search"])


def _recalculate_last(chat_id: int) -> None:
    """`last_message_at` — время последнего живого сообщения или `None`, если живых нет (FR-644, 657)."""
    last = (Message.objects.filter(chat_id=chat_id, deleted_at__isnull=True)
            .order_by("-created_at", "-id").values_list("created_at", flat=True).first())
    Chat.objects.filter(pk=chat_id).update(last_message_at=last)