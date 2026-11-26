"""Красные серверные контракты автораспределения (T-12103).

Здесь проверяется публичный контракт ``distribution``. Реализация этапа 3
должна сделать тесты зелёными, не меняя ожидаемые причины возврата и порядок
приоритетов.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db


def _member(queue, name):
    user = support.make_employee(full_name=name)
    org.make_member(user, queue.unit)
    return user


def test_rule_modes_are_read_and_changed_with_audit():
    """FR-759: режимы off/evenly/strictly/all настраиваются и журналируются."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    actor = support.make_admin()
    assert distribution.mode_for(queue.unit_id) == "off"
    for mode in ("evenly", "strictly", "all", "off"):
        distribution.set_mode(queue.unit_id, mode, actor=actor)
        assert distribution.mode_for(queue.unit_id) == mode


def test_create_priority_take_by_category_then_sla_before_distribution():
    """FR-760: явный, категорийный и SLA-ответственный важнее режима."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    explicit = _member(queue, "Явный")
    category_user = _member(queue, "Категория")
    sla_user = _member(queue, "SLA")
    sd.make_rule(queue, "evenly")
    category = sd.make_category(queue=queue, default_assignee=category_user)
    level = sd.make_level(default_assignee=sla_user)
    for ticket, expected in (
        (sd.make_ticket(queue=queue, assignee=explicit), explicit),
        (sd.make_ticket(queue=queue, category=category), category_user),
        (sd.make_ticket(queue=queue, sla=level), sla_user),
    ):
        assert distribution.assign_or_notify(ticket, reason="create") == expected.pk


def test_evenly_counts_only_open_tickets_and_strictly_skips_unavailable():
    """FR-761/762: evenly считает открытую очередь, strictly пропускает недоступных."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    first = _member(queue, "Альфа")
    second = _member(queue, "Бета")
    sd.make_rule(queue, "evenly")
    sd.make_ticket(queue=queue, kind="in_progress", assignee=first)
    sd.make_ticket(queue=queue, kind="closed", assignee=first)
    assert distribution.choose_evenly(queue.unit_id, [first, second]).id == second.pk
    sd.set_unavailable(second, timezone.localdate() + timedelta(days=1), actor=second)
    rule = sd.make_rule(queue, "strictly", last_assignee=first)
    assert distribution.choose_strictly(rule, [first, second]).id == first.pk


def test_all_leaves_ticket_free_and_notifies_candidates_once(django_capture_on_commit_callbacks):
    """FR-763: all не назначает ответственного, а повтор идемпотентен."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    first, second = _member(queue, "Альфа"), _member(queue, "Бета")
    observer = support.make_employee()
    sd.add_observer(queue, observer)
    sd.make_rule(queue, "all")
    ticket = sd.make_ticket(queue=queue)
    from apps.servicedesk.services import events
    with django_capture_on_commit_callbacks(execute=True):
        assert distribution.assign_or_notify(ticket, reason="create") is None
        assert distribution.assign_or_notify(ticket, reason="create") is None
        events.ticket_created(ticket, actor_id=None, channel="mail")
    ticket.refresh_from_db()
    assert ticket.assignee_id is None
    Notice = model("notify.Notification")
    recipients = set(Notice.objects.filter(user_id__in=[first.pk, second.pk, observer.pk])
                     .values_list("user_id", flat=True))
    assert recipients == {first.pk, second.pk, observer.pk}


@pytest.mark.parametrize("reason", ["manual", "reconcile", "unavailable", "transfer", "category"])
def test_return_paths_use_reason_and_do_not_touch_closed_ticket(reason):
    """FR-764: возвраты несут причину, закрытая заявка не распределяется."""
    from apps.servicedesk.services import distribution

    queue = sd.make_queue()
    user = _member(queue, "Исполнитель")
    sd.make_rule(queue, "evenly")
    ticket = sd.make_ticket(queue=queue, assignee=user)
    result = distribution.return_ticket(ticket, actor=user, reason=reason)
    assert result is not None
    closed = sd.make_ticket(queue=queue, kind="closed", assignee=user)
    assert distribution.return_ticket(closed, actor=user, reason=reason) is None


def test_observer_and_unavailable_are_not_candidates_but_manual_assignment_remains_possible():
    """FR-765/767: наблюдатель и недоступный исключены из авто, ручное назначение разрешено."""
    from apps.servicedesk.services import access, distribution

    queue = sd.make_queue()
    unavailable = _member(queue, "Недоступный")
    observer = _member(queue, "Наблюдатель")
    available = _member(queue, "Доступный")
    sd.add_observer(queue, observer)
    sd.set_unavailable(unavailable, timezone.localdate() + timedelta(days=1), actor=unavailable)
    ids = {person.id for person in access.eligible_assignees(queue.unit_id)}
    assert unavailable.pk not in ids and observer.pk not in ids
    chosen = distribution.choose_evenly(queue.unit_id, access.eligible_assignees(queue.unit_id))
    assert chosen is not None and chosen.id == available.pk
