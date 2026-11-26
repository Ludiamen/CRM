"""Красные серверные контракты доступа и области очереди (T-12102)."""
from datetime import timedelta

import pytest
from django.http import Http404
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db


def _member(queue, *, name=None, mark=""):
    user = support.make_employee(full_name=name) if name else support.make_employee()
    org.make_member(user, queue.unit, mark=mark)
    return user


def test_observer_can_view_but_cannot_work():
    """FR-767: наблюдатель читает карточку, но не получает рабочее право."""
    from apps.servicedesk.services import access

    queue = sd.make_queue()
    observer = support.make_employee()
    ticket = sd.make_ticket(queue=queue)
    sd.add_observer(queue, observer)
    assert access.can_view(observer, ticket) is True
    assert access.can_work(observer, ticket) is False


def test_observer_is_in_list_search_get_for_and_briefs_but_not_mutations():
    """FR-767/777: все read-пути используют can_view, мутация — can_work."""
    from apps.servicedesk.services import access, public, search, tickets

    queue = sd.make_queue()
    observer = support.make_employee()
    ticket = sd.make_ticket(queue=queue, subject="Наблюдаемая заявка")
    sd.add_observer(queue, observer)
    search.rebuild(ticket)
    assert ticket.number in set(access.visible_tickets(observer).values_list("number", flat=True))
    assert ticket.number in {row.number for row in search.search(observer, "Наблюдаемая", 10).tickets}
    assert tickets.get_for(observer, ticket.number).pk == ticket.pk
    assert public.briefs(observer, [ticket.number])[ticket.number].subject == ticket.subject
    assert access.menu_visible(observer) is True


def test_observer_cannot_take_or_assign_ticket():
    """FR-767: наблюдатель не может изменить ответственного прямым вызовом службы."""
    from apps.servicedesk.services import assignment

    queue = sd.make_queue()
    observer = support.make_employee()
    ticket = sd.make_ticket(queue=queue)
    sd.add_observer(queue, observer)
    with pytest.raises(Exception, match="наблюдатель|доступ"):
        assignment.take(ticket, actor=observer)
    ticket.refresh_from_db()
    assert ticket.assignee_id is None


def test_removed_observer_loses_read_scope_without_other_access():
    """FR-767: снятая строка не даёт доступа к очереди."""
    from apps.servicedesk.services import access

    queue = sd.make_queue()
    observer = support.make_employee()
    ticket = sd.make_ticket(queue=queue)
    row = sd.add_observer(queue, observer)
    row.removed_at = timezone.now()
    row.save(update_fields=["removed_at"])
    assert access.can_view(observer, ticket) is False


def test_unavailable_employee_is_excluded_from_eligible_assignees_until_date():
    """FR-765: недоступный сотрудник исключён до указанной даты включительно."""
    from apps.servicedesk.services import access

    queue = sd.make_queue()
    available = _member(queue, name="Альфа Исполнитель")
    away = _member(queue, name="Бета Исполнитель")
    sd.set_unavailable(away, timezone.localdate() + timedelta(days=1), actor=away)
    ids = {person.id for person in access.eligible_assignees(queue.unit_id)}
    assert available.pk in ids
    assert away.pk not in ids


def test_queue_head_has_settings_scope_but_foreign_member_does_not():
    """FR-780: руководитель узла очереди управляет ею, чужой участник — нет."""
    from apps.org.services import structure

    tree = org.make_tree({"Сеть": {"Очередь": {}}, "Чужой": {}})
    queue = sd.make_queue(tree["Очередь"])
    head = _member(queue, mark="head")
    foreign = _member(sd.make_queue(tree["Чужой"]))
    assert queue.unit_id in structure.managed_units(head)
    assert queue.unit_id not in structure.managed_units(foreign)
