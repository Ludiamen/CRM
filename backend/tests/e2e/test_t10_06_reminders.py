"""T-10124, сценарий 6: лестница напоминаний в карточке (FR-709, 710)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import cast_for, create_instruction, open_card, open_instructions

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_06_ladder_visible_and_editable_for_author(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(page, "Лестница напоминаний", basis="Приказ", assignee=cast.assignee)
    card = open_card(new_context(), cast.head, instruction_id)
    expect(card.locator("[data-ladder]")).to_be_visible()
    expect(card.locator('form[data-form="instruction-ladder"]')).to_be_visible()
    expect(card.locator("[data-ladder-offset]").first).to_be_visible()
