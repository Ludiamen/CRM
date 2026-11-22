"""Настройки задач и справочник категорий (срез 009, T-9208/T-9213; CONTRACT-009, 6.2).

`/settings/tasks/` — срок хранения 1–10 лет, уменьшение требует второго шага и показывает число задач к уборке;
`/settings/tasks/categories/` — справочник администратора под `settings.portal`.
"""
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.services import permissions
from apps.core.views.common import render_page
from apps.tasks.models import TaskCategory
from apps.tasks.services import categories, settings as task_settings
from apps.tasks.services.errors import TasksError


def _error(exc: TasksError) -> dict:
    return {"field": exc.field, "code": exc.code, "message": exc.message}


def _settings_page(request, *, error=None, confirm=None):
    row = task_settings.get()
    return render_page(request, "tasks/settings.html", {
        "row": row, "error": error, "confirm": confirm})


@require_http_methods(["GET", "POST"])
@permissions.require_permission("settings.portal")
def settings_page(request):
    if request.method == "GET":
        return _settings_page(request)
    raw = request.POST.get("retention_years", "")
    try:
        years = task_settings._years_from(raw)
    except TasksError as exc:
        return _settings_page(request, error=_error(exc))
    current = task_settings.get().retention_years
    count = task_settings.pending_count(years) if years < current else 0
    if count and request.POST.get("confirm") != "1":
        return _settings_page(request, confirm={"years": years, "count": count})
    try:
        task_settings.save(request.user, years)
    except TasksError as exc:
        return _settings_page(request, error=_error(exc))
    return redirect("/settings/tasks/")


def _categories_page(request, *, error=None, confirm=None):
    return render_page(request, "tasks/categories.html", {
        "categories": TaskCategory.objects.order_by("position", "pk"), "error": error, "confirm": confirm})


@require_http_methods(["GET", "POST"])
@permissions.require_permission("settings.portal")
def categories_page(request):
    if request.method == "GET":
        return _categories_page(request)
    try:
        categories.add(request.user, request.POST.get("title", ""))
    except TasksError as exc:
        return _categories_page(request, error=_error(exc))
    return redirect("/settings/tasks/categories/")


@require_POST
@permissions.require_permission("settings.portal")
def edit_category(request, category_id):
    category = TaskCategory.objects.filter(pk=category_id).first()
    if category is None:
        raise Http404
    try:
        categories.rename(request.user, category, request.POST.get("title", category.title),
                          request.POST.get("position"))
    except TasksError as exc:
        return _categories_page(request, error=_error(exc))
    return redirect("/settings/tasks/categories/")


@require_POST
@permissions.require_permission("settings.portal")
def delete_category(request, category_id):
    category = TaskCategory.objects.filter(pk=category_id).first()
    if category is None:
        raise Http404
    if request.POST.get("confirm") != "1":
        return _categories_page(request, confirm={"category": category}, error={
            "field": "confirm", "code": "category_delete_confirm",
            "message": "Удалить категорию? Задачи останутся без категории"})
    categories.delete(request.user, category)
    return redirect("/settings/tasks/categories/")