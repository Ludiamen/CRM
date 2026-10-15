"""T-4113: отправка доставок, повторы, аренда, обход и идемпотентность (FR-333, NFR-302, NFR-304, NFR-306).

Сценарии 11 и 1 спеки среза 004; механизм — план «Отправка, повторы, идемпотентность», контракт 6.9 и 7.1-7.3.
Доставки создаются прямой записью (уведомление + `Delivery`), задания выполняют помощники § 7.3. Telegram и MAX —
`fake_bot_send` (решения 4, E16), Web Push — `webpush_capture` (§ 5.3). Часы — фикстура `clock`: Valkey и RQ живут по
настоящему времени, поэтому сроки очереди (`enqueued_at`, `lease_until`) сдвигаются прямой записью. Код среза 004
на уровне модуля не импортируется (CONTRACT-004, шапка).
"""
import datetime
import email.utils
import json
import secrets
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.utils import timezone

from tests import support, support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
MOMENT = datetime.datetime(2026, 10, 13, 11, 0, 0, tzinfo=MSK)  # вторник, микросекунд нет
KIND = "servicedesk.assigned"


# --- помощники только этого файла -------------------------------------------------------------------

def _sec(value: int) -> datetime.timedelta:
    return datetime.timedelta(seconds=value)


def _bind(user, channel: str):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id="chat-" + secrets.token_hex(6))


def _note(user, *, created_at=None, kind: str = KIND):
    return model("notify.Notification").objects.create(
        user=user, kind=kind, text="Тест " + secrets.token_hex(5), url="/tickets/1/", object_ref="servicedesk.ticket:1",
        created_at=created_at or timezone.now())


def _make(channel: str, *, user=None, state: str = "waiting", due_in: int | None = -5, enqueued_ago: int | None = None,
          lease_in: int | None = None, created_at=None, bind: bool = True, notification=None, **over):
    """Доставка канала `channel` (`telegram`, `max`, `webpush`); срок — `due_in` секунд от «сейчас» (None — нет срока)."""
    user = user or support.make_employee()
    now = timezone.now()
    if bind and channel in ("telegram", "max") and not model("notify.ChatBinding").objects.filter(
            user=user, channel=channel).exists():
        _bind(user, channel)
    note = notification or _note(user, created_at=created_at)
    fields = {"notification": note, "channel": channel, "state": state,
              "due_at": None if due_in is None else now + _sec(due_in),
              "enqueued_at": None if enqueued_ago is None else now - _sec(enqueued_ago),
              "lease_until": None if lease_in is None else now + _sec(lease_in)}
    fields.update(over)
    return model("notify.Delivery").objects.create(**fields)


def _send(delivery_obj) -> str:
    from apps.notify.services import delivery
    return delivery.send_delivery(delivery_obj.pk)


def _fresh(delivery_obj):
    delivery_obj.refresh_from_db()
    return delivery_obj


def _retry(code, *, reason: str = "", after=None):
    from apps.integrations import channel
    return channel.RetryLater("sendMessage", code, reason=reason, after=after)


def _enqueue(capture, ids) -> None:
    """`delivery.enqueue` внутри транзакции: задание уходит после фиксации (§ 7.3)."""
    from apps.notify.services import delivery
    with capture(execute=True):
        with transaction.atomic():
            delivery.enqueue(list(ids))


def _tick(capture) -> dict:
    """Обход без выполнения заданий: тест смотрит очередь сам."""
    from apps.notify.services import delivery
    with capture(execute=True):
        return delivery.tick()


def _snapshot(delivery_obj) -> tuple:
    row = _fresh(delivery_obj)
    return (row.state, row.reason, row.attempts, row.due_at, row.enqueued_at, row.lease_until, list(row.log))


def _channel_code(channel: str):
    from apps.notify.services import settings as notify_settings
    status = notify_settings.channel_error(channel)
    return None if status is None else status["code"]


# --- 1-3. взятие доставки, аренда, холостой выход ---------------------------------------------------

