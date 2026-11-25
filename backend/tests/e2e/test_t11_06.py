"""T-11150, сценарий 6: 360 px, русский интерфейс и Europe/Moscow (FR-757, FR-758)."""
import pytest

from tests.e2e.helpers_sla import check_360, prepare_sla_stand

pytestmark = pytest.mark.e2e


def test_t11_06_sla_report_and_answers_fit_phone(stand_admin, admin_page):
    prepare_sla_stand(stand_admin)
    for url in ("/servicedesk/sla/", "/servicedesk/reports/?period=month",
                "/servicedesk/answers/"):
        admin_page.goto(url)
        check_360(admin_page)
    assert admin_page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone") == "Europe/Moscow"
