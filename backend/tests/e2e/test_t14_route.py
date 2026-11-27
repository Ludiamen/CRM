"""Срез 014: страница маршрута и шаблоны (T-14051)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t14_templates_page_and_form(admin_page):
    page = admin_page
    page.goto("/approvals/")
    expect(page.get_by_role("heading", name="Согласования")).to_be_visible()
    page.get_by_role("link", name="Новый шаблон").click()
    expect(page.locator("[data-approval-template-form]")).to_be_visible()
    expect(page.locator('input[name="name"]')).to_be_visible()
    expect(page.locator('textarea[name="stages_text"]')).to_be_visible()


def test_t14_route_page_requires_route(admin_page):
    page = admin_page
    response = page.goto("/approvals/routes/999999/")
    assert response.status == 404
