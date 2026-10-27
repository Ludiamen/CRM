"""Регистрации списков в точках расширения ядра (срез 006)."""


def register_all() -> None:
    """Регистрирует функции `lists` в точках ядра; остальные точки добавляют свои задачи среза."""
    from apps.core import extensions
    from apps.lists import audit_labels  # подписи журнала (T-6224, CONTRACT-006 8.2)
    from apps.lists import notify_kinds  # вид уведомления о сроке (T-6219, CONTRACT-006 раздел 7)
    from apps.lists.services import links  # фразы запрета удаления узла и роли (T-6211, CONTRACT-006 3.2)
    from apps.lists.services import search  # поставщик поиска (T-6212, CONTRACT-006 раздел 9)

    extensions.register("search_providers", search.search_providers)
    extensions.register("notification_kinds", notify_kinds.notification_kinds)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("unit_usage", links.unit_usage)
    extensions.register("role_usage", links.role_usage)
