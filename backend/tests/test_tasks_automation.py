"""Автоматика задач (T-13024; SPEC-013, FR-796/816)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_tasks
from tests.support_automation import make_action, make_rule

pytestmark = pytest.mark.django_db


def test_task_threshold_runs_once_and_status_change_is_published(django_capture_on_commit_callbacks):
    from apps.automation.models import RuleRun
    from apps.tasks.tasks import tasks_automation_tick

    author = support.make_employee()
    task = support_tasks.make_task(author=author, assignee=author,
                                   deadline=timezone.localdate() - timedelta(days=1))
    rule = make_rule(author, subject_type="task", trigger="task_threshold", enabled=True)
    make_action(rule, 1, "comment", {"text": "Просрочено"})
    with django_capture_on_commit_callbacks(execute=True):
        tasks_automation_tick()
        tasks_automation_tick()
    assert RuleRun.objects.filter(rule=rule, subject_type="task", subject_id=task.pk).count() == 1
