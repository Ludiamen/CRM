"""T-7124: `FeedConsumer` — подключение и проверка сессии (FR-627). Сценарий 8 п. 8 спеки среза 007.

План: «Живые обновления» (проверка сессии, `FeedConsumer`), «Контракты» (`/ws/feed/`); CONTRACT-007: 3.2 (примесь
`SessionGuardMixin`), 5.6, 5.8 (подмены `ws_state` и слоя), 11.1, 11.4, решения 7 и 49 задач. Соединение ведёт
`support_feed.ws_client` внутри `support_notify.ws_run`; весь сценарий — одна асинхронная функция, действия с базой —
`hub.do(...)`. Проверка сессии ускорена подменой `apps.feed.consumers.CHECK_INTERVAL` (0,2 с) до подключения. Код среза на
уровне модуля не импортируется.
"""
import json
from datetime import timedelta

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from tests import support
from tests import support_feed as ff
from tests.support import HX
from tests.support_notify import ws_fragments, ws_run

pytestmark = pytest.mark.django_db


# --- помощники только этого файла -----------------------------------------------------------------------------------

def _employee(name: str = "Читатель Читателев") -> ff.Session:
    return ff.as_plain(full_name=name)


def _sid(session) -> str:
    return session.client.cookies[django_settings.SESSION_COOKIE_NAME].value


def _fast(monkeypatch, interval: float = 0.2) -> None:
    monkeypatch.setattr("apps.feed.consumers.CHECK_INTERVAL", interval)


def _publish(session, *recipients, text: str = "Запись для проверки"):
    data = {"kind": "post", "text": text, "to": [f"p{person.pk}" for person in recipients]}
    return session.client.post("/feed/posts/", data, **HX)


def _publish_after_commit(capture, session, *recipients):
    with capture(execute=True):
        return _publish(session, *recipients)


async def _settle(conn, timeout: float = 0.5):
    """Соединение принято и осталось открытым."""
    assert conn.accepted
    assert await conn.wait_close(timeout) is None, f"соединение закрыто кодом {conn.close_code}"


# --- подключение ------------------------------------------------------------------------------------------------------

def test_connect_after_login_and_second_factor_is_accepted():
    """FR-627: вошедший с вторым фактором подключается: соединение принято и открыто."""
    user = _employee()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn)

    ws_run(scenario)


def test_connect_without_login_accepts_then_closes_with_4401():
    """FR-627: без входа соединение принимается и закрывается кодом 4401 (расширение после него не переподключается)."""
    async def scenario(hub):
        conn = await ff.ws_client(None, hub=hub)
        assert conn.accepted, "сначала `accept`, затем закрытие"
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_connect_without_second_factor_closes_with_4401():
    """FR-627: вход без второго фактора не закончен (ограниченная сессия) — приём и закрытие 4401."""
    from apps.core.services import sessions

    user = _employee()
    session = user.client.session
    session[sessions.LIMITED_KEY] = True
    session.save()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        assert conn.accepted
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_connect_with_expired_session_closes_with_4401():
    """FR-627: бездействие сессии истекло до подключения — приём и закрытие 4401."""
    user = _employee()
    idle = support.model("core.SecuritySettings").objects.get().idle_timeout_minutes
    support.model("core.UserSession").objects.filter(session_key=_sid(user)).update(
        last_activity=timezone.now() - timedelta(minutes=idle + 5))

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        assert conn.accepted
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_connect_with_foreign_origin_is_refused_before_accept():
    """FR-627: чужой `Origin` — закрытие до `accept`; с `Origin` портала тот же сотрудник принят."""
    user = _employee()

    async def scenario(hub):
        refused = await ff.ws_client(user, hub=hub, origin="http://evil.example")
        assert refused.accepted is False, "соединение с чужим Origin принято"
        accepted = await ff.ws_client(user, hub=hub, origin="http://testserver")
        await _settle(accepted)

    ws_run(scenario)


# --- закрытие по проверке сессии --------------------------------------------------------------------------------------

