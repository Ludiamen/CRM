"""Шина событий ядра (PLAN-003, «Шина событий»; CONTRACT-003, § 3.1, FR-292).

Приложения подписываются в `AppConfig.ready()`; реестр хранит обработчики в порядке подписки.
`publish` ставит вызов каждого обработчика на фиксацию транзакции: откатилось действие — события нет.
Ошибка обработчика пишется в лог и не откатывает действие и не мешает остальным обработчикам.
Ядро не импортирует приложения, которые на шине подписываются.
"""
import logging
from contextlib import contextmanager

from django.db import transaction

logger = logging.getLogger(__name__)

_registry: dict[str, list] = {}


def subscribe(name: str, handler) -> None:
    """Добавляет обработчик события; повторная подписка той же функции игнорируется."""
    handlers = _registry.setdefault(name, [])
    if handler not in handlers:
        handlers.append(handler)


def unsubscribe(name: str, handler) -> None:
    """Снимает обработчик; если его нет — ничего не происходит."""
    handlers = _registry.get(name, [])
    if handler in handlers:
        handlers.remove(handler)


def subscribers(name: str) -> list:
    """Копия списка обработчиков события в порядке подписки."""
    return list(_registry.get(name, []))


def clear() -> None:
    """Снимает все подписки."""
    _registry.clear()


@contextmanager
def empty():
    """На время блока подписок нет; прежние возвращаются при выходе."""
    saved = {name: list(handlers) for name, handlers in _registry.items()}
    _registry.clear()
    try:
        yield
    finally:
        _registry.clear()
        _registry.update(saved)


def publish(name: str, **data) -> None:
    """Вызывает обработчики события как `handler(**data)` после фиксации транзакции.

    У каждого обработчика своя транзакция; исключение обработчика пишется в лог
    `apps.core.events` и дальше не поднимается.
    """
    for handler in subscribers(name):
        def run(handler=handler):
            try:
                with transaction.atomic():
                    handler(**data)
            except Exception:
                logger.exception("Ошибка обработчика %r события %s", handler, name)

        transaction.on_commit(run, robust=True)
