"""Регистрации списков в точках расширения ядра (срез 006)."""


def register_all() -> None:
    """Регистрирует функции `lists` в точках ядра; остальные точки добавляют свои задачи среза."""
    from apps.core import extensions
    from apps.lists import audit_labels  # подписи журнала (T-6224, CONTRACT-006 8.2)

    extensions.register("audit_labels", audit_labels.audit_labels)
