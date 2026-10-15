"""Публичный интерфейс уведомлений: отправка и повторы (PLAN-004, «Отправка, повторы, идемпотентность», «Web Push» →
«Отправка»; CONTRACT-004, 6.9).

`send_delivery` берёт доставку под замком короткой транзакцией, проверяет без сети, отправляет вне транзакции и вторым
коротким шагом записывает итог. `tick` — обход раз в 30 секунд: письма по сроку, повторная постановка, возврат
зависших, сводки, просроченные коды. Токены, адреса и ключи в `log` не пишутся.
"""
import datetime
import html
import json
import logging

import django_rq
from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.integrations import channel as channel_errors
from apps.integrations.max import client as max_client
from apps.integrations.telegram import client as telegram_client
from apps.integrations.webpush import client as webpush_client
from apps.integrations.webpush import crypto as webpush_crypto

from ..models import Delivery, PushSubscription, UserNotifySettings
from . import binding, kinds, live, push
from . import settings as notify_settings
from .errors import NotifyError

log = logging.getLogger(__name__)

LEASE_SECONDS = 240
REQUEUE_AFTER_SECONDS = 120
WEBPUSH_BUDGET_SECONDS = 90
BATCH = 200
MAX_AGE = datetime.timedelta(hours=24)
RETRY_DELAYS = (60, 300, 900, 3600)   # секунды после 1, 2, 3, 4 попытки
RETRY_LATER = 10800                   # после пятой и далее
BUTTON_LABEL = "Открыть уведомления"  # текст контракта (решение E14)
SEND_TIMEOUT = 180                    # `job_timeout` задания отправки
DIGEST_TIMEOUT = 120                  # `job_timeout` задания сборки сводки
NOTIFICATIONS_PATH = "/notifications/"
FALLBACK_TEXT = "У вас новое уведомление"   # у вида без внешнего текста (в раздел 15 не входит)

_IMMEDIATE = ("webpush", "telegram", "max")
_CLIENTS = {"telegram": telegram_client, "max": max_client}


def next_due(created_at, attempts: int, now, *, retry_after: int | None = None):
    """Срок следующей попытки или `None`, если он позже `created_at + 24 часа` (доставка `failed`, `expired`).

    `attempts` — число уже сделанных попыток, включая только что не удавшуюся."""
    attempts = max(int(attempts), 1)
    seconds = RETRY_DELAYS[attempts - 1] if attempts <= len(RETRY_DELAYS) else RETRY_LATER
    due = now + datetime.timedelta(seconds=seconds)
    if retry_after is not None:
        due = max(due, now + datetime.timedelta(seconds=retry_after))
    if due > created_at + MAX_AGE:
        return None
    return due


def enqueue(delivery_ids) -> None:
    """Ставит `tasks.send_delivery(id)` по одному заданию на номер; `enqueued_at` — сейчас; после фиксации."""
    from apps.notify import tasks

    ids = list(dict.fromkeys(delivery_ids))
    if not ids:
        return
    queue = django_rq.get_queue("notify", commit_mode="on_db_commit")
    Delivery.objects.filter(pk__in=ids).update(enqueued_at=timezone.now())
    for delivery_id in ids:
        queue.enqueue(tasks.send_delivery, delivery_id, job_timeout=SEND_TIMEOUT)


def _declension(count: int) -> str:
    """«У вас N новых уведомлений» с согласованием по правилу раздела 15.6."""
    if 11 <= count % 100 <= 14:
        words = "новых уведомлений"
    elif count % 10 == 1:
        words = "новое уведомление"
    elif 2 <= count % 10 <= 4:
        words = "новых уведомления"
    else:
        words = "новых уведомлений"
    return f"У вас {count} {words}"


def external_text(delivery) -> str:
    """Внешний текст для Telegram, MAX и Web Push: у уведомления — текст вида, у сводки — «У вас N новых …»."""
    if delivery.digest_id is not None:
        return _declension(delivery.digest.count_message)
    try:
        text = kinds.get(delivery.notification.kind).external_text
    except NotifyError:
        text = ""
    return text or FALLBACK_TEXT


def _user_id(delivery) -> int:
    return delivery.notification.user_id if delivery.notification_id is not None else delivery.digest.user_id


