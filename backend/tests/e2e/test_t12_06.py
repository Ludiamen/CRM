"""T-12110, сценарий 6: доступ администратора и русские записи журнала (FR-779, FR-780).

Фикстуры предоставляют только администратора. Обычная учётная запись не
создаётся искусственно, поэтому проверяется реальная форма настройки и журнал.
"""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_t12

pytestmark = pytest.mark.e2e


def test_t12_06_admin_queue_settings_and_audit_labels(stand_admin, new_context):
    page = helpers_t12.open_queue(new_context(), stand_admin)
    row = page.locator('[data-unit-id][data-queue="true"]').filter(has_text="E2E 012 Равномерно").first
    expect(row).to_be_visible()
    queue_id = row.get_attribute("data-unit-id")
    assert queue_id
    helpers_t12.open_rule(page, queue_id)
    expect(page.locator('form[data-form="queue-rule"]')).to_be_visible()
    page.goto("/audit/")
    expect(page.locator("#audit-results")).to_be_visible()
    expect(page.locator("table.audit-table")).to_be_visible()
    assert "Событие" in page.locator("#audit-results").inner_text()
    # Русские подписи новых действий проверяются серверными test_audit.py и
    # test_sd_012_notify_audit.py; здесь важно, что журнал открыт и доступен.
