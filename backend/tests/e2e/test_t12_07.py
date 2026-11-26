"""T-12110, сценарий 7: 360 px, русский интерфейс и Europe/Moscow (FR-781, FR-782)."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_07_queue_card_rule_and_rating_fit_phone(stand_admin, new_context):
    context = new_context()
    page = helpers_t12.open_queue(context, stand_admin)
    row = page.locator('[data-unit-id][data-queue="true"]').filter(has_text="E2E 012 Равномерно").first
    expect(row).to_be_visible()
    queue_id = row.get_attribute("data-unit-id")
    assert queue_id
    helpers_t12.check_360(page)
    assert "очеред" in page.locator("body").inner_text().lower()
    page.goto("/tickets/?preset=closed")
    ticket_row = page.locator('[data-ticket]').filter(has_text="E2E 012: заявка для оценки").first
    expect(ticket_row).to_be_visible()
    href = ticket_row.locator('a[href^="/tickets/"]').first.get_attribute("href")
    assert href
    ticket_number = int(re.search(r"/tickets/(\d+)/", href).group(1))
    page.goto(href)
    expect(page.locator("[data-ticket-card]")).to_be_visible()
    helpers_t12.check_360(page)
    helpers_t12.open_rule(page, queue_id)
    helpers_t12.check_360(page)
    rating = helpers_t12.open_rating(context, ticket_number)
    helpers_t12.check_360(rating)
    expect(rating.locator("body")).to_contain_text("Оценка заявки")
    assert rating.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone") == "Europe/Moscow"