def _created_at(delivery):
    return delivery.notification.created_at if delivery.notification_id is not None else delivery.digest.created_at


def _entry(outcome: str, code=None, reason: str = "", sub=None) -> dict:
    """Запись `log`: время, исход, код ответа, причина; у Web Push — номер подписки (без адреса и ключей)."""
    entry = {"at": timezone.now().isoformat(), "outcome": outcome, "code": code, "reason": reason}
    if sub is not None:
        entry["sub"] = sub
    return entry


def _take(delivery_id):
    """Короткая транзакция: берёт доставку `waiting` со сроком под замком, `sending` и аренда; иначе `None`."""
    now = timezone.now()
    with transaction.atomic():
        row = (Delivery.objects.select_for_update(skip_locked=True)
               .filter(pk=delivery_id, state=Delivery.State.WAITING, due_at__lte=now).first())
        if row is None:
            return None
        row.state = Delivery.State.SENDING
        row.lease_until = now + datetime.timedelta(seconds=LEASE_SECONDS)
        row.save(update_fields=["state", "lease_until"])
        return row


def _skip(row, reason: str) -> str:
    """Проверка не прошла: `skipped` с причиной, аренда снята, сеть не тронута."""
    with transaction.atomic():
        Delivery.objects.filter(pk=row.pk).update(state=Delivery.State.SKIPPED, reason=reason, lease_until=None)
    return Delivery.State.SKIPPED


def _check(row, user):
    """Проверки без сети (порядок 6.9); возвращает причину отказа или `None`, а также привязку для Telegram и MAX."""
    if user.state == "blocked":
        return "user_blocked", None
    if user.state == "dismissed":
        return "user_dismissed", None
    if not notify_settings.channel_on(row.channel):
        return "channel_disabled", None
    if row.channel in _CLIENTS:
        bound = binding.get(user.pk, row.channel)
        return (None, bound) if bound is not None else ("not_bound", None)
    if not PushSubscription.objects.filter(user_id=user.pk).exists():
        return "no_subscriptions", None
    if live.is_online(user.pk):
        return "tab_open", None
    return None, None


def _finish(row_id, entry, *, state: str, reason: str = "", due_at=None, keep_due: bool = False,
            expire: bool = False, from_index: int | None = None) -> str:
    """Вторая короткая транзакция: запись попытки (если есть), `attempts + 1`, аренда снята, итог.

    `expire` — попытка последняя: записи повтора этого вызова (с `from_index`) становятся `failed` (доп. 15 (в))."""
    with transaction.atomic():
        row = Delivery.objects.select_for_update().get(pk=row_id)
        entries = list(row.log or [])
        if entry is not None:
            entries.append(entry)
        if expire:
            for index in range(from_index if from_index is not None else len(entries) - 1, len(entries)):
                if entries[index].get("outcome") == "retry":
                    entries[index] = {**entries[index], "outcome": "failed"}
        row.log = entries
        row.attempts += 1
        row.lease_until = None
        row.state = state
        row.reason = reason
        if state == Delivery.State.WAITING:
            row.enqueued_at = None
            if not keep_due:
                row.due_at = due_at
        row.save(update_fields=["log", "attempts", "lease_until", "state", "reason", "due_at", "enqueued_at"])
        return state


def _retry_or_fail(row, entry, now, retry_after=None, *, from_index: int | None = None) -> str:
    """Повтор по расписанию; срок позже 24 часов — `failed`, `expired`."""
    due = next_due(_created_at(row), row.attempts + 1, now, retry_after=retry_after)
    if due is None:
        return _finish(row.pk, entry, state=Delivery.State.FAILED, reason="expired", expire=True,
                       from_index=from_index)
    return _finish(row.pk, entry, state=Delivery.State.WAITING, due_at=due)


def _retry_reason(error) -> str:
    """Причина попытки в `log` для повторяемой ошибки бота."""
    if error.reason:
        return error.reason
    if error.code == 429:
        return "rate_limited"
    if error.code is not None and error.code >= 500:
        return "server_error"
    return "unavailable"


