"""Красные тесты атомарности автораспределения (T-12104, NFR-736).

Стенд проекта не поддерживает `django_db(transaction=True)` (см. `tests/conftest.py` и CONTRACT-005/007/008):
тестовая база создана владельцем, запросы идут под ролью приложения, TRUNCATE запрещён. Поэтому атомарность
проверяется без потоков: идемпотентный повтор того же вызова, один ответственный и одно событие, а также
наличие `SELECT ... FOR UPDATE` в SQL распределения/взятия. Это честная проверка доступного контракта,
а не имитация гонки моками.
"""
from django.db import connection
from django.test.utils import CaptureQueriesContext

import pytest

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _member(queue, name):
    user = support.make_employee(full_name=name)
    org.make_member(user, queue.unit)
    return user


def _assign_events(ticket):
    from tests.support import model

    return model("servicedesk.TicketEntry").objects.filter(
        ticket=ticket, event="assignee_changed").count()


def _audit_count(ticket, action):
    from tests.support import model

    return model("core.AuditEvent").objects.filter(action=action, object_id=str(ticket.number)).count()


def test_evenly_is_idempotent_and_locks_rule_and_ticket():
    """NFR-736: повтор distribute не меняет ответственного, одно событие и один журнал; есть FOR UPDATE."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    _member(queue, "Альфа")
    _member(queue, "Бета")
    sd.make_rule(queue, "evenly")
    ticket = sd.make_ticket(queue=queue)
    with CaptureQueriesContext(connection) as captured:
        first = distribution.assign_or_notify(ticket, reason="create")
        second = distribution.assign_or_notify(ticket, reason="create")
    ticket.refresh_from_db()
    assert first == second == ticket.assignee_id
    assert _assign_events(ticket) == 1
    assert _audit_count(ticket, "ticket.distributed") == 1
    sql = "\n".join(query["sql"].upper() for query in captured.captured_queries)
    assert "FOR UPDATE" in sql, "распределение обязано блокировать правило/заявку"


def test_strictly_pointer_advances_once_and_is_idempotent_for_same_ticket():
    """NFR-736: указатель строгой очереди не удваивается при повторном вызове того же ticket."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    first = _member(queue, "Альфа")
    second = _member(queue, "Бета")
    sd.make_rule(queue, "strictly")
    ticket = sd.make_ticket(queue=queue)
    one = distribution.assign_or_notify(ticket, reason="create")
    two = distribution.assign_or_notify(ticket, reason="create")
    ticket.refresh_from_db()
    assert one == two == ticket.assignee_id
    assert ticket.assignee_id in {first.pk, second.pk}
    rule = support.model("servicedesk.QueueRule").objects.get(queue=queue)
    assert rule.last_assignee_id == ticket.assignee_id


def test_take_is_idempotent_and_writes_one_assignee_event():
    """NFR-736: повторное «Взять» того же сотрудника не создаёт второе событие."""
    from apps.servicedesk.services import assignment

    queue = sd.make_queue()
    actor = _member(queue, "Альфа")
    ticket = sd.make_ticket(queue=queue)
    assert assignment.take(ticket, actor=actor) is True
    assert assignment.take(ticket, actor=actor) is False
    ticket.refresh_from_db()
    assert ticket.assignee_id == actor.pk
    assert _assign_events(ticket) == 1
