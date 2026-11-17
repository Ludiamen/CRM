"""Создание личного, группового и общего чата, выборка списка (срез 008, T-8202).

CONTRACT-008 § 5.1; PLAN-008, «Виды чатов и создание», «Список чатов и порядок». Личный диалог — один на пару
(`pair_key = "<меньший id>:<больший id>"`) под уникальным индексом, гонка двух созданий перехватывается и строка
читается заново. Список видимых чатов собирается **одним** запросом с `LATERAL`: название, превью последнего
неудалённого сообщения (отрывок 100 знаков), время, число непрочитанных; порядок
`COALESCE(last_message_at, created_at) DESC, id DESC` (FR-644). SQL — литералы с `%s`, значения уходят параметрами
(NFR-703); модели `org` не импортируются, имя узла берётся из таблицы по литералу под `apps.is_installed`.
"""
from datetime import datetime
from typing import NamedTuple

from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.core.models import User, UserState
from apps.core.services import text as core_text
from apps.messenger.models import Chat, ChatMember
from apps.messenger.services.errors import MessengerError

PREVIEW_LIMIT = 100
TITLE_LIMIT = 200
# Участники группового чата — «действующие»: уволенный и приглашённый не подходят (PLAN-008, «Виды чатов и создание»).
NON_PARTICIPANT_STATES = (UserState.DISMISSED, UserState.INVITED)
HIDDEN_STATES = (UserState.DISMISSED, UserState.INVITED)


class Row(NamedTuple):
    """Строка списка чатов: номер, вид, название, превью, время последнего сообщения и число непрочитанных."""

    id: int
    kind: str
    title: str
    preview: str
    at: datetime
    unread: int
    has_unread: bool


def personal(user, peer) -> Chat:
    """Личный диалог пары; второй диалог не появляется (FR-645).

    `pair_key` — «<меньший id>:<больший id>», строка берётся `get_or_create` под уникальным индексом; нарушение
    уникальности при гонке перехватывается, и строка читается заново. С уволенным диалог не создаётся.
    """
    if getattr(peer, "state", None) == UserState.DISMISSED:
        raise MessengerError("dismissed", field="user")

    low, high = sorted((user.pk, peer.pk))
    pair_key = f"{low}:{high}"
    now = timezone.now()
    lookup = {"kind": Chat.Kind.PERSONAL, "pair_key": pair_key}
    try:
        chat, created = Chat.objects.get_or_create(
            **lookup, defaults={"title": "", "created_by": user, "created_at": now})
    except IntegrityError:
        # Параллельный запрос уже вставил диалог: читаем его, второй строки не появляется.
        chat = Chat.objects.get(**lookup)
        created = False

    if created:
        ChatMember.objects.bulk_create(
            [
                ChatMember(chat=chat, user=user, is_creator=False, joined_at=now),
                ChatMember(chat=chat, user=peer, is_creator=False, joined_at=now),
            ],
            ignore_conflicts=True,
        )
    else:
        for person in (user, peer):
            _ensure_member(chat, person, now)
    return chat


def create_group(creator, title: str, members=()) -> Chat:
    """Групповой чат: название 1–200 после среза пробелов, участники — действующие, создатель входит сам (FR-646)."""
    clean = (title or "").strip()
    if not 1 <= len(clean) <= TITLE_LIMIT:
        raise MessengerError("title_range", field="title")

    wanted = _user_ids(members)
    if not wanted:
        raise MessengerError("no_members", field="members")
    people = list(User.objects.filter(pk__in=wanted))
    if len(people) != len(wanted):
        raise MessengerError("no_members", field="members")
    if any(person.state in NON_PARTICIPANT_STATES for person in people):
        raise MessengerError("dismissed", field="members")
    others = [person for person in people if person.pk != creator.pk]
    if not others:
        raise MessengerError("no_members", field="members")

    now = timezone.now()
    with transaction.atomic():
        chat = Chat.objects.create(kind=Chat.Kind.GROUP, title=clean, created_by=creator, created_at=now)
        rows = [ChatMember(chat=chat, user=creator, is_creator=True, joined_at=now)]
        rows.extend(ChatMember(chat=chat, user=person, is_creator=False, joined_at=now) for person in others)
        ChatMember.objects.bulk_create(rows)
    return chat


def general() -> Chat | None:
    """Единственная строка «Общего чата» (или `None`, если её нет); включённость проверяет `members.visible_chats`."""
    return Chat.objects.filter(kind=Chat.Kind.GENERAL).first()


def rows(user, q: str = "") -> list[Row]:
    """Список видимых чатов одним запросом с `LATERAL` (FR-644, NFR-703).

    Число SQL-запросов не зависит от числа чатов. Непрочитанное: у личного и группового — от `joined_at` (или более
    поздней отметки `ChatRead`), у чата отдела и «Общего чата» — только после отметки, без неё 0 (PLAN-008,
    «Прочтение»). Свои и удалённые сообщения не считаются. `q` фильтрует название и ФИО собеседника параметром SQL.
    """
    user_id = getattr(user, "pk", None)
    if user_id is None or getattr(user, "state", None) in HIDDEN_STATES:
        return []

    query = (q or "").strip()
    chain = _unit_chain(user)
    sql = _rows_sql(apps.is_installed("apps.org"))
    params = [
        user_id,                    # название личного диалога — ФИО собеседника
        user_id, user_id, user_id,  # база отсчёта непрочитанного
        user_id,                    # свои сообщения не считаются
        user_id,                    # участие в личном и групповом
        list(chain),                # цепочка узлов сотрудника
        _general_enabled(),         # «Общий чат» только включённый
        query,                      # пустой запрос — без фильтра
        f"%{query}%",               # шаблон фильтра названия и ФИО
    ]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        fetched = cursor.fetchall()

    return [
        Row(
            id=row_id,
            kind=kind,
            title=title or "",
            preview=core_text.snippet(preview or "", PREVIEW_LIMIT),
            at=at,
            unread=int(unread),
            has_unread=int(unread) > 0,
        )
        for row_id, kind, title, preview, at, unread in fetched
    ]


