"""Регистрации списков в точках расширения ядра (срез 006)."""


def menu_items() -> list[dict]:
    """Пункт меню «Списки»: без прав в `permissions`, виден по `access.sees_section`, без `badge`, `order` 8
    (CONTRACT-006, 3.2)."""
    from apps.lists.services import access

    return [{"permissions": (), "url": "/lists/", "title": "Списки", "icon": "icons/lists.html", "order": 8,
             "visible": access.sees_section}]


def register_all() -> None:
    """Регистрирует функции `lists` в точках ядра; остальные точки добавляют свои задачи среза."""
    from apps.core import extensions
    from apps.lists import audit_labels  # подписи журнала (T-6224, CONTRACT-006 8.2)
    from apps.lists import card  # «Закреплённое» в карточке сотрудника (T-6217)
    from apps.lists import notify_kinds  # вид уведомления о сроке (T-6219, CONTRACT-006 раздел 7)
    from apps.lists import ticket_parts  # раздел «Записи списков» в карточке заявки (T-6218, CONTRACT-006 3.2)
    from apps.lists import stand  # сброс данных на стенде (T-6241, CONTRACT-006 1.3)
    from apps.lists.services import files  # назначение файлов записей (T-6222, CONTRACT-006 3.2)
    from apps.lists.services import links  # фразы запрета удаления узла и роли (T-6211, CONTRACT-006 3.2)
    from apps.lists.services import search  # поставщик поиска (T-6212, CONTRACT-006 раздел 9)

    extensions.register("menu_items", menu_items)  # порядок регистраций — CONTRACT-006, 3.2
    extensions.register("search_providers", search.search_providers)
    extensions.register("card_sections", card.card_sections)
    extensions.register("ticket_card_parts", ticket_parts.ticket_card_parts)
    extensions.register("notification_kinds", notify_kinds.notification_kinds)
    extensions.register("file_purposes", files.file_purposes)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("unit_usage", links.unit_usage)
    extensions.register("role_usage", links.role_usage)
    extensions.register("stand_reset", stand.stand_reset)
