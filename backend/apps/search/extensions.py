"""Регистрации поиска в точках расширения ядра (PLAN-005, «Строка поиска»; CONTRACT-005, 11.9)."""
from apps.core import extensions

__all__ = ["register_all", "top_bar_items"]


def register_all() -> None:
    """Регистрации `search` в точках ядра; зовёт `SearchConfig.ready()`."""
    extensions.register("top_bar_items", top_bar_items)  # строка поиска слева от колокольчика


def top_bar_items() -> list:
    """Строка поиска: один элемент верхней панели, порядок 5 (колокольчик — 10)."""
    return [extensions.TopBarItem(key="search", order=5, template="search/_bar.html", context=lambda request: {})]
