"""T-4116: отправка Web Push — ответы push-сервиса, нагрузка, присутствие вкладки (FR-324, FR-331, FR-332).
Сценарии 5, 7 и 11 спеки среза 004.

Доставка `Delivery(channel="webpush")` создаётся напрямую и выполняется `delivery.send_delivery` (контракт 6.9);
запросы к push-сервису перехватывает `webpush_capture` (5.3), нагрузку расшифровывают ключами браузера, присутствие
вкладки ставится записью в Valkey (7.4). Имена кода среза 004 импортируются внутри тестов.
"""
import importlib
import json
import secrets
import types
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

KIND = "servicedesk.assigned"
KIND_TEXT = "Вам назначена заявка"   # внешний текст вида (контракт 3.2, FR-317)


# --- помощники только этого файла -------------------------------------------------------------------

def _svc():
    return importlib.import_module("apps.notify.services.delivery")


def _resp(status: int, headers: dict | None = None):
    """Ответ push-сервиса для `webpush_capture` (форма — `apps.integrations.channel.Response`)."""
    from apps.integrations.channel import Response
    return Response(status, {name.lower(): value for name, value in (headers or {}).items()}, b"")


def _world(count: int = 1):
    """Сотрудник и `count` подписок Web Push с ключами браузера (по возрастанию номера)."""
    user = support.make_employee()
    pairs = [notify.browser_keys() for _ in range(count)]
    subs = [notify.subscribe(user, keys=pair) for pair in pairs]
    return types.SimpleNamespace(user=user, pairs=pairs, subs=subs)


def _delivery(user, *, text: str | None = None, url: str | None = None):
    """Ожидающая доставка Web Push по уведомлению вида `servicedesk.assigned`, срок — минуту назад."""
    note = model("notify.Notification").objects.create(
        user=user, kind=KIND, text=text or f"{KIND_TEXT} №{secrets.token_hex(3)}",
        url=url or "/servicedesk/tickets/1/", object_ref="ticket:1")
    return model("notify.Delivery").objects.create(
        notification=note, channel="webpush", state="waiting", due_at=timezone.now() - timedelta(minutes=1))


def _digest_delivery(user, count: int):
    digest = model("notify.Digest").objects.create(user=user, count_message=count)
    return model("notify.Delivery").objects.create(
        digest=digest, channel="webpush", state="waiting", due_at=timezone.now() - timedelta(minutes=1))


def _send(delivery) -> str:
    return _svc().send_delivery(delivery.pk)


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _log_by_sub(delivery) -> dict:
    """Записи `log` по номеру подписки (у Web Push в журнале доставки только записи подписок, решение E17)."""
    _fresh(delivery)
    result = {}
    for record in delivery.log:
        assert "sub" in record, f"в log Web Push есть запись без подписки: {record}"
        result.setdefault(record["sub"], []).append(record)
    return result


def _online(user, *, age: float = 0.0, name: str = "c1") -> None:
    """Присутствие вкладки: элемент множества `notify:online:<id>` с оценкой «сейчас минус age секунд» (7.4)."""
    from apps.core.services.valkey import conn
    conn().zadd(f"notify:online:{user.pk}", {name: timezone.now().timestamp() - age})


def _removed_events():
    return list(model("core.AuditEvent").objects.filter(action="notify.push_removed").order_by("id"))


# --- несколько подписок и их итоги (FR-324) ----------------------------------------------------------

def test_send_goes_to_every_subscription_of_the_user(webpush_on):
    """FR-324: запрос уходит на каждую подписку сотрудника по возрастанию номера, чужие подписки не трогаются."""
    world = _world(3)
    stranger = _world(1)
    delivery = _delivery(world.user)
    with notify.webpush_capture() as capture:
        outcome = _send(delivery)
    assert outcome == "sent"
    assert [request.url for request in capture.requests] == [sub.endpoint for sub in world.subs]
    assert stranger.subs[0].endpoint not in [request.url for request in capture.requests]
    assert all(request.method == "POST" for request in capture.requests)
    _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.attempts) == ("sent", "", 1)


