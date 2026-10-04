"""Публичный интерфейс `org` — пакет `services` (CONTRACT-002, § 4).

Семь модулей: `structure`, `membership`, `people`, `unit_roles`, `calendar`, `calendar_file`,
`staff_import`. Здесь они не импортируются (чтобы не создавать циклов); зовите их как
`apps.org.services.<модуль>.<функция>`. Из пакета экспортируются ошибка и контактные значения.
"""
from .errors import OrgError
from .refs import HeadsOf, PersonRef, UnitRef

__all__ = ["OrgError", "PersonRef", "UnitRef", "HeadsOf"]
