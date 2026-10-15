"""Публичный интерфейс уведомлений: очистка при увольнении и возврате на работу (PLAN-004, «Хранение, увольнение,
блокировка»; CONTRACT-004, 6.15).

Подписчики событий ядра `core.user_dismissed` и `core.user_rehired` (подключает `NotifyConfig.ready()`).
"""
import logging

from django.db import models, transaction

from ..models import BindCode, Delivery, Digest, Notification, PushSubscription, UserNotifySettings

log = logging.getLogger(__name__)

_OPEN_STATES = ("waiting", "held", "sending")
_MESSENGERS = ("telegram", "max")


def on_dismissed(*, user_id: int, actor_id: int | None = None) -> None:
    """Подписчик `core.user_dismissed`: убирает каналы и незавершённые доставки уволенного.

    В одной транзакции: доставки в ожидании, отложенные и отправляемые (по уведомлению и по сводке) — `skipped`
    с причиной `user_dismissed`; подписки Web Push, привязки Telegram и MAX и все коды привязки удаляются; строка
    личных настроек удаляется. `Notification` и `Digest` остаются до срока хранения. Журнал — от системы, без
    идентификаторов чатов (его пишут `push.drop` и `binding.unbind`).
    """
    from . import binding, push

    with transaction.atomic():
        Delivery.objects.filter(
            models.Q(notification__user_id=user_id) | models.Q(digest__user_id=user_id),
            state__in=_OPEN_STATES,
        ).update(state="skipped", reason="user_dismissed", lease_until=None)
        for subscription_id in list(
                PushSubscription.objects.filter(user_id=user_id).order_by("pk").values_list("pk", flat=True)):
            push.drop(subscription_id, reason="dismissed")
        for channel in _MESSENGERS:
            binding.unbind(user_id, channel, reason="dismissed")
        BindCode.objects.filter(user_id=user_id).delete()
        UserNotifySettings.objects.filter(user_id=user_id).delete()


def on_rehired(*, user_id: int, actor_id: int | None = None) -> None:
    """Подписчик `core.user_rehired`: удаляет прежние уведомления и сводки сотрудника (доставки — каскадом)."""
    with transaction.atomic():
        Notification.objects.filter(user_id=user_id).delete()
        Digest.objects.filter(user_id=user_id).delete()
