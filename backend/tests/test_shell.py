"""T-114: оболочка портала и «Безопасность» (FR-004, FR-018, FR-048, FR-050, FR-051, NFR-007, NFR-009).

Разметка (CONTRACT.md): левое меню — `<nav id="main-menu">`, у пункта `<span class="menu-icon">` и
`<span class="menu-label">`, кнопка режима «только значки» — `data-menu-toggle`; верхняя панель —
`<header id="top-bar">`; статический скрипт оболочки хранит режим в `localStorage`.
"""
import re

import pytest

from tests import factories, support
from tests.support import HX, PERMISSIONS, make_with_permissions

pytestmark = pytest.mark.django_db

SECTIONS = {"accounts.manage": "/staff/", "roles.manage": "/roles/", "audit.view": "/audit/",
            "settings.portal": "/settings/portal/", "settings.security": "/settings/security/"}


def block(html: str, pattern: str) -> str:
    found = re.search(pattern, html, re.S)
    assert found, f"в разметке нет {pattern!r}"
    return found.group(0)


def test_left_menu_only_permitted_sections():
    """FR-050: в левом меню (nav#main-menu) только разделы по правам; у каждого — значок и подпись."""
    for permission, link in SECTIONS.items():
        html = support.logged_in(make_with_permissions(permission), ip="198.51.100.120").get("/me/").content.decode()
        menu = block(html, r'<nav[^>]*id="main-menu".*?</nav>')
        assert f'href="{link}"' in menu
        assert not [other for p, other in SECTIONS.items() if p != permission and f'href="{other}"' in menu]
        assert 'class="menu-icon' in menu and 'class="menu-label' in menu
    plain = support.logged_in(support.make_employee(), ip="198.51.100.121").get("/me/").content.decode()
    assert not [link for link in SECTIONS.values() if f'href="{link}"' in block(plain, r'<nav[^>]*id="main-menu".*?</nav>')]


def test_icon_only_mode_markup_and_script_without_inline_code():
    """FR-050, NFR-007: переключатель режима есть, режим хранится в localStorage внешним скриптом; ни inline-скриптов, ни обработчиков в атрибутах, ни style=."""
    html = support.logged_in(support.make_admin(), ip="198.51.100.122").get("/me/").content.decode()
    assert "data-menu-toggle" in html
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S)
    assert scripts and all('src="' in attrs and not body.strip() for attrs, body in scripts), "inline-скрипт под CSP недопустим"
    assert not re.search(r"\son[a-z]+\s*=", html, re.I) and not re.search(r"\sstyle\s*=", html, re.I)
    own = [m for m in re.findall(r'src="([^"]+)"', html) if "/static/" in m and "vendor/" not in m]
    assert own, "свой скрипт оболочки не подключён"
    from django.contrib.staticfiles import finders

    sources = " ".join(open(finders.find(m.split("/static/", 1)[1]), encoding="utf-8").read() for m in own)
    assert "localStorage" in sources and "menu-icons-only" in sources
    assert "eval(" not in sources and "new Function" not in sources


def test_top_bar_name_logo_and_profile_menu_items():
    """FR-050, FR-048: верхняя панель — название, логотип, меню профиля (профиль, безопасность, выход POST-формой)."""
    html = support.logged_in(support.make_employee(), ip="198.51.100.123").get("/me/").content.decode()
    bar = block(html, r'<header[^>]*id="top-bar".*?</header>')
    name = support.model("core.PortalSettings").objects.get().name
    assert name in bar and "<img" in bar
    assert 'href="/me/"' in bar and 'href="/me/security/"' in bar
    logout = block(bar, r'<form[^>]*action="/logout/"[^>]*>.*?</form>')
    assert re.search(r'method="post"', logout, re.I) and "csrfmiddlewaretoken" in logout


def test_security_page_has_password_logout_everywhere_totp_codes_devices_history():
    """FR-051: в «Безопасности» в одном месте — пароль, «выйти со всех», второй фактор, резервные коды, устройства, история."""
    client = support.logged_in(support.make_employee(), ip="198.51.100.124")
    full = client.get("/me/security/").content.decode()
    fragment = client.get("/me/security/", **HX).content.decode()
    for html in (full, fragment):
        for needle in ("/me/security/password/", "/me/security/logout-everywhere/", "/me/security/totp/",
                       "/me/security/backup-codes/", "/me/security/devices/", "/me/security/history/", "data-backup-remaining="):
            assert needle in html, f"в «Безопасности» нет {needle}"
    assert "<html" not in fragment and "<html" in full


def test_htmx_request_returns_fragment_plain_request_full_page():
    """FR-004, FR-051: ответ на HTMX-запрос — фрагмент без оболочки, обычный — полная страница."""
    admin = support.logged_in(support.make_admin(), ip="198.51.100.125")
    target = support.make_employee()
    for path in ("/staff/", f"/staff/{target.pk}/", "/me/security/", "/roles/", "/audit/", "/settings/mail-log/"):
        plain, hx = admin.get(path), admin.get(path, **HX)
        assert plain.status_code == hx.status_code == 200, path
        assert "<html" in plain.content.decode() and 'id="main-menu"' in plain.content.decode(), path
        body = hx.content.decode()
        assert "<html" not in body and "<body" not in body and 'id="main-menu"' not in body, f"{path}: HTMX получил оболочку"


def test_403_and_404_pages_without_details():
    """FR-018: отказ и неизвестный адрес — короткие страницы по-русски без путей, кодов прав, трассировок и списка маршрутов."""
    client = support.logged_in(support.make_employee(), ip="198.51.100.126")
    forbidden, missing = client.get("/staff/"), client.get("/no-such-page-xyz/")
    assert forbidden.status_code == 403 and missing.status_code == 404
    for response in (forbidden, missing):
        text = response.content.decode()
        assert re.search("[а-яА-Я]{4,}", text)
        for leak in ("Traceback", "URLconf", "Request URL", "accounts.manage", "PermissionDenied", "no-such-page-xyz", "/staff/", "Django"):
            assert leak not in text, f"страница {response.status_code} раскрывает {leak!r}"
    assert support.make_client().get("/admin/").status_code == 404


def test_health_endpoint_open_and_minimal():
    """План «Контракты» (/health/): открыт без входа, отвечает 200 коротко и без сведений о версиях и службах; запись не принимает."""
    client = support.make_client(ip="198.51.100.127")
    done = client.get("/health/")
    assert done.status_code == 200 and len(done.content) < 120
    assert not re.search(r"(?i)django|postgres|valkey|redis|version|\d+\.\d+\.\d+", done.content.decode())
    assert client.post("/health/").status_code == 405


@pytest.mark.parametrize("path", ["/login/", "/password/forgot/", "/activate/"])
def test_pages_have_viewport_meta_and_responsive_container(path):
    """NFR-009: страницы входа, восстановления и активации адаптивны от 360 px (meta viewport, контейнер Bootstrap)."""
    html = support.make_client().get(path).content.decode()
    assert re.search(r'<meta[^>]+name="viewport"[^>]+width=device-width', html)
    assert re.search(r'class="[^"]*\bcontainer(-fluid|-sm)?\b', html)
    logged = support.logged_in(support.make_employee(), ip="198.51.100.128").get("/me/").content.decode()
    assert 'name="viewport"' in logged and re.search(r'class="[^"]*\bcontainer(-fluid)?\b', logged)
