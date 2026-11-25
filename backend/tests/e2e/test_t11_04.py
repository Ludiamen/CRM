"""T-11150, сценарий 4: отчёт руководителя и выгрузка Excel (FR-746…750)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_sla import export_xlsx, open_report, prepare_sla_stand

pytestmark = pytest.mark.e2e


def test_t11_04_manager_report_and_excel(stand_admin, new_context):
    prepare_sla_stand(stand_admin)
    page = open_report(new_context(), stand_admin, period="month")
    expect(page.locator("[data-report-page]")).to_be_visible()
    expect(page.locator('[data-report-period="month"]')).to_be_visible()
    expect(page.locator("[data-report-row]").first).to_be_visible()
    assert export_xlsx(page)
