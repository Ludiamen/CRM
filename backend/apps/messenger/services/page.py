"""Название чата для списка, шапки и журнала (срез 008, T-8205/T-8207).

PLAN-008 «Список чатов и порядок», «Виды чатов и создание» (чат отдела); CONTRACT-008 § 5.4. Личный диалог
называется ФИО собеседника, чат отдела — именем узла через `org.services.structure.unit_refs` (в `Chat.title` его
нет, поэтому переименование отдела видно сразу), групповой и «Общий чат» — своим названием. Модели `org` не
импортируются, подразделения — публичная служба `org` под `apps.is_installed`.
"""
from django.apps import apps
from django.db.models import Q

from apps.messenger.models import Chat, ChatMember, Message

HISTORY_LIMIT = 50


def history(chat, before=None, *, limit: int = HISTORY_LIMIT):
    """Порция истории беседы по курсору `(created_at, id)`: старые — строго раньше, без `OFFSET` (FR-658).

    Возвращает `(messages, more)`; сообщения — от старых к новым для вывода, `more` — есть ли ещё более
    ранние. Без `before` — последние `limit` сообщений. Удалённые и системные входят: удалённое показывается
    пометкой, системная запись — своим текстом (FR-649, 657).
    """
    queryset = Message.objects.filter(chat=chat).select_related("author", "quote").prefetch_related("files")
    if before is not None:
        at, message_id = before
        queryset = queryset.filter(Q(created_at__lt=at) | Q(created_at=at, id__lt=message_id))
    fetched = list(queryset.order_by("-created_at", "-id")[:limit + 1])
    more = len(fetched) > limit
    messages = list(reversed(fetched[:limit]))
    return messages, more


def chat_title(chat, viewer=None) -> str:
    """Название чата по виду; у личного диалога — ФИО собеседника (`viewer` — чей это взгляд)."""
    kind = chat.kind
    if kind == Chat.Kind.PERSONAL:
        return _peer_name(chat, viewer)
    if kind == Chat.Kind.DEPARTMENT:
        return _unit_name(chat.unit_id)
    return chat.title or ""


def _peer_name(chat, viewer=None) -> str:
    """ФИО собеседника личного диалога: участник, отличный от смотрящего (или от создателя)."""
    other = getattr(viewer, "pk", None) or chat.created_by_id
    rows = ChatMember.objects.filter(chat=chat).select_related("user").order_by("id")
    row = next((item for item in rows if item.user_id != other), None)
    if row is None:
        row = rows.first()
    return row.user.full_name if row is not None else ""


def _unit_name(unit_id) -> str:
    if unit_id is None or not apps.is_installed("apps.org"):
        return ""

    from apps.org.services import structure

    ref = structure.unit_refs([unit_id]).get(int(unit_id))
    return ref.name if ref is not None else ""