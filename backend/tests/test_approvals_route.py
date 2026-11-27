"""Тесты запуска и снимка маршрута (T-14004; SPEC-014, FR-820…826, FR-849)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _template(*, subject="ticket", stages=None, enabled=True, author=None):
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate

    author = author or support.make_admin()
    template = ApprovalTemplate.objects.create(name="Согласование", subject_type=subject,
                                               author=author, enabled=enabled)
    for index, (mode, rule, users) in enumerate(stages or [("sequential", "all", [support.make_employee()])], 1):
        stage = ApprovalStage.objects.create(template=template, order=index, title=f"Этап {index}",
                                             mode=mode, rule=rule)
        for user in users:
            ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=user)
    return template


def test_start_creates_snapshot_and_first_stage():
    from apps.approvals.models import ApprovalAssignment, ApprovalRoute, ApprovalStageRun
    from apps.approvals.services import routes

    admin = support.make_admin()
    participant = support.make_employee()
    template = _template(stages=[("sequential", "all", [participant]), ("parallel", "all", [participant])])
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assert route.status == ApprovalRoute.Status.RUNNING
    assert route.subject_number == ticket.number
    assert route.stages.count() == 2
    first = route.stages.get(order=1)
    assert first.status == ApprovalStageRun.Status.RUNNING
    assert first.assignments.count() == 1
    assert route.stages.get(order=2).status == ApprovalStageRun.Status.WAITING
    assert ApprovalAssignment.objects.filter(stage_run=first, user=participant).exists()


def test_second_start_is_rejected_by_active_route():
    from apps.approvals.services import routes
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    template = _template()
    ticket = sd.make_ticket(queue=sd.make_queue())
    routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    with pytest.raises(ApprovalError) as error:
        routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assert error.value.code == "route_exists"


def test_closed_ticket_and_deleted_or_done_task_are_rejected():
    from apps.approvals.services import routes
    from apps.approvals.services.errors import ApprovalError
    from tests import support_tasks

    admin = support.make_admin()
    template = _template()
    ticket = sd.make_ticket(queue=sd.make_queue())
    ticket.closed_at = ticket.closed_at or __import__("django.utils.timezone", fromlist=["now"]).now()
    ticket.save(update_fields=["closed_at"])
    with pytest.raises(ApprovalError) as error:
        routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assert error.value.code == "subject_closed"

    task = support_tasks.make_task("Закрытая", author=admin, assignee=admin, status="done")
    task_template = _template(subject="task")
    with pytest.raises(ApprovalError) as error:
        routes.start(admin, subject_type="task", subject_id=task.pk, template_id=task_template.pk)
    assert error.value.code == "subject_closed"
