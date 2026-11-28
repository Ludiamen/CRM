"""T-15030/T-15031: доска «Стадии» (FR-879…FR-881; CONTRACT-015, раздел 9)."""
import pytest
from django.http import QueryDict

from apps.lists.services import board, grid, process
from tests import factories, support
from tests import factories, support_lists as ll

pytestmark = pytest.mark.django_db


def prepare():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = process.add_stage(lst, manager.user, title="Новая")
    second = process.add_stage(lst, manager.user, title="Закрыта", kind="closed")
    process.save_settings(lst, manager.user, enabled=True)
    return lst, manager, first, second


def place(lst, stage, title, *, archived=False):
    record = ll.make_record(lst, title=title, archived=archived)
    record.stage = stage
    record.save(update_fields=["stage"])
    return record


def test_columns_counts_and_archive():
    lst, manager, first, second = prepare()
    place(lst, first, "Одна")
    place(lst, first, "Две")
    place(lst, second, "Готово")
    place(lst, first, "В архиве", archived=True)
    ll.make_record(lst, title="Без стадии")
    gp = grid.read(QueryDict(), lst, manager.user)
    columns = board.columns(lst, manager.user, gp)
    assert [item["key"] for item in columns] == [str(first.pk), str(second.pk), "none"]
    assert {item["key"]: item["count"] for item in columns} == {str(first.pk): 2, str(second.pk): 1, "none": 1}
    assert "В архиве" not in [row.title for row in columns[0]["rows"]]


def test_board_page_and_column_page():
    lst, manager, first, second = prepare()
    place(lst, first, "Одна")
    page = manager.client.get(f"/lists/{lst.pk}/board/")
    assert page.status_code == 200
    body = page.content.decode()
    assert "Новая" in body and "Закрыта" in body and "Одна" in body
    fragment = manager.client.get(f"/lists/{lst.pk}/board/column/{first.pk}/")
    assert fragment.status_code == 200
    assert "Одна" in fragment.content.decode()


def test_move_endpoint_changes_stage():
    lst, manager, first, second = prepare()
    record = place(lst, first, "Одна")
    response = manager.client.post(f"/lists/{lst.pk}/board/move/",
                                   {"number": record.number, "stage": second.pk, "base_version": record.version},
                                   HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    record.refresh_from_db()
    assert record.stage_id == second.pk


def test_hidden_stage_column_absent():
    lst, manager, first, second = prepare()
    role = factories.make_role()
    support.model("lists.ProcessStageAccess").objects.create(stage=first, level="read", role=role)
    support.model("lists.ProcessStageAccess").objects.create(stage=second, level="read", role=factories_role(role))
    user = support.make_employee(roles=[role])
    ll.grant_list(lst, role, "read")
    columns = board.columns(lst, user, grid.read(QueryDict(), lst, user))
    assert [item["key"] for item in columns] == [str(first.pk)]


def factories_role(other):
    return factories.make_role()
