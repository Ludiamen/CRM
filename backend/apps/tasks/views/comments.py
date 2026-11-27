"""Комментарии задачи (срез 009, T-9210; CONTRACT-009, 6.2)."""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.core.services import permissions
from apps.core.views.common import is_fragment, render_page
from apps.tasks.models import Task, TaskCategory, TaskComment
from apps.tasks.services import access, comments as service, plan
from apps.tasks.services import card
from apps.tasks.services import tasks as task_service
from apps.tasks.services.errors import TasksError


def _task(request, task_id) -> Task:
    task = Task.objects.filter(pk=task_id).first()
    if task is None or not access.visible(request.user, task):
        raise Http404
    return task


def _card(request, task, error=None):
    return render_page(request, "tasks/_card.html", {
        "task": task, "comments": task.comments.select_related("author"),
        "feed": task_service.feed(task),
        "reminders": task.reminders.order_by("moment", "pk"),
        "can_edit": access.can_edit_fields(request.user, task),
        "can_status": access.can_change_status(request.user, task),
        "can_delete": access.can_delete(request.user, task), "can_comment": access.can_comment(request.user, task),
        "columns": plan.columns_of(task.assignee),
        "categories": TaskCategory.objects.all(),
        "error": error, "card_parts": card.card_parts(request, task)}, status=200)


@require_POST
@permissions.require_permission("tasks.use")
def add(request, task_id):
    task = _task(request, task_id)
    try:
        service.add(request.user, task, request.POST.get("text", ""), request.POST.getlist("files"))
    except TasksError as exc:
        if exc.code == "comment_forbidden":
            raise PermissionDenied from exc
        return _card(request, task, {"field": exc.field, "code": exc.code, "message": exc.message})
    return _card(request, task) if is_fragment(request) else redirect(f"/tasks/{task.pk}/")


def _comment(request, comment_id) -> TaskComment:
    comment = TaskComment.objects.select_related("task").filter(pk=comment_id).first()
    if comment is None or not access.visible(request.user, comment.task):
        raise Http404
    return comment


@require_POST
@permissions.require_permission("tasks.use")
def edit(request, comment_id):
    comment = _comment(request, comment_id)
    if comment.deleted_at is not None:
        raise Http404
    if not access.can_edit_comment(request.user, comment):
        raise PermissionDenied
    try:
        service.edit(request.user, comment, request.POST.get("text", ""))
    except TasksError as exc:
        return _card(request, comment.task, {"field": exc.field, "code": exc.code, "message": exc.message})
    return _card(request, comment.task) if is_fragment(request) else redirect(f"/tasks/{comment.task_id}/")


@require_POST
@permissions.require_permission("tasks.use")
def remove(request, comment_id):
    comment = _comment(request, comment_id)
    if comment.deleted_at is not None:
        raise Http404
    if not access.can_edit_comment(request.user, comment):
        raise PermissionDenied
    service.remove(request.user, comment)
    return _card(request, comment.task) if is_fragment(request) else redirect(f"/tasks/{comment.task_id}/")
