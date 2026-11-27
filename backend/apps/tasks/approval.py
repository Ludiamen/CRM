"""Адаптер задачи для согласований (PLAN-014, T-14011)."""
from apps.approvals.extensions import ApprovalSubject

from .models import Task
from .services import access


def approval_subject() -> ApprovalSubject:
    return ApprovalSubject(
        type="task",
        title="Задача",
        load=_load,
        lock=_lock,
        brief=_brief,
        can_view=access.visible,
        can_work=access.can_change_status,
        url=lambda task: f"/tasks/{task.pk}/",
    )


def _query():
    return Task.objects.select_related("author", "assignee").filter(deleted_at__isnull=True)


def _load(pk: int):
    return _query().filter(pk=pk).first()


def _lock(pk: int):
    return _query().select_for_update().filter(pk=pk).first()


def _brief(task) -> dict:
    return {
        "number": task.pk,
        "title": task.title,
        "status": task.get_status_display(),
        "description": task.description,
        "queue": "Задачи",
        "url": f"/tasks/{task.pk}/",
        "closed": task.status == Task.Status.DONE,
    }
