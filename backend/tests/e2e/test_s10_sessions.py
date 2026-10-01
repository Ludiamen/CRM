"""T-145: сценарий 10 — выход по бездействию и «Выйти со всех устройств» (FR-028, FR-030, NFR-007)."""
import re
import time

from playwright.sync_api import expect

from tests.e2e import helpers


def test_s10_idle_timeout_logs_out_and_back_button_shows_nothing(employee, new_context):
    """Сценарий 10, п. 1 и 5: после порога бездействия любое действие ведёт на вход с сообщением о
    бездействии; после «Выйти» кнопка «Назад» защищённых страниц не показывает (FR-028, NFR-007).

    Порог в форме не меньше 5 минут (CONTRACT.md); чтобы не ждать их, тест ставит одну минуту прямо в
    базе командой в контейнере и возвращает 60 в `finally`. Форма и журнал значений — test_s17."""
    acc = employee()
    page = new_context().new_page()
    helpers.sign_in(page, acc)
    helpers.set_idle_minutes(1)
    try:
        page.goto("/me/security/")  # новая сессия отсчитывает порог от последнего действия
        time.sleep(75)
        page.goto("/me/")
        page.wait_for_url(re.compile(r"/login/"))
        assert "бездейств" in page.locator("body").inner_text().lower()
        assert page.locator("#top-bar").count() == 0
    finally:
        helpers.set_idle_minutes(60)

    # п. 5: «Выйти», затем «Назад»
    helpers.sign_in(page, acc)
    page.goto("/me/security/")
    helpers.sign_out(page)
    page.go_back()
    page.wait_for_load_state("networkidle")
    assert page.locator("#top-bar").count() == 0, "после выхода «Назад» показал защищённую страницу"
    assert "/me/security/" not in page.url or "/login/" in page.url


def test_s10_logout_everywhere_closes_other_browser_context(employee, new_context):
    """Сценарий 10, п. 3-4 (FR-030): «Выйти со всех устройств» на одном из трёх устройств закрывает
    сессии на двух других (они попадают на вход), а текущая остаётся."""
    acc = employee()
    a = acc.page  # устройство 1: сессия после активации
    b, c = new_context().new_page(), new_context().new_page()
    helpers.sign_in(b, acc)
    helpers.sign_in(c, acc)
    for p in (a, b, c):
        p.goto("/me/security/")
        expect(p.locator("#top-bar")).to_be_visible()

    b.goto("/me/security/")
    helpers.submit(b.locator('form[action="/me/security/logout-everywhere/"]'))
    b.goto("/me/security/")
    expect(b.locator("#top-bar")).to_be_visible()  # текущая осталась
    for closed in (a, c):
        closed.goto("/me/security/")
        assert "/login/" in closed.url, "сессия другого устройства не закрыта"