def test_logout_closes_socket_with_4401_within_check_interval(monkeypatch):
    """FR-627: выход из портала закрывает соединение кодом 4401 на ближайшей проверке; пока сессия цела, проверка
    соединение не трогает."""
    _fast(monkeypatch)
    user = _employee()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn, 0.7)
        assert (await hub.do(user.client.post, "/logout/")).status_code == 302
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_logout_from_all_devices_closes_socket_with_4401_within_check_interval(monkeypatch):
    """FR-627: «Выйти со всех устройств» с другой сессии закрывает соединение закрытой сессии кодом 4401;
    соединение другого сотрудника остаётся."""
    _fast(monkeypatch)
    user, bystander_user = support.make_employee(), support.make_employee()
    here = ff.Session(user, support.logged_in(user, ip="198.51.100.221", ua=support.FIREFOX_UA))
    there = support.logged_in(user, ip="198.51.100.222", ua=support.CHROME_UA)
    bystander = ff.Session(bystander_user, support.logged_in(bystander_user, ip="198.51.100.223"))

    async def scenario(hub):
        closed, kept = await ff.ws_client(here, hub=hub), await ff.ws_client(bystander, hub=hub)
        assert closed.accepted and kept.accepted
        assert (await hub.do(there.post, "/me/security/logout-everywhere/")).status_code == 302
        assert await closed.wait_close(2.0) == 4401
        assert await kept.wait_close(0.6) is None, "соединение другого сотрудника закрыто"

    ws_run(scenario)


def test_blocking_employee_closes_socket_with_4401_within_check_interval(monkeypatch):
    """FR-627: блокировка сотрудника закрывает его соединение кодом 4401 на ближайшей проверке."""
    from apps.core.services import accounts

    _fast(monkeypatch)
    user, admin = _employee(), support.make_admin()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn, 0.5)
        await hub.do(accounts.block, user.user, "Проверка соединения", actor=admin)
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_dismissing_employee_closes_socket_with_4401_within_check_interval(monkeypatch):
    """FR-627: увольнение сотрудника закрывает его соединение кодом 4401 на ближайшей проверке."""
    from apps.core.services import accounts

    _fast(monkeypatch)
    user, admin = _employee(), support.make_admin()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn, 0.5)
        await hub.do(accounts.dismiss, user.user, actor=admin)
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_idle_expiry_closes_socket_with_4401_within_check_interval(monkeypatch):
    """FR-627: бездействие сессии истекло уже после подключения — ближайшая проверка закрывает соединение кодом 4401."""
    _fast(monkeypatch)
    user = _employee()
    idle = support.model("core.SecuritySettings").objects.get().idle_timeout_minutes

    def expire():
        support.model("core.UserSession").objects.filter(session_key=_sid(user)).update(
            last_activity=timezone.now() - timedelta(minutes=idle + 5))

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn, 0.5)
        await hub.do(expire)
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_password_expiry_closes_socket_with_4401_within_check_interval(monkeypatch):
    """FR-627: срок действия пароля истёк уже после подключения — ближайшая проверка закрывает соединение кодом 4401."""
    _fast(monkeypatch)
    user = _employee()

    def expire_by_age():
        support.set_security(password_max_age_days=30)
        support.model("core.PasswordHistory").objects.filter(user=user.user).delete()
        type(user.user).objects.filter(pk=user.user.pk).update(activated_at=timezone.now() - timedelta(days=90))

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn, 0.5)
        await hub.do(expire_by_age)
        assert await conn.wait_close(2.0) == 4401

    ws_run(scenario)


