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