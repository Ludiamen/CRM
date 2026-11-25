"""T-11150, сценарий 2: сроки заявки и блок SLA в карточке (FR-734…740, FR-742)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_sla import prepare_sla_stand

pytestmark = pytest.mark.e2e


def _open_seeded_card(page):
    """Открывает карточку заявки из наполнения `e2e_sla_seed` (тема начинается с «E2E SLA»)."""
    page.goto("/tickets/?preset=all")
    link = page.locator('a[href^="/tickets/"]', has_text="E2E SLA").first
    expect(link).to_be_visible()
    href = link.get_attribute("href")
    page.goto(href)
    page.wait_for_load_state()


def test_t11_02_sla_contract_hooks_are_defined(stand_admin, admin_page):
    """FR-734…740, 742: блок SLA в карточке заявки из наполнения стенда."""
    prepare_sla_stand(stand_admin)
    _open_seeded_card(admin_page)
    sla = admin_page.locator("[data-sla]")
    expect(sla).to_be_visible()
    for name in ("reaction-due", "solution-due", "reaction-fact", "solution-fact",
                 "reaction-verdict", "solution-verdict"):
        expect(sla.locator(f'[data-{name}]')).to_be_visible()
