"""Регистрации базы знаний в точках расширения ядра (срез 005)."""


def register_all() -> None:
    """Регистрирует функции `knowledge` в точках ядра (вызывается из `KnowledgeConfig.ready()`).

    Сейчас — `notification_kinds` (T-5213); остальные точки добавляют свои задачи среза.
    """
    from apps.core import extensions
    from apps.knowledge import notify_kinds

    extensions.register("notification_kinds", notify_kinds.notification_kinds)
