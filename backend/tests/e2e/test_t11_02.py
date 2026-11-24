"""T-11150, сценарий 2: сроки заявки и блок SLA в карточке (FR-734…740, FR-742)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t11_02_sla_contract_hooks_are_defined(admin_page):
    """Проверяет контрактные корни карточки; данные заявок создаются следующим этапом."""
    admin_page.goto("/tickets/1/")
    sla = admin_page.locator("[data-sla]")
    expect(sla).to_be_visible()
    for name in ("reaction-due", "solution-due", "reaction-fact", "solution-fact",
                 "reaction-verdict", "solution-verdict"):
        expect(sla.locator(f'[data-{name}]')).to_be_visible()
