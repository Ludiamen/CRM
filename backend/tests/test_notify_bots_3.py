"""T-4120: служба опроса ботов и события ботов на учебной службе `fakebots` (FR-325, FR-332, FR-336, FR-340, FR-344).

Сценарии 6 и 10 спеки среза 004; механизм — план «Telegram и MAX» («Служба опроса»), контракт 5.4, 6.14, 6.15, 8.2.
Шаг опроса — `bots.poll_once(channel, wait=…)` против настоящей учебной службы (`bots_on`; события —
`FakeBots.put_telegram` и `put_max`); запросы адаптеров перехватывает `bots_capture(module, passthrough=True)`.
Учебная служба держит запрос до `timeout` секунд, пока нет событий: каждый шаг опроса здесь идёт при уже
положенных событиях. Ответ бота уходит после фиксации (`transaction.on_commit`), поэтому шаг опроса, после
которого читаются отправленные сообщения, выполняется внутри `django_capture_on_commit_callbacks(execute=True)`.
Сбой `handle_update` — обёртка над `bots.handle_update` только в двух тестах (дополнение 1 контракта, раздел 17).
Цикл `run_loop` (`apps.notify.management.commands.notify_poll`) — подменой `bots.active`, `bots.start_cycle`,
`bots.poll_once` чистыми записывающими фальшивками. Имена кода среза 004 — внутри тестов или через `support.model`.
"""
import importlib
import logging
import threading
import time
import urllib.parse

import pytest
from django.db import transaction

from tests import support
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

ASK_CODE = "Отправьте код из раздела «Мои уведомления» портала"
BOUND = {"telegram": "Telegram привязан к вашей учётной записи портала",
         "max": "MAX привязан к вашей учётной записи портала"}
UNBOUND_TEXT = {"telegram": "Telegram отвязан: бот недоступен", "max": "MAX отвязан: бот недоступен"}


# --- помощники только этого файла -------------------------------------------------------------------

def _bots():
    from apps.notify.services import bots
    return bots


def _client(channel: str):
    return importlib.import_module(f"apps.integrations.{channel}.client")


