"""Страницы поручений (срез 010; каркас T-10007).

T-10007: реестр, фрагмент реестра и настройки — адрес и право работают, содержимое добавляет T-10207 для реестра
и T-10201/T-10213 для настроек. Карточку, действия, отчёты, переносы, файлы и дисциплину добавляют T-10203…T-10215.
"""
from django.views.decorators.http import require_GET

from apps.core.services import permissions
from apps.core.views.common import render_page
from apps.instructions.services import basis as basis_service
from apps.instructions.services import registry as registry_service


KEYS = ("basis", "assignee", "deadline", "state", "q", "sort")


def _context(request) -> dict:
    filters = {key: request.GET.get(key) for key in KEYS if request.GET.get(key)}
    preset = request.GET.get("preset", "mine")
    data = registry_service.rows(request.user, preset=preset, filters=filters,
                                 sort=request.GET.get("sort", ""), page=request.GET.get("page", 1),
                                 per_page=request.GET.get("per_page", 20))
    return {**data, "preset": preset, "filters": filters,
            "basis_kinds": basis_service.active()}


@require_GET
@permissions.require_permission("instructions.use")
def registry(request):
    """GET `/instructions/` — реестр поручений."""
    return render_page(request, "instructions/page.html", _context(request))


@require_GET
@permissions.require_permission("instructions.use")
def list_fragment(request):
    """GET `/instructions/list/` — фрагмент реестра."""
    return render_page(request, "instructions/_list.html", _context(request))


@require_GET
@permissions.require_permission("instructions.use")
def discipline(request):
    """GET `/instructions/discipline/` — отчёт по дисциплине."""
    from django.core.exceptions import PermissionDenied

    from apps.instructions.models import Instruction
    from apps.instructions.services import access, discipline as discipline_service, excel as excel_service
    from apps.org.services import structure

    if not access.can_view_discipline(request.user):
        raise PermissionDenied
    today = __import__("apps.core.widgets", fromlist=["moscow_today"]).moscow_today()
    first = today.replace(day=1)
    date_from = request.GET.get("from") or first.isoformat()
    date_to = request.GET.get("to") or today.isoformat()
    unit = structure.Unit.objects.filter(pk=request.GET.get("unit") or 0).first()
    data = discipline_service.rows(request.user, date_from=date_from, date_to=date_to, unit=unit)
    return render_page(request, "instructions/discipline.html", {
        **data, "date_from": date_from, "date_to": date_to,
        "unit": unit, "export_url": f"/instructions/discipline.xlsx?from={date_from}&to={date_to}"
        + (f"&unit={unit.pk}" if unit else "")})


@require_GET
@permissions.require_permission("instructions.use")
def discipline_excel(request):
    """GET `/instructions/discipline.xlsx` — книга с теми же числами."""
    from django.core.exceptions import PermissionDenied
    from django.http import HttpResponse

    from apps.instructions.services import access, discipline as discipline_service, excel as excel_service
    from apps.org.services import structure

    if not access.can_view_discipline(request.user):
        raise PermissionDenied
    today = __import__("apps.core.widgets", fromlist=["moscow_today"]).moscow_today()
    first = today.replace(day=1)
    date_from = request.GET.get("from") or first.isoformat()
    date_to = request.GET.get("to") or today.isoformat()
    unit = structure.Unit.objects.filter(pk=request.GET.get("unit") or 0).first()
    data = discipline_service.rows(request.user, date_from=date_from, date_to=date_to, unit=unit)
    payload = excel_service.build(data)
    return HttpResponse(payload,
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
