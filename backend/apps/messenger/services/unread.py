"""Числа непрочитанного по чатам и общее (срез 008, T-8211; CONTRACT-008, 5.1, 5.3).

PLAN-008 «Прочтение и счётчики». Один SQL-запрос считает числа всех видимых чатов сотрудника (NFR-703): у
личного и группового база отсчёта — `GREATEST(joined_at, ChatRead.last_read_at)`, у чата отдела и «Общего чата» —
только отметка (без неё 0). Свои, системные и удалённые сообщения не считаются. Числа кэшируются на
`COUNT_CACHE_SECONDS` с версией и сбрасываются при отправке, прочтении и смене состава (`invalidate`); подписка
на `access.changed` — в `apps.py`.
"""
from django.apps import apps
from django.core.cache import cache
from django.db import connection

from apps.core.models import UserState

COUNT_CACHE_SECONDS = 5
_VERSION_KEY = "messenger:unread:version"
_COUNT_KEY = "messenger:unread:count:{version}:{user_id}"
HIDDEN_STATES = (UserState.DISMISSED, UserState.INVITED)


def counts(user) -> dict[int, int]:
    """Числа непрочитанного по чатам: `{chat_id: count}` для чатов с ненулевым числом; кэш 5 с.

    Попадание в кэш — без запросов к базе: цепочка узлов и «Общий чат» читаются только при промахе
    (`test_capacity` считает запросы страницы).
    """
    user_id = getattr(user, "pk", None)
    if user_id is None or getattr(user, "state", None) in HIDDEN_STATES:
        return {}
    cached = cache.get(_count_key(user_id))
    if cached is not None:
        return dict(cached)
    return _counts_with(user_id, _chain_ids(user_id), _general_enabled())


def counts_for(people) -> dict[int, dict[int, int]]:
    """Числа для нескольких сотрудников: `{user_id: {chat_id: count}}` (T-8304).

    Правила те же, что у `counts`, но общие данные — цепочки узлов (два запроса на всех) и включённость
    «Общего чата» — читаются один раз и только для тех, у кого нет кэша. Значения кладутся в тот же кэш.
    """
    people = [person for person in people if getattr(person, "pk", None) is not None]
    if not people:
        return {}
    result: dict[int, dict[int, int]] = {}
    missing: list[int] = []
    for person in people:
        cached = cache.get(_count_key(person.pk))
        if cached is not None:
            result[person.pk] = dict(cached)
        else:
            missing.append(person.pk)
    if missing:
        chains = _chains(missing)
        general = _general_enabled()
        for user_id in missing:
            result[user_id] = _counts_with(user_id, chains[user_id], general)
    return result


def total(user) -> int:
    """Общее число непрочитанного — сумма по чатам (число пункта меню)."""
    return sum(counts(user).values())


def badge(user) -> int:
    """Число пункта меню «Мессенджер»: то же, что `total` (CONTRACT-008, 5.3)."""
    return total(user)


def on_access_changed(user_ids=None, **extra) -> None:
    """Обработчик шины `access.changed`: перевод, приём и увольнение меняют видимость и числа (3.5)."""
    invalidate(None if user_ids is None else user_ids)


def invalidate(user_ids=None) -> None:
    """Сбросить числа: `None` — все (версия), иначе только перечисленным сотрудникам."""
    if user_ids is None:
        cache.set(_VERSION_KEY, _version() + 1, timeout=None)
        return
    ids = {int(user_id) for user_id in user_ids if user_id is not None}
    if ids:
        version = _version()
        cache.delete_many([_COUNT_KEY.format(version=version, user_id=user_id) for user_id in ids])


def _version() -> int:
    version = cache.get(_VERSION_KEY)
    if version is None:
        version = 1
        cache.set(_VERSION_KEY, version, timeout=None)
    return version


def _count_key(user_id: int) -> str:
    return _COUNT_KEY.format(version=_version(), user_id=user_id)


def _unit_chain(user) -> frozenset[int]:
    if not apps.is_installed("apps.org"):
        return frozenset()

    from apps.org.services import structure

    return structure.unit_chain_ids(user)


