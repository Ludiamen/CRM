"""Красные контракты журнала автоматизации (T-13006; FR-809/810/817)."""
import pytest

from tests import support
from tests.support_automation import make_rule

pytestmark = pytest.mark.django_db


def test_rule_change_is_audited_without_requester_data():
    from apps.core.models import AuditEvent
    from apps.automation.services import journal

    rule = make_rule(support.make_employee())
    journal.rule_changed(rule, "automation.rule_created", actor=rule.author)
    event = AuditEvent.objects.filter(action="automation.rule_created").latest("pk")
    assert event.object_id == str(rule.pk)
    text = str(event.after)
    assert "@" not in text
