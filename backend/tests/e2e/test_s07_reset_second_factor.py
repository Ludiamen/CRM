"""T-143: сценарий 7 — сброс второго фактора администратором (FR-021, FR-024, FR-052)."""
import re

from playwright.sync_api import expect

from tests.e2e import helpers


def test_s07_admin_resets_user_reconnects_second_factor_and_mail_sent(admin_page, employee, mailpit, new_context,
                                                                       stand_admin):
    """Сценарий 7, п. 1-5: после сброса письмо о сбросе, прежний ключ и коды не работают, вход по паролю
    ведёт только на подключение фактора; после подключения вход проходит по новому ключу, коды выпущены
    заново; в журнале кто и чей сбросил; у себя сбросить нельзя (кнопки нет)."""
    acc = employee()
    seen = helpers.mail_ids(mailpit, acc.email)
    old_secret, old_codes = acc.totp_secret, list(acc.backup_codes)

    admin_page.goto(f"/staff/{acc.id}/")
    helpers.open_security_tab(admin_page)
    helpers.submit(admin_page.locator('form[action$="/reset-2fa/"]'))
    mail = helpers.wait_mail(mailpit, acc.email, "second_factor_reset", seen=seen, timeout=60)
    assert re.search(r"[А-Яа-я]", mail["Subject"] + mail["Text"])

    # п. 5: у самого администратора формы сброса нет
    admin_page.goto(f"/staff/?q={stand_admin.email}")  # поиск по почте: список в круге длиннее одной страницы
    admin_page.locator(f'tr[data-user-email="{stand_admin.email}"] a[href^="/staff/"]').first.click()
    helpers.open_security_tab(admin_page)
    expect(admin_page.locator('form[action$="/reset-2fa/"]')).to_have_count(0)

    # п. 1-2: прежние коды и ключ не работают, вход по паролю — только на подключение фактора
    page = new_context().new_page()
    helpers.fill_login(page, acc.email, acc.password)
    page.wait_for_url(re.compile(r"/me/security/totp/"))
    page.goto("/staff/")
    assert "/me/security/totp/" in page.url
    secret = page.locator("#totp-secret").inner_text().strip()
    assert secret.replace(" ", "") != old_secret.replace(" ", ""), "после сброса показан прежний ключ"
    page.fill("input[name=code]", helpers.totp_for(secret))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/me/security/backup-codes/"))
    new_codes = [c.strip() for c in page.locator("code.backup-code").all_inner_texts()]
    assert len(new_codes) == 10 and not set(new_codes) & set(old_codes)
    page.locator("input[name=confirm]").check()
    page.click("button[type=submit]")
    expect(page.locator("#top-bar")).to_be_visible()
    acc.totp_secret, acc.backup_codes = secret, new_codes

    # прежний код (из старого приложения) и прежний резервный код входа не дают
    stale = new_context().new_page()
    helpers.fill_login(stale, acc.email, acc.password)
    stale.wait_for_url(re.compile(r"/login/code/"))
    stale.fill("input[name=code]", helpers.totp_for(old_secret))
    stale.click("button[type=submit]")
    assert stale.locator("#top-bar").count() == 0
    helpers.use_backup_code(stale, old_codes[0])
    assert stale.locator("#top-bar").count() == 0
    # и новые данные входят
    helpers.sign_in(new_context().new_page(), acc)

    # п. 3: журнал — кто, когда, чей
    admin_page.goto(f"/audit/?action=totp.reset&object_id={acc.id}")
    row = admin_page.locator("tr[data-event-id][data-action='totp.reset']")
    assert row.count() >= 1
    who = row.first.inner_text()
    assert stand_admin.email in who or stand_admin.full_name in who, "в записи не указан, кто сбросил"
