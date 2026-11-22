"""Личные колонки плана (срез 009, T-9207; CONTRACT-009, 6.2)."""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from apps.core.services import permissions
from apps.core.views.common import is_fragment, render_page
from apps.tasks.models import PlanColumn
from apps.tasks.services import boards, plan
from apps.tasks.services.errors import TasksError


def _board(request, error=None):
    context = {"board": "plan", "title": "Мой план", "columns": boards.plan_columns(request.user), "move": True,
               "plan_owner": request.user, "plan_readonly": False}
    if error is not None:
        context["error"] = error
    return render_page(request, "tasks/_board.html", context)


def _fail(request, exc: TasksError):
    return render_page(request, "tasks/board.html", {
        "board": "plan", "title": "Мой план", "columns": boards.plan_columns(request.user),
        "error": {"field": exc.field, "code": exc.code, "message": exc.message}}, status=200)


@require_POST
@permissions.require_permission("tasks.use")
def add_column(request):
    try:
        plan.add_column(request.user, request.POST.get("title", ""))
    except TasksError as exc:
        return _fail(request, exc)
    return redirect("/tasks/board/plan/") if not is_fragment(request) else _board(request)


@require_POST
@permissions.require_permission("tasks.use")
def edit_column(request, column_id):
    column = PlanColumn.objects.filter(pk=column_id).first()
    if column is None:
        raise Http404
    try:
        plan.rename_column(request.user, column, request.POST.get("title", column.title),
                           request.POST.get("position"))
    except TasksError as exc:
        if exc.code == "plan_forbidden":
            raise PermissionDenied from exc
        return _fail(request, exc)
    return redirect("/tasks/board/plan/") if not is_fragment(request) else _board(request)


@require_POST
@permissions.require_permission("tasks.use")
def delete_column(request, column_id):
    column = PlanColumn.objects.filter(pk=column_id).first()
    if column is None:
        raise Http404
    if request.POST.get("confirm") != "1":
        return render_page(request, "tasks/board.html", {
            "board": "plan", "title": "Мой план", "columns": boards.plan_columns(request.user),
            "confirm_column": column})
    try:
        plan.delete_column(request.user, column)
    except TasksError as exc:
        if exc.code == "plan_forbidden":
            raise PermissionDenied from exc
        return _fail(request, exc)
    return redirect("/tasks/board/plan/") if not is_fragment(request) else _board(request)