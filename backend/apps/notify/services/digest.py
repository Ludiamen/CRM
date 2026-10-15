"""Публичный интерфейс уведомлений: сводка (PLAN-004, «Тихие часы и сводка»; CONTRACT-004, 6.11, доп. 14 и 29).

`build(user_id)` собирает накопленное за тихие часы (доставки `held`) в письмо и одно сообщение. Задание сборки ставит
обход, когда `digest_due_at` наступил.
"""
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from ..models import Delivery, Digest, UserNotifySettings
from . import dispatch, kinds, quiet
from .errors import NotifyError

log = logging.getLogger(__name__)

MESSAGE_CHANNELS = ("telegram", "max", "webpush")  # порядок выбора канала сообщения (FR-330)


def _relevant(row) -> bool:
    """Перепроверка вида: нет вида в каталоге — уведомление не актуально."""
    note = row.notification
    try:
        kind = kinds.get(note.kind)
    except NotifyError:
        return False
    return bool(kind.still_relevant(note.user_id, note.object_ref))


def _skip(row, reason: str) -> None:
    row.state = Delivery.State.SKIPPED
    row.reason = reason
    row.save(update_fields=["state", "reason"])


def build(user_id: int):
    """Сводка сотрудника: `Digest` или `None` (шаги (1)–(5) раздела 6.11 контракта)."""
    from . import delivery, mail

    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return None
    now = timezone.now()
    with transaction.atomic():
        held = list(Delivery.objects.select_for_update().select_related("notification")
                    .filter(notification__user_id=user_id, state=Delivery.State.HELD)
                    .order_by("notification__created_at", "notification_id", "pk"))
        # (1) заблокированный или уволенный; тихие часы
        if user.state != "active":
            reason = "user_blocked" if user.state == "blocked" else "user_dismissed"
            for row in held:
                _skip(row, reason)
            UserNotifySettings.objects.filter(user_id=user_id).update(digest_due_at=None)
            return None
        settings_row = UserNotifySettings.objects.filter(user_id=user_id).first()
        if not quiet.is_working(settings_row, now):
            dispatch.replan_digest(user_id)
            return None
        # (2) прочитанное и неактуальное
        used = []
        relevance: dict[int, bool] = {}
        for row in held:
            note = row.notification
            if note.read_at is not None:
                _skip(row, "read")
                continue
            if note.pk not in relevance:
                relevance[note.pk] = _relevant(row)
            if not relevance[note.pk]:
                _skip(row, "not_relevant")
                continue
            used.append(row)
        result = None
        if used:
            mails = [row for row in used if row.channel == Delivery.Channel.EMAIL]
            channel = next((c for c in MESSAGE_CHANNELS if any(row.channel == c for row in used)), None)
            messages = [row for row in used if row.channel == channel] if channel else []
            if mails or messages:
                ids = list(dict.fromkeys(row.notification_id for row in used))
                result = Digest.objects.create(user_id=user_id, created_at=now, count_email=len(mails),
                                               count_message=len(messages), notification_ids=ids)
                if mails:  # (3) письмо
                    letter = Delivery.objects.create(digest=result, channel=Delivery.Channel.EMAIL,
                                                     state=Delivery.State.SENT, attempts=1)
                    letter.mail_id = mail.queue_digest(letter)
                    letter.save(update_fields=["mail_id"])
                if messages:  # (4) одно сообщение в первый канал
                    chat = Delivery.objects.create(digest=result, channel=channel, state=Delivery.State.WAITING,
                                                   due_at=now, enqueued_at=now)
                    transaction.on_commit(lambda pk=chat.pk: delivery.enqueue([pk]))
            # (5) все использованные — в сводке, в том числе доставки невыбранных каналов (доп. 14)
            Delivery.objects.filter(pk__in=[row.pk for row in used]).update(state=Delivery.State.DIGESTED)
        UserNotifySettings.objects.filter(user_id=user_id).update(digest_due_at=None)
        return result
