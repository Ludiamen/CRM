"""T-11150, сценарий 5: общие и личные шаблоны ответа (FR-751…754)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_sla import prepare_sla_stand

pytestmark = pytest.mark.e2e


def test_t11_05_answer_pages_and_insert_hook(stand_admin, admin_page):
    prepare_sla_stand(stand_admin)
    admin_page.goto("/servicedesk/answers/")
    expect(admin_page.locator('[data-answer-page="list"]')).to_be_visible()
    admin_page.goto("/servicedesk/answers/new/")
    expect(admin_page.locator('[data-answer-page="new"]')).to_be_visible()
    expect(admin_page.locator("[data-answer-id]")).to_have_count(0)

    admin_page.goto("/tickets/?preset=all")
    row = admin_page.locator("tr", has_text="E2E SLA").first
    expect(row).to_be_visible()
    admin_page.goto(row.locator('a[href^="/tickets/"]').first.get_attribute("href"))
    expect(admin_page.locator("[data-answer-insert]")).to_be_visible()
