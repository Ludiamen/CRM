"""Регистрации главной, меню, поиска, файлов и подписей журнала ленты (T-7213a, T-7227, T-7228, T-7231,
сброс стенда — T-7232)."""


def menu_items() -> list[dict]:
    from apps.feed.services import unread

    return [
        {"permissions": (), "url": "/", "title": "Лента", "icon": "icons/feed.html", "order": 0,
         "visible": lambda user: True, "badge": unread.count, "live_badge": "feed"},
        {"permissions": ("settings.portal",), "url": "/settings/feed/", "title": "Настройки ленты",
         "icon": "icons/gear.html", "order": 63},
    ]


def register_all() -> None:
    from apps.core import extensions
    from apps.feed import audit_labels, notify_kinds
    from apps.feed import stand  # сброс данных на стенде (T-7232, CONTRACT-007 1.3)
    from apps.feed.services import files, search
    from apps.feed.views.home import body

    extensions.register("menu_items", menu_items)
    extensions.register("home_body", body)
    extensions.register("search_providers", search.search_providers)
    extensions.register("notification_kinds", notify_kinds.notification_kinds)
    extensions.register("file_purposes", files.file_purposes)
    extensions.register("audit_labels", audit_labels.audit_labels)  # подписи журнала (T-7231, CONTRACT-007 8.2)
    extensions.register("stand_reset", stand.stand_reset)  # последняя: сброс зовёт функции в обратном порядке
