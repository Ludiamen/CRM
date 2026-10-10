"""T-4105: события ядра, выход и увольнение (FR-305, FR-313, FR-324, FR-340). Сценарии 1, 5, 8 и 11 спеки SPEC-004.

События `core.new_device`, `core.password_changed`, `core.second_factor_reset`, `core.user_dismissed`,
`core.user_rehired`, `core.logged_out` (CONTRACT-004 § 3.3), три вида безопасности (§ 3.5), подписчики
`notify` — `push.on_logged_out`, `cleanup.on_dismissed`, `cleanup.on_rehired` (§ 6.12, § 6.15).

Имена кода среза 004 (`apps.notify…`) импортируются внутри тестов или берутся через `support.model`:
сбор проходит до появления кода. Тесты событий идут под фикстурой `bus` (подписчиков нет, шина записывает
вызовы); тесты действия подписчиков `notify` — с настоящей шиной, в журнале приложения нет ошибок подписчиков
(решение 24 задач). Всё, что идёт после фиксации, выполняется внутри `django_capture_on_commit_callbacks`.
"""
import hashlib
import logging
import uuid
from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from tests import factories, support
from tests.support import model
from tests.support_notify import browser_keys

pytestmark = pytest.mark.django_db

SAFARI_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/17.5 Safari/605.1.15")
CHANGE_URL = "/me/security/password/"
EVERYWHERE = "/me/security/logout-everywhere/"
DEVICES = "/me/security/devices/"
SECURITY_URL = "/me/security/"

CORE_EVENTS = ("core.new_device", "core.password_changed", "core.second_factor_reset",
               "core.user_dismissed", "core.user_rehired", "core.logged_out")


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
    """Подписка Web Push сотрудника: адрес разрешённого хоста, ключи браузера (дополнение 4 контракта)."""
    from apps.notify.services import push

    pair = browser_keys()
    return push.save(user, endpoint=f"https://fcm.googleapis.com/{uuid.uuid4().hex}", p256dh=pair.p256dh,
                     auth=pair.auth, device_id=device_id)


def _change_password(client, user, fresh=None):
    fresh = fresh or factories.new_password()
    return client.post(CHANGE_URL, {"current_password": user.test_password, "password1": fresh, "password2": fresh})


def _other_client(user, source, *, ip: str, ua: str):
    """Ещё одна сессия сотрудника с той же кукой устройства, что у клиента `source`."""
    from apps.core.services import devices

    client = support.make_client(ip=ip, ua=ua)
    client.cookies[devices.COOKIE_NAME] = source.cookies[devices.COOKIE_NAME].value
    support.login(client, user)
    return client


def _audit(action: str, user=None):
    qs = model("core.AuditEvent").objects.filter(action=action)
    if user is not None:
        qs = qs.filter(object_id=str(user.pk))
    return list(qs.order_by("id"))


# --- core.new_device ---------------------------------------------------------------------------------------

def test_new_device_event_published_for_new_not_first_device_with_browser_platform_at(
        bus, django_capture_on_commit_callbacks):
    """FR-313, FR-305: вход с нового, не первого устройства публикует `core.new_device` с браузером и платформой из
    `devices.parse_user_agent` и временем с поясом; других ключей в данных нет; первый вход события не даёт."""
    from apps.core.services import devices

    bus.listen("core.new_device")
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.101")
    assert bus.calls("core.new_device") == [], "первое устройство — события нет"
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.102", ua=support.CHROME_UA)
    finished = timezone.now()
    calls = bus.calls("core.new_device")
    assert len(calls) == 1
    data = calls[0]
    assert set(data) == {"user_id", "browser", "platform", "at"}
    browser, platform = devices.parse_user_agent(support.CHROME_UA)
    assert browser and platform
    assert data["user_id"] == user.pk and data["browser"] == browser and data["platform"] == platform
    assert timezone.is_aware(data["at"]) and started <= data["at"] <= finished


def test_new_device_event_not_published_for_first_device(bus, django_capture_on_commit_callbacks):
    """FR-313: первый вход сотрудника (нет ни устройств, ни прежних входов) события `core.new_device` не публикует."""
    bus.listen("core.new_device")
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.103", ua=support.CHROME_UA)
    assert model("core.KnownDevice").objects.filter(user=user).count() == 1
    assert bus.calls("core.new_device") == []
    with django_capture_on_commit_callbacks(execute=True):  # контроль: второе устройство событие даёт
        support.logged_in(user, ip="198.51.100.199", ua=SAFARI_UA)
    assert [c["user_id"] for c in bus.calls("core.new_device")] == [user.pk]


