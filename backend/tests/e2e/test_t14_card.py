"""Срез 014: блок «Согласования» в карточке (T-14051)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t14_ticket_card_renders(admin_page):
    page = admin_page
    page.goto("/tickets/")
    cards = page.locator("a[href^='/tickets/'][href$='/']")
    if cards.count() == 0:
        pytest.skip("на стенде нет заявок")
    cards.first.click()
    expect(page.locator("[data-ticket-card]")).to_be_visible()
    expect(page.locator("[data-card-fields]")).to_be_visible()
