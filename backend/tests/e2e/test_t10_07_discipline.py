"""T-10124, сценарий 7: дисциплина и Excel (FR-714, 715)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import cast_for, export_excel, open_discipline

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_07_discipline_table_and_excel(cast, new_context):
    page = open_discipline(new_context(), cast.head)
    expect(page.locator("[data-discipline-table]")).to_be_visible()
    expect(page.locator("[data-discipline-row]").first).to_be_visible()
    path = export_excel(page)
    assert path
