"""Красные контракты отложенных действий (T-13006; FR-807/808)."""
import pytest

from tests import support
from tests import support_servicedesk as sd
from tests.support_automation import make_action, make_rule

pytestmark = pytest.mark.django_db


def test_delayed_action_is_pending_until_tick_and_cancelled_on_disable():
    from apps.automation.services import tick

    from apps.automation.services import rules

    author = support.make_employee()
    ticket = sd.make_ticket(queue=sd.make_queue())
    rule = make_rule(author, enabled=True)
    make_action(rule, 1, "notify", {"recipients": ["assignee"], "text": "Поздно"}, delay_seconds=7200)
    rules.on_event("ticket", ticket.pk, "ticket_created", "created:delayed")
    assert tick.pending_count(rule=rule) == 1
    rule.enabled = False
    rule.save(update_fields=["enabled"])
    tick.cancel_rule(rule)
    assert tick.pending_count(rule=rule) == 0


def test_delayed_action_starts_new_chain_at_depth_one(django_capture_on_commit_callbacks):
    """FR-806/808: отложенное действие продолжает root, но новое событие идёт с глубиной 1."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.automation.models import RuleRun
    from apps.automation.services import rules, tick
    from tests.support_automation import make_action, make_rule

    author = support.make_admin()
    ticket = sd.make_ticket(queue=sd.make_queue())
    first = make_rule(author, enabled=True)
    make_action(first, 1, "change_status",
                {"status": support.model("servicedesk.Status").objects.get(kind="in_progress", is_default=True).pk},
                delay_seconds=1)
    second = make_rule(author, trigger="ticket_status_changed", enabled=True)
    make_action(second, 1, "comment", {"text": "После смены"})
    rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}")
    with django_capture_on_commit_callbacks(execute=True):
        tick.run_due(now=timezone.now() + timedelta(seconds=5))
    run = RuleRun.objects.get(rule=second)
    assert run.depth == 1
    assert run.root_run_id is not None
