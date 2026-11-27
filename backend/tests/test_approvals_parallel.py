"""Тесты параллельных этапов (T-14005; SPEC-014, FR-828)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _template(mode, rule, users):
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate

    admin = support.make_admin()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode=mode, rule=rule)
    for user in users:
        ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=user)
    return admin, template


def test_parallel_all_waits_for_everyone():
    from apps.approvals.models import ApprovalAssignment, ApprovalStageRun
    from apps.approvals.services import routes

    first, second = support.make_employee(), support.make_employee()
    admin, template = _template("parallel", "all", [first, second])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    stage = route.stages.get()
    routes.decide(first, stage.assignments.get(user=first).pk, "approved")
    stage.refresh_from_db()
    assert stage.status == ApprovalStageRun.Status.RUNNING
    assert stage.assignments.get(user=second).status == ApprovalAssignment.Status.PENDING
    routes.decide(second, stage.assignments.get(user=second).pk, "approved")
    stage.refresh_from_db()
    assert stage.status == ApprovalStageRun.Status.DONE


def test_parallel_any_first_approval_completes_stage():
    from apps.approvals.models import ApprovalAssignment
    from apps.approvals.services import routes

    first, second, third = (support.make_employee() for _ in range(3))
    admin, template = _template("parallel", "any", [first, second, third])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    stage = route.stages.get()
    routes.decide(first, stage.assignments.get(user=first).pk, "approved")
    assert stage.assignments.get(user=second).status == ApprovalAssignment.Status.CANCELLED
    assert stage.assignments.get(user=third).status == ApprovalAssignment.Status.CANCELLED
