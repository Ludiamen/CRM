"""T-144: сценарий 9 — блокировка записи после 5 неудач и защита от перебора (FR-025, FR-035…038, FR-044, NFR-006).

Все тесты идут с одного адреса (127.0.0.1 за nginx), поэтому блокировка адреса в тестах снимается в
`finally` через «Снять блокировку входа» у администратора (его сессия заведена раньше).
"""
import re

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def _fail(page, email: str, times: int) -> str:
    """`times` раз вводит неверный пароль; возвращает текст последнего сообщения."""
    text = ""
    for _ in range(times):
        helpers.fill_login(page, email, factories.new_password())
        text = helpers.alert_text(page)
    return text


def _unlock_ip(admin_page) -> None:
    admin_page.goto("/staff/locks/")
    rows = admin_page.locator('[data-lock-kind="ip"]')
    for i in range(rows.count()):
        helpers.submit(admin_page.locator('[data-lock-kind="ip"]').first.locator("form"))
        admin_page.goto("/staff/locks/")


def test_s09_account_locked_after_five_other_user_unaffected(employee, mailpit, new_context):
    """Сценарий 9, п. 1, 4, 5: после пяти неудач шестая попытка с верными данными отклонена тем же
    сообщением, что и неверный пароль; владельцу ушло письмо о блокировке; другой сотрудник с того же
    адреса входит (FR-035, FR-037, NFR-006)."""
    victim, other = employee(), employee()
    seen = helpers.mail_ids(mailpit, victim.email)
    page = new_context().new_page()
    generic = _fail(page, victim.email, 5)
    assert generic
    helpers.fill_login(page, victim.email, victim.password)  # верные данные, но запись заблокирована
    assert page.locator("input[name=code]").count() == 0, "заблокированная запись дошла до шага кода"
    assert helpers.alert_text(page) == generic, "сообщение о блокировке отличается от «неверные данные»"
    helpers.wait_mail(mailpit, victim.email, "account_locked", seen=seen, timeout=60)

    # п. 5: другой сотрудник с того же адреса входит
    helpers.sign_in(new_context().new_page(), other)


def test_s09_ip_locked_after_20_failures_across_accounts(admin_page, employee, new_context):
    """Сценарий 9, п. 6 (FR-036, FR-025): 20 неудач по разным записям с одного адреса — 21-я попытка
    (даже с верными данными другой записи) отклонена, а сообщение не называет перебираемых записей;
    после снятия блокировки адреса вход снова возможен."""
    innocent = employee()
    page = new_context().new_page()
    generic = ""
    try:
        for i in range(5):  # пять записей по четыре неудачи: ни одна запись не блокируется, адрес считает все
            generic = _fail(page, factories.new_email(f"brute{i}"), 4)
        helpers.fill_login(page, innocent.email, innocent.password)
        assert page.locator("input[name=code]").count() == 0, "адрес после 20 неудач по разным записям не заблокирован"
        assert helpers.alert_text(page) == generic
        assert "brute" not in page.locator("body").inner_text()
    finally:
        _unlock_ip(admin_page)
    helpers.sign_in(new_context().new_page(), innocent)  # после снятия блокировки адреса


def test_s09_admin_unlocks_and_journal_has_events(admin_page, employee, new_context):
    """Сценарий 9, п. 7-9 (FR-038, FR-044): блокировка и разблокировка видны в журнале, у блокировки
    записи есть действие «Снять блокировку входа», после него вход проходит прежним паролем и кодом;
    у владельца в истории отмечены «неверный пароль» и «блокировка»."""
    victim = employee()
    page = new_context().new_page()
    _fail(page, victim.email, 5)
    helpers.fill_login(page, victim.email, victim.password)

    assert "account.locked" in helpers.audit_actions(admin_page, "preset=access")
    admin_page.goto("/staff/locks/")
    row = admin_page.locator(f'[data-lock-kind="account"][data-lock-target="{victim.id}"]')
    expect(row).to_have_count(1)
    expect(row.locator("button[type=submit]")).to_contain_text("Снять блокировку входа")
    helpers.submit(row.locator("form"))
    expect(admin_page.locator(f'[data-lock-kind="account"][data-lock-target="{victim.id}"]')).to_have_count(0)
    assert "account.unlocked" in helpers.audit_actions(admin_page, "preset=access")

    helpers.sign_in(new_context().new_page(), victim)  # прежний пароль и тот же второй фактор

    # п. 9: в истории (вид администратора) — «неверный пароль» и «блокировка»
    admin_page.goto(f"/staff/{victim.id}/logins/")
    results = {r.get_attribute("data-result") for r in admin_page.locator("[data-history-row]").all()}
    assert {"bad_password", "locked"} <= results, results
    assert re.search(r"/staff/\d+/logins/", admin_page.url)
