"""Тесты журнала согласований (T-14006; SPEC-014, FR-844, FR-845)."""
import json

import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_journal_records_start_and_decision_without_comment():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes
    from apps.core.models import AuditEvent

    admin = support.make_admin()
    participant = support.make_employee()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assignment = route.stages.get().assignments.get(user=participant)
    routes.decide(participant, assignment.pk, "rejected", "Комментарий-ПДн")
    actions = set(AuditEvent.objects.filter(object_type="approvals.route").values_list("action", flat=True))
    assert "approvals.route_started" in actions
    assert "approvals.decision" in actions
    for event in AuditEvent.objects.filter(object_type="approvals.route"):
        assert "Комментарий-ПДн" not in json.dumps(event.after, ensure_ascii=False)
