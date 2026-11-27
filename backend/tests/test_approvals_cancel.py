"""Тесты отмены маршрута (T-14005; SPEC-014, FR-834)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _route():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes

    admin = support.make_admin()
    participant = support.make_employee()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    return admin, participant, route, route.stages.get().assignments.get(user=participant)


def test_initiator_and_admin_can_cancel_and_second_cancel_is_idempotent():
    from apps.approvals.models import ApprovalAssignment, ApprovalRoute
    from apps.approvals.services import routes

    admin, participant, route, assignment = _route()
    cancelled = routes.cancel(admin, route.pk)
    assert cancelled.status == ApprovalRoute.Status.CANCELLED
    assignment.refresh_from_db()
    assert assignment.status == ApprovalAssignment.Status.CANCELLED
    assert routes.cancel(admin, route.pk).pk == route.pk


def test_finished_route_cannot_be_cancelled():
    from apps.approvals.services import routes
    from apps.approvals.services.errors import ApprovalError

    admin, participant, route, assignment = _route()
    routes.decide(participant, assignment.pk, "approved")
    with pytest.raises(ApprovalError) as error:
        routes.cancel(admin, route.pk)
    assert error.value.code == "route_finished"
