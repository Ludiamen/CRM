"""T-4117: выход, устройства и подписки Web Push (FR-324). Сценарий 5 спеки SPEC-004.

Подписка Web Push принадлежит устройству (`PushSubscription.device`, CONTRACT-004 § 2.2): выход кнопкой и «выйти
везде» публикуют `core.logged_out` (§ 3.3), подписчик `push.on_logged_out` удаляет подписки устройств из события
(§ 6.12, причина `logout`); «забыть устройство» и «закрыть сессию на устройстве» удаляют `KnownDevice`, подписка
уходит каскадом; истечение по бездействию, смена пароля и сброс второго фактора подписок не трогают (план,
«Web Push», «Выход из портала»). Подписку устройства тест создаёт сам через `push.save(device_id=…)` (дополнение 4
контракта). Имена кода среза 004 — внутри тестов или через `support.model`. Всё, что идёт после фиксации, —
внутри `django_capture_on_commit_callbacks`; в журнале приложения нет ошибок подписчиков шины (решение 24 задач).
"""
import logging
import uuid
from html.parser import HTMLParser

import pytest

from tests import factories, support
from tests.support import model
from tests.support_notify import browser_keys

pytestmark = pytest.mark.django_db

SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.5 Safari/605.1.15")
PAGE = "/me/notifications/"
EVERYWHERE = "/me/security/logout-everywhere/"
CHANGE_URL = "/me/security/password/"


# --- помощники файла -------------------------------------------------------------------------------------

def _no_subscriber_errors(caplog) -> None:
    """Решение 24 задач: сбоев подписчиков шины в журнале приложения нет."""
    bad = [r.getMessage() for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, f"ошибки подписчиков шины: {bad}"


def _device_id(client) -> int:
    """Номер `KnownDevice` сессии клиента (`UserSession.device_id`)."""
    row = model("core.UserSession").objects.get(session_key=client.session.session_key)
    assert row.device_id is not None, "у сессии клиента нет устройства"
    return row.device_id


def _subscribe(user, device_id=None):
    """Подписка Web Push сотрудника: адрес разрешённого хоста, ключи браузера, User-Agent Chrome (дополнение 4)."""
    from apps.notify.services import push

    pair = browser_keys()
    return push.save(user, endpoint=f"https://fcm.googleapis.com/{uuid.uuid4().hex}", p256dh=pair.p256dh,
                     auth=pair.auth, device_id=device_id, user_agent=support.CHROME_UA)


class _Marks(HTMLParser):
    """Открывающие теги страницы с их атрибутами (значение без кавычек и без значения — пустая строка)."""

    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k: (v or "") for k, v in attrs}))


def _marks(html: str) -> list:
    parser = _Marks()
    parser.feed(html)
    return parser.tags


def _alive(user) -> set:
    """Номера подписок сотрудника, оставшихся в базе."""
    return set(model("notify.PushSubscription").objects.filter(user=user).values_list("pk", flat=True))


def _audit(action: str, user=None) -> list:
    qs = model("core.AuditEvent").objects.filter(action=action)
    if user is not None:
        qs = qs.filter(object_id=str(user.pk))
    return list(qs.order_by("id"))


def _change_password(client, user):
    fresh = factories.new_password()
    return client.post(CHANGE_URL, {"current_password": user.test_password, "password1": fresh, "password2": fresh})


# --- выход кнопкой ----------------------------------------------------------------------------------------

def test_logout_button_deletes_subscription_of_this_device(caplog, django_capture_on_commit_callbacks):
    """FR-324: «Выйти» удаляет подписки Web Push устройства текущей сессии; запись устройства остаётся; журнал —
    `notify.push_removed` от системы, причина `logout`, браузер и платформа удалённой подписки, без адреса и ключей."""
    user = support.make_employee()
    here = support.logged_in(user, ip="203.0.113.11")
    device = _device_id(here)
    first, second = _subscribe(user, device), _subscribe(user, device)
    with django_capture_on_commit_callbacks(execute=True):
        done = here.post("/logout/")
    assert done.status_code == 302
    assert _alive(user) == set(), "обе подписки устройства удалены"
    assert model("core.KnownDevice").objects.filter(pk=device).exists(), "выход устройство не забывает"
    events = _audit("notify.push_removed", user)
    assert len(events) == 2
    for event in events:
        assert event.actor_id is None and event.object_type == "user"
        assert event.before == {"browser": first.browser, "platform": first.platform}
        assert event.after == {"reason": "logout"}
        text = f"{event.before}{event.after}"
        assert first.endpoint not in text and second.endpoint not in text and first.auth not in text
    _no_subscriber_errors(caplog)


