"""Маршруты переноса срока (срез 010, T-10206; CONTRACT-010, 6.2)."""
from django.http import Http404, HttpResponseRedirect
from django.views.decorators.http import require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page
from apps.instructions.models import InstructionTransfer
from apps.instructions.services import transfers as service
from apps.instructions.texts import InstructionsError
from apps.instructions.views.actions import _card_context, _card_or_404, _error


def _render_error(request, row, exc):
    return render_page(request, "instructions/card.html", _card_context(request, row, error=_error(exc)), status=200)


@require_permission("instructions.use")
@require_POST
def request(request, instruction_id):
    """POST `/instructions/<id>/transfers/` — запрос переноса."""
    row = _card_or_404(request.user, instruction_id)
    try:
        service.request(request.user, row, new_deadline=request.POST.get("new_deadline") or None,
                        reason=request.POST.get("reason") or "")
    except InstructionsError as exc:
        return _render_error(request, row, exc)
    return HttpResponseRedirect(f"/instructions/{row.pk}/")


def _transfer(viewer, transfer_id) -> InstructionTransfer:
    row = InstructionTransfer.objects.filter(pk=transfer_id).select_related("instruction").first()
    if row is None:
        raise Http404
    _card_or_404(viewer, row.instruction_id)
    return row


@require_permission("instructions.use")
@require_POST
def approve(request, transfer_id):
    """POST `/instructions/transfers/<id>/approve/`."""
    transfer = _transfer(request.user, transfer_id)
    try:
        service.decide(request.user, transfer, approve=True, comment=request.POST.get("comment") or "")
    except InstructionsError as exc:
        return _render_error(request, transfer.instruction, exc)
    return HttpResponseRedirect(f"/instructions/{transfer.instruction_id}/")


@require_permission("instructions.use")
@require_POST
def reject(request, transfer_id):
    """POST `/instructions/transfers/<id>/reject/`."""
    transfer = _transfer(request.user, transfer_id)
    try:
        service.decide(request.user, transfer, approve=False, comment=request.POST.get("comment") or "")
    except InstructionsError as exc:
        return _render_error(request, transfer.instruction, exc)
    return HttpResponseRedirect(f"/instructions/{transfer.instruction_id}/")
