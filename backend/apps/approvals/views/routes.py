"""Страница маршрута, запуск, решение и отмена (PLAN-014, T-14024/T-14014)."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core.views.common import flash, render_page

from ..models import ApprovalAssignment, ApprovalRoute
from ..services import access, queue, routes
from ..services.errors import ApprovalError


def _route_or_404(user, pk):
    route = ApprovalRoute.objects.select_related("template", "initiator").filter(pk=pk).first()
    if route is None:
        raise Http404
    if not access.can_see_route(user, route):
        raise PermissionDenied
    return route


@login_required
def route_page(request, pk: int):
    route = _route_or_404(request.user, pk)
    stages = route.stages.prefetch_related("assignments__user").order_by("order")
    rows = []
    for stage in stages:
        assignments = list(stage.assignments.all())
        pending = [item for item in assignments if item.status == "pending"] if stage.status == "running" else []
        if stage.mode == "sequential" and pending:
            pending = sorted(pending, key=lambda item: (item.order, item.pk))[:1]
        rows.append({"stage": stage, "assignments": assignments,
                     "active_ids": {item.pk for item in pending}})
    return render_page(request, "approvals/routes/page.html", {
        "route": route, "stages": rows, "brief": access.brief(route),
        "can_cancel": access.can_cancel(request.user, route),
        "nav_active": "approvals",
    })


@login_required
@require_POST
def start_view(request):
    subject_type = request.POST.get("subject_type", "")
    try:
        subject_id = int(request.POST.get("subject_id") or 0)
        template_id = int(request.POST.get("template") or 0)
    except ValueError:
        raise Http404
    try:
        route = routes.start(request.user, subject_type=subject_type, subject_id=subject_id,
                             template_id=template_id)
    except ApprovalError as error:
        flash(request, error.message, error=True)
        return redirect(request.POST.get("next") or "/approvals/my/")
    flash(request, "Маршрут запущен")
    return HttpResponseRedirect(f"/approvals/routes/{route.pk}/")


@login_required
@require_POST
def cancel_view(request, pk: int):
    route = _route_or_404(request.user, pk)
    try:
        routes.cancel(request.user, route.pk)
    except ApprovalError as error:
        flash(request, error.message, error=True)
    else:
        flash(request, "Маршрут отменён")
    return HttpResponseRedirect(f"/approvals/routes/{route.pk}/")


@login_required
@require_POST
def decide_view(request, pk: int):
    assignment = ApprovalAssignment.objects.filter(pk=pk).select_related("stage_run__route").first()
    if assignment is None:
        raise Http404
    route = assignment.stage_run.route
    if not access.can_see_route(request.user, route):
        raise PermissionDenied
    try:
        routes.decide(request.user, pk, request.POST.get("decision", ""), request.POST.get("comment", ""))
    except ApprovalError as error:
        flash(request, error.message, error=True)
    else:
        flash(request, "Решение принято")
    return HttpResponseRedirect(f"/approvals/routes/{route.pk}/")
