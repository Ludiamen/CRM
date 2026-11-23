"""T-10124, сценарий 8: связь с задачами (FR-716)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import cast_for, create_instruction, open_card, open_instructions

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_08_assignee_sees_task_section_controller_does_not(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(page, "Задачи из поручения", basis="Приказ", assignee=cast.assignee)
    assignee_card = open_card(new_context(), cast.assignee, instruction_id)
    expect(assignee_card.locator("[data-instruction-tasks]")).to_be_visible()
    expect(assignee_card.locator('form[data-form="instruction-task"]')).to_be_visible()

    controller_card = open_card(new_context(), cast.head, instruction_id)
    expect(controller_card.locator('form[data-form="instruction-task"]')).to_have_count(0)