def test_logout_keeps_subscriptions_of_other_devices(caplog, django_capture_on_commit_callbacks):
    """FR-324: выход с одного устройства оставляет подписки других устройств сотрудника (и их сессии); записей
    `notify.push_removed` — только по удалённым."""
    user = support.make_employee()
    here = support.logged_in(user, ip="203.0.113.12")
    there = support.logged_in(user, ip="203.0.113.13", ua=support.CHROME_UA)
    third = support.logged_in(user, ip="203.0.113.14", ua=SAFARI_UA)
    gone = _subscribe(user, _device_id(here))
    kept_there, kept_third = _subscribe(user, _device_id(there)), _subscribe(user, _device_id(third))
    with django_capture_on_commit_callbacks(execute=True):
        assert here.post("/logout/").status_code == 302
    assert _alive(user) == {kept_there.pk, kept_third.pk}
    assert there.get("/me/").status_code == 200, "сессия другого устройства осталась"
    assert len(_audit("notify.push_removed", user)) == 1 and gone.pk not in _alive(user)
    _no_subscriber_errors(caplog)


def test_logout_does_not_touch_other_accounts_subscriptions(caplog, django_capture_on_commit_callbacks):
    """FR-324: выход одного сотрудника не удаляет подписки другого; подписчик `push.on_logged_out` отбирает подписки
    по сотруднику из события, а не только по номеру устройства."""
    from apps.notify.services import push

    user, other = support.make_employee(), support.make_employee()
    mine = support.logged_in(user, ip="203.0.113.15")
    theirs = support.logged_in(other, ip="203.0.113.16", ua=support.CHROME_UA)
    own_sub = _subscribe(user, _device_id(mine))
    other_sub = _subscribe(other, _device_id(theirs))
    other_bare = _subscribe(other)
    with django_capture_on_commit_callbacks(execute=True):
        assert mine.post("/logout/").status_code == 302
    assert _alive(user) == set() and not model("notify.PushSubscription").objects.filter(pk=own_sub.pk).exists()
    assert _alive(other) == {other_sub.pk, other_bare.pk}
    assert theirs.get("/me/").status_code == 200
    assert _audit("notify.push_removed", other) == []
    # событие с чужим номером устройства: подписка другого сотрудника остаётся
    with django_capture_on_commit_callbacks(execute=True):
        push.on_logged_out(user_id=user.pk, device_ids=[_device_id(theirs)], reason="logout")
    assert _alive(other) == {other_sub.pk, other_bare.pk}
    _no_subscriber_errors(caplog)


def test_next_login_offers_to_enable_push_again(webpush_on, caplog, django_capture_on_commit_callbacks):
    """FR-324: после выхода и нового входа с того же браузера на «Моих уведомлениях» устройства в списке нет и есть
    кнопка «Включить push на этом устройстве»; до выхода строка устройства в списке была."""
    user = support.make_employee()
    client = support.logged_in(user, ip="203.0.113.17")
    sub = _subscribe(user, _device_id(client))
    before = client.get(PAGE)
    assert before.status_code == 200
    assert any(t == "li" and a.get("data-device") == str(sub.pk) for t, a in _marks(before.content.decode())), \
        "до выхода устройство в списке"
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post("/logout/").status_code == 302
    support.login(client, user)
    after = client.get(PAGE)
    assert after.status_code == 200
    tags = _marks(after.content.decode())
    section = [a for t, a in tags if a.get("data-section") == "push"]
    assert len(section) == 1 and section[0].get("data-web-push") == "on"
    assert any(t == "button" and a.get("data-action") == "push-subscribe" for t, a in tags), \
        "портал снова предлагает включить push"
    assert not any(t == "li" and a.get("data-device") == str(sub.pk) for t, a in tags), \
        "подписка этого устройства удалена"
    assert any(a.get("data-empty-state") == "devices" for _, a in tags)
    _no_subscriber_errors(caplog)


# --- «выйти везде» -----------------------------------------------------------------------------------------

