"""Срез 014: «Мои задания» и 360 px (T-14051)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t14_my_page_renders(admin_page):
    page = admin_page
    page.goto("/approvals/my/")
    expect(page.get_by_role("heading", name="Мои задания")).to_be_visible()
    expect(page.locator("[data-empty-state=assignments], [data-approval-my]")).to_be_visible()


def test_t14_my_page_at_360(admin_page):
    page = admin_page
    page.set_viewport_size({"width": 360, "height": 640})
    page.goto("/approvals/my/")
    expect(page.get_by_role("heading", name="Мои задания")).to_be_visible()
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"), (
        "на 360 px горизонтальная прокрутка страницы"
    )
