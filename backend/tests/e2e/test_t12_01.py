"""T-12110, сценарий 1: режимы правила очереди (FR-759, FR-760…763)."""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_01_queue_rule_modes_and_htmx(stand_admin, new_context):
    page = helpers_t12.open_queue(new_context(), stand_admin)
    row = page.locator('[data-unit-id][data-queue="true"]').filter(has_text="E2E 012 Равномерно").first
    expect(row).to_be_visible()
    queue_id = row.get_attribute("data-unit-id")
    assert queue_id
    helpers_t12.open_rule(page, queue_id)
    mode = page.locator('[data-queue-rule-field="mode"]')
    expect(mode).to_have_value("evenly")
    for value in ("strictly", "all"):
        mode.select_option(value)
        mode.locator("xpath=ancestor::form").locator("button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        expect(mode).to_have_value(value)
        expect(page.locator('[data-queue-rule-page]')).to_be_visible()
        expect(page.locator('[role="alert"]')).to_have_count(0)
