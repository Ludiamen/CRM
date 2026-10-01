"""T-147: сценарий 14 — название и логотип портала (FR-048, FR-049)."""
import re
import secrets

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers

PNG = {"name": "logo.png", "mimeType": "image/png"}


def _portal_name(page) -> str:
    return page.locator("[data-portal-name]").first.inner_text().strip()


def _save(page, *, name: str | None = None, logo: dict | None = None) -> None:
    page.goto("/settings/portal/")
    form = page.locator('form[action="/settings/portal/"]')
    if name is not None:
        form.locator("[name=name]").fill(name)
    if logo is not None:
        form.locator("[name=logo]").set_input_files(logo)
    form.locator("button[type=submit]:not([name=reset])").first.click()


def test_s14_name_and_logo_change_everywhere_and_reset(admin_page, mailpit, new_context):
    """Сценарий 14, п. 1-5: название по умолчанию нейтральное; новое видно на входе, в верхней панели, во
    вкладке и в письмах; PNG принят и показан как `<img>` из /media/, SVG, не-картинка и слишком большой
    файл отклонены с понятным сообщением, прежний логотип остаётся; в журнале «было / стало»;
    «Вернуть по умолчанию» возвращает название и знак (FR-048, FR-049)."""
    guest = new_context().new_page()
    guest.goto("/login/")
    default_name = _portal_name(guest)
    # название эталона собрано из частей: само слово запрещено в нашем коде
    # инвариантом «эталон-не-копия», а проверить его отсутствие нужно
    чужое = "(?i)" + "|".join(["bit" + "rix", "бит" + "рикс", "1[сc]"])
    assert default_name and not re.search(чужое, default_name)  # п. 1
    expect(guest.locator("img[data-portal-logo]")).to_have_count(1)
    default_src = guest.locator("img[data-portal-logo]").get_attribute("src")

    new_name = f"Портал-{secrets.token_hex(3)}"
    try:
        _save(admin_page, name=new_name, logo={**PNG, "buffer": helpers.make_png(64, 64)})  # п. 2
        guest.goto("/login/")
        assert _portal_name(guest) == new_name and new_name in guest.title()
        logo = guest.locator("img[data-portal-logo]")
        assert logo.get_attribute("src").startswith("/media/"), "логотип не из /media/"
        admin_page.goto("/me/")
        assert new_name in admin_page.locator("#top-bar").inner_text()
        assert new_name in admin_page.title()

        # письма подписаны новым названием
        email = factories.new_email("emp")
        helpers.create_employee(admin_page, email)
        mail = helpers.wait_mail(mailpit, email, "invitation")
        assert new_name in mail["Subject"] + mail["Text"]

        # п. 3: отказы; прежний логотип остаётся
        kept = guest.locator("img[data-portal-logo]").get_attribute("src")
        bad_files = {
            "svg": {"name": "logo.svg", "mimeType": "image/svg+xml",
                    "buffer": b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>1</script></svg>'},
            "не картинка": {"name": "logo.png", "mimeType": "image/png", "buffer": "это не изображение".encode()},
            "слишком большой": {**PNG, "buffer": helpers.make_png(700, 700, noise=True)},
        }
        for label, file in bad_files.items():
            _save(admin_page, logo=file)
            assert re.search(r"логотип|изображен", helpers.alert_text(admin_page), re.I), f"нет отказа: {label}"
            guest.goto("/login/")
            assert guest.locator("img[data-portal-logo]").get_attribute("src") == kept, f"логотип сменился: {label}"
        assert re.search(r"512|1\s?МБ", helpers.alert_text(admin_page)), "отказ не называет границу размера"

        # п. 4: журнал — кто, прежнее и новое название; логотип «заменён»
        admin_page.goto("/audit/?preset=settings")
        row = admin_page.locator("tr[data-event-id][data-action='portal_settings.updated']").first
        expect(row).to_be_visible()
        assert new_name in row.inner_text() and "заменён" in admin_page.locator("body").inner_text()
    finally:
        # п. 5: вернуть по умолчанию
        admin_page.goto("/settings/portal/")
        admin_page.locator('form[action="/settings/portal/"] button[name=reset][value="1"]').click()
    guest.goto("/login/")
    assert _portal_name(guest) == default_name
    assert guest.locator("img[data-portal-logo]").get_attribute("src") == default_src