def test_new_device_event_not_published_for_known_device(bus, django_capture_on_commit_callbacks):
    """FR-313: повторный вход с уже известного устройства (кука устройства сохранена) события не публикует."""
    bus.listen("core.new_device")
    user = support.make_employee()
    client = support.make_client(ip="198.51.100.104")
    with django_capture_on_commit_callbacks(execute=True):
        support.login(client, user)
        support.logged_in(user, ip="198.51.100.105", ua=support.CHROME_UA)
    assert len(bus.calls("core.new_device")) == 1, "второе устройство — новое"
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/logout/")
        support.login(client, user)
    assert len(bus.calls("core.new_device")) == 1, "то же устройство — не новое, события нет"
    assert model("core.KnownDevice").objects.filter(user=user).count() == 2


def test_new_device_event_published_exactly_where_core_mail_is_sent(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-305: событие публикуется в тех же случаях, что письмо `new_device`: после каждого шага число событий
    равно числу писем; первое устройство, известное устройство и ограниченная сессия (нет второго фактора) — ни того,
    ни другого."""
    bus.listen("core.new_device")
    user = support.make_employee()

    def counts():
        return len(bus.calls("core.new_device")), support.mails(to=user.email, template="new_device").count()

    client = support.make_client(ip="198.51.100.106")
    with django_capture_on_commit_callbacks(execute=True):
        support.login(client, user)
    assert counts() == (0, 0), "первое устройство"
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.107", ua=support.CHROME_UA)
    assert counts() == (1, 1), "новое не первое устройство"
    with django_capture_on_commit_callbacks(execute=True):
        client.post("/logout/")
        support.login(client, user)
    assert counts() == (1, 1), "известное устройство"
    model("core.EncryptedTOTPDevice").objects.filter(user=user).delete()
    limited = support.make_client(ip="198.51.100.108", ua=SAFARI_UA)
    with django_capture_on_commit_callbacks(execute=True):
        step = support.post_password(limited, user)
    assert step.status_code == 302
    assert counts() == (1, 1), "ограниченная сессия: устройство не запоминается, письма и события нет"
    assert model("core.KnownDevice").objects.filter(user=user).count() == 2


# --- core.password_changed, core.second_factor_reset ---------------------------------------------------------

def test_password_changed_event_published_on_profile_change(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-305: смена пароля в профиле публикует `core.password_changed` с `user_id` и `actor_id` — самим
    сотрудником; событие уходит вместе с письмом `password_changed`."""
    bus.listen("core.password_changed")
    user = support.make_employee()
    client = support.logged_in(user, ip="198.51.100.109")
    with django_capture_on_commit_callbacks(execute=True):
        done = _change_password(client, user)
    assert done.status_code == 302
    assert bus.calls("core.password_changed") == [{"user_id": user.pk, "actor_id": user.pk}]
    assert support.mails(to=user.email, template="password_changed").count() == 1


def test_password_changed_event_published_on_recovery(bus, django_capture_on_commit_callbacks):
    """FR-313: смена пароля по ссылке восстановления публикует `core.password_changed`, действующее лицо — сам
    сотрудник (как у записи журнала `password.changed`)."""
    bus.listen("core.password_changed")
    user = support.make_employee()
    _, code = factories.make_link(user, "reset")
    client = support.make_client(ip="198.51.100.110")
    assert client.post("/password/reset/exchange/", {"code": code}).status_code == 302
    fresh = factories.new_password()
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post("/password/reset/", {"password1": fresh, "password2": fresh})
    assert done.status_code == 302 and "/login/" in done["Location"]
    assert bus.calls("core.password_changed") == [{"user_id": user.pk, "actor_id": user.pk}]


def test_second_factor_reset_event_published_with_user_and_actor(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-305: сброс второго фактора публикует `core.second_factor_reset` (`user_id`, `actor_id`) после
    фиксации; действие системы (`actor=None`) — `actor_id` пусто."""
    from apps.core.services import accounts

    bus.listen("core.second_factor_reset")
    admin, target, other = support.make_admin(), support.make_employee(), support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            accounts.reset_second_factor(target, actor=admin)
            assert bus.calls("core.second_factor_reset") == [], "до фиксации события нет"
    assert bus.calls("core.second_factor_reset") == [{"user_id": target.pk, "actor_id": admin.pk}]
    with django_capture_on_commit_callbacks(execute=True):
        accounts.reset_second_factor(other, actor=None)
    assert bus.calls("core.second_factor_reset")[1:] == [{"user_id": other.pk, "actor_id": None}]
    assert support.mails(to=target.email, template="second_factor_reset").count() == 1


# --- core.user_dismissed, core.user_rehired -------------------------------------------------------------------

def test_user_dismissed_event_published_with_user_and_actor(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-340: увольнение публикует `core.user_dismissed` с `user_id` и `actor_id` после фиксации."""
    from apps.core.services import accounts

    bus.listen("core.user_dismissed")
    admin, target = support.make_admin(), support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            accounts.dismiss(target, actor=admin)
            assert bus.calls("core.user_dismissed") == [], "до фиксации события нет"
    assert bus.calls("core.user_dismissed") == [{"user_id": target.pk, "actor_id": admin.pk}]


def test_user_rehired_event_published_with_user_and_actor(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-340: повторный приём публикует `core.user_rehired` с `user_id` и `actor_id`; увольнение второго
    события не даёт."""
    from apps.core.services import accounts

    bus.listen("core.user_rehired")
    admin, target = support.make_admin(), support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        accounts.dismiss(target, actor=admin)
    assert bus.calls("core.user_rehired") == []
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            accounts.rehire(target, actor=admin)
            assert bus.calls("core.user_rehired") == [], "до фиксации события нет"
    assert bus.calls("core.user_rehired") == [{"user_id": target.pk, "actor_id": admin.pk}]


# --- core.logged_out -----------------------------------------------------------------------------------------

def test_logout_button_publishes_logged_out_with_device_of_current_session(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-324: «Выйти» публикует `core.logged_out`: `device_ids` — устройство текущей сессии (прочитано до
    закрытия сессии), `reason="logout"`; выход без входа события не даёт."""
    bus.listen("core.logged_out")
    user = support.make_employee()
    here = support.logged_in(user, ip="198.51.100.111")
    there = support.logged_in(user, ip="198.51.100.112", ua=support.CHROME_UA)
    here_device, there_device = _device_id(here), _device_id(there)
    assert here_device != there_device
    with django_capture_on_commit_callbacks(execute=True):
        anonymous = support.make_client(ip="198.51.100.113").post("/logout/")
    assert anonymous.status_code == 302 and bus.calls("core.logged_out") == [], "не вошёл — события нет"
    with django_capture_on_commit_callbacks(execute=True):
        done = here.post("/logout/")
    assert done.status_code == 302
    assert bus.calls("core.logged_out") == [{"user_id": user.pk, "device_ids": [here_device], "reason": "logout"}]
    assert not model("core.UserSession").objects.filter(device_id=here_device).exists()
    assert model("core.UserSession").objects.filter(device_id=there_device).exists(), "чужая сессия осталась"


def test_logout_everywhere_publishes_devices_of_other_sessions_without_current(
        bus, django_capture_on_commit_callbacks):
    """FR-313, FR-324: «Выйти везде» публикует `core.logged_out` с устройствами остальных сессий — по возрастанию, без
    повторов, без устройства текущей сессии; `reason="logout_everywhere"`."""
    bus.listen("core.logged_out")
    user = support.make_employee()
    current = support.logged_in(user, ip="198.51.100.114")
    second = support.logged_in(user, ip="198.51.100.115", ua=support.CHROME_UA)
    third = support.logged_in(user, ip="198.51.100.116", ua=SAFARI_UA)
    twin = _other_client(user, second, ip="198.51.100.117", ua=support.CHROME_UA)
    current_device, second_device, third_device = _device_id(current), _device_id(second), _device_id(third)
    assert _device_id(twin) == second_device, "две сессии одного устройства"
    assert len({current_device, second_device, third_device}) == 3
    with django_capture_on_commit_callbacks(execute=True):
        done = current.post(EVERYWHERE)
    assert done.status_code == 302
    assert bus.calls("core.logged_out") == [{"user_id": user.pk, "device_ids": sorted([second_device, third_device]),
                                             "reason": "logout_everywhere"}]
    assert model("core.UserSession").objects.filter(user=user).count() == 1, "текущая сессия осталась"


def test_logged_out_device_ids_exclude_sessions_without_device(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-324: сессия без устройства в `device_ids` не попадает; выход кнопкой из такой сессии даёт `[]`;
    «выйти везде» публикуется и при пустом списке."""
    UserSession = model("core.UserSession")
    bus.listen("core.logged_out")
    user = support.make_employee()
    main = support.logged_in(user, ip="198.51.100.118")
    bare = support.logged_in(user, ip="198.51.100.119", ua=support.CHROME_UA)
    UserSession.objects.filter(session_key=bare.session.session_key).update(device=None)
    with django_capture_on_commit_callbacks(execute=True):
        assert bare.post("/logout/").status_code == 302
    assert bus.calls("core.logged_out") == [{"user_id": user.pk, "device_ids": [], "reason": "logout"}]
    bare_again = support.logged_in(user, ip="198.51.100.120", ua=SAFARI_UA)
    with_device = support.logged_in(user, ip="198.51.100.121", ua=support.CHROME_UA)
    UserSession.objects.filter(session_key=bare_again.session.session_key).update(device=None)
    expected = _device_id(with_device)
    with django_capture_on_commit_callbacks(execute=True):
        assert main.post(EVERYWHERE).status_code == 302
    assert bus.calls("core.logged_out")[1:] == [{"user_id": user.pk, "device_ids": [expected],
                                                  "reason": "logout_everywhere"}]
    bare_last = support.logged_in(user, ip="198.51.100.122", ua=SAFARI_UA)
    UserSession.objects.filter(session_key=bare_last.session.session_key).update(device=None)
    with django_capture_on_commit_callbacks(execute=True):
        assert main.post(EVERYWHERE).status_code == 302
    assert bus.calls("core.logged_out")[2:] == [{"user_id": user.pk, "device_ids": [], "reason": "logout_everywhere"}]


def test_no_logged_out_event_on_idle_expiry(bus, clock, django_capture_on_commit_callbacks):
    """FR-313, FR-324: истечение сессии по бездействию (`SessionGuardMiddleware`) `core.logged_out` не публикует."""
    bus.listen("core.logged_out")
    user = support.make_employee()
    client = support.logged_in(user, ip="198.51.100.123")
    clock.advance(minutes=61)
    with django_capture_on_commit_callbacks(execute=True):
        done = client.get("/me/")
    assert done.status_code == 302 and "/login/" in done["Location"], "сессия истекла"
    assert not model("core.UserSession").objects.filter(user=user).exists()
    assert bus.calls("core.logged_out") == []
    control = support.make_employee()  # контроль: выход кнопкой событие даёт, значит, шина подключена
    leaving = support.logged_in(control, ip="198.51.100.198")
    with django_capture_on_commit_callbacks(execute=True):
        leaving.post("/logout/")
    assert [c["user_id"] for c in bus.calls("core.logged_out")] == [control.pk], "от бездействия событий не прибавилось"


def test_no_logged_out_event_when_session_closed_elsewhere(bus, django_capture_on_commit_callbacks):
    """FR-313, FR-324: закрытие сессии в другом месте — «Закрыть сессию» устройства, смена пароля, блокировка —
    `core.logged_out` не публикует."""
    from apps.core.services import accounts

    bus.listen("core.logged_out")
    user, admin = support.make_employee(), support.make_admin()
    mine = support.logged_in(user, ip="198.51.100.124")
    remote = support.logged_in(user, ip="198.51.100.125", ua=support.CHROME_UA)
    with django_capture_on_commit_callbacks(execute=True):
        closed = mine.post(f"{DEVICES}{_device_id(remote)}/close/")
    assert closed.status_code == 302
    assert remote.get("/me/").status_code == 302, "сессия устройства закрыта"
    third = support.logged_in(user, ip="198.51.100.126", ua=SAFARI_UA)
    with django_capture_on_commit_callbacks(execute=True):
        assert _change_password(mine, user).status_code == 302
    assert third.get("/me/").status_code == 302, "смена пароля закрыла остальные сессии"
    with django_capture_on_commit_callbacks(execute=True):
        accounts.block(user, "проверка", actor=admin)
    assert not model("core.UserSession").objects.filter(user=user).exists()
    assert bus.calls("core.logged_out") == []
    control = support.make_employee()  # контроль: выход кнопкой событие даёт, значит, шина подключена
    leaving = support.logged_in(control, ip="198.51.100.197")
    with django_capture_on_commit_callbacks(execute=True):
        leaving.post("/logout/")
    assert [c["user_id"] for c in bus.calls("core.logged_out")] == [control.pk], "закрытие в другом месте событий не дало"


# --- подписки Web Push при выходе (FR-324) --------------------------------------------------------------------

def test_logout_button_deletes_push_subscription_of_current_device(
        caplog, django_capture_on_commit_callbacks):
    """FR-324: выход кнопкой удаляет подписку Web Push устройства текущей сессии; подписки других устройств, подписка
    без устройства и подписки других сотрудников остаются; журнал — `notify.push_removed` от системы, причина `logout`,
    без адреса."""
    PushSubscription = model("notify.PushSubscription")
    user, other_user = support.make_employee(), support.make_employee()
    here = support.logged_in(user, ip="198.51.100.127")
    there = support.logged_in(user, ip="198.51.100.128", ua=support.CHROME_UA)
    gone = _subscribe(user, _device_id(here))
    kept_there = _subscribe(user, _device_id(there))
    kept_bare = _subscribe(user)
    kept_other = _subscribe(other_user)
    with django_capture_on_commit_callbacks(execute=True):
        assert here.post("/logout/").status_code == 302
    assert set(PushSubscription.objects.values_list("pk", flat=True)) == {kept_there.pk, kept_bare.pk, kept_other.pk}
    assert not PushSubscription.objects.filter(pk=gone.pk).exists()
    events = _audit("notify.push_removed", user)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id is None and event.object_type == "user" and event.after == {"reason": "logout"}
    assert gone.endpoint not in f"{event.before}{event.after}"
    _no_subscriber_errors(caplog)


def test_logout_everywhere_deletes_subscriptions_of_other_devices_keeps_current(
        caplog, django_capture_on_commit_callbacks):
    """FR-324: «Выйти везде» удаляет подписки устройств остальных сессий и оставляет подписку устройства текущей
    сессии и подписку без устройства; по записи журнала `notify.push_removed` (причина `logout`) на каждую удалённую."""
    PushSubscription = model("notify.PushSubscription")
    user = support.make_employee()
    current = support.logged_in(user, ip="198.51.100.129")
    second = support.logged_in(user, ip="198.51.100.130", ua=support.CHROME_UA)
    third = support.logged_in(user, ip="198.51.100.131", ua=SAFARI_UA)
    kept_current = _subscribe(user, _device_id(current))
    kept_bare = _subscribe(user)
    _subscribe(user, _device_id(second))
    _subscribe(user, _device_id(third))
    with django_capture_on_commit_callbacks(execute=True):
        assert current.post(EVERYWHERE).status_code == 302
    assert set(PushSubscription.objects.filter(user=user).values_list("pk", flat=True)) == {
        kept_current.pk, kept_bare.pk}
    events = _audit("notify.push_removed", user)
    assert len(events) == 2 and all(e.actor_id is None and e.after == {"reason": "logout"} for e in events)
    _no_subscriber_errors(caplog)


def test_idle_expiry_and_password_change_keep_push_subscriptions(
        clock, caplog, django_capture_on_commit_callbacks):
    """FR-324: подписка принадлежит устройству: закрытие сессии сменой пароля и истечение по бездействию подписок не
    удаляют, записей `notify.push_removed` нет."""
    PushSubscription = model("notify.PushSubscription")
    user = support.make_employee()
    here = support.logged_in(user, ip="198.51.100.132")
    there = support.logged_in(user, ip="198.51.100.133", ua=support.CHROME_UA)
    sub_here, sub_there = _subscribe(user, _device_id(here)), _subscribe(user, _device_id(there))
    with django_capture_on_commit_callbacks(execute=True):
        assert _change_password(here, user).status_code == 302
    assert there.get("/me/").status_code == 302, "сессия второго устройства закрыта сменой пароля"
    assert set(PushSubscription.objects.filter(user=user).values_list("pk", flat=True)) == {sub_here.pk, sub_there.pk}
    clock.advance(minutes=61)
    with django_capture_on_commit_callbacks(execute=True):
        assert here.get("/me/").status_code == 302, "сессия истекла по бездействию"
    assert set(PushSubscription.objects.filter(user=user).values_list("pk", flat=True)) == {sub_here.pk, sub_there.pk}
    assert _audit("notify.push_removed") == []
    _no_subscriber_errors(caplog)


def test_forget_device_removes_its_push_subscription_by_cascade(caplog, django_capture_on_commit_callbacks):
    """FR-324: «Забыть» устройство удаляет его подписку Web Push каскадом (подписка принадлежит устройству); подписка
    другого устройства остаётся."""
    PushSubscription = model("notify.PushSubscription")
    user = support.make_employee()
    here = support.logged_in(user, ip="198.51.100.134")
    there = support.logged_in(user, ip="198.51.100.135", ua=support.CHROME_UA)
    there_device = _device_id(there)
    kept = _subscribe(user, _device_id(here))
    dropped = _subscribe(user, there_device)
    with django_capture_on_commit_callbacks(execute=True):
        assert here.post(f"{DEVICES}{there_device}/forget/").status_code == 302
    assert not model("core.KnownDevice").objects.filter(pk=there_device).exists()
    assert not PushSubscription.objects.filter(pk=dropped.pk).exists()
    assert PushSubscription.objects.filter(pk=kept.pk).exists()
    _no_subscriber_errors(caplog)


# --- увольнение и повторный приём (FR-340) ---------------------------------------------------------------------

def _notification(user, text="Пароль изменён", kind="core.password_changed"):
    return model("notify.Notification").objects.create(user=user, kind=kind, text=text, url=SECURITY_URL)


def test_dismissed_event_removes_subscriptions_bindings_codes_and_settings_but_keeps_notification_records(
        caplog, django_capture_on_commit_callbacks):
    """FR-340: увольнение удаляет подписки Web Push, привязки Telegram и MAX, коды привязки и настройки сотрудника;
    записи на портале и сводки остаются до срока хранения; чужие данные целы; журнал — от системы, причина
    `dismissed`, без идентификаторов чатов и адресов."""
    from apps.core.services import accounts

    PushSubscription, ChatBinding = model("notify.PushSubscription"), model("notify.ChatBinding")
    BindCode, Settings = model("notify.BindCode"), model("notify.UserNotifySettings")
    admin, target, other = support.make_admin(), support.make_employee(), support.make_employee()
    chat_ids = {"telegram": f"c{uuid.uuid4().hex}", "max": f"c{uuid.uuid4().hex}"}
    soon = timezone.now() + timedelta(minutes=10)
    for channel, chat in chat_ids.items():
        ChatBinding.objects.create(user=target, channel=channel, chat_id=chat)
        BindCode.objects.create(user=target, channel=channel, code_hash=hashlib.sha256(b"12345678").hexdigest(),
                                expires_at=soon)
    ChatBinding.objects.create(user=other, channel="telegram", chat_id=f"c{uuid.uuid4().hex}")
    Settings.objects.create(user=target, matrix={})
    Settings.objects.create(user=other, matrix={})
    sub_target = _subscribe(target)
    sub_other = _subscribe(other)
    kept_note = _notification(target)
    kept_digest = model("notify.Digest").objects.create(user=target)
    notes_before = model("notify.Notification").objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        accounts.dismiss(target, actor=admin)
    assert not PushSubscription.objects.filter(user=target).exists()
    assert not ChatBinding.objects.filter(user=target).exists()
    assert not BindCode.objects.filter(user=target).exists()
    assert not Settings.objects.filter(user=target).exists()
    assert PushSubscription.objects.filter(pk=sub_other.pk).exists()
    assert ChatBinding.objects.filter(user=other).count() == 1 and Settings.objects.filter(user=other).exists()
    assert model("notify.Notification").objects.filter(pk=kept_note.pk).exists(), "записи остаются до срока хранения"
    assert model("notify.Digest").objects.filter(pk=kept_digest.pk).exists()
    assert model("notify.Notification").objects.count() == notes_before, "записи вида при увольнении не создаются"
    pushes = _audit("notify.push_removed", target)
    assert len(pushes) == 1 and pushes[0].actor_id is None and pushes[0].after == {"reason": "dismissed"}
    unbound = _audit("notify.channel_unbound", target)
    assert sorted(e.before.get("channel") for e in unbound) == ["max", "telegram"]
    for event in unbound:
        assert event.actor_id is None and event.object_type == "user"
        assert event.before.get("bound") is True
        assert event.after == {"bound": False, "reason": "dismissed"}
    dumped = "".join(f"{e.before}{e.after}" for e in pushes + unbound)
    assert all(chat not in dumped for chat in chat_ids.values()) and sub_target.endpoint not in dumped
    _no_subscriber_errors(caplog)


def test_dismissed_event_marks_waiting_held_sending_deliveries_skipped(caplog, django_capture_on_commit_callbacks):
    """FR-340: доставки уволенного (по уведомлению и по сводке) в состояниях `waiting`, `held`, `sending` становятся
    `skipped` с причиной `user_dismissed` и без срока аренды; `sent`, `failed` и доставки других сотрудников не меняются."""
    from apps.core.services import accounts

    Delivery = model("notify.Delivery")
    admin, target, other = support.make_admin(), support.make_employee(), support.make_employee()
    now = timezone.now()
    first, second, foreign = _notification(target), _notification(target, "Второй фактор сброшен",
                                                                  "core.second_factor_reset"), _notification(other)
    digest = model("notify.Digest").objects.create(user=target)
    waiting = Delivery.objects.create(notification=first, channel="email", state="waiting", due_at=now)
    held = Delivery.objects.create(notification=first, channel="webpush", state="held")
    sending = Delivery.objects.create(notification=first, channel="telegram", state="sending",
                                      enqueued_at=now, lease_until=now + timedelta(minutes=5))
    sent = Delivery.objects.create(notification=first, channel="max", state="sent")
    failed = Delivery.objects.create(notification=second, channel="email", state="failed", reason="expired")
    in_digest = Delivery.objects.create(digest=digest, channel="email", state="waiting", due_at=now)
    foreign_waiting = Delivery.objects.create(notification=foreign, channel="email", state="waiting", due_at=now)
    with django_capture_on_commit_callbacks(execute=True):
        accounts.dismiss(target, actor=admin)
    for row in (waiting, held, sending, in_digest):
        row.refresh_from_db()
        assert (row.state, row.reason, row.lease_until) == ("skipped", "user_dismissed", None), row.channel
    sent.refresh_from_db(), failed.refresh_from_db(), foreign_waiting.refresh_from_db()
    assert (sent.state, sent.reason) == ("sent", "")
    assert (failed.state, failed.reason) == ("failed", "expired")
    assert (foreign_waiting.state, foreign_waiting.reason) == ("waiting", "")
    _no_subscriber_errors(caplog)


def test_rehired_event_deletes_former_notifications_of_employee(caplog, django_capture_on_commit_callbacks):
    """FR-340: повторный приём удаляет прежние записи на портале сотрудника (доставки каскадом) и его сводки; до приёма
    они лежали; записи других сотрудников остаются."""
    from apps.core.services import accounts

    Notification, Delivery, Digest = model("notify.Notification"), model("notify.Delivery"), model("notify.Digest")
    admin, target, other = support.make_admin(), support.make_employee(), support.make_employee()
    note, foreign = _notification(target), _notification(other)
    digest = Digest.objects.create(user=target)
    Delivery.objects.create(notification=note, channel="email", state="sent")
    Delivery.objects.create(digest=digest, channel="email", state="skipped", reason="user_dismissed")
    kept = Delivery.objects.create(notification=foreign, channel="email", state="waiting", due_at=timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        accounts.dismiss(target, actor=admin)
    assert Notification.objects.filter(pk=note.pk).exists() and Digest.objects.filter(pk=digest.pk).exists()
    with django_capture_on_commit_callbacks(execute=True):
        accounts.rehire(target, actor=admin)
    assert not Notification.objects.filter(user=target).exists()
    assert not Digest.objects.filter(user=target).exists()
    assert not Delivery.objects.filter(notification_id=note.pk).exists() and not Delivery.objects.filter(
        digest_id=digest.pk).exists(), "доставки ушли каскадом"
    assert Notification.objects.filter(pk=foreign.pk).exists() and Delivery.objects.filter(pk=kept.pk).exists()
    _no_subscriber_errors(caplog)


# --- письма ядра и записи безопасности -------------------------------------------------------------------------

def test_core_mails_new_device_password_and_second_factor_are_unchanged(
        bus, mailpit, django_capture_on_commit_callbacks):
    """FR-313, FR-305: письма ядра `new_device`, `password_changed`, `second_factor_reset` уходят теми же вызовами, что
    в срезе 001: по одному письму адресату, тема и текст прежние; рядом с каждым — своё событие шины."""
    from apps.core.services import accounts
    from tests.support_mail import deliver

    bus.listen("core.new_device", "core.password_changed", "core.second_factor_reset")
    admin = support.make_admin()
    walker, changer, lost = support.make_employee(), support.make_employee(), support.make_employee()
    support.logged_in(walker, ip="198.51.100.136")
    changer_client = support.logged_in(changer, ip="198.51.100.137")
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(walker, ip="198.51.100.138", ua=support.CHROME_UA)
        assert _change_password(changer_client, changer).status_code == 302
        accounts.reset_second_factor(lost, actor=admin)
    deliver()
    expected = {"new_device": (walker, "core.new_device", "с нового устройства"),
                "password_changed": (changer, "core.password_changed", "изменён"),
                "second_factor_reset": (lost, "core.second_factor_reset", "сброшен")}
    for template, (user, event, ending) in expected.items():
        rows = support.mails(to=user.email, template=template)
        assert rows.count() == 1, template
        row = rows.get()
        assert row.related_user_id == user.pk and row.status == "sent"
        assert row.subject.endswith(ending), f"{template}: тема письма изменилась"
        assert [c["user_id"] for c in bus.calls(event)] == [user.pk], f"{template}: нет события рядом с письмом"
    body = mailpit.wait_for(walker.email)["Text"]
    assert "Chrome" in body and "Windows" in body and "198.51.100.138" in body, "письмо о новом устройстве"
    assert support.mails(to=admin.email).count() == 0


def test_blocking_invitation_and_recovery_link_publish_no_notification_event(
        bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-313, FR-305: приглашение, ссылка восстановления пароля, блокировка и разблокировка — только письма ядра: ни
    событий ядра для уведомлений, ни записей на портале."""
    from apps.core.services import accounts, links

    bus_spy.listen(*CORE_EVENTS)
    admin, member = support.make_admin(), support.make_employee()
    invited = support.make_employee(state="invited", totp=False)
    support.logged_in(member, ip="198.51.100.139")
    with django_capture_on_commit_callbacks(execute=True):
        accounts.resend_invitation(invited, actor=admin)
        links.request_password_reset(member.email, ip="198.51.100.140")
        accounts.block(member, "проверка", actor=admin)
        accounts.unblock(member, actor=admin)
    assert bus_spy.all() == [], "событий ядра нет"
    assert support.mails(to=invited.email, template="invitation").count() == 1
    assert support.mails(to=member.email, template="password_reset").count() == 1
    assert model("notify.Notification").objects.filter(user__in=[admin, member, invited]).count() == 0
    _no_subscriber_errors(caplog)


def test_security_events_create_portal_record_without_deliveries(
        bots_on, webpush_on, caplog, django_capture_on_commit_callbacks):
    """FR-305, FR-313: события безопасности создают запись на портале (вид, текст, ссылка `/me/security/`) и ни одной
    доставки, ни сводки — даже при включённых каналах; первый вход записи не создаёт."""
    from apps.core.services import accounts, devices

    Notification = model("notify.Notification")
    admin, user = support.make_admin(), support.make_employee()
    here = support.logged_in(user, ip="198.51.100.141")
    assert not Notification.objects.filter(user=user).exists(), "первое устройство записи не даёт"
    # Прямая запись в обход сервисов (виды `mandatory` сервисы в таблицы не пишут): все внешние каналы отмечены
    # и в значениях по умолчанию, и в таблице сотрудника; доставок нет всё равно (§ 6.7 `create`).
    all_external = ["email", "push", "telegram", "max"]
    security_kinds = ["core.new_device", "core.password_changed", "core.second_factor_reset"]
    updated = model("notify.NotifySettings").objects.filter(pk=1).update(defaults={k: all_external for k in security_kinds})
    assert updated == 1, "строку NotifySettings(pk=1) создаёт миграция данных (CONTRACT-004 § 2.3)"
    model("notify.UserNotifySettings").objects.update_or_create(
        user=user, defaults={"matrix": {k: all_external for k in security_kinds}})
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.142", ua=support.CHROME_UA)
        assert _change_password(here, user).status_code == 302
        accounts.reset_second_factor(user, actor=admin)
    rows = {n.kind: n for n in Notification.objects.filter(user=user)}
    assert set(rows) == {"core.new_device", "core.password_changed", "core.second_factor_reset"}
    browser, _ = devices.parse_user_agent(support.CHROME_UA)
    assert rows["core.new_device"].text.startswith("Вход с нового устройства (") and browser in rows[
        "core.new_device"].text
    assert rows["core.password_changed"].text == "Пароль изменён"
    assert rows["core.second_factor_reset"].text == "Второй фактор сброшен"
    for note in rows.values():
        assert note.url == SECURITY_URL and note.object_ref == "" and note.read_at is None
    assert not model("notify.Delivery").objects.exists(), "доставок у видов безопасности нет"
    assert not model("notify.Digest").objects.exists()
    _no_subscriber_errors(caplog)
