"""Срок хранения переписки и «Общий чат» (срез 008, T-8201; CONTRACT-008, 2.3, 5.4).

Строка настроек одна — `pk=1`; её создаёт миграция данных `messenger 0002_initial_data`, а `get()` создаёт
при отсутствии на всякий случай (план: «`messenger_settings.get()` создаёт её при отсутствии»). Значения по
умолчанию — три года и включённый «Общий чат».
"""
from apps.messenger.models import MessengerSettings

DEFAULT_YEARS = 3      # строка первой установки (миграция данных, план)
DEFAULT_GENERAL = True


def get() -> MessengerSettings:
    """Возвращает единственную строку настроек, создавая её при отсутствии (три года, «Общий чат» включён)."""
    row, _ = MessengerSettings.objects.get_or_create(
        pk=1, defaults={"retention_years": DEFAULT_YEARS, "general_chat_enabled": DEFAULT_GENERAL})
    return row