def _tg_text(chat_id: int, text: str, chat_type: str = "private") -> dict:
    return {"message": {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": chat_id}, "text": text}}


def _tg_kicked(chat_id: int, chat_type: str = "private") -> dict:
    return {"my_chat_member": {"chat": {"id": chat_id, "type": chat_type}, "new_chat_member": {"status": "kicked"}}}


def _max_started(chat_id: int) -> dict:
    return {"update_type": "bot_started", "chat_id": chat_id, "user": {"user_id": chat_id}}


def _max_stopped(chat_id: int) -> dict:
    return {"update_type": "bot_stopped", "chat_id": chat_id, "user": {"user_id": chat_id}}


def _max_text(chat_id: int, text: str, chat_type: str = "dialog") -> dict:
    return {"update_type": "message_created",
            "message": {"sender": {"user_id": chat_id}, "recipient": {"chat_id": chat_id, "chat_type": chat_type},
                        "body": {"text": text}}}


def _ignored(channel: str, chat_id: int = 9999) -> dict:
    """Событие из группы: `handle_update` отвечает `ignored` без ответа и без записи."""
    return _tg_text(chat_id, "привет", "group") if channel == "telegram" else _max_text(chat_id, "привет", "chat")


def _put(fake, channel: str, events):
    return fake.put_telegram(events) if channel == "telegram" else fake.put_max(events)


def _poll(capture, channel: str, **kwargs):
    """Один шаг опроса; ответы бота после фиксации уходят при выходе из блока."""
    bots = _bots()
    with capture(execute=True):
        return bots.poll_once(channel, **kwargs)


def _method(request) -> str:
    """Имя метода адаптера по последнему сегменту пути (адрес целиком не печатаем: в нём токен)."""
    return urllib.parse.urlsplit(request.url).path.rsplit("/", 1)[-1]


def _of(capture_obj, name: str) -> list:
    return [r for r in capture_obj.requests if _method(r) == name]


def _state(channel: str):
    return model("notify.BotState").objects.filter(channel=channel).first()


def _cursor(channel: str) -> str:
    row = _state(channel)
    return "" if row is None else row.cursor


def _bind(user, channel: str, chat_id):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=str(chat_id))


def _binding(user, channel: str):
    return model("notify.ChatBinding").objects.filter(user=user, channel=channel).first()


def _texts(fake, channel: str) -> list[str]:
    return [m["text"] for m in fake.sent(channel)]


def _audit(action: str, **filters):
    return list(model("core.AuditEvent").objects.filter(action=action, **filters).order_by("id"))


def _set_active(settings, channel: str, *, enabled: bool = True, has_token: bool = True) -> None:
    model("notify.NotifySettings").objects.filter(pk=1).update(**{f"{channel}_enabled": enabled})
    if not has_token:
        setattr(settings, f"{channel.upper()}_BOT_TOKEN", "")


class _Stop(threading.Event):
    """Событие остановки для `run_loop` без потоков: `wait` запоминает паузу и взводит событие на `limit`-м ожидании."""

    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.waits: list = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if len(self.waits) >= self.limit:
            self.set()
        return self.is_set()


class _Spy:
    """Записывающие фальшивки `bots.active`, `bots.start_cycle`, `bots.poll_once` (чистые: базы не трогают)."""

    def __init__(self, monkeypatch, *, active, poll_pause=0.0, stop=None, cap: int = 40):
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._active, self._poll_pause, self._stop, self._cap = active, poll_pause, stop, cap
        bots = _bots()
        monkeypatch.setattr(bots, "active", self.active)
        monkeypatch.setattr(bots, "start_cycle", self.start_cycle)
        monkeypatch.setattr(bots, "poll_once", self.poll_once)

    def _note(self, name, channel):
        with self._lock:
            self.calls.append((name, channel))
            if self._stop is not None and len(self.calls) >= self._cap:
                self._stop.set()

    def active(self, channel):
        self._note("active", channel)
        return self._active(channel) if callable(self._active) else self._active

    def start_cycle(self, channel):
        self._note("start_cycle", channel)
        return True

    def poll_once(self, channel, **kwargs):
        self._note("poll_once", channel)
        return self._poll_pause(channel) if callable(self._poll_pause) else self._poll_pause

    def names(self, channel=None, skip=("active",)):
        return [n for n, c in self.calls if n not in skip and (channel is None or c == channel)]


def _failing_wrapper(monkeypatch, bots, is_target):
    """Обёртка над `bots.handle_update` (дополнение 1): на событии `is_target` поднимает исключение, на остальных
    зовёт настоящую функцию. Возвращает состояние: `calls` — события, дошедшие до обёртки; `on` — включён ли сбой."""
    real = bots.handle_update
    state = {"calls": [], "on": True}

    def wrapped(channel, update):
        state["calls"].append(update)
        if state["on"] and is_target(update):
            raise RuntimeError("сбой обработчика события (тест)")
        return real(channel, update)

    monkeypatch.setattr(bots, "handle_update", wrapped)
    return state


def _is_group_9999(update) -> bool:
    return update.get("message", {}).get("chat", {}).get("id") == 9999


# --- 1-2. полный путь привязки на учебной службе -----------------------------------------------------

def test_fakebots_telegram_full_bind_flow_from_start_to_confirmation(bots_on, django_capture_on_commit_callbacks):
    """FR-325: /start в личном чате → бот просит код → код из портала → привязка, код использован, бот подтверждает."""
    from apps.notify.services import binding

    user = support.make_employee()
    code = binding.new_code(user, "telegram").code
    bots_on.put_telegram(_tg_text(7001, "/start"))
    assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    assert [(str(m["chat_id"]), m["text"]) for m in bots_on.sent("telegram")] == [("7001", ASK_CODE)]
    assert model("notify.BotChat").objects.filter(channel="telegram", chat_id="7001").count() == 1
    assert _binding(user, "telegram") is None

    bots_on.put_telegram(_tg_text(7001, code))
    assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    row = _binding(user, "telegram")
    assert row is not None and row.chat_id == "7001"
    assert model("notify.BindCode").objects.get(user=user, channel="telegram").used_at is not None
    assert _texts(bots_on, "telegram") == [ASK_CODE, BOUND["telegram"]]
    assert _cursor("telegram") == "2"
    events = _audit("notify.channel_bound", object_id=str(user.pk))
    assert len(events) == 1 and events[0].actor_id == user.pk
    assert bots_on.sent("max") == []


def test_fakebots_max_full_bind_flow_from_bot_started_to_confirmation(bots_on, django_capture_on_commit_callbacks):
    """FR-325: bot_started → бот просит код → message_created с кодом → привязка, код использован, бот подтверждает."""
    from apps.notify.services import binding

    user = support.make_employee()
    code = binding.new_code(user, "max").code
    bots_on.put_max(_max_started(8101))
    assert _poll(django_capture_on_commit_callbacks, "max") == 0.0
    assert [(str(m["chat_id"]), m["text"]) for m in bots_on.sent("max")] == [("8101", ASK_CODE)]
    assert model("notify.BotChat").objects.filter(channel="max", chat_id="8101").count() == 1
    assert _binding(user, "max") is None

    marker = bots_on.put_max(_max_text(8101, code))
    assert _poll(django_capture_on_commit_callbacks, "max") == 0.0
    row = _binding(user, "max")
    assert row is not None and row.chat_id == "8101"
    assert model("notify.BindCode").objects.get(user=user, channel="max").used_at is not None
    assert _texts(bots_on, "max") == [ASK_CODE, BOUND["max"]]
    assert _cursor("max") == str(marker)
    events = _audit("notify.channel_bound", object_id=str(user.pk))
    assert len(events) == 1 and events[0].actor_id == user.pk
    assert bots_on.sent("telegram") == []


# --- 3-5. параметры запросов опроса -----------------------------------------------------------------

def test_telegram_poll_requests_use_offset_timeout_25_and_allowed_updates(bots_on, django_capture_on_commit_callbacks):
    """FR-325: getUpdates — POST с JSON: timeout=25, allowed_updates=[message, my_chat_member], offset только при курсоре."""
    client = _client("telegram")
    first = bots_on.put_telegram(_ignored("telegram"))
    with notify.bots_capture(client) as cap:
        _poll(django_capture_on_commit_callbacks, "telegram")
        second = bots_on.put_telegram(_ignored("telegram"))
        _poll(django_capture_on_commit_callbacks, "telegram")
    polls = _of(cap, "getUpdates")
    assert len(polls) == 2
    for request in polls:
        assert request.method == "POST"
        assert request.headers["content-type"].startswith("application/json")
        assert request.params["timeout"] == 25
        assert request.params["allowed_updates"] == ["message", "my_chat_member"]
    assert "offset" not in polls[0].params
    assert polls[1].params["offset"] == first[-1] + 1
    assert second == [first[-1] + 1]


def test_max_poll_requests_use_timeout_25_types_and_marker(bots_on, django_capture_on_commit_callbacks):
    """FR-325: GET /updates с параметрами timeout=25, types=bot_started,bot_stopped,message_created, marker — только при курсоре."""
    client = _client("max")
    first = bots_on.put_max(_ignored("max"))
    with notify.bots_capture(client) as cap:
        _poll(django_capture_on_commit_callbacks, "max")
        bots_on.put_max(_ignored("max"))
        _poll(django_capture_on_commit_callbacks, "max")
    polls = _of(cap, "updates")
    assert len(polls) == 2
    for request in polls:
        assert request.method == "GET"
        assert int(request.params["timeout"]) == 25
        assert set(request.params["types"].split(",")) == {"bot_started", "bot_stopped", "message_created"}
    assert "marker" not in polls[0].params
    assert int(polls[1].params["marker"]) == first
    assert "authorization" in polls[0].headers


def test_poll_socket_timeout_is_40_seconds_and_send_timeout_15(bots_on, django_capture_on_commit_callbacks):
    """FR-325: сокет опроса — 40 с, отправки и прочих методов — 15 с; ожидание на стороне службы остаётся 25 с."""
    bots = _bots()
    for channel, start, polled, sent in (("telegram", _tg_text(7001, "/start"), "getUpdates", "sendMessage"),
                                         ("max", _max_started(8101), "updates", "messages")):
        client = _client(channel)
        assert client.POLL_SOCKET_TIMEOUT == 40 and client.SEND_SOCKET_TIMEOUT == 15
        _put(bots_on, channel, start)
        with notify.bots_capture(client) as cap:
            assert bots.start_cycle(channel) is True
            _poll(django_capture_on_commit_callbacks, channel)
        assert [r.timeout for r in _of(cap, polled)] == [40]
        assert [r.timeout for r in _of(cap, sent)] == [15]
        other = "getMe" if channel == "telegram" else "me"
        assert [r.timeout for r in _of(cap, other)] == [15]
        if channel == "telegram":
            assert [r.timeout for r in _of(cap, "deleteWebhook")] == [15]


# --- 6-8. курсор ------------------------------------------------------------------------------------

def test_telegram_offset_is_last_update_id_plus_1(bots_on, django_capture_on_commit_callbacks):
    """FR-325: курсор Telegram — последний update_id пачки, в следующий запрос идёт offset = курсор + 1 (решение E6)."""
    client = _client("telegram")
    ids = bots_on.put_telegram([_tg_text(7001, "/start"), _tg_text(7002, "/start"), _tg_text(7003, "/start")])
    assert len(ids) == 3
    with notify.bots_capture(client) as cap:
        _poll(django_capture_on_commit_callbacks, "telegram")
        assert _cursor("telegram") == str(ids[-1])
        assert model("notify.BotChat").objects.filter(channel="telegram").count() == 3
        new = bots_on.put_telegram(_tg_text(7004, "/start"))
        _poll(django_capture_on_commit_callbacks, "telegram")
    polls = _of(cap, "getUpdates")
    assert len(polls) == 2
    assert polls[1].params["offset"] == ids[-1] + 1
    assert model("notify.BotChat").objects.filter(channel="telegram").count() == 4
    assert _cursor("telegram") == str(new[-1])


def test_max_marker_is_taken_from_previous_response(bots_on, django_capture_on_commit_callbacks):
    """FR-325: marker MAX — всегда из прошлого ответа (номер следующего события), курсор хранит его строкой."""
    client = _client("max")
    after_two = bots_on.put_max([_ignored("max"), _ignored("max")])
    with notify.bots_capture(client) as cap:
        _poll(django_capture_on_commit_callbacks, "max")
        assert _cursor("max") == str(after_two)
        bots_on.put_max(_max_started(8101))
        _poll(django_capture_on_commit_callbacks, "max")
    polls = _of(cap, "updates")
    assert len(polls) == 2
    assert "marker" not in polls[0].params
    assert int(polls[1].params["marker"]) == after_two
    assert model("notify.BotChat").objects.filter(channel="max", chat_id="8101").count() == 1


def test_cursor_is_saved_in_database_after_batch(bots_on, django_capture_on_commit_callbacks):
    """FR-325: после пачки курсор записан в BotState: Telegram — последний update_id, MAX — marker ответа."""
    ids = bots_on.put_telegram([_ignored("telegram"), _ignored("telegram"), _ignored("telegram")])
    assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    row = model("notify.BotState").objects.get(channel="telegram")
    assert row.cursor == str(ids[-1]) and row.last_error == ""
    assert _state("max") is None

    marker = bots_on.put_max([_ignored("max"), _ignored("max")])
    assert _poll(django_capture_on_commit_callbacks, "max") == 0.0
    assert model("notify.BotState").objects.get(channel="max").cursor == str(marker)
    assert _cursor("telegram") == str(ids[-1])


def test_each_event_is_handled_in_its_own_transaction(bots_on, monkeypatch, django_capture_on_commit_callbacks):
    """FR-325: сбой третьего события не откатывает первые два (каждое — своя транзакция); курсор не записан."""
    from apps.notify.services import binding

    bots = _bots()
    user = support.make_employee()
    code = binding.new_code(user, "telegram").code
    state = _failing_wrapper(monkeypatch, bots, _is_group_9999)
    bots_on.put_telegram([_tg_text(7001, "/start"), _tg_text(7001, code), _ignored("telegram")])
    with pytest.raises(RuntimeError):
        _poll(django_capture_on_commit_callbacks, "telegram")
    assert len(state["calls"]) == 3
    assert model("notify.BotChat").objects.filter(channel="telegram", chat_id="7001").count() == 1
    row = _binding(user, "telegram")
    assert row is not None and row.chat_id == "7001"
    assert model("notify.BindCode").objects.get(user=user, channel="telegram").used_at is not None
    assert _cursor("telegram") == ""


def test_cursor_not_saved_when_batch_fails_and_event_repeats_safely(bots_on, monkeypatch,
                                                                     django_capture_on_commit_callbacks):
    """FR-325: сбой пачки — исключение из poll_once, курсор прежний; повтор события даёт одну привязку и один ответ."""
    from apps.notify.services import binding

    bots = _bots()
    client = _client("telegram")
    user = support.make_employee()
    code = binding.new_code(user, "telegram").code
    bots_on.put_telegram(_tg_text(7001, "/start"))
    _poll(django_capture_on_commit_callbacks, "telegram")
    assert _cursor("telegram") == "1"

    state = _failing_wrapper(monkeypatch, bots, _is_group_9999)
    bots_on.put_telegram([_tg_text(7001, code), _ignored("telegram")])
    with pytest.raises(RuntimeError):
        _poll(django_capture_on_commit_callbacks, "telegram")
    assert len(state["calls"]) == 2
    assert _cursor("telegram") == "1"
    assert _binding(user, "telegram") is not None

    state["on"] = False
    with notify.bots_capture(client) as cap:
        assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    assert _of(cap, "getUpdates")[0].params["offset"] == 2
    assert _cursor("telegram") == "3"
    assert model("notify.ChatBinding").objects.filter(user=user, channel="telegram").count() == 1
    assert len(_audit("notify.channel_bound", object_id=str(user.pk))) == 1
    assert _texts(bots_on, "telegram").count(BOUND["telegram"]) == 1


# --- 11-12. начало цикла ----------------------------------------------------------------------------

def test_delete_webhook_called_on_first_start_without_dropping_pending_updates(bots_on,
                                                                               django_capture_on_commit_callbacks):
    """FR-325: start_cycle вызывает deleteWebhook с drop_pending_updates=false; ожидающие события не пропадают."""
    bots = _bots()
    client = _client("telegram")
    bots_on.put_telegram(_tg_text(7001, "/start"))
    with notify.bots_capture(client) as cap:
        assert bots.start_cycle("telegram") is True
        hooks = _of(cap, "deleteWebhook")
        assert len(hooks) == 1
        assert hooks[0].method == "POST" and hooks[0].json == {"drop_pending_updates": False}
        _poll(django_capture_on_commit_callbacks, "telegram")
    assert len(_of(cap, "deleteWebhook")) == 1  # шаги опроса deleteWebhook не зовут
    assert model("notify.BotChat").objects.filter(channel="telegram", chat_id="7001").count() == 1
    with notify.bots_capture(_client("max")) as cap_max:
        assert bots.start_cycle("max") is True
    assert _of(cap_max, "deleteWebhook") == [] and len(_of(cap_max, "me")) == 1


def test_bot_name_is_refreshed_on_each_loop_start(bots_on):
    """FR-325: имя бота (BotState.bot_username) из getMe и GET /me обновляется при каждом начале цикла."""
    bots = _bots()
    for channel in ("telegram", "max"):
        with notify.bots_capture(_client(channel)) as cap:
            for stale in ("stale", "other"):
                model("notify.BotState").objects.update_or_create(channel=channel, defaults={"bot_username": stale})
                assert bots.start_cycle(channel) is True
                assert model("notify.BotState").objects.get(channel=channel).bot_username == "stand_notify_bot"
        name = "getMe" if channel == "telegram" else "me"
        assert len(_of(cap, name)) == 2


# --- 13. простой цикла ------------------------------------------------------------------------------

def test_loop_idles_when_channel_disabled_or_token_missing(bots_on, settings, monkeypatch):
    """FR-336: канал выключен или токен пуст — poll_once и start_cycle без сети и записей; run_loop ждёт PAUSE_IDLE."""
    from apps.notify.management.commands import notify_poll

    bots = _bots()
    assert bots.PAUSE_IDLE == 60
    saved = {name: getattr(settings, f"{name.upper()}_BOT_TOKEN") for name in ("telegram", "max")}
    for channel in ("telegram", "max"):
        for case in ("disabled", "no_token"):
            _set_active(settings, channel, enabled=(case != "disabled"), has_token=(case != "no_token"))
            assert bots.active(channel) is False
            with notify.bots_capture(_client(channel)) as cap:
                assert bots.poll_once(channel, wait=1) == bots.PAUSE_IDLE
                assert bots.start_cycle(channel) is False
            assert cap.requests == []
            assert _state(channel) is None
            _set_active(settings, channel, enabled=True)
            setattr(settings, f"{channel.upper()}_BOT_TOKEN", saved[channel])
        assert bots.active(channel) is True
    assert bots_on.sent("telegram") == [] and bots_on.sent("max") == []

    stop = _Stop(limit=2)
    spy = _Spy(monkeypatch, active=False, stop=stop)
    notify_poll.run_loop("telegram", stop)
    assert spy.names() == []
    assert stop.waits == [bots.PAUSE_IDLE, bots.PAUSE_IDLE]

    stop = _Stop(limit=3)
    answers = iter([False] + [True] * 60)
    spy = _Spy(monkeypatch, active=lambda channel: next(answers), poll_pause=0.0, stop=stop)
    notify_poll.run_loop("max", stop)
    assert spy.names() == ["start_cycle", "poll_once", "poll_once"]
    assert stop.waits[0] == bots.PAUSE_IDLE


# --- 14. конфликт 409 -------------------------------------------------------------------------------

def test_telegram_409_pauses_30_seconds_and_writes_last_error(bots_on, django_capture_on_commit_callbacks):
    """FR-332: 409 на getUpdates — пауза PAUSE_CONFLICT=30, last_error="conflict", курсор и channel_status не меняются."""
    bots = _bots()
    assert bots.PAUSE_CONFLICT == 30
    bots_on.fail("telegram", 409, method="getUpdates")
    assert _poll(django_capture_on_commit_callbacks, "telegram") == bots.PAUSE_CONFLICT
    row = model("notify.BotState").objects.get(channel="telegram")
    assert row.last_error == "conflict" and row.cursor == ""
    assert model("notify.NotifySettings").objects.get(pk=1).channel_status == {}

    ids = bots_on.put_telegram(_ignored("telegram"))
    assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    row = model("notify.BotState").objects.get(channel="telegram")
    assert row.last_error == "" and row.cursor == str(ids[-1])


# --- 15-18. события отвязки -------------------------------------------------------------------------

def test_my_chat_member_kicked_in_private_chat_unbinds_and_notifies(bots_on, caplog,
                                                                     django_capture_on_commit_callbacks):
    """FR-332, FR-344: kicked в личном чате снимает привязку и создаёт уведомление «Канал отвязан» без доставок."""
    user = support.make_employee()
    other = support.make_employee()
    _bind(user, "telegram", 7001)
    _bind(other, "telegram", 7002)
    bots_on.put_telegram(_tg_kicked(7001))
    caplog.set_level(logging.ERROR, logger="apps.core.events")
    assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    assert _binding(user, "telegram") is None
    assert _binding(other, "telegram") is not None
    notes = list(model("notify.Notification").objects.filter(kind="notify.channel_unbound"))
    assert [(n.user_id, n.text, n.url) for n in notes] == [(user.pk, UNBOUND_TEXT["telegram"], "/me/notifications/")]
    assert model("notify.Delivery").objects.filter(notification=notes[0]).count() == 0
    assert bots_on.sent("telegram") == []
    assert not [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]


def test_my_chat_member_kicked_in_group_is_ignored(bots_on, django_capture_on_commit_callbacks):
    """FR-332: kicked в групповом чате игнорируется: привязка остаётся, уведомления, записи журнала и ответа нет."""
    user = support.make_employee()
    _bind(user, "telegram", -4001)
    ids = bots_on.put_telegram([_tg_kicked(-4001, "group"), _tg_kicked(-4001, "supergroup")])
    assert _poll(django_capture_on_commit_callbacks, "telegram") == 0.0
    assert _binding(user, "telegram") is not None
    assert model("notify.Notification").objects.count() == 0
    assert _audit("notify.channel_unbound") == []
    assert model("notify.BotChat").objects.count() == 0
    assert bots_on.sent("telegram") == []
    assert _cursor("telegram") == str(ids[-1])


def test_bot_stopped_unbinds_max_chat_and_notifies(bots_on, django_capture_on_commit_callbacks):
    """FR-332, FR-344: bot_stopped снимает привязку MAX и создаёт уведомление «MAX отвязан: бот недоступен»."""
    user = support.make_employee()
    other = support.make_employee()
    _bind(user, "max", 8101)
    _bind(other, "max", 8102)
    _bind(user, "telegram", 7001)
    bots_on.put_max(_max_stopped(8101))
    assert _poll(django_capture_on_commit_callbacks, "max") == 0.0
    assert _binding(user, "max") is None
    assert _binding(other, "max") is not None
    assert _binding(user, "telegram") is not None
    notes = list(model("notify.Notification").objects.filter(kind="notify.channel_unbound"))
    assert [(n.user_id, n.text, n.url) for n in notes] == [(user.pk, UNBOUND_TEXT["max"], "/me/notifications/")]
    assert model("notify.Delivery").objects.filter(notification=notes[0]).count() == 0
    assert bots_on.sent("max") == []


def test_unbind_by_event_writes_audit_by_system_without_chat_id(bots_on, django_capture_on_commit_callbacks):
    """FR-332: отвязка событием — запись журнала от системы (без автора), причина bot_unavailable, без идентификатора чата."""
    import json

    user = support.make_employee()
    chat = 774199042
    _bind(user, "telegram", chat)
    bots_on.put_telegram(_tg_kicked(chat))
    _poll(django_capture_on_commit_callbacks, "telegram")
    events = _audit("notify.channel_unbound")
    assert len(events) == 1
    event = events[0]
    assert event.actor_id is None
    assert (event.object_type, event.object_id) == ("user", str(user.pk))
    assert event.before == {"channel": "telegram", "bound": True}
    assert event.after == {"bound": False, "reason": "bot_unavailable"}
    assert str(chat) not in json.dumps([event.before, event.after, event.object_id, event.object_type])
    note = model("notify.Notification").objects.get(kind="notify.channel_unbound")
    assert str(chat) not in note.text + note.url


# --- 19. два цикла ----------------------------------------------------------------------------------

def test_loops_of_two_bots_run_independently(monkeypatch):
    """FR-325: пауза и медленный шаг цикла Telegram не задерживают цикл MAX (потоки независимы)."""
    from apps.notify.management.commands import notify_poll

    stop = threading.Event()
    seen = {"max_when_telegram_returned": None, "telegram": 0, "max": 0}

    def pause(channel):
        if channel == "telegram":
            seen["telegram"] += 1
            if seen["telegram"] == 1:
                time.sleep(0.5)  # медленный шаг: длинный запрос опроса
                seen["max_when_telegram_returned"] = seen["max"]
            return 30
        seen["max"] += 1
        return 0.01

    spy = _Spy(monkeypatch, active=True, poll_pause=pause)
    threads = [threading.Thread(target=notify_poll.run_loop, args=(channel, stop), daemon=True)
               for channel in ("telegram", "max")]
    for thread in threads:
        thread.start()
    try:
        deadline = time.monotonic() + 5
        while seen["max_when_telegram_returned"] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.3)
        telegram_polls, max_polls = seen["telegram"], seen["max"]
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
    assert not any(thread.is_alive() for thread in threads)
    assert seen["max_when_telegram_returned"] is not None and seen["max_when_telegram_returned"] >= 5
    assert telegram_polls == 1  # пауза 30 с не кончилась
    assert max_polls > seen["max_when_telegram_returned"]
    assert spy.names("telegram")[0] == "start_cycle" and spy.names("max")[0] == "start_cycle"
    assert spy.names("telegram").count("start_cycle") == 1 and spy.names("max").count("start_cycle") == 1