def test_delivery_is_sent_if_at_least_one_subscription_succeeded(webpush_on):
    """FR-324: доставка удачна, если удалась хотя бы одна подписка; неудавшаяся остаётся в журнале повтором."""
    world = _world(2)
    delivery = _delivery(world.user)
    failing = world.subs[0]
    with notify.webpush_capture(by_endpoint={failing.endpoint: _resp(500)}) as capture:
        outcome = _send(delivery)
    assert outcome == "sent"
    assert len(capture.requests) == 2
    log = _log_by_sub(delivery)
    assert [record["outcome"] for record in log[world.subs[1].pk]] == ["ok"]
    assert [record["outcome"] for record in log[failing.pk]] == ["retry"]
    assert delivery.state == "sent" and delivery.reason == ""


def test_result_of_each_subscription_written_to_log_at_once_without_endpoints(webpush_on):
    """FR-324: итог каждой подписки дописывается в `log` сразу, без адреса; итоговой записи попытки нет (E17)."""
    world = _world(3)
    delivery = _delivery(world.user)
    first, second, third = world.subs
    seen = []

    def peek(request):
        seen.append(len(_fresh(delivery).log))

    with notify.webpush_capture(by_endpoint={second.endpoint: _resp(500), third.endpoint: "timeout"},
                                on_request=peek):
        assert _send(delivery) == "sent"
    assert seen == [0, 1, 2]
    log = _log_by_sub(delivery)
    assert sorted(log) == sorted(sub.pk for sub in world.subs)
    assert len(delivery.log) == 3
    ok, = log[first.pk]
    assert (ok["outcome"], ok["code"], ok["reason"]) == ("ok", 201, "")
    server_error, = log[second.pk]
    assert (server_error["outcome"], server_error["code"], server_error["reason"]) == ("retry", 500, "server_error")
    timed_out, = log[third.pk]
    assert (timed_out["outcome"], timed_out["code"], timed_out["reason"]) == ("retry", None, "timeout")
    assert all(record["at"] for record in delivery.log)
    dump = json.dumps(delivery.log, ensure_ascii=False)
    for sub, pair in zip(world.subs, world.pairs):
        assert sub.endpoint not in dump and "https://" not in dump
        assert pair.p256dh not in dump and pair.auth not in dump
    assert delivery.attempts == 1


def test_retry_sends_only_to_subscriptions_without_success_mark(webpush_on, clock):
    """FR-324: повтор шлёт только подпискам без удачной отметки в `log` (уже получившие не получают второй раз)."""
    world = _world(3)
    delivery = _delivery(world.user)
    first_sub, retry_sub, untouched = world.subs
    seen = []

    def jump(request):
        seen.append(request.url)
        if len(seen) == 2:    # бюджет 90 с выходит после второго запроса: третья подписка без попытки (доп. 11)
            clock.advance(seconds=91)

    with notify.webpush_capture(by_endpoint={retry_sub.endpoint: _resp(500)}, on_request=jump) as first:
        assert _send(delivery) == "waiting"
    assert [request.url for request in first.requests] == [first_sub.endpoint, retry_sub.endpoint]
    log = _log_by_sub(delivery)
    assert [record["outcome"] for record in log[first_sub.pk]] == ["ok"]
    assert [record["outcome"] for record in log[retry_sub.pk]] == ["retry"]
    assert untouched.pk not in log
    with notify.webpush_capture() as second:
        assert _send(delivery) == "sent"
    assert [request.url for request in second.requests] == [retry_sub.endpoint, untouched.endpoint]
    log = _log_by_sub(delivery)
    assert [record["outcome"] for record in log[first_sub.pk]] == ["ok"]
    assert [record["outcome"] for record in log[retry_sub.pk]] == ["retry", "ok"]
    assert [record["outcome"] for record in log[untouched.pk]] == ["ok"]
    assert delivery.attempts == 2 and delivery.state == "sent"


