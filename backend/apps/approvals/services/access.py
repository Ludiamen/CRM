"""Доступ к шаблонам, маршрутам и заданиям (PLAN-014, T-14023/T-14040)."""
from apps.core.services import permissions

from ..models import ApprovalAssignment, ApprovalRoute


def is_admin(actor) -> bool:
    return permissions.has_permission(actor, "automation.manage")


def can_manage_templates(actor) -> bool:
    return is_admin(actor)


def subject_adapter(subject_type: str):
    from ..extensions import subjects

    return subjects().get(subject_type)


def subject_object(route: ApprovalRoute):
    adapter = subject_adapter(route.subject_type)
    return adapter.load(route.subject_id) if adapter is not None else None


def can_see_route(actor, route: ApprovalRoute) -> bool:
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if is_admin(actor) or route.initiator_id == actor.pk:
        return True
    if ApprovalAssignment.objects.filter(stage_run__route=route, user=actor).exists():
        return True
    adapter = subject_adapter(route.subject_type)
    obj = adapter.load(route.subject_id) if adapter is not None else None
    return bool(adapter is not None and obj is not None and adapter.can_view(actor, obj))


def can_cancel(actor, route: ApprovalRoute) -> bool:
    return route.status == ApprovalRoute.Status.RUNNING and (
        is_admin(actor) or route.initiator_id == getattr(actor, "pk", None))


def can_decide(actor, assignment: ApprovalAssignment) -> bool:
    return (assignment.status == ApprovalAssignment.Status.PENDING
            and assignment.user_id == getattr(actor, "pk", None)
            and assignment.stage_run.route.status == ApprovalRoute.Status.RUNNING)


def brief(route: ApprovalRoute) -> dict:
    adapter = subject_adapter(route.subject_type)
    obj = adapter.load(route.subject_id) if adapter is not None else None
    if adapter is None or obj is None:
        return {"number": route.subject_number, "title": route.template_name, "status": "", "description": ""}
    return adapter.brief(obj)
