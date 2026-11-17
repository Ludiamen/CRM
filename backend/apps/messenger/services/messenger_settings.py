"""Срок хранения переписки и «Общий чат» (срез 008, T-8201/T-8206/T-8220; CONTRACT-008, 2.3, 5.4, 8.1).

Строка настроек одна — `pk=1`; её создаёт миграция данных `messenger 0002_initial_data`, а `get()` создаёт
при отсутствии на всякий случай (план: «`messenger_settings.get()` создаёт её при отсутствии»). Значения по
умолчанию — три года и включённый «Общий чат». Смена «Общего чата» пишется в журнал словами «включён» /
«выключен» (план, «Журнал»); срок хранения сохраняет T-8220.
"""
from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.messenger.models import MessengerSettings

DEFAULT_YEARS = 3      # строка первой установки (миграция данных, план)
DEFAULT_GENERAL = True
ENABLED_WORD = "включён"
DISABLED_WORD = "выключен"
OBJECT_TYPE = "messenger.settings"
OBJECT_ID = "1"


def get() -> MessengerSettings:
    """Возвращает единственную строку настроек, создавая её при отсутствии (три года, «Общий чат» включён)."""
    row, _ = MessengerSettings.objects.get_or_create(
        pk=1, defaults={"retention_years": DEFAULT_YEARS, "general_chat_enabled": DEFAULT_GENERAL})
    return row


def set_general(enabled: bool, actor) -> bool:
    """Включает или выключает «Общий чат»; при смене — одна запись `messenger.general_changed` (FR-651, 671).

    История чата остаётся в базе: выключенный чат не виден, но включается обратно тем же действием.
    Возвращает `True`, если значение изменилось.
    """
    row = get()
    before = bool(row.general_chat_enabled)
    enabled = bool(enabled)
    if before == enabled:
        return False
    with transaction.atomic():
        row.general_chat_enabled = enabled
        row.updated_at = timezone.now()
        row.updated_by = actor
        row.save(update_fields=["general_chat_enabled", "updated_at", "updated_by"])
        audit.record(
            "messenger.general_changed", actor=actor, object_type=OBJECT_TYPE, object_id=OBJECT_ID,
            before={"general_chat_enabled": ENABLED_WORD if before else DISABLED_WORD},
            after={"general_chat_enabled": ENABLED_WORD if enabled else DISABLED_WORD},
        )
    return True