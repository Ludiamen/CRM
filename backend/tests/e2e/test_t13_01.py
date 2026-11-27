"""Срез 013: доска заявок, страница правил и 360 px (T-13051)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t13_01_board_renders_columns_and_cards(admin_page):
    page = admin_page
    page.goto("/tickets/board/")
    expect(page.locator("[data-ticket-board]")).to_be_visible()
    columns = page.locator("[data-column]")
    assert columns.count() >= 2
    expect(page.locator('[data-column="closed"]')).to_be_visible()
    expect(page.locator("[data-ticket-card]").first).to_be_visible()
    page.screenshot(path="/home/gpgr/Документы/CRM/crm-work/slice013/stage4/manual/board-desktop.png", full_page=True)


def test_t13_02_rules_page_and_form(admin_page):
    page = admin_page
    page.goto("/automation/")
    expect(page.get_by_role("heading", name="Автоматизация")).to_be_visible()
    page.get_by_role("link", name="Новое правило").click()
    expect(page.locator("form.card")).to_be_visible()
    page.screenshot(path="/home/gpgr/Документы/CRM/crm-work/slice013/stage4/manual/rule-form.png", full_page=True)
    expect(page.locator('textarea[name="conditions_text"]')).to_be_visible()
    expect(page.locator('select[name$="-0-kind"]')).to_be_visible()


def test_t13_03_board_at_360(admin_page):
    page = admin_page
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto("/tickets/board/")
    expect(page.locator("[data-ticket-board]")).to_be_visible()
    page.screenshot(path="/home/gpgr/Документы/CRM/crm-work/slice013/stage4/manual/board-360.png", full_page=True)
    assert page.evaluate("""() => document.body.scrollWidth <= window.innerWidth
      && ['hidden', 'clip'].includes(getComputedStyle(document.documentElement).overflowX)"""), (
        "на 360 px горизонтальная прокрутка страницы"
    )


def test_t13_04_card_menu_moves_to_next_column(admin_page):
    page = admin_page
    page.goto("/tickets/board/")
    columns = page.locator("[data-column]")
    if columns.count() < 2:
        pytest.skip("нет двух открытых колонок")
    card = columns.nth(0).locator("[data-ticket-card]").first
    if card.count() == 0:
        pytest.skip("нет карточек в первой колонке")
    number = card.get_attribute("data-number")
    target_key = columns.nth(1).get_attribute("data-column")
    form = card.locator("form.ticket-board-card-menu")
    form.locator("select[name=status]").select_option(target_key)
    form.locator("button[type=submit]").click()
    page.wait_for_load_state("networkidle")
    target = page.locator(f'[data-column="{target_key}"]')
    expect(target.locator(f'[data-ticket-card][data-number="{number}"]').first).to_be_visible()
