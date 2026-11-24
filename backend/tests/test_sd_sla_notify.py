"""T-11107: уведомления и задания контроля сроков SLA.

Тесты намеренно написаны до реализации ``servicedesk.tasks.sla_tick`` /
``sla_digest`` и видов уведомлений T-11207.
"""
from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _scene(*, assignee=None, subject=None, level=None, started_at=None, **cycle):
    """Очередь, участник и заявка с текущим циклом SLA."""
    unit = support_org.make_unit()
    assignee = assignee or support.make_employee()
    support_org.make_member(assignee, unit)
    queue = sd.make_queue(unit=unit)
    ticket = sd.make_ticket(queue=queue, assignee=assignee, subject=subject or "Тема SLA")
    level = level or sd.make_level(all_day=True, reaction_minutes=60, solution_minutes=240)
    cycle = sd.make_cycle(ticket, level=level, assignee=assignee, cycle_started_at=started_at, **cycle)
    return unit, queue, assignee, ticket, cycle


def _catalog():
    from apps.core import extensions

    return extensions.registered("notification_kinds")


def test_sla_notification_kinds_are_registered_with_russian_names_and_orders():
    expected = {
        "servicedesk.sla_due_soon": 230,
        "servicedesk.sla_overdue": 231,
        "servicedesk.sla_digest": 232,
    }
    kinds = [kind for factory in _catalog() for kind in factory()]
    found = {kind.code: kind for kind in kinds if kind.code in expected}

    assert set(found) == set(expected)
    assert {code: found[code].order for code in expected} == expected
    for kind in found.values():
        assert kind.module == "Сервис-деск"
        assert kind.title
        assert any("\u0400" <= char <= "\u04ff" for char in kind.title)


def test_sla_external_delivery_contains_event_and_link_but_not_ticket_subject():
    from apps.notify.services import delivery, kinds as notify_kinds
    from apps.notify.models import Delivery, Notification
    from apps.servicedesk import tasks

    _, _, assignee, ticket, cycle = _scene(subject="Секретная тема заявки")
    cycle.reaction_due = timezone.now() - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])
    from django.test import TestCase

    with TestCase.captureOnCommitCallbacks(execute=True):
        tasks.sla_tick(now=timezone.now())

    note = Notification.objects.get(user=assignee, kind="servicedesk.sla_overdue")
    assert note.url == f"/tickets/{ticket.number}/"
    assert "Секретная тема заявки" not in note.text
    rows = Delivery.objects.filter(notification=note, channel__in=("telegram", "max", "webpush"))
    for row in rows:
        assert "Секретная тема заявки" not in delivery.external_text(row)
        assert notify_kinds.external_text(notify_kinds.get(note.kind), note.object_ref)


def test_heads_of_unit_returns_heads_and_deputies_of_unit_and_ancestors_once():
    from apps.org.services import structure

    tree = support_org.make_tree({"Отдел SLA": {"Группа SLA": {}}})
    top, nested = tree["Отдел SLA"], tree["Группа SLA"]
    people = [
        support.make_employee(),
        support.make_employee(),
        support.make_employee(),
        support.make_employee(),
    ]
    for person, unit, mark in zip(
        people, (top, top, nested, nested), ("head", "deputy", "head", "deputy")
    ):
        support_org.make_member(person, unit, mark=mark)
    support_org.make_member(people[0], nested, mark="head")

    got = structure.heads_of_unit(nested.pk)

    assert {person.pk for person in got} == {person.pk for person in people}
    assert len(got) == len({person.pk for person in got})


def test_sla_tick_creates_reaction_reminder_configured_working_hours_before_due():
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now + timedelta(hours=2)
    cycle.save(update_fields=["reaction_due"])
    sd.configure_servicedesk(sla_reminder_hours=2)

    tasks.sla_tick(now=now)

    rows = sd.notice_rows(recipient=assignee, deadline="reaction", kind="due_soon")
    assert len(rows) == 1
    assert rows[0]["due_at"] == cycle.reaction_due


