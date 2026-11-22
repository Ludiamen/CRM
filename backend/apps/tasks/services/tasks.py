"""Создание, правка, статусы и удаление задач (срез 009, T-9203; FR-674…679, FR-694, FR-695).

Все проверки — службы: текст, срок-дата, состав, права (`access`). Изменения пишутся в журнал «было/стало»
(`core.AuditEvent`), `updated_at` обновляется; «Готово» ставит `completed_at` и снимает напоминания, возврат —
снимает `completed_at`. Удаление мягкое: минимальный снимок без названия, описания и комментариев.
"""
import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.core.widgets import moscow_today
from apps.tasks.models import Task, TaskComment, TaskMember
from apps.tasks.services import access
from apps.tasks.services.errors import TasksError

TITLE_MAX, DESCRIPTION_MAX = 300, 10_000
EDITABLE = ("title", "description", "deadline", "assignee", "members", "category", "plan_column")


def _clean_title(value) -> str:
    title = (value or "").strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise TasksError("title_range", "title")
    return title


def _clean_description(value) -> str:
    text = value or ""
    if len(text) > DESCRIPTION_MAX:
        raise TasksError("description_long", "description")
    return text


def _clean_deadline(value, *, allow_past: bool = False) -> datetime.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = datetime.date.fromisoformat(value)
        except ValueError:
            raise TasksError("deadline_past", "deadline") from None
    if not isinstance(value, datetime.date):
        raise TasksError("deadline_past", "deadline")
    if not allow_past and value < moscow_today():
        raise TasksError("deadline_past", "deadline")
    return value


def _active(user, code: str, field: str):
    if user is None or getattr(user, "state", None) == "dismissed":
        raise TasksError(code, field)
    return user


def _members(task, users, *, assignee, observers=()) -> list[TaskMember]:
    """Проверить состав: действующие, без повторов и без исполнителя."""
    seen: set[int] = set()
    result = []
    for user in list(users or ()) + list(observers or ()):
        _active(user, "member_dismissed", "members")
        if user.pk == assignee.pk:
            raise TasksError("member_is_assignee", "members")
        if user.pk in seen:
            raise TasksError("member_duplicate", "members")
        seen.add(user.pk)
        role = TaskMember.Role.OBSERVER if user in observers else TaskMember.Role.COEXECUTOR
        result.append(TaskMember(task=task, user=user, role=role))
    return result


def _allowed_assignee(actor, assignee) -> None:
    if not access.can_set_task(actor, assignee):
        raise TasksError("assignee_forbidden", "assignee")


@transaction.atomic
def create(actor, *, title, description="", deadline=None, assignee, members=(), category=None,
           plan_column=None) -> Task:
    """Создать задачу; проверки текста, срока, исполнителя, состава и прав."""
    _allowed_assignee(actor, assignee)
    _active(assignee, "assignee_dismissed", "assignee")
    now = timezone.now()
    task = Task.objects.create(
        title=_clean_title(title), description=_clean_description(description),
        deadline=_clean_deadline(deadline), author=actor, assignee=assignee,
        status=Task.Status.NEW, category=category, plan_column=plan_column, created_at=now, updated_at=now)
    TaskMember.objects.bulk_create(_members(task, members, assignee=assignee))
    audit.record("tasks.created", actor=actor, object_type="tasks.task", object_id=task.pk,
                 after={"title": task.title, "assignee": assignee.full_name, "deadline": _iso(task.deadline)})
    return task


def _iso(day) -> str:
    return day.isoformat() if day else ""


