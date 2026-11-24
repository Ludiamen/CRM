"""T-11104: жизненный цикл SlaCycle (FR-738…740, CONTRACT-011 §2.1).

Тесты написаны до реализации SLA в replies/closing и намеренно остаются
красными до этапа 3. Импорты сервисов выполняются только внутри тестов.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _actor():
    return support.make_with_permissions("servicedesk.all")


def _cycle(ticket):
    return support.model("servicedesk.SlaCycle").objects.get(ticket=ticket, is_current=True)


def test_queued_reply_records_first_response_and_reaction_minutes():
    from apps.servicedesk.services import replies

    ticket = sd.make_ticket()
    level = sd.make_level(all_day=True, reaction_minutes=60, solution_minutes=240)
    cycle = sd.make_cycle(ticket, level=level)
    actor = _actor()

    entry = replies.reply(ticket, text="Ответ исполнителя", actor=actor)

    cycle.refresh_from_db()
    assert entry.kind == "reply"
    assert entry.send_state == "queued"
    assert cycle.first_response_at == entry.at
    assert cycle.reaction_minutes == 0
    assert cycle.reaction_met is True


def test_not_sent_reply_is_not_a_first_response():
    from apps.servicedesk.models import TicketEntry
    from apps.servicedesk.services import replies

    ticket = sd.make_ticket()
    cycle = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    entry = TicketEntry.objects.create(
        ticket=ticket, kind=TicketEntry.Kind.REPLY, author=_actor(),
        text="Не ушло", send_state=TicketEntry.SendState.NOT_SENT,
    )
    replies._not_sent(entry, ticket, "delivery_failed")

    cycle.refresh_from_db()
    assert cycle.first_response_at is None
    assert cycle.reaction_minutes is None
    assert cycle.reaction_met is None


def test_comment_and_event_are_not_first_responses():
    from apps.servicedesk.services import replies

    ticket = sd.make_ticket()
    cycle = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    actor = _actor()

    replies.comment(ticket, text="Внутренний комментарий", actor=actor)
    replies.add_event(ticket, "some_event", actor=actor)

    cycle.refresh_from_db()
    assert cycle.first_response_at is None
    assert cycle.reaction_minutes is None


def test_waiting_files_reply_counts_only_after_file_check():
    from apps.servicedesk.models import TicketEntry
    from apps.servicedesk.services import replies

    ticket = sd.make_ticket()
    cycle = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    entry = TicketEntry.objects.create(
        ticket=ticket, kind=TicketEntry.Kind.REPLY, author=_actor(),
        text="Ответ с файлом", send_state=TicketEntry.SendState.WAITING_FILES,
    )

    cycle.refresh_from_db()
    assert cycle.first_response_at is None
    replies.on_files_checked(entry.pk)

    cycle.refresh_from_db()
    entry.refresh_from_db()
    assert entry.send_state == TicketEntry.SendState.QUEUED
    assert cycle.first_response_at == entry.at
    assert cycle.reaction_minutes == 0


def test_manual_close_records_solution_and_manual_kind():
    ticket = sd.make_ticket()
    sd.make_cycle(ticket, level=sd.make_level(all_day=True))

    closed = sd.close_ticket(ticket, actor=_actor())

    cycle = _cycle(closed)
    assert closed.closed_at == cycle.closed_at
    assert cycle.solution_minutes == 0
    assert cycle.solution_met is True
    assert cycle.closed_kind == "manual"


def test_autoclose_records_verdict_and_has_no_author():
    from apps.servicedesk.services import closing

    ticket = sd.make_ticket(kind="waiting")
    cycle = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    now = timezone.now()
    ticket.waiting_since = now - timedelta(days=8)
    ticket.save(update_fields=["waiting_since"])
    sd.configure_servicedesk(autoclose_days=7)

    assert closing.autoclose_one(ticket.pk, now=now) is True

    cycle.refresh_from_db()
    ticket.refresh_from_db()
    assert cycle.closed_kind == "autoclosed"
    assert cycle.closed_at == now
    assert cycle.solution_met is True
    assert ticket.closed_by_id is None


def test_close_after_solution_due_is_late():
    from apps.servicedesk.models import SlaCycle

    ticket = sd.make_ticket()
    cycle = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    late = timezone.now() - timedelta(minutes=1)
    SlaCycle.objects.filter(pk=cycle.pk).update(solution_due=late)

    sd.close_ticket(ticket, actor=_actor())

    cycle.refresh_from_db()
    assert cycle.solution_met is False


def test_manual_reopen_marks_old_cycle_and_starts_cycle_two():
    ticket = sd.make_ticket()
    first = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    sd.close_ticket(ticket, actor=_actor())
    closed_at = ticket.closed_at

    reopened = sd.reopen_ticket(ticket, actor=_actor())

    first.refresh_from_db()
    current = _cycle(reopened)
    assert first.is_current is False
    assert current.number == 2
    assert current.is_current is True
    assert current.cycle_started_at >= closed_at
    assert current.reaction_due > current.cycle_started_at


def test_mail_reopen_starts_cycle_at_inbound_received_at():
    from apps.servicedesk.services import closing

    ticket = sd.make_ticket()
    sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    sd.close_ticket(ticket, actor=_actor())
    received_at = ticket.closed_at - timedelta(hours=2)

    closing.reopen(ticket, actor=None, at=received_at, via="mail")

    current = _cycle(ticket)
    assert current.number == 2
    assert current.cycle_started_at == received_at


def test_reopened_ticket_keeps_history_but_only_new_cycle_is_current():
    ticket = sd.make_ticket()
    first = sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    sd.close_ticket(ticket, actor=_actor())
    sd.reopen_ticket(ticket, actor=_actor())

    Cycle = support.model("servicedesk.SlaCycle")
    first.refresh_from_db()
    current = _cycle(ticket)
    assert Cycle.objects.filter(ticket=ticket).count() == 2
    assert first.is_current is False
    assert current.is_current is True
    assert list(Cycle.objects.filter(ticket=ticket, is_current=True)) == [current]


def test_closed_journal_contains_cycle_number_and_verdicts():
    from apps.core.models import AuditEvent

    ticket = sd.make_ticket()
    sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    sd.close_ticket(ticket, actor=_actor())

    event = AuditEvent.objects.filter(action="ticket.closed", object_id=str(ticket.number)).latest("id")
    assert event.after["cycle"] == 1
    assert "reaction_due" in event.after
    assert "solution_due" in event.after
    assert event.after["verdicts"]["solution"] == "met"


def test_repeated_sla_tick_does_not_change_closed_cycle_verdicts():
    from apps.servicedesk import tasks

    ticket = sd.make_ticket()
    sd.make_cycle(ticket, level=sd.make_level(all_day=True))
    sd.close_ticket(ticket, actor=_actor())
    cycle = _cycle(ticket)
    before = {
        "reaction_met": cycle.reaction_met,
        "solution_met": cycle.solution_met,
        "closed_at": cycle.closed_at,
    }

    tasks.sla_tick()
    tasks.sla_tick()

    cycle.refresh_from_db()
    assert {
        "reaction_met": cycle.reaction_met,
        "solution_met": cycle.solution_met,
        "closed_at": cycle.closed_at,
    } == before


def test_ticket_without_level_has_no_cycle_after_close():
    ticket = sd.make_ticket()
    sd.close_ticket(ticket, actor=_actor())

    Cycle = support.model("servicedesk.SlaCycle")
    assert not Cycle.objects.filter(ticket=ticket).exists()
