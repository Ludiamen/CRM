"""Порог SLA в автоматизации (T-13025; SPEC-013, FR-815)."""
import pytest

from tests import support
from tests import support_servicedesk as sd
from tests.support_automation import make_action, make_rule

pytestmark = pytest.mark.django_db


def test_sla_threshold_event_is_deduplicated(django_capture_on_commit_callbacks):
    from apps.automation.models import RuleRun
    from apps.servicedesk.services import events as sd_events

    author = support.make_employee()
    ticket = sd.make_ticket(queue=sd.make_queue())
    rule = make_rule(author, trigger="sla_threshold", enabled=True)
    make_action(rule, 1, "notify", {"recipients": ["author"], "text": "Просрочка {number}"})
    with django_capture_on_commit_callbacks(execute=True):
        sd_events.sla_threshold(ticket, cycle_id=7, deadline="solution", kind="overdue")
        sd_events.sla_threshold(ticket, cycle_id=7, deadline="solution", kind="overdue")
    assert RuleRun.objects.filter(rule=rule).count() == 1
