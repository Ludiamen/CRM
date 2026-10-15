"""Регистрация в точках ядра и подписка на события (PLAN-004, «Где живёт код»)."""
from apps.core import events, extensions
from apps.notify.notify_kinds import notification_kinds  # вид «Канал отвязан» (CONTRACT-004 § 3.2)

__all__ = ["notification_kinds", "register_all", "subscribe_bus"]


def register_all() -> None:
    """Регистрации `notify` в точках ядра; зовёт `NotifyConfig.ready()`. Подписки на шину — `subscribe_bus()`
    (T-4206), прочие точки добавляют задачи волн (б)–(г)."""
    from apps.notify import audit_labels
    from apps.notify.services import mail

    extensions.register("notification_kinds", notification_kinds)
    extensions.register("audit_labels", audit_labels.audit_labels)  # подписи журнала (T-4215, CONTRACT-004 § 9)
    extensions.register("mail_renderers", mail.renderers)  # письма notify.item и notify.digest (T-4210, § 10)


def subscribe_bus() -> None:
    """Подписки `notify` на шину событий (CONTRACT-004, 6.1): подписчик — сама функция службы; зовёт
    `NotifyConfig.ready()` после `register_all()`. Повторная подписка той же функции шиной игнорируется."""
    from apps.notify.services import cleanup, dispatch, push, reading

    dispatch.subscribe_all()
    events.subscribe("object.viewed", reading.on_object_viewed)
    events.subscribe("core.logged_out", push.on_logged_out)
    events.subscribe("core.user_dismissed", cleanup.on_dismissed)
    events.subscribe("core.user_rehired", cleanup.on_rehired)
