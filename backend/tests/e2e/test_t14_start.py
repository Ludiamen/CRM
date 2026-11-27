"""Срез 014: запуск из карточки (T-14015)."""
import pytest

pytestmark = pytest.mark.e2e


def test_t14_start_requires_post(admin_page):
    page = admin_page
    response = page.goto("/approvals/start/")
    assert response.status == 405