def test_logout_all_devices_deletes_others_and_keeps_current(caplog, django_capture_on_commit_callbacks):
    """FR-324: «Выйти на всех устройствах» удаляет подписки устройств остальных сессий и оставляет подписку
    устройства текущей сессии и подписку без устройства; журнал — по записи `logout` на каждую удалённую."""
    user, other = support.make_employee(), support.make_employee()
    current = support.logged_in(user, ip="203.0.113.18")
    second = support.logged_in(user, ip="203.0.113.19", ua=support.CHROME_UA)
    third = support.logged_in(user, ip="203.0.113.20", ua=SAFARI_UA)
    kept_current, kept_bare = _subscribe(user, _device_id(current)), _subscribe(user)
    _subscribe(user, _device_id(second))
    _subscribe(user, _device_id(third))
    foreign = _subscribe(other, _device_id(support.logged_in(other, ip="203.0.113.21")))
    with django_capture_on_commit_callbacks(execute=True):
        assert current.post(EVERYWHERE).status_code == 302
    assert _alive(user) == {kept_current.pk, kept_bare.pk}
    assert _alive(other) == {foreign.pk}
    assert current.get("/me/").status_code == 200, "текущая сессия осталась"
    events = _audit("notify.push_removed", user)
    assert len(events) == 2 and all(e.actor_id is None and e.after == {"reason": "logout"} for e in events)
    _no_subscriber_errors(caplog)


# --- «забыть устройство» и «закрыть сессию» ----------------------------------------------------------------

def test_forget_device_deletes_subscription_by_cascade(caplog, django_capture_on_commit_callbacks):
    """FR-324: `devices.forget` удаляет запись устройства, подписка устройства уходит каскадом; подписка другого
    устройства и подписка без устройства остаются."""
    from apps.core.services import devices

    user = support.make_employee()
    here = support.logged_in(user, ip="203.0.113.22")
    there = support.logged_in(user, ip="203.0.113.23", ua=support.CHROME_UA)
    there_device = _device_id(there)
    kept, kept_bare = _subscribe(user, _device_id(here)), _subscribe(user)
    dropped = _subscribe(user, there_device)
    with django_capture_on_commit_callbacks(execute=True):
        assert devices.forget(user, there_device) is True
    assert not model("core.KnownDevice").objects.filter(pk=there_device).exists()
    assert not model("notify.PushSubscription").objects.filter(pk=dropped.pk).exists()
    assert _alive(user) == {kept.pk, kept_bare.pk}
    _no_subscriber_errors(caplog)


def test_close_session_on_device_deletes_subscription_by_cascade(
        caplog, django_capture_on_commit_callbacks):
    """FR-324: `devices.close_sessions` закрывает сессии устройства и удаляет запись устройства, подписка уходит
    каскадом; подписка и сессия другого устройства остаются."""
    from apps.core.services import devices

    user = support.make_employee()
    here = support.logged_in(user, ip="203.0.113.24")
    there = support.logged_in(user, ip="203.0.113.25", ua=support.CHROME_UA)
    there_device = _device_id(there)
    kept = _subscribe(user, _device_id(here))
    dropped = _subscribe(user, there_device)
    with django_capture_on_commit_callbacks(execute=True):
        assert devices.close_sessions(user, there_device) is True
    assert not model("core.UserSession").objects.filter(device_id=there_device).exists()
    assert not model("core.KnownDevice").objects.filter(pk=there_device).exists()
    assert not model("notify.PushSubscription").objects.filter(pk=dropped.pk).exists()
    assert _alive(user) == {kept.pk}
    assert there.get("/me/").status_code == 302, "сессия закрытого устройства прервана"
    assert here.get("/me/").status_code == 200
    _no_subscriber_errors(caplog)


# --- что подписку не удаляет --------------------------------------------------------------------------------

