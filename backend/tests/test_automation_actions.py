"""Контракты действий автоматизации (T-13036; SPEC-013, FR-799…804/818)."""
import pytest

from tests import support
from tests import support_servicedesk as sd
from tests.support_automation import make_action, make_rule

pytestmark = pytest.mark.django_db


def _rule(author, *actions):
    rule = make_rule(author, trigger="ticket_created", enabled=True)
    for order, (kind, params) in enumerate(actions, start=1):
        make_action(rule, order, kind, params)
    return rule


def test_assign_and_change_status_run_from_rule():
    from apps.automation.services import rules

    author = support.make_admin()
    queue = sd.make_queue()
    assignee = support.make_employee()
    from tests import support_org as org

    org.make_member(assignee, queue.unit)
    ticket = sd.make_ticket(queue=queue)
    rule = _rule(author, ("assign", {"mode": "employee", "employee": assignee.pk}),
                 ("change_status", {"status": support.model("servicedesk.Status").objects.get(kind="in_progress", is_default=True).pk}))
    assert rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}") == 1
    ticket.refresh_from_db()
    assert ticket.assignee_id == assignee.pk
    assert ticket.kind == "in_progress"
    assert rule.runs.filter(status="done").count() == 1


def test_create_task_and_comment_actions():
    from apps.automation.services import rules
    from apps.servicedesk.models import TicketEntry
    from apps.tasks.models import Task

    author = support.make_admin()
    ticket = sd.make_ticket(queue=sd.make_queue())
    _rule(author, ("create_task", {"title": "По заявке {number}", "due_days": 2}),
          ("comment", {"text": "Правило сработало"}))
    rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}")
    task = Task.objects.get(ticket_number=ticket.number)
    assert task.title == f"По заявке {ticket.number}"
    assert TicketEntry.objects.filter(ticket=ticket, kind="comment", author__isnull=True).exists()


def test_failed_action_does_not_stop_next_and_no_pii_in_notification():
    from apps.automation.services import rules
    from apps.notify.models import Notification
    from apps.servicedesk.models import TicketEntry

    author = support.make_admin()
    ticket = sd.make_ticket(queue=sd.make_queue(), assignee=author)
    _rule(author, ("assign", {"mode": "employee", "employee": 999999}),
          ("comment", {"text": "Второе действие"}),
          ("notify", {"recipients": ["assignee"], "text": "Заявка {number}"}))
    rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}")
    assert TicketEntry.objects.filter(ticket=ticket, text="Второе действие").exists()
    assert Notification.objects.filter(kind="automation.rule_notice").exists()
    assert "@" not in Notification.objects.get(kind="automation.rule_notice").text


def test_employee_recipient_and_long_text_are_supported():
    """FR-800/811: выбранный сотрудник и текст до 500 знаков."""
    from apps.automation.services import rules
    from apps.notify.models import Notification
    from tests import support_org as org

    author = support.make_admin()
    queue = sd.make_queue()
    chosen = support.make_employee()
    org.make_member(chosen, queue.unit)
    ticket = sd.make_ticket(queue=queue)
    rule = _rule(author, ("notify", {"recipients": ["employee"], "employee": chosen.pk, "text": "X" * 400}))
    rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}")
    note = Notification.objects.get(kind="automation.rule_notice")
    assert note.user_id == chosen.pk and len(note.text) == 400
    assert rule.runs.count() == 1
