"""Регистрация приложения в точках расширения ядра (PLAN-002, «Точки расширения ядра»)."""


def menu_items() -> list[dict]:
    """Пункты меню среза: «Структура» и «Календарь» (достаточно любого из прав пункта)."""
    return [
        {"permissions": ("staff.view",), "url": "/structure/", "title": "Структура",
         "icon": "icons/structure.html", "order": 20},
        {"permissions": ("staff.view", "calendar.manage"), "url": "/calendar/", "title": "Календарь",
         "icon": "icons/calendar.html", "order": 30},
    ]


def register_all() -> None:
    """Регистрирует функции `org` в девяти точках ядра (вызывается из `OrgConfig.ready()`).

    Регистрации добавляют задачи (функции точек — обычные функции модулей `apps.org…`):
    `home_notices` — T-2219; `role_sources` и `role_usage` — T-2213; `audit_labels` — T-2221;
    `menu_items` — T-2230a (готово); `staff_directory` — T-2233 (готово); `card_sections` — T-2234 (готово);
    `day_marks` — T-2238; `stand_reset` — T-2242.
    """
    from apps.core import extensions
    from apps.org import audit_labels, card, directory
    from apps.org.services import calendar, unit_roles

    extensions.register("home_notices", calendar.calendar_notices)
    extensions.register("role_sources", unit_roles.role_sources)
    extensions.register("role_usage", unit_roles.role_usage)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("menu_items", menu_items)
    extensions.register("staff_directory", directory.staff_directory)
    extensions.register("card_sections", card.card_sections)
