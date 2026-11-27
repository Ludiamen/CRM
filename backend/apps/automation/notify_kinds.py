"""Вид уведомления автоматизации (PLAN-013, T-13042; SPEC-013, FR-811)."""
from apps.core.extensions import NotificationKind

MODULE = "Автоматизация"


def notification_kinds() -> list:
    return [NotificationKind(
        code="automation.rule_notice", title="Сообщение правила", module=MODULE, order=240,
        external_text="Сработало правило автоматизации", default_channels=("portal", "email"))]
