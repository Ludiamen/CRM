"""T-10124, сценарий 9: права — чужое 404, руководитель только читает (FR-719, 721)."""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_notify
from tests.e2e.helpers_instructions import cast_for, create_instruction, open_card, open_instructions

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_09_outsider_404_and_manager_cannot_decide(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(page, "Права доступа", basis="Приказ", assignee=cast.assignee)
    context = new_context()
    context.clear_cookies()
    helpers_notify.adopt_session(context, cast.outsider)
    outsider = context.new_page()
    response = outsider.goto(f"/instructions/{instruction_id}/")
    assert response.status == 404

    manager = open_card(new_context(), cast.head, instruction_id)
    expect(manager.locator('[data-decide="accept"]')).to_have_count(0)
