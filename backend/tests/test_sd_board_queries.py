"""NFR-745: число запросов доски не зависит от количества заявок (T-13052)."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_board_columns_use_at_most_twelve_queries():
    viewer = support.make_admin()
    queue = sd.make_queue()
    for _ in range(60):
        sd.make_ticket(queue=queue)
    from apps.servicedesk.services import board

    with CaptureQueriesContext(connection) as captured:
        columns = board.columns(viewer, preset="all")
    assert columns and len(captured) <= 12, f"запросов доски: {len(captured)}"