def test_closed_socket_gets_no_frames_about_post_published_afterwards(monkeypatch, django_capture_on_commit_callbacks):
    """FR-627: после закрытия соединения (выход) запись, опубликованная позже, фрагментов в него не даёт; соединение
    другого адресата (контроль) плашку получает."""
    _fast(monkeypatch)
    author, leaver, stayer = ff.as_writer(full_name="Автор Авторов"), _employee("Вышедший Узлов"), \
        _employee("Оставшийся Узлов")

    async def scenario(hub):
        closed, open_conn = await ff.ws_client(leaver, hub=hub), await ff.ws_client(stayer, hub=hub)
        await ff.send_sync(open_conn, [], timezone.now())
        assert await open_conn.receive(2.0) is not None, "ответ на `sync` у контрольного соединения"
        assert (await hub.do(leaver.client.post, "/logout/")).status_code == 302
        assert await closed.wait_close(2.0) == 4401
        response = await hub.do(_publish_after_commit, django_capture_on_commit_callbacks, author,
                                leaver.user, stayer.user)
        assert response.status_code == 200
        assert await closed.receive(0.8) is None, "закрытое соединение получило кадр"
        frame = await open_conn.receive(2.0)
        assert frame is not None and ws_fragments(frame).get("feed-new") is not None, "контроль: плашки нет"

    ws_run(scenario)


def test_check_interval_change_applies_on_next_wait(monkeypatch):
    """FR-627: интервал проверки читается при каждом ожидании: после смены значения следующее ожидание уже новое
    (закрытие не наступает за прежние 0,2 с, но наступает после нового интервала)."""
    _fast(monkeypatch, 0.2)
    user = _employee()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        await _settle(conn, 0.5)
        monkeypatch.setattr("apps.feed.consumers.CHECK_INTERVAL", 1.5)
        await hub.sleep(0.4)       # текущее ожидание (до 0,2 с) закончилось, началось ожидание в 1,5 с
        await hub.do(user.client.post, "/logout/")
        assert await conn.wait_close(0.8) is None, "новый интервал не применён: закрытие за прежние 0,2 с"
        assert await conn.wait_close(3.0) == 4401, "после нового интервала соединение не закрыто"

    ws_run(scenario)


def test_feed_check_interval_default_is_25_seconds_not_over_30():
    """FR-627: интервал проверки по умолчанию — 25 с и не больше 30 (закрыть не позже чем через 30 с); у потребителя
    `check_interval()` отдаёт то же значение."""
    from apps.feed import consumers

    assert consumers.CHECK_INTERVAL == 25
    assert consumers.CHECK_INTERVAL <= 30
    assert consumers.FeedConsumer().check_interval() == 25


# --- сбои ------------------------------------------------------------------------------------------------------------

def test_ws_state_error_in_check_loop_closes_with_1013(monkeypatch):
    """FR-627: ошибка проверки сессии в цикле закрывает соединение кодом 1013 (а не оставляет без проверки)."""
    from apps.core.services import sessions

    _fast(monkeypatch)
    real, calls = sessions.ws_state, []

    def fake(session, user):
        calls.append(1)
        if len(calls) == 1:
            return real(session, user)
        raise RuntimeError("сбой проверки (подмена теста)")

    monkeypatch.setattr("apps.core.services.sessions.ws_state", fake)
    user = _employee()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        assert conn.accepted
        assert await conn.wait_close(2.0) == 1013

    ws_run(scenario)
    assert len(calls) >= 2


def test_channel_layer_error_in_consumer_closes_with_1011(monkeypatch):
    """FR-627: ошибка слоя каналов в потребителе (подписка на группу) закрывает соединение кодом 1011."""
    async def broken(self, group, channel):
        raise OSError("слой каналов недоступен (подмена теста)")

    monkeypatch.setattr("channels_redis.core.RedisChannelLayer.group_add", broken)
    user = _employee()

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        code = conn.close_code if conn.close_code is not None else await conn.wait_close(2.0)
        assert code == 1011

    ws_run(scenario)


# --- группа и запрос --------------------------------------------------------------------------------------------------

