"""T-111: устройства и история входов (FR-039…042, NFR-007). Сценарии 5 и 11."""
import re
from datetime import datetime, timedelta, timezone as tz

import pytest

from tests import factories, support
from tests.support import model
from tests.support_mail import deliver, device_cookie_names

pytestmark = pytest.mark.django_db

DEVICES, HISTORY = "/me/security/devices/", "/me/security/history/"


def close_url(device) -> str:
    return f"{DEVICES}{device.pk}/close/"


def forget_url(device) -> str:
    return f"{DEVICES}{device.pk}/forget/"


def device_of(client_user, ua_word):
    return model("core.KnownDevice").objects.get(user=client_user, browser__contains=ua_word)


def new_device_mails(user):
    return support.mails(to=user.email, template="new_device").count()


def test_known_devices_list_for_owner_only(clock):
    """FR-040, FR-039 (сценарий 11.1): сотрудник видит свои устройства и свою историю (с неудачами, по убыванию), чужих — нет."""
    mine, other = support.make_employee(), support.make_employee()
    ip_ff, ip_ch, ip_bad, ip_other = "198.51.100.61", "198.51.100.62", "198.51.100.63", "198.51.100.64"
    first = support.logged_in(mine, ip=ip_ff)
    clock.advance(minutes=5)
    support.logged_in(mine, ip=ip_ch, ua=support.CHROME_UA)
    clock.advance(minutes=5)
    support.make_client(ip=ip_bad).post("/login/", {"email": mine.email, "password": factories.new_password()})
    support.logged_in(other, ip=ip_other)
    page = first.get(DEVICES)
    assert page.status_code == 200
    html = page.content.decode()
    for word in ("Firefox", "Chrome", "Linux", "Windows"):
        assert word in html, f"в списке устройств нет {word}"
    KnownDevice = model("core.KnownDevice")
    own = list(KnownDevice.objects.filter(user=mine))
    assert len(own) == 2 and all(close_url(d) in html for d in own)
    foreign = KnownDevice.objects.get(user=other)
    assert close_url(foreign) not in html and forget_url(foreign) not in html
    history = first.get(HISTORY).content.decode()
    assert all(ip in history for ip in (ip_ff, ip_ch, ip_bad)) and ip_other not in history
    assert history.index(ip_bad) < history.index(ip_ch) < history.index(ip_ff), "по убыванию времени, неудача тоже видна"
    assert first.post(close_url(foreign)).status_code in (403, 404)
    assert first.post(forget_url(foreign)).status_code in (403, 404)
    assert KnownDevice.objects.filter(pk=foreign.pk).exists()
    anonymous = support.make_client(ip="198.51.100.65")
    for path in (DEVICES, HISTORY):
        got = anonymous.get(path)
        assert got.status_code == 302 and "/login/" in got["Location"]


def test_close_session_and_forget_device(clock):
    """FR-040 (сценарий 11.3): «Закрыть сессию» завершает сессию устройства, следующий вход с него — снова новое устройство; «Забыть» убирает устройство."""
    user = support.make_employee()
    here = support.logged_in(user, ip="198.51.100.66")
    there = support.logged_in(user, ip="198.51.100.67", ua=support.CHROME_UA)
    assert new_device_mails(user) == 1, "письмо только о втором устройстве"
    chrome = device_of(user, "Chrome")
    done = here.post(close_url(chrome))
    assert done.status_code == 302
    got = there.get("/me/")
    assert got.status_code == 302 and "/login/" in got["Location"], "сессия закрытого устройства завершена"
    assert here.get("/me/").status_code == 200, "своя сессия остаётся"
    assert not model("core.UserSession").objects.filter(device=chrome).exists()
    support.login(there, user, REMOTE_ADDR="198.51.100.67")
    assert new_device_mails(user) == 2, "после закрытия сессии вход с него — снова новое устройство"
    firefox = device_of(user, "Firefox")
    assert here.post(forget_url(firefox)).status_code == 302
    assert not model("core.KnownDevice").objects.filter(pk=firefox.pk).exists()
    assert str(firefox.pk) not in "".join(re.findall(r"/devices/(\d+)/", here.get(DEVICES).content.decode()))
    here.post("/logout/")
    support.login(here, user)
    assert new_device_mails(user) == 3, "забытое устройство при входе снова новое"


def test_new_device_mail_has_time_browser_platform_ip_and_advice(clock, mailpit, django_capture_on_commit_callbacks):
    """FR-041 (сценарий 5.1, 5.4): письмо — время (Europe/Moscow), браузер, платформа, адрес IP, указание закрыть сессию и сменить пароль; ссылок без входа нет."""
    clock.set(datetime(2026, 10, 1, 21, 30, tzinfo=tz.utc))  # 00:30 2 октября по Москве
    user = support.make_employee()
    support.logged_in(user, ip="198.51.100.68")
    assert new_device_mails(user) == 0
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="203.0.113.68", ua=support.CHROME_UA)
    deliver()
    body = mailpit.wait_for(user.email)["Text"]
    for expected in ("Chrome", "Windows", "203.0.113.68", "00:30"):
        assert expected in body, f"в письме нет {expected!r}"
    assert "02.10.2026" in body or "2 октября 2026" in body
    lowered = body.lower()
    assert "закр" in lowered and "парол" in lowered, "нет указания, что делать"
    assert not re.search(r"/(activate|password/reset)/", body), "в письме о входе нет ссылок, действующих без входа"
    assert user.test_password not in body


