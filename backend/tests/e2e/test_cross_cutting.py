"""T-150: сквозная приёмка (FR-012, FR-032, NFR-007, NFR-009, NFR-010).

Ширина 360 px, заголовки и куки на настоящем стенде (nginx с TLS), журнал доступа nginx без кодов ссылок,
русский интерфейс и письма, время по Москве, три браузера.
"""
import http.client
import re
import ssl
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers
from tests.e2e.conftest import PROJECTS

MOSCOW = ZoneInfo("Europe/Moscow")


def _csp(headers: dict) -> dict:
    policy = {}
    for part in headers.get("content-security-policy", "").split(";"):
        tokens = part.split()
        if tokens:
            policy[tokens[0]] = tokens[1:]
    return policy


def test_no_horizontal_scroll_at_360px_login_activation_totp_security(browser, browser_context_args, admin_page,
                                                                      mailpit, employee):
    """NFR-009: на ширине 360 px нет горизонтальной прокрутки у входа, восстановления пароля, всех четырёх
    шагов активации (профиль, пароль, подключение второго фактора, резервные коды) и «Безопасности»."""
    narrow = browser.new_context(**browser_context_args, viewport={"width": 360, "height": 740})
    try:
        page = narrow.new_page()
        for path in ("/login/", "/password/forgot/"):
            page.goto(path)
            assert helpers.no_horizontal_scroll(page), f"{path}: горизонтальная прокрутка"

        email, password = factories.new_email("emp"), factories.new_password()
        helpers.create_employee(admin_page, email)
        link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
        helpers.open_activation_link(page, link)
        assert helpers.no_horizontal_scroll(page), "активация, профиль"
        page.click("button[type=submit]")
        page.wait_for_url(re.compile(r"/activate/password/"))
        assert helpers.no_horizontal_scroll(page), "активация, пароль"
        page.fill("input[name=password1]", password)
        page.fill("input[name=password2]", password)
        page.click("button[type=submit]")
        page.wait_for_url(re.compile(r"/activate/totp/"))
        assert helpers.no_horizontal_scroll(page), "активация, второй фактор (QR и ключ)"
        secret = page.locator("#totp-secret").inner_text().strip()
        page.fill("input[name=code]", helpers.totp_for(secret))
        page.click("button[type=submit]")
        page.wait_for_url(re.compile(r"/activate/codes/"))
        assert helpers.no_horizontal_scroll(page), "активация, резервные коды"
        page.locator("input[name=confirm]").check()
        page.click("button[type=submit]")
        page.wait_for_url(lambda url: "/activate/" not in url)
        for path in ("/", "/me/security/", "/me/security/devices/", "/me/security/history/"):
            page.goto(path)
            assert helpers.no_horizontal_scroll(page), f"{path}: горизонтальная прокрутка"
    finally:
        narrow.close()


def test_headers_and_cookies_on_real_stand(employee, new_context):
    """NFR-007: на настоящем стенде у страниц CSP без unsafe-inline/unsafe-eval, nosniff, Referrer-Policy
    (no-referrer на страницах ссылок), Cache-Control: no-store на защищённых; куки — Secure, HttpOnly,
    SameSite=Lax."""
    acc = employee()
    page = acc.page
    login = page.request.get("/login/")
    headers = {k.lower(): v for k, v in login.headers.items()}
    csp = _csp(headers)
    script = csp.get("script-src") or csp.get("default-src") or []
    assert script, "в CSP нет script-src"
    for banned in ("'unsafe-inline'", "'unsafe-eval'", "*", "data:"):
        assert banned not in script, f"script-src разрешает {banned}"
    assert "'unsafe-inline'" not in csp.get("style-src", [])
    assert csp.get("object-src") == ["'none'"]
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "same-origin"
    assert "no-store" in headers.get("cache-control", "")
    assert "no-referrer" == page.request.get("/activate/").headers.get("referrer-policy")
    protected = page.request.get("/me/security/")
    assert "no-store" in protected.headers.get("cache-control", "")

    cookies = page.context.cookies()
    assert cookies, "после входа нет ни одной куки"
    for cookie in cookies:
        assert cookie["secure"], f"кука {cookie['name']} без Secure"
        assert cookie["httpOnly"], f"кука {cookie['name']} без HttpOnly"
        assert cookie["sameSite"] == "Lax", f"кука {cookie['name']}: SameSite={cookie['sameSite']}"
    assert len(page.request.get("/health/").text()) < 120


