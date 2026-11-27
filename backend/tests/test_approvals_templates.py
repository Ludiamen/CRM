"""Тесты шаблонов (T-14004; SPEC-014, FR-820…822, FR-846)."""
import pytest

from tests import support
from tests import support_servicedesk as sd
from tests import support_org

pytestmark = pytest.mark.django_db


def _data(users, *, mode="sequential", rule="all", deadline=None):
    return [{"title": "Этап", "mode": mode, "rule": rule, "deadline_hours": deadline,
             "participants": [{"kind": "employee", "user_id": user.pk} for user in users]}]


def test_template_validation_rejects_sequential_any_and_inactive_employee():
    from apps.approvals.models import ApprovalTemplate
    from apps.approvals.services import templates
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    user = support.make_employee()
    template = ApprovalTemplate(name="Шаблон", subject_type="ticket", author=admin)
    template.save()
    with pytest.raises(ApprovalError) as error:
        templates.save_template(template, actor=admin, stages=_data([user], mode="sequential", rule="any"))
    assert error.value.code == "template_invalid"

    inactive = support.make_employee(state="dismissed")
    with pytest.raises(ApprovalError) as error:
        templates.save_template(template, actor=admin, stages=_data([inactive]))
    assert error.value.code == "template_invalid"


def test_template_without_stages_is_rejected():
    from apps.approvals.models import ApprovalTemplate
    from apps.approvals.services import templates
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    template = ApprovalTemplate.objects.create(name="Пустой", subject_type="ticket", author=admin)
    with pytest.raises(ApprovalError):
        templates.validate(template)


def test_queue_head_participant_is_resolved_at_launch():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes

    admin = support.make_admin()
    head = support.make_employee()
    unit = support_org.make_unit("Очередь согласования")
    support_org.make_member(head, unit, mark="head")
    queue = sd.make_queue(unit=unit)
    template = ApprovalTemplate.objects.create(name="Очередь", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Руководитель", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=stage, kind="queue_head")
    ticket = sd.make_ticket(queue=queue)
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assert route.stages.get().assignments.get().user_id == head.pk


def test_disabled_template_cannot_start_and_edit_does_not_change_snapshot():
    from apps.approvals.models import ApprovalTemplate
    from apps.approvals.services import routes, templates
    from apps.approvals.services.errors import ApprovalError

    admin = support.make_admin()
    user = support.make_employee()
    template = ApprovalTemplate(name="Шаблон", subject_type="ticket", author=admin, enabled=False)
    template.save()
    templates.save_template(template, actor=admin, stages=_data([user]))
    ticket = sd.make_ticket(queue=sd.make_queue())
    with pytest.raises(ApprovalError) as error:
        routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    assert error.value.code == "template_disabled"

    template.enabled = True
    template.save(update_fields=["enabled"])
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    stage = template.stages.get()
    stage.title = "Новое название"
    stage.save(update_fields=["title"])
    route.refresh_from_db()
    assert route.stages.get().title == "Этап"
