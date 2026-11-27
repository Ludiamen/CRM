"""Пункт меню автоматизации (PLAN-013, T-13044)."""
from apps.core.services import permissions


def _visible(user) -> bool:
    if permissions.has_permission(user, "automation.manage"):
        return True
    from apps.org.services import structure

    return bool(structure.managed_units(user))


def menu_items() -> list[dict]:
    return [{"permissions": ("automation.manage",), "url": "/automation/", "title": "Автоматизация",
             "icon": "icons/servicedesk.html", "order": 66, "visible": _visible}]
