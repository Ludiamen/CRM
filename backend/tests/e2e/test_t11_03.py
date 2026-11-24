"""T-11150, сценарий 3: фильтры просрочки и срока сегодня (FR-741, FR-742)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t11_03_due_filters_and_counters(admin_page):
    for due in ("overdue", "today"):
        admin_page.goto(f"/tickets/?due={due}")
        expect(admin_page.locator(f'[data-due="{due}"]')).to_be_visible()
        expect(admin_page.locator(f'[data-due-count="{due}"]')).to_be_visible()

        response = admin_page.request.get(f"/tickets/count/?due={due}")
        assert response.ok
