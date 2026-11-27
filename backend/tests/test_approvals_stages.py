"""Тесты последовательного этапа и выбывания (T-14005; SPEC-014, FR-827)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _route(users, mode="sequential"):
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes

    admin = support.make_admin()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode=mode, rule="all")
    for user in users:
        ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=user)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    return admin, route, route.stages.get()


def test_sequential_shows_one_active_assignment_at_a_time():
    from apps.approvals.services import queue

    first, second = support.make_employee(), support.make_employee()
    admin, route, stage = _route([first, second])
    first_assignment = stage.assignments.get(user=first)
    assert [item["assignment"].pk for item in queue.rows(first)] == [first_assignment.pk]
    assert queue.rows(second) == []
    from apps.approvals.services import routes
    routes.decide(first, first_assignment.pk, "approved")
    assert queue.rows(second)


def test_dismissed_current_participant_passes_to_next():
    from apps.approvals.models import ApprovalAssignment
    from apps.approvals.services import routes

    first, second, third = (support.make_employee() for _ in range(3))
    admin, route, stage = _route([first, second, third])
    routes.decide(first, stage.assignments.get(user=first).pk, "approved")
    second.state = "dismissed"
    second.save(update_fields=["state"])
    routes.drop_inactive()
    assert stage.assignments.get(user=second).status == ApprovalAssignment.Status.CANCELLED
    assert stage.assignments.get(user=third).status == ApprovalAssignment.Status.PENDING
    assert stage.assignments.get(user=third).pk in [a.pk for a in stage.assignments.filter(status="pending")]
