"""T-7126a: изменения `core/ws.py`, `notify/consumers.py`, `notify/services/live.py`, `config/asgi.py` и
`CHANNEL_LAYERS`; прежнее поведение соединения `/ws/notify/` (FR-626, FR-627, FR-641, NFR-614).

`core.ws.SessionGuardMixin` проверяется на тестовом потребителе, собранном в самом тесте (CONTRACT-007, 5.8, решение 49
задач): подмена `apps.core.services.sessions.ws_state` и короткий `check_interval()`. Для `NotifyConsumer` — прежние
приёмы `test_notify_ws.py`: настоящее соединение через `hub.connect`, интервал — подменой
`apps.notify.consumers.CHECK_INTERVAL`. Сообщения слоя в группы шлёт сам тест, чтобы проверить обработчики
потребителя (`notify.update`, `notify.html`). `live.push` проверяется подменой `apps.notify.services.live.get_channel_layer`
(фабрика принимает любые аргументы). Маршруты `asgi` без ленты — `support_feed.reload_asgi_without_feed()`.
Разделы 3.2, 4.2, 5.8, 11 контракта `CONTRACT-007.md`; план «Проверка» → «Изменения кода прежних срезов».

Код среза на уровне модуля не импортируется (CONTRACT-007, «Правила для всех тестов»).
"""
import asyncio
import datetime
import logging
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from tests import support
from tests import support_feed as feed
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROBE_PATH = "/ws/probe/"


# --- помощники только этого файла ----------------------------------------------------------------------------------

def _probe_class(trace, *, interval=0.2):
    """Тестовый потребитель на примеси: `check_interval()` короткий, `on_check()` пишет вызов в `trace`
    (CONTRACT-007, 5.8). `connect` — по описанию `guard_connect`: не «ok» — примесь сама принимает и закрывает."""
    from channels.generic.websocket import AsyncWebsocketConsumer

    from apps.core.ws import SessionGuardMixin

    class Probe(SessionGuardMixin, AsyncWebsocketConsumer):
        def check_interval(self):
            return interval

        async def on_check(self):
            trace.append("on_check")

        async def connect(self):
            if not await self.guard_connect():
                return
            await self.accept()
            self.start_guard()

        async def disconnect(self, code):
            self.stop_guard()

    return Probe


async def _connect_probe(hub, consumer, *, session, user):
    """Рукопожатие с тестовым потребителем: свой маршрутизатор, `scope` с сессией и пользователем."""
    from asgiref.testing import ApplicationCommunicator
    from channels.routing import URLRouter
    from django.urls import re_path

    router = URLRouter([re_path(r"^ws/probe/$", consumer.as_asgi())])
    scope = {"type": "websocket", "path": PROBE_PATH, "raw_path": PROBE_PATH.encode(), "query_string": b"",
             "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
             "scheme": "ws", "subprotocols": [], "session": session, "user": user}
    conn = notify.WsClient(ApplicationCommunicator(router, scope))
    hub._clients.append(conn)
    await conn._comm.send_input({"type": "websocket.connect"})
    message = await conn._next_output(2.0)
    assert message is not None, "потребитель не ответил на websocket.connect за 2 с"
    if message["type"] == "websocket.accept":
        conn.accepted = True
    elif message["type"] == "websocket.close":
        conn._note_close(message)
        conn._finished = True
    return conn


async def _wait_until(condition, timeout=3.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.05)
    return condition()


async def _group_send(user, message) -> None:
    """Сообщение слоя каналов в группу колокольчика сотрудника."""
    from channels.layers import get_channel_layer

    await get_channel_layer().group_send(f"notify.u.{user.pk}", message)


def _sid(client) -> str:
    return client.cookies[django_settings.SESSION_COOKIE_NAME].value


def _note(user, text="Уведомление", read=False):
    return model("notify.Notification").objects.create(
        user=user, kind="test.thing", text=text, url="/test/", object_ref="",
        read_at=timezone.now() if read else None)


def _count(frame) -> tuple[str, str]:
    fragment = notify.ws_fragments(frame)["notify-count"]
    return fragment.attrs["data-count"], fragment.text.strip()


def _scores(user) -> list[float]:
    conn = support.valkey()
    try:
        return [score for _, score in conn.zrange(f"notify:online:{user.pk}", 0, -1, withscores=True)]
    finally:
        conn.close()


