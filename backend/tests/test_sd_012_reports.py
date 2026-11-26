"""T-12108: красные серверные тесты показателя оценки и Excel (FR-772)."""
import io
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _manager_tree():
    tree = org.make_tree({"Управляемый": {"Сеть": {}}, "Чужой": {}})
    manager = support.make_with_permissions("servicedesk.reports")
    org.make_member(manager, tree["Управляемый"], mark="head")
    return manager, tree


def _report(manager, **params):
    params = {"period": "month", **params}
    return support.logged_in(manager).get("/servicedesk/reports/", params)


def _body(response):
    return response.content.decode("utf-8", "replace")


def test_requester_rating_has_average_one_decimal_and_count():
    manager, tree = _manager_tree()
    for score in (4, 5):
        ticket = sd.make_ticket(queue=tree["Сеть"])
        sd.make_rating(ticket, score=score, closed_at=timezone.now())
    response = _report(manager)
    body = _body(response)
    assert response.status_code == 200
    assert 'data-key="requester_rating"' in body
    assert 'data-value="4.5"' in body
    assert 'data-count="2"' in body


def test_requester_rating_is_dash_when_there_are_no_current_ratings():
    manager, _ = _manager_tree()
    body = _body(_report(manager))
    assert "Оценка заявителей" in body
    assert "—" in body


def test_rating_period_uses_closed_snapshot_not_rated_at():
    manager, tree = _manager_tree()
    ticket = sd.make_ticket(queue=tree["Сеть"])
    rating = sd.make_rating(ticket, score=5, closed_at=timezone.now() - timedelta(days=40))
    rating.rated_at = timezone.now()
    rating.save(update_fields=["rated_at"])
    body = _body(_report(manager))
    assert 'data-key="requester_rating"' in body
    assert "data-value=\"—\"" in body or "—" in body


def test_rating_filters_use_queue_level_category_and_assignee_snapshots():
    manager, tree = _manager_tree()
    queue = tree["Сеть"]
    category = sd.make_category("Снимок категории", queue=queue)
    level = sd.make_level(title="Снимок уровня", all_day=True)
    assignee = support.make_employee(full_name="Снимок исполнитель")
    ticket = sd.make_ticket(queue=queue)
    sd.make_rating(ticket, score=5, queue_id=queue.pk, queue_name=queue.name,
                   category_id=category.pk, category_name=category.name,
                   level_id=level.pk, level_title=level.title,
                   assignee_id=assignee.pk, assignee_name=assignee.full_name)
    response = _report(manager, queue=queue.pk, sla=level.pk, category=category.pk, assignee=assignee.pk)
    body = _body(response)
    assert response.status_code == 200
    assert 'data-count="1"' in body


def test_report_rating_respects_managed_units():
    manager, tree = _manager_tree()
    inside = sd.make_ticket(queue=tree["Сеть"])
    outside = sd.make_ticket(queue=tree["Чужой"])
    sd.make_rating(inside, score=5)
    sd.make_rating(outside, score=1)
    body = _body(_report(manager))
    assert 'data-count="1"' in body
    assert outside.subject not in body


def test_excel_repeats_rating_numbers_and_contains_no_subject_or_requester_data():
    manager, tree = _manager_tree()
    requester = sd.make_requester(email="synthetic.requester@example.test", full_name="Синтетический Заявитель")
    ticket = sd.make_ticket(queue=tree["Сеть"], requester=requester)
    sd.make_rating(ticket, score=5)
    client = support.logged_in(manager)
    page = client.get("/servicedesk/reports/", {"period": "month"})
    response = client.get("/servicedesk/reports/export/", {"period": "month"})
    assert response.status_code == 200
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(response.content), data_only=True)
    values = [str(cell.value) for sheet in book.worksheets for row in sheet.iter_rows() for cell in row
              if cell.value is not None]
    assert "requester_rating" in values
    assert 5 in [cell.value for row in book["Показатели"].iter_rows() for cell in row]
    assert ticket.subject not in values
    assert requester.email not in values and requester.full_name not in values
    assert "5" in _body(page)
