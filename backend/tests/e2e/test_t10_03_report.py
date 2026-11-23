"""T-10124, сценарий 3: отчёт к дате и принятие контролёром (FR-706, 717, 723)."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import (accept_report, cast_for, create_instruction, open_card,
                                            open_instructions, submit_report)

pytestmark = pytest.mark.e2e
MOSCOW = timezone(timedelta(hours=3))


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_03_assignee_reports_and_controller_accepts(cast, new_context):
    deadline = (datetime.now(MOSCOW).date() + timedelta(days=20)).isoformat()
    head_page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(head_page, "Отчёт и принятие", basis="Приказ",
                                        assignee=cast.assignee, deadline=deadline, periodicity="weekly")
    page = open_card(new_context(), cast.assignee, instruction_id)
    date_id = page.locator("[data-report-date]").first.get_attribute("data-report-date")
    submit_report(page, "Работа выполнена")
    expect(page.locator(f'[data-report-date="{date_id}"] [data-report-state]')).to_have_text(re.compile("проверк"))

    controller = open_card(new_context(), cast.head, instruction_id)
    accept_report(controller, date_id)
    expect(controller.locator(f'[data-report-date="{date_id}"] [data-report-state]')).to_have_text(
        re.compile("Принято"))
