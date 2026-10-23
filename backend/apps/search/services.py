"""Опрос поставщиков поиска и склейка выдачи (PLAN-005, «Сквозной поиск» → «Сборка»; CONTRACT-005, 9.2, раздел 17 п. 49, 73).

Модуль знает только точку `search_providers`; о приложениях-поставщиках ничего не знает. Запрос нигде не сохраняется и не
логируется: ошибка поставщика пишется в журнал приложения только ключом группы и классом исключения (текст ошибки базы и
трассировка могут содержать фрагмент запроса, поэтому `log.exception` не используется).
"""
import logging
from contextlib import contextmanager
from typing import NamedTuple

from django.db import connection, transaction

from apps.core import extensions
from apps.core.extensions import ParsedQuery, SearchProvider, SearchRow

log = logging.getLogger(__name__)

POPUP_LIMIT = 5
PAGE_LIMIT = 20
# Предел времени каждого запроса поставщика к базе (проверка безопасности 2026-10-23, CONTRACT-005 п. 81): дорогой
# запрос прерывается базой, группа выпадает как при сбое поставщика, остальные работают.
QUERY_TIMEOUT_MS = 2000


class Group(NamedTuple):
    """Группа выдачи: ключ, название, строки (закреплённые и не больше `limit` основных).

    `has_more` — основных строк больше `limit`; `next_offset` — смещение следующей порции (`offset + limit`).
    """
    key: str
    title: str
    rows: list[SearchRow]
    has_more: bool = False
    next_offset: int = 0


class Count(NamedTuple):
    """Число группы: значение, упёрлись ли в потолок, текст (`N` или `N+`)."""
    number: int
    capped: bool
    text: str


def providers(user) -> list[SearchProvider]:
    """Поставщики, доступные сотруднику: по `order`, при равенстве — порядок регистрации.

    Упавшая функция регистрации или `available` группу не показывает, остальные работают.
    """
    found = []
    for func in extensions.registered("search_providers"):
        try:
            for provider in func():
                if provider.available(user):
                    found.append(provider)
        except Exception as exc:  # noqa: BLE001 — выдача не должна падать из-за одного поставщика
            log.error("search provider registration failed: error=%s", type(exc).__name__)
    found.sort(key=lambda provider: provider.order)  # сортировка устойчива
    return found


@contextmanager
def _time_limited():
    """Транзакция поставщика с пределом `statement_timeout` (`set_config(…, true)` действует до конца транзакции);
    после успешного опроса прежнее значение возвращается, при ошибке его возвращает откат точки сохранения."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('statement_timeout')")
            previous = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [str(QUERY_TIMEOUT_MS)])
        yield
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", [previous])


def _collect(provider: SearchProvider, user, parsed: ParsedQuery, limit: int, offset: int):
    """Строки одной группы: закреплённые и первые `limit` основных; поставщик выбирает `limit + 1` основных строк.

    Возвращает `(строки, есть_ещё)`; при ошибке поставщика — `None`.
    """
    try:
        with _time_limited():
            rows = provider.search(user, parsed, limit, offset)
    except Exception as exc:  # noqa: BLE001
        log.error("search provider failed: key=%s error=%s", provider.key, type(exc).__name__)
        return None
    pinned = [row for row in rows if row.pinned]
    main = [row for row in rows if not row.pinned]
    return pinned + main[:limit], len(main) > limit


def _groups(user, parsed: ParsedQuery, limit: int) -> list[Group]:
    if parsed.hint:
        return []
    groups = []
    for provider in providers(user):
        collected = _collect(provider, user, parsed, limit, 0)
        if collected is None or not collected[0]:
            continue
        rows, has_more = collected
        groups.append(Group(provider.key, provider.title, rows, has_more, limit if has_more else 0))
    return groups


def popup(user, parsed: ParsedQuery) -> list[Group]:
    """Всплывающая выдача: по `POPUP_LIMIT` строк в группе; на непустую подсказку — пусто."""
    return _groups(user, parsed, POPUP_LIMIT)


def page(user, parsed: ParsedQuery) -> list[Group]:
    """Страница результатов: по `PAGE_LIMIT` строк в группе; на непустую подсказку — пусто."""
    return _groups(user, parsed, PAGE_LIMIT)


def _provider(user, key: str) -> SearchProvider | None:
    for provider in providers(user):
        if provider.key == key:
            return provider
    return None


def more_group(user, parsed: ParsedQuery, key: str, offset: int) -> Group | None:
    """Следующая порция группы `key` со смещения `offset` (группа без строк тоже возвращается пустой); `None` —
    группа неизвестна, недоступна или упала."""
    if parsed.hint:
        return None
    provider = _provider(user, key)
    if provider is None:
        return None
    collected = _collect(provider, user, parsed, PAGE_LIMIT, max(offset, 0))
    if collected is None:
        return None
    rows, has_more = collected
    return Group(provider.key, provider.title, rows, has_more, max(offset, 0) + PAGE_LIMIT if has_more else 0)


def more(user, parsed: ParsedQuery, key: str, offset: int) -> list[SearchRow]:
    """Строки следующей порции группы; неизвестный или недоступный ключ и смещение за концом — пустой список."""
    group = more_group(user, parsed, key, offset)
    return group.rows if group else []


def count(user, parsed: ParsedQuery, key: str) -> Count | None:
    """Число группы; неизвестная, недоступная или упавшая группа и запрос с подсказкой — `None`."""
    if parsed.hint:
        return None
    provider = _provider(user, key)
    if provider is None:
        return None
    try:
        with _time_limited():
            number, capped = provider.count(user, parsed)
    except Exception as exc:  # noqa: BLE001
        log.error("search provider failed: key=%s error=%s", provider.key, type(exc).__name__)
        return None
    return Count(number, capped, f"{number}+" if capped else str(number))