def test_no_new_device_mail_on_first_login_after_activation():
    """FR-041 (сценарий 5.3): первый вход после активации письма не шлёт; устройство запоминается как первое; второе устройство — шлёт."""
    user = support.make_employee(state="invited", totp=False, roles=[support.role_by_name(support.STAFF_ROLE)])
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.69")
    assert client.post("/activate/exchange/", {"code": code}).status_code == 302
    client.post("/activate/profile/", {"phone": "+7 900 000-00-00", "contacts": ""})
    password = factories.new_password()
    client.post("/activate/password/", {"password1": password, "password2": password})
    key, _ = support.enroll_totp(client, user, totp_url="/activate/totp/", codes_url="/activate/codes/")
    user.test_password = password
    assert model("core.KnownDevice").objects.filter(user=user).count() == 1, "устройство активации запомнено как первое"
    assert new_device_mails(user) == 0
    client.post("/logout/")
    support.login(client, user)
    assert new_device_mails(user) == 0, "то же устройство — не новое"
    support.login(support.make_client(ip="198.51.100.70", ua=support.CHROME_UA), user)
    assert new_device_mails(user) == 1


def test_admin_sees_devices_and_history_only_with_view_logins():
    """FR-042 (сценарий 11.4): устройства и входы сотрудника видны только с правом accounts.view_logins."""
    target = support.make_employee()
    support.logged_in(target, ip="198.51.100.71")
    support.make_client(ip="198.51.100.72").post("/login/", {"email": target.email, "password": factories.new_password()})
    url = f"/staff/{target.pk}/logins/"
    viewer = support.logged_in(support.make_with_permissions("accounts.view_logins"), ip="198.51.100.73")
    html = viewer.get(url).content.decode()
    assert viewer.get(url).status_code == 200
    assert "198.51.100.71" in html and "198.51.100.72" in html and "Firefox" in html
    manager = support.logged_in(support.make_with_permissions("accounts.manage"), ip="198.51.100.74")
    assert manager.get(url).status_code == 403
    card = manager.get(f"/staff/{target.pk}/").content.decode()
    assert "198.51.100.71" not in card, "карточка без права не раскрывает входы"
    admin = support.logged_in(support.make_admin(), ip="198.51.100.75")
    assert "198.51.100.71" in admin.get(url).content.decode()


def test_history_cleanup_cron_removes_entries_older_than_retention(clock):
    """FR-039 (сценарий 11.5): ночное задание удаляет записи истории старше login_history_days; события журнала остаются."""
    from apps.core.services.retention import purge_login_history

    Attempt, Audit = model("core.LoginAttempt"), model("core.AuditEvent")
    user = support.make_employee()
    now = clock._now
    for days, ip in ((400, "198.51.100.80"), (366, "198.51.100.81"), (364, "198.51.100.82")):
        clock.set(now - timedelta(days=days))
        support.make_client(ip=ip).post("/login/", {"email": user.email, "password": factories.new_password()})
    clock.set(now)
    audit_before = Audit.objects.filter(action="login.failed").count()
    assert Attempt.objects.count() == 3 and audit_before == 3
    assert purge_login_history() == 2
    assert list(Attempt.objects.values_list("ip", flat=True)) == ["198.51.100.82"]
    assert Audit.objects.filter(action="login.failed").count() == 3, "журнал событий о входах хранится дольше"
    support.set_security(login_history_days=30)
    assert purge_login_history() == 1 and not Attempt.objects.exists(), "срок берётся из настройки"


def test_device_cookie_httponly_and_hash_only_stored():
    """FR-040, NFR-007: кука устройства HttpOnly, Secure, SameSite=Lax, долгоживущая; в базе только хеш её значения."""
    user = support.make_employee()
    client = support.logged_in(user, ip="198.51.100.83")
    names = device_cookie_names(client)
    assert len(names) == 1, f"ожидали одну куку устройства, есть {names}"
    cookie = client.cookies[names[0]]
    assert cookie["httponly"] and cookie["secure"] and cookie["samesite"] == "Lax"
    assert int(cookie["max-age"] or 0) >= 30 * 24 * 3600, "кука долгоживущая"
    value = cookie.value
    device = model("core.KnownDevice").objects.get(user=user)
    assert re.fullmatch(r"[0-9a-f]{64}", device.device_key_hash) and device.device_key_hash != value
    stored = " ".join(str(getattr(device, f.name)) for f in device._meta.concrete_fields)
    assert value not in stored
    again = support.make_client(ip="198.51.100.84")
    again.cookies[names[0]] = value
    support.login(again, user)
    assert model("core.KnownDevice").objects.filter(user=user).count() == 1, "кука узнаёт устройство"
