"""Три вида уведомлений безопасности ядра (PLAN-004, «Виды безопасности»; CONTRACT-004, § 3.5).

Создаётся только запись на портале: виды обязательные, доставок нет, сводка их не берёт (FR-305).
Получатель — всегда `data["user_id"]`, даже если действие совершил он сам.
"""
from django.utils import timezone

from apps.core.extensions import Draft, NotificationKind

SECURITY_URL = "/me/security/"


def _new_device(event: str, data: dict) -> list[Draft]:
    at = timezone.localtime(data["at"]).strftime("%d.%m.%Y %H:%M")
    return [Draft(user_id=data["user_id"], text=f"Вход с нового устройства ({data['browser']}, {at})",
                  url=SECURITY_URL, object_ref="")]


def _password_changed(event: str, data: dict) -> list[Draft]:
    return [Draft(user_id=data["user_id"], text="Пароль изменён", url=SECURITY_URL, object_ref="")]


def _second_factor_reset(event: str, data: dict) -> list[Draft]:
    return [Draft(user_id=data["user_id"], text="Второй фактор сброшен", url=SECURITY_URL, object_ref="")]


def notification_kinds() -> list[NotificationKind]:
    """Функция точки `notification_kinds`: свежие объекты при каждом вызове."""
    return [
        NotificationKind(code="core.new_device", title="Вход с нового устройства", module="Ядро",
                         events=("core.new_device",), build=_new_device, mandatory=True, order=110),
        NotificationKind(code="core.password_changed", title="Пароль изменён", module="Ядро",
                         events=("core.password_changed",), build=_password_changed, mandatory=True, order=120),
        NotificationKind(code="core.second_factor_reset", title="Второй фактор сброшен", module="Ядро",
                         events=("core.second_factor_reset",), build=_second_factor_reset, mandatory=True,
                         order=130),
    ]