def _general_enabled() -> bool:
    """Включён ли «Общий чат»; читается строка напрямую, чтобы числа не звали службу настроек на каждой странице."""
    from apps.messenger.models import MessengerSettings

    value = MessengerSettings.objects.filter(pk=1).values_list("general_chat_enabled", flat=True).first()
    return True if value is None else bool(value)


def _counts_with(user_id: int, chain, general: bool) -> dict[int, int]:
    """Числа одного сотрудника по готовым общим данным: кэш 5 с, иначе один запрос `_fetch`."""
    key = _count_key(user_id)
    cached = cache.get(key)
    if cached is not None:
        return dict(cached)
    result = {chat_id: int(count) for chat_id, count in _fetch(user_id, chain=chain, general=general) if count}
    cache.set(key, result, COUNT_CACHE_SECONDS)
    return result


def _chains(user_ids: list[int]) -> dict[int, frozenset[int]]:
    """Цепочки узлов многих сотрудников пачкой; без `org` — пустые."""
    if not apps.is_installed("apps.org"):
        return {user_id: frozenset() for user_id in user_ids}

    from apps.org.services import structure

    return structure.unit_chains(user_ids)


def _fetch(user_id: int, *, chain=None, general: bool | None = None) -> list:
    """Один запрос: номер чата и число непрочитанных; значения — параметры SQL (NFR-703)."""
    sql = """
SELECT c.id, COALESCE(unread.count, 0) AS count
FROM "messenger_chat" AS c
LEFT JOIN LATERAL (
    SELECT CASE
        WHEN c.kind IN ('personal', 'group') THEN (
            SELECT GREATEST(cm.joined_at, COALESCE(r.last_read_at, cm.joined_at))
            FROM "messenger_chatmember" AS cm
            LEFT JOIN "messenger_chatread" AS r ON r.chat_id = c.id AND r.user_id = %s
            WHERE cm.chat_id = c.id AND cm.user_id = %s AND cm.left_at IS NULL
        )
        ELSE COALESCE((SELECT r.last_read_at
                       FROM "messenger_chatread" AS r
                       WHERE r.chat_id = c.id AND r.user_id = %s),
                      '-infinity'::timestamptz)
    END AS at,
    CASE WHEN c.kind IN ('personal', 'group') THEN (
        SELECT cm.joined_at
        FROM "messenger_chatmember" AS cm
        WHERE cm.chat_id = c.id AND cm.user_id = %s
    ) ELSE NULL END AS joined,
    (SELECT r.last_read_at FROM "messenger_chatread" AS r
     WHERE r.chat_id = c.id AND r.user_id = %s) AS read_at
) AS base ON TRUE
LEFT JOIN LATERAL (
    SELECT count(*) AS count
    FROM "messenger_message" AS m
    WHERE m.chat_id = c.id
      AND m.deleted_at IS NULL
      AND m.is_system = false
      AND m.author_id IS DISTINCT FROM %s
      AND base.at IS NOT NULL
      AND (
          m.created_at > base.at
          OR (m.created_at = base.at AND base.joined IS NOT NULL AND base.at = base.joined
              AND (base.read_at IS NULL OR base.read_at < base.joined))
      )
) AS unread ON TRUE
WHERE (
    (
        c.kind IN ('personal', 'group')
        AND EXISTS (
            SELECT 1
            FROM "messenger_chatmember" AS cm
            WHERE cm.chat_id = c.id AND cm.user_id = %s AND cm.left_at IS NULL
        )
    )
    OR (c.kind = 'department' AND c.unit_id = ANY(%s))
    OR (c.kind = 'general' AND %s)
)
"""
    with connection.cursor() as cursor:
        cursor.execute(sql, [user_id, user_id, user_id, user_id, user_id, user_id, user_id,
                             list(_chain_ids(user_id)) if chain is None else list(chain),
                             _general_enabled() if general is None else general])
        return cursor.fetchall()


def _chain_ids(user_id: int) -> frozenset[int]:
    """Цепочка узлов сотрудника по номеру (для SQL видимости чатов отдела)."""
    from apps.core.models import User

    person = User.objects.filter(pk=user_id).first()
    return _unit_chain(person) if person is not None else frozenset()