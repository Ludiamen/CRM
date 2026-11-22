"""Комментарии задачи (срез 009, T-9210; FR-693, FR-694; CONTRACT-009, 6.2).

Пишут все, кто видит задачу; автор правит и удаляет свой (мягко, `deleted_at` — серая запись); правка и удаление
пишутся в журнал без текста (`tasks.comment_changed`).
"""
from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.tasks.services import access
from apps.tasks.services.errors import TasksError

TEXT_MAX = 10_000


@transaction.atomic
def add(actor, task, text, files=()) -> "TaskComment":
    """Добавить комментарий с файлами (номера непривязанных `TaskFile`)."""
    from apps.tasks.models import TaskComment, TaskFile

    if not access.can_comment(actor, task):
        raise TasksError("comment_forbidden", "text")
    body = (text or "").strip()
    if not body:
        raise TasksError("comment_empty", "text")
    if len(body) > TEXT_MAX:
        raise TasksError("comment_too_long", "text")
    selected = list(files or ())
    if len(selected) > 10:
        raise TasksError("files_limit", "file")
    comment = TaskComment.objects.create(task=task, author=actor, text=body)
    from apps.tasks.services import notify_rules
    from apps.tasks import tasks as jobs

    jobs.notify(task, "tasks.comment", [user for user in notify_rules.targets(task, "comment")
                                        if user.pk != actor.pk])
    if files:
        TaskFile.objects.filter(pk__in=list(files), task=task, uploaded_by=actor, comment__isnull=True).update(
            comment=comment)
    return comment


@transaction.atomic
def edit(actor, comment, text) -> "TaskComment":
    """Править свой комментарий; текст в журнал не попадает."""
    from apps.tasks.models import TaskComment

    if not access.can_edit_comment(actor, comment):
        raise TasksError("comment_forbidden", "text")
    body = (text or "").strip()
    if not body:
        raise TasksError("comment_empty", "text")
    if len(body) > TEXT_MAX:
        raise TasksError("comment_too_long", "text")
    comment.text = body
    comment.edited_at = timezone.now()
    comment.save(update_fields=["text", "edited_at"])
    audit.record("tasks.comment_changed", actor=actor, object_type="tasks.comment", object_id=comment.pk,
                 after={"task": comment.task_id})
    return comment


@transaction.atomic
def remove(actor, comment) -> "TaskComment":
    """Мягко удалить свой комментарий."""
    if not access.can_edit_comment(actor, comment):
        raise TasksError("comment_forbidden", "text")
    comment.deleted_at = timezone.now()
    comment.save(update_fields=["deleted_at"])
    audit.record("tasks.comment_changed", actor=actor, object_type="tasks.comment", object_id=comment.pk,
                 after={"task": comment.task_id, "deleted": True})
    return comment