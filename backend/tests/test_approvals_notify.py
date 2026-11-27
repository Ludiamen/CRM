"""Тесты уведомлений согласований (T-14006; SPEC-014, FR-842, FR-845)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_assignment_and_decision_notifications_do_not_contain_requester_data():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes
    from apps.notify.models import Notification

    admin = support.make_admin()
    participant = support.make_employee()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=participant)
    ticket = sd.make_ticket(queue=sd.make_queue(), requester_name="Иван Петров",
                            requester_email="ivan@example.com")
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    note = Notification.objects.filter(kind="approvals.assignment", user=participant).first()
    assert note is not None
    assert "Иван" not in note.text and "ivan@" not in note.text and ticket.subject not in note.text
    assignment = route.stages.get().assignments.get(user=participant)
    routes.decide(participant, assignment.pk, "approved", "Секретный комментарий")
    decision = Notification.objects.filter(kind="approvals.decision", user=admin).first()
    assert decision is not None
    assert "Секретный комментарий" not in decision.text


def test_five_notification_kinds_are_registered():
    from apps.notify.services import kinds

    codes = {kind.code for kind in kinds.catalog()}
    assert {"approvals.assignment", "approvals.decision", "approvals.returned",
            "approvals.reminder", "approvals.overdue"} <= codes