def test_job_after_90_seconds_starts_no_new_subscription_and_returns_delivery_to_waiting(webpush_on, clock):
    """FR-324: через 90 с после начала задание не начинает новых подписок; доставка — `waiting` с прежним сроком."""
    world = _world(3)
    delivery = _delivery(world.user)
    due_before = delivery.due_at
    fired = []

    def jump(request):
        if not fired:
            fired.append(request.url)
            clock.advance(seconds=91)

    with notify.webpush_capture(on_request=jump) as capture:
        outcome = _send(delivery)
    assert outcome == "waiting"
    assert [request.url for request in capture.requests] == [world.subs[0].endpoint]
    _fresh(delivery)
    assert (delivery.state, delivery.due_at, delivery.enqueued_at, delivery.lease_until) == ("waiting", due_before, None, None)
    assert delivery.attempts == 1
    assert sorted(_log_by_sub(delivery)) == [world.subs[0].pk]
    # следующий вызов доделывает оставшиеся подписки, получившая первой не получает повторно
    with notify.webpush_capture() as rest:
        assert _send(delivery) == "sent"
    assert [request.url for request in rest.requests] == [sub.endpoint for sub in world.subs[1:]]


def test_request_has_ttl_43200_normal_urgency_vapid_and_aes128gcm_headers(webpush_on, settings):
    """FR-324: запрос — POST на адрес подписки с TTL 43200, Urgency normal, Content-Encoding aes128gcm и VAPID."""
    world = _world(1)
    delivery = _delivery(world.user)
    with notify.webpush_capture() as capture:
        assert _send(delivery) == "sent"
    request, = capture.requests
    assert request.method == "POST" and request.url == world.subs[0].endpoint
    assert request.headers["ttl"] == "43200"
    assert request.headers["urgency"] == "normal"
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["content-type"] == "application/octet-stream"
    assert "topic" not in request.headers    # доп. 12: заголовка Topic у доставок нет
    authorization = request.headers["authorization"]
    assert authorization.startswith("vapid t=")
    assert authorization.endswith(", k=" + settings.VAPID_PUBLIC_KEY)
    assert request.timeout == 10
    assert request.body and request.body[20] == 65    # заголовок aes128gcm: idlen = 65


def test_response_201_sets_last_ok_at_of_subscription(webpush_on, clock):
    """FR-324: ответ 201 — попытка удачна, `last_ok_at` подписки равен времени отправки; у неудавшейся — пусто."""
    world = _world(2)
    delivery = _delivery(world.user)
    good, bad = world.subs
    assert good.last_ok_at is None
    with notify.webpush_capture(by_endpoint={bad.endpoint: _resp(500)}):
        assert _send(delivery) == "sent"
    assert _fresh(good).last_ok_at == timezone.now()
    assert _fresh(bad).last_ok_at is None


# --- ответы push-сервиса (FR-324, FR-332) ----------------------------------------------------------------

def _gone_case(status: int):
    world = _world(2)
    delivery = _delivery(world.user)
    gone, alive = world.subs
    expected_before = {"browser": gone.browser, "platform": gone.platform}
    with notify.webpush_capture(by_endpoint={gone.endpoint: _resp(status)}):
        assert _send(delivery) == "sent"
    PushSubscription = model("notify.PushSubscription")
    assert not PushSubscription.objects.filter(pk=gone.pk).exists()
    assert PushSubscription.objects.filter(pk=alive.pk).exists()
    log = _log_by_sub(delivery)
    record, = log[gone.pk]
    assert (record["outcome"], record["code"]) == ("gone", status)
    event, = _removed_events()
    assert event.actor_id is None
    assert (event.object_type, event.object_id) == ("user", str(world.user.pk))
    assert event.before == expected_before
    assert event.after == {"reason": "gone"}


def test_response_404_deletes_subscription_and_logs_by_system(webpush_on):
    """FR-332: ответ 404 — подписка удаляется, в журнале `notify.push_removed` от системы с причиной `gone`."""
    _gone_case(404)


def test_response_410_deletes_subscription_and_logs_by_system(webpush_on):
    """FR-332: ответ 410 — подписка удаляется, в журнале `notify.push_removed` от системы с причиной `gone`."""
    _gone_case(410)


