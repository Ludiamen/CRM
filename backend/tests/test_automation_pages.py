"""Страницы автоматизации и доски (T-13040/T-13011; SPEC-013, FR-783/793)."""
import pytest

from tests import support

pytestmark = pytest.mark.django_db


def test_board_page_and_rules_page_render_for_admin():
    admin = support.make_admin()
    client = support.logged_in(admin)
    board = client.get("/tickets/board/")
    assert board.status_code == 200
    assert "data-ticket-board" in board.content.decode()
    rules = client.get("/automation/")
    assert rules.status_code == 200
    assert "Новое правило" in rules.content.decode()
    form = client.get("/automation/new/")
    assert form.status_code == 200
    assert "Действия" in form.content.decode()


def test_rules_page_is_closed_for_employee_without_rights():
    client = support.logged_in(support.make_employee())
    assert client.get("/automation/").status_code == 403
    assert client.get("/automation/runs/").status_code == 403