def test_two_jobs_for_one_delivery_send_one_message(bots_on, clock, django_capture_on_commit_callbacks):
    """NFR-306, FR-333: два задания на одну доставку — одно сообщение; повтор выходит с «noop» (план, п. 1)."""
    clock.set(MOMENT)
    row = _make("telegram")
    _enqueue(django_capture_on_commit_callbacks, [row.pk])
    _enqueue(django_capture_on_commit_callbacks, [row.pk])
    jobs = notify.queued()
    assert len(jobs) == 2 and all(job.args == (row.pk,) and job.timeout == 180 for job in jobs)
    with notify.fake_bot_send("telegram") as bot:
        assert notify.run_jobs() == 2
        assert len(bot.calls) == 1
    row = _fresh(row)
    assert (row.state, row.attempts, len(row.log)) == ("sent", 1, 1)
    with notify.fake_bot_send("telegram") as bot:
        assert _send(row) == "noop"
        assert bot.calls == []


def test_job_takes_delivery_sets_sending_and_lease_until_plus_240_seconds(webpush_on, clock):
    """FR-333: при взятии доставка `sending`, `lease_until = сейчас + 240 с`; после итога аренда снята (6.9, п. 1)."""
    clock.set(MOMENT)
    user = support.make_employee()
    notify.subscribe(user)
    row = _make("webpush", user=user)
    seen = []

    def watch(_request):
        current = model("notify.Delivery").objects.get(pk=row.pk)
        seen.append((current.state, current.lease_until))

    with notify.webpush_capture(on_request=watch) as push:
        assert _send(row) == "sent"
    assert len(push.requests) == 1
    assert seen == [("sending", MOMENT + _sec(240))]
    row = _fresh(row)
    assert (row.state, row.lease_until, row.attempts) == ("sent", None, 1)


def test_job_exits_without_sending_when_delivery_not_waiting_or_not_due(bots_on, clock):
    """NFR-306: нет строки, не `waiting` или срок не наступил — итог «noop», сообщения нет, строка не меняется."""
    clock.set(MOMENT)
    rows = [_make("telegram", state=name, due_in=None if name == "held" else -5,
                  lease_in=100 if name == "sending" else None)
            for name in ("sent", "failed", "skipped", "held", "digested", "sending")]
    rows.append(_make("telegram", state="waiting", due_in=3600))
    before = [_snapshot(row) for row in rows]
    with notify.fake_bot_send("telegram") as bot:
        assert [_send(row) for row in rows] == ["noop"] * len(rows)
        from apps.notify.services import delivery
        assert delivery.send_delivery(max(row.pk for row in rows) + 1000) == "noop"
        assert bot.calls == []
    assert [_snapshot(row) for row in rows] == before


# --- 4-8. проверки без сети --------------------------------------------------------------------------

def test_failed_check_marks_skipped_without_network_and_releases_lease(bots_on):
    """FR-333: не прошла проверка — `skipped` с причиной, `lease_until` снят, запросов в сеть нет (план, п. 2)."""
    from apps.integrations.max import client as max_client
    user = support.make_employee(state="dismissed")
    row = _make("max", user=user)
    with notify.bots_capture(max_client, passthrough=False, responses=[]) as net:
        assert _send(row) == "skipped"
    assert net.requests == []
    row = _fresh(row)
    assert (row.state, row.reason, row.lease_until) == ("skipped", "user_dismissed", None)


def test_disabled_channel_marks_delivery_skipped_with_reason(bots_on, webpush_on, settings):
    """FR-333: канал выключен администратором или токен не задан — `skipped`, причина `channel_disabled`."""
    cfg = model("notify.NotifySettings").objects
    cfg.filter(pk=1).update(telegram_enabled=False, webpush_enabled=False)
    settings.MAX_BOT_TOKEN = ""
    user = support.make_employee()
    notify.subscribe(user)
    rows = [_make("telegram", user=user), _make("max", user=user), _make("webpush", user=user)]
    with notify.fake_bot_send("telegram") as tg, notify.fake_bot_send("max") as mx, notify.webpush_capture() as push:
        assert [_send(row) for row in rows] == ["skipped"] * 3
    assert tg.calls == [] and mx.calls == [] and push.requests == []
    for row in rows:
        row = _fresh(row)
        assert (row.state, row.reason, row.lease_until) == ("skipped", "channel_disabled", None)


