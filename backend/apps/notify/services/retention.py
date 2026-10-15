"""Публичный интерфейс уведомлений: ночное удаление старых данных (PLAN-004, «Хранение, увольнение, блокировка»;
CONTRACT-004, 6.15).

Уведомления и сводки старше срока хранения (`NotifySettings.retention_days`) удаляются порциями по `BATCH`, доставки
уходят каскадом; история заявки остаётся в заявке. Просроченные и использованные коды привязки удаляет
`binding.purge_expired_codes`; служебные записи диалогов `BotChat` без привязки живут 30 суток.
"""
import datetime
import logging

from django.db import models, transaction
from django.utils import timezone

from ..models import BotChat, ChatBinding, Digest, Notification
from . import settings

log = logging.getLogger(__name__)

BATCH = 1000  # размер порции удаления
BOTCHAT_DAYS = 30  # срок хранения записей диалогов без привязки (решение плана, в FR-338 не входят)


def _delete_in_batches(model, cutoff: datetime.datetime) -> int:
    """Удаляет записи `model` с `created_at < cutoff` порциями по `BATCH`; порция — своя транзакция.

    Цикл кончается, когда порция короче `BATCH`. Возвращает число удалённых записей модели (без каскада).
    """
    total = 0
    while True:
        ids = list(model.objects.filter(created_at__lt=cutoff).order_by("pk").values_list("pk", flat=True)[:BATCH])
        if not ids:
            break
        with transaction.atomic():
            model.objects.filter(pk__in=ids).delete()
        total += len(ids)
        if len(ids) < BATCH:
            break
    return total


def run() -> dict[str, int]:
    """Ночное удаление; итог — число удалённых: `notifications`, `digests`, `codes`, `botchats`."""
    from . import binding

    now = timezone.now()
    cutoff = now - datetime.timedelta(days=settings.get().retention_days)
    notifications = _delete_in_batches(Notification, cutoff)
    digests = _delete_in_batches(Digest, cutoff)
    codes = binding.purge_expired_codes()
    bound = ChatBinding.objects.filter(channel=models.OuterRef("channel"), chat_id=models.OuterRef("chat_id"))
    stale = BotChat.objects.filter(started_at__lt=now - datetime.timedelta(days=BOTCHAT_DAYS)).annotate(
        has_binding=models.Exists(bound)).filter(has_binding=False)
    ids = list(stale.values_list("pk", flat=True))
    botchats = BotChat.objects.filter(pk__in=ids).delete()[1].get(BotChat._meta.label, 0) if ids else 0
    result = {"notifications": notifications, "digests": digests, "codes": codes, "botchats": botchats}
    log.info("Ночное удаление уведомлений: %s", result)
    return result
