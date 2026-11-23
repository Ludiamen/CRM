"""Срез 010 «Поручения»: дисциплина и Excel (T-10110; FR-714, 715, NFR-721).

`apps.instructions.services.discipline/excel` и страницы отчёта — CONTRACT-010, раздел 11, К23. Код среза
импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime
import io
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")


def discipline():
    from apps.instructions.services import discipline as module
    return module


def excel():
    from apps.instructions.services import excel as module
    return module


def _base():
    tree = support_org.make_tree({"Направление": {"Отдел": {"Группа": {}}}, "Чужой": {}})
    head = ins.head_of(tree["Направление"])
    deputy = ins.deputy_of(tree["Направление"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    peer = support.make_employee()
    support_org.make_member(peer, tree["Группа"])
    outsider = support.make_employee()
    support_org.make_member(outsider, tree["Чужой"])
    return tree, head, deputy, assignee, peer, outsider


def _closed(day, *, assignee, deadline, original=None, transfer=None, author=None):
    """Поручение, снятое с контроля в `day`; `transfer=(new_deadline, decided_on)` — согласованный перенос."""
    row = ins.make_instruction(author=author, assignee=assignee, deadline=deadline,
                               original_deadline=original or deadline)
    row.closed_at = datetime.datetime.combine(day, datetime.time(12), tzinfo=MSK)
    row.save(update_fields=["closed_at"])
    if transfer is not None:
        new_deadline, decided_on = transfer
        row.deadline = new_deadline
        row.save(update_fields=["deadline"])
        support.model("instructions.InstructionTransfer").objects.create(
            instruction=row, old_deadline=original or deadline, new_deadline=new_deadline, reason="Перенос",
            requested_by=assignee, state="approved", decided_by=row.controller,
            decided_at=datetime.datetime.combine(decided_on, datetime.time(12), tzinfo=MSK))
    return row


def _person_row(data, person):
    return next(row for row in data["rows"] if row["kind"] == "person" and row["person"] == person.full_name)


def _unit_row(data, unit):
    return next(row for row in data["rows"] if row["kind"] == "unit" and row["unit"] == unit.name)


def test_access_only_managers_and_deputies_without_admin():
    """FR-714: отчёт строит руководитель или заместитель своего подразделения; рядовому — 403, администратору —
    403 даже если он руководитель."""
    tree, head, deputy, assignee, peer, outsider = _base()
    _closed(ins._today(), assignee=assignee, deadline=ins._today())
    for viewer in (head, deputy):
        data = discipline().rows(viewer, date_from=ins._today() - datetime.timedelta(days=30),
                                 date_to=ins._today())
        assert data["rows"]
    from apps.instructions.texts import InstructionsError

    for viewer in (assignee, outsider):
        with pytest.raises(InstructionsError) as caught:
            discipline().rows(viewer, date_from=ins._today(), date_to=ins._today())
        assert caught.value.code == "discipline_forbidden"

    admin = support.make_admin()
    support_org.make_member(admin, tree["Направление"], mark="head")
    with pytest.raises(InstructionsError) as caught:
        discipline().rows(admin, date_from=ins._today(), date_to=ins._today())
    assert caught.value.code == "discipline_forbidden"


def test_population_is_closed_in_period_and_open_overdue_is_separate():
    """FR-714: население — снятые с контроля в периоде; открытые просроченные — отдельной строкой, в три
    категории не входят."""
    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    inside = _closed(today - datetime.timedelta(days=2), assignee=assignee, deadline=today)
    outside = _closed(today - datetime.timedelta(days=60), assignee=assignee, deadline=today - datetime.timedelta(days=60))
    open_overdue = ins.make_instruction(assignee=assignee, deadline=today - datetime.timedelta(days=3))

    data = discipline().rows(head, date_from=today - datetime.timedelta(days=30), date_to=today)
    ids = {row.pk for row in data["closed"]}
    assert inside.pk in ids and outside.pk not in ids
    assert data["open_rows"], "открытая просрочка не попала в отдельную строку"
    assert _person_row(data, assignee)["total"] == 1, "открытая просрочка вошла в три категории"


def test_original_scale_in_time_with_transfer_and_overdue():
    """FR-714: по исходному сроку — «в срок», «с переносом», «просрочено»; категории взаимоисключающие."""
    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    in_time = _closed(today - datetime.timedelta(days=5), assignee=assignee, deadline=today - datetime.timedelta(days=4))
    with_transfer = _closed(today - datetime.timedelta(days=5), assignee=assignee, deadline=today,
                            original=today - datetime.timedelta(days=15),
                            transfer=(today, today - datetime.timedelta(days=12)))
    overdue = _closed(today - datetime.timedelta(days=2), assignee=assignee, deadline=today - datetime.timedelta(days=4))

    data = discipline().rows(head, date_from=today - datetime.timedelta(days=30), date_to=today)
    row = _person_row(data, assignee)
    assert (row["in_time"], row["with_transfer"], row["overdue"], row["total"]) == (1, 1, 1, 3)
    assert row["total"] == row["in_time"] + row["with_transfer"] + row["overdue"]


def test_final_scale_example_from_spec():
    """FR-714, пример спеки: перенос с 1 на 10 июня, исполнено 8 июня — «с переносом» и «в срок»; исполнено
    12 июня — «просрочено» в обеих шкалах."""
    tree, head, deputy, assignee, peer, outsider = _base()
    first = _closed(datetime.date(2026, 6, 8), assignee=assignee, deadline=datetime.date(2026, 6, 10),
                    original=datetime.date(2026, 6, 1),
                    transfer=(datetime.date(2026, 6, 10), datetime.date(2026, 6, 2)))
    second = _closed(datetime.date(2026, 6, 12), assignee=peer, deadline=datetime.date(2026, 6, 10),
                     original=datetime.date(2026, 6, 1),
                     transfer=(datetime.date(2026, 6, 10), datetime.date(2026, 6, 2)))
    data = discipline().rows(head, date_from=datetime.date(2026, 6, 1), date_to=datetime.date(2026, 6, 30))

    first_row = _person_row(data, assignee)
    assert (first_row["with_transfer"], first_row["final_in_time"], first_row["final_overdue"]) == (1, 1, 0)
    second_row = _person_row(data, peer)
    assert (second_row["overdue"], second_row["final_overdue"]) == (1, 1)


def test_last_approved_transfer_before_close_defines_final_deadline():
    """FR-714: срок с переносами — последний согласованный перенос с `decided_at <= closed_at`; отказ и
    согласование после снятия не учитываются."""
    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    row = _closed(today - datetime.timedelta(days=1), assignee=assignee, deadline=today + datetime.timedelta(days=5),
                  original=today - datetime.timedelta(days=20))
    Transfer = support.model("instructions.InstructionTransfer")
    Transfer.objects.create(instruction=row, old_deadline=today - datetime.timedelta(days=20),
                            new_deadline=today + datetime.timedelta(days=3), reason="Первый", requested_by=assignee,
                            state="approved", decided_by=row.controller,
                            decided_at=datetime.datetime.combine(today - datetime.timedelta(days=6),
                                                                 datetime.time(12), tzinfo=MSK))
    Transfer.objects.create(instruction=row, old_deadline=today - datetime.timedelta(days=20),
                            new_deadline=today + datetime.timedelta(days=30), reason="Отказ", requested_by=assignee,
                            state="rejected", decided_by=row.controller,
                            decided_at=datetime.datetime.combine(today - datetime.timedelta(days=5),
                                                                 datetime.time(12), tzinfo=MSK))
    Transfer.objects.create(instruction=row, old_deadline=today - datetime.timedelta(days=20),
                            new_deadline=today + datetime.timedelta(days=40), reason="После снятия",
                            requested_by=assignee, state="approved", decided_by=row.controller,
                            decided_at=datetime.datetime.combine(today + datetime.timedelta(days=2),
                                                                 datetime.time(12), tzinfo=MSK))
    # закрыто вчера, последний согласованный до снятия — срок +3 → исполнено вовремя
    data = discipline().rows(head, date_from=today - datetime.timedelta(days=30), date_to=today)
    assert _person_row(data, assignee)["final_in_time"] == 1


def test_main_unit_is_first_non_root_by_path():
    """FR-714: «основной узел» — первый не-корневой узел по `path`, иначе корень."""
    tree, head, deputy, assignee, peer, outsider = _base()
    assert discipline().main_unit(assignee).pk == tree["Направление"].pk
    # сотрудник без узлов — корень дерева
    loner = support.make_employee()
    root = support.model("org.Unit").objects.get(parent=None)
    assert discipline().main_unit(loner).pk == root.pk


def test_unit_filter_includes_nested_and_totals_match_rows():
    """FR-714: подразделение — узел и вложенные; итоги равны сумме строк."""
    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    _closed(today, assignee=assignee, deadline=today)
    _closed(today, assignee=peer, deadline=today - datetime.timedelta(days=2))
    data = discipline().rows(head, date_from=today - datetime.timedelta(days=10), date_to=today,
                             unit=tree["Отдел"])
    persons = [row for row in data["rows"] if row["kind"] == "person"]
    assert {row["person"] for row in persons} == {assignee.full_name, peer.full_name}
    for key in ("in_time", "with_transfer", "overdue", "final_in_time", "final_overdue"):
        assert data["totals"][key] == sum(row[key] for row in persons)


def test_sql_uses_parameters_and_chain_array():
    """NFR-721: период и цепочка узлов — параметры, а не текст SQL."""
    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    _closed(today, assignee=assignee, deadline=today)
    pairs = ins.queries_with_params(lambda: discipline().rows(
        head, date_from=today - datetime.timedelta(days=10), date_to=today, unit=tree["Отдел"]))
    joined = " ".join(sql for sql, _params in pairs)
    assert "= ANY(%s)" in joined, "цепочка узлов не массивом"
    assert not any("2026-" in sql for sql, _params in pairs), "дата попала в текст SQL"


def test_excel_has_same_numbers_and_russian_labels():
    """FR-715: выгрузка — `.xlsx` с теми же числами и русскими подписями."""
    from openpyxl import load_workbook

    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    _closed(today, assignee=assignee, deadline=today)
    data = discipline().rows(head, date_from=today - datetime.timedelta(days=10), date_to=today)
    payload = excel().build(data)
    assert payload[:2] == b"PK"

    book = load_workbook(io.BytesIO(payload))
    sheet = book["Дисциплина"]
    text = [[cell.value for cell in row] for row in sheet.iter_rows()]
    flat = " ".join(str(value) for row in text for value in row if value is not None)
    assert "Исполнено в срок" in flat and "Просрочено" in flat
    assert assignee.full_name in flat
    assert str(data["totals"]["in_time"]) in flat


def test_discipline_page_and_excel_route(client):
    """CONTRACT-010, 6.2: страница `[data-discipline-table]` с строками `[data-discipline-row]`; Excel — файл
    книги; администратору и рядовому — 403."""
    tree, head, deputy, assignee, peer, outsider = _base()
    today = ins._today()
    _closed(today, assignee=assignee, deadline=today)

    support.login(client, head)
    page = client.get("/instructions/discipline/")
    html = page.content.decode()
    assert page.status_code == 200 and "data-discipline-table" in html and "data-discipline-row" in html

    book = client.get("/instructions/discipline.xlsx")
    assert book.status_code == 200 and book.content[:2] == b"PK"
    assert "spreadsheet" in book["Content-Type"]

    support.login(client, assignee)
    assert client.get("/instructions/discipline/").status_code == 403
    assert client.get("/instructions/discipline.xlsx").status_code == 403