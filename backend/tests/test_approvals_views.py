"""Тесты страниц согласований (T-14006; SPEC-014, FR-846…848)."""
import json

import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_templates_page_is_admin_only():
    admin = support.logged_in(support.make_admin())
    assert admin.get("/approvals/").status_code == 200
    employee = support.logged_in(support.make_employee())
    assert employee.get("/approvals/").status_code == 403


def test_template_create_and_my_page():
    admin_user = support.make_admin()
    participant = support.make_employee()
    client = support.logged_in(admin_user)
    stages = [{"title": "Этап", "mode": "parallel", "rule": "all", "deadline_hours": 24,
               "participants": [{"kind": "employee", "user_id": participant.pk}]}]
    response = client.post("/approvals/templates/new/", {
        "name": "Шаблон из формы", "subject_type": "ticket", "description": "",
        "enabled": "on", "stages_text": json.dumps(stages, ensure_ascii=False)})
    assert response.status_code == 302
    from apps.approvals.models import ApprovalTemplate, ApprovalRoute
    from apps.approvals.services import routes
    template = ApprovalTemplate.objects.get(name="Шаблон из формы")
    assert template.stages.count() == 1
    assert support.logged_in(participant).get("/approvals/my/").status_code == 200
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin_user, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    page = client.get(f"/approvals/routes/{route.pk}/")
    assert page.status_code == 200
    assert participant.full_name.encode() in page.content



def test_empty_template_form_shows_server_validation():
    client = support.logged_in(support.make_admin())
    response = client.post("/approvals/templates/new/", {
        "name": "Пустой", "subject_type": "ticket", "description": "", "enabled": "on", "stages_text": ""})
    assert response.status_code == 200
    assert "Добавьте хотя бы один этап" in response.content.decode()


def test_future_stage_has_no_decision_form():
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes

    admin_user = support.make_admin()
    participant = support.make_employee()
    template = ApprovalTemplate.objects.create(name="Два этапа", subject_type="ticket", author=admin_user)
    first = ApprovalStage.objects.create(template=template, order=1, title="Первый", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=first, kind="employee", user=admin_user)
    second = ApprovalStage.objects.create(template=template, order=2, title="Второй", mode="parallel", rule="all")
    ApprovalStageParticipant.objects.create(stage=second, kind="employee", user=admin_user)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin_user, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    page = support.logged_in(admin_user).get(f"/approvals/routes/{route.pk}/")
    assert page.content.decode().count('data-form="approval-decision"') == 1
