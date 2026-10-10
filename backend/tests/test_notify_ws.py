"""T-4122: соединение `/ws/notify/` — проверки при подключении, проверка раз в 25 с, кадры сервера, присутствие
(FR-318, FR-320, FR-331, NFR-301). Сценарии 10-11 спеки среза 004.

Соединение ведут только помощники CONTRACT-004 § 11.4: весь сценарий — одна асинхронная функция в `ws_run`
(решение C9), действия с базой и заданиями — `hub.do(...)`; вход — Django `Client` (строка `UserSession` создана
средствами тестов). Проверка раз в 25 с ускорена подменой `apps.notify.consumers.CHECK_INTERVAL` до подключения.
Время кадров с системным уведомлением ставит фикстура `clock` (рабочее время — среда 14.10.2026 12:00 по Москве,
тихие часы — тот же день 22:00); остальные тесты идут по настоящему времени (Valkey и присутствие живут по нему).
Имена кода среза 004 — внутри тестов или через `support.model`.
"""
import asyncio
import datetime
import logging
import time
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from tests import factories, support
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
WORK = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=MSK)      # среда, рабочее время
QUIET = datetime.datetime(2026, 10, 14, 22, 0, tzinfo=MSK)     # среда, после конца рабочего дня

KIND = "test.thing"
CHANGE = "/me/security/password/"


# --- помощники только этого файла --------------------------------------------------------------------------

@pytest.fixture
def env(clock):
    """Каталог видов пуст, часы стоят в рабочем времени; тестовый вид — `_register`."""
    from apps.core import extensions

    with extensions.empty():
        clock.set(WORK)
        yield clock


def _register(*, code=KIND, channels=("portal", "push"), mandatory=False):
    """Тестовый вид без событий: уведомления создаёт `dispatch.create` напрямую."""
    from apps.core.extensions import NotificationKind

    kind = NotificationKind(code=code, title="Тестовый вид", module="test", external_text="Есть новое",
                            default_channels=tuple(channels), mandatory=mandatory)
    notify.register_kind(kind)
    return kind


def _sid(client) -> str:
    """Ключ сессии Django клиента (значение куки)."""
    return client.cookies[django_settings.SESSION_COOKIE_NAME].value


def _note(user, text="Уведомление", kind="test.thing", read=False):
    return model("notify.Notification").objects.create(
        user=user, kind=kind, text=text, url="/test/", object_ref="",
        read_at=timezone.now() if read else None)


def _count(frame) -> tuple[str, str]:
    """`data-count` и текст фрагмента числа в кадре."""
    fragment = notify.ws_fragments(frame)["notify-count"]
    return fragment.attrs["data-count"], fragment.text.strip()


def _scores(user) -> list[float]:
    """Оценки элементов присутствия сотрудника (`notify:online:<id>`, CONTRACT-004 § 7.4)."""
    conn = support.valkey()
    try:
        return [score for _, score in conn.zrange(f"notify:online:{user.pk}", 0, -1, withscores=True)]
    finally:
        conn.close()


def _set_presence(user, name: str, age_seconds: float) -> None:
    conn = support.valkey()
    try:
        conn.zadd(f"notify:online:{user.pk}", {name: time.time() - age_seconds})
    finally:
        conn.close()


def _activity(sid: str):
    return model("core.UserSession").objects.get(session_key=sid).last_activity


