"""T-145: сценарий 11 — история входов и устройства (FR-039, FR-040, FR-042, FR-051)."""
import re
from datetime import datetime

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_s11_history_devices_and_admin_view_of_other_user(admin_page, employee, mailpit, new_context):
    """Сценарий 11, п. 1-4: история не пуста с первого входа, по убыванию времени, с неудачами и без чужих
    записей; «Закрыть сессию» у незнакомого устройства закрывает его сессию, и следующий вход с него — снова
    новое устройство (письмо); администратор видит устройства и входы другого сотрудника."""
    acc, bystander = employee(), employee()

    page = new_context().new_page()
    helpers.fill_login(page, acc.email, factories.new_password())  # неудача
    helpers.sign_in(page, acc)

    page.goto("/me/security/history/")
    rows = page.locator("[data-history-row]")
    assert rows.count() >= 2, "история пуста"
    stamps = [datetime.fromisoformat(r.get_attribute("data-at")) for r in rows.all()]
    assert stamps == sorted(stamps, reverse=True), "история не по убыванию времени"
    results = [r.get_attribute("data-result") for r in rows.all()]
    assert "bad_password" in results and "success" in results
    assert bystander.email not in page.locator("body").inner_text()

    # п. 3: активация-контекст acc.page — «другое устройство»; закрываем его сессию с нового
    page.goto("/me/security/devices/")
    foreign = page.locator("[data-device-id][data-current=false]")
    assert foreign.count() >= 1, "в списке нет второго устройства"
    seen = helpers.mail_ids(mailpit, acc.email)
    helpers.submit(foreign.first.locator('form[action$="/close/"]'))
    acc.page.goto("/me/security/")
    assert "/login/" in acc.page.url, "сессия закрытого устройства жива"
    helpers.sign_in(acc.page, acc)
    helpers.wait_mail(mailpit, acc.email, "new_device", seen=seen, timeout=60)

    # п. 4: администратор — карточка другого сотрудника: устройства и входы
    admin_page.goto(f"/staff/{acc.id}/logins/")
    assert admin_page.locator("[data-device-id]").count() >= 1
    assert admin_page.locator("[data-history-row]").count() >= 3
    assert re.search(r"/staff/\d+/logins/", admin_page.url)
    expect(admin_page.locator("body")).not_to_contain_text(bystander.email)
