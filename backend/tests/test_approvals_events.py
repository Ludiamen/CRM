"""Тесты событий маршрута (T-14006; SPEC-014, FR-843)."""
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


def test_approved_route_publishes_stage_then_completed(django_capture_on_commit_callbacks):
    from apps.core import events
    from apps.approvals.services import routes

    participant = support.make_employee()
    admin, template = _template(participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    seen = []
    stage_handler = lambda **data: seen.append(("stage", data))
    completed_handler = lambda **data: seen.append(("completed", data))
    events.subscribe("approvals.stage_completed", stage_handler)
    events.subscribe("approvals.completed", completed_handler)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
            assignment = route.stages.get().assignments.get(user=participant)
            routes.decide(participant, assignment.pk, "approved")
    finally:
        events.unsubscribe("approvals.stage_completed", stage_handler)
        events.unsubscribe("approvals.completed", completed_handler)
    assert [kind for kind, _ in seen] == ["stage", "completed"]
    assert seen[1][1]["event_id"] == f"approval-route:{route.pk}:approved"
    assert seen[1][1]["dedupe_key"] == seen[1][1]["event_id"]


def test_rejected_route_has_no_completed(django_capture_on_commit_callbacks):
    from apps.core import events
    from apps.approvals.services import routes

    participant = support.make_employee()
    admin, template = _template(participant)
    ticket = sd.make_ticket(queue=sd.make_queue())
    seen = []
    rejected_handler = lambda **data: seen.append(data)
    completed_handler = lambda **data: seen.append(data)
    events.subscribe("approvals.rejected", rejected_handler)
    events.subscribe("approvals.completed", completed_handler)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
            assignment = route.stages.get().assignments.get(user=participant)
            routes.decide(participant, assignment.pk, "rejected", "Не подходит")
    finally:
        events.unsubscribe("approvals.rejected", rejected_handler)
        events.unsubscribe("approvals.completed", completed_handler)
    assert len(seen) == 1
    assert seen[0]["subject_id"] == ticket.pk
