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
    """Регистрирует функции `org` в девяти точках среза 002 и в `search_providers` (вызывается из `OrgConfig.ready()`).

    Регистрации добавляют задачи (функции точек — обычные функции модулей `apps.org…`):
    `home_notices` — T-2219; `role_sources` и `role_usage` — T-2213; `audit_labels` — T-2221;
    `menu_items` — T-2230a (готово); `staff_directory` — T-2233 (готово); `card_sections` — T-2234 (готово);
    `day_marks` — T-2238 (готово: `calendar.month_marks`); `stand_reset` — T-2242 (готово: `stand.stand_reset`).
    """
    from apps.core import extensions
    from apps.org import audit_labels, card, directory, stand
    from apps.org.services import calendar, search_provider, unit_roles

    extensions.register("home_notices", calendar.calendar_notices)
    extensions.register("role_sources", unit_roles.role_sources)
    extensions.register("role_usage", unit_roles.role_usage)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("menu_items", menu_items)
    extensions.register("staff_directory", directory.staff_directory)
    extensions.register("card_sections", card.card_sections)
    extensions.register("day_marks", calendar.month_marks)
    extensions.register("stand_reset", stand.stand_reset)
    extensions.register("search_providers", search_provider.search_providers)