def test_connect_adds_socket_to_personal_group_feed_u_id():
    """FR-627: соединение подписано на личную группу `feed.u.<id>`: сообщение `feed.event` в неё доходит, в группу
    другого сотрудника — нет."""
    from channels.layers import get_channel_layer

    author, user, other = ff.as_writer(full_name="Автор Авторов"), _employee(), _employee("Другой Узлов")
    post = ff.make_post(author.user, to=[user.user, other.user])
    message = {"type": "feed.event", "post": post.pk, "action": "post", "owner": 0, "comment": None,
               "moderators": [], "staff_viewers": [],
               "variants": {"reader:0": f'<div id="feed-post-{post.pk}-body" hx-swap-oob="true">МЕТКА-ГРУППЫ</div>'}}

    async def scenario(hub):
        conn = await ff.ws_client(user, f"post={post.pk}", hub=hub)
        assert conn.accepted
        layer = get_channel_layer()
        await layer.group_send(f"feed.u.{other.user.pk}", message)
        assert await conn.receive(0.6) is None, "сообщение в группу другого сотрудника дошло"
        await layer.group_send(f"feed.u.{user.user.pk}", message)
        frame = await conn.receive(2.0)
        assert frame is not None and "МЕТКА-ГРУППЫ" in frame, "сообщение в личную группу не дошло"

    ws_run(scenario)


def test_query_keeps_only_filter_keys_or_post_and_drops_foreign_keys(django_capture_on_commit_callbacks):
    """FR-627: из адреса соединения берутся только ключи фильтра (`f`, `author`, `from`, `to`) или `post`; чужие ключи
    отбрасываются без ошибки: фильтр `f=important` действует (плашка о важной записи есть, об обычной нет), а у
    карточки с фильтром и чужим ключом приходят кадры своей записи."""
    capture = django_capture_on_commit_callbacks
    author, viewer = ff.as_writer(full_name="Автор Авторов"), _employee()
    card_post = ff.make_post(author.user, to=[viewer.user])

    def publish_important():
        with capture(execute=True):
            return author.client.post("/feed/posts/", {
                "kind": "important", "text": "Важная запись", "term": "day", "to": [f"p{viewer.user.pk}"]}, **HX)

    async def scenario(hub):
        page = await ff.ws_client(viewer, "f=important&evil=1&ids=99&since=2000-01-01", hub=hub)
        assert page.accepted
        await ff.send_sync(page, [], timezone.now())
        assert await page.receive(2.0) is not None, "ответа на `sync` нет"
        card = await ff.ws_client(viewer, f"post={card_post.pk}&f=mine&evil=%3Cb%3E", hub=hub)
        assert card.accepted
        plain = await hub.do(_publish_after_commit, capture, author, viewer.user)
        assert plain.status_code == 200
        assert await page.receive(0.8) is None, "фильтр `f=important` не применён: плашка об обычной записи"
        assert (await hub.do(publish_important)).status_code == 200
        banner = ws_fragments(await page.receive(2.0) or "").get("feed-new")
        assert banner is not None and banner.attrs.get("data-count") == "1", "плашки о важной записи нет"
        await _drain_quiet(card)
        comment = await hub.do(_comment_after_commit, capture, author, card_post)
        assert comment.status_code == 200
        frame = await card.receive(2.0)
        assert frame is not None and f"feed-post-{card_post.pk}-comments" in frame, "кадры карточки не пришли"

    ws_run(scenario)


async def _drain_quiet(conn, timeout: float = 0.4) -> None:
    while await conn.receive(timeout) is not None:
        pass


def _comment_after_commit(capture, session, post):
    with capture(execute=True):
        return session.client.post(f"/feed/{post.pk}/comments/", {"text": "Для карточки"}, **HX)


def test_client_messages_do_not_extend_session_idle_time():
    """FR-627: сообщения клиента (`sync`, `add`, произвольные) не продлевают сессию: `last_activity` не меняется."""
    user = _employee()
    before = timezone.now() - timedelta(minutes=10)
    support.model("core.UserSession").objects.filter(session_key=_sid(user)).update(last_activity=before)

    def activity():
        return support.model("core.UserSession").objects.get(session_key=_sid(user)).last_activity

    async def scenario(hub):
        conn = await ff.ws_client(user, hub=hub)
        assert conn.accepted
        await ff.send_sync(conn, [1, 2, 3], timezone.now())
        await ff.send_add(conn, [4], timezone.now())
        await conn.send("ping")
        await conn.send(json.dumps({"type": "anything"}))
        await _drain_quiet(conn, 0.5)
        assert conn.close_code is None, "соединение закрыто"
        assert await hub.do(activity) == before

    ws_run(scenario)
