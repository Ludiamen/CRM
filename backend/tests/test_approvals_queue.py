"""Тесты службы «Мои задания» (T-14006; SPEC-014, FR-835, FR-837)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_queue_returns_subject_stage_and_due():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import queue, routes

    admin = support.make_admin()
    participant = support.make_employee()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Согласовать", mode="parallel",
                                         rule="all", deadline_hours=48)
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    rows = queue.rows(participant)
    assert len(rows) == 1
    assert rows[0]["brief"]["number"] == ticket.number
    assert rows[0]["stage"].title == "Согласовать"
    assert rows[0]["due_at"] is not None