@transaction.atomic
def update(actor, task, **fields) -> Task:
    """Изменить поля задачи; неизвестные ключи игнорируются, журнал — по фактическим изменениям."""
    if not access.can_edit_fields(actor, task):
        raise TasksError("edit_forbidden", "title")
    changes = {key: value for key, value in fields.items() if key in EDITABLE}
    before, after = {}, {}
    if "title" in changes:
        title = _clean_title(changes["title"])
        if title != task.title:
            before["title"], after["title"] = task.title, title
            task.title = title
    if "description" in changes:
        description = _clean_description(changes["description"])
        if description != task.description:
            before["description"], after["description"] = task.description, description
            task.description = description
    if "deadline" in changes:
        deadline = _clean_deadline(changes["deadline"])
        if deadline != task.deadline:
            before["deadline"], after["deadline"] = _iso(task.deadline), _iso(deadline)
            task.deadline = deadline
    if "assignee" in changes:
        assignee = changes["assignee"]
        _active(assignee, "assignee_dismissed", "assignee")
        if assignee.pk != task.assignee_id:
            _allowed_assignee(actor, assignee)
            before["assignee"], after["assignee"] = task.assignee.full_name, assignee.full_name
            task.assignee = assignee
    if "category" in changes:
        category = changes["category"]
        if getattr(category, "pk", None) != task.category_id:
            before["category"] = task.category.title if task.category_id else ""
            after["category"] = category.title if category else ""
            task.category = category
    if "plan_column" in changes:
        column = changes["plan_column"]
        if getattr(column, "pk", None) != task.plan_column_id:
            before["plan_column"] = task.plan_column.title if task.plan_column_id else ""
            after["plan_column"] = column.title if column else ""
            task.plan_column = column
    if "members" in changes:
        members = list(changes["members"] or ())
        wanted = {user.pk for user in members}
        current = {row.user_id: row for row in task.members.filter(role=TaskMember.Role.COEXECUTOR)}
        if wanted != set(current):
            _active_members = _members(task, members, assignee=task.assignee)
            before["members"] = sorted(row.user.full_name for row in current.values())
            after["members"] = sorted(row.user.full_name for row in _active_members)
            task.members.filter(role=TaskMember.Role.COEXECUTOR).delete()
            TaskMember.objects.bulk_create(_active_members)
    if after:
        task.updated_at = timezone.now()
        task.save()
        audit.record("tasks.changed", actor=actor, object_type="tasks.task", object_id=task.pk,
                     before=before, after=after)
    return task


@transaction.atomic
def change_status(actor, task, status) -> Task:
    """Сменить статус; «Готово» ставит `completed_at` и снимает напоминания."""
    if status not in Task.Status.values:
        raise TasksError("status_invalid", "status")
    if not access.can_change_status(actor, task):
        raise TasksError("status_forbidden", "status")
    if status == task.status:
        return task
    before = task.status
    task.status = status
    task.completed_at = timezone.now() if status == Task.Status.DONE else None
    task.updated_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    audit.record("tasks.changed", actor=actor, object_type="tasks.task", object_id=task.pk,
                 before={"status": before}, after={"status": status})
    if status == Task.Status.DONE:
        from apps.tasks.services import reminders

        reminders.cancel_all(task, reason="done")
    return task


@transaction.atomic
def soft_delete(actor, task) -> Task:
    """Мягко удалить задачу: `deleted_at`, снятие напоминаний и минимальный снимок в журнале."""
    if not access.can_delete(actor, task):
        raise TasksError("delete_forbidden", "confirm")
    now = timezone.now()
    task.deleted_at = now
    task.updated_at = now
    task.save(update_fields=["deleted_at", "updated_at"])
    from apps.tasks.services import reminders

    reminders.cancel_all(task, reason="deleted")
    audit.record("tasks.deleted", actor=actor, object_type="tasks.task", object_id=task.pk,
                 after={"number": task.pk, "author": task.author.full_name,
                        "assignee": task.assignee.full_name, "status": task.status})
    return task


def feed(task) -> list[dict]:
    """Лента карточки: журнал по объекту и комментарии, от старых к новым (FR-693)."""
    events = list(audit.AuditEvent.objects.filter(object_type="tasks.task", object_id=str(task.pk)).order_by("at", "id"))
    comments = list(TaskComment.objects.filter(task=task).select_related("author").order_by("created_at", "pk"))
    return [{"kind": "event", "event": event} for event in events] + [
        {"kind": "comment", "comment": comment} for comment in comments]