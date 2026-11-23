"""T-10124, сценарий 5: перенос срока и решение контролёра (FR-708)."""
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import (cast_for, create_instruction, decide_transfer, open_card,
                                            open_instructions, request_transfer)

pytestmark = pytest.mark.e2e
MOSCOW = timezone(timedelta(hours=3))


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_05_request_and_approve_transfer(cast, new_context):
    new_day = (datetime.now(MOSCOW).date() + timedelta(days=30)).isoformat()
    head_page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(head_page, "Перенос срока", basis="Приказ", assignee=cast.assignee)
    page = open_card(new_context(), cast.assignee, instruction_id)
    request_transfer(page, new_day, "Нужно больше времени")
    transfer_id = page.locator('[data-transfer][data-transfer-state="pending"]').first.get_attribute("data-transfer")

    controller = open_card(new_context(), cast.head, instruction_id)
    decide_transfer(controller, transfer_id, approve=True, comment="Согласовано")
    expect(controller.locator(f'[data-transfer="{transfer_id}"]')).to_have_attribute("data-transfer-state", "approved")
