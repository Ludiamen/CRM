"""Поиск мессенджера: поставщик «Мессенджер» и поиск по беседе (срез 008, T-8219; CONTRACT-008, 5.4, 9).

PLAN-008 «Поиск». Векторы `search` заполняются в отправке, правке и удалении (`services.messages`); здесь —
поставщик `("messenger", "Мессенджер", 61)` и поиск по беседе. Видимость считается тем же SQL, что и список:
участие в личном и групповом, цепочка узлов для чата отдела, включённый «Общий чат». Слова запроса и цепочка узлов
уходят параметрами (NFR-703), потолок числа — 300, строки — «<чат>, <ФИО>, <дата по Москве> — <отрывок 100>».
"""
from django.apps import apps
from django.db import connection

from apps.core.extensions import SearchProvider, SearchRow
from apps.core.models import UserState
from apps.core.services import text as core_text
from apps.core.widgets import MOSCOW

COUNT_CEILING = 300
CHAT_LIMIT = 50
HIGHLIGHT_START = "<b>"
HIGHLIGHT_STOP = "</b>"
ACTIVE_STATES = (UserState.ACTIVE, UserState.BLOCKED)

_VISIBILITY = """
        AND (
            (
                c.kind IN ('personal', 'group')
                AND EXISTS (
                    SELECT 1 FROM "messenger_chatmember" AS cm
                    WHERE cm.chat_id = c.id AND cm.user_id = %s AND cm.left_at IS NULL
                )
            )
            OR (c.kind = 'department' AND c.unit_id = ANY(%s))
            OR (c.kind = 'general' AND %s)
        )
"""

_SEARCH_SQL = """
SELECT m.id, m.chat_id, m.created_at, u.full_name, m.text
FROM "messenger_message" AS m
JOIN "messenger_chat" AS c ON c.id = m.chat_id
JOIN "core_user" AS u ON u.id = m.author_id
WHERE m.deleted_at IS NULL
  AND m.is_system = false
  AND m.search @@ to_tsquery('russian', %s)
""" + _VISIBILITY + """
ORDER BY m.created_at DESC, m.id DESC
LIMIT %s OFFSET %s
"""

_COUNT_SQL = """
SELECT count(*) FROM (
    SELECT 1
    FROM "messenger_message" AS m
    JOIN "messenger_chat" AS c ON c.id = m.chat_id
    WHERE m.deleted_at IS NULL AND m.is_system = false
      AND m.search @@ to_tsquery('russian', %s)
""" + _VISIBILITY + """
    LIMIT %s
) AS hits
"""

_CHAT_SQL = """
SELECT m.id, m.created_at, u.full_name,
       ts_headline('russian', m.text, to_tsquery('russian', %s),
                   'StartSel=<b>, StopSel=</b>, MaxFragments=1, MinWords=1, MaxWords=12')
FROM "messenger_message" AS m
JOIN "core_user" AS u ON u.id = m.author_id
WHERE m.chat_id = %s AND m.deleted_at IS NULL AND m.is_system = false
  AND m.search @@ to_tsquery('russian', %s)
ORDER BY m.created_at DESC, m.id DESC
LIMIT %s
"""


def search_providers() -> list:
    """Запись точки `search_providers`: группа «Мессенджер» после «Ленты» (order 61)."""
    return [SearchProvider(key="messenger", title="Мессенджер", order=61,
                           search=search, count=count, available=available)]


def available(user) -> bool:
    """Группа видна действующему и заблокированному сотруднику (уволенному портал закрыт)."""
    return getattr(user, "pk", None) is not None and getattr(user, "state", None) in ACTIVE_STATES


def search(user, parsed, limit: int, offset: int) -> list:
    """Строки выдачи: «<чат>, <ФИО>, <дата> — <отрывок>», ссылка на сообщение (FR-668)."""
    if not _query(parsed) or not available(user):
        return []
    with connection.cursor() as cursor:
        cursor.execute(_SEARCH_SQL, _params(user, parsed, [limit, offset]))
        rows = cursor.fetchall()
    chats = _chats([row[1] for row in rows])
    from apps.messenger.services import page

    result = []
    for message_id, chat_id, created_at, author, raw in rows:
        chat = chats.get(chat_id)
        if chat is None:
            continue
        when = created_at.astimezone(MOSCOW).strftime("%d.%m.%Y")
        snippet = core_text.snippet(raw or "", 100)
        title = f"{page.chat_title(chat, user)}, {author}, {when} — {snippet}"
        result.append(SearchRow(title=title, subtitle="Мессенджер",
                                url=f"/messenger/chats/{chat_id}/#m{message_id}"))
    return result


def count(user, parsed) -> tuple[int, bool]:
    """Число сообщений с потолком 300: `(300, True)`, если найдено больше (FR-668)."""
    if not _query(parsed) or not available(user):
        return 0, False
    with connection.cursor() as cursor:
        cursor.execute(_COUNT_SQL, [_query_text(parsed), user.pk, list(_chain(user)),
                                    _general_enabled(), COUNT_CEILING + 1])
        found = cursor.fetchone()[0]
    return min(found, COUNT_CEILING), found > COUNT_CEILING


def chat_search(user, chat, parsed, *, limit: int = CHAT_LIMIT) -> list:
    """Поиск по беседе: подсветка `ts_headline`, время и якорь `#m<id>` (FR-668); чужие сообщения не входят."""
    if not _query(parsed):
        return []
    with connection.cursor() as cursor:
        cursor.execute(_CHAT_SQL, [_query_text(parsed), chat.pk, _query_text(parsed), limit])
        rows = cursor.fetchall()
    return [{"id": message_id, "at": created_at, "author": author, "headline": highlighted}
            for message_id, created_at, author, highlighted in rows]


def _query_text(parsed) -> str:
    """Строка `to_tsquery` из слов запроса: слова — параметром, префиксных операторов нет (NFR-703)."""
    return " & ".join(parsed.words)


def _query(parsed) -> bool:
    """Пустой запрос и стоп-слова (`to_tsquery` из одних стоп-слов пуст) — выдача пуста без ошибки."""
    return bool(parsed is not None and parsed.hint == "" and parsed.raw)


def _params(user, parsed, tail) -> list:
    chain = _chain(user)
    params = [_query_text(parsed), user.pk, list(chain), _general_enabled()]
    return params + list(tail)


def _chain(user) -> frozenset[int]:
    if not apps.is_installed("apps.org"):
        return frozenset()

    from apps.org.services import structure

    return structure.unit_chain_ids(user)


def _general_enabled() -> bool:
    from apps.messenger.services import messenger_settings

    return bool(messenger_settings.get().general_chat_enabled)


def _chats(chat_ids) -> dict:
    from apps.messenger.models import Chat

    wanted = {int(chat_id) for chat_id in chat_ids}
    return {chat.pk: chat for chat in Chat.objects.filter(pk__in=wanted)}