def test_idle_expiry_keeps_subscription(clock, bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-324: истечение сессии по бездействию — не выход: подписка устройства остаётся, `core.logged_out` не
    публикуется, записей `notify.push_removed` нет."""
    bus_spy.listen("core.logged_out")
    user = support.make_employee()
    client = support.logged_in(user, ip="203.0.113.26")
    sub = _subscribe(user, _device_id(client))
    clock.advance(minutes=61)
    with django_capture_on_commit_callbacks(execute=True):
        done = client.get("/me/")
    assert done.status_code == 302 and "/login/" in done["Location"], "сессия истекла"
    assert not model("core.UserSession").objects.filter(user=user).exists()
    assert _alive(user) == {sub.pk}
    assert bus_spy.calls("core.logged_out") == []
    assert _audit("notify.push_removed") == []
    _no_subscriber_errors(caplog)


def test_password_change_keeps_subscriptions_of_other_devices(
        bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-324: смена пароля закрывает другие сессии, но подписки их устройств (и текущего) остаются: push несёт
    только событие и ссылку; `core.logged_out` не публикуется."""
    bus_spy.listen("core.logged_out")
    user = support.make_employee()
    here = support.logged_in(user, ip="203.0.113.27")
    there = support.logged_in(user, ip="203.0.113.28", ua=support.CHROME_UA)
    sub_here, sub_there = _subscribe(user, _device_id(here)), _subscribe(user, _device_id(there))
    with django_capture_on_commit_callbacks(execute=True):
        assert _change_password(here, user).status_code == 302
    assert there.get("/me/").status_code == 302, "сессия второго устройства закрыта сменой пароля"
    assert _alive(user) == {sub_here.pk, sub_there.pk}
    assert bus_spy.calls("core.logged_out") == []
    assert _audit("notify.push_removed") == []
    _no_subscriber_errors(caplog)


def test_second_factor_reset_keeps_subscriptions(bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-324: сброс второго фактора закрывает сессии сотрудника, но подписки его устройств остаются;
    `core.logged_out` не публикуется, записей `notify.push_removed` нет."""
    from apps.core.services import accounts

    bus_spy.listen("core.logged_out")
    admin, user = support.make_admin(), support.make_employee()
    here = support.logged_in(user, ip="203.0.113.29")
    there = support.logged_in(user, ip="203.0.113.30", ua=support.CHROME_UA)
    sub_here, sub_there = _subscribe(user, _device_id(here)), _subscribe(user, _device_id(there))
    bare = _subscribe(user)
    with django_capture_on_commit_callbacks(execute=True):
        accounts.reset_second_factor(user, actor=admin)
    assert not model("core.UserSession").objects.filter(user=user).exists(), "сессии закрыты"
    assert _alive(user) == {sub_here.pk, sub_there.pk, bare.pk}
    assert bus_spy.calls("core.logged_out") == []
    assert _audit("notify.push_removed") == []
    _no_subscriber_errors(caplog)


# --- сессия без устройства и событие -----------------------------------------------------------------------

def test_logout_without_device_cookie_keeps_subscription_without_device(
        bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-324: у сессии нет устройства (нет куки устройства) — при выходе подписка без устройства не находится и
    остаётся, как и подписка устройства другой сессии; событие несёт `device_ids == []`."""
    bus_spy.listen("core.logged_out")
    user = support.make_employee()
    other_session = support.logged_in(user, ip="203.0.113.31")
    bare = support.logged_in(user, ip="203.0.113.32", ua=support.CHROME_UA)
    model("core.UserSession").objects.filter(session_key=bare.session.session_key).update(device=None)
    without_device = _subscribe(user)
    on_device = _subscribe(user, _device_id(other_session))
    with django_capture_on_commit_callbacks(execute=True):
        assert bare.post("/logout/").status_code == 302
    assert bus_spy.calls("core.logged_out") == [{"user_id": user.pk, "device_ids": [], "reason": "logout"}]
    assert _alive(user) == {without_device.pk, on_device.pk}
    assert _audit("notify.push_removed") == []
    _no_subscriber_errors(caplog)


def test_logged_out_event_carries_device_taken_before_session_end(
        bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-324: `core.logged_out` при выходе кнопкой несёт устройство, прочитанное до закрытия сессии (запись
    `UserSession` к моменту обработчика уже удалена), и подписка этого устройства удаляется подписчиком `notify`
    именно по этому номеру."""
    bus_spy.listen("core.logged_out")
    user = support.make_employee()
    here = support.logged_in(user, ip="203.0.113.33")
    device = _device_id(here)
    session_name = here.session.session_key
    sub = _subscribe(user, device)
    with django_capture_on_commit_callbacks(execute=True):
        assert here.post("/logout/").status_code == 302
    assert bus_spy.calls("core.logged_out") == [{"user_id": user.pk, "device_ids": [device], "reason": "logout"}]
    assert not model("core.UserSession").objects.filter(session_key=session_name).exists(), "сессия к этому моменту закрыта"
    assert not model("notify.PushSubscription").objects.filter(pk=sub.pk).exists()
    _no_subscriber_errors(caplog)
