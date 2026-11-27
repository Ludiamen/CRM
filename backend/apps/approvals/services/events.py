"""Публикация событий согласований (PLAN-014, T-14033)."""
from django.utils import timezone

from apps.core import events as bus

from ..models import ApprovalAssignment, ApprovalRoute, ApprovalStageRun


def _common(route: ApprovalRoute, actor=None) -> dict:
    return {
        "route_id": route.pk,
        "subject_type": route.subject_type,
        "subject_id": route.subject_id,
        "subject_number": route.subject_number,
        "initiator_id": route.initiator_id,
        "actor_id": getattr(actor, "pk", None),
        "status": route.status,
        "event_id": "",
        "dedupe_key": "",
    }


def started(route: ApprovalRoute, *, actor) -> None:
    data = _common(route, actor)
    event_id = f"approval-start:{route.pk}"
    data.update(event_id=event_id, dedupe_key=event_id, template_id=route.template_id,
                started_at=route.started_at.isoformat() if route.started_at else "")
    bus.publish("approvals.started", **data)


def stage_completed(stage: ApprovalStageRun, *, actor, result: str) -> None:
    route = stage.route
    data = _common(route, actor)
    event_id = f"approval-stage:{stage.pk}"
    data.update(event_id=event_id, dedupe_key=event_id, stage_run_id=stage.pk, order=stage.order, result=result)
    bus.publish("approvals.stage_completed", **data)


def route_finished(route: ApprovalRoute, *, actor, kind: str, assignment_id=None) -> None:
    data = _common(route, actor)
    suffix = "approved" if kind == "completed" else kind
    event_id = f"approval-route:{route.pk}:{suffix}"
    data.update(event_id=event_id, dedupe_key=event_id,
                finished_at=(route.finished_at or timezone.now()).isoformat(),
                assignment_id=assignment_id)
    bus.publish(f"approvals.{kind}", **data)


def assignment_cancelled(assignment: ApprovalAssignment) -> None:
    """Внутреннее событие задания не публикуется в шину: шесть событий маршрута заданы контрактом."""
    return None
