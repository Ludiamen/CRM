"""Страницы поручений (срез 010; каркас T-10007).

T-10007: реестр, фрагмент реестра и настройки — адрес и право работают, содержимое добавляет T-10207 для реестра
и T-10201/T-10213 для настроек. Карточку, действия, отчёты, переносы, файлы и дисциплину добавляют T-10203…T-10215.
"""
from django.views.decorators.http import require_GET

from apps.core.services import permissions
from apps.core.views.common import render_page


@require_GET
@permissions.require_permission("instructions.use")
def registry(request):
    """GET `/instructions/` — реестр (каркас: пресет и пустое состояние)."""
    return render_page(request, "instructions/page.html", {"preset": request.GET.get("preset", "mine")})


@require_GET
@permissions.require_permission("instructions.use")
def list_fragment(request):
    """GET `/instructions/list/` — фрагмент реестра (каркас: пустой список)."""
    return render_page(request, "instructions/_list.html", {"preset": request.GET.get("preset", "mine")})
