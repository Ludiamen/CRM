"""Вид уведомления самого `notify`: «Канал отвязан» (PLAN-004, «Каталог видов и каналы»; CONTRACT-004, § 3.2).

Событий шины у вида нет: запись на портале создаёт сам `notify` при отвязке канала (обязательный вид, только портал).
"""
from apps.core.extensions import NotificationKind


def notification_kinds() -> list[NotificationKind]:
    """Функция точки `notification_kinds`: свежие объекты при каждом вызове."""
    return [
        NotificationKind(code="notify.channel_unbound", title="Канал отвязан", module="Уведомления",
                         events=(), mandatory=True, default_channels=("portal",), order=200),
    ]
