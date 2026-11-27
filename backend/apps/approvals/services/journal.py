"""Журнал согласований без ПДн (PLAN-014, T-14034)."""
from apps.core.services import audit

from ..models import ApprovalAssignment, ApprovalRoute, ApprovalStageRun


def route_started(route: ApprovalRoute, *, actor, ip=None) -> None:
    audit.record("approvals.route_started", actor=actor, object_type="approvals.route", object_id=route.pk,
                 after={"subject_type": route.subject_type, "subject_id": route.subject_id,
                        "template": route.template_id, "status": route.status}, ip=ip)


def stage_completed(stage: ApprovalStageRun, *, actor, ip=None) -> None:
    audit.record("approvals.stage_completed", actor=actor, object_type="approvals.route", object_id=stage.route_id,
                 after={"stage_run": stage.pk, "order": stage.order, "status": stage.status}, ip=ip)


def decision(assignment: ApprovalAssignment, *, actor, ip=None) -> None:
    audit.record("approvals.decision", actor=actor, object_type="approvals.route",
                 object_id=assignment.stage_run.route_id,
                 after={"assignment": assignment.pk, "decision": assignment.decision,
                        "stage_run": assignment.stage_run_id}, ip=ip)


def route_finished(route: ApprovalRoute, *, actor, status: str, reason: str = "", ip=None) -> None:
    action = {
        "approved": "approvals.route_completed",
        "rejected": "approvals.route_rejected",
        "returned": "approvals.route_returned",
        "cancelled": "approvals.route_cancelled",
    }.get(status, "approvals.route_completed")
    audit.record(action, actor=actor, object_type="approvals.route", object_id=route.pk,
                 after={"status": status, "reason": reason}, ip=ip)


def assignment_cancelled(assignment: ApprovalAssignment, *, actor=None) -> None:
    audit.record("approvals.assignment_cancelled", actor=actor, object_type="approvals.route",
                 object_id=assignment.stage_run.route_id,
                 after={"assignment": assignment.pk, "stage_run": assignment.stage_run_id}, ip=None)
