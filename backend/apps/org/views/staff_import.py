"""Загрузка сотрудников из таблицы: файл, предпросмотр, подтверждение, образцы (FR-136…142; T-2236).

Пока заглушки (T-2230a): нужны оба права, с правами ответ — 404; тело заменяет T-2236.
"""
from django.http import Http404
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.services.permissions import require_permission


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def import_start(request):
    """`/structure/import/` — выбор файла."""
    raise Http404


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def import_preview(request, import_id: int):
    """`/structure/import/<id>/` — предпросмотр, подтверждение, итог."""
    raise Http404


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_GET
def sample_csv(request):
    """`/structure/import/sample.csv` — образец файла."""
    raise Http404


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_GET
def sample_xlsx(request):
    """`/structure/import/sample.xlsx` — образец файла."""
    raise Http404
