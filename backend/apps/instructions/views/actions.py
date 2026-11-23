"""Страницы создания и карточки поручения (срез 010, T-10203; CONTRACT-010, 6.2, 6.3).

Форма `/instructions/new/` показывает только управляемых сотрудников и действующие виды основания. Карточка
отдаёт историю, отчётные даты, файлы и связанные задачи; редактор — автор, решения — контролёр (T-10205/T-10206).
"""
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseRedirect
from django.views.decorators.http import require_http_methods, require_GET, require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page
from apps.instructions.models import (Instruction, InstructionFile, InstructionReport,
                                      InstructionReportDate, InstructionReportPart, InstructionTask,
                                      InstructionTransfer)
from apps.instructions.services import access, basis as basis_service, dates, instructions as service
from apps.instructions.texts import InstructionsError

LIST_URL = "/instructions/"


def _people(actor):
    """Действующие сотрудники управляемых узлов (без самого актора и без уволенных)."""
    units = access.managed_units(actor)
    if not units:
        return get_user_model().objects.none()
    return (get_user_model().objects.filter(memberships__unit_id__in=units, state="active")
            .exclude(pk=actor.pk).distinct().order_by("full_name"))


def _payload(request) -> dict:
    raw_dates = request.POST.get("dates") or ""
    values = [part.strip() for part in raw_dates.replace(";", ",").split(",") if part.strip()]
    return {
        "title": request.POST.get("title") or "",
        "text": request.POST.get("text") or "",
        "basis_kind": request.POST.get("basis_kind") or None,
        "basis_number": request.POST.get("basis_number") or "",
        "basis_date": request.POST.get("basis_date") or None,
        "assignee": request.POST.get("assignee") or None,
        "members": [value for value in request.POST.getlist("members") if value],
        "deadline": request.POST.get("deadline") or None,
        "controller": request.POST.get("controller") or None,
        "periodicity": request.POST.get("periodicity") or "",
        "dates": values,
    }


def _error(exc: InstructionsError) -> dict:
    return {"field": exc.field, "code": exc.code, "message": exc.message}


def _form_context(request, *, error=None) -> dict:
    return {"kinds": basis_service.active(), "people": _people(request.user),
            "values": request.POST if request.method == "POST" else {}, "error": error}


@require_permission("instructions.use")
@require_http_methods(["GET", "POST"])
def new_page(request):
    """GET, POST `/instructions/new/` — форма создания."""
    if request.method == "POST":
        return create(request)
    return render_page(request, "instructions/new.html", _form_context(request))


@require_permission("instructions.use")
@require_http_methods(["POST"])
def create(request):
    """POST `/instructions/new/` — создание поручения."""
    data = _payload(request)
    try:
        row = service.create(request.user, **data)
    except InstructionsError as exc:
        return render_page(request, "instructions/new.html", _form_context(request, error=_error(exc)), status=200)
    return HttpResponseRedirect(f"/instructions/{row.pk}/")


def _card_or_404(viewer, instruction_id) -> Instruction:
    row = Instruction.objects.filter(pk=instruction_id).select_related(
        "basis_kind", "author", "controller", "assignee").first()
    if row is None or not access.visible(viewer, row):
        raise Http404
    return row


def _history(row) -> list[dict]:
    from apps.core.models import AuditEvent
    from apps.instructions.audit_labels import audit_labels

    labels = audit_labels()["actions"]
    return [{"at": event.at, "title": labels.get(event.action, event.action), "before": event.before,
             "after": event.after}
            for event in AuditEvent.objects.filter(object_id=str(row.pk)).order_by("at", "id")]


def _visible_tasks(viewer, row) -> list:
    from apps.tasks.services import access as task_access

    result = []
    for link in InstructionTask.objects.filter(instruction=row).select_related("task"):
        if task_access.visible(viewer, link.task):
            result.append(link.task)
    return result


def _card_context(request, row, *, error=None) -> dict:
    state = dates.state_of(row)
    return {
        "row": row, "state": state, "state_title": dates.STATE_TITLES[state],
        "report_dates": list(InstructionReportDate.objects.filter(instruction=row).order_by("due_date", "pk")),
        "reports": list(InstructionReport.objects.filter(instruction=row).select_related("date", "author")
                        .order_by("submitted_at", "pk")),
        "parts": list(InstructionReportPart.objects.filter(date__instruction=row).select_related("date", "author")
                      .order_by("date__due_date", "pk")),
        "transfers": list(InstructionTransfer.objects.filter(instruction=row).select_related("requested_by")
                           .order_by("created_at", "pk")),
        "history": _history(row),
        "files": list(InstructionFile.objects.filter(instruction=row).select_related("file")),
        "tasks": _visible_tasks(request.user, row),
        "can_edit": access.can_edit_fields(request.user, row),
        "can_decide": access.can_decide(request.user, row),
        "can_report": access.can_report(request.user, row),
        "can_add_part": access.can_add_part(request.user, row, None) if False else False,
        "can_close": access.can_close(request.user, row),
        "can_request_transfer": access.can_request_transfer(request.user, row),
        "can_decide_transfer": access.can_decide_transfer(request.user, row),
        "kinds": basis_service.active(), "people": _people(row.author),
        "values": request.POST if request.method == "POST" else {}, "error": error,
    }


@require_permission("instructions.use")
@require_http_methods(["GET", "POST"])
def detail(request, instruction_id):
    """GET, POST `/instructions/<id>/` — карточка и правка полей."""
    row = _card_or_404(request.user, instruction_id)
    if request.method == "GET":
        return render_page(request, "instructions/card.html", _card_context(request, row))
    data = _payload(request)
    data.pop("assignee", None)
    try:
        service.update(request.user, row, **data)
    except InstructionsError as exc:
        return render_page(request, "instructions/card.html", _card_context(request, row, error=_error(exc)),
                           status=200)
    return HttpResponseRedirect(f"/instructions/{row.pk}/")

@require_permission("instructions.use")
@require_POST
def close(request, instruction_id):
    """POST `/instructions/<id>/close/` — снятие с контроля в два шага."""
    from django.core.exceptions import PermissionDenied

    row = _card_or_404(request.user, instruction_id)
    if request.user.pk != row.controller_id:
        raise PermissionDenied
    if request.POST.get("confirm") != "1":
        context = _card_context(request, row)
        context["confirm_close"] = True
        return render_page(request, "instructions/card.html", context, status=200)
    try:
        service.close(request.user, row)
    except InstructionsError as exc:
        return render_page(request, "instructions/card.html", _card_context(request, row, error=_error(exc)),
                           status=200)
    return HttpResponseRedirect(f"/instructions/{row.pk}/")
