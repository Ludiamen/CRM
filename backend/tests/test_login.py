"""T-109: вход (FR-021, FR-034, FR-035, FR-039, FR-043). Сценарии 4, 9, 11."""
import re
import socket
import statistics
import sys
import time
from unittest import mock
from urllib.parse import urlsplit

import pytest
from django.conf import settings

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db


def bad_login(email, ip, password=None, **kwargs):
    return support.make_client(ip=ip, **kwargs).post("/login/", {"email": email, "password": password or factories.new_password()})


def test_login_same_message_for_unknown_wrong_password_blocked():
    """FR-034 (сценарий 4.3, 9.1, 15.2): неизвестная почта, неверный пароль, заблокированная и заблокированная по перебору запись неотличимы."""
    known = support.make_employee()
    blocked = support.make_employee(state="blocked")
    brute = support.make_employee()
    responses = [
        bad_login(factories.new_email("ghost"), "198.51.100.230"),
        bad_login(known.email, "198.51.100.231"),
        support.make_client(ip="198.51.100.232").post("/login/", {"email": blocked.email, "password": blocked.test_password}),
    ]
    for i in range(5):
        bad_login(brute.email, f"198.51.100.{233 + i}")
    responses.append(support.make_client(ip="198.51.100.238").post(
        "/login/", {"email": brute.email, "password": brute.test_password}))
    assert all(r.status_code == 200 for r in responses)
    assert support.same_failure(*responses)
    text = responses[0].content.decode().lower()
    assert not any(word in text for word in ("заблокирован", "не найден", "не существует", "неверный пароль", "неверная почта"))


def test_unknown_account_runs_dummy_hash_timing_comparable():
    """FR-034: для несуществующей записи выполняется холостая проверка хеша — время ответа сопоставимо с настоящей."""
    known = [support.make_employee() for _ in range(4)]
    for u in known[:1]:  # прогрев: первый вызов хешера дороже остальных
        bad_login(u.email, "198.51.100.239")
    existing, missing = [], []
    for i in range(4):
        start = time.perf_counter()
        bad_login(known[i].email, f"198.51.100.{240 + i}")
        existing.append(time.perf_counter() - start)
        start = time.perf_counter()
        bad_login(factories.new_email("ghost"), f"198.51.100.{244 + i}")
        missing.append(time.perf_counter() - start)
    ratio = statistics.median(missing) / statistics.median(existing)
    assert 0.5 < ratio < 2.0, f"время для несуществующей записи отличается в {ratio:.2f} раза"


def test_login_two_steps_password_then_code():
    """FR-021 (сценарий 4.1, 4.4): сначала почта и пароль, затем код; после входа возврат на запрошенную страницу."""
    admin = support.make_admin()
    client = support.make_client(ip="198.51.100.250")
    gate = client.get("/staff/")
    assert gate.status_code == 302 and gate["Location"].startswith("/login/") and "next=" in gate["Location"]
    first = client.post(gate["Location"], {"email": admin.email, "password": admin.test_password})
    assert first.status_code == 302 and first["Location"].endswith("/login/code/")
    assert client.get("/staff/").status_code == 302
    assert not model("core.LoginAttempt").objects.filter(user=admin, result="success").exists(), "вход ещё не завершён"
    second = client.post("/login/code/", {"code": support.current_code(admin)})
    assert second.status_code == 302 and second["Location"] == "/staff/"
    assert model("core.LoginAttempt").objects.filter(user=admin, result="success").count() == 1
    assert model("core.UserSession").objects.filter(user=admin).count() == 1
    assert "login.success" in support.audit_actions(object_id=str(admin.pk))
    outsider = support.make_client(ip="198.51.100.251")
    outsider.post("/login/?next=https://evil.example/path", {"email": admin.email, "password": admin.test_password})
    final = outsider.post("/login/code/", {"code": support.current_code(admin)})
    assert final.status_code == 302 and "evil.example" not in final["Location"]


