"""T-15032/T-15033: стадия в таблице и выгрузке (FR-882…FR-884; CONTRACT-015, раздел 9)."""
import io

import pytest
from django.http import QueryDict
from openpyxl import load_workbook

from apps.lists.services import grid, process
from tests import support
from tests import support_lists as ll

pytestmark = pytest.mark.django_db


def prepare():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = process.add_stage(lst, manager.user, title="Новая")
    second = process.add_stage(lst, manager.user, title="Готово", kind="closed")
    process.save_settings(lst, manager.user, enabled=True)
    one = ll.make_record(lst, title="Первая")
    one.stage = first
    one.save(update_fields=["stage"])
    two = ll.make_record(lst, title="Вторая")
    two.stage = second
    two.save(update_fields=["stage"])
    return lst, manager, first, second


def test_grid_filters_and_sorts_by_stage():
    lst, manager, first, second = prepare()
    gp = grid.read(QueryDict(f"stage={first.pk}"), lst, manager.user)
    found = list(grid.records(lst, manager.user, gp))
    assert [row.title for row in found] == ["Первая"]
    gp = grid.read(QueryDict("sort=stage"), lst, manager.user)
    found = list(grid.records(lst, manager.user, gp))
    assert [row.title for row in found] == ["Первая", "Вторая"]


def test_grid_page_has_stage_column_and_filter():
    lst, manager, first, second = prepare()
    page = manager.client.get(f"/lists/{lst.pk}/")
    body = page.content.decode()
    assert "Стадия" in body and "Первая" in body and "Новая" in body
    filtered = manager.client.get(f"/lists/{lst.pk}/?stage={second.pk}")
    text = filtered.content.decode()
    assert "Вторая" in text and "Первая" not in text


def test_export_has_stage_column():
    lst, manager, first, second = prepare()
    response = manager.client.get(f"/lists/{lst.pk}/export/")
    assert response.status_code == 200
    book = load_workbook(io.BytesIO(response.content), read_only=True)
    sheet = book["Список"]
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][:2] == ("Название", "Стадия")
    assert rows[1][:2] == ("Первая", "Новая")
