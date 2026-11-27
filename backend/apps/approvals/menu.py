"""Пункт меню «Мои задания» (PLAN-014, T-14030)."""


def menu_items() -> list[dict]:
    return [{"permissions": (), "url": "/approvals/my/", "title": "Мои задания",
             "icon": "icons/servicedesk.html", "order": 4, "visible": lambda user: True}]