def test_blocked_account_marks_delivery_skipped_with_reason(bots_on, webpush_on):
    """FR-333: заблокированная учётная запись — `skipped`, `user_blocked`; запись на портале остаётся."""
    user = support.make_employee(state="blocked")
    notify.subscribe(user)
    note = _note(user)
    rows = [_make("telegram", user=user, notification=note), _make("webpush", user=user, notification=note)]
    with notify.fake_bot_send("telegram") as bot, notify.webpush_capture() as push:
        assert [_send(row) for row in rows] == ["skipped", "skipped"]
    assert bot.calls == [] and push.requests == []
    for row in rows:
        row = _fresh(row)
        assert (row.state, row.reason, row.lease_until) == ("skipped", "user_blocked", None)
        assert row.notification_id is not None
    assert model("notify.Notification").objects.filter(user=user).count() == 1


def test_open_tab_marks_webpush_delivery_skipped(webpush_on, clock):
    """FR-333: Web Push при открытой вкладке (`live.is_online`) — `skipped`, `tab_open`; подписка цела."""
    from apps.core.services.valkey import conn
    from apps.notify.services import live
    clock.set(MOMENT)
    user = support.make_employee()
    sub = notify.subscribe(user)
    conn().zadd(f"notify:online:{user.pk}", {"c1": timezone.now().timestamp()})
    assert live.is_online(user.pk)
    row = _make("webpush", user=user)
    with notify.webpush_capture() as push:
        assert _send(row) == "skipped"
    assert push.requests == []
    row = _fresh(row)
    assert (row.state, row.reason, row.lease_until) == ("skipped", "tab_open", None)
    assert model("notify.PushSubscription").objects.filter(pk=sub.pk).exists()


def test_missing_binding_or_token_marks_delivery_skipped(bots_on, webpush_on, settings):
    """FR-333: нет привязки — `not_bound`, нет подписок — `no_subscriptions`, нет токена — `channel_disabled`."""
    user = support.make_employee()
    rows = {"tg": _make("telegram", user=user, bind=False), "mx": _make("max", user=user, bind=False),
            "wp": _make("webpush", user=user)}
    with notify.fake_bot_send("telegram") as tg, notify.fake_bot_send("max") as mx, notify.webpush_capture() as push:
        assert [_send(row) for row in rows.values()] == ["skipped"] * 3
    assert tg.calls == [] and mx.calls == [] and push.requests == []
    reasons = {name: _fresh(row).reason for name, row in rows.items()}
    assert reasons == {"tg": "not_bound", "mx": "not_bound", "wp": "no_subscriptions"}
    settings.TELEGRAM_BOT_TOKEN = ""
    other = support.make_employee()
    row = _make("telegram", user=other, bind=False)
    with notify.fake_bot_send("telegram") as tg:
        assert _send(row) == "skipped"
    assert tg.calls == [] and _fresh(row).reason == "channel_disabled"


# --- 9-14. расписание и повторы ---------------------------------------------------------------------

def test_retry_schedule_is_1_5_15_minutes_1_hour_then_3_hours():
    """FR-333: после 1…4 неудач срок — +1, +5, +15 минут, +1 час; после пятой и далее — +3 часа (решение E17)."""
    from apps.notify.services import delivery
    created = MOMENT
    expected = {1: 60, 2: 300, 3: 900, 4: 3600, 5: 10800, 6: 10800}
    for attempts, seconds in expected.items():
        assert delivery.next_due(created, attempts, MOMENT) == MOMENT + _sec(seconds), attempts


def test_retry_scheduled_after_5xx_keeps_state_waiting_and_attempts_plus_one(bots_on, clock):
    """FR-333: 5xx — доставка `waiting`, `attempts + 1`, новый срок по расписанию, запись `retry` в `log`."""
    clock.set(MOMENT)
    row = _make("telegram", created_at=MOMENT)
    with notify.fake_bot_send("telegram", raises=_retry(502)) as bot:
        assert _send(row) == "waiting"
    assert len(bot.calls) == 1
    row = _fresh(row)
    assert (row.state, row.reason, row.attempts, row.lease_until) == ("waiting", "", 1, None)
    assert row.due_at == MOMENT + _sec(60)
    assert [(entry["outcome"], entry["code"]) for entry in row.log] == [("retry", 502)]
    assert _channel_code("telegram") == "unavailable"
    clock.advance(seconds=61)
    with notify.fake_bot_send("telegram", raises=_retry(502)):
        assert _send(row) == "waiting"
    row = _fresh(row)
    assert row.attempts == 2 and row.due_at == MOMENT + _sec(61 + 300) and len(row.log) == 2


