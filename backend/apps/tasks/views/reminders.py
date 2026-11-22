"""Ручные напоминания и «Отложить» (срез 009, T-9211; CONTRACT-009, 6.2)."""
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.core.services import permissions
from apps.core.views.common import is_fragment
from apps.tasks.models import Task, TaskReminder
from apps.tasks.services import access, plan, reminders as service
from apps.tasks.services import tasks as task_service
from apps.tasks.services.errors import TasksError
from apps.tasks.views.actions import _card


def _task(request, task_id) -> Task:
    task = Task.objects.filter(pk=task_id).first()
    if task is None or not access.visible(request.user, task):
        raise Http404
    return task


@require_POST
@permissions.require_permission("tasks.use")
def remind(request, task_id):
    task = _task(request, task_id)
    try:
        service.set_manual(request.user, task, days=request.POST.get("days"), on=request.POST.get("on"))
    except TasksError as exc:
        return _card(request, task, {"field": exc.field, "code": exc.code, "message": exc.message})
    return _card(request, task) if is_fragment(request) else redirect(f"/tasks/{task.pk}/")


@require_POST
@permissions.require_permission("tasks.use")
def postpone(request, reminder_id):
    reminder = TaskReminder.objects.select_related("task").filter(pk=reminder_id).first()
    if reminder is None or not access.visible(request.user, reminder.task):
        raise Http404
    try:
        service.postpone(request.user, reminder)
    except TasksError as exc:
        if exc.code == "reminder_forbidden_other":
            raise Http404 from exc
        return _card(request, reminder.task, {"field": exc.field, "code": exc.code, "message": exc.message})
    return _card(request, reminder.task) if is_fragment(request) else redirect(f"/tasks/{reminder.task_id}/")
