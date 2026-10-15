"""Точки расширения ядра (PLAN-002, «Точки расширения ядра»; CONTRACT-002, § 5).

Другие приложения регистрируют функции в `AppConfig.ready()`; реестры хранят их в порядке
регистрации. Без зарегистрированных функций ядро ведёт себя как после среза 001.
Ядро не импортирует приложения, которые в нём регистрируются.
"""
import pathlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, NamedTuple

from django.http import HttpRequest

POINTS = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory",
          "card_sections", "day_marks", "home_notices", "stand_reset",
          "unit_usage", "file_purposes", "mail_renderers", "login_links",
          "notification_kinds", "top_bar_items")

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


@dataclass
class FilePurpose:
    """Назначение файла в хранилище: как приложение обрабатывает итог проверки на вирусы."""
    purpose: str
    still_waiting: Callable
    clean: Callable
    found: Callable


@dataclass
class MailRenderer:
    """Сборка письма приложения в момент отправки: `render(MailMessage, context) -> Rendered`."""
    prefix: str
    render: Callable


class Rendered(NamedTuple):
    """Готовое письмо: текст и вложения (имя и путь файла в томе `protected`)."""
    body: str
    attachments: list[tuple[str, pathlib.Path]]


@dataclass(frozen=True)
class Draft:
    """Черновик уведомления: кому, строка текста, ссылка внутри портала, ссылка на объект для «прочитано»."""
    user_id: int
    text: str
    url: str
    object_ref: str = ""


def _no_drafts(event: str, data: dict) -> list:
    return []


def _always(*args) -> bool:
    return True


@dataclass(frozen=True)
class NotificationKind:
    """Вид уведомления (PLAN-004, «Точки расширения ядра и шина событий»; CONTRACT-004, § 3.1).

    `build(event, data)` возвращает список `Draft`; `available(user)` — показывать ли строку вида
    сотруднику; `still_relevant(user_id, object_ref)` — проверка перед письмом и сводкой.
    """
    code: str
    title: str
    module: str
    events: tuple[str, ...] = ()
    build: Callable[[str, dict], list] = _no_drafts
    external_text: str = ""
    default_channels: tuple[str, ...] = ("portal",)
    mandatory: bool = False
    available: Callable = _always
    still_relevant: Callable[[int, str], bool] = _always
    order: int = 0


@dataclass(frozen=True)
class TopBarItem:
    """Элемент верхней панели перед ссылками профиля: шаблон и контекст по запросу."""
    key: str
    order: int
    template: str
    context: Callable[[HttpRequest], dict]
