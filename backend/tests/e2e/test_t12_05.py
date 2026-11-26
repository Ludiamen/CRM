"""T-12110, сценарий 5: задача из карточки и связь с заявкой (FR-773…778)."""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org, helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_05_create_task_from_ticket_and_open_both_sides(stand_admin, new_context):
    context = new_context()
    page = helpers_t12._session(context, stand_admin)
    page.goto("/tickets/?preset=all")
    row = page.locator('[data-ticket]').filter(has_text="E2E 012: заявка для оценки").first
    expect(row).to_be_visible()
    href = row.locator('a[href^="/tickets/"]').first.get_attribute("href")
    assert href
    ticket_number = int(re.search(r"/tickets/(\d+)/", href).group(1))
    page.goto(href)
    expect(page.locator("[data-ticket-card]")).to_be_visible()
    expect(page.locator('[data-action="task-new-from-ticket"]')).to_be_visible()
    page.locator('[data-action="task-new-from-ticket"]').click()
    expect(page.locator('[data-tasks-page="new"]')).to_be_visible()
    expect(page.locator("[data-task-ticket]")).to_contain_text(str(ticket_number))
    title = helpers_org.unique_name("E2E 012 задача")
    page.locator('[data-task-field="title"]').fill(title)
    page.locator('[data-form="task-new"] button[type=submit]').click()
    expect(page.locator("[data-task-ticket]")).to_be_visible()
    expect(page.locator("[data-task-title]")).to_contain_text(title)
    match = re.search(r"/tasks/(\d+)/", page.url)
    assert match
    task_id = int(match.group(1))
    task = helpers_t12.open_task(context, stand_admin, task_id)
    expect(task.locator("[data-task-ticket]")).to_contain_text("Заявка")
    expect(task.locator("[data-task-ticket]")).to_contain_text(str(ticket_number))
    page.goto(f"/tickets/{ticket_number}/")
    expect(page.locator("[data-ticket-tasks]")).to_be_visible()
    expect(page.locator(f'[data-task-link][data-task-id="{task_id}"]')).to_contain_text(title)