def test_gone_for_all_subscriptions_marks_delivery_failed_no_subscriptions(webpush_on):
    """FR-332: все подписки ответили 404 или 410 — их не осталось, доставка `failed` с причиной `no_subscriptions`."""
    world = _world(2)
    delivery = _delivery(world.user)
    first, second = world.subs
    with notify.webpush_capture(by_endpoint={first.endpoint: _resp(404), second.endpoint: _resp(410)}):
        outcome = _send(delivery)
    assert outcome == "failed"
    _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.attempts, delivery.lease_until) == ("failed", "no_subscriptions", 1, None)
    assert not model("notify.PushSubscription").objects.filter(user=world.user).exists()
    log = _log_by_sub(delivery)
    assert [log[first.pk][0]["code"], log[second.pk][0]["code"]] == [404, 410]
    assert len(_removed_events()) == 2
    # повторной отправки нет
    with notify.webpush_capture() as again:
        assert _send(delivery) == "noop"
    assert again.requests == []


def _unrepeatable_case(status: int):
    world = _world(1)
    delivery = _delivery(world.user)
    with notify.webpush_capture(status=status) as capture:
        assert _send(delivery) == "failed"
    assert len(capture.requests) == 1
    _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.attempts, delivery.lease_until) == ("failed", "bad_request", 1, None)
    assert model("notify.PushSubscription").objects.filter(pk=world.subs[0].pk).exists()
    record, = _log_by_sub(delivery)[world.subs[0].pk]
    assert (record["outcome"], record["code"], record["reason"]) == ("failed", status, "bad_request")
    assert _removed_events() == []
    with notify.webpush_capture() as again:
        assert _send(delivery) == "noop"
    assert again.requests == []


def test_response_400_keeps_subscription_fails_without_retry_and_logs_code(webpush_on):
    """FR-324: ответ 400 — подписка остаётся, доставка `failed` (`bad_request`) без повторов, в `log` код ответа."""
    _unrepeatable_case(400)


def test_response_413_keeps_subscription_fails_without_retry(webpush_on):
    """FR-324: ответ 413 — подписка остаётся, доставка `failed` (`bad_request`) без повторов."""
    _unrepeatable_case(413)


def test_response_429_delays_retry_until_retry_after(webpush_on, clock):
    """FR-324: ответ 429 с `Retry-After` — повтор не раньше указанного срока (дальше расписания 1 минуты)."""
    world = _world(1)
    delivery = _delivery(world.user)
    started = timezone.now()
    with notify.webpush_capture(status=429, headers={"Retry-After": "7200"}):
        assert _send(delivery) == "waiting"
    _fresh(delivery)
    assert delivery.state == "waiting" and delivery.attempts == 1 and delivery.enqueued_at is None
    assert delivery.due_at >= started + timedelta(seconds=7200)
    record, = _log_by_sub(delivery)[world.subs[0].pk]
    assert (record["outcome"], record["code"], record["reason"]) == ("retry", 429, "rate_limited")
    status = model("notify.NotifySettings").objects.get(pk=1).channel_status
    assert status["webpush"]["code"] == "rate_limited"
    assert model("notify.PushSubscription").objects.filter(pk=world.subs[0].pk).exists()
    clock.advance(seconds=7199)
    with notify.webpush_capture() as early:
        assert _send(delivery) == "noop"
    assert early.requests == []
    clock.advance(seconds=2)
    with notify.webpush_capture() as later:
        assert _send(delivery) == "sent"
    assert len(later.requests) == 1


def test_response_500_retries_by_schedule(webpush_on, clock):
    """FR-324: ответ 5xx — повтор по расписанию (1 минута, затем 5), подписка остаётся, канал в статусе `unavailable`."""
    world = _world(1)
    delivery = _delivery(world.user)
    delays = _svc().RETRY_DELAYS
    with notify.webpush_capture(status=500):
        assert _send(delivery) == "waiting"
    _fresh(delivery)
    assert delivery.due_at == timezone.now() + timedelta(seconds=delays[0])
    assert (delivery.attempts, delivery.enqueued_at, delivery.lease_until) == (1, None, None)
    record, = _log_by_sub(delivery)[world.subs[0].pk]
    assert (record["outcome"], record["code"], record["reason"]) == ("retry", 500, "server_error")
    assert model("notify.NotifySettings").objects.get(pk=1).channel_status["webpush"]["code"] == "unavailable"
    assert model("notify.PushSubscription").objects.filter(pk=world.subs[0].pk).exists()
    clock.advance(seconds=delays[0])
    with notify.webpush_capture(status=503):
        assert _send(delivery) == "waiting"
    _fresh(delivery)
    assert delivery.attempts == 2
    assert delivery.due_at == timezone.now() + timedelta(seconds=delays[1])


