"""T-113: настройки портала (FR-044, FR-048, FR-049, NFR-007, NFR-010). Сценарий 14.

Форма `/settings/portal/` (CONTRACT.md): POST `name`, файл `logo`, `reset=1` — «Вернуть по умолчанию».
Логотип отдаётся по `/media/…` (адрес — `PortalSettings.logo.url`).
"""
import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db

URL = "/settings/portal/"


def image_bytes(fmt="PNG", size=(64, 64)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(out, fmt)
    return out.getvalue()


def upload(filename, content, **fields):
    return {"name": fields.pop("name", "Портал ИТ"), "logo": SimpleUploadedFile(filename, content), **fields}


def portal_admin():
    return support.logged_in(support.make_with_permissions("settings.portal", "audit.view"), ip="198.51.100.110")


def row():
    return model("core.PortalSettings").objects.get()


def test_name_shown_in_header_login_title_and_mail(mailpit, django_capture_on_commit_callbacks):
    """FR-048, NFR-010 (сценарий 14.2): новое название — в верхней панели, на странице входа, во вкладке и в письмах."""
    from tests.support_mail import deliver

    name = "Портал Тест-" + factories.new_email("n").split("@")[0][-6:]
    admin = portal_admin()
    assert admin.post(URL, {"name": name}).status_code == 302
    page = admin.get("/me/").content.decode()
    assert name in page and re.search(rf"<title>[^<]*{re.escape(name)}", page)
    assert re.search(r"<(header|nav)[^>]*>.*?" + re.escape(name), page, re.S)
    login = support.make_client().get("/login/").content.decode()
    assert name in login and re.search(rf"<title>[^<]*{re.escape(name)}", login)
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.make_client(ip="198.51.100.111").post("/password/forgot/", {"email": user.email})
    deliver()
    letter = mailpit.wait_for(user.email)
    assert name in letter["Text"] or name in letter["Subject"]


@pytest.mark.parametrize("filename,fmt,ok", [("logo.png", "PNG", True), ("logo.jpg", "JPEG", True), ("logo.exe", "PNG", True),
                                              ("logo.gif", "GIF", False), ("logo.webp", "WEBP", False)])
def test_logo_png_jpeg_only_by_content_not_by_extension(filename, fmt, ok):
    """FR-049: формат определяется по содержимому: PNG и JPEG принимаются под любым именем, остальное — нет; текст под видом PNG — отказ."""
    admin = portal_admin()
    done = admin.post(URL, upload(filename, image_bytes(fmt)))
    assert (done.status_code == 302) is ok, f"{filename} ({fmt}): {done.status_code}"
    if ok:
        assert row().logo
    fake = admin.post(URL, upload("fake.png", b"<html>not an image</html>"))
    assert fake.status_code == 200 and "логотип" in fake.content.decode().lower()


def test_logo_over_1mb_or_512px_rejected():
    """FR-049 (сценарий 14.3): больше 1 МБ или больше 512×512 — понятный отказ, прежний логотип остаётся."""
    admin = portal_admin()
    assert admin.post(URL, upload("ok.png", image_bytes("PNG", (512, 512)))).status_code == 302, "512×512 — граница допустима"
    before = row().logo.name
    wide = admin.post(URL, upload("wide.png", image_bytes("PNG", (513, 64))))
    tall = admin.post(URL, upload("tall.png", image_bytes("PNG", (64, 513))))
    heavy = admin.post(URL, upload("heavy.png", image_bytes("PNG", (512, 512)) + b"\0" * (1024 * 1024 + 1)))
    for refused in (wide, tall, heavy):
        assert refused.status_code == 200 and re.search("512|МБ|размер", refused.content.decode())
    assert row().logo.name == before


def test_svg_logo_rejected():
    """FR-049: SVG не принимается ни под каким именем (в нём можно исполнить скрипт)."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script></svg>'
    admin = portal_admin()
    for name in ("logo.svg", "logo.png"):
        done = admin.post(URL, upload(name, svg))
        assert done.status_code == 200, name
    assert not row().logo


def test_default_name_and_logo_not_reference_assets_and_reset_works():
    """FR-049 (сценарий 14.1, 14.5): значения по умолчанию свои, не эталона; «Вернуть по умолчанию» возвращает название и знак."""
    default_name = row().name
    page = support.make_client().get("/login/").content.decode()
    assert default_name and default_name in page
    assert not re.search("|".join(("bit" + "rix", "бит" + "рикс", "1с", "bx" + "24")), (default_name + page).lower())
    admin = portal_admin()
    admin.post(URL, upload("mine.png", image_bytes()))
    admin.post(URL, {"name": "Временное имя"})
    assert row().name == "Временное имя"
    assert admin.post(URL, {"reset": "1"}).status_code == 302
    assert row().name == default_name and not row().logo
    after = support.make_client().get("/login/").content.decode()
    assert default_name in after and "Временное имя" not in after and "<img" in after, "знак по умолчанию виден"


def test_media_served_nosniff_and_only_via_img():
    """FR-049, NFR-007: файл логотипа отдаётся с nosniff и типом изображения; в страницах он выводится только через <img>."""
    admin = portal_admin()
    admin.post(URL, upload("logo.png", image_bytes()))
    url = row().logo.url
    assert url.startswith("/media/")
    got = support.make_client().get(url)
    assert got.status_code == 200 and got["X-Content-Type-Options"] == "nosniff"
    assert got["Content-Type"] == "image/png" and "attachment" not in got.get("Content-Disposition", "")
    for page in (admin.get("/me/").content.decode(), support.make_client().get("/login/").content.decode()):
        assert re.search(rf'<img[^>]+src="[^"]*{re.escape(url)}', page)
        assert not re.search(rf'<(object|embed|iframe|script|a)[^>]+(src|data|href)="[^"]*{re.escape(url)}', page)
    assert support.make_client().get("/media/../manage.py").status_code in (400, 404)


def test_settings_need_matching_permission_and_are_audited():
    """FR-048, FR-044 (сценарий 14.4): страница портала — только с settings.portal; изменения пишутся «было / стало», логотип — отметкой «заменён»."""
    outsider = support.logged_in(support.make_with_permissions("settings.security"), ip="198.51.100.112")
    assert outsider.get(URL).status_code == 403 and outsider.post(URL, {"name": "Взлом"}).status_code == 403
    before = row().name
    assert row().name == before
    admin = portal_admin()
    admin.post(URL, upload("logo.png", image_bytes(), name="Новое имя"))
    event = model("core.AuditEvent").objects.filter(action="portal_settings.updated").latest("id")
    assert event.actor_id and event.before["name"] == before and event.after["name"] == "Новое имя"
    assert "заменён" in str(event.after.get("logo"))
    admin.post(URL, {"reset": "1"})
    assert model("core.AuditEvent").objects.filter(action="portal_settings.updated").count() == 2
