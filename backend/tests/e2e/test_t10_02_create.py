"""T-10124, сценарий 2: создание поручения и отказ пустого названия (FR-700…704)."""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_instructions import cast_for, create_instruction, open_instructions

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_02_empty_title_refused_and_valid_create_opens_card(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    page.goto("/instructions/new/")
    form = page.locator('form[data-form="instruction-new"]')
    from datetime import datetime, timedelta, timezone

    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    form.locator('[data-instruction-field="basis_kind"]').select_option(label="Приказ")
    form.locator('[data-instruction-field="basis_number"]').fill("12")
    form.locator('[data-instruction-field="basis_date"]').fill(today.strftime("%d.%m.%Y"))
    form.locator('[data-instruction-field="assignee"]').select_option(str(cast.assignee.id))
    form.locator('[data-instruction-field="deadline"]').fill((today + timedelta(days=7)).strftime("%d.%m.%Y"))
    form.locator('[data-instruction-field="title"]').fill("")
    form.locator("button[type=submit]").first.click()
    expect(page.locator('[data-error="title"][data-code="title_range"]')).to_be_visible()

    title = helpers_org.unique_name("Создание")
    instruction_id = create_instruction(page, title, basis="Приказ", assignee=cast.assignee)
    expect(page.locator('[data-instructions-page="card"]')).to_be_visible()
    expect(page.locator(f'[data-instruction-id="{instruction_id}"]')).to_be_visible()
    expect(page.locator("[data-instruction-title]")).to_have_text(title)
