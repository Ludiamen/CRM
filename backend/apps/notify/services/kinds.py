"""Публичный интерфейс уведомлений: каталог видов уведомлений (PLAN-004, «Каталог видов и каналы»; CONTRACT-004, 6.3).

Виды собираются из точки `notification_kinds` при каждом вызове (кэша нет): регистрации живут в памяти процесса.
"""
import logging

from django.core.exceptions import ImproperlyConfigured

from apps.core import extensions

from .errors import NotifyError

log = logging.getLogger(__name__)

CHANNELS = ("portal", "email", "push", "telegram", "max")
EXTERNAL = ("email", "push", "telegram", "max")


def catalog() -> list:
    """Виды всех функций точки по `(order, порядок регистрации)`; повтор кода — `ImproperlyConfigured`."""
    found = []
    for function in extensions.registered("notification_kinds"):
        found.extend(function())
    seen = set()
    for kind in found:
        if kind.code in seen:
            raise ImproperlyConfigured(f"Код вида уведомления повторяется: {kind.code}")
        seen.add(kind.code)
    return sorted(found, key=lambda kind: kind.order)  # сортировка устойчива: при равном order — порядок регистрации


def get(code: str):
    """Вид по коду; нет в каталоге — `NotifyError("unknown_kind")`."""
    for kind in catalog():
        if kind.code == code:
            return kind
    raise NotifyError("unknown_kind", "Вид уведомления не найден", field="kind")


def external_text(kind, object_ref: str) -> str:
    """Внешний текст вида по ссылке на объект: `external_text_of(object_ref)`, если задана, иначе `external_text`."""
    if kind.external_text_of is not None:
        return kind.external_text_of(object_ref)
    return kind.external_text


def for_event(name: str) -> list:
    """Виды, у которых событие `name` среди `events`, в порядке каталога."""
    return [kind for kind in catalog() if name in kind.events]


def event_names() -> list[str]:
    """Все имена событий видов каталога без повторов, в порядке первого появления."""
    names = []
    for kind in catalog():
        for name in kind.events:
            if name not in names:
                names.append(name)
    return names


def check() -> None:
    """Проверка каталога при запуске: повтор кода останавливает запуск (`ImproperlyConfigured`)."""
    catalog()
