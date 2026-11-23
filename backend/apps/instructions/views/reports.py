"""Маршруты отчётов и решений (срез 010, T-10205; CONTRACT-010, 6.2)."""
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page
from apps.instructions.models import InstructionReport
from apps.instructions.services import reports as service
from apps.instructions.texts import InstructionsError
from apps.instructions.views.actions import _card_context, _card_or_404, _error


def _render_error(request, row, exc):
    return render_page(request, "instructions/card.html", _card_context(request, row, error=_error(exc)), status=200)


@require_permission("instructions.use")
@require_POST
def submit(request, instruction_id):
    """POST `/instructions/<id>/reports/` — сводный отчёт к дате или сроку."""
    row = _card_or_404(request.user, instruction_id)
    try:
        service.submit(request.user, row, date=request.POST.get("date") or None,
                       text=request.POST.get("text") or "", files=request.POST.getlist("files"))
    except InstructionsError as exc:
        return _render_error(request, row, exc)
    return HttpResponseRedirect(f"/instructions/{row.pk}/")


@require_permission("instructions.use")
@require_POST
def add_part(request, instruction_id):
    """POST `/instructions/<id>/parts/` — часть отчёта к дате."""
    row = _card_or_404(request.user, instruction_id)
    from apps.instructions.models import InstructionReportDate

    date_row = InstructionReportDate.objects.filter(pk=request.POST.get("date") or 0, instruction=row).first()
    try:
        service.add_part(request.user, row, date_row, text=request.POST.get("text") or "",
                         files=request.POST.getlist("files"))
    except InstructionsError as exc:
        return _render_error(request, row, exc)
    return HttpResponseRedirect(f"/instructions/{row.pk}/")


def _report_or_404(viewer, report_id) -> InstructionReport:
    report = InstructionReport.objects.filter(pk=report_id).select_related("instruction", "date").first()
    if report is None:
        from django.http import Http404

        raise Http404
    row = _card_or_404(viewer, report.instruction_id)
    return report


@require_permission("instructions.use")
@require_POST
def accept(request, report_id):
    """POST `/instructions/reports/<id>/accept/` — принять отчёт."""
    report = _report_or_404(request.user, report_id)
    try:
        service.decide(request.user, report, accept=True, comment=request.POST.get("comment") or "")
    except InstructionsError as exc:
        return _render_error(request, report.instruction, exc)
    return HttpResponseRedirect(f"/instructions/{report.instruction_id}/")


@require_permission("instructions.use")
@require_POST
def return_report(request, report_id):
    """POST `/instructions/reports/<id>/return/` — вернуть с причиной."""
    report = _report_or_404(request.user, report_id)
    try:
        service.decide(request.user, report, accept=False, comment=request.POST.get("comment") or "")
    except InstructionsError as exc:
        return _render_error(request, report.instruction, exc)
    return HttpResponseRedirect(f"/instructions/{report.instruction_id}/")