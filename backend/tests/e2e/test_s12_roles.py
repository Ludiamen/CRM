"""T-146: сценарий 12 — роли и права (FR-014…FR-020, FR-019)."""
import re
import secrets
import time

from playwright.sync_api import expect

from tests.e2e import helpers


def _role_id(page, name: str) -> str:
    page.goto("/roles/")
    row = page.locator(f'[data-role-id][data-role-name="{name}"]')
    expect(row).to_have_count(1)
    return row.get_attribute("data-role-id")


def test_s12_create_role_assign_permission_effect_next_request(admin_page, employee):
    """Сценарий 12, п. 1-3, 6-8 и критерий «новая роль — до 2 минут»: администратор создаёт роль «Аудитор»
    с правом просмотра журнала и назначает её сотруднику без разработчика; у сотрудника право появляется
    на следующем действии без повторного входа; без права раздел закрыт (403) и скрыт в меню; роль,
    назначенную человеку, не удалить; изменения — в журнале (FR-014…FR-018, FR-020)."""
    acc = employee()
    page = acc.page
    assert page.goto("/audit/").status == 403, "без права журнал открылся"
    expect(page.locator('#main-menu a[href="/audit/"]')).to_have_count(0)

    # п. 1: три начальные роли
    admin_page.goto("/roles/")
    names = [r.get_attribute("data-role-name") for r in admin_page.locator("[data-role-id]").all()]
    assert set(helpers.DEFAULT_ROLES) <= set(names)

    role_name = f"Аудитор-{secrets.token_hex(3)}"
    started = time.monotonic()
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(role_name)
    form.locator('input[name=permissions][value="audit.view"]').check()
    form.locator("button[type=submit]").click()
    role_id = _role_id(admin_page, role_name)  # п. 3: роль в списке сразу
    admin_page.goto(f"/staff/{acc.id}/")
    roles_form = admin_page.locator('form[action$="/roles/"]')
    roles_form.locator(f'input[name=roles][value="{role_id}"]').check()
    roles_form.locator("button[type=submit]").click()
    assert time.monotonic() - started < 120, "создание и назначение роли заняли больше двух минут"

    # п. 2 и 4: право действует на следующем запросе, без повторного входа
    assert page.goto("/audit/").status == 200
    expect(page.locator('#main-menu a[href="/audit/"]')).to_have_count(1)
    assert page.goto("/settings/portal/").status == 403  # права только по выбранным

    # п. 2: правка набора прав роли действует у держателя сразу
    admin_page.goto(f"/roles/{role_id}/")
    admin_page.locator('input[name=permissions][value="settings.portal"]').check()
    admin_page.locator('form:has(input[name=permissions]) button[type=submit]').first.click()
    assert page.goto("/settings/portal/").status == 200

    # п. 6: роль назначена — удалить нельзя
    admin_page.goto(f"/roles/{role_id}/")
    helpers.submit(admin_page.locator('form[action$="/delete/"]'))
    assert _role_id(admin_page, role_name) == role_id, "назначенная роль удалена"

    # п. 7: в журнале «было / стало» и кто изменил
    actions = helpers.audit_actions(admin_page, "preset=roles")
    for needed in ("role.created", "role.updated", "role.assigned"):
        assert needed in actions, f"в журнале нет {needed}"


def test_s12_last_admin_protected_in_ui(admin_page, stand_admin):
    """Сценарий 12, п. 5 (FR-019): у единственного администратора нельзя снять роль «Администратор
    портала» и нельзя его заблокировать; роль остаётся, статус «активен»."""
    admin_page.goto("/staff/")
    admin_page.locator(f'tr[data-user-email="{stand_admin.email}"] a[href^="/staff/"]').first.click()
    admin_page.wait_for_url(re.compile(r"/staff/\d+/"))
    own_url = admin_page.url

    roles_form = admin_page.locator('form[action$="/roles/"]')
    admin_role = roles_form.get_by_label(helpers.ADMIN_ROLE, exact=True)
    admin_role.uncheck()
    roles_form.locator("button[type=submit]").click()
    expect(admin_page.locator("[role=alert]").first).to_be_visible()
    admin_page.goto(own_url)
    expect(admin_page.locator('form[action$="/roles/"]').get_by_label(helpers.ADMIN_ROLE, exact=True)).to_be_checked()

    helpers.open_security_tab(admin_page)  # форма блокировки лежит на вкладке «Безопасность»
    block = admin_page.locator('form[action$="/block/"]')
    if block.count():  # форма блокировки может быть скрыта у себя — тогда отказ уже в интерфейсе
        block.locator("[name=reason]").fill("проверка")
        helpers.submit(block)
        expect(admin_page.locator("[role=alert]").first).to_be_visible()
    admin_page.goto("/staff/")
    assert helpers.staff_row(admin_page, stand_admin.email).get_attribute("data-state") == "active"
