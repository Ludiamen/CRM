"""T-10124, сценарий 1: реестр поручений — пресеты, строки, состояние (FR-713, FR-717)."""
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_instructions import cast_for, create_instruction, open_instructions

pytestmark = pytest.mark.e2e
MOSCOW = timezone(timedelta(hours=3))


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def _day(offset=0):
    return (datetime.now(MOSCOW).date() + timedelta(days=offset)).strftime("%d.%m.%Y")


def test_t10_01_registry_rows_and_presets(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    for preset in ("mine", "control", "subordinate", "overdue"):
        expect(page.locator(f'[data-instructions-preset="{preset}"]')).to_be_visible()
    title = helpers_org.unique_name("Реестр")
    instruction_id = create_instruction(page, title, basis="Приказ", assignee=cast.assignee, deadline=_day(5))
    page.goto("/instructions/?preset=control")
    row = page.locator(f'[data-instruction-id="{instruction_id}"]')
    expect(row).to_be_visible()
    expect(row).to_contain_text(title)
    expect(row).to_contain_text(cast.assignee.full_name)
    expect(row).to_contain_text(_day(5))
    expect(page.locator(f'[data-instruction-id="{instruction_id}"][data-instruction-state]')).to_be_visible()
