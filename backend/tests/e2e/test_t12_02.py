"""T-12110, сценарий 2: добавление и снятие наблюдателя (FR-766, FR-767).

Отдельной сессии второго сотрудника в фикстурах нет, поэтому полноценная
проверка действий наблюдателя здесь не подменяется моками; проверяются формы,
``data-user-id`` и неизменность активного состава после обратного действия.
"""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_02_observer_add_remove_without_changing_queue_people(stand_admin, new_context):
    page = helpers_t12.open_queue(new_context(), stand_admin)
    row = page.locator('[data-unit-id][data-queue="true"]').filter(has_text="E2E 012 Всем").first
    expect(row).to_be_visible()
    queue_id = row.get_attribute("data-unit-id")
    assert queue_id
    helpers_t12.open_observers(page, queue_id)
    observer_list = page.locator("[data-observer-list]")
    initial_ids = sorted(observer_list.locator("[data-observer]").evaluate_all(
        "(items) => items.map((item) => item.dataset.userId)"
    ))
    select = page.locator('form[data-form="observer-add"] select[name="user"]')
    expect(select).to_be_visible()
    values = select.locator("option").evaluate_all("(items) => items.map((item) => item.value)")
    candidate = next((value for value in values if value not in initial_ids), None)
    if candidate is None:
        pytest.fail("seed не предоставил отдельного сотрудника для формы наблюдателя")
    helpers_t12.add_observer(page, candidate)
    expect(page.locator(f'[data-observer][data-user-id="{candidate}"]')).to_be_visible()
    page.locator(
        f'[data-observer][data-user-id="{candidate}"] form[data-form="observer-remove"] '
        'button[type=submit]'
    ).click()
    expect(page.locator(f'[data-observer][data-user-id="{candidate}"]')).to_have_count(0)
    final_ids = sorted(observer_list.locator("[data-observer]").evaluate_all(
        "(items) => items.map((item) => item.dataset.userId)"
    ))
    assert final_ids == initial_ids
    expect(page.locator('form[data-form="observer-add"]')).to_be_visible()