def test_network_error_and_timeout_retry_by_schedule(webpush_on, clock):
    """FR-324: сбой сети и таймаут — повтор по расписанию; в `log` код пуст, причины `network` и `timeout`."""
    world = _world(2)
    delivery = _delivery(world.user)
    broken, slow = world.subs
    with notify.webpush_capture(by_endpoint={broken.endpoint: "network", slow.endpoint: "timeout"}):
        assert _send(delivery) == "waiting"
    _fresh(delivery)
    assert delivery.due_at == timezone.now() + timedelta(seconds=_svc().RETRY_DELAYS[0])
    log = _log_by_sub(delivery)
    network, = log[broken.pk]
    timeout, = log[slow.pk]
    assert (network["outcome"], network["code"], network["reason"]) == ("retry", None, "network")
    assert (timeout["outcome"], timeout["code"], timeout["reason"]) == ("retry", None, "timeout")
    assert model("notify.NotifySettings").objects.get(pk=1).channel_status["webpush"]["code"] == "unavailable"
    assert model("notify.PushSubscription").objects.filter(user=world.user).count() == 2


def test_redirect_3xx_is_not_followed_and_fails_without_retries(webpush_on):
    """FR-324: ответ 3xx не исполняется: один запрос, доставка `failed` с причиной `redirect`, повторов нет."""
    world = _world(1)
    delivery = _delivery(world.user)
    with notify.webpush_capture(status=302, headers={"Location": "https://internal.example.test/x"}) as capture:
        assert _send(delivery) == "failed"
    assert [request.url for request in capture.requests] == [world.subs[0].endpoint]
    _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.attempts) == ("failed", "redirect", 1)
    record, = _log_by_sub(delivery)[world.subs[0].pk]
    assert (record["outcome"], record["code"], record["reason"]) == ("failed", 302, "redirect")
    assert model("notify.PushSubscription").objects.filter(pk=world.subs[0].pk).exists()
    with notify.webpush_capture() as again:
        assert _send(delivery) == "noop"
    assert again.requests == []


# --- нагрузка (FR-324) ---------------------------------------------------------------------------------

def test_payload_decrypts_to_external_text_url_and_tag(webpush_on):
    """FR-324: нагрузка расшифровывается ключами браузера в `title` (внешний текст вида), `url`, `tag`."""
    world = _world(1)
    delivery = _delivery(world.user)
    with notify.webpush_capture() as capture:
        assert _send(delivery) == "sent"
    request, = capture.requests
    payload = capture.decrypt(request, world.pairs[0])
    assert payload == {"title": KIND_TEXT, "url": "/notifications/", "tag": f"n-{delivery.notification_id}"}


def test_payload_has_no_ticket_number_or_subject(webpush_on):
    """FR-324: в нагрузке нет номера и темы заявки, ссылки на заявку и текста записи портала — только внешний текст."""
    world = _world(1)
    number, subject = "ZK81734Q", "Принтер издаёт треск"
    delivery = _delivery(world.user, text=f"{KIND_TEXT} №{number}: {subject}", url=f"/servicedesk/tickets/{number}/")
    with notify.webpush_capture() as capture:
        assert _send(delivery) == "sent"
    payload = capture.decrypt(capture.requests[0], world.pairs[0])
    assert set(payload) == {"title", "url", "tag"}
    dump = json.dumps(payload, ensure_ascii=False)
    for leaked in (number, subject, "Принтер", "/servicedesk/"):
        assert leaked not in dump


