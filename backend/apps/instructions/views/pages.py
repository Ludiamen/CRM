"""Страницы поручений (срез 010; каркас T-10007)."""
from django.views.decorators.http import require_GET

from apps.core.services import permissions
from apps.core.views.common import render_page


@require_GET
@permissions.require_permission("instructions.use")
def registry(request):
    """GET `/instructions/` — реестр (каркас)."""
    return render_page(request, "instructions/page.html", {})


@require_GET
@permissions.require_permission("settings.portal")
def settings_page(request):
    """GET `/settings/instructions/` — настройки (каркас)."""
    return render_page(request, "instructions/settings.html", {})
