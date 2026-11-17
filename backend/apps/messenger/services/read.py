"""Отметки прочтения и «Прочитали N из M» (срез 008, T-8211; CONTRACT-008, 2.2, 3.5, 5.3).

PLAN-008 «Прочтение и счётчики». Отметка — `min(max(прежняя, at), now())`: повтор с меньшим `at` её не
уменьшает, будущий `at` обрезается до теперь. Открытие беседы и `POST …/read/` публикуют `object.viewed` с
`object_ref="messenger.chat:<id>"` (подписчик `notify` гасит уведомления этого чата этому сотруднику). «Прочитали
N из M» — N отметок не раньше сообщения среди состава без автора, M — этот состав (уволенные и вышедшие не входят).
"""
from datetime import datetime

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.core import events
from apps.messenger.models import ChatRead, Message
from apps.messenger.services import members, unread

OBJECT_TYPE = "messenger.chat"


def parse_at(value):
    """`at` из формы: ISO или `None`/неверное — теперь; будущее обрезается до теперь (10.1)."""
    now = timezone.now()
    if not value:
        return now
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return now
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return min(moment, now)


def mark(chat, user, at=None) -> ChatRead:
    """Поставить отметку прочтения: `min(max(прежняя, at), now())`, сброс чисел и `object.viewed` (FR-659)."""
    if not members.is_member(user, chat):
        raise PermissionDenied
    now = timezone.now()
    moment = min(at or now, now)
    row = ChatRead.objects.filter(chat=chat, user=user).first()
    if row is None:
        row = ChatRead.objects.create(chat=chat, user=user, last_read_at=moment)
    elif moment > row.last_read_at:
        row.last_read_at = moment
        row.save(update_fields=["last_read_at"])
    unread.invalidate([user.pk])
    events.publish("object.viewed", object_ref=f"{OBJECT_TYPE}:{chat.pk}", user_id=user.pk)
    return row


def line(chat, message) -> tuple[int, int]:
    """«Прочитали N из M»: отметки не раньше сообщения среди состава без автора (FR-659)."""
    if message is None:
        return 0, 0
    audience = members.members(chat) - {message.author_id}
    if not audience:
        return 0, 0
    read = (ChatRead.objects
            .filter(chat=chat, user_id__in=audience, last_read_at__gte=message.created_at)
            .count())
    return read, len(audience)


def last_own(chat, user):
    """Последнее живое своё сообщение чата: строка «Прочитали» стоит только под ним (FR-659)."""
    return (Message.objects.filter(chat=chat, author=user, deleted_at__isnull=True)
            .order_by("-created_at", "-id").first())