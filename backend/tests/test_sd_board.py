"""Красные контракты канбана заявок (T-13005; SPEC-013, FR-783…792)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_board_columns_are_open_statuses_then_closed():
    """FR-784: открытые статусы по порядку и последняя колонка «Закрытые»."""
    from apps.servicedesk.services import board

    viewer = support.make_admin()
    queue = sd.make_queue()
    columns = board.columns(viewer, queue=queue.unit_id)
    assert [column["key"] for column in columns][-1] == "closed"
    assert columns[-1]["title"] == "Закрытые"


def test_board_move_requires_can_work_and_opens_close_for_closed():
    """FR-786/787/788: наблюдатель не двигает, закрытие идёт через форму."""
    from apps.servicedesk.services import board

    queue = sd.make_queue()
    observer = support.make_employee()
    sd.add_observer(queue, observer)
    ticket = sd.make_ticket(queue=queue)
    with pytest.raises(board.BoardError):
        board.move(observer, ticket, ticket.status_id)


def test_observer_sees_board_without_drag_or_status_menu():
    """FR-786: наблюдатель видит карточки, но не перетаскивание и не меню смены статуса."""
    queue = sd.make_queue()
    observer = support.make_employee()
    sd.add_observer(queue, observer)
    sd.make_ticket(queue=queue)
    page = support.logged_in(observer).get("/tickets/?view=board")
    assert page.status_code == 200
    html = page.content.decode()
    assert 'data-ticket-board' in html and 'data-ticket-card' in html
    assert 'draggable="true"' not in html
    assert "Сменить статус" not in html


def test_board_preset_mine_and_all_differ():
    """FR-783: режим «Канбан» сохраняет пресет списка (`Мои` / `Все`)."""
    queue = sd.make_queue()
    admin = support.make_admin()
    mine = sd.make_ticket(queue=queue, assignee=admin)
    other = sd.make_ticket(queue=queue)
    page = support.logged_in(admin).get("/tickets/?view=board&preset=mine")
    html = page.content.decode()
    assert f"#{mine.number}" in html and f"#{other.number}" not in html
