"""Сброс данных мессенджера на стенде (срез 008, T-8008; план «Проверка» → «данные установки и стенд»).

Здесь только проверка стенда `require_stand()` для команд `e2e_messenger_*` (копия образца `feed`, не импорт)
и перечень таблиц сброса `TABLES` по договору сброса. Функцию `stand_reset()` и регистрацию точки
`stand_reset` в `extensions.py` добавляет T-8224 (решение 5 задач среза): сброс приводит данные мессенджера к
состоянию сразу после миграций `0001_initial`/`0002_initial_data` —
- стирает строки мессенджера в порядке `TABLES` (зависимые раньше): `MessageAttachment`, `Message`,
  `ChatMember`, `ChatRead`, `Chat`, `MessengerSettings` — вложение раньше сообщения, потому что держит
  `StoredFile` через `PROTECT`; строки `ChatMember`/`ChatRead`/`Message` снимает и каскад `Chat`;
- стирает строки `core.StoredFile` назначения `messenger` (вложения сообщений чата), собранные по строкам
  `MessageAttachment` до их удаления;
- файлы и эскизы удаляет с диска после фиксации транзакции (`on_commit` того же алиаса, К-9 CONTRACT-006):
  оригиналы по путям `StoredFile` и весь каталог эскизов `attachments/thumbs/`;
- возвращает данные установки: `MessengerSettings(pk=1, retention_years=3, general_chat_enabled=True)`
  (срок хранения 3 года, общий чат включён) и «Общий чат» (`kind="general"`).

Сброс идёт под владельцем схемы (алиас `migrate`) в одной транзакции; на мессенджер никто не ссылается,
поэтому регистрация точки — последней записью, а вызов — первым (сброс зовёт функции в обратном порядке).
"""
import os

from django.core.management.base import CommandError

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."

# Таблицы мессенджера в порядке стирания: зависимые раньше (вложение — до сообщения: `PROTECT` на `StoredFile`).
# `core.StoredFile` назначения `FILE_PURPOSE` стирается отдельно — общую таблицу ядра сброс не трогает.
TABLES = (
    "messenger_messageattachment",
    "messenger_message",
    "messenger_chatmember",
    "messenger_chatread",
    "messenger_chat",
    "messenger_messengersettings",
)
FILE_PURPOSE = "messenger"


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)

def stand_reset() -> None:
    """Сброс данных мессенджера под владельцем схемы (алиас `migrate`, CONTRACT-008 1.3).

    Стирает строки `TABLES` в порядке зависимостей, строки `core.StoredFile` назначения `messenger` и вложения;
    файлы оригиналов и эскизы стираются после фиксации на том же соединении. Затем `seed(stand=True)` возвращает
    срок 3 года, включённый «Общий чат» и его строку. Повторный запуск идёт по тому же пути.
    """
    import pathlib

    from django.apps import apps as django_apps
    from django.conf import settings as django_settings
    from django.db import connections, transaction
    from django.utils import timezone

    from apps.core.models import StoredFile
    from apps.core.services import files as core_files
    from apps.messenger.models import Chat, ChatMember, ChatRead, Message, MessageAttachment, MessengerSettings

    db = "migrate"
    connection = connections[db]

    with transaction.atomic(using=db):
        attachments = list(MessageAttachment.objects.using(db).all())
        paths: list[pathlib.Path] = []
        for attachment in attachments:
            try:
                paths.append(core_files.attachment_path(attachment.file))
            except Exception:  # noqa: BLE001 — путь собирается по состоянию; сбой не отменяет сброс
                pass
            if attachment.thumb:
                paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / attachment.thumb)
        stored = list(StoredFile.objects.using(db).filter(purpose=FILE_PURPOSE))
        for row in stored:
            try:
                paths.append(core_files.attachment_path(row))
            except Exception:  # noqa: BLE001
                pass

        MessageAttachment.objects.using(db).all().delete()
        Message.objects.using(db).all().delete()
        ChatMember.objects.using(db).all().delete()
        ChatRead.objects.using(db).all().delete()
        Chat.objects.using(db).all().delete()
        MessengerSettings.objects.using(db).all().delete()
        StoredFile.objects.using(db).filter(purpose=FILE_PURPOSE).delete()

        transaction.on_commit(lambda: _erase(paths), using=db)

        import importlib

        seed_module = importlib.import_module("apps.messenger.migrations.0002_initial_data")
        seed_module.seed(django_apps, _Schema(connection), stand=True)


class _Schema:
    """Минимальная обёртка `schema_editor` для `seed`: нужен только `.connection.alias`."""

    def __init__(self, connection):
        self.connection = connection


def _erase(paths) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
