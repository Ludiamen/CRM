"""Регистрации базы знаний в точках расширения ядра (срез 005)."""


def register_all() -> None:
    """Регистрирует функции `knowledge` в точках ядра (вызывается из `KnowledgeConfig.ready()`).

    Сейчас — `notification_kinds` (T-5213); остальные точки добавляют свои задачи среза.
    """
    from apps.core import extensions
    from apps.knowledge import notify_kinds

    extensions.register("notification_kinds", notify_kinds.notification_kinds)

    from apps.knowledge import audit_labels  # подписи журнала (T-5211, CONTRACT-005 8.2)

    extensions.register("audit_labels", audit_labels.audit_labels)

    from apps.knowledge.services import search as article_search

    extensions.register("search_providers", article_search.search_providers)

    from apps.knowledge.services import files as article_files  # файлы статьи (T-5210)

    extensions.register("file_purposes", article_files.file_purposes)

    from apps.knowledge.views import links as link_views  # части карточки заявки (T-5212)

    extensions.register("ticket_card_parts", link_views.ticket_card_parts)
