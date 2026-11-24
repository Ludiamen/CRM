"""Красные тесты выгрузки отчёта среза 011 (T-11109; FR-748, NFR-731).

Маршрут Excel пока является заглушкой 404. Импорты реализации и openpyxl
находятся внутри тестов, чтобы файл собирался до появления отчёта.
"""
import datetime
import io
import re
import time
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
EXPORT = "/servicedesk/reports/export/"
PERIOD = {"period": "month"}


def _managed_fixture(*, foreign=True):
    tree = org.make_tree({"Управляемый отдел": {"Поддержка": {}},
                          "Чужой отдел": {}} if foreign else {"Управляемый отдел": {}})
    manager = support.make_with_permissions("servicedesk.reports")
    org.make_member(manager, tree["Управляемый отдел"], mark="head")
    managed = sd.make_queue(tree["Поддержка"] if "Поддержка" in tree else tree["Управляемый отдел"])
    outsider = sd.make_queue(tree["Чужой отдел"]) if foreign else None
    return manager, managed, outsider


def _ticket_with_cycle(queue, *, requester=None, assignee=None, **cycle):
    level = sd.make_level(all_day=True)
    ticket = sd.make_ticket(queue=queue, requester=requester, sla=level)
    sd.make_cycle(ticket, level=level, assignee=assignee, queue=queue, **cycle)
    return ticket


def _xlsx(response):
    from openpyxl import load_workbook

    assert response.status_code == 200
    assert response.content[:2] == b"PK"
    assert "spreadsheet" in response["Content-Type"]
    return load_workbook(io.BytesIO(response.content), data_only=True)


def _values(book):
    return [cell.value for sheet in book.worksheets for row in sheet.iter_rows() for cell in row
            if cell.value is not None]


def _metric_map(sheet):
    result = {}
    for row in sheet.iter_rows(values_only=True):
        values = [value for value in row if value is not None]
        if len(values) >= 2 and isinstance(values[0], str) and isinstance(values[1], (int, float)):
            result[values[0]] = values[1]
    return result


def test_report_export_requires_reports_permission_and_managed_access():
    manager, managed, _ = _managed_fixture()
    without_permission = support.make_employee()
    org.make_member(without_permission, managed.unit)

    assert support.logged_in(manager).get(EXPORT, PERIOD).status_code == 200
    assert support.logged_in(without_permission).get(EXPORT, PERIOD).status_code == 403


def test_report_export_is_xlsx_named_for_period_and_matches_report_page():
    manager, managed, _ = _managed_fixture(foreign=False)
    ticket = _ticket_with_cycle(managed)
    client = support.logged_in(manager)
    page = client.get("/servicedesk/reports/", PERIOD)
    exported = client.get(EXPORT, PERIOD)

    book = _xlsx(exported)
    moscow_today = datetime.datetime.now(MSK).date().isoformat()
    assert re.fullmatch(rf"tickets-{moscow_today}\.xlsx", exported["Content-Disposition"].split("filename=")[-1].strip('"'))
    assert set(book.sheetnames) == {"Показатели", "Заявки"}
    assert ticket.number in _values(book["Заявки"])

    page_numbers = sd.report_numbers(page)
    exported_numbers = _metric_map(book["Показатели"])
    assert page_numbers
    assert all(exported_numbers.get(key) == value for key, value in page_numbers.items())


def test_report_export_metrics_sheet_has_same_numbers_as_page():
    manager, managed, _ = _managed_fixture(foreign=False)
    _ticket_with_cycle(managed)
    client = support.logged_in(manager)
    page = client.get("/servicedesk/reports/", PERIOD)
    book = _xlsx(client.get(EXPORT, PERIOD))

    page_numbers = sd.report_numbers(page)
    metrics = _metric_map(book["Показатели"])
    assert page_numbers
    assert set(page_numbers) <= set(metrics)
    for key, value in page_numbers.items():
        assert metrics[key] == value


def test_report_export_ticket_sheet_has_required_columns_and_maximum_rows():
    manager, managed, _ = _managed_fixture(foreign=False)
    ticket = _ticket_with_cycle(managed)
    book = _xlsx(support.logged_in(manager).get(EXPORT, PERIOD))
    rows = list(book["Заявки"].iter_rows(values_only=True))
    headers = {str(value).strip().lower() for value in rows[0] if value is not None}
    required = {
        "номер", "создана", "закрыта", "очередь", "уровень",
        "срок реакции", "факт реакции", "срок решения", "факт решения",
        "вердикты", "вид закрытия", "исполнитель",
    }
    assert required <= headers
    assert len(rows) - 1 <= 20_000
    assert ticket.number in {row[0] for row in rows[1:]}


def test_report_export_contains_no_ticket_or_requester_personal_data():
    manager, managed, _ = _managed_fixture(foreign=False)
    requester = sd.make_requester(email="requester@example.test", full_name="Имя Заявителя")
    ticket = _ticket_with_cycle(managed, requester=requester)
    client = support.logged_in(manager)
    response = client.get(EXPORT, PERIOD)
    values = [str(value) for value in _values(_xlsx(response))]

    forbidden = {ticket.subject, ticket.requester_email, ticket.requester_name,
                 requester.email, requester.full_name}
    assert not any(secret and secret in value for value in values for secret in forbidden)


def test_report_export_excludes_queues_outside_managed_units():
    manager, managed, foreign = _managed_fixture()
    inside = _ticket_with_cycle(managed)
    outside = _ticket_with_cycle(foreign)
    book = _xlsx(support.logged_in(manager).get(EXPORT, PERIOD))
    values = _values(book["Заявки"])

    assert inside.number in values
    assert outside.number not in values
    assert foreign.unit.name not in values


def test_report_export_writes_audit_event_with_actor():
    manager, managed, _ = _managed_fixture(foreign=False)
    _ticket_with_cycle(managed)
    before = support.model("core.AuditEvent").objects.filter(
        action="servicedesk.report_exported").count()
    response = support.logged_in(manager).get(EXPORT, PERIOD)
    assert response.status_code == 200

    event = support.model("core.AuditEvent").objects.filter(
        action="servicedesk.report_exported").order_by("id").last()
    assert support.model("core.AuditEvent").objects.filter(
        action="servicedesk.report_exported").count() == before + 1
    assert event.actor_id == manager.pk
    assert event.at.tzinfo is not None


def test_report_export_20000_rows_finishes_within_nfr_731():
    manager, managed, _ = _managed_fixture(foreign=False)
    level = sd.make_level(all_day=True)
    for _ in range(20_000):
        ticket = sd.make_ticket(queue=managed, sla=level)
        sd.make_cycle(ticket, level=level, queue=managed)

    started = time.monotonic()
    book = _xlsx(support.logged_in(manager).get(EXPORT, PERIOD))
    elapsed = time.monotonic() - started

    assert elapsed <= 10
    assert book["Заявки"].max_row - 1 <= 20_000
