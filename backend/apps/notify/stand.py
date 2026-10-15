"""Очистка данных среза командой стенда (PLAN-004, «Где живёт код»; CONTRACT-004, 8.3).

`stand_reset` — функция точки `stand_reset`: возвращает данные среза к состоянию сразу после миграций (`0002_initial_data`):
стирает доставки, уведомления, сводки, подписки Web Push, привязки, коды и чаты бота, настройки сотрудников, пересоздаёт
`NotifySettings`, обнуляет курсоры и коды ошибок `BotState` (имя бота остаётся), удаляет присутствие `notify:online:*` в
Valkey, очищает очередь `notify` и сбрасывает учебную службу ботов. Идёт под владельцем схемы (алиас `migrate`).
Общая очистка таблиц ядра с каскадом уже стёрла часть таблиц среза, поэтому функция не рассчитывает на их строки.
Регистрация точки в `extensions.py` — вне этого файла.
"""
import logging
import urllib.request

import django_rq
from django.conf import settings
from django.db import connections, transaction

from apps.core.services import valkey

from .models import (BindCode, BotChat, BotState, ChatBinding, Delivery, Digest, Notification, NotifySettings,
                     PushSubscription, UserNotifySettings)

log = logging.getLogger(__name__)

REAL_TELEGRAM = "https://api.telegram.org"
FAKEBOTS_TIMEOUT = 5   # секунд на сброс учебной службы


def _erase(db: str) -> None:
    """Стирает данные среза: доставки — раньше уведомлений и сводок."""
    for model in (Delivery, Notification, Digest, PushSubscription, ChatBinding, BindCode, BotChat,
                  UserNotifySettings, NotifySettings):
        model.objects.using(db).all().delete()


def _seed(db: str) -> None:
    """Строка настроек со значениями миграции данных."""
    NotifySettings.objects.using(db).create(
        pk=1, webpush_enabled=False, telegram_enabled=False, max_enabled=False, email_delay_minutes=15,
        retention_days=90, defaults={}, channel_status={})


def _reset_fakebots() -> None:
    """`POST <TELEGRAM_API_BASE>/_test/reset`; на адресе настоящего Telegram не вызывается (решение C11).
    Сбой — предупреждение без адреса и токена."""
    base = settings.TELEGRAM_API_BASE.rstrip("/")
    if base == REAL_TELEGRAM:
        return
    try:
        request = urllib.request.Request(f"{base}/_test/reset", data=b"", method="POST")
        with urllib.request.urlopen(request, timeout=FAKEBOTS_TIMEOUT) as response:
            if response.status != 200:
                log.warning("Сброс учебной службы ботов не удался: ответ %s", response.status)
    except Exception as error:  # сеть, разбор адреса, не 200 (HTTPError): стенд не отказывает
        log.warning("Сброс учебной службы ботов не удался: %s", type(error).__name__)


def stand_reset() -> None:
    """Приводит данные среза к состоянию после миграций; идёт под владельцем схемы (алиас `migrate`), если он настроен."""
    db = "migrate" if "migrate" in connections.databases else "default"
    with transaction.atomic(using=db):
        _erase(db)
        _seed(db)
        BotState.objects.using(db).update(cursor="", last_error="")
    conn = valkey.conn()
    for key in conn.scan_iter(match="notify:online:*", count=500):
        conn.delete(key)
    django_rq.get_queue("notify").empty()
    _reset_fakebots()
