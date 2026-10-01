"""T-148: сценарий 16 — смена своего пароля (FR-026, FR-029, FR-052)."""
import re

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def _change(page, current: str, new: str) -> None:
    page.goto("/me/security/password/")
    page.fill("input[name=current_password]", current)
    page.fill("input[name=password1]", new)
    page.fill("input[name=password2]", new)
    page.click("button[type=submit]")


def test_s16_change_password_mail_and_other_sessions_closed(admin_page, employee, mailpit, new_context):
    """Сценарий 16, п. 1-5: верный текущий и новый по политике — пароль сменён, письмо о смене ушло;
    неверный текущий и повтор недавнего пароля отклонены с объяснением; сессии на других устройствах закрыты,
    текущая осталась; в журнале смена без значений паролей (FR-026, FR-029, FR-052)."""
    acc = employee()
    current = new_context().new_page()
    helpers.sign_in(current, acc)
    other = acc.page  # другая сессия (контекст активации)
    other.goto("/me/security/")
    expect(other.locator("#top-bar")).to_be_visible()

    # п. 4: неверный текущий пароль — смены нет
    _change(current, factories.new_password(), factories.new_password())
    expect(current.locator("[role=alert]").first).to_be_visible()
    # п. 2: новый совпадает с недавним (текущим) — отказ с объяснением
    _change(current, acc.password, acc.password)
    assert re.search(r"последн", helpers.alert_text(current), re.I)

    # п. 1: смена
    seen = helpers.mail_ids(mailpit, acc.email)
    new_password = factories.new_password()
    _change(current, acc.password, new_password)
    mail = helpers.wait_mail(mailpit, acc.email, "password_changed", seen=seen, timeout=60)
    assert re.search(r"[А-Яа-я]", mail["Subject"] + mail["Text"])
    assert new_password not in mail["Text"] and acc.password not in mail["Text"]

    # п. 3: чужая сессия закрыта, текущая осталась
    other.goto("/me/security/")
    assert "/login/" in other.url, "сессия другого устройства осталась открытой"
    current.goto("/me/security/")
    expect(current.locator("#top-bar")).to_be_visible()

    # новый пароль работает, прежний — нет
    stale = new_context().new_page()
    helpers.fill_login(stale, acc.email, acc.password)
    assert stale.locator("input[name=code]").count() == 0
    acc.password = new_password
    helpers.sign_in(new_context().new_page(), acc)

    # п. 5: журнал — смена есть, паролей нет
    assert "password.changed" in helpers.audit_actions(admin_page, f"object_id={acc.id}")
    journal = helpers.audit_text(admin_page)
    assert new_password not in journal and acc.password not in journal
