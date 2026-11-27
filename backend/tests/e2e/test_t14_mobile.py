"""Срез 014: мобильные страницы согласований (T-14051)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_t14_mobile_template_form(admin_page):
    page = admin_page
    page.set_viewport_size({"width": 360, "height": 640})
    page.goto("/approvals/templates/new/")
    expect(page.locator("[data-approval-template-form]")).to_be_visible()
    assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"), (
        "на 360 px горизонтальная прокрутка страницы"
    )
