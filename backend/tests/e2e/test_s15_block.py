"""T-146: сценарий 15 — блокировка учётной записи (FR-005, FR-011, FR-019)."""
import re

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_s15_block_closes_sessions_and_kills_links_unblock_restores(admin_page, employee, mailpit, new_context):
    """Сценарий 15, п. 1-6: блокировка сразу закрывает сессии, вход с верными данными отклонён тем же
    сообщением, что и неверный пароль; ссылка приглашения заблокированной записи не работает; после
    разблокировки сотрудник входит прежним паролем и кодом; в журнале кто, кого и причина; в списке
    статус «заблокирован» и фильтр по нему (FR-005, FR-011)."""
    acc = employee()
    session = acc.page
    session.goto("/me/security/")
    expect(session.locator("#top-bar")).to_be_visible()

    # приглашённый, но не активированный: ссылка должна умереть при блокировке (п. 3)
    invited = employee(activate=False)

    reason = "проверка блокировки " + factories.new_email("why").split("@")[0]
    for target in (acc, invited):
        admin_page.goto(f"/staff/{target.id}/")
        helpers.open_security_tab(admin_page)
        form = admin_page.locator('form[action$="/block/"]')
        form.locator("[name=reason]").fill(reason)
        helpers.submit(form)

    # п. 1: открытая сессия закрыта сразу
    session.goto("/me/security/")
    assert "/login/" in session.url, "сессия заблокированного жива"

    # п. 2: вход с верными данными отклонён; сообщение неотличимо от неверного пароля
    page = new_context().new_page()
    helpers.fill_login(page, acc.email, factories.new_password())
    generic = helpers.alert_text(page)
    helpers.fill_login(page, acc.email, acc.password)
    assert page.locator("input[name=code]").count() == 0
    assert helpers.alert_text(page) == generic

    # п. 3: ссылка заблокированной записи
    dead = new_context().new_page()
    dead.goto(invited.link)
    dead.wait_for_load_state("networkidle")
    assert "/activate/profile/" not in dead.url

    # п. 6: статус и фильтр по статусу
    admin_page.goto("/staff/?state=blocked")
    row = helpers.staff_row(admin_page, acc.email)
    expect(row).to_have_count(1)
    assert row.get_attribute("data-state") == "blocked"

    # п. 4: разблокировка — вход прежним паролем и вторым фактором
    admin_page.goto(f"/staff/{acc.id}/")
    helpers.open_security_tab(admin_page)
    helpers.submit(admin_page.locator('form[action$="/unblock/"]'))
    helpers.sign_in(new_context().new_page(), acc)

    # п. 5: журнал — кто, кого, причина
    admin_page.goto(f"/audit/?object_id={acc.id}")
    blocked = admin_page.locator("tr[data-event-id][data-action='user.blocked']")
    assert blocked.count() >= 1 and reason in blocked.first.inner_text()
    assert admin_page.locator("tr[data-event-id][data-action='user.unblocked']").count() >= 1
    assert re.search(r"audit", admin_page.url)
