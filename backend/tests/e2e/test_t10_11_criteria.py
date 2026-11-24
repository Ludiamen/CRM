"""T-10308: критерий успеха — поручение с основанием и отчётом за минуту (FR-700, 706)."""
import os
import time
from pathlib import Path

import pytest

from tests.e2e.helpers_instructions import (cast_for, create_instruction, open_card, open_instructions,
                                            submit_report)

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    return cast_for(browser, admin_page, mailpit, new_context)


def test_t10_11_one_minute_instruction_with_basis_and_report(cast, new_context):
    page = open_instructions(new_context(), cast.head)
    started = time.monotonic()
    instruction_id = create_instruction(page, "Критерий минуты", basis="Приказ", assignee=cast.assignee,
                                        periodicity="weekly")
    assignee_page = open_card(new_context(), cast.assignee, instruction_id)
    submit_report(assignee_page, "Работа выполнена в срок")
    elapsed = time.monotonic() - started
    target = os.environ.get("E2E_TIMING_OUT")
    if target:
        Path(target).write_text(f"instruction_id={instruction_id}\nseconds={elapsed:.2f}\n", encoding="utf-8")
    assert elapsed < 60, f"поручение с основанием и отчётом заняло {elapsed:.1f} с"