def test_payload_url_is_notifications_page_and_tag_is_n_plus_id(webpush_on):
    """FR-324: `url` — страница `/notifications/`, `tag` — `n-<номер уведомления>`, у разных уведомлений разный."""
    world = _world(1)
    first, second = _delivery(world.user, url="/a/"), _delivery(world.user, url="/b/")
    with notify.webpush_capture() as capture:
        assert _send(first) == "sent" and _send(second) == "sent"
    payloads = [capture.decrypt(request, world.pairs[0]) for request in capture.requests]
    assert [payload["url"] for payload in payloads] == ["/notifications/", "/notifications/"]
    assert [payload["tag"] for payload in payloads] == [f"n-{first.notification_id}", f"n-{second.notification_id}"]
    assert payloads[0]["tag"] != payloads[1]["tag"]


def test_digest_payload_has_count_text_and_digest_tag(webpush_on):
    """FR-324: у доставки сводки `title` — «У вас N новых уведомлений» (склонение, § 15.6), `tag` — `digest`."""
    world = _world(1)
    cases = [(1, "У вас 1 новое уведомление"), (2, "У вас 2 новых уведомления"),
             (5, "У вас 5 новых уведомлений"), (21, "У вас 21 новое уведомление")]
    for count, text in cases:
        delivery = _digest_delivery(world.user, count)
        with notify.webpush_capture() as capture:
            assert _send(delivery) == "sent"
        payload = capture.decrypt(capture.requests[0], world.pairs[0])
        assert payload == {"title": text, "url": "/notifications/", "tag": "digest"}


# --- присутствие вкладки (FR-331) ------------------------------------------------------------------------

def test_open_tab_presence_skips_webpush_even_if_browser_denied_notifications(webpush_on):
    """FR-331: есть свежее соединение живых обновлений — Web Push не уходит (`skipped`, `tab_open`), что бы ни
    решил браузер насчёт системных уведомлений: сервер этого не знает и во вкладке обновляется колокольчик."""
    world = _world(1)
    delivery = _delivery(world.user)
    _online(world.user, age=0)
    live = importlib.import_module("apps.notify.services.live")
    assert live.is_online(world.user.pk) is True
    with notify.webpush_capture() as capture:
        assert _send(delivery) == "skipped"
    assert capture.requests == []
    _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.lease_until) == ("skipped", "tab_open", None)
    assert model("notify.PushSubscription").objects.filter(pk=world.subs[0].pk).exists()


def test_no_live_connection_sends_webpush(webpush_on):
    """FR-331: соединения нет (чужое соединение не в счёт) — Web Push уходит."""
    world = _world(1)
    other = _world(1)
    delivery = _delivery(world.user)
    _online(other.user, age=0)
    live = importlib.import_module("apps.notify.services.live")
    assert live.is_online(world.user.pk) is False
    with notify.webpush_capture() as capture:
        assert _send(delivery) == "sent"
    assert [request.url for request in capture.requests] == [world.subs[0].endpoint]


def test_presence_older_than_60_seconds_does_not_block_webpush(webpush_on):
    """FR-331: отметка старше 60 секунд — вкладка не считается открытой и Web Push уходит; свежая (30 с) блокирует."""
    world = _world(1)
    fresh_delivery = _delivery(world.user)
    _online(world.user, age=30)
    with notify.webpush_capture() as blocked:
        assert _send(fresh_delivery) == "skipped"
    assert blocked.requests == []
    stale_delivery = _delivery(world.user)
    from apps.core.services.valkey import conn
    conn().delete(f"notify:online:{world.user.pk}")
    _online(world.user, age=61)
    live = importlib.import_module("apps.notify.services.live")
    assert live.is_online(world.user.pk) is False
    with notify.webpush_capture() as capture:
        assert _send(stale_delivery) == "sent"
    assert [request.url for request in capture.requests] == [world.subs[0].endpoint]


def test_webpush_to_blocked_account_is_not_sent(webpush_on):
    """FR-324: заблокированная учётная запись — доставка `skipped` с причиной `user_blocked`, запросов нет."""
    world = _world(1)
    delivery = _delivery(world.user)
    world.user.state = "blocked"
    world.user.save()
    with notify.webpush_capture() as capture:
        assert _send(delivery) == "skipped"
    assert capture.requests == []
    _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.lease_until) == ("skipped", "user_blocked", None)
