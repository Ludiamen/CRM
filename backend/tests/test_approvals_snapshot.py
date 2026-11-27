"""Тесты снимка маршрута (T-14004; SPEC-014, FR-826)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_snapshot_keeps_participants_and_stage_after_template_edit():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes

    admin = support.make_admin()
    first, second = support.make_employee(), support.make_employee()
    template = ApprovalTemplate.objects.create(name="Шаблон", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Первый", mode="sequential", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=first)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)

    stage.title = "Правка"
    stage.save(update_fields=["title"])
    ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=second)

    route.refresh_from_db()
    assert route.stages.get().title == "Первый"
    assert route.stages.get().assignments.count() == 1
    assert route.stages.get().assignments.get().user_id == first.pk
