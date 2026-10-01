"""T-142: сценарий 4 — обычный вход с двумя факторами (FR-021, FR-034, FR-039)."""
import re
import time

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_s04_login_two_factors_under_30_seconds(employee, new_context):
    """Сценарий 4, п. 1-4 и критерий успеха: вход «почта, пароль, код» занимает меньше 30 секунд и
    отражён в истории; неверный код и неверная пара не входят, сообщения о паре не различаются;
    защищённая страница ведёт на вход и возвращает после него (FR-021, FR-034, FR-039)."""
    acc = employee()
    page = new_context().new_page()

    # п. 3: «не та почта» и «не тот пароль» — одно и то же сообщение
    helpers.fill_login(page, factories.new_email("nobody"), factories.new_password())
    unknown = helpers.alert_text(page)
    helpers.fill_login(page, acc.email, factories.new_password())
    wrong_password = helpers.alert_text(page)
    assert unknown and unknown == wrong_password

    # п. 2: верный пароль и неверный код — не входит
    helpers.fill_login(page, acc.email, acc.password)
    page.wait_for_url(re.compile(r"/login/code/"))
    page.fill("input[name=code]", helpers.wrong_code(acc.totp_secret))
    page.click("button[type=submit]")
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert page.locator("#top-bar").count() == 0

    # п. 4: защищённая страница → вход → возврат на неё
    helpers.wait_fresh_step(acc.totp_secret)  # ожидание шага TOTP — не часть времени входа
    started = time.monotonic()
    page.goto("/me/security/")
    assert "/login/" in page.url
    page.fill("input[name=email]", acc.email)
    page.fill("input[name=password]", acc.password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/login/code/"))
    page.fill("input[name=code]", helpers.totp_for(acc.totp_secret))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/me/security/"))
    expect(page.locator("#top-bar")).to_be_visible()
    assert time.monotonic() - started < 30, "вход с двумя факторами занял 30 секунд и больше"

    # п. 1: вход записан в историю
    page.goto("/me/security/history/")
    results = [r.get_attribute("data-result") for r in page.locator("[data-history-row]").all()]
    assert "success" in results and "bad_code" in results and "bad_password" in results
