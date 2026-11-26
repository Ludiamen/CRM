"""T-11108: отчёт по заявкам (FR-746…750, NFR-735).

Страница отчёта пока является заглушкой 404. Тесты намеренно остаются
красными до реализации представления и службы отчётов; импорты кода среза
выполняются только внутри тестов.
"""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")


def _manager(unit, *permissions):
    user = support.make_with_permissions(*permissions)
    org.make_member(user, unit, mark="head")
    return user


def _admin_with_report_permission():
    admin = support.make_admin()
    permission = support.model("core.Permission").objects.get(code="servicedesk.reports")
    admin.roles.first().permissions.add(permission)
    return admin


def _report(user, **params):
    query = {"period": "month"}
    query.update(params)
    return support.logged_in(user).get("/servicedesk/reports/", query)


def _body(response):
    return response.content.decode("utf-8", "replace")


def _numbers(response):
    return sd.report_numbers(response)


def _tickets(response):
    return {int(number) for number in re.findall(r'data-report-ticket="(\d+)"', _body(response))}


def _closed_cycle(ticket, *, level, closed_at, assignee=None, **over):
    cycle = sd.make_cycle(ticket, level=level, assignee=assignee, **over)
    cycle.closed_at = closed_at
    cycle.solution_minutes = over.get("solution_minutes", 12)
    cycle.reaction_met = over.get("reaction_met", True)
    cycle.solution_met = over.get("solution_met", True)
    cycle.save(update_fields=["closed_at", "solution_minutes", "reaction_met", "solution_met"])
    return cycle


def test_report_permission_is_required_and_manager_gets_report():
    """FR-746/NFR-735: руководитель с правом открывает отчёт, без права получает 403."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    without_permission = support.make_employee()
    org.make_member(without_permission, tree["ИТ"], mark="head")

    allowed = _report(manager)
    denied = _report(without_permission)

    assert allowed.status_code == 200
    assert "data-report-page" in _body(allowed)
    assert denied.status_code == 403


def test_admin_without_managed_unit_is_forbidden_even_with_report_permission():
    """FR-749: администратор без отметки руководителя/заместителя не получает отчёт."""
    admin = _admin_with_report_permission()

    response = _report(admin)

    assert response.status_code == 403


def test_queue_manager_sees_only_own_units_and_descendants():
    """FR-749: руководитель очереди видит свой узел и вложенные, но не чужую ветку."""
    tree = org.make_tree({"Своя очередь": {"Вложенная": {}}, "Чужая очередь": {}})
    manager = _manager(tree["Своя очередь"], "servicedesk.reports")
    own = sd.make_ticket(queue=tree["Вложенная"])
    foreign = sd.make_ticket(queue=tree["Чужая очередь"])

    response = _report(manager)

    assert response.status_code == 200
    assert own.number in _tickets(response)
    assert foreign.number not in _tickets(response)


def test_it_department_head_sees_all_queues():
    """FR-749: руководитель ИТ-отдела видит заявки всех очередей."""
    tree = org.make_tree({"ИТ-отдел": {"Сеть": {}, "Поддержка": {}}})
    manager = _manager(tree["ИТ-отдел"], "servicedesk.reports")
    network = sd.make_ticket(queue=tree["Сеть"])
    support_ticket = sd.make_ticket(queue=tree["Поддержка"])

    response = _report(manager)

    assert response.status_code == 200
    assert network.number in _tickets(response)
    assert support_ticket.number in _tickets(response)


def test_month_counts_created_by_ticket_created_at_in_moscow():
    """FR-746: период month считает созданные заявки по Ticket.created_at."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    now = timezone.now().astimezone(MSK)
    inside = sd.make_ticket(queue=tree["ИТ"], created_at=now.replace(day=5))
    outside = sd.make_ticket(queue=tree["ИТ"], created_at=now - timedelta(days=40))

    response = _report(manager)
    numbers = _numbers(response)

    assert numbers["created"] == 1
    assert inside.number in _tickets(response)
    assert outside.number not in _tickets(response)


