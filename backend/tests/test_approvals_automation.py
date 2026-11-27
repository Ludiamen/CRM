"""Тесты интеграции с автоматикой (T-14006; SPEC-014, FR-824, FR-843)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_start_approval_action_is_registered_and_validated():
    from apps.automation.extensions import actions
    from apps.automation.models import Rule, RuleAction
    from apps.automation.services import validation

    author = support.make_admin()
    assert "start_approval" in actions()
    rule = Rule.objects.create(name="Запуск", subject_type="ticket", scope="global", author=author,
                               trigger="ticket_created", enabled=True)
    RuleAction.objects.create(rule=rule, order=1, kind="start_approval", params={"template": 1})
    validation.validate_rule(rule)


def test_rule_starts_route_after_event():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalRoute, ApprovalTemplate
    from apps.automation.models import Rule, RuleAction
    from apps.automation.services import rules

    author = support.make_admin()
    participant = support.make_employee()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=author)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    rule = Rule.objects.create(name="Запуск", subject_type="ticket", scope="global", author=author,
                               trigger="ticket_created", enabled=True)
    RuleAction.objects.create(rule=rule, order=1, kind="start_approval", params={"template": template.pk})
    rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}")
    assert ApprovalRoute.objects.filter(subject_type="ticket", subject_id=ticket.pk).exists()
