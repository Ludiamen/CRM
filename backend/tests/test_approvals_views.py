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