def test_closed_uses_closed_at_of_current_cycle_only_after_reopen():
    """Решение 5б: старый закрытый цикл после reopen не входит в «закрыто»."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    ticket = sd.make_ticket(queue=tree["ИТ"])
    level = sd.make_level(all_day=True)
    old = _closed_cycle(ticket, level=level, closed_at=timezone.now() - timedelta(days=1))
    sd.make_cycle(ticket, level=level, number=2, cycle_started_at=timezone.now())

    numbers = _numbers(_report(manager))

    old.refresh_from_db()
    assert old.is_current is False
    assert numbers["closed"] == 0


def test_averages_use_recorded_reaction_and_solution_minutes():
    """FR-747: средние берутся из готовых reaction_minutes/solution_minutes."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    level = sd.make_level(all_day=True)
    for reaction, solution in ((10, 40), (30, 80)):
        ticket = sd.make_ticket(queue=tree["ИТ"])
        _closed_cycle(ticket, level=level, closed_at=timezone.now(),
                      reaction_minutes=reaction, solution_minutes=solution)

    numbers = _numbers(_report(manager))

    assert numbers["average_reaction_minutes"] == 20
    assert numbers["average_solution_minutes"] == 60


def test_reaction_on_time_ratio_excludes_closed_without_response():
    """FR-747: знаменатель реакции — только True/False; NULL показан отдельно."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    level = sd.make_level(all_day=True)
    for verdict in (True, False, None):
        ticket = sd.make_ticket(queue=tree["ИТ"])
        _closed_cycle(ticket, level=level, closed_at=timezone.now(), reaction_met=verdict)

    numbers = _numbers(_report(manager))

    assert numbers["reaction_on_time"] == 50
    assert numbers["closed_without_response"] == 1


def test_solution_on_time_ratio_uses_closed_cycles_only():
    """FR-747: доля решения — True к True/False закрытых текущих циклов."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    level = sd.make_level(all_day=True)
    for verdict in (True, False):
        ticket = sd.make_ticket(queue=tree["ИТ"])
        _closed_cycle(ticket, level=level, closed_at=timezone.now(), solution_met=verdict)

    numbers = _numbers(_report(manager))

    assert numbers["solution_on_time"] == 50


def test_overdue_rows_are_grouped_by_level_title_snapshot():
    """FR-747: просрочки группируются по сохранённому level_title."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    late_level = sd.make_level(title="Критичный", all_day=True)
    ticket = sd.make_ticket(queue=tree["ИТ"])
    _closed_cycle(ticket, level=late_level, closed_at=timezone.now(),
                  solution_met=False, level_title="Критичный")

    response = _report(manager)

    assert response.status_code == 200
    assert "Критичный" in _body(response)


def test_load_is_closed_per_assignee_snapshot():
    """FR-747: нагрузка — число закрытых заявок на assignee_name."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    first = support.make_employee(full_name="Исполнитель А")
    second = support.make_employee(full_name="Исполнитель Б")
    level = sd.make_level(all_day=True)
    for assignee in (first, first, second):
        ticket = sd.make_ticket(queue=tree["ИТ"])
        _closed_cycle(ticket, level=level, closed_at=timezone.now(), assignee=assignee)

    response = _report(manager)
    html = _body(response)

    assert response.status_code == 200
    assert "Исполнитель А" in html and "Исполнитель Б" in html
    assert _numbers(response)["closed"] == 3


