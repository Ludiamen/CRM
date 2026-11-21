"""Кому и какое уведомление о сообщении чата (срез 008, T-8217; CONTRACT-008, 5.3, 7.2).

PLAN-008 «Уведомления». Получатели — действующие участники чата без автора; упомянутый получает только
«Упомянул вас в чате», остальные — «Новое сообщение в чате». Текст без отрывка переписки: «<ФИО>: новое сообщение в
чате «<название>»» и «<ФИО> упомянул(а) вас в чате «<название>»». Ссылка — на сообщение, `object_ref` — чат
(`messenger.chat:<id>`), поэтому склейка и `object.viewed` работают по чату. `still_relevant` истинно, пока чат виден
получателю и в нём есть непрочитанные.
"""
import re

from apps.core.models import User, UserState

REF = re.compile(r"messenger\.chat:([1-9]\d{0,18})")
RECIPIENT_STATES = (UserState.ACTIVE,)


def decide(message) -> dict[int, tuple[str, str]]:
    """Решения по одному сообщению: `{user_id: (код вида, текст)}` (FR-663, 664, 666)."""
    from apps.messenger.models import Chat
    from apps.messenger.services import members, mentions
    from apps.messenger.services import page as page_service

    chat = message.chat
    author_id = message.author_id
    if author_id is None or message.deleted_at is not None:
        return {}
    audience = {user_id for user_id in members.members(chat) if user_id != author_id}
    if not audience:
        return {}
    states = dict(User.objects.filter(pk__in=audience).values_list("pk", "state"))
    audience = {user_id for user_id in audience if states.get(user_id) in RECIPIENT_STATES}
    people, _ = mentions.extract(message.text)
    mentioned = audience & set(people)
    author = User.objects.filter(pk=author_id).first()
    author_name = author.full_name if author is not None else ""
    result = {}
    for user_id in sorted(audience):
        person = User.objects.filter(pk=user_id).first()
        title = page_service.chat_title(chat, person)
        if user_id in mentioned:
            result[user_id] = ("messenger.mention",
                               f"{author_name} упомянул(а) вас в чате «{title}»")
        else:
            result[user_id] = ("messenger.message",
                               f"{author_name}: новое сообщение в чате «{title}»")
    return result


def message_coalesce_text(user_id: int, object_ref: str, since) -> str:
    """Текст склейки: сколько сообщений других пришло в чат после первого непрочитанного (FR-666)."""
    from apps.messenger.models import Chat, Message
    from apps.messenger.services import page as page_service

    chat_id = _chat_id(object_ref)
    chat = Chat.objects.filter(pk=chat_id).first() if chat_id else None
    if chat is None:
        return ""
    count = (Message.objects.filter(chat=chat, deleted_at__isnull=True)
             .exclude(author_id=user_id).filter(created_at__gt=since).count() + 1)
    person = User.objects.filter(pk=user_id).first()
    return f"Новых сообщений: {count} в чате «{page_service.chat_title(chat, person)}»"


def message_coalesce_texts(items) -> list[str]:
    """Тексты склейки пачкой: `items` — `[(user_id, object_ref, since), …]`, ответ — в том же порядке (T-8304).

    Тот же текст, что у `message_coalesce_text`: «Новых сообщений: N в чате «Название»». Числа считаются одним
    запросом на всех получателей чата, название — один раз на чат; у личного диалога — по собеседнику.
    """
    from apps.messenger.models import Chat
    from apps.messenger.services import page as page_service

    result = [""] * len(items)
    by_chat: dict[int, list[int]] = {}
    for index, (user_id, object_ref, _since) in enumerate(items):
        chat_id = _chat_id(object_ref)
        if chat_id is None:
            continue
        by_chat.setdefault(chat_id, []).append(index)
    for chat_id, indexes in by_chat.items():
        chat = Chat.objects.filter(pk=chat_id).first()
        if chat is None:
            continue
        users = [items[index][0] for index in indexes]
        counts = _coalesce_counts(chat_id, users, [items[index][2] for index in indexes])
        titles = _coalesce_titles(chat, users)
        for index in indexes:
            user_id = items[index][0]
            result[index] = f"Новых сообщений: {counts.get(user_id, 0) + 1} в чате «{titles.get(user_id, '')}»"
    return result


def _coalesce_counts(chat_id: int, users: list[int], since: list) -> dict[int, int]:
    """Сколько сообщений других пришло после первого непрочитанного — одним запросом по всем получателям."""
    from django.db import connection

    sql = """
SELECT p.user_id, count(m.id) AS count
FROM unnest(%s::int[], %s::timestamptz[]) AS p(user_id, since)
LEFT JOIN "messenger_message" AS m
    ON m.chat_id = %s
   AND m.deleted_at IS NULL
   AND m.author_id IS NOT NULL
   AND m.author_id IS DISTINCT FROM p.user_id
   AND m.created_at > p.since
GROUP BY p.user_id
"""
    with connection.cursor() as cursor:
        cursor.execute(sql, [users, since, chat_id])
        return {int(user_id): int(count) for user_id, count in cursor.fetchall()}


def _coalesce_titles(chat, users: list[int]) -> dict[int, str]:
    """Названия чата для каждого получателя: у личного диалога — свой собеседник, у остальных — имя чата."""
    from apps.messenger.models import Chat
    from apps.messenger.services import page as page_service

    if chat.kind != Chat.Kind.PERSONAL:
        title = page_service.chat_title(chat, None)
        return {user_id: title for user_id in users}
    people = {person.pk: person for person in User.objects.filter(pk__in=users)}
    return {user_id: page_service.chat_title(chat, people.get(user_id)) for user_id in users}


message_coalesce_text.many = message_coalesce_texts


def still_relevant(user_id: int, object_ref: str) -> bool:
    """Письмо и сводка идут, пока чат виден получателю и в нём есть непрочитанные (FR-663, 666)."""
    from apps.messenger.services import members, unread

    chat_id = _chat_id(object_ref)
    if chat_id is None:
        return False
    person = User.objects.filter(pk=user_id).first()
    if person is None or not members.visible_chats(person).filter(pk=chat_id).exists():
        return False
    return unread.counts(person).get(chat_id, 0) > 0


def _chat_id(object_ref: str) -> int | None:
    if not isinstance(object_ref, str):
        return None
    match = REF.fullmatch(object_ref)
    return int(match.group(1)) if match else None