"""«Мои задания» и просрочка (PLAN-014, T-14030/T-14031)."""
from django.utils import timezone

from ..models import ApprovalAssignment, ApprovalRoute, ApprovalStageRun
from . import access, stages


def active_for(user):
    """Ожидающие задания, которые сейчас видны участнику (sequential — только текущее)."""
    from django.db.models import Prefetch

    rows = list(ApprovalAssignment.objects.filter(
        user=user, status=ApprovalAssignment.Status.PENDING,
        stage_run__route__status=ApprovalRoute.Status.RUNNING,
        stage_run__status=ApprovalStageRun.Status.RUNNING)
        .select_related("stage_run", "stage_run__route", "user")
        .prefetch_related(Prefetch(
            "stage_run__assignments",
            queryset=ApprovalAssignment.objects.filter(status=ApprovalAssignment.Status.PENDING).order_by("order", "pk")))
        .order_by("due_at", "pk"))
    result = []
    for assignment in rows:
        stage = assignment.stage_run
        if stage.mode == "sequential":
            current = next(iter(stage.assignments.all()), None)
            if current is None or current.pk != assignment.pk:
                continue
        result.append(assignment)
    return result


def rows(user):
    now = timezone.now()
    found = []
    for assignment in active_for(user):
        route = assignment.stage_run.route
        found.append({
            "assignment": assignment,
            "route": route,
            "brief": access.brief(route),
            "stage": assignment.stage_run,
            "due_at": assignment.due_at,
            "overdue": assignment.due_at is not None and assignment.due_at < now,
        })
    return found


def overdue_ids(user):
    return {item["assignment"].pk for item in rows(user) if item["overdue"]}
