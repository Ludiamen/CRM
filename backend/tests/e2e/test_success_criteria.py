"""T-151: критерии успеха спеки, измеряемые временем (FR-008, FR-009, FR-013, FR-021, NFR-003).

«Новая роль создаётся и назначается не дольше 2 минут» меряет test_s12_roles (T-146). Критерии с нагрузкой
(500 мс для 95 % при 100 пользователях) — tests/load (locust), не e2e.
"""
import re
import time

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_invitation_created_within_1_minute_mail_within_1_minute(admin_page, mailpit):
    """Критерии 1-2: администратор создаёт сотрудника и отправляет приглашение не дольше минуты; письмо в
    ящике не позже минуты после создания (FR-008, FR-009, NFR-003)."""
    email = factories.new_email("emp")
    started = time.monotonic()
    helpers.create_employee(admin_page, email, full_name="Сидоров Сидор Сидорович", position="Инженер")
    created = time.monotonic()
    assert created - started < 60, f"создание и приглашение заняли {created - started:.0f} с"
    mail = helpers.wait_mail(mailpit, email, "invitation", timeout=60)
    assert time.monotonic() - created < 60, "письмо-приглашение позже минуты после создания"
    assert helpers.link_in(mail, "/activate/")


def test_activation_within_5_minutes_without_admin_help(admin_page, mailpit, new_context):
    """Критерий 3: сотрудник проходит активацию (профиль, пароль, второй фактор, сохранение кодов) не
    дольше пяти минут с первой попытки, без участия администратора (FR-013)."""
    email, password = factories.new_email("emp"), factories.new_password()
    helpers.create_employee(admin_page, email)
    link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
    page = new_context().new_page()  # администратор дальше ничего не делает
    started = time.monotonic()
    helpers.walk_activation(page, link, password)
    expect(page.locator("#top-bar")).to_be_visible()
    assert time.monotonic() - started < 300, "активация заняла пять минут и больше"
    assert re.search(r"/(?!activate)", page.url)


def test_login_with_two_factors_within_30_seconds(employee, new_context):
    """Критерий 4: обычный вход с двумя факторами — не больше 30 секунд (FR-021). Ожидание нового
    30-секундного шага TOTP в замер не входит: оно нужно лишь тесту, который только что использовал код."""
    acc = employee()
    page = new_context().new_page()
    helpers.wait_fresh_step(acc.totp_secret)
    started = time.monotonic()
    helpers.sign_in(page, acc)
    assert time.monotonic() - started < 30, "вход с двумя факторами занял 30 секунд и больше"
