"""T-10124, сценарий 10: телефон 360 px — реестр, карточка, дисциплина (FR-720, NFR-725)."""
import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import (cast_for, check_360, create_instruction, open_card,
                                            open_discipline, open_instructions)

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_10_phone_layout(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(page, "Телефон 360", basis="Приказ", assignee=cast.assignee)
    page.goto("/instructions/")
    check_360(page)
    card = open_card(new_context(), cast.head, instruction_id)
    card.set_viewport_size({"width": 360, "height": 800})
    expect(card.get_by_role("link", name="Назад")).to_be_visible()
    discipline = open_discipline(new_context(), cast.head)
    check_360(discipline)