def test_delivery_failed_when_next_retry_would_pass_24_hours_from_creation(bots_on, clock):
    """FR-333: срок следующего повтора позже `created_at + 24 часа` — `failed`, причина `expired`; в запас — `waiting`."""
    from apps.notify.services import delivery
    clock.set(MOMENT)
    late = _make("telegram", created_at=MOMENT - datetime.timedelta(hours=24) + _sec(30))
    early = _make("telegram", created_at=MOMENT - datetime.timedelta(hours=24) + _sec(120))
    with notify.fake_bot_send("telegram", raises=_retry(503, reason="server_error")):
        assert _send(late) == "failed"
        assert _send(early) == "waiting"
    late, early = _fresh(late), _fresh(early)
    assert (late.state, late.reason, late.attempts, late.lease_until) == ("failed", "expired", 1, None)
    assert [(entry["outcome"], entry["reason"]) for entry in late.log] == [("failed", "server_error")]
    assert (early.state, early.reason) == ("waiting", "")
    assert delivery.next_due(MOMENT - datetime.timedelta(hours=24) + _sec(30), 1, MOMENT) is None
    assert delivery.next_due(MOMENT - datetime.timedelta(hours=22), 5, MOMENT) is None


def test_failed_delivery_keeps_portal_notification_and_creates_no_new_one(bots_on, clock):
    """FR-333: «не доставлено» (срок вышел, неповторяемый отказ) — запись на портале цела, новых уведомлений нет."""
    from apps.integrations import channel
    clock.set(MOMENT)
    user = support.make_employee()
    note = _note(user, created_at=MOMENT - datetime.timedelta(hours=25))
    expired = _make("telegram", user=user, notification=note)
    refused = _make("max", user=user, notification=note)
    notes_before = model("notify.Notification").objects.count()
    deliveries_before = model("notify.Delivery").objects.count()
    with notify.fake_bot_send("telegram", raises=_retry(500)), \
            notify.fake_bot_send("max", raises=channel.BadRequest("POST /messages", 400)):
        assert _send(expired) == "failed"
        assert _send(refused) == "failed"
    assert (_fresh(expired).reason, _fresh(refused).reason) == ("expired", "bad_request")
    assert [entry["outcome"] for entry in _fresh(expired).log] == ["failed"]
    assert [entry["outcome"] for entry in _fresh(refused).log] == ["failed"]
    assert model("notify.Notification").objects.count() == notes_before
    assert model("notify.Delivery").objects.count() == deliveries_before
    kept = model("notify.Notification").objects.get(pk=note.pk)
    assert (kept.user_id, kept.read_at, kept.text) == (user.pk, None, note.text)


def test_retry_has_empty_enqueued_at(bots_on, clock):
    """FR-333: повтор — `waiting` с пустым `enqueued_at` (иначе обход подхватит не раньше чем через 2 минуты)."""
    clock.set(MOMENT)
    row = _make("telegram", enqueued_ago=1)
    assert _fresh(row).enqueued_at is not None
    with notify.fake_bot_send("telegram", raises=_retry(None, reason="timeout")):
        assert _send(row) == "waiting"
    row = _fresh(row)
    assert (row.state, row.enqueued_at) == ("waiting", None)


def test_tick_picks_up_retry_with_empty_enqueued_at_on_time(bots_on, clock):
    """FR-333: обход ставит повтор с пустым `enqueued_at` сразу, как наступил срок, и не раньше."""
    clock.set(MOMENT)
    row = _make("telegram", created_at=MOMENT)
    with notify.fake_bot_send("telegram", raises=_retry(500)):
        assert _send(row) == "waiting"
    clock.advance(seconds=30)
    with notify.fake_bot_send("telegram") as early:
        assert notify.run_tick()["requeued"] == 0
    assert early.calls == [] and _fresh(row).state == "waiting"
    clock.advance(seconds=31)
    with notify.fake_bot_send("telegram") as bot:
        assert notify.run_tick()["requeued"] == 1
    assert len(bot.calls) == 1
    row = _fresh(row)
    assert (row.state, row.attempts, len(row.log)) == ("sent", 2, 2)


