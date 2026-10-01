"""T-240…T-243, T-250, T-223 (остаток): страницы оболочки, входа и профиля, которым хватает проверки без страниц администратора."""
import re

import pytest

from tests import factories, support
from tests.support import HX, model

pytestmark = pytest.mark.django_db


def test_404_and_403_pages_short_and_without_details():
    """FR-018: неизвестный адрес и CSRF-отказ — короткие страницы по-русски без пути, версий и подробностей."""
    client = support.logged_in(support.make_employee(), ip="198.51.100.20")
    missing = client.get("/no-such-page-xyz/")
    assert missing.status_code == 404
    text = missing.content.decode()
    assert re.search("[а-яА-Я]{4,}", text)
    for leak in ("Traceback", "URLconf", "Request URL", "no-such-page-xyz", "Django"):
        assert leak not in text
    assert support.make_client().get("/admin/").status_code == 404
    strict = support.make_client(ip="198.51.100.21", enforce_csrf_checks=True)
    refused = strict.post("/login/", {"email": factories.new_email(), "password": factories.new_password()})
    assert refused.status_code == 403 and "CSRF" not in refused.content.decode()


def test_media_serves_png_jpeg_only_with_nosniff(settings, tmp_path):
    """FR-049: /media/ отдаёт PNG и JPEG с nosniff и типом изображения, остальное и выход из каталога — 404."""
    settings.MEDIA_ROOT = tmp_path
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (tmp_path / "page.html").write_text("<script>1</script>")
    client = support.make_client()
    got = client.get("/media/logo.png")
    assert got.status_code == 200 and got["X-Content-Type-Options"] == "nosniff" and got["Content-Type"] == "image/png"
    assert client.get("/media/page.html").status_code == 404
    assert client.get("/media/../manage.py").status_code in (400, 404)
    assert client.get("/media/nope.png").status_code == 404


def test_exchange_pages_post_only_and_landing_has_script_not_code():
    """FR-012: страница ссылки — форма и внешний скрипт; обмен кода только POST, адрес после обмена без кода."""
    for landing, exchange in (("/activate/", "/activate/exchange/"), ("/password/reset/", "/password/reset/exchange/")):
        client = support.make_client()
        html = client.get(landing).content.decode()
        assert 'id="exchange-form"' in html and "/static/js/exchange.js" in html
        assert not re.search(r"<script[^>]*>[^<]", html), "inline-скрипт"
        assert client.get(exchange).status_code == 405


def test_slider_pages_same_address_fragment_and_full_page():
    """UX-03: каждая страница слайдера по своему адресу открывается и фрагментом (HTMX), и полной страницей с профилем под панелью."""
    client = support.logged_in(support.make_employee(), ip="198.51.100.22")
    for path in ("/me/security/", "/me/security/password/", "/me/security/devices/", "/me/security/history/"):
        full, part = client.get(path), client.get(path, **HX)
        assert full.status_code == part.status_code == 200, path
        page, fragment = full.content.decode(), part.content.decode()
        assert "<html" in page and 'id="main-menu"' in page and 'class="slider-panel"' in page, path
        assert 'id="slider-root"' in page and "Мой профиль" in page, "профиль под слайдером"
        assert "<html" not in fragment and 'class="slider-panel"' in fragment and 'id="main-menu"' not in fragment, path
    closed = client.get("/me/", **HX, HTTP_HX_TARGET="slider-root")
    assert closed.status_code == 200 and closed.content == b"", "«×» закрывает слайдер пустым ответом"
    restored = client.get("/me/security/", **HX, HTTP_HX_HISTORY_RESTORE_REQUEST="true")
    assert "<html" in restored.content.decode(), "восстановление истории браузера получает полную страницу"


def test_backup_codes_shown_once_then_never_regenerated_by_reopening():
    """FR-022: после «Я сохранил коды» страница больше кодов не выпускает и не показывает; набор не сменился."""
    user = support.make_employee(totp=False)
    client = support.make_client(ip="198.51.100.23")
    support.post_password(client, user)
    _, codes = support.enroll_totp(client, user, totp_url="/me/security/totp/", codes_url="/me/security/backup-codes/")
    hashes = set(model("core.BackupCode").objects.filter(device__user=user).values_list("code_hash", flat=True))
    for _ in range(2):
        page = client.get("/me/security/backup-codes/").content.decode()
        assert not support.backup_code_values(page) and "уже показаны" in page
    assert set(model("core.BackupCode").objects.filter(device__user=user).values_list("code_hash", flat=True)) == hashes
    assert user.state == "active"


def test_interrupted_activation_finished_from_limited_session_activates_user():
    """FR-013, NFR-004: мастер прервали после пароля; вход по паролю, подключение фактора и «я сохранил» активируют запись."""
    user = support.make_employee(state="invited", totp=False, roles=[support.role_by_name(support.STAFF_ROLE)])
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.24")
    assert support.post_password(client, user)["Location"].endswith("/me/security/totp/")
    support.enroll_totp(client, user, totp_url="/me/security/totp/", codes_url="/me/security/backup-codes/")
    user.refresh_from_db()
    assert user.state == "active" and user.activated_at
    link.refresh_from_db()
    assert link.revoked_at is not None or link.used_at is not None, "ссылка активации погашена"
    assert "user.activated" in support.audit_actions(object_id=str(user.pk))
    assert client.get("/me/").status_code == 200


def test_menu_toggle_state_script_files_are_external_and_clean():
    """FR-050, NFR-007: скрипты оболочки внешние, без eval и Function; режим меню хранится под ключом menu-icons-only."""
    from django.contrib.staticfiles import finders

    for name in ("js/shell.js", "js/shell-init.js", "js/exchange.js", "js/htmx-glue.js"):
        path = finders.find(name)
        assert path, name
        source = open(path, encoding="utf-8").read()
        assert "eval(" not in source and "new Function" not in source and "innerHTML" not in source, name
    assert "menu-icons-only" in open(finders.find("js/shell.js"), encoding="utf-8").read()
    assert "replaceState" in open(finders.find("js/exchange.js"), encoding="utf-8").read()


def test_csrf_rejects_null_origin_and_accepts_normal_form():
    """NFR-007: стандартная проверка CSRF Django без исключений — запрос с `Origin: null` отвергается
    всегда, даже с `Sec-Fetch-Site: same-origin` и токеном; обычная форма с токеном проходит.
    Политика реферера везде same-origin, браузер шлёт настоящий Origin (решение Opus 2026-10-01)."""
    user = support.make_employee(state="invited", totp=False)
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.25", enforce_csrf_checks=True)
    page = client.get("/activate/").content.decode()
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page).group(1)
    data = {"code": code, "csrfmiddlewaretoken": token}
    null = {"HTTP_ORIGIN": "null"}
    assert client.post("/activate/exchange/", data, **null).status_code == 403
    assert client.post("/activate/exchange/", data, **null, HTTP_SEC_FETCH_SITE="same-origin").status_code == 403
    assert client.post("/activate/exchange/", {"code": code}).status_code == 403, "без токена CSRF — отказ"
    done = client.post("/activate/exchange/", data)
    assert done.status_code == 302 and done["Location"].endswith("/activate/profile/")
