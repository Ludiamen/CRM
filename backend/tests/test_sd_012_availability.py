"""T-12202: ручная недоступность сотрудника и возврат его заявок (FR-765)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support, support_org
from tests.support_servicedesk import make_queue, make_rule, make_ticket

pytestmark = pytest.mark.django_db


def _member(queue, name):
    user = support.make_employee(full_name=name)
    support_org.make_member(user, queue.unit)
    return user


def test_employee_sets_and_clears_own_availability_with_audit():
    from apps.core.models import AuditEvent
    from apps.core.services import accounts

    user = support.make_employee()
    until = timezone.localdate() + timedelta(days=3)
    accounts.set_availability(user, until, "отпуск", actor=user)
    user.refresh_from_db()
    assert user.unavailable_until == until and user.unavailable_note == "отпуск"
    assert AuditEvent.objects.filter(action="core.user_unavailable", object_id=str(user.pk)).count() == 1
    accounts.set_availability(user, None, actor=user)
    user.refresh_from_db()
    assert user.unavailable_until is None and user.unavailable_note == ""


def test_foreign_employee_cannot_set_availability_and_head_can():
    from apps.core.services import accounts
    from apps.org.services import availability

    queue = make_queue()
    head = support.make_employee(full_name="Руководитель")
    support_org.make_member(head, queue.unit, mark="head")
    worker = _member(queue, "Сотрудник")
    foreign = support.make_employee()
    until = timezone.localdate() + timedelta(days=1)
    with pytest.raises(accounts.AccountError):
        accounts.set_availability(worker, until, actor=foreign)
    availability.set_for_head(head, worker, until, "нет на месте")
    worker.refresh_from_db()
    assert worker.unavailable_until == until


def test_setting_availability_returns_open_tickets_to_queue(django_capture_on_commit_callbacks):
    from apps.core.services import accounts

    queue = make_queue()
    worker = _member(queue, "Исполнитель")
    colleague = _member(queue, "Коллега")
    make_rule(queue, "evenly")
    ticket = make_ticket(queue=queue, kind="in_progress", assignee=worker)
    with django_capture_on_commit_callbacks(execute=True):
        accounts.set_availability(worker, timezone.localdate() + timedelta(days=2), actor=worker)
    ticket.refresh_from_db()
    assert ticket.assignee_id == colleague.pk
