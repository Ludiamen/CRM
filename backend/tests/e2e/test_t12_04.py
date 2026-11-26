"""T-12110, сценарий 4: публичная оценка и изменение оценки (FR-769…772)."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_04_rate_closed_ticket_and_change_score(stand_admin, new_context):
    context = new_context()
    staff = helpers_t12._session(context, stand_admin)
    staff.goto("/tickets/?preset=closed")
    row = staff.locator('[data-ticket]').filter(has_text="E2E 012: заявка для оценки").first
    expect(row).to_be_visible()
    href = row.locator('a[href^="/tickets/"]').first.get_attribute("href")
    assert href
    ticket_number = int(re.search(r"/tickets/(\d+)/", href).group(1))
    rating = helpers_t12.open_rating(context, ticket_number)
    helpers_t12.rate(rating, "012E2EDEM01", 5)
    expect(rating.locator("[data-rating-state]")).to_contain_text("Спасибо")
    assert "012E2EDEM01" not in rating.url
    rating.goto(f"/rate/?ticket={ticket_number}")
    expect(rating.locator('[data-form="rating"]')).to_be_visible()
    helpers_t12.rate(rating, "012E2EDEM01", 4)
    expect(rating.locator("[data-rating-state]")).to_contain_text("Спасибо")
    assert "012E2EDEM01" not in rating.url
