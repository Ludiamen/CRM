"""Название чата для списка, шапки и журнала (срез 008, T-8205/T-8207).

PLAN-008 «Список чатов и порядок», «Виды чатов и создание» (чат отдела); CONTRACT-008 § 5.4. Личный диалог
называется ФИО собеседника, чат отдела — именем узла через `org.services.structure.unit_refs` (в `Chat.title` его
нет, поэтому переименование отдела видно сразу), групповой и «Общий чат» — своим названием. Модели `org` не
импортируются, подразделения — публичная служба `org` под `apps.is_installed`.
"""
from django.apps import apps

from apps.messenger.models import Chat, ChatMember


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