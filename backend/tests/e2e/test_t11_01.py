"""T-11150, сценарий 1: администратор настраивает уровень SLA (FR-730…733)."""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_sla import create_level, open_sla

pytestmark = pytest.mark.e2e


def test_t11_01_admin_creates_binds_archives_and_restores_level(stand_admin, new_context):
    page = open_sla(new_context(), stand_admin)
    page.goto("/servicedesk/sla/new/")
    form = page.locator('[data-sla-page="new"]')
    expect(form).to_be_visible()
    form.locator("button[type=submit]").click()
    expect(page.locator('[data-error="title"][data-code="sla_title_range"]')).to_be_visible()

    title = helpers_org.unique_name("SLA")
    level_id = create_level(page, title, priority=1, reaction_minutes=30, solution_minutes=240,
                            workdays=(0, 1, 2, 3, 4))
    row = page.locator(f'[data-sla-id="{level_id}"]')
    expect(row).to_be_visible()

    row.locator("form[action$='/archive/'] button[type=submit]").click()
    page.wait_for_load_state()
    expect(page.locator(f'[data-sla-id="{level_id}"]').first).to_contain_text("в архиве")
    archived = open_sla(new_context(), stand_admin, archived=True)
    expect(archived.locator(f'[data-sla-id="{level_id}"]')).to_be_visible()
    archived.locator(f'[data-sla-id="{level_id}"] form[action$="/archive/"] button[type=submit]').click()
    archived.wait_for_load_state()
    active = open_sla(new_context(), stand_admin)
    expect(active.locator(f'[data-sla-id="{level_id}"]')).to_be_visible()
