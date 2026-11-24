"""T-11150, сценарий 5: общие и личные шаблоны ответа (FR-751…754)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t11_05_answer_pages_and_insert_hook(admin_page):
    admin_page.goto("/servicedesk/answers/")
    expect(admin_page.locator('[data-answer-page="list"]')).to_be_visible()
    admin_page.goto("/servicedesk/answers/new/")
    expect(admin_page.locator('[data-answer-page="new"]')).to_be_visible()
    expect(admin_page.locator("[data-answer-id]")).to_have_count(0)

    admin_page.goto("/tickets/1/")
    expect(admin_page.locator("[data-answer-insert]")).to_be_visible()
