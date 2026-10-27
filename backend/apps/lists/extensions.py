"""Регистрации списков в точках расширения ядра (срез 006)."""


def register_all() -> None:
    """Регистрирует функции `lists` в точках ядра; остальные точки добавляют свои задачи среза."""
    from apps.core import extensions
    from apps.lists import audit_labels  # подписи журнала (T-6224, CONTRACT-006 8.2)
    from apps.lists.services import search  # поставщик поиска (T-6212, CONTRACT-006 раздел 9)

    extensions.register("search_providers", search.search_providers)
    extensions.register("audit_labels", audit_labels.audit_labels)
