"""T-148: сценарий 17 — политика паролей и сессий (FR-026, FR-027, FR-028)."""
import re

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers

DEFAULTS = {"password_min_length": "12", "password_history": "5", "password_max_age_days": "",
            "idle_timeout_minutes": "60"}


def _form(page):
    page.goto("/settings/security/")
    return page.locator('form[action="/settings/security/"]')


def _save(page, **values) -> None:
    form = _form(page)
    for name, value in values.items():
        form.locator(f"[name={name}]").fill(str(value))
    form.locator("button[type=submit]").first.click()


def test_s17_policy_change_applies_to_new_passwords_and_new_sessions(admin_page, mailpit, new_context):
    """Сценарий 17, п. 1-4: по умолчанию длина 12, запрет 5 паролей, срок выключен, выход через 60 минут;
    длина ниже границы и бездействие вне границ отклонены с объяснением границы; новая длина действует
    на новые пароли (старые не сбрасываются); изменение записано «было / стало» (FR-026, FR-027, FR-028)."""
    form = _form(admin_page)
    for name, value in DEFAULTS.items():  # п. 1
        assert form.locator(f"[name={name}]").input_value() == value, name

    try:
        _save(admin_page, password_min_length=8)  # п. 2: ослаблять нельзя
        assert re.search(r"12", helpers.alert_text(admin_page)), "отказ не называет границу длины"
        _save(admin_page, idle_timeout_minutes=4)
        assert re.search(r"\b5\b|\b60\b", helpers.alert_text(admin_page)), "отказ не называет границы бездействия"
        assert _form(admin_page).locator("[name=password_min_length]").input_value() == "12", "форма сохранена частично"

        # п. 3: длина 16 — пароль в 14 знаков при активации нового сотрудника отклонён
        _save(admin_page, password_min_length=16, idle_timeout_minutes=5)
        expect(admin_page.locator("[role=alert]")).to_have_count(0)
        email = factories.new_email("emp")
        helpers.create_employee(admin_page, email)
        link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
        page = new_context().new_page()
        helpers.open_activation_link(page, link)
        page.click("button[type=submit]")
        page.wait_for_url(re.compile(r"/activate/password/"))
        short = factories.new_password()[:14] + "!"
        page.fill("input[name=password1]", short)
        page.fill("input[name=password2]", short)
        page.click("button[type=submit]")
        text = helpers.alert_text(page)
        assert "символ" in text and "16" in text, text
        assert "/activate/password/" in page.url

        # п. 4: журнал «было / стало»: 12 → 16 и 60 → 5
        admin_page.goto("/audit/?preset=settings")
        row = admin_page.locator("tr[data-event-id][data-action='security_settings.updated']").first
        expect(row).to_be_visible()
        body = row.inner_text()
        assert "12" in body and "16" in body and "60" in body
    finally:
        _save(admin_page, **{k: v for k, v in DEFAULTS.items()})
    form = _form(admin_page)
    assert form.locator("[name=password_min_length]").input_value() == "12"
    assert form.locator("[name=idle_timeout_minutes]").input_value() == "60"
