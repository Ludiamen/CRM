"""Публичный интерфейс уведомлений: живая рассылка в группы сотрудников и присутствие (PLAN-004, «Колокольчик…» →
«Отправка в группы», «Присутствие для FR-331»; CONTRACT-004, 6.8, 7.4).

Рассылка не должна ронять действие, из которого она вызвана: ошибки слоя каналов пишутся в лог предупреждением.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Count
from django.utils import timezone

from apps.core.services import valkey

from ..models import Notification

log = logging.getLogger(__name__)

ONLINE_WINDOW = 60      # секунд: элемент присутствия моложе — вкладка открыта
ONLINE_KEEP = 120       # секунд: страховочный срок ключа и предел хранения элементов


def group(user_id: int) -> str:
    """Имя группы слоя каналов сотрудника."""
    return f"notify.u.{user_id}"


def _counts(user_ids) -> dict[int, int]:
    """Непрочитанные сотрудников одним запросом по частичному индексу."""
    rows = (Notification.objects.filter(user_id__in=list(user_ids), read_at__isnull=True)
            .values("user_id").annotate(total=Count("pk")))
    counts = {user_id: 0 for user_id in user_ids}
    counts.update({row["user_id"]: row["total"] for row in rows})
    return counts


def push(user_ids, *, toasts=None, binding=None) -> None:
    """Кадр «число, системное уведомление, блок привязки» в группы сотрудников одним обращением к слою каналов."""
    user_ids = list(dict.fromkeys(user_ids))
    if not user_ids:
        return
    toasts = toasts or {}
    try:
        counts = _counts(user_ids)
        layer = get_channel_layer()
        if layer is None:
            raise RuntimeError("слой каналов не настроен")

        async def send():
            for user_id in user_ids:
                await layer.group_send(group(user_id), {"type": "notify.update", "count": counts[user_id],
                                                        "toast": toasts.get(user_id), "binding": binding})

        async_to_sync(send)()
    except Exception as error:
        log.warning("Рассылка в группы уведомлений не удалась: %s", type(error).__name__)


def _key(user_id: int) -> str:
    return f"notify:online:{user_id}"


def is_online(user_id: int) -> bool:
    """Есть ли у сотрудника элемент присутствия моложе `ONLINE_WINDOW` секунд."""
    edge = timezone.now().timestamp() - ONLINE_WINDOW
    return bool(valkey.conn().zcount(_key(user_id), edge, "+inf"))


def mark_online(user_id: int, connection_id: str) -> None:
    """Отметка соединения: оценка — сейчас; элементы старше `ONLINE_KEEP` убираются, ключу — срок жизни."""
    now = timezone.now().timestamp()
    pipe = valkey.conn().pipeline()
    pipe.zadd(_key(user_id), {connection_id: now})
    pipe.zremrangebyscore(_key(user_id), "-inf", now - ONLINE_KEEP)
    pipe.expire(_key(user_id), ONLINE_KEEP)
    pipe.execute()


def mark_offline(user_id: int, connection_id: str) -> None:
    """Убирает элемент этого соединения; остальные вкладки остаются."""
    valkey.conn().zrem(_key(user_id), connection_id)