def _route_texts(routes) -> list[str]:
    return [str(route.pattern) for route in routes]


# --- core.ws.SessionGuardMixin ---------------------------------------------------------------------------------------

def test_session_guard_with_bad_ws_state_on_connect_accepts_and_closes_4401(monkeypatch):
    """FR-627: `guard_connect` зовёт `sessions.ws_state(session, user)` (атрибутом модуля) и при состоянии не «ok»
    принимает соединение и закрывает его кодом 4401; потребитель после этого не продолжает подключение."""
    from apps.core import ws

    calls = []

    def fake_state(session, user):
        calls.append((session, user))
        return "expired"

    monkeypatch.setattr("apps.core.services.sessions.ws_state", fake_state)
    session, user = object(), SimpleNamespace(pk=7, id=7)
    probe = _probe_class([])
    assert ws.CLOSE_SESSION == 4401

    async def scenario(hub):
        conn = await _connect_probe(hub, probe, session=session, user=user)
        assert conn.accepted, "соединение сначала принимается"
        assert await conn.wait_close(2.0) == 4401

    notify.ws_run(scenario)
    assert len(calls) == 1 and calls[0][0] is session and calls[0][1] is user


def test_session_guard_loop_waits_check_interval_then_calls_on_check_and_ws_state(monkeypatch):
    """FR-627: цикл — сон `check_interval()`, затем `on_check()`, затем `ws_state`; пока состояние «ok», соединение
    живёт; не «ok» — закрытие 4401 и выход из цикла (после закрытия вызовов больше нет)."""
    trace, state = [], {"value": "ok"}

    def fake_state(session, user):
        trace.append("ws_state")
        return state["value"]

    monkeypatch.setattr("apps.core.services.sessions.ws_state", fake_state)
    probe = _probe_class(trace, interval=0.3)

    async def scenario(hub):
        conn = await _connect_probe(hub, probe, session=object(), user=SimpleNamespace(pk=7, id=7))
        assert conn.accepted and trace == ["ws_state"], "при подключении — одна проверка"
        await asyncio.sleep(0.12)
        assert trace == ["ws_state"], "до конца первого ожидания ни on_check, ни ws_state не зовутся"
        assert await _wait_until(lambda: len(trace) >= 5)
        assert trace[:5] == ["ws_state", "on_check", "ws_state", "on_check", "ws_state"]
        assert conn.close_code is None
        state["value"] = "idle"
        assert await conn.wait_close(2.0) == 4401
        assert trace[-2:] == ["on_check", "ws_state"], "порядок цикла: on_check, затем ws_state"
        seen = len(trace)
        await asyncio.sleep(0.8)
        assert len(trace) == seen, "после закрытия цикл продолжается"

    notify.ws_run(scenario)


# --- NotifyConsumer ------------------------------------------------------------------------------------------------

def test_notify_consumer_check_interval_patch_still_applies(monkeypatch):
    """FR-627: подмена `apps.notify.consumers.CHECK_INTERVAL` действует, как прежде (интервал читается методом
    потребителя при каждом ожидании): проверка сессии идёт каждые 0,2 с, а не раз в 25 с."""
    from apps.core.services import sessions

    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)
    real, stamps = sessions.ws_state, []

    def spy(session, user):
        stamps.append(time.monotonic())
        return real(session, user)

    monkeypatch.setattr("apps.core.services.sessions.ws_state", spy)
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted and await conn.receive() is not None
        assert await _wait_until(lambda: len(stamps) >= 4, timeout=3.0), f"проверок за 3 с: {len(stamps)}"
        gaps = [later - earlier for earlier, later in zip(stamps[1:], stamps[2:])]
        assert all(0.1 <= gap <= 1.0 for gap in gaps), gaps
        assert conn.close_code is None

    notify.ws_run(scenario)