def test_every_attempt_recorded_with_time_device_browser_platform_ip_result(clock):
    """FR-039: каждая попытка — время, адрес, браузер, платформа, устройство (при успехе), результат."""
    Attempt = model("core.LoginAttempt")
    user = support.make_employee()
    ip, ua = "198.51.100.252", support.FIREFOX_UA
    client = support.make_client(ip=ip, ua=ua)
    bad_login(factories.new_email("ghost"), ip, ua=ua)
    client.post("/login/", {"email": user.email, "password": factories.new_password()})
    support.post_password(client, user)
    client.post("/login/code/", {"code": "000000"})
    support.post_password(client, user)
    client.post("/login/code/", {"code": support.current_code(user)})
    rows = list(Attempt.objects.order_by("id"))
    assert [r.result for r in rows] == ["bad_password", "bad_password", "bad_code", "success"]
    assert [r.user_id for r in rows] == [None, user.pk, user.pk, user.pk]
    for row in rows:
        assert row.ip == ip and row.at == clock._now
        assert "Firefox" in row.browser and "Linux" in row.platform
    assert rows[-1].device is not None and "Firefox" in rows[-1].device.browser
    assert {c[0] for c in Attempt._meta.get_field("result").choices} >= {
        "success", "bad_password", "bad_code", "locked", "ip_locked", "backup_code"}


def test_login_history_is_always_on_no_setting_disables_it():
    """FR-039 (сценарий 11.2): история включена с первого дня и не отключается — есть только срок хранения."""
    names = {f.name for f in model("core.SecuritySettings")._meta.get_fields()}
    assert "login_history_days" in names
    assert not [n for n in names if re.search(r"history_(enabled|on|off)|record_login|log_login|track", n)]
    admin = support.logged_in(support.make_admin(), ip="198.51.100.253")
    page = admin.get("/settings/security/").content.decode()
    fields = set(re.findall(r'name="(\w*history\w*)"', page))
    assert fields == {"password_history", "login_history_days"}, f"в форме лишние поля истории: {fields}"
    support.post_security_settings(admin, login_history_days=1)
    user = support.make_employee()
    support.login(support.make_client(ip="198.51.100.254"), user)
    assert model("core.LoginAttempt").objects.filter(user=user, result="success").count() == 1
    assert support.audit_actions(object_id=str(user.pk)).count("login.success") == 1


def test_no_geolocation_fields_or_lookups():
    """FR-043: геопозиция не собирается: ни полей, ни библиотек, ни обращений к внешним службам."""
    forbidden = re.compile(r"country|city|geo|latitude|longitude|\blat\b|\blon\b|location|region|timezone", re.I)
    for label in ("core.User", "core.LoginAttempt", "core.KnownDevice", "core.UserSession"):
        names = [f.name for f in model(label)._meta.get_fields()]
        assert not [n for n in names if forbidden.search(n)], f"{label}: поля геопозиции {names}"
    assert not {"geoip2", "maxminddb", "geoip", "GeoIP"} & set(sys.modules)
    resolved = []
    real = socket.getaddrinfo

    def spy(host, *args, **kwargs):
        resolved.append(host)
        return real(host, *args, **kwargs)

    user = support.make_employee()
    with mock.patch("socket.getaddrinfo", side_effect=spy):
        support.login(support.make_client(ip="8.8.8.8"), user)
        bad_login(factories.new_email("ghost"), "1.1.1.1")
    own = {settings.EMAIL_HOST, "localhost", "127.0.0.1", urlsplit(settings.VALKEY_URL).hostname}
    assert not [h for h in resolved if h not in own], f"вход обращался к посторонним адресам: {resolved}"


def test_success_resets_failure_counter():
    """FR-035 (сценарий 9.3): успешный вход обнуляет серию неудач."""
    user = support.make_employee()
    for _ in range(4):
        bad_login(user.email, "198.51.100.255")
    assert support.valkey_int(f"fail:acct:{user.pk}") == 4
    support.login(support.make_client(ip="198.51.100.255"), user)
    assert support.valkey_int(f"fail:acct:{user.pk}") == 0
    for _ in range(4):
        bad_login(user.email, "198.51.100.255")
    assert not support.valkey_key(f"lock:acct:{user.pk}"), "серия началась заново, четыре неудачи не блокируют"
    support.login(support.make_client(ip="198.51.100.255"), user)
    for _ in range(5):
        bad_login(user.email, "198.51.100.255")
    assert support.valkey_key(f"lock:acct:{user.pk}")
