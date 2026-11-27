"""Тесты доступа к маршруту и заданиям (T-14006; SPEC-014, FR-830, FR-839…841, FR-846)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _template(participant):
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate

    admin = support.make_admin()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=participant)
    return admin, template


def test_participant_and_initiator_see_route_stranger_does_not():
    from apps.approvals.services import access, routes

    participant, stranger = support.make_employee(), support.make_employee()
    admin, template = _template(participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assert access.can_see_route(participant, route)
    assert access.can_see_route(admin, route)
    assert not access.can_see_route(stranger, route)
    brief = access.brief(route)
    assert ticket.requester_name not in str(brief) if ticket.requester_name else True
    assert ticket.requester_email not in str(brief)


def test_only_pending_assignment_of_actor_can_be_decided():
    from apps.approvals.models import ApprovalAssignment
    from apps.approvals.services import access, routes

    participant, stranger = support.make_employee(), support.make_employee()
    admin, template = _template(participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assignment = route.stages.get().assignments.get(user=participant)
    assert access.can_decide(participant, assignment)
    assert not access.can_decide(stranger, assignment)
    routes.decide(participant, assignment.pk, "approved")
    assignment.refresh_from_db()
    assert assignment.status == ApprovalAssignment.Status.APPROVED
    assert not access.can_decide(participant, assignment)