def test_report_filters_queue_level_category_and_assignee():
    """FR-746: все четыре фильтра ограничивают выборку отчёта."""
    tree = org.make_tree({"ИТ": {"Сеть": {}, "Поддержка": {}}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    assignee = support.make_employee(full_name="Нужный исполнитель")
    category = sd.make_category("Сеть", queue=tree["Сеть"])
    level = sd.make_level(title="Нужный SLA", all_day=True)
    ticket = sd.make_ticket(queue=tree["Сеть"], category=category, assignee=assignee, sla=level)
    sd.make_cycle(ticket, level=level, category=category, assignee=assignee)

    response = _report(manager, queue=tree["Сеть"].pk, sla=level.pk,
                       category=category.pk, assignee=assignee.pk)

    assert response.status_code == 200
    assert _numbers(response)["created"] == 1


def test_empty_report_returns_zero_metrics_without_error():
    """FR-747: пустая выборка возвращает нули, а не ошибку."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")

    response = _report(manager)
    numbers = _numbers(response)

    assert response.status_code == 200
    assert numbers and all(value == 0 for value in numbers.values())


def test_requester_rating_metric_is_present_and_empty():
    """FR-750/FR-772: показатель оценки предусмотрен; без оценок — «—» и число 0."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")

    response = _report(manager)
    html = _body(response)

    assert response.status_code == 200
    assert "requester_rating" in html or "оценка заявителей" in html.lower()
    assert 'data-value="—"' in html
    assert 'data-count="0"' in html


def test_custom_report_period_allows_370_days_but_rejects_371():
    """FR-746: custom-период длиной 370 дней допустим, 371 даёт ошибку поля и 400."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    start = date(2026, 1, 1)
    client = support.logged_in(manager)

    allowed = client.get("/servicedesk/reports/", {
        "period": "custom", "from": start, "to": start + timedelta(days=369),
    })
    rejected = client.get("/servicedesk/reports/", {
        "period": "custom", "from": start, "to": start + timedelta(days=370),
    })

    assert allowed.status_code == 200
    assert rejected.status_code == 400
    assert 'data-error="from"' in _body(rejected) or 'data-error="to"' in _body(rejected)


def test_moscow_midnight_places_tickets_in_different_days():
    """FR-746/758: 23:59 и 00:01 по Москве относятся к разным суткам."""
    tree = org.make_tree({"ИТ": {}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    late = sd.make_ticket(queue=tree["ИТ"],
                          created_at=datetime(2026, 3, 10, 23, 59, tzinfo=MSK))
    early = sd.make_ticket(queue=tree["ИТ"],
                           created_at=datetime(2026, 3, 11, 0, 1, tzinfo=MSK))
    client = support.logged_in(manager)

    previous_day = client.get("/servicedesk/reports/", {
        "period": "day", "date": "2026-03-10",
    })
    next_day = client.get("/servicedesk/reports/", {
        "period": "day", "date": "2026-03-11",
    })

    assert late.number in _tickets(previous_day)
    assert early.number not in _tickets(previous_day)
    assert early.number in _tickets(next_day)
    assert late.number not in _tickets(next_day)


def test_report_history_uses_cycle_snapshots_after_mutations():
    """Решения 5/9/11 и NFR-733: правки уровня, календаря, передачи и ответственного не меняют историю."""
    tree = org.make_tree({"ИТ": {"Сеть": {}, "Поддержка": {}}})
    manager = _manager(tree["ИТ"], "servicedesk.reports")
    old_assignee = support.make_employee(full_name="Старый исполнитель")
    level = sd.make_level(title="Старый SLA", all_day=True)
    category = sd.make_category("Старая категория", queue=tree["Сеть"])
    ticket = sd.make_ticket(queue=tree["Сеть"], category=category, assignee=old_assignee, sla=level)
    cycle = _closed_cycle(ticket, level=level, assignee=old_assignee,
                          closed_at=timezone.now(), level_title="Старый SLA",
                          queue_name="Сеть", category_name="Старая категория",
                          assignee_name="Старый исполнитель")
    level.title = "Новый SLA"
    level.save(update_fields=["title"])
    ticket.queue = tree["Поддержка"]
    ticket.assignee = support.make_employee(full_name="Новый исполнитель")
    ticket.save(update_fields=["queue", "assignee"])
    cycle.refresh_from_db()

    response = _report(manager)
    html = _body(response)

    assert response.status_code == 200
    assert "Старый SLA" in html
    assert "Старая категория" in html
    assert "Старый исполнитель" in html