def test_rate_limit_429_moves_due_not_earlier_than_retry_after_seconds(bots_on, clock):
    """FR-333: 429 бота с `after` (целые секунды) — срок не раньше `now + after`; канал `rate_limited`."""
    from apps.notify.services import delivery
    clock.set(MOMENT)
    row = _make("telegram", created_at=MOMENT)
    with notify.fake_bot_send("telegram", raises=_retry(429, after=600)):
        assert _send(row) == "waiting"
    row = _fresh(row)
    assert row.state == "waiting" and row.attempts == 1
    assert row.due_at >= MOMENT + _sec(600) and row.due_at >= MOMENT + _sec(60)
    assert _channel_code("telegram") == "rate_limited"
    assert delivery.next_due(MOMENT, 1, MOMENT, retry_after=600) >= MOMENT + _sec(600)


def test_rate_limit_429_moves_due_not_earlier_than_retry_after_http_date(webpush_on, clock):
    """FR-333: 429 push-сервиса с `Retry-After` датой HTTP — `Sent.retry_after` в секундах, срок не раньше даты."""
    from apps.integrations.webpush import client
    clock.set(MOMENT)
    stamp = email.utils.format_datetime((MOMENT + _sec(900)).astimezone(datetime.timezone.utc), usegmt=True)
    user = support.make_employee()
    sub = notify.subscribe(user)
    row = _make("webpush", user=user, created_at=MOMENT)
    with notify.webpush_capture(status=429, headers={"Retry-After": stamp}) as push:
        assert client.send(sub, b'{"title": "x"}').retry_after == 900
        assert _send(row) == "waiting"
    assert len(push.requests) == 2
    row = _fresh(row)
    assert row.attempts == 1 and row.due_at >= MOMENT + _sec(900)
    assert _channel_code("webpush") == "rate_limited"


# --- 17-21. обход: аренда, повторная постановка -----------------------------------------------------

def test_tick_returns_stuck_sending_to_waiting_after_lease_expired(bots_on):
    """FR-333, NFR-306: `sending` с истёкшей арендой — в `waiting`, срок и `enqueued_at` очищены; живая аренда цела."""
    stuck = _make("telegram", state="sending", lease_in=-10, enqueued_ago=300)
    alive = _make("telegram", state="sending", lease_in=100, enqueued_ago=300)
    with notify.fake_bot_send("telegram") as bot:
        tick = notify.run_tick()
    assert tick["released"] == 1 and tick["requeued"] == 0
    assert bot.calls == []
    stuck, alive = _fresh(stuck), _fresh(alive)
    assert (stuck.state, stuck.lease_until, stuck.enqueued_at) == ("waiting", None, None)
    assert alive.state == "sending" and alive.lease_until is not None


def test_tick_requeues_waiting_delivery_enqueued_more_than_2_minutes_ago(bots_on, django_capture_on_commit_callbacks):
    """FR-333: `waiting` со сроком в прошлом, поставленная больше 2 минут назад, — повторная постановка."""
    row = _make("telegram", enqueued_ago=180)
    old = row.enqueued_at
    assert _tick(django_capture_on_commit_callbacks)["requeued"] == 1
    jobs = notify.queued()
    assert [job.args for job in jobs] == [(row.pk,)]
    assert _fresh(row).enqueued_at > old
    with notify.fake_bot_send("telegram") as bot:
        notify.run_jobs()
    assert len(bot.calls) == 1 and _fresh(row).state == "sent"