def _create(capture, user, kind_code: str, text: str):
    """`dispatch.create` одного уведомления внутри `atomic()` и `capture(execute=True)`: рассылка в группу идёт
    после фиксации. Возвращает номер записи."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch

    with capture(execute=True):
        with transaction.atomic():
            ids = dispatch.create(kind_code, [Draft(user_id=user.pk, text=text, url="/test/",
                                                    object_ref=f"test:{user.pk}")])
    return ids[0]


async def _created_frame(hub, conn, capture, user, kind_code=KIND, text="Новое событие"):
    """Создаёт уведомление и возвращает `(номер, кадр)` — кадр, пришедший в соединение."""
    note_id = await hub.do(_create, capture, user, kind_code, text)
    frame = await conn.receive()
    assert frame is not None, "кадра после создания уведомления нет"
    return note_id, frame


# --- подключение: сессия и Origin ----------------------------------------------------------------------------

def test_connect_without_session_accepts_then_closes_with_4401():
    """FR-318: без сессии (куки нет) соединение сначала принимается, затем закрывается кодом 4401; кадра с числом нет."""
    async def scenario(hub):
        conn = await hub.connect()
        assert conn.accepted, "после проверки сессии обработчик сначала принимает соединение (решения 22 и 35)"
        assert await conn.receive() is None, "кадра с числом у чужого соединения быть не должно"
        assert conn.close_code == 4401

    notify.ws_run(scenario)


def test_connect_with_foreign_session_closes_with_4401():
    """FR-318: строка `UserSession` с этим ключом принадлежит другому сотруднику — `session_missing`: приём и закрытие 4401."""
    user, other = support.make_employee(), support.make_employee()
    client = support.logged_in(user)
    model("core.UserSession").objects.filter(session_key=_sid(client)).update(user=other)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is None
        assert conn.close_code == 4401
        assert await hub.do(_is_online, user.pk) is False and await hub.do(_is_online, other.pk) is False

    notify.ws_run(scenario)


def _is_online(user_id: int) -> bool:
    from apps.notify.services import live

    return live.is_online(user_id)


def test_connect_with_idle_expired_session_closes_with_4401():
    """FR-318: бездействие сессии истекло (порог — из сессии) — `idle_expired`: приём и закрытие 4401."""
    user = support.make_employee()
    client = support.logged_in(user)
    idle = model("core.SecuritySettings").objects.get().idle_timeout_minutes
    model("core.UserSession").objects.filter(session_key=_sid(client)).update(
        last_activity=timezone.now() - datetime.timedelta(minutes=idle + 5))

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is None
        assert conn.close_code == 4401
        assert await hub.do(_is_online, user.pk) is False

    notify.ws_run(scenario)


def test_connect_without_second_factor_closes_with_4401():
    """FR-318: вход без второго фактора не закончен (ограниченная сессия) — `limited`: приём и закрытие 4401."""
    from apps.core.services import sessions

    user = support.make_employee()
    client = support.logged_in(user)
    session = client.session
    session[sessions.LIMITED_KEY] = True
    session.save()

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is None
        assert conn.close_code == 4401
        assert await hub.do(_is_online, user.pk) is False

    notify.ws_run(scenario)


def test_connect_with_expired_password_closes_with_4401():
    """FR-318: срок действия пароля истёк (политика с лимитом, пароль старше) — `password_expired`: приём и закрытие 4401."""
    user = support.make_employee()
    client = support.logged_in(user)
    support.set_security(password_max_age_days=30)
    model("core.PasswordHistory").objects.filter(user=user).delete()
    type(user).objects.filter(pk=user.pk).update(activated_at=timezone.now() - datetime.timedelta(days=90))

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is None
        assert conn.close_code == 4401
        assert await hub.do(_is_online, user.pk) is False

    notify.ws_run(scenario)


def test_connect_without_origin_is_refused():
    """FR-318: нет заголовка `Origin` — соединение закрыто до `accept` (раздел 11.1); с верным Origin тот же клиент принят."""
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        refused = await hub.connect(client, origin=None)
        assert refused.accepted is False
        assert await hub.do(_is_online, user.pk) is False, "отказ до обработчика: присутствия нет"
        accepted = await hub.connect(client)
        assert accepted.accepted, "тот же клиент с верным Origin принят"
        assert await accepted.receive() is not None

    notify.ws_run(scenario)


def test_connect_with_foreign_origin_is_refused():
    """FR-318: Origin чужого хоста — закрыто до `accept`; с Origin портала тот же клиент принят."""
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        refused = await hub.connect(client, origin="http://evil.example")
        assert refused.accepted is False
        assert await hub.do(_is_online, user.pk) is False
        accepted = await hub.connect(client, origin="http://testserver")
        assert accepted.accepted
        assert await accepted.receive() is not None

    notify.ws_run(scenario)


# --- число при подключении и сообщения клиента ---------------------------------------------------------------

def test_connect_sends_current_unread_count_and_resends_after_reconnect():
    """FR-318: при подключении приходит один кадр с точным числом непрочитанных (`#notify-count[data-count]`);
    после прочтения и переподключения — кадр с новым числом."""
    user = support.make_employee()
    client = support.logged_in(user)
    notes = [_note(user, f"Уведомление {i}") for i in range(3)]
    _note(user, "Прочитанное", read=True)

    def read_one():
        model("notify.Notification").objects.filter(pk=notes[0].pk).update(read_at=timezone.now())

    async def scenario(hub):
        first = await hub.connect(client)
        assert first.accepted
        frame = await first.receive()
        assert frame is not None, "кадра с числом при подключении нет"
        assert _count(frame) == ("3", "3")
        assert await first.receive(0.3) is None, "при подключении приходит один кадр"
        await first.disconnect()
        await hub.do(read_one)
        second = await hub.connect(client)
        assert second.accepted
        again = await second.receive()
        assert again is not None, "после переподключения число не прислано"
        assert _count(again) == ("2", "2")

    notify.ws_run(scenario)


def test_message_over_socket_does_not_extend_session_idle_time():
    """FR-318: сообщения клиента по соединению игнорируются и не продлевают сессию (`last_activity` не меняется)."""
    user = support.make_employee()
    client = support.logged_in(user)
    sid = _sid(client)
    before = timezone.now() - datetime.timedelta(minutes=10)
    model("core.UserSession").objects.filter(session_key=sid).update(last_activity=before)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        await conn.send("ping")
        await conn.send('{"type": "anything"}')
        assert await conn.receive(0.4) is None, "на сообщения клиента ответа нет"
        assert conn.close_code is None, "соединение осталось открытым"
        assert await hub.do(_activity, sid) == before

    notify.ws_run(scenario)


# --- проверка раз в CHECK_INTERVAL секунд ---------------------------------------------------------------------

def test_check_every_25_seconds_closes_socket_after_logout(monkeypatch):
    """FR-318: на ближайшей проверке после выхода из портала соединение закрывается кодом 4401; пока сессия
    цела, проверка соединение не трогает и обновляет присутствие."""
    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        first = await hub.do(_scores, user)
        assert len(first) == 1
        assert await conn.wait_close(timeout=0.7) is None, "здоровое соединение проверка не закрывает"
        later = await hub.do(_scores, user)
        assert len(later) == 1 and later[0] > first[0], "проверка обновляет отметку присутствия"
        assert (await hub.do(client.post, "/logout/")).status_code == 302
        assert await conn.wait_close(timeout=2.0) == 4401

    notify.ws_run(scenario)


def test_check_closes_socket_after_logout_from_all_devices(monkeypatch):
    """FR-318: «Выйти со всех устройств» с другой сессии закрывает соединение закрытой сессии кодом 4401; соединение
    другого сотрудника остаётся."""
    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)
    user, other = support.make_employee(), support.make_employee()
    here = support.logged_in(user, ip="198.51.100.211", ua=support.FIREFOX_UA)
    there = support.logged_in(user, ip="198.51.100.212", ua=support.CHROME_UA)
    bystander = support.logged_in(other, ip="198.51.100.213")

    async def scenario(hub):
        closed = await hub.connect(here)
        kept = await hub.connect(bystander)
        assert closed.accepted and kept.accepted
        assert await closed.receive() is not None and await kept.receive() is not None
        done = await hub.do(there.post, "/me/security/logout-everywhere/")
        assert done.status_code == 302
        assert await closed.wait_close(timeout=2.0) == 4401
        assert await kept.wait_close(timeout=0.6) is None, "соединение другого сотрудника не закрыто"

    notify.ws_run(scenario)


def test_check_closes_socket_after_idle_expiry(monkeypatch):
    """FR-318: бездействие сессии истекло уже после подключения — ближайшая проверка закрывает соединение кодом 4401."""
    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)
    user = support.make_employee()
    client = support.logged_in(user)
    sid = _sid(client)
    idle = model("core.SecuritySettings").objects.get().idle_timeout_minutes

    def expire():
        model("core.UserSession").objects.filter(session_key=sid).update(
            last_activity=timezone.now() - datetime.timedelta(minutes=idle + 5))

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        assert await conn.wait_close(timeout=0.5) is None
        await hub.do(expire)
        assert await conn.wait_close(timeout=2.0) == 4401

    notify.ws_run(scenario)


def test_check_closes_socket_on_next_tick_after_password_change(monkeypatch):
    """FR-318: смена пароля меняет ключ сессии — у прежней сессии нет строки `UserSession`, и ближайшая проверка
    закрывает соединение этой вкладки кодом 4401."""
    monkeypatch.setattr("apps.notify.consumers.CHECK_INTERVAL", 0.2)
    user = support.make_employee()
    client = support.logged_in(user)
    old_sid = _sid(client)
    new_pw = factories.new_password()

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        assert await conn.wait_close(timeout=0.5) is None
        done = await hub.do(client.post, CHANGE, {"current_password": user.test_password,
                                                  "password1": new_pw, "password2": new_pw})
        assert done.status_code == 302
        assert _sid(client) != old_sid, "смена пароля меняет ключ сессии"
        assert await conn.wait_close(timeout=2.0) == 4401

    notify.ws_run(scenario)


# --- рассылка в группу: скорость, системное уведомление ------------------------------------------------------

def test_push_from_rq_worker_reaches_open_socket_within_2_seconds(bots_on, django_capture_on_commit_callbacks):
    """FR-318, NFR-301: задание очереди, в котором `send_delivery` получает `ChannelGone`, снимает привязку и
    создаёт уведомление «Канал отвязан»; кадр с новым числом приходит в открытое соединение не позже 2 с."""
    from apps.integrations.telegram.client import ChannelGone
    from apps.notify.services import delivery

    user = support.make_employee()
    client = support.logged_in(user)
    note = _note(user, "Заявка назначена", kind="servicedesk.assigned")
    model("notify.ChatBinding").objects.create(user=user, channel="telegram", chat_id=f"c-{uuid.uuid4().hex[:8]}")
    row = model("notify.Delivery").objects.create(notification=note, channel="telegram", state="waiting",
                                                  due_at=timezone.now())

    def run_worker():
        with notify.fake_bot_send("telegram", raises=ChannelGone) as sent:
            with django_capture_on_commit_callbacks(execute=True):
                with transaction.atomic():
                    delivery.enqueue([row.pk])
            with django_capture_on_commit_callbacks(execute=True):
                executed = notify.run_jobs()
        return sent.calls, executed

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        first = await conn.receive()
        assert first is not None and _count(first) == ("1", "1")
        calls, executed = await hub.do(run_worker)
        assert executed == 1 and len(calls) == 1
        frame = await conn.receive(timeout=2.0)
        assert frame is not None, "кадр из задания рабочего процесса не пришёл за 2 с"
        fragments = notify.ws_fragments(frame)
        assert fragments["notify-count"].attrs["data-count"] == "2"
        assert fragments["notify-toast"].attrs["data-text"] == "Telegram отвязан: бот недоступен"
        assert fragments["notify-toast"].attrs["data-show"] == "0", "у вида «Канал отвязан» (mandatory) показа нет"

    notify.ws_run(scenario)
    row.refresh_from_db()
    assert (row.state, row.reason) == ("failed", "channel_unbound")
    assert not model("notify.ChatBinding").objects.filter(user=user, channel="telegram").exists()
    assert model("notify.Notification").objects.filter(user=user, kind="notify.channel_unbound").count() == 1


def test_push_sends_toast_fragment_with_text_url_and_tag(env, django_capture_on_commit_callbacks):
    """FR-320: новое уведомление приходит одним кадром: число, затем `#notify-toast` с `data-text` (текст записи),
    `data-url` (`/notifications/<id>/open/`), `data-tag` (`n-<id>`), `data-show="1"`; элементы пустые, без ролей."""
    _register()
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        note_id, frame = await _created_frame(hub, conn, django_capture_on_commit_callbacks, user,
                                              text="Вам назначена заявка")
        assert await conn.receive(0.3) is None, "на одно уведомление приходит один кадр"
        fragments = notify.ws_fragments(frame)
        assert list(fragments) == ["notify-count", "notify-toast"], "порядок: число, затем системное уведомление"
        assert fragments["notify-count"].attrs["hx-swap-oob"] == "true"
        assert fragments["notify-count"].attrs["data-count"] == "1"
        toast = fragments["notify-toast"]
        assert toast.attrs["hx-swap-oob"] == "true"
        assert toast.attrs["data-text"] == "Вам назначена заявка"
        assert toast.attrs["data-url"] == f"/notifications/{note_id}/open/"
        assert toast.attrs["data-tag"] == f"n-{note_id}"
        assert toast.attrs["data-show"] == "1"
        assert toast.text.strip() == "", "элемент системного уведомления пустой"
        for forbidden in ('role="status"', 'role="alert"', "data-error", "data-warning"):
            assert forbidden not in frame, f"решение 22 задач: в кадре нет {forbidden}"

    notify.ws_run(scenario)


def test_toast_shown_flag_on_when_browser_push_kind_enabled_and_not_quiet(env, django_capture_on_commit_callbacks):
    """FR-320, FR-331: у вида включена ячейка `push`, рабочее время получателя — `data-show="1"`; наличие подписки
    Web Push на признак не влияет."""
    _register(channels=("portal", "push"))
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        _, frame = await _created_frame(hub, conn, django_capture_on_commit_callbacks, user)
        assert notify.ws_fragments(frame)["notify-toast"].attrs["data-show"] == "1"

    notify.ws_run(scenario)


def test_toast_shown_flag_off_when_browser_push_disabled_or_quiet_hours(env, django_capture_on_commit_callbacks):
    """FR-320, FR-329, FR-331: ячейка `push` у вида выключена (по умолчанию вида, по таблице сотрудника, вид
    `mandatory`) либо сейчас тихие часы — `data-show="0"`; фрагмент и число приходят."""
    _register(channels=("portal", "email"))
    _register(code="test.with_push", channels=("portal", "push"))
    _register(code="test.fixed", channels=("portal", "push"), mandatory=True)
    user = support.make_employee()
    client = support.logged_in(user)
    model("notify.UserNotifySettings").objects.create(user=user, matrix={"test.with_push": ["email"]})

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        for code in (KIND, "test.with_push", "test.fixed"):
            note_id, frame = await _created_frame(hub, conn, django_capture_on_commit_callbacks, user, kind_code=code)
            fragments = notify.ws_fragments(frame)
            assert fragments["notify-toast"].attrs["data-show"] == "0", f"вид {code}: показа во вкладке быть не должно"
            assert fragments["notify-toast"].attrs["data-tag"] == f"n-{note_id}"
        assert _count(frame)[0] == "3"

    notify.ws_run(scenario)

    env.set(QUIET)
    quiet_user = support.make_employee()
    quiet_client = support.logged_in(quiet_user)

    async def quiet_scenario(hub):
        conn = await hub.connect(quiet_client)
        assert conn.accepted
        assert await conn.receive() is not None
        note_id, frame = await _created_frame(hub, conn, django_capture_on_commit_callbacks, quiet_user,
                                              kind_code="test.with_push")
        fragments = notify.ws_fragments(frame)
        assert fragments["notify-toast"].attrs["data-show"] == "0", "тихие часы: системного уведомления нет"
        assert fragments["notify-count"].attrs["data-count"] == "1", "число на колокольчике обновляется"

    notify.ws_run(quiet_scenario)


def test_toast_values_are_html_escaped(env, django_capture_on_commit_callbacks):
    """FR-320: разметка и кавычки в тексте уведомления экранируются шаблоном: в сыром кадре нет чужих тегов, а
    разобранное значение `data-text` равно исходному тексту."""
    _register()
    user = support.make_employee()
    client = support.logged_in(user)
    text = "<img src=x onerror=alert(1)> \"кавычка\" & 'апостроф' <b>жирный</b>"

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        _, frame = await _created_frame(hub, conn, django_capture_on_commit_callbacks, user, text=text)
        assert "<img" not in frame and "<b>" not in frame and "</b>" not in frame
        assert "onerror=alert(1)>" not in frame
        fragments = notify.ws_fragments(frame)
        assert list(fragments) == ["notify-count", "notify-toast"], "чужих корневых элементов в кадре нет"
        assert fragments["notify-toast"].attrs["data-text"] == text

    notify.ws_run(scenario)


def test_push_reaches_only_sockets_of_target_user():
    """FR-318: `live.push` отправляет кадр только в группу сотрудника: обе его вкладки получают число, чужое
    соединение — ничего."""
    from apps.notify.services import live

    target, other = support.make_employee(), support.make_employee()
    target_client = support.logged_in(target, ip="198.51.100.221")
    other_client = support.logged_in(other, ip="198.51.100.222")
    _note(target, "Для первого")

    async def scenario(hub):
        tab_one = await hub.connect(target_client)
        tab_two = await hub.connect(target_client)
        stranger = await hub.connect(other_client)
        for conn in (tab_one, tab_two, stranger):
            assert conn.accepted
            assert await conn.receive() is not None
        await hub.do(live.push, [target.pk])
        for conn in (tab_one, tab_two):
            frame = await conn.receive()
            assert frame is not None, "вкладка получателя кадра не получила"
            assert _count(frame) == ("1", "1")
        assert await stranger.receive(0.5) is None, "чужое соединение кадра получить не должно"

    notify.ws_run(scenario)


# --- присутствие (FR-331) ------------------------------------------------------------------------------------

def test_presence_is_online_when_entry_younger_than_60_seconds():
    """FR-331: сотрудник онлайн, если в `notify:online:<id>` есть элемент моложе 60 с: запись, сделанная тестом
    (45 с), и отметка живого соединения (оценка — настоящее время)."""
    from apps.notify.services import live

    user, nobody = support.make_employee(), support.make_employee()
    client = support.logged_in(user)
    assert live.ONLINE_WINDOW == 60
    assert live.is_online(nobody.pk) is False
    _set_presence(nobody, "c1", 45)
    assert live.is_online(nobody.pk) is True

    async def scenario(hub):
        assert await hub.do(live.is_online, user.pk) is False
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        assert await hub.do(live.is_online, user.pk) is True
        scores = await hub.do(_scores, user)
        assert len(scores) == 1 and abs(scores[0] - time.time()) < 10

    notify.ws_run(scenario)


def test_presence_is_offline_when_entry_older_than_60_seconds():
    """FR-331: единственный элемент старше 60 с (90 с) — не онлайн; свежий элемент рядом со старым — онлайн;
    ключа нет — не онлайн."""
    from apps.notify.services import live

    user = support.make_employee()
    assert live.is_online(user.pk) is False
    _set_presence(user, "c1", 90)
    assert live.is_online(user.pk) is False
    _set_presence(user, "c2", 5)
    assert live.is_online(user.pk) is True


def test_presence_removed_after_disconnect_and_stays_with_other_tab():
    """FR-331: отключение убирает элемент только этого соединения; пока открыта вторая вкладка, сотрудник онлайн;
    после отключения второй — нет."""
    user = support.make_employee()
    client = support.logged_in(user)

    async def scenario(hub):
        first = await hub.connect(client)
        second = await hub.connect(client)
        assert first.accepted and second.accepted
        assert await first.receive() is not None and await second.receive() is not None
        assert len(await hub.do(_scores, user)) == 2, "по элементу на соединение"
        await first.disconnect()
        assert len(await hub.do(_scores, user)) == 1
        assert await hub.do(_is_online, user.pk) is True, "вторая вкладка держит присутствие"
        await second.disconnect()
        assert await hub.do(_scores, user) == []
        assert await hub.do(_is_online, user.pk) is False

    notify.ws_run(scenario)


# --- сбой слоя каналов, долгое ожидание, нагрузка ------------------------------------------------------------

def test_live_push_survives_channel_layer_failure_without_raising(monkeypatch, caplog):
    """FR-318: сбой слоя каналов (нет слоя, сбой отправки в группу) `live.push` перехватывает: исключения нет,
    в логгер `apps.notify.services.live` пишется предупреждение, запись уведомления остаётся."""
    from apps.notify.services import live

    user = support.make_employee()
    note = _note(user)

    def broken_layer():
        raise ConnectionError("слой каналов недоступен")

    class BrokenLayer:
        async def group_send(self, group, message):
            raise OSError("отправка в группу не удалась")

    for factory in (broken_layer, BrokenLayer):
        caplog.clear()
        monkeypatch.setattr("apps.notify.services.live.get_channel_layer", factory)
        with caplog.at_level(logging.WARNING, logger="apps.notify.services.live"):
            assert live.push([user.pk]) is None
        warnings = [r for r in caplog.records if r.name == "apps.notify.services.live" and r.levelno == logging.WARNING]
        assert warnings, "сбой слоя должен попасть в журнал приложения предупреждением"
    assert model("notify.Notification").objects.filter(pk=note.pk).exists()


def test_idle_connection_without_messages_stays_open_longer_than_10_seconds():
    """FR-318, NFR-301: соединение без сообщений остаётся открытым дольше 10 с (проверка раз в 25 с здоровое
    соединение не закрывает), присутствие на месте, а кадр рассылки после простоя доходит."""
    from apps.notify.services import live

    user = support.make_employee()
    client = support.logged_in(user)
    _note(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        assert await conn.receive() is not None
        await hub.sleep(11)
        assert conn.close_code is None
        assert await conn.receive(0.2) is None and conn.close_code is None, "за 11 с простоя соединение не закрыто"
        assert await hub.do(_is_online, user.pk) is True
        await hub.do(live.push, [user.pk])
        frame = await conn.receive(timeout=2.0)
        assert frame is not None and _count(frame) == ("1", "1"), "после простоя кадр доходит"

    notify.ws_run(scenario, timeout=60)


def test_100_concurrent_connections_in_one_process_get_count():
    """FR-318, NFR-301: сто одновременных соединений одного процесса (пять сотрудников по двадцать вкладок) каждое
    получает кадр с точным числом своего сотрудника (`99+` при числе больше 99); присутствие — по элементу на вкладку."""
    counts = [0, 1, 7, 100, 3]
    people = []
    for i, amount in enumerate(counts):
        user = support.make_employee()
        people.append((user, support.logged_in(user, ip=f"198.51.100.{140 + i}"), amount))
        model("notify.Notification").objects.bulk_create(
            [model("notify.Notification")(user=user, kind=KIND, text=f"n{n}", url="/test/") for n in range(amount)])
    plan = [(user, client, amount) for user, client, amount in people for _ in range(20)]

    async def scenario(hub):
        opened = []
        for start in range(0, len(plan), 10):
            batch = await asyncio.gather(*(hub.connect(client) for _, client, _ in plan[start:start + 10]))
            opened.extend(batch)
        assert len(opened) == 100 and all(conn.accepted for conn in opened)
        for conn, (_, _, amount) in zip(opened, plan):
            frame = await conn.receive(timeout=5.0)
            assert frame is not None, "кадр с числом при подключении не пришёл"
            expected_text = "99+" if amount > 99 else str(amount)
            assert _count(frame) == (str(amount), expected_text)
        for user, _, _ in people:
            assert len(await hub.do(_scores, user)) == 20
            assert await hub.do(_is_online, user.pk) is True

    notify.ws_run(scenario, timeout=120)
