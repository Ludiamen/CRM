"""Действия задач: создание, правка, статус, перенос, удаление (срез 009, T-9203/T-9209; CONTRACT-009, 6.2).

Обычный POST отвечает 302 на карточку или доску; HTMX — фрагментом. Отказ службы — 200 с `[data-error]` у поля.
"""
import datetime

from django.http import Http404, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from apps.core.models import User
from apps.core.services import permissions
from apps.core.views.common import is_fragment, render_page
from apps.core.widgets import moscow_today
from apps.tasks.models import Task, TaskCategory
from apps.tasks.services import access, boards, plan
from apps.tasks.services import tasks as service
from apps.tasks.services.errors import TasksError

BOARD_TITLES = {"status": "Стадии", "deadline": "Сроки", "plan": "Мой план", "category": "Категории"}
BOARD_URLS = {"status": "/tasks/board/status/", "deadline": "/tasks/board/deadline/",
              "plan": "/tasks/board/plan/", "category": "/tasks/board/category/"}


def _error(exc: TasksError) -> dict:
    return {"field": exc.field, "code": exc.code, "message": exc.message}


def _task_or_404(viewer, task_id) -> Task:
    task = Task.objects.filter(pk=task_id).first()
    if task is None or not access.visible(viewer, task):
        raise Http404
    return task


def _user(value, default=None):
    if value in (None, ""):
        return default
    try:
        return User.objects.get(pk=int(value))
    except (TypeError, ValueError, User.DoesNotExist):
        return default


def _category(value):
    if value in (None, "", "none"):
        return None
    try:
        return TaskCategory.objects.get(pk=int(value))
    except (TypeError, ValueError, TaskCategory.DoesNotExist):
        return None


def _deadline(value):
    if value in (None, ""):
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise TasksError("deadline_past", "deadline")


def _people(request):
    return [user for user in (_user(value) for value in request.POST.getlist("members")) if user is not None]


def _form(request, error=None, task=None, ticket=None):
    from apps.core.models import User as People
    from apps.tasks.models import TaskCategory as Categories

    context = {
        "task": task,
        "assignee": _user(request.POST.get("assignee"), request.user),
        "people": People.objects.exclude(state="dismissed").order_by("full_name", "pk"),
        "categories": Categories.objects.order_by("position", "pk"),
        "today": moscow_today().isoformat(),
        "posted": request.POST,
        "error": error,
        "ticket": ticket,
    }
    return render_page(request, "tasks/new.html" if task is None else "tasks/card.html", context, status=200)


@require_http_methods(["GET", "POST"])
@permissions.require_permission("tasks.use")
def tasks_root(request):
    """`/tasks/`: GET — список, POST — создание."""
    from apps.tasks.views import pages

    return create(request) if request.method == "POST" else pages.list_page(request)


@require_POST
@permissions.require_permission("tasks.use")
def create(request, ticket_number=None):
    try:
        if ticket_number is not None:
            from apps.tasks.services.task_links import create_from_ticket
            task = create_from_ticket(
                request.user, ticket_number, title=request.POST.get("title", ""),
                description=request.POST.get("description", ""),
                deadline=_deadline(request.POST.get("deadline")),
                assignee=_user(request.POST.get("assignee"), request.user),
                members=_people(request), category=_category(request.POST.get("category")))
        else:
            task = service.create(
            request.user, title=request.POST.get("title", ""), description=request.POST.get("description", ""),
            deadline=_deadline(request.POST.get("deadline")),
            assignee=_user(request.POST.get("assignee"), request.user),
            members=_people(request), category=_category(request.POST.get("category")))
    except TasksError as exc:
        return _form(request, _error(exc))
    return redirect(f"/tasks/{task.pk}/")


@require_http_methods(["GET", "POST"])
@permissions.require_permission("tasks.use")
def task_detail(request, task_id):
    """`/tasks/<id>/`: GET — карточка, POST — правка полей."""
    from apps.tasks.views import pages

    return update(request, task_id) if request.method == "POST" else pages.card_page(request, task_id)