def test_tick_requeues_waiting_delivery_never_enqueued(bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-333: `waiting` с пустым `enqueued_at` в каналах `webpush`, `telegram`, `max` обход ставит в очередь."""
    user = support.make_employee()
    notify.subscribe(user)
    rows = [_make(channel, user=user, enqueued_ago=None) for channel in ("webpush", "telegram", "max")]
    assert all(row.enqueued_at is None for row in rows)
    assert _tick(django_capture_on_commit_callbacks)["requeued"] == 3
    assert sorted(job.args[0] for job in notify.queued()) == sorted(row.pk for row in rows)
    assert all(_fresh(row).enqueued_at is not None for row in rows)


def test_tick_skips_waiting_delivery_enqueued_less_than_2_minutes_ago(bots_on, django_capture_on_commit_callbacks):
    """NFR-306: доставка, поставленная меньше 2 минут назад, повторно не ставится (старше 2 минут — ставится)."""
    fresh = _make("telegram", enqueued_ago=100)
    stale = _make("telegram", enqueued_ago=150)
    before = _snapshot(fresh)
    assert _tick(django_capture_on_commit_callbacks)["requeued"] == 1
    assert [job.args for job in notify.queued()] == [(stale.pk,)]
    assert _snapshot(fresh) == before


def test_repeated_enqueue_of_same_delivery_is_harmless(bots_on, django_capture_on_commit_callbacks):
    """NFR-306: повторная постановка той же доставки — лишние задания выходят с «noop», сообщение одно."""
    row = _make("telegram")
    for _ in range(3):
        _enqueue(django_capture_on_commit_callbacks, [row.pk])
    assert len(notify.queued()) == 3
    with notify.fake_bot_send("telegram") as bot:
        assert notify.run_jobs() == 3
    assert len(bot.calls) == 1
    row = _fresh(row)
    assert (row.state, row.attempts, len(row.log)) == ("sent", 1, 1)


def test_second_job_after_sent_creates_no_second_message_or_notification(bots_on, django_capture_on_commit_callbacks):
    """NFR-306: задание после успешной отправки не даёт второго сообщения и второй записи уведомления."""
    row = _make("telegram")
    notes, deliveries = model("notify.Notification").objects.count(), model("notify.Delivery").objects.count()
    with notify.fake_bot_send("telegram") as bot:
        assert _send(row) == "sent"
        _enqueue(django_capture_on_commit_callbacks, [row.pk])
        assert notify.run_jobs() == 1
        assert _send(row) == "noop"
    assert len(bot.calls) == 1
    row = _fresh(row)
    assert (row.state, row.attempts, len(row.log)) == ("sent", 1, 1)
    assert model("notify.Notification").objects.count() == notes
    assert model("notify.Delivery").objects.count() == deliveries


# --- 23. журнал попыток -----------------------------------------------------------------------------

def test_each_attempt_written_to_log_with_time_and_outcome_without_addresses_and_tokens(bots_on, webpush_on, clock,
                                                                                         settings):
    """FR-333: каждая попытка — запись `log` со временем и исходом; адресов, токенов, ключей и текстов в ней нет."""
    clock.set(MOMENT)
    user = support.make_employee()
    row = _make("telegram", user=user, created_at=MOMENT)
    chat = model("notify.ChatBinding").objects.get(user=user, channel="telegram").chat_id
    text = row.notification.text
    outcomes = [_retry(None, reason="network"), _retry(502)]
    for index, failure in enumerate(outcomes):
        with notify.fake_bot_send("telegram", raises=failure):
            assert _send(row) == "waiting"
        row = _fresh(row)
        assert len(row.log) == index + 1
        clock.advance(seconds=301)
    with notify.fake_bot_send("telegram"):
        assert _send(row) == "sent"
    row = _fresh(row)
    assert [entry["outcome"] for entry in row.log] == ["retry", "retry", "ok"]
    assert (row.log[0]["code"], row.log[0]["reason"]) == (None, "network")
    assert row.log[1]["code"] == 502 and row.log[2]["reason"] == ""
    stamps = [datetime.datetime.fromisoformat(entry["at"]) for entry in row.log]
    assert all(stamp.tzinfo is not None for stamp in stamps)
    assert stamps == [MOMENT, MOMENT + _sec(301), MOMENT + _sec(602)]
    dump = json.dumps(row.log, ensure_ascii=False)
    assert chat not in dump and text not in dump and settings.TELEGRAM_BOT_TOKEN not in dump
    # Web Push: запись на каждую подписку, номер подписки без адреса и ключей
    other = support.make_employee()
    first, second = notify.subscribe(other), notify.subscribe(other)
    push_row = _make("webpush", user=other, created_at=MOMENT)
    with notify.webpush_capture(by_endpoint={second.endpoint: "network"}):
        assert _send(push_row) == "sent"  # § 6.9: хотя бы одна подписка удалась
    push_row = _fresh(push_row)
    assert [(entry["sub"], entry["outcome"]) for entry in push_row.log] == [(first.pk, "ok"), (second.pk, "retry")]
    assert (push_row.log[1]["code"], push_row.log[1]["reason"]) == (None, "network")
    dump = json.dumps(push_row.log, ensure_ascii=False)
    for hidden_value in (first.endpoint, second.endpoint, first.p256dh, first.auth, second.p256dh, second.auth):
        assert hidden_value not in dump


# --- 24-26. срок, отказ служб, закрытый интернет ----------------------------------------------------

def test_delivery_is_enqueued_at_creation_and_sent_in_same_clock_minute(bots_on, django_capture_on_commit_callbacks):
    """NFR-302: доставка ставится при создании уведомления и уходит в ту же минуту (по настоящему времени)."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    user = support.make_employee()
    model("notify.UserNotifySettings").objects.create(user=user, quiet_mode="none")
    _bind(user, "telegram")
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            ids = dispatch.create(KIND, [Draft(user_id=user.pk, text="Тест " + secrets.token_hex(4),
                                               url="/tickets/1/", object_ref="servicedesk.ticket:1")])
    row = model("notify.Delivery").objects.get(notification_id=ids[0], channel="telegram")
    assert row.enqueued_at is not None and row.state == "waiting"
    assert [job.args for job in notify.queued()] == [(row.pk,)]
    notify.run_jobs()
    row = _fresh(row)
    sent = bots_on.sent("telegram")
    assert row.state == "sent" and len(sent) == 1
    chat = model("notify.ChatBinding").objects.get(user=user, channel="telegram").chat_id
    assert str(sent[0]["chat_id"]) == str(chat)
    note = model("notify.Notification").objects.get(pk=ids[0])
    done = datetime.datetime.fromisoformat(row.log[0]["at"])
    assert abs(note.created_at - started) < datetime.timedelta(minutes=1)
    assert datetime.timedelta(0) <= done - note.created_at < datetime.timedelta(minutes=1)
    assert row.enqueued_at - note.created_at < datetime.timedelta(minutes=1)


def test_service_failure_keeps_portal_notification_and_pages_respond(bots_on, webpush_on, clock):
    """NFR-304: сбой Telegram, MAX и push-сервиса не теряет уведомление на портале; страницы отвечают."""
    clock.set(MOMENT)
    user = support.make_employee()
    notify.subscribe(user)
    note = _note(user, created_at=MOMENT)
    rows = [_make(channel, user=user, notification=note) for channel in ("telegram", "max", "webpush")]
    with notify.fake_bot_send("telegram", raises=_retry(503)), notify.fake_bot_send("max", raises=_retry(500)), \
            notify.webpush_capture(status=500):
        assert [_send(row) for row in rows] == ["waiting"] * 3
    assert all(_fresh(row).attempts == 1 for row in rows)
    kept = model("notify.Notification").objects.get(pk=note.pk)
    assert (kept.read_at, kept.text) == (None, note.text)
    client = support.logged_in(user)
    page = client.get("/notifications/")
    assert page.status_code == 200 and f'data-notification="{note.pk}"' in page.content.decode()
    assert client.get("/notifications/bell/").status_code == 200


def test_closed_internet_leaves_deliveries_waiting_for_retries_and_portal_works(bots_on, webpush_on, clock):
    """NFR-304, FR-333: нет выхода в сеть — доставки `waiting` до повторов, портал работает; сеть вернулась — `sent`."""
    clock.set(MOMENT)
    user = support.make_employee()
    sub = notify.subscribe(user)
    note = _note(user, created_at=MOMENT)
    rows = [_make(channel, user=user, notification=note, created_at=MOMENT) for channel in ("telegram", "max", "webpush")]
    down = _retry(None, reason="network")
    with notify.fake_bot_send("telegram", raises=down), notify.fake_bot_send("max", raises=down), \
            notify.webpush_capture(error="network") as push:
        assert [_send(row) for row in rows] == ["waiting"] * 3
    assert len(push.requests) == 1
    for row in rows:
        row = _fresh(row)
        assert (row.state, row.attempts, row.enqueued_at, row.lease_until) == ("waiting", 1, None, None)
        assert row.due_at == MOMENT + _sec(60)
        assert row.log[-1]["outcome"] == "retry" and row.log[-1]["reason"] == "network"
    assert model("notify.PushSubscription").objects.filter(pk=sub.pk).exists()
    assert {name: _channel_code(name) for name in ("telegram", "max", "webpush")} == {
        "telegram": "unavailable", "max": "unavailable", "webpush": "unavailable"}
    client = support.logged_in(user)
    assert client.get("/notifications/").status_code == 200
    assert model("notify.Notification").objects.get(pk=note.pk).read_at is None
    clock.advance(seconds=61)
    with notify.fake_bot_send("telegram"), notify.fake_bot_send("max"), notify.webpush_capture():
        assert [_send(row) for row in rows] == ["sent"] * 3
    assert all(_fresh(row).attempts == 2 for row in rows)