def test_notify_consumer_count_system_notice_and_group_binding_as_before():
    """FR-627: `NotifyConsumer` — на подключении один кадр с числом непрочитанных; привязан к группе
    `notify.u.<id>` (`live.group`), на сообщение `notify.update` отвечает одним кадром «число, системное
    уведомление»; сообщения чужой группы не получает."""
    from apps.notify.services import live

    user, other = support.make_employee(), support.make_employee()
    _note(user), _note(user), _note(user, read=True)
    client = support.logged_in(user)
    assert live.group(user.pk) == f"notify.u.{user.pk}"
    toast = {"text": "Системное", "url": "/notifications/9/open/", "tag": "n-9", "show": True}

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        first = await conn.receive()
        assert first is not None and _count(first) == ("2", "2")
        assert await conn.receive(0.3) is None, "при подключении приходит один кадр"
        await _group_send(user, {"type": "notify.update", "count": 5, "toast": toast, "binding": None})
        frame = await conn.receive(2.0)
        assert frame is not None
        fragments = notify.ws_fragments(frame)
        assert list(fragments) == ["notify-count", "notify-toast"], "порядок: число, системное уведомление"
        assert fragments["notify-count"].attrs["data-count"] == "5"
        assert fragments["notify-toast"].attrs["data-text"] == "Системное"
        assert fragments["notify-toast"].attrs["data-url"] == "/notifications/9/open/"
        assert fragments["notify-toast"].attrs["data-tag"] == "n-9"
        assert fragments["notify-toast"].attrs["data-show"] == "1"
        await _group_send(other, {"type": "notify.update", "count": 9, "toast": None, "binding": None})
        assert await conn.receive(0.4) is None, "сообщение чужой группы пришло"

    notify.ws_run(scenario)


def test_notify_consumer_on_check_marks_presence_online(monkeypatch):
    """FR-627: `on_check` колокольчика — отметка присутствия `live.mark_online`: на каждой проверке оценка элемента
    присутствия растёт (прежнее поведение, порядок «сон, on_check, ws_state» прежний)."""
    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted and await conn.receive() is not None
        first = await hub.do(_scores, user)
        assert len(first) == 1
        await asyncio.sleep(0.7)
        later = await hub.do(_scores, user)
        assert len(later) == 1 and later[0] > first[0], "проверка обновляет отметку присутствия"
        assert conn.close_code is None

    notify.ws_run(scenario)


def test_notify_consumer_ignores_incoming_messages_as_before():
    """FR-627: входящие сообщения колокольчика игнорируются: ответа нет, соединение открыто, сессию они не продлевают
    (`last_activity` не меняется)."""
    user = support.make_employee()
    client = support.logged_in(user)
    sid = _sid(client)
    before = timezone.now() - datetime.timedelta(minutes=10)
    model("core.UserSession").objects.filter(session_key=sid).update(last_activity=before)

    def activity():
        return model("core.UserSession").objects.get(session_key=sid).last_activity

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted and await conn.receive() is not None
        await conn.send("ping")
        await conn.send('{"type": "anything"}')
        assert await conn.receive(0.4) is None, "на сообщения клиента ответа нет"
        assert conn.close_code is None
        assert await hub.do(activity) == before

    notify.ws_run(scenario)


def test_notify_consumer_check_loop_error_closes_with_1013(monkeypatch, caplog):
    """FR-627: любая ошибка в цикле проверки (исправление дефекта среза 004: прежде цикл молча прекращался и соединение
    оставалось без проверки) пишет предупреждение в журнал приложения и закрывает соединение кодом 1013."""
    from apps.core.services import sessions

    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.15)
    real, calls = sessions.ws_state, []

    def flaky(session, user):
        calls.append(1)
        if len(calls) == 1:
            return real(session, user)          # подключение проходит
        raise RuntimeError("сбой проверки сессии")

    monkeypatch.setattr("apps.core.services.sessions.ws_state", flaky)
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted and await conn.receive() is not None
        with caplog.at_level(logging.WARNING):
            assert await conn.wait_close(3.0) == 1013

    notify.ws_run(scenario)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == "apps.core.ws"]
    assert warnings, "ошибка цикла проверки должна попасть в журнал приложения предупреждением"


def test_notify_html_handler_sends_ready_fragment_as_is():
    """FR-626, FR-627: на сообщение слоя `notify.html` колокольчик отправляет `event["html"]` как есть — готовый
    фрагмент числа «Ленты» (`#menu-badge-feed` с `hx-swap-oob`), без обёрток и правок."""
    user = support.make_employee()
    client = support.logged_in(user)
    html = '<span id="menu-badge-feed" class="badge" hx-swap-oob="true" data-menu-live-badge data-count="3">3</span>'

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted and await conn.receive() is not None
        await _group_send(user, {"type": "notify.html", "html": html})
        frame = await conn.receive(2.0)
        assert frame == html
        assert await conn.receive(0.3) is None and conn.close_code is None

    notify.ws_run(scenario)