def _send_messenger(row, user_id: int, chat_id: str) -> str:
    """Telegram и MAX: один запрос; итог — вторая транзакция."""
    channel = row.channel
    text = html.escape(external_text(row))
    url = dj_settings.PORTAL_URL.rstrip("/") + NOTIFICATIONS_PATH
    try:
        _CLIENTS[channel].send_message(chat_id, text, button=(BUTTON_LABEL, url))
    except channel_errors.ChannelGone as error:
        with transaction.atomic():
            binding.unbind(user_id, channel, reason="bot_unavailable")
            return _finish(row.pk, _entry("failed", error.code, "channel_unbound"), state=Delivery.State.FAILED,
                           reason="channel_unbound")
    except channel_errors.BadRequest as error:
        return _finish(row.pk, _entry("failed", error.code, "bad_request"), state=Delivery.State.FAILED,
                       reason="bad_request")
    except channel_errors.BadToken as error:
        notify_settings.note_channel_error(channel, "bad_token")
        return _retry_or_fail(row, _entry("retry", error.code, "bad_token"), timezone.now())
    except channel_errors.RetryLater as error:
        reason = _retry_reason(error)
        notify_settings.note_channel_error(channel, "rate_limited" if error.code == 429 else "unavailable")
        return _retry_or_fail(row, _entry("retry", error.code, reason), timezone.now(), retry_after=error.after)
    except channel_errors.ChannelError as error:
        return _finish(row.pk, _entry("failed", error.code, "bad_request"), state=Delivery.State.FAILED,
                       reason="bad_request")
    notify_settings.clear_channel_error(channel)
    return _finish(row.pk, _entry("ok"), state=Delivery.State.SENT)


def _append_log(delivery_id, entry) -> None:
    """Итог одной подписки сразу дописывается в `log` короткой транзакцией."""
    with transaction.atomic():
        row = Delivery.objects.select_for_update().get(pk=delivery_id)
        row.log = [*(row.log or []), entry]
        row.save(update_fields=["log"])


def _one_subscription(row, subscription, body: bytes) -> dict:
    """Запрос на одну подписку; возвращает запись `log` и, для повторов, `after` (секунды `Retry-After`)."""
    try:
        sent = webpush_client.send(subscription, body)
    except webpush_client.SendError as error:
        return {"entry": _entry("retry", None, error.reason, sub=subscription.pk), "kind": "retry",
                "channel": "unavailable"}
    except webpush_crypto.CryptoError:
        return {"entry": _entry("failed", None, "bad_request", sub=subscription.pk), "kind": "bad"}
    status = sent.status
    if 200 <= status < 300:
        return {"entry": _entry("ok", status, "", sub=subscription.pk), "kind": "ok"}
    if status in (404, 410):
        return {"entry": _entry("gone", status, "", sub=subscription.pk), "kind": "gone"}
    if status == 429:
        return {"entry": _entry("retry", status, "rate_limited", sub=subscription.pk), "kind": "retry",
                "channel": "rate_limited", "after": sent.retry_after}
    if status >= 500:
        return {"entry": _entry("retry", status, "server_error", sub=subscription.pk), "kind": "retry",
                "channel": "unavailable"}
    if 300 <= status < 400:
        return {"entry": _entry("failed", status, "redirect", sub=subscription.pk), "kind": "redirect"}
    if status in (401, 403):
        return {"entry": _entry("retry", status, "bad_token", sub=subscription.pk), "kind": "retry",
                "channel": "bad_token"}
    return {"entry": _entry("failed", status, "bad_request", sub=subscription.pk), "kind": "bad"}


