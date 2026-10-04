"""Точки расширения ядра (PLAN-002, «Точки расширения ядра»; CONTRACT-002, § 5).

Другие приложения регистрируют функции в `AppConfig.ready()`; реестры хранят их в порядке
регистрации. Без зарегистрированных функций ядро ведёт себя как после среза 001.
Ядро не импортирует приложения, которые в нём регистрируются.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable

POINTS = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory",
          "card_sections", "day_marks", "home_notices", "stand_reset")

_registry: dict[str, list] = {point: [] for point in POINTS}


def _check(point: str) -> None:
    if point not in _registry:
        raise ValueError(f"Неизвестная точка расширения: {point}")


def register(point: str, func) -> None:
    """Добавляет функцию в точку; повторная регистрация той же функции игнорируется."""
    _check(point)
    if func not in _registry[point]:
        _registry[point].append(func)


def registered(point: str) -> list:
    """Копия списка функций точки в порядке регистрации."""
    _check(point)
    return list(_registry[point])


def clear() -> None:
    """Очищает все реестры."""
    for funcs in _registry.values():
        funcs.clear()


@contextmanager
def empty():
    """На время блока все реестры пусты; прежние возвращаются при выходе."""
    saved = {point: list(funcs) for point, funcs in _registry.items()}
    clear()
    try:
        yield
    finally:
        for point, funcs in saved.items():
            _registry[point][:] = funcs


@dataclass
class Preset:
    key: str
    title: str
    apply: Callable
    order: int


@dataclass
class Filter:
    name: str
    label: str
    choices: Callable
    apply: Callable


@dataclass
class Column:
    key: str
    title: str
    template: str
    order: int


@dataclass
class Button:
    title: str
    url: str
    permissions_all: tuple
    key: str


@dataclass
class StaffDirectory:
    presets: list = field(default_factory=list)
    filters: list = field(default_factory=list)
    search: Callable | None = None
    columns: list = field(default_factory=list)
    buttons: list = field(default_factory=list)


@dataclass
class CardSection:
    key: str
    tab: str
    order: int
    template: str
    context: dict = field(default_factory=dict)