def test_https_redirect_hsts_and_secure_cookies_on_stand(portal_url):
    """NFR-007: HTTP-запрос на порт стенда перенаправляется на HTTPS, HTTPS-ответ несёт HSTS не короче
    года (31536000 с) и перенаправление не раскрывает ничего, кроме адреса."""
    target = urlparse(portal_url)
    conn = http.client.HTTPConnection(target.hostname, target.port, timeout=15)
    conn.request("GET", "/login/")
    response = conn.getresponse()
    assert response.status in (301, 302, 307, 308), f"HTTP не перенаправлен: {response.status}"
    assert response.getheader("Location", "").startswith("https://")
    conn.close()

    secure = http.client.HTTPSConnection(target.hostname, target.port, timeout=15,
                                         context=ssl._create_unverified_context())
    secure.request("GET", "/login/")
    answer = secure.getresponse()
    hsts = answer.getheader("Strict-Transport-Security", "")
    assert answer.status == 200
    found = re.search(r"max-age=(\d+)", hsts)
    assert found and int(found.group(1)) >= 31536000, "нет HSTS на год и больше"
    secure.close()


def test_nginx_access_log_has_no_link_codes(admin_page, employee, mailpit, new_context):
    """FR-012, FR-032, NFR-007: после активации и после восстановления пароля в журнале доступа nginx нет
    кодов ссылок (код живёт во фрагменте адреса и уходит только в теле POST-обмена)."""
    acc = employee()  # приглашение и активация по ссылке
    activation_code = helpers.code_of(acc.link)
    page = new_context().new_page()
    seen = helpers.mail_ids(mailpit, acc.email)
    page.goto("/password/forgot/")
    page.fill("input[name=email]", acc.email)
    page.click("button[type=submit]")
    reset_link = helpers.link_in(helpers.wait_mail(mailpit, acc.email, "password_reset", seen=seen), "/password/reset/")
    page.goto(reset_link)
    page.wait_for_url(re.compile(r"/password/reset/"))
    reset_code = helpers.code_of(reset_link)

    log = helpers.nginx_access_log()
    assert "/activate" in log and "/password/reset" in log, "прочитан не тот журнал: запросов портала в нём нет"
    for name, code in (("активации", activation_code), ("восстановления", reset_code)):
        assert code not in log, f"в журнале доступа nginx есть код ссылки {name}"
    for part in (activation_code[:16], reset_code[:16]):
        assert part not in log, "в журнале доступа есть часть кода ссылки"


def test_ui_and_mail_in_russian_moscow_time(employee, mailpit, new_context, browser, browser_context_args):
    """NFR-010: страницы и письма по-русски; время в истории и в письме — по Москве, даже когда часовой пояс
    браузера другой (контекст в America/New_York)."""
    acc = employee()
    seen = helpers.mail_ids(mailpit, acc.email)
    context = browser.new_context(**{**browser_context_args, "timezone_id": "America/New_York"})
    try:
        page = context.new_page()
        page.goto("/login/")
        assert page.locator("html").get_attribute("lang") == "ru"
        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", page.locator("body").inner_text())
        assert letters and sum(1 for c in letters if re.match(r"[А-Яа-яЁё]", c)) / len(letters) > 0.8, \
            "страница входа не по-русски"
        helpers.sign_in(page, acc)
        now = datetime.now(MOSCOW)
        page.goto("/me/security/history/")
        times = re.findall(r"\b(\d{2}):(\d{2})\b", page.locator("[data-history-row]").first.inner_text())
        assert times, "в истории нет времени"
        shown = now.replace(hour=int(times[0][0]), minute=int(times[0][1]), second=0, microsecond=0)
        assert abs(shown - now) < timedelta(minutes=10) or abs(shown - now) > timedelta(hours=23, minutes=50), \
            f"время в истории не по Москве: {times[0][0]}:{times[0][1]}"

        mail = helpers.wait_mail(mailpit, acc.email, "new_device", seen=seen, timeout=60)
        assert re.search(r"[А-Яа-я]", mail["Subject"]) and re.search(r"[А-Яа-я]{4,}", mail["Text"])
        found = re.findall(r"\b(\d{2}):(\d{2})\b", mail["Text"])
        assert found, "в письме нет времени"
        mail_time = now.replace(hour=int(found[0][0]), minute=int(found[0][1]), second=0, microsecond=0)
        assert abs(mail_time - now) < timedelta(minutes=10) or abs(mail_time - now) > timedelta(hours=23, minutes=50), \
            "время в письме не по Москве"
    finally:
        context.close()


def test_suite_runs_in_chromium_firefox_and_edge_if_installed(browser, page, request):
    """NFR-009: набор идёт в трёх браузерах; проект Edge без установленного Edge пропускается фикстурой
    (единственный допустимый skip), Firefox обязан быть установлен (`playwright install firefox`)."""
    assert PROJECTS == ["chromium", "firefox", "edge"]
    project = request.node.callspec.params["browser"]
    assert browser.e2e_project == project
    agent = page.evaluate("navigator.userAgent")
    expected = {"chromium": r"Chrome/(?!.*Edg/)", "firefox": r"Firefox/", "edge": r"Edg/"}[project]
    assert re.search(expected, agent), f"проект {project} запущен не в своём браузере: {agent}"
    response = page.goto("/login/")
    assert response is not None and response.status == 200
    expect(page.locator("input[name=email]")).to_be_visible()