# --- notify.services.live.push ---------------------------------------------------------------------------------------

class _RecordingLayer:
    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


def test_live_push_takes_publish_channel_layer(monkeypatch):
    """NFR-614: `live.push` берёт слой `publish` (`get_channel_layer("publish")`) — иначе зависший Valkey держал бы
    действие 30 с; фабрика зовётся атрибутом модуля `apps.notify.services.live.get_channel_layer`."""
    from apps.notify.services import live

    layer, asked = _RecordingLayer(), []

    def factory(*args, **kwargs):
        asked.append((args, kwargs))
        return layer

    monkeypatch.setattr("apps.notify.services.live.get_channel_layer", factory)
    user = support.make_employee()
    live.push([user.pk])
    assert asked, "фабрика слоя не вызвана"
    assert all(args[:1] == ("publish",) or kwargs.get("alias") == "publish" for args, kwargs in asked), asked
    assert [group for group, _ in layer.sent] == [f"notify.u.{user.pk}"]


def test_live_push_frame_and_parts_order_as_before(monkeypatch):
    """FR-627: сообщение слоя прежнее — `notify.update` с числом непрочитанных, системным уведомлением и привязкой по
    одному на сотрудника в порядке списка; кадр в соединении — части в порядке «число, уведомление, привязка»."""
    from apps.notify.services import live

    first, second = support.make_employee(), support.make_employee()
    _note(first), _note(first), _note(second)
    toast = {"text": "Системное", "url": "/notifications/1/open/", "tag": "n-1", "show": True}
    layer = _RecordingLayer()
    monkeypatch.setattr("apps.notify.services.live.get_channel_layer", lambda *args, **kwargs: layer)
    live.push([first.pk, second.pk], toasts={first.pk: toast}, binding="telegram")
    monkeypatch.undo()
    assert layer.sent == [
        (f"notify.u.{first.pk}", {"type": "notify.update", "count": 2, "toast": toast, "binding": "telegram"}),
        (f"notify.u.{second.pk}", {"type": "notify.update", "count": 1, "toast": None, "binding": "telegram"}),
    ]

    client = support.logged_in(first)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted and await conn.receive() is not None
        await hub.do(live.push, [first.pk], toasts={first.pk: toast}, binding="telegram")
        frame = await conn.receive(2.0)
        assert frame is not None, "кадр после live.push не пришёл"
        parts = list(notify.ws_fragments(frame))
        assert parts[:2] == ["notify-count", "notify-toast"] and parts[2:] == ["notify-binding-telegram"], parts

    notify.ws_run(scenario)


def test_live_push_layer_failure_only_logs_warning(monkeypatch, caplog):
    """NFR-614: сбой слоя каналов (нет слоя, ошибка фабрики с аргументом `"publish"`, ошибка отправки в группу)
    `live.push` перехватывает: исключения нет, в журнал `apps.notify.services.live` пишется предупреждение, запись
    уведомления остаётся."""
    from apps.notify.services import live

    user = support.make_employee()
    note = _note(user)

    def broken_factory(*args, **kwargs):
        raise ConnectionError("слой каналов недоступен")

    class BrokenLayer:
        async def group_send(self, group, message):
            raise OSError("отправка в группу не удалась")

    for factory in (broken_factory, lambda *args, **kwargs: BrokenLayer(), lambda *args, **kwargs: None):
        caplog.clear()
        monkeypatch.setattr("apps.notify.services.live.get_channel_layer", factory)
        with caplog.at_level(logging.WARNING, logger="apps.notify.services.live"):
            assert live.push([user.pk]) is None
        warnings = [r for r in caplog.records if r.name == "apps.notify.services.live" and r.levelno == logging.WARNING]
        assert warnings, "сбой слоя должен попасть в журнал приложения предупреждением"
    assert model("notify.Notification").objects.filter(pk=note.pk).exists()


# --- CHANNEL_LAYERS --------------------------------------------------------------------------------------------------

