"""T-143: сценарий 6 — вход по резервному коду (FR-022, FR-025, FR-039)."""
from playwright.sync_api import expect

from tests.e2e import helpers


def test_s06_backup_code_login_once_and_counts_down(admin_page, employee, new_context):
    """Сценарий 6, п. 1-3, 5: резервный код входит один раз; использованный не работает и считается
    неудачей; в «Безопасности» остаток уменьшился, новый набор из 10 кодов гасит прежний; в журнале вход по
    резервному коду отмечен отдельно (FR-022, FR-025, FR-039)."""
    acc = employee()
    first, second = acc.backup_codes[0], acc.backup_codes[1]

    page = new_context().new_page()
    helpers.sign_in_backup(page, acc, first)
    expect(page.locator("#top-bar")).to_be_visible()  # п. 1: вход выполнен
    page.goto("/me/security/")
    assert page.locator("[data-backup-remaining]").first.get_attribute("data-backup-remaining") == "9"

    # п. 2: тот же код повторно — не входит, попытка в истории неудачная
    again = new_context().new_page()
    helpers.sign_in_backup(again, acc, first)
    expect(again.locator("[role=alert]").first).to_be_visible()
    assert again.locator("#top-bar").count() == 0
    page.goto("/me/security/history/")
    assert page.locator("[data-history-row][data-result=bad_code]").count() >= 1

    # п. 3: новый набор из 10 кодов; старые перестают действовать
    page.goto("/me/security/")
    helpers.submit(page.locator('form[action="/me/security/backup-codes/new/"]'))
    new_codes = [c.strip() for c in page.locator("code.backup-code").all_inner_texts()]
    assert len(new_codes) == 10 and not set(new_codes) & set(acc.backup_codes)
    old = new_context().new_page()
    helpers.sign_in_backup(old, acc, second)
    expect(old.locator("[role=alert]").first).to_be_visible()
    assert old.locator("#top-bar").count() == 0
    acc.backup_codes = new_codes
    helpers.sign_in_backup(new_context().new_page(), acc, new_codes[0])

    # п. 5: в журнале вход по резервному коду отмечен отдельно от обычного
    actions = helpers.audit_actions(admin_page, "preset=access")
    assert "backup_code.used" in actions
    assert "backup_codes.issued" in helpers.audit_actions(admin_page)