@require_POST
@permissions.require_permission("tasks.use")
def update(request, task_id):
    task = _task_or_404(request.user, task_id)
    changes = {}
    for key in ("title", "description"):
        if key in request.POST:
            changes[key] = request.POST.get(key, "")
    if "deadline" in request.POST:
        changes["deadline"] = _deadline(request.POST.get("deadline"))
    if "assignee" in request.POST:
        changes["assignee"] = _user(request.POST.get("assignee"), task.assignee)
    if "members" in request.POST:
        changes["members"] = _people(request)
    if "category" in request.POST:
        changes["category"] = _category(request.POST.get("category"))
    try:
        task = service.update(request.user, task, **changes)
    except TasksError as exc:
        return _card(request, task, _error(exc))
    if is_fragment(request):
        return _card(request, task)
    return redirect(f"/tasks/{task.pk}/")


@require_POST
@permissions.require_permission("tasks.use")
def change_status(request, task_id):
    task = _task_or_404(request.user, task_id)
    try:
        service.change_status(request.user, task, request.POST.get("status", ""))
    except TasksError as exc:
        return _card(request, task, _error(exc))
    if is_fragment(request):
        return _card(request, task)
    return redirect(f"/tasks/{task.pk}/")


def _card(request, task, error=None):
    return render_page(request, "tasks/_card.html", {
        "task": task, "feed": service.feed(task), "comments": task.comments.select_related("author"),
        "reminders": task.reminders.select_related("user").order_by("moment", "pk"),
        "can_edit": access.can_edit_fields(request.user, task),
        "can_status": access.can_change_status(request.user, task),
        "can_delete": access.can_delete(request.user, task),
        "can_comment": access.can_comment(request.user, task),
        "columns": plan.columns_of(task.assignee), "categories": TaskCategory.objects.order_by("position", "pk"),
        "error": error,
    }, status=200)


@require_POST
@permissions.require_permission("tasks.use")
def move(request, task_id):
    task = _task_or_404(request.user, task_id)
    board = request.POST.get("board", "")
    value = request.POST.get("value", "")
    try:
        if board not in BOARD_TITLES:
            raise TasksError("board_unknown", "board")
        if not access.can_move(request.user, task, board):
            raise TasksError("plan_forbidden" if board == "plan" else "move_forbidden", "board")
        if board == "status":
            if value not in Task.Status.values:
                raise TasksError("value_invalid", "board")
            service.change_status(request.user, task, value)
        elif board == "deadline":
            today = moscow_today()
            if value == "overdue":
                raise TasksError("overdue_move", "board")
            if value == "today":
                service.update(request.user, task, deadline=today)
            elif value == "week":
                days = (4 - today.weekday()) % 7
                service.update(request.user, task, deadline=today + datetime.timedelta(days=days or 7))
            elif value == "none":
                service.update(request.user, task, deadline=None)
            else:
                raise TasksError("value_invalid", "board")
        elif board == "category":
            service.update(request.user, task, category=_category(value))
        else:  # plan
            column = plan.columns_of(task.assignee or request.user)
            target = None
            for item in column:
                if str(item.pk) == str(value):
                    target = item
            if target is None or task.assignee_id != request.user.pk:
                raise TasksError("plan_forbidden", "board")
            plan.move_task(request.user, task, target)
    except TasksError as exc:
        safe = board if board in BOARD_TITLES else "status"
        context = {**_board_context(request, safe), "error": _error(exc)}
        if is_fragment(request):
            return render_page(request, "tasks/_board.html", context, status=200)
        return render_page(request, "tasks/board.html", context, status=200)
    if is_fragment(request):
        return render_page(request, "tasks/_board.html", _board_context(request, board))
    return HttpResponseRedirect(BOARD_URLS[board])


def _board_context(request, board) -> dict:
    if board == "status":
        columns = boards.status_columns(request.user)
    elif board == "deadline":
        columns = boards.deadline_columns(request.user)
    elif board == "plan":
        columns = boards.plan_columns(request.user)
    else:
        columns = boards.category_columns(request.user)
    return {"board": board, "title": BOARD_TITLES[board], "columns": columns, "move": True}


@require_POST
@permissions.require_permission("tasks.use")
def delete(request, task_id):
    task = _task_or_404(request.user, task_id)
    if not access.can_delete(request.user, task):
        raise Http404
    if request.POST.get("confirm") != "1":
        return _card(request, task, {"field": "confirm", "code": "delete_confirm",
                                     "message": "Удалить задачу без возможности вернуть?"})
    try:
        service.soft_delete(request.user, task)
    except TasksError as exc:
        return _card(request, task, _error(exc))
    return redirect("/tasks/")