# --- 20. увольнение ---------------------------------------------------------------------------------

def test_dismissal_event_removes_bindings_and_codes_so_nothing_is_sent(bots_on, caplog,
                                                                        django_capture_on_commit_callbacks):
    """FR-340: увольнение снимает привязки и коды, ожидающая доставка пропускается; в боты ничего не уходит."""
    from apps.core.services import accounts
    from apps.notify.services import binding, delivery

    user = support.make_employee()
    admin = support.make_admin()
    code = binding.new_code(user, "telegram").code
    binding.new_code(user, "max")
    _bind(user, "telegram", 7001)
    _bind(user, "max", 8101)
    note = model("notify.Notification").objects.create(user=user, kind="servicedesk.assigned", text="Назначена заявка",
                                                       url="/tickets/1/", object_ref="servicedesk.ticket:1")
    from django.utils import timezone

    waiting = model("notify.Delivery").objects.create(notification=note, channel="telegram", state="waiting",
                                                      due_at=timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            delivery.enqueue([waiting.pk])
    assert len(notify.queued()) == 1

    caplog.set_level(logging.ERROR, logger="apps.core.events")
    with django_capture_on_commit_callbacks(execute=True):
        accounts.dismiss(user, actor=admin)
    assert model("notify.ChatBinding").objects.filter(user=user).count() == 0
    assert model("notify.BindCode").objects.filter(user=user).count() == 0
    waiting.refresh_from_db()
    assert (waiting.state, waiting.reason, waiting.lease_until) == ("skipped", "user_dismissed", None)
    assert not [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    notify.run_jobs()
    notify.run_tick()
    assert bots_on.sent("telegram") == [] and bots_on.sent("max") == []

    bots_on.put_telegram([_tg_text(7002, "/start"), _tg_text(7002, code)])
    _poll(django_capture_on_commit_callbacks, "telegram")
    assert model("notify.ChatBinding").objects.filter(user=user).count() == 0
    assert BOUND["telegram"] not in _texts(bots_on, "telegram")
