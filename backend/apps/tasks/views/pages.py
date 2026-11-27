"""Страницы раздела «Задачи» (срез 009, T-9203…T-9209; CONTRACT-009, 6.2, 6.3).

Список с пресетами и фильтрами, карточка, форма создания и четыре доски. Права — `tasks.use`; видимость задачи
проверяет `services.access` (чужая и удалённая — 404).
"""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.services import permissions
from apps.core.views.common import render_page
from apps.core.models import User
from apps.core.widgets import moscow_today
from apps.tasks.models import Task, TaskCategory
from apps.tasks.services import access, boards, list as task_list, plan
from apps.tasks.services import card
from apps.tasks.services import reminders, tasks as task_service

PRESETS = (("mine", "Мои"), ("authored", "Поставленные мной"), ("subordinate", "Задачи подчинённых"),
           ("work", "В работе"), ("overdue", "Просрочены"))
FILTERS = {"status": "", "deadline": "", "assignee": "", "category": ""}


def _filters(request) -> dict:
    result = dict(FILTERS)
    for key in result:
        value = request.GET.get(key, "").strip()
        if value:
            result[key] = value
    if request.GET.get("q", "").strip():
        result["q"] = request.GET["q"].strip()
    return result


def _task_or_404(viewer, task_id) -> Task:
    task = Task.objects.filter(pk=task_id).first()
    if task is None or not access.visible(viewer, task):
        raise Http404
    return task


@require_GET
@permissions.require_permission("tasks.use")
def list_page(request):
    data = task_list.rows(request.user, preset=request.GET.get("preset", "mine"), filters=_filters(request),
                          sort=request.GET.get("sort", ""), page=request.GET.get("page", 1),
                          per_page=request.GET.get("per_page", 20))
    card = None
    card_id = request.GET.get("card", "")
    if card_id.isdigit():
        card = Task.objects.filter(pk=int(card_id)).first()
        if card is not None and not access.visible(request.user, card):
            card = None
    return render_page(request, "tasks/page.html", {
        "presets": PRESETS, "preset": request.GET.get("preset", "mine"), "filters": _filters(request),
        "sort": request.GET.get("sort", ""), "data": data, "rows": data["rows"], "card": card,
        "categories": TaskCategory.objects.all(),
    })


@require_GET
@permissions.require_permission("tasks.use")
def list_fragment(request):
    data = task_list.rows(request.user, preset=request.GET.get("preset", "mine"), filters=_filters(request),
                          sort=request.GET.get("sort", ""), page=request.GET.get("page", 1),
                          per_page=request.GET.get("per_page", 20))
    return render_page(request, "tasks/_list.html", {"rows": data["rows"], "data": data})


@require_GET
@permissions.require_permission("tasks.use")
def card_page(request, task_id):
    task = _task_or_404(request.user, task_id)
    from apps.tasks.services.task_links import ticket_for_task
    return render_page(request, "tasks/card.html", {
        "task": task,
        "feed": task_service.feed(task),
        "comments": task.comments.select_related("author").order_by("created_at", "pk"),
        "reminders": reminders_of(task),
        "can_edit": access.can_edit_fields(request.user, task),
        "can_status": access.can_change_status(request.user, task),
        "can_delete": access.can_delete(request.user, task),
        "can_comment": access.can_comment(request.user, task),
        "columns": plan.columns_of(task.assignee),
        "categories": TaskCategory.objects.all(),
        "ticket": ticket_for_task(request.user, task),
        "card_parts": card.card_parts(request, task),
    })


def reminders_of(task):
    """Напоминания задачи по моменту (для карточки)."""
    return task.reminders.select_related("user").order_by("moment", "pk")


@require_http_methods(["GET", "POST"])
@permissions.require_permission("tasks.use")
def new_page(request):
    ticket_number = request.GET.get("ticket") or request.POST.get("ticket")
    ticket = None
    seed = None
    if ticket_number:
        try:
            ticket_number = int(ticket_number)
        except (TypeError, ValueError):
            raise Http404
        from apps.tasks.services import task_links
        seed = task_links.seed_for_ticket(request.user, ticket_number)
        if seed is None:
            raise PermissionDenied
        ticket = {"number": seed["number"], "subject": seed["title"]}
    if request.method == "POST":
        from apps.tasks.views import actions

        return actions.create(request) if ticket is None else actions.create(request, ticket_number=ticket_number)
    posted = seed or {}
    return render_page(request, "tasks/new.html", {
        "assignee": posted.get("assignee") or request.user,
        "people": User.objects.exclude(state="dismissed").order_by("full_name", "pk"),
        "categories": TaskCategory.objects.order_by("position", "pk"),
        "today": moscow_today().isoformat(),
        "posted": posted, "ticket": ticket,
    })


@require_GET
@permissions.require_permission("tasks.use")
def board_status(request):
    return render_page(request, "tasks/board.html", {"board": "status", "title": "Стадии",
                                                      "columns": boards.status_columns(request.user)})


@require_GET
@permissions.require_permission("tasks.use")
def board_deadline(request):
    return render_page(request, "tasks/board.html", {"board": "deadline", "title": "Сроки",
                                                      "columns": boards.deadline_columns(request.user)})


@require_GET
@permissions.require_permission("tasks.use")
def board_plan(request):
    owner = request.user
    owner_id = request.GET.get("user", "")
    if owner_id.isdigit():
        found = User.objects.filter(pk=int(owner_id)).first()
        if found is not None and found.state != "dismissed":
            owner = found
    return render_page(request, "tasks/board.html", {
        "board": "plan", "title": "Мой план", "columns": boards.plan_columns(request.user, owner),
        "plan_owner": owner, "plan_readonly": owner.pk != request.user.pk,
    })


@require_GET
@permissions.require_permission("tasks.use")
def board_category(request):
    return render_page(request, "tasks/board.html", {"board": "category", "title": "Категории",
                                                      "columns": boards.category_columns(request.user)})
