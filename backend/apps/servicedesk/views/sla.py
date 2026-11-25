"""Представления уровней обслуживания (CONTRACT-011, §§ 3.1, 4, 5)."""
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import is_fragment, render_page

from ..models import Category, Priority, SlaLevel
from ..services import sla
from ..services.errors import ServiceDeskError


def _values(level=None):
    if level is None:
        return {
            "title": "", "priority": "0", "reaction_minutes": "60", "solution_minutes": "240",
            "workdays": ["0", "1", "2", "3", "4"], "day_start": "09:00", "day_end": "18:00",
            "all_day": False, "default_assignee": "", "categories": [], "priorities": [],
        }
    bindings = level.bindings.all()
    return {
        "title": level.title, "priority": str(level.priority),
        "reaction_minutes": str(level.reaction_minutes), "solution_minutes": str(level.solution_minutes),
        "workdays": [str(day) for day in level.workdays],
        "day_start": level.day_start.strftime("%H:%M"), "day_end": level.day_end.strftime("%H:%M"),
        "all_day": level.all_day, "default_assignee": str(level.default_assignee_id or ""),
        "categories": [str(row.category_id) for row in bindings if row.category_id],
        "priorities": [str(row.priority_id) for row in bindings if row.priority_id],
    }


def _form_context(level, values, error=None):
    return {
        "level": level, "values": values, "error": error,
        # Свободные привязки: категория и критичность принадлежат только одному уровню (уникальность в модели).
        "categories": Category.objects.exclude(sla_bindings__isnull=False).order_by("name"),
        "priorities": Priority.objects.exclude(sla_bindings__isnull=False).order_by("name"),
        "assignees": get_user_model().objects.filter(state="active").order_by("full_name", "id"),
        "workday_choices": ((0, "Пн"), (1, "Вт"), (2, "Ср"), (3, "Чт"), (4, "Пт"), (5, "Сб"), (6, "Вс")),
    }


def _rows():
    levels = SlaLevel.objects.prefetch_related("bindings__category", "bindings__priority").order_by("archived", "priority", "id")
    return [{"level": level, "bindings": list(level.bindings.all())} for level in levels]


def _page(request, *, level=None, values=None, error=None, status=200):
    if values is None:
        values = _values(level if level is not False else None)
    context = {"rows": _rows(), "form": _form_context(level, values, error) if level is not False else None}
    return render_page(request, "servicedesk/sla/page.html", context, status=status)


def _form_response(request, level, values, error=None, status=200):
    context = _form_context(level, values, error)
    if is_fragment(request):
        response = render(request, "servicedesk/sla/_form.html", {"form": context}, status=status)
        response["Vary"] = "HX-Request"
        return response
    return _page(request, level=level, values=values, error=error, status=status)


def _post_values(post):
    raw_assignee = (post.get("default_assignee") or "").strip()
    assignee = get_user_model().objects.filter(pk=raw_assignee).first() if raw_assignee else None
    return {
        "title": post.get("title", ""), "priority": post.get("priority", "0"),
        "reaction_minutes": post.get("reaction_minutes", ""), "solution_minutes": post.get("solution_minutes", ""),
        "workdays": post.getlist("workdays"), "day_start": post.get("day_start", ""),
        "day_end": post.get("day_end", ""), "all_day": bool(post.get("all_day")),
        "default_assignee": assignee, "categories": post.getlist("category"),
        "priorities": post.getlist("priority_binding"),
    }


def _save(request, level=None):
    values = _post_values(request.POST)
    try:
        fields = {key: values[key] for key in
                  ("title", "priority", "reaction_minutes", "solution_minutes", "workdays",
                   "day_start", "day_end", "all_day", "default_assignee")}
        if level is None:
            level = sla.create_level(actor=request.user, ip=getattr(request, "client_ip", None), **fields)
        else:
            level = sla.update_level(level, actor=request.user, ip=getattr(request, "client_ip", None), **fields)
        # Неизвестные значения в списках (пустая строка из формы) игнорируются, а не роняют страницу.
        category_ids = [value for value in values["categories"] if str(value).isdigit()]
        priority_ids = [value for value in values["priorities"] if str(value).isdigit()]
        categories = Category.objects.filter(pk__in=category_ids)
        priorities = Priority.objects.filter(pk__in=priority_ids)
        sla.set_bindings(level, categories=categories, priorities=priorities,
                         actor=request.user, ip=getattr(request, "client_ip", None))
    except ServiceDeskError as error:
        field = {
            "sla_title_range": "title", "sla_minutes_range": "reaction_minutes",
            "sla_reaction_gt_solution": "reaction_minutes", "sla_days_empty": "workdays",
            "sla_interval_empty": "day_start", "sla_assignee_dismissed": "default_assignee",
            "sla_priority_range": "priority", "sla_binding_taken": "category",
        }.get(error.code)
        return _form_response(request, level, values, {"code": error.code, "message": error.message, "field": field}, 400)
    if is_fragment(request):
        response = render(request, "servicedesk/sla/_list.html", {"rows": _rows()}, status=200)
        response["Vary"] = "HX-Request"
        return response
    return HttpResponseRedirect("/servicedesk/sla/")


@require_permission("servicedesk.sla")
@require_http_methods(["GET"])
def sla_list(request):
    return _page(request, level=False)


@require_permission("servicedesk.sla")
@require_http_methods(["GET", "POST"])
def sla_new(request):
    if request.method == "POST":
        return _save(request)
    return _form_response(request, None, _values())


@require_permission("servicedesk.sla")
@require_http_methods(["GET", "POST"])
def sla_edit(request, pk: int):
    level = get_object_or_404(SlaLevel, pk=pk)
    if request.method == "POST":
        return _save(request, level)
    return _form_response(request, level, _values(level))


@require_permission("servicedesk.sla")
@require_POST
def sla_archive(request, pk: int):
    level = get_object_or_404(SlaLevel, pk=pk)
    level = sla.archive_level(level, actor=request.user, ip=getattr(request, "client_ip", None))
    if is_fragment(request):
        row = next(row for row in _rows() if row["level"].pk == level.pk)
        response = render(request, "servicedesk/sla/_list.html", {"rows": [row]}, status=200)
        response["Vary"] = "HX-Request"
        return response
    return HttpResponseRedirect("/servicedesk/sla/")