def list_for(user, q: str = "") -> list[Row]:
    """То же, что `rows` — имя из TASKS-008 T-8202; оставлены оба, чтобы службу звали по контракту и по задаче."""
    return rows(user, q)


def _ensure_member(chat, person, now) -> None:
    """Строка участника личного диалога; вернувшегося (вышел ранее) возвращает с новым `joined_at`."""
    row, created = ChatMember.objects.get_or_create(
        chat=chat, user=person, defaults={"is_creator": False, "joined_at": now})
    if not created and row.left_at is not None:
        ChatMember.objects.filter(pk=row.pk).update(left_at=None, joined_at=now)


def _user_ids(values) -> list[int]:
    """Номера сотрудников из формы (`members`) или объектов: положительные целые без повторов."""
    result: list[int] = []
    for value in values or ():
        raw = getattr(value, "pk", value)
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in result:
            result.append(number)
    return result


def _unit_chain(user) -> frozenset[int]:
    if not apps.is_installed("apps.org"):
        return frozenset()

    from apps.org.services import structure

    return structure.unit_chain_ids(user)


def _general_enabled() -> bool:
    from apps.messenger.services import messenger_settings

    return bool(messenger_settings.get().general_chat_enabled)


# --- один запрос списка: SQL — литералы с `%s` (NFR-703) -----------------------------------------------------------
#
# Название чата отдела — имя узла, переименование видно сразу. Без `apps.org` отдельских чатов не видно, поэтому
# вариант без обращения к таблице узлов просто не нужен: подставляется пустая строка. Собираются три литерала
# (без f-строк), чтобы не зависеть от наличия таблицы `org_unit`.

_ROWS_SQL_HEAD = """
SELECT row.id, row.kind, row.title_text AS title, row.preview, row.at, row.unread
FROM (
    SELECT c.id, c.kind, c.last_message_at, c.created_at,
           CASE c.kind
               WHEN 'personal' THEN (
                   SELECT u.full_name
                   FROM "messenger_chatmember" AS cm
                   JOIN "core_user" AS u ON u.id = cm.user_id
                   WHERE cm.chat_id = c.id AND cm.user_id <> %s
                   ORDER BY cm.id
                   LIMIT 1
               )
               WHEN 'department' THEN
"""

_ROWS_SQL_UNIT_TITLE = '(SELECT un.name FROM "org_unit" AS un WHERE un.id = c.unit_id)'
_ROWS_SQL_EMPTY_TITLE = "''"

_ROWS_SQL_TAIL = """
               ELSE c.title
           END AS title_text,
           COALESCE(preview.text, '') AS preview,
           COALESCE(c.last_message_at, c.created_at) AS at,
           unread.count AS unread
    FROM "messenger_chat" AS c
    LEFT JOIN LATERAL (
        SELECT m.text
        FROM "messenger_message" AS m
        WHERE m.chat_id = c.id AND m.deleted_at IS NULL
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT 1
    ) AS preview ON TRUE
    LEFT JOIN LATERAL (
        SELECT CASE
            WHEN c.kind IN ('personal', 'group') THEN (
                SELECT GREATEST(cm.joined_at, COALESCE(r.last_read_at, cm.joined_at))
                FROM "messenger_chatmember" AS cm
                LEFT JOIN "messenger_chatread" AS r ON r.chat_id = c.id AND r.user_id = %s
                WHERE cm.chat_id = c.id AND cm.user_id = %s
            )
            ELSE (
                SELECT r.last_read_at
                FROM "messenger_chatread" AS r
                WHERE r.chat_id = c.id AND r.user_id = %s
            )
        END AS at
    ) AS base ON TRUE
    LEFT JOIN LATERAL (
        SELECT count(*) AS count
        FROM "messenger_message" AS m
        WHERE m.chat_id = c.id
          AND m.deleted_at IS NULL
          AND m.author_id IS DISTINCT FROM %s
          AND base.at IS NOT NULL
          AND m.created_at > base.at
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
) AS row
WHERE (%s = '' OR row.title_text ILIKE %s)
ORDER BY COALESCE(row.last_message_at, row.created_at) DESC, row.id DESC
"""


def _rows_sql(with_unit_title: bool) -> str:
    """Полный текст запроса списка: вариант с именем узла (есть `apps.org`) или с пустой строкой."""
    return _ROWS_SQL_HEAD + (_ROWS_SQL_UNIT_TITLE if with_unit_title else _ROWS_SQL_EMPTY_TITLE) + _ROWS_SQL_TAIL