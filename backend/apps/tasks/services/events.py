"""События задач для шины и автоматизации (PLAN-013, T-13024; SPEC-013, FR-796/816)."""
from apps.core import events as bus

TASK_CREATED = "tasks.task_created"
TASK_FIELD_CHANGED = "tasks.task_field_changed"
TASK_STATUS_CHANGED = "tasks.task_status_changed"
TASK_THRESHOLD = "tasks.task_threshold"


def task_created(task) -> None:
    bus.publish(TASK_CREATED, id=task.pk, author_id=task.author_id, event_id=f"task-created:{task.pk}")


def task_field_changed(task, *, changed: list, audit_id: int) -> None:
    bus.publish(TASK_FIELD_CHANGED, id=task.pk, changed=list(changed), event_id=f"task-update:{audit_id}")


def task_status_changed(task, *, before: str, after: str, audit_id: int) -> None:
    bus.publish(TASK_STATUS_CHANGED, id=task.pk, before=before, after=after,
                event_id=f"task-status:{audit_id}")


def task_threshold(task, *, deadline, kind: str) -> None:
    bus.publish(TASK_THRESHOLD, id=task.pk, deadline=str(deadline), kind=kind,
                event_id=f"task:{task.pk}:{kind}:{deadline}")
