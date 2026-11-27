"""Регистрации задач в точках расширения ядра (срез 009; PLAN-009 «Точки расширения ядра»).

Меню, виды уведомлений, поиск, раздел карточки сотрудника, подписи журнала, назначение файла и сброс стенда.
`stand_reset` — всегда последняя запись, чтобы общий сброс вызывал её первой. `role_sources` приложение не
регистрирует: права выданы ролям данными (`core 0013`).
"""


def menu_items() -> list[dict]:
    """Пункты меню: «Задачи» (order 2, `tasks.use`) и «Настройки задач» (order 65, `settings.portal`)."""
    return [
        {"permissions": ("tasks.use",), "url": "/tasks/", "title": "Задачи", "icon": "icons/tasks.html", "order": 2},
        {"permissions": ("settings.portal",), "url": "/settings/tasks/", "title": "Настройки задач",
         "icon": "icons/gear.html", "order": 65},
    ]


def card_sections(viewer, person) -> list:
    """Раздел «Задачи» карточки сотрудника (делегат службы поиска)."""
    from apps.tasks.services import search

    return search.card_section(viewer, person)


def register_all() -> None:
    """Зарегистрировать точки задач (T-9214/T-9217; сброс стенда — последним)."""
    from apps.core import extensions
    from apps.tasks import audit_labels, automation as automation_ext, notify_kinds, stand
    from apps.tasks.services import files, search, task_links

    extensions.register("menu_items", menu_items)
    extensions.register("notification_kinds", notify_kinds.notification_kinds)
    extensions.register("search_providers", search.search_providers)
    extensions.register("card_sections", card_sections)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("file_purposes", files.file_purposes)
    extensions.register("ticket_task_create", task_links.create_from_ticket)
    extensions.register("ticket_task_list", task_links.list_tasks)
    extensions.register("automation_subjects", automation_ext.subject)
    extensions.register("automation_triggers", automation_ext.triggers)
    extensions.register("automation_actions", automation_ext.actions)
    extensions.register("automation_recipients", automation_ext.recipients)
    extensions.register("stand_reset", stand.stand_reset)