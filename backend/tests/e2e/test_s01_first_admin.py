"""T-140: сценарий 1 — первый администратор после установки (FR-001, FR-003, FR-008, FR-013, FR-044, NFR-009).

Файл идёт первым в круге браузера (conftest): нужен пустой стенд. Если администратор
уже есть — тест падает с подсказкой сбросить данные (E2E_RESET_CMD), а не пропускается.
"""
import re
import subprocess

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_e2e_harness_smoke(mailpit, page, portal_url):
    """NFR-009: стенд отвечает, страница входа открывается, ящик Mailpit читается через API."""
    assert mailpit.messages() == []
    response = page.goto("/login/")
    assert response is not None and response.status == 200, "стенд не отвечает на /login/"
    expect(page.locator("input[name=email]")).to_be_visible()
    expect(page.locator("input[name=password]")).to_be_visible()
    assert page.url.startswith(portal_url)


def test_s01_fresh_install_one_admin_three_roles_activate_and_journal(browser, browser_context_args, first_admin,
                                                                      new_context):
    """Сценарий 1, п. 1-3: после установки одна запись с ролью администратора и три роли; ссылка
    открывает тот же мастер (без пароля и второго фактора внутрь не попасть); в журнале есть
    создание и активация первой записи (FR-001, FR-003, FR-008, FR-013, FR-044)."""
    assert browser.e2e_project not in helpers.ADMINS, "администратор круга уже создан раньше s01"
    account = helpers.Account(email=factories.new_email("admin"), password=factories.new_password(),
                              full_name="Администратор Стенда")
    try:
        link = first_admin(account.email)
    except subprocess.CalledProcessError as e:
        raise AssertionError("create_first_admin отказала: стенд не пуст, сбросьте данные перед кругом "
                             "(E2E_RESET_CMD)") from e

    context = new_context()
    page = context.new_page()
    # п. 2: до конца мастера внутрь не попасть
    helpers.open_activation_link(page, link)
    for protected in ("/", "/staff/", "/audit/"):
        page.goto(protected)
        assert re.search(r"/(login|activate|me/security/totp)/", page.url), \
            f"{protected} открылась до подключения второго фактора"
    page.goto("/activate/profile/")
    page.fill("[name=phone]", "+7 900 000-00-00")
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/password/"))
    page.fill("input[name=password1]", account.password)
    page.fill("input[name=password2]", account.password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/totp/"))
    page.goto("/staff/")
    assert "/staff/" not in page.url, "без второго фактора раздел сотрудников открылся"
    page.goto("/activate/totp/")
    account.totp_secret = page.locator("#totp-secret").inner_text().strip()
    page.fill("input[name=code]", helpers.totp_for(account.totp_secret))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/codes/"))
    account.backup_codes = [c.strip() for c in page.locator("code.backup-code").all_inner_texts()]
    page.locator("input[name=confirm]").check()
    page.click("button[type=submit]")
    page.wait_for_url(lambda url: "/activate/" not in url)
    account.storage_state = context.storage_state()
    helpers.ADMINS[browser.e2e_project] = account

    # п. 1: ровно одна запись, три начальные роли
    page.goto("/staff/")
    assert page.locator("tr[data-user-id]").count() == 1
    expect(helpers.staff_row(page, account.email)).to_have_count(1)
    page.goto("/roles/")
    names = [r.get_attribute("data-role-name") for r in page.locator("[data-role-id]").all()]
    for role in helpers.DEFAULT_ROLES:
        assert role in names, f"нет начальной роли «{role}»"
    page.locator(f'tr[data-user-email="{account.email}"] a[href^="/staff/"]').first.click()
    page.wait_for_url(re.compile(r"/staff/\d+/"))
    expect(page.locator("body")).to_contain_text(helpers.ADMIN_ROLE)
    for section in ("/staff/", "/roles/", "/audit/", "/settings/portal/", "/settings/security/"):
        expect(page.locator(f'#main-menu a[href="{section}"]')).to_have_count(1)  # раздел «Администрирование»

    # п. 3: в журнале — создание и активация первой записи
    actions = helpers.audit_actions(page)
    assert "user.created" in actions, "в журнале нет создания первой записи"
    assert "user.activated" in actions, "в журнале нет активации первой записи"
