"""Срез 014: блок «Согласования» в карточке (T-14051)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t14_ticket_card_renders(admin_page):
    page = admin_page
    page.goto("/tickets/")
    import re

    links = page.locator("a[href^='/tickets/']")
    ticket_link = None
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href") or ""
        if re.fullmatch(r"/tickets/\d+/", href):
            ticket_link = links.nth(index)
            break
    if ticket_link is None:
        pytest.skip("на стенде нет заявок")
    ticket_link.click()
    expect(page.locator("[data-ticket-card]")).to_be_visible()
    expect(page.locator("[data-card-fields]")).to_be_visible()
