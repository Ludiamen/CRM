"""T-10124, сценарий 4: возврат отчёта с причиной и повторная отправка (FR-706)."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e.helpers_instructions import (accept_report, cast_for, create_instruction, open_card,
                                            open_instructions, return_report, submit_report)

pytestmark = pytest.mark.e2e
MOSCOW = timezone(timedelta(hours=3))


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_04_return_requires_reason_and_resubmit(cast, new_context):
    deadline = (datetime.now(MOSCOW).date() + timedelta(days=20)).isoformat()
    head_page = open_instructions(new_context(), cast.head)
    instruction_id = create_instruction(head_page, "Возврат отчёта", basis="Приказ",
                                        assignee=cast.assignee, deadline=deadline, periodicity="weekly")
    page = open_card(new_context(), cast.assignee, instruction_id)
    date_id = page.locator("[data-report-date]").first.get_attribute("data-report-date")
    submit_report(page, "Первый вариант")

    controller = open_card(new_context(), cast.head, instruction_id)
    return_report(controller, date_id, "Нужны детали")
    expect(controller.locator(f'[data-report-date="{date_id}"] [data-report-state]')).to_have_text(
        re.compile("возвращено", re.I))

    again = open_card(new_context(), cast.assignee, instruction_id)
    submit_report(again, "Доработано")
    controller = open_card(new_context(), cast.head, instruction_id)
    accept_report(controller, date_id)
