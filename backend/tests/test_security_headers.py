"""T-116: заголовки, куки, кэш и утечки в адресе (FR-012, FR-046, NFR-007, NFR-010)."""
import json
import re
from datetime import datetime, timezone as tz

import pytest

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db

HTTPS = {"HTTP_X_FORWARDED_PROTO": "https"}


def csp(response) -> dict[str, list[str]]:
    header = response.get("Content-Security-Policy", "")
    assert header, "нет заголовка Content-Security-Policy"
    policy = {}
    for part in header.split(";"):
        tokens = part.split()
        if tokens:
            policy[tokens[0]] = tokens[1:]
    return policy


def test_csp_has_no_unsafe_inline_or_unsafe_eval_for_scripts():
    """NFR-007: CSP — свои скрипты, без 'unsafe-inline' и 'unsafe-eval' (и стили без inline), на анонимных и защищённых страницах."""
    client = support.logged_in(support.make_admin(), ip="198.51.100.170")
    for response in (support.make_client().get("/login/", **HTTPS), client.get("/me/", **HTTPS), client.get("/staff/", **HTTPS)):
        policy = csp(response)
        script = policy.get("script-src") or policy.get("default-src")
        assert script and "'self'" in script
        assert not {"'unsafe-inline'", "'unsafe-eval'", "*", "data:"} & set(script), script
        assert "'unsafe-inline'" not in policy.get("style-src", policy.get("default-src", []))
        assert not any(src.startswith(("http:", "https:")) for src in script), "скрипты только свои (без CDN)"
        assert "'none'" in policy.get("object-src", []) or "'none'" in policy.get("default-src", [])


def test_htmx_config_disables_eval_and_indicator_styles():
    """NFR-007: HTMX без eval и без своих <style> для индикаторов (иначе их заблокирует CSP)."""
    html = support.make_client().get("/login/").content.decode()
    meta = re.search(r'<meta[^>]+name="htmx-config"[^>]+content=\'?"?([^>]+?)\'?"?\s*/?>', html)
    assert meta, "нет <meta name=\"htmx-config\">"
    config = json.loads(meta.group(1).replace("&quot;", '"'))
    assert config["allowEval"] is False and config["includeIndicatorStyles"] is False
    assert "hx-on" not in html


def test_hsts_nosniff_referrer_policy_headers():
    """NFR-007: HSTS на год и дольше, nosniff, Referrer-Policy same-origin, защита от встраивания."""
    got = support.make_client().get("/login/", **HTTPS)
    assert got.status_code == 200, "страница входа должна открываться"
    hsts = got["Strict-Transport-Security"]
    assert int(re.search(r"max-age=(\d+)", hsts).group(1)) >= 31536000
    assert got["X-Content-Type-Options"] == "nosniff"
    assert got["Referrer-Policy"] == "same-origin"
    assert got.get("X-Frame-Options", "").upper() in ("DENY", "SAMEORIGIN") or "frame-ancestors" in got.get("Content-Security-Policy", "")


def test_link_pages_send_no_referrer():
    """FR-012, NFR-007: страницы ссылок (активация, восстановление) и ответы обмена — Referrer-Policy: no-referrer."""
    user = support.make_employee(state="invited", totp=False)
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.171")
    assert client.get("/activate/")["Referrer-Policy"] == "no-referrer"
    exchange = client.post("/activate/exchange/", {"code": code})
    assert exchange["Referrer-Policy"] == "no-referrer"
    assert client.get("/activate/profile/")["Referrer-Policy"] == "no-referrer"
    active = support.make_employee()
    reset_link, reset_code = factories.make_link(active, "reset")
    other = support.make_client(ip="198.51.100.172")
    assert other.post("/password/reset/exchange/", {"code": reset_code})["Referrer-Policy"] == "no-referrer"
    assert other.get("/password/reset/")["Referrer-Policy"] == "no-referrer"


