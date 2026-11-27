"""Переходы этапов маршрута (PLAN-014, T-14020/T-14031)."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import ApprovalAssignment, ApprovalRoute, ApprovalStageRun
from . import events, journal


def current_assignments(stage: ApprovalStageRun) -> list[ApprovalAssignment]:
    """Ожидающие задания, которые сейчас видны участникам."""
    pending = list(stage.assignments.filter(status=ApprovalAssignment.Status.PENDING).order_by("order", "pk"))
    if stage.mode == "sequential":
        return pending[:1]
    return pending


def activate(stage: ApprovalStageRun, now=None) -> ApprovalStageRun:
    now = now or timezone.now()
    stage.status = ApprovalStageRun.Status.RUNNING
    stage.started_at = now
    stage.due_at = now + timedelta(hours=stage.deadline_hours) if stage.deadline_hours else None
    stage.save(update_fields=["status", "started_at", "due_at"])
    stage.assignments.filter(status=ApprovalAssignment.Status.PENDING).update(due_at=stage.due_at)
    if not stage.assignments.filter(status=ApprovalAssignment.Status.PENDING).exists():
        recalculate(stage, now=now)
    return stage


def next_stage(stage: ApprovalStageRun):
    return stage.route.stages.filter(order__gt=stage.order).order_by("order").first()


def complete(stage: ApprovalStageRun, *, actor, result: str, now=None) -> None:
    """Завершить этап и, если нужно, маршрут."""
    now = now or timezone.now()
    stage.status = ApprovalStageRun.Status.DONE
    stage.finished_at = now
    stage.save(update_fields=["status", "finished_at"])
    journal.stage_completed(stage, actor=actor)
    events.stage_completed(stage, actor=actor, result=result)
    nxt = next_stage(stage)
    if nxt is not None:
        activate(nxt, now)
        return
    route = stage.route
    if result == "approved":
        route.status = ApprovalRoute.Status.APPROVED
        route.finished_at = now
        route.save(update_fields=["status", "finished_at"])
        journal.route_finished(route, actor=actor, status=route.status)
        events.route_finished(route, actor=actor, kind="completed")
    else:
        route.status = ApprovalRoute.Status.REJECTED if result == "rejected" else ApprovalRoute.Status.RETURNED
        route.finished_at = now
        route.save(update_fields=["status", "finished_at"])
        journal.route_finished(route, actor=actor, status=route.status)
        events.route_finished(route, actor=actor, kind=route.status)


def cancel_others(stage: ApprovalStageRun, *, except_user_id=None) -> None:
    pending = stage.assignments.filter(status=ApprovalAssignment.Status.PENDING)
    if except_user_id is not None:
        pending = pending.exclude(user_id=except_user_id)
    for assignment in pending:
        assignment.status = ApprovalAssignment.Status.CANCELLED
        assignment.save(update_fields=["status"])
        journal.assignment_cancelled(assignment)
        events.assignment_cancelled(assignment)


def cancel_route_pending(route: ApprovalRoute) -> None:
    for stage in route.stages.all():
        for assignment in stage.assignments.filter(status=ApprovalAssignment.Status.PENDING):
            assignment.status = ApprovalAssignment.Status.CANCELLED
            assignment.save(update_fields=["status"])
            journal.assignment_cancelled(assignment)
            events.assignment_cancelled(assignment)


def approved(stage: ApprovalStageRun, assignment: ApprovalAssignment, *, actor, now=None) -> None:
    """Обработать «Согласовано» с учётом режима и правила этапа."""
    now = now or timezone.now()
    if stage.mode == "parallel" and stage.rule == "any":
        cancel_others(stage, except_user_id=assignment.user_id)
        complete(stage, actor=actor, result="approved", now=now)
        return
    pending = stage.assignments.filter(status=ApprovalAssignment.Status.PENDING).exclude(pk=assignment.pk)
    if not pending.exists():
        complete(stage, actor=actor, result="approved", now=now)


def rejected(stage: ApprovalStageRun, assignment: ApprovalAssignment, *, actor, decision: str, now=None) -> None:
    now = now or timezone.now()
    stage.status = ApprovalStageRun.Status.DONE
    stage.finished_at = now
    stage.save(update_fields=["status", "finished_at"])
    journal.stage_completed(stage, actor=actor)
    events.stage_completed(stage, actor=actor, result=decision)
    route = stage.route
    route.status = ApprovalRoute.Status.REJECTED if decision == "rejected" else ApprovalRoute.Status.RETURNED
    route.finished_at = now
    route.save(update_fields=["status", "finished_at"])
    cancel_route_pending(route)
    journal.route_finished(route, actor=actor, status=route.status)
    events.route_finished(route, actor=actor, kind=route.status, assignment_id=assignment.pk)


def recalculate(stage: ApprovalStageRun, *, actor=None, now=None) -> None:
    """После отмены задания: завершить этап или маршрут, если ждать больше некого."""
    now = now or timezone.now()
    route = stage.route
    if route.status != ApprovalRoute.Status.RUNNING:
        return
    pending = stage.assignments.filter(status=ApprovalAssignment.Status.PENDING).exists()
    approved = stage.assignments.filter(status=ApprovalAssignment.Status.APPROVED).exists()
    if pending:
        return
    if stage.mode == "sequential" and approved:
        complete(stage, actor=actor, result="approved", now=now)
    elif stage.mode == "parallel" and approved and stage.rule == "all":
        complete(stage, actor=actor, result="approved", now=now)
    elif not approved:
        route = stage.route
        route.status = ApprovalRoute.Status.CANCELLED
        route.finished_at = now
        route.save(update_fields=["status", "finished_at"])
        cancel_route_pending(route)
        journal.route_finished(route, actor=actor, status=route.status, reason="no_participants")
        events.route_finished(route, actor=actor, kind="cancelled")
