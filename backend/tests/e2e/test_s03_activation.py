"""T-141: сценарий 3 — активация по ссылке (FR-011, FR-012, FR-013, FR-021, FR-022, FR-025, FR-026, NFR-004).

Подключение второго фактора в мастере: ключ показан элементом `#totp-secret`, код — `input[name=code]`
(CONTRACT.md, «Дополнения исполнителя T-140…T-151»).
"""
import re

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_s03_wizard_password_totp_backup_codes_no_code_in_address(admin_page, mailpit, new_context):
    """Сценарий 3, п. 1, 2, 3, 5, 7, 8: ссылка ведёт на мастер, адрес без кода; короткий пароль отклонён с
    объяснением; неверный код не завершает подключение; кодов ровно 10, продолжить можно только с «я
    сохранил»; в журнале активация и подключение, секрета и кодов нет."""
    email, password = factories.new_email("emp"), factories.new_password()
    helpers.create_employee(admin_page, email)
    link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
    code = helpers.code_of(link)

    page = new_context().new_page()
    helpers.open_activation_link(page, link)
    assert "#" not in page.url and code not in page.url, "адрес страницы после обмена содержит код ссылки"
    page.reload()
    assert code not in page.url
    page.fill("[name=phone]", "+7 900 000-00-00")
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/password/"))

    # п. 2: короткий пароль — объяснение политики, пароль не принят
    short = "Aa1-" + "x" * 3
    page.fill("input[name=password1]", short)
    page.fill("input[name=password2]", short)
    page.click("button[type=submit]")
    expect(page.locator("[role=alert]").first).to_contain_text(re.compile("символ"))
    assert "/activate/password/" in page.url
    page.fill("input[name=password1]", password)
    page.fill("input[name=password2]", password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/totp/"))

    # п. 3: неверный код — подключение не завершается, можно повторить
    secret = page.locator("#totp-secret").inner_text().strip()
    expect(page.locator("img#totp-qr")).to_be_visible()
    page.fill("input[name=code]", helpers.wrong_code(secret))
    page.click("button[type=submit]")
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert "/activate/totp/" in page.url
    page.fill("input[name=code]", helpers.totp_for(secret))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/codes/"))

    # п. 5: ровно 10 различных кодов; без подтверждения дальше нельзя
    codes = [c.strip() for c in page.locator("code.backup-code").all_inner_texts()]
    assert len(codes) == 10 and len(set(codes)) == 10
    page.click("button[type=submit]")
    assert "/activate/codes/" in page.url or page.locator("input[name=confirm]").evaluate("e => !e.checked")
    page.locator("input[name=confirm]").check()
    page.click("button[type=submit]")
    page.wait_for_url(lambda url: "/activate/" not in url)
    expect(page.locator("#top-bar")).to_be_visible()

    # п. 8: повторное открытие ссылки — сообщение «использована», а не мастер
    page2 = new_context().new_page()
    page2.goto(link)
    page2.wait_for_load_state("networkidle")
    assert "/activate/profile/" not in page2.url
    assert "использован" in helpers.alert_text(page2).lower()

    # п. 7: в журнале активация и подключение, значений секрета и кодов нет
    actions = helpers.audit_actions(admin_page)
    assert "user.activated" in actions and "totp.enrolled" in actions
    journal = helpers.audit_text(admin_page)
    assert secret not in journal and secret.replace(" ", "") not in journal
    assert not [c for c in codes if c in journal], "резервный код попал в журнал"
    assert code not in journal and password not in journal


def test_s03_interrupted_activation_leads_only_to_totp_page(admin_page, mailpit, new_context):
    """Сценарий 3, п. 6 (NFR-004): после пароля без второго фактора доступна только страница его подключения."""
    email, password = factories.new_email("emp"), factories.new_password()
    helpers.create_employee(admin_page, email)
    link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
    page = new_context().new_page()
    helpers.open_activation_link(page, link)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/password/"))
    page.fill("input[name=password1]", password)
    page.fill("input[name=password2]", password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/totp/"))

    later = new_context().new_page()  # «войти позже»
    helpers.fill_login(later, email, password)
    later.wait_for_url(re.compile(r"/me/security/totp/"))
    for forbidden in ("/", "/me/", "/staff/", "/me/security/devices/"):
        later.goto(forbidden)
        assert "/me/security/totp/" in later.url, f"{forbidden} доступна без второго фактора"


def test_s03_bad_totp_code_at_setup_counts_as_failure(admin_page, mailpit, new_context):
    """Сценарий 3, п. 4 (FR-025): пять неверных кодов при подключении — дальше действует блокировка
    как при переборе пароля: даже верный код отклоняется."""
    email, password = factories.new_email("emp"), factories.new_password()
    helpers.create_employee(admin_page, email)
    link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
    page = new_context().new_page()
    helpers.open_activation_link(page, link)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/password/"))
    page.fill("input[name=password1]", password)
    page.fill("input[name=password2]", password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/totp/"))
    secret = page.locator("#totp-secret").inner_text().strip()
    for _ in range(5):
        page.fill("input[name=code]", helpers.wrong_code(secret))
        page.click("button[type=submit]")
        expect(page.locator("[role=alert]").first).to_be_visible()
    page.fill("input[name=code]", helpers.totp_for(secret))
    page.click("button[type=submit]")
    assert "/activate/codes/" not in page.url, "после пяти неудач верный код принят — блокировки нет"
    expect(page.locator("[role=alert]").first).to_be_visible()
