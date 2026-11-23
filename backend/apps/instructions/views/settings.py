"""Страницы настроек поручений и справочника видов (срез 010, T-10201/T-10213; CONTRACT-010, 6.2).

Право `settings.portal` проверяется декоратором раньше служб: без него 403 на GET и POST. Уменьшение срока
хранения — второй шаг с числом поручений к уборке (`retention_decrease`).
"""
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page
from apps.instructions.services import basis as basis_service
from apps.instructions.services import settings as settings_service
from apps.instructions.texts import InstructionsError

SETTINGS_URL = "/settings/instructions/"
BASIS_URL = "/settings/instructions/basis/"
PERMISSION = "settings.portal"


def _error(exc: InstructionsError) -> dict:
    return {"field": exc.field, "code": exc.code, "message": exc.message}


def _ladder_from_post(request) -> dict | None:
    raw = (request.POST.get("offsets") or "").replace(";", ",").strip()
    if not raw:
        return None
    try:
        offsets = [int(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise InstructionsError("ladder_invalid", "ladder") from None
    return {"offsets": offsets, "due": request.POST.get("due") == "1",
            "overdue": request.POST.get("overdue") == "1"}


@require_permission(PERMISSION)
@require_http_methods(["GET", "POST"])
def settings_page(request):
    """GET, POST `/settings/instructions/` — срок хранения и умолчание лестницы."""
    row = settings_service.get()
    if request.method == "GET":
        return _settings_page(request, row)
    raw = (request.POST.get("retention_years") or "").strip()
    try:
        years = int(raw)
    except ValueError:
        return _settings_page(request, row, error={"field": "retention_years", "code": "retention_range",
                                                   "message": "Срок хранения — от 1 до 10 лет"}, value=raw)
    if not 1 <= years <= 10:
        return _settings_page(request, row, error={"field": "retention_years", "code": "retention_range",
                                                   "message": "Срок хранения — от 1 до 10 лет"}, value=raw)
    if years < row.retention_years and request.POST.get("confirm") != "1":
        count = settings_service.purge_count(years)
        if count:
            return _settings_page(request, row, confirm={"years": years, "count": count})
    try:
        settings_service.save(request.user, retention_years=years,
                              default_ladder=_ladder_from_post(request))
    except InstructionsError as exc:
        return _settings_page(request, row, error=_error(exc), value=raw)
    return HttpResponseRedirect(SETTINGS_URL)


def _settings_page(request, row, *, error=None, value=None, confirm=None):
    kinds = basis_service.all()
    return render_page(request, "instructions/settings.html", {
        "row": row, "value": row.retention_years if value in (None, "") else value,
        "offsets": ", ".join(str(item) for item in (row.default_ladder or {}).get("offsets", [])),
        "due": (row.default_ladder or {}).get("due", True),
        "overdue": (row.default_ladder or {}).get("overdue", True),
        "error": error, "confirm": confirm, "kinds": kinds,
    })


@require_permission(PERMISSION)
@require_http_methods(["GET", "POST"])
def basis_page(request):
    """GET, POST `/settings/instructions/basis/` — справочник видов основания."""
    if request.method == "GET":
        return _basis_page(request)
    try:
        basis_service.add(request.user, request.POST.get("title"))
    except InstructionsError as exc:
        return _basis_page(request, error=_error(exc), title=request.POST.get("title") or "")
    return HttpResponseRedirect(BASIS_URL)


@require_permission(PERMISSION)
@require_POST
def edit_basis(request, kind_id):
    """POST `/settings/instructions/basis/<id>/` — переименование."""
    kind = basis_service.all().filter(pk=kind_id).first()
    if kind is None:
        from django.http import Http404

        raise Http404
    try:
        basis_service.rename(request.user, kind, request.POST.get("title"))
    except InstructionsError as exc:
        return _basis_page(request, error=_error(exc), title=request.POST.get("title") or "")
    return HttpResponseRedirect(BASIS_URL)


@require_permission(PERMISSION)
@require_POST
def delete_basis(request, kind_id):
    """POST `/settings/instructions/basis/<id>/delete/` — удаление или выключение вида."""
    kind = basis_service.all().filter(pk=kind_id).first()
    if kind is None:
        from django.http import Http404

        raise Http404
    if request.POST.get("confirm") != "1":
        return _basis_page(request, confirm={"kind": kind})
    basis_service.delete(request.user, kind)
    return HttpResponseRedirect(BASIS_URL)


def _basis_page(request, *, error=None, title="", confirm=None):
    return render_page(request, "instructions/basis.html", {
        "kinds": basis_service.all(), "error": error, "title": title, "confirm": confirm,
    })