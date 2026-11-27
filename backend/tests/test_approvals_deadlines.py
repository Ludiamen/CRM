"""Тесты «Моих заданий» и сроков (T-14006; SPEC-014, FR-835…838, NFR-748)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _route(*users, due_hours=None, mode="parallel", rule="all"):
    from apps.approvals.models import ApprovalStage, ApprovalStageParticipant, ApprovalTemplate
    from apps.approvals.services import routes

    admin = support.make_admin()
    template = ApprovalTemplate.objects.create(name="Маршрут", subject_type="ticket", author=admin)
    stage = ApprovalStage.objects.create(template=template, order=1, title="Этап", mode=mode, rule=rule,
                                         deadline_hours=due_hours)
    for user in users:
        ApprovalStageParticipant.objects.create(stage=stage, kind="employee", user=user)
    ticket = sd.make_ticket(queue=sd.make_queue())
    route = routes.start(admin, subject_type="ticket", subject_id=ticket.pk, template_id=template.pk)
    return admin, route, route.stages.get().assignments.get(user=users[0])


def test_my_assignments_show_only_current_and_overdue():
    from apps.approvals.services import queue

    first, second = support.make_employee(), support.make_employee()
    admin, route, assignment = _route(first, second, mode="sequential", due_hours=1)
    assignment.due_at = timezone.now() - timedelta(minutes=5)
    assignment.save(update_fields=["due_at"])
    rows = queue.rows(first)
    assert [item["assignment"].pk for item in rows] == [assignment.pk]
    assert rows[0]["overdue"] is True
    assert queue.rows(second) == []


def test_reminder_and_overdue_are_sent_once():
    from apps.approvals.models import ApprovalNotice
    from apps.approvals.services import notices
    from apps.notify.models import Notification

    participant = support.make_employee()
    admin, route, assignment = _route(participant, due_hours=25)
    now = timezone.now() + timedelta(hours=1)
    assert notices.run_due(now) == 1
    assert ApprovalNotice.objects.filter(assignment=assignment, kind="reminder").count() == 1
    assert Notification.objects.filter(kind="approvals.reminder").count() == 2
    assert notices.run_due(now) == 0
    assignment.due_at = now - timedelta(minutes=1)
    assignment.save(update_fields=["due_at"])
    assert notices.run_due(now) == 1
    assert ApprovalNotice.objects.filter(assignment=assignment, kind="overdue").count() == 1


def test_far_deadline_has_no_reminder():
    from apps.approvals.models import ApprovalNotice
    from apps.approvals.services import notices

    participant = support.make_employee()
    admin, route, assignment = _route(participant, due_hours=30)
    assert notices.run_due(timezone.now()) == 0
    assert not ApprovalNotice.objects.filter(assignment=assignment).exists()
