"""Файлы задачи: загрузка и выдача (срез 009, T-9210; CONTRACT-009, 6.2)."""
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.core.services import permissions
from apps.core.views.common import render_page
from apps.tasks.models import Task, TaskFile
from apps.tasks.services import access, files as service
from apps.tasks.services.errors import TasksError

MESSAGES = {"pending": "Файл ещё проверяется", "quarantine": "Файл в карантине"}


def _task(request, task_id=None) -> Task:
    task = Task.objects.filter(pk=task_id).first()
    if task is None or not access.visible(request.user, task):
        raise Http404
    return task


@require_POST
@permissions.require_permission("tasks.use")
def upload(request):
    task = _task(request, request.POST.get("task"))
    try:
        entry = service.store(request.user, task, request.FILES.get("file"))
    except TasksError as exc:
        return render(request, "tasks/_file_error.html",
                      {"error": {"field": exc.field, "code": exc.code, "message": exc.message}}, status=200)
    return render(request, "tasks/_file_tile.html", {"entry": entry}, status=200)


@require_GET
@permissions.require_permission("tasks.use")
def download(request, file_id):
    entry = TaskFile.objects.select_related("task", "file").filter(pk=file_id).first()
    if entry is None or not access.visible(request.user, entry.task):
        raise Http404
    path = service.content(entry.task, entry, request.user)
    if path in MESSAGES:
        return HttpResponse(MESSAGES[path], status=404, content_type="text/plain; charset=utf-8")
    if path is None:
        raise Http404
    response = HttpResponse(b"", content_type=entry.file.content_type)
    response["X-Accel-Redirect"] = f"/protected/{path.parent.name}/{path.name}"
    response["Content-Disposition"] = f'attachment; filename="{entry.name}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response
