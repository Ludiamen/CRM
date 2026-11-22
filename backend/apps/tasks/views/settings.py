"""Настройки задач и справочник категорий (срез 009, каркас T-9009).

T-9009: страницы-заглушки под правом `settings.portal`; срок хранения и второй шаг подтверждения добавляет
T-9125/T-9213, справочник категорий — T-9208.
"""
from django.views.decorators.http import require_GET

from apps.core.services import permissions
from apps.core.views.common import render_page


@require_GET
@permissions.require_permission("settings.portal")
def settings_page(request):
    """GET `/settings/tasks/` — срок хранения задач (каркас)."""
    return render_page(request, "tasks/settings.html", {})


@require_GET
@permissions.require_permission("settings.portal")
def categories_page(request):
    """GET `/settings/tasks/categories/` — справочник категорий (каркас)."""
    return render_page(request, "tasks/categories.html", {})
