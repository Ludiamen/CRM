"""T-12110, сценарий 3: собственная недоступность (FR-764, FR-765)."""
from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_03_set_and_clear_unavailable_until(stand_admin, new_context):
    page = helpers_t12._session(new_context(), stand_admin)
    page.goto("/me/")
    expect(page.locator('form[data-form="availability"]')).to_be_visible()
    future = (date.today() + timedelta(days=30)).strftime("%d.%m.%Y")
    until = page.locator("#id_unavailable_until")
    until.fill(future)
    page.locator('form[data-form="availability"] button[type=submit]').click()
    expect(until).to_have_value(future)
    until.fill("")
    page.locator('form[data-form="availability"] button[type=submit]').click()
    expect(until).to_have_value("")
    expect(page.locator('form[data-form="availability"]')).to_be_visible()