def test_no_store_on_protected_and_secret_pages():
    """NFR-007 (сценарий 10, п. 5): защищённые страницы и страницы с вводом секретов — Cache-Control: no-store."""
    admin = support.logged_in(support.make_admin(), ip="198.51.100.173")
    for path in ("/me/", "/me/security/", "/me/security/password/", "/staff/", "/audit/", "/settings/security/", "/roles/"):
        assert "no-store" in admin.get(path).get("Cache-Control", ""), path
    anonymous = support.make_client(ip="198.51.100.174")
    for path in ("/login/", "/password/forgot/", "/activate/"):
        assert "no-store" in anonymous.get(path).get("Cache-Control", ""), path
    user = support.make_employee()
    step = support.make_client(ip="198.51.100.175")
    support.post_password(step, user)
    assert "no-store" in step.get("/login/code/").get("Cache-Control", "")
    fresh = support.make_employee(state="invited", totp=False)
    link, code = factories.make_link(fresh, "activation")
    wizard = support.make_client(ip="198.51.100.176")
    wizard.post("/activate/exchange/", {"code": code})
    for path in ("/activate/profile/", "/activate/password/"):
        assert "no-store" in wizard.get(path).get("Cache-Control", ""), path
    after = support.logged_in(support.make_employee(), ip="198.51.100.177")
    after.post("/logout/")
    assert after.get("/me/").status_code == 302


def test_session_csrf_device_cookies_secure_httponly_samesite_lax():
    """NFR-007: сессия, CSRF и кука устройства — Secure, HttpOnly, SameSite=Lax."""
    client = support.make_client(ip="198.51.100.178")
    client.get("/login/", **HTTPS)
    user = support.make_employee()
    support.login(client, user)
    names = set(client.cookies)
    assert len(names) >= 3, f"ожидали сессию, CSRF и устройство: {names}"
    for name, cookie in client.cookies.items():
        assert cookie["secure"] and cookie["httponly"] and cookie["samesite"] == "Lax", f"кука {name}"


def test_no_secret_or_code_in_any_url_or_redirect():
    """FR-012, FR-046: ни код ссылки, ни пароль, ни код TOTP не появляются в адресе, перенаправлении или теле ответа; GET с кодом код не принимает."""
    user = support.make_employee(state="invited", totp=False, roles=[support.role_by_name(support.STAFF_ROLE)])
    link, code = factories.make_link(user, "activation")
    seen = []

    def watch(response, path):
        seen.append((path, response.get("Location", ""), response.content.decode("utf-8", "replace")))
        return response

    client = support.make_client(ip="198.51.100.179")
    for path in (f"/activate/?code={code}", f"/activate/{code}/", f"/activate/exchange/?code={code}"):
        got = watch(client.get(path), path)
        assert got.status_code in (200, 302, 404, 405)
        assert code not in got.get("Location", "") and "/activate/profile/" not in got.get("Location", "")
    done = watch(client.post("/activate/exchange/", {"code": code}), "/activate/exchange/")
    watch(client.get(done["Location"]), done["Location"])
    password = factories.new_password()
    watch(client.post("/activate/profile/", {"phone": "+7 900 000-00-03", "contacts": ""}), "/activate/profile/")
    done = watch(client.post("/activate/password/", {"password1": password, "password2": password}), "/activate/password/")
    key, codes = support.enroll_totp(client, user, totp_url="/activate/totp/", codes_url="/activate/codes/")
    login = support.make_client(ip="198.51.100.180")
    user.test_password = password
    watch(support.post_password(login, user), "/login/")
    bad = watch(login.post("/login/code/", {"code": "000000"}), "/login/code/")
    totp = support.current_code(user)
    watch(login.post("/login/code/", {"code": totp}), "/login/code/")
    wrong = factories.new_password()
    echo = watch(support.make_client(ip="198.51.100.181").post("/login/", {"email": user.email, "password": wrong}), "/login/")
    for secret in (code, password, wrong, totp, *codes):
        for path, location, body in seen:
            assert secret not in path and secret not in location, f"секрет в адресе: {path}"
        assert secret not in echo.content.decode() and secret not in bad.content.decode()
    for path, location, body in seen:
        assert code not in body, f"{path}: код ссылки в теле ответа"


def test_time_shown_in_europe_moscow_and_ui_in_russian(clock):
    """NFR-010: время в интерфейсе — Europe/Moscow (UTC+3), язык страницы русский."""
    clock.set(datetime(2026, 10, 1, 21, 30, tzinfo=tz.utc))
    user = support.make_employee()
    client = support.logged_in(user, ip="198.51.100.182")
    html = client.get("/me/security/history/").content.decode()
    assert "00:30" in html and ("02.10.2026" in html or "2 октября 2026" in html)
    assert "21:30" not in html
    assert re.search(r'<html[^>]+lang="ru"', html)
    login = support.make_client().get("/login/").content.decode()
    assert re.search("[Вв]ход", login) and not re.search(r"\b(Sign in|Log in|Password)\b", login)
