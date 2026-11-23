"""Загрузка и скачивание файлов поручения (срез 010, T-10211; CONTRACT-010, 6.2)."""
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET, require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page
from apps.instructions.models import Instruction, InstructionFile, InstructionReport, InstructionReportPart
from apps.instructions.services import files as service
from apps.instructions.texts import InstructionsError

MESSAGES = {"pending": "Файл ещё проверяется", "quarantine": "Файл в карантине"}


@require_permission("instructions.use")
@require_POST
def upload(request):
    """POST `/instructions/files/` — «таблетка» загруженного файла."""
    from django.contrib.auth.decorators import login_required

    row = Instruction.objects.filter(pk=request.POST.get("instruction") or 0).first()
    from apps.core.views.common import render_page as _render

    if row is None:
        raise Http404
    from apps.instructions.services import access

    if not access.visible(request.user, row):
        raise Http404
    report = InstructionReport.objects.filter(pk=request.POST.get("report") or 0, instruction=row).first()
    part = InstructionReportPart.objects.filter(pk=request.POST.get("part") or 0, date__instruction=row).first()
    upload_file = request.FILES.get("file")
    try:
        entry = service.store(request.user, row, upload_file, kind=request.POST.get("kind") or "report",
                              report=report, part=part)
    except InstructionsError as exc:
        return render_page(request, "instructions/_file_error.html",
                           {"error": {"field": exc.field, "code": exc.code, "message": exc.message}}, status=200)
    return render_page(request, "instructions/_file_tile.html",
                       {"entry": entry, "file_id": entry.pk}, status=200)


@require_GET
@require_permission("instructions.use")
def download(request, file_id):
    """GET `/instructions/files/<uuid>/` — оригинал через X-Accel."""
    from apps.instructions.services import access

    entry = InstructionFile.objects.filter(pk=file_id).select_related("instruction", "file").first()
    if entry is None or not access.visible(request.user, entry.instruction):
        raise Http404
    path = service.content(entry.instruction, entry, request.user)
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
