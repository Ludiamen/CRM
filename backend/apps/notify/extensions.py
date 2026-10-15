"""Регистрация в точках ядра и подписка на события (PLAN-004, «Где живёт код»)."""
from apps.core import extensions
from apps.notify.notify_kinds import notification_kinds  # вид «Канал отвязан» (CONTRACT-004 § 3.2)

__all__ = ["notification_kinds", "register_all"]


def register_all() -> None:
    """Регистрации `notify` в точках ядра; зовёт `NotifyConfig.ready()`. Подписки на шину — `dispatch.subscribe_all()`
    (T-4206), прочие точки добавляют задачи волн (б)–(г)."""
    extensions.register("notification_kinds", notification_kinds)
