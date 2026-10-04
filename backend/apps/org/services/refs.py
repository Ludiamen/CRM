"""Контактные значения служб `org` (CONTRACT-002, § 2): не привязаны к базе."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PersonRef:
    """Сотрудник в ответах служб."""

    id: int
    full_name: str
    position: str


@dataclass(frozen=True)
class UnitRef:
    """Подразделение; `path` — `Unit.path`, например «/1/5/9/»."""

    id: int
    name: str
    kind: str
    path: str


@dataclass(frozen=True)
class HeadsOf:
    """Руководители подразделения и узел, где они найдены (`None`, если не найдены)."""

    unit: UnitRef
    heads: list[PersonRef]
    source: UnitRef | None
