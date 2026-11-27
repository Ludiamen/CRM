"""Тесты этапов и решений (T-14005; SPEC-014, FR-827…834, FR-838)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _template(stages, *, author=None, subject="ticket"):
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate

    author = author or support.make_admin()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type=subject, author=author)
    for index, stage_data in enumerate(stages, 1):
        mode, rule, users = stage_data
        stage = ApprovalStage.objects.create(template=template, order=index, title=f"Этап {index}",
                                             mode=mode, rule=rule)
        for user in users:
            ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=user)
    return template


def test_sequential_two_stages_and_status_unchanged():
    from apps.approvals.models import ApprovalAssignment, ApprovalRoute, ApprovalStageRun
    from apps.approvals.services import routes

    admin = support.make_admin()
    first, second = support.make_employee(), support.make_employee()
    template = _template([("sequential", "all", [first]), ("sequential", "all", [second])])
    ticket = sd.make_ticket(queue=sd.make_queue())
    before = ticket.status_id
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    stage1 = route.stages.get(order=1)
    assignment1 = stage1.assignments.get(user=first)
    routes.decide(first, assignment1.pk, "approved")
    stage1.refresh_from_db()
    route.refresh_from_db()
    assert stage1.status == ApprovalStageRun.Status.DONE
    assert route.stages.get(order=2).status == ApprovalStageRun.Status.RUNNING
    assert route.stages.get(order=2).assignments.get(user=second).status == ApprovalAssignment.Status.PENDING
    assignment2 = route.stages.get(order=2).assignments.get(user=second)
    routes.decide(second, assignment2.pk, "approved")
    route.refresh_from_db()
    assert route.status == ApprovalRoute.Status.APPROVED
    ticket.refresh_from_db()
    assert ticket.status_id == before


def test_parallel_any_cancels_others_and_approves_route():
    from apps.approvals.models import ApprovalAssignment, ApprovalRoute
    from apps.approvals.services import routes

    admin = support.make_admin()
    first, second = support.make_employee(), support.make_employee()
    template = _template([("parallel", "any", [first, second])])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assignment = route.stages.get().assignments.get(user=first)
    routes.decide(first, assignment.pk, "approved")
    route.refresh_from_db()
    assert route.status == ApprovalRoute.Status.APPROVED
    assert route.stages.get().assignments.get(user=second).status == ApprovalAssignment.Status.CANCELLED


def test_reject_requires_comment_and_cancels_route():
    from apps.approvals.models import ApprovalAssignment, ApprovalRoute
    from apps.approvals.services import routes
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    first, second = support.make_employee(), support.make_employee()
    template = _template([("parallel", "all", [first, second])])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assignment = route.stages.get().assignments.get(user=first)
    with pytest.raises(ApprovalError) as error:
        routes.decide(first, assignment.pk, "rejected", "")
    assert error.value.code == "comment_required"
    routes.decide(first, assignment.pk, "rejected", "Не подходит")
    route.refresh_from_db()
    assert route.status == ApprovalRoute.Status.REJECTED
    assert route.stages.get().assignments.get(user=second).status == ApprovalAssignment.Status.CANCELLED


def test_decision_is_idempotent_and_conflict_is_rejected():
    from apps.approvals.services import routes
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    participant = support.make_employee()
    template = _template([("parallel", "all", [participant])])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assignment = route.stages.get().assignments.get(user=participant)
    routes.decide(participant, assignment.pk, "approved")
    assert routes.decide(participant, assignment.pk, "approved").pk == assignment.pk
    with pytest.raises(ApprovalError) as error:
        routes.decide(participant, assignment.pk, "rejected", "Поздно")
    assert error.value.code == "already_decided"


def test_foreign_actor_and_cancelled_route():
    from apps.approvals.models import ApprovalRoute
    from apps.approvals.services import routes
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    participant, stranger = support.make_employee(), support.make_employee()
    template = _template([("parallel", "all", [participant])])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assignment = route.stages.get().assignments.get(user=participant)
    with pytest.raises(ApprovalError) as error:
        routes.decide(stranger, assignment.pk, "approved")
    assert error.value.code == "forbidden"
    cancelled = routes.cancel(admin, route.pk)
    assert cancelled.status == ApprovalRoute.Status.CANCELLED
    assert routes.cancel(admin, route.pk).status == ApprovalRoute.Status.CANCELLED