def test_publish_layer_has_same_host_and_prefix_2_second_timeouts_and_300_connections():
    """NFR-614: слой `publish` — тот же адрес и префикс `crm-asgi`, что у `default`; `socket_timeout` 2 с,
    `socket_connect_timeout` 2 с, `max_connections` 300; настоящий слой собирается из этой настройки."""
    from channels.layers import channel_layers

    default, publish = django_settings.CHANNEL_LAYERS["default"], django_settings.CHANNEL_LAYERS["publish"]
    assert publish == {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [{"address": django_settings.VALKEY_URL, "socket_timeout": 2, "max_connections": 300,
                              "socket_connect_timeout": 2}],
                   "prefix": "crm-asgi"},
    }
    assert publish["CONFIG"]["hosts"][0]["address"] == default["CONFIG"]["hosts"][0]["address"]
    assert publish["CONFIG"]["prefix"] == default["CONFIG"]["prefix"] == "crm-asgi"
    layer = channel_layers["publish"]
    assert type(layer).__name__ == "RedisChannelLayer" and layer is not channel_layers["default"]


def test_default_layer_unchanged_and_channel_layers_have_two_keys():
    """NFR-614: слой `default` прежний (таймаут 30 с, 300 соединений, соединение 2 с, префикс `crm-asgi`); ключей
    `CHANNEL_LAYERS` два — `default` и `publish`."""
    assert set(django_settings.CHANNEL_LAYERS) == {"default", "publish"}
    assert django_settings.CHANNEL_LAYERS["default"] == {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [{"address": django_settings.VALKEY_URL, "socket_timeout": 30, "max_connections": 300,
                              "socket_connect_timeout": 2}],
                   "prefix": "crm-asgi"},
    }


# --- config/asgi.py ----------------------------------------------------------------------------------------------

def test_asgi_websocket_patterns_include_notify_routes_and_feed_routing_list_when_feed_installed():
    """FR-627, FR-641: `websocket_urlpatterns` — маршруты `notify`, затем (при установленной ленте) маршруты
    `feed.routing`; маршрут ленты — `^ws/feed/$` с `FeedConsumer`; в маршрутизатор идёт эта переменная, а подключение
    ленты стоит под `apps.is_installed("apps.feed")`."""
    import config.asgi as asgi
    from apps.feed import routing as feed_routing
    from apps.feed.consumers import FeedConsumer
    from apps.notify import routing as notify_routing

    patterns = asgi.websocket_urlpatterns
    assert patterns == list(notify_routing.websocket_urlpatterns) + list(feed_routing.websocket_urlpatterns)
    assert _route_texts(patterns)[-1] == "^ws/feed/$" and "ws/notify/" in _route_texts(patterns)
    assert getattr(patterns[-1].callback, "consumer_class", None) is FeedConsumer
    assert patterns[-1].pattern.match("ws/feed/") is not None
    source = re.sub(r"\s+", "", (BACKEND_DIR / "config" / "asgi.py").read_text(encoding="utf-8"))
    assert re.search(r"AllowedHostsOriginValidator\(AuthMiddlewareStack\(URLRouter\((?:[\w.]+\.)?websocket_urlpatterns\)\)\)",
                     source), "в маршрутизатор идёт переменная websocket_urlpatterns"
    assert 'apps.is_installed("apps.feed")' in source, "маршруты ленты подключаются под apps.is_installed"


def test_asgi_without_feed_has_no_ws_feed_route_and_ws_notify_as_before():
    """FR-641: без `apps.feed` маршрутов ленты нет, маршрут `ws/notify/` прежний (`NotifyConsumer`), приложение —
    по-прежнему `ProtocolTypeRouter` с `http` и `websocket` за проверкой Origin."""
    from channels.routing import ProtocolTypeRouter
    from channels.security.websocket import OriginValidator

    from apps.notify import routing as notify_routing
    from apps.notify.consumers import NotifyConsumer

    with feed.reload_asgi_without_feed() as module:
        patterns = module.websocket_urlpatterns
        assert _route_texts(patterns) == _route_texts(notify_routing.websocket_urlpatterns) == ["ws/notify/"]
        assert not any("feed" in text for text in _route_texts(patterns))
        assert getattr(patterns[0].callback, "consumer_class", None) is NotifyConsumer
        assert isinstance(module.application, ProtocolTypeRouter)
        assert set(module.application.application_mapping) == {"http", "websocket"}
        assert isinstance(module.application.application_mapping["websocket"], OriginValidator)