def test_sla_tick_creates_separate_solution_deadline_reminder():
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.solution_due = now + timedelta(minutes=1)
    cycle.save(update_fields=["solution_due"])
    sd.configure_servicedesk(sla_reminder_hours=1)

    tasks.sla_tick(now=now)

    rows = sd.notice_rows(recipient=assignee, deadline="solution", kind="due_soon")
    assert len(rows) == 1
    assert rows[0]["due_at"] == cycle.solution_due


def test_sla_tick_notifies_assignee_and_queue_heads_once_for_each_overdue_deadline():
    from apps.org.services import structure
    from apps.servicedesk import tasks

    unit, _, assignee, _, cycle = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.solution_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due", "solution_due"])

    tasks.sla_tick(now=now)

    recipients = {row["recipient"] for row in sd.notice_rows(kind="overdue")}
    assert recipients == {assignee.pk, head.pk, *[person.pk for person in structure.heads_of_unit(unit.pk)]}
    assert sd.notice_rows(recipient=assignee, deadline="reaction", kind="overdue")
    assert sd.notice_rows(recipient=assignee, deadline="solution", kind="overdue")


def test_repeated_sla_tick_is_idempotent_for_sla_notices():
    from apps.servicedesk import tasks

    _, _, _, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])

    tasks.sla_tick(now=now)
    first = sd.notice_rows()
    tasks.sla_tick(now=now + timedelta(minutes=5))

    assert sd.notice_rows() == first


def test_recalculated_due_at_creates_new_notice_without_suppressing_old_one():
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])
    tasks.sla_tick(now=now)
    cycle.reaction_due = now + timedelta(hours=1)
    cycle.save(update_fields=["reaction_due"])
    tasks.sla_tick(now=now)

    rows = sd.notice_rows(recipient=assignee, deadline="reaction", kind="overdue")
    assert {row["due_at"] for row in rows} == {now - timedelta(minutes=1)}
    rows = sd.notice_rows(recipient=assignee, deadline="reaction", kind="due_soon")
    assert {row["due_at"] for row in rows} == {now + timedelta(hours=1)}


def test_sla_reminder_hours_accepts_one_and_24_but_rejects_25():
    from apps.servicedesk.services import settings
    from apps.servicedesk.services.errors import ServiceDeskError

    actor = support.make_employee()
    for value in (1, 24):
        assert settings.update(actor=actor, sla_reminder_hours=value).sla_reminder_hours == value
    with pytest.raises(ServiceDeskError):
        settings.update(actor=actor, sla_reminder_hours=25)


def test_recipient_without_ticket_visibility_gets_no_sla_notification():
    from apps.servicedesk import tasks

    _, _, _, _, cycle = _scene()
    outsider = support.make_employee()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])

    tasks.sla_tick(now=now)

    assert not sd.notice_rows(recipient=outsider)


def test_manual_sla_event_excludes_event_author_from_recipients():
    from apps.servicedesk.notify_kinds import notification_kinds

    _, _, assignee, ticket, _ = _scene()
    kind = next(item for item in notification_kinds() if item.code == "servicedesk.sla_overdue")
    drafts = kind.build(
        "servicedesk.sla_overdue",
        {"number": ticket.number, "actor_id": assignee.pk},
    )

    assert assignee.pk not in {draft.user_id for draft in drafts}


def test_sla_digest_is_sent_once_per_day_to_each_queue_head():
    from apps.servicedesk import tasks
    from apps.servicedesk.models import SlaDigest

    unit, _, _, _, _ = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    from zoneinfo import ZoneInfo

    msk = ZoneInfo("Europe/Moscow")
    day = timezone.now().astimezone(msk).date()
    now = datetime.combine(day, time(9, 30), tzinfo=msk)  # первый час после начала рабочего дня

    tasks.sla_digest(now=now)
    tasks.sla_digest(now=now + timedelta(hours=1))

    assert SlaDigest.objects.filter(recipient=head, day=day).count() == 1