def send_webpush(row) -> str:
    """Web Push по подпискам сотрудника без удачной отметки в `log`; итог доставки — по правилам 6.9."""
    user_id = _user_id(row)
    fresh = Delivery.objects.get(pk=row.pk)
    prior = list(fresh.log or [])
    done = {entry["sub"] for entry in prior if entry.get("outcome") == "ok" and "sub" in entry}
    tag = "digest" if row.digest_id is not None else f"n-{row.notification_id}"
    body = json.dumps({"title": external_text(row), "url": NOTIFICATIONS_PATH, "tag": tag},
                      ensure_ascii=False).encode("utf-8")
    started = timezone.now()
    budget = datetime.timedelta(seconds=WEBPUSH_BUDGET_SECONDS)
    ok_now = False
    cut = False
    kinds_seen: list[str] = []
    channel_codes: list[str] = []
    after: list[int] = []
    for subscription in PushSubscription.objects.filter(user_id=user_id).order_by("pk"):
        if subscription.pk in done:
            continue
        if timezone.now() - started >= budget:
            cut = True
            break
        result = _one_subscription(row, subscription, body)
        _append_log(row.pk, result["entry"])
        kind = result["kind"]
        kinds_seen.append(kind)
        if kind == "ok":
            ok_now = True
            PushSubscription.objects.filter(pk=subscription.pk).update(last_ok_at=timezone.now())
        elif kind == "gone":
            push.drop(subscription.pk, reason="gone")
        elif kind == "retry":
            channel_codes.append(result["channel"])
            if result.get("after") is not None:
                after.append(result["after"])
    if ok_now:
        notify_settings.clear_channel_error("webpush")
    elif channel_codes:
        for code in ("rate_limited", "bad_token", "unavailable"):
            if code in channel_codes:
                notify_settings.note_channel_error("webpush", code)
                break
    now = timezone.now()
    start_index = len(prior)
    if cut:
        return _finish(row.pk, None, state=Delivery.State.WAITING, keep_due=True)
    if ok_now or done:
        return _finish(row.pk, None, state=Delivery.State.SENT)
    if "retry" in kinds_seen:
        return _retry_or_fail(row, None, now, retry_after=max(after) if after else None, from_index=start_index)
    if not PushSubscription.objects.filter(user_id=user_id).exists():
        return _finish(row.pk, None, state=Delivery.State.FAILED, reason="no_subscriptions")
    if "redirect" in kinds_seen:
        return _finish(row.pk, None, state=Delivery.State.FAILED, reason="redirect")
    return _finish(row.pk, None, state=Delivery.State.FAILED, reason="bad_request")


def send_delivery(delivery_id) -> str:
    """Отправка одной доставки; итог: `noop` или состояние строки после вызова (6.9)."""
    row = _take(delivery_id)
    if row is None:
        return "noop"
    row = Delivery.objects.select_related("notification", "digest").get(pk=row.pk)
    user_id = _user_id(row)
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(pk=user_id)
    reason, bound = _check(row, user)
    if reason is not None:
        return _skip(row, reason)
    if row.channel == "webpush":
        return send_webpush(row)
    return _send_messenger(row, user_id, bound.chat_id)


def tick() -> dict:
    """Обход: письма по сроку, повторная постановка, возврат зависших, сводки, просроченные коды (6.9)."""
    from apps.notify import tasks

    from . import mail

    emails = mail.send_due()
    now = timezone.now()
    requeued = 0
    stale = now - datetime.timedelta(seconds=REQUEUE_AFTER_SECONDS)
    while True:
        ids = list(Delivery.objects.filter(state=Delivery.State.WAITING, channel__in=_IMMEDIATE, due_at__lte=now)
                   .filter(Q(enqueued_at__isnull=True) | Q(enqueued_at__lt=stale))
                   .order_by("pk").values_list("pk", flat=True)[:BATCH])
        if not ids:
            break
        enqueue(ids)
        requeued += len(ids)
        if len(ids) < BATCH:
            break
    released = 0
    while True:
        ids = list(Delivery.objects.filter(state=Delivery.State.SENDING, channel__in=_IMMEDIATE, lease_until__lt=now)
                   .order_by("pk").values_list("pk", flat=True)[:BATCH])
        if not ids:
            break
        released += Delivery.objects.filter(pk__in=ids, state=Delivery.State.SENDING).update(
            state=Delivery.State.WAITING, lease_until=None, enqueued_at=None)
        if len(ids) < BATCH:
            break
    users = list(UserNotifySettings.objects.filter(digest_due_at__isnull=False, digest_due_at__lte=now)
                 .order_by("digest_due_at").values_list("user_id", flat=True)[:BATCH])
    if users:
        queue = django_rq.get_queue("notify", commit_mode="on_db_commit")
        for user_id in users:
            queue.enqueue(tasks.build_digest, user_id, job_timeout=DIGEST_TIMEOUT)
    codes = binding.purge_expired_codes()
    return {"emails": emails, "released": released, "requeued": requeued, "digests": len(users), "codes": codes}
