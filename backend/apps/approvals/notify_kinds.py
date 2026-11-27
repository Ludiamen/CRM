"""Виды уведомлений согласований (PLAN-014, T-14032)."""
from django.contrib.auth import get_user_model

from apps.core.extensions import NotificationKind

ASSIGNMENT = "approvals.assignment"
DECISION = "approvals.decision"
RETURNED = "approvals.returned"
REMINDER = "approvals.reminder"
OVERDUE = "approvals.overdue"
MODULE = "Согласования"


def assignment_ref(assignment_id: int) -> str:
    return f"approvals.assignment:{assignment_id}"


def route_ref(route_id: int) -> str:
    return f"approvals.route:{route_id}"


def _assignment_relevant(user_id: int, object_ref: str) -> bool:
    from .models import ApprovalAssignment

    try:
        assignment_id = int((object_ref or "").split(":")[-1])
    except ValueError:
        return False
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or user.state == "dismissed":
        return False
    return ApprovalAssignment.objects.filter(pk=assignment_id, user_id=user_id,
                                             status=ApprovalAssignment.Status.PENDING).exists()


def _route_relevant(user_id: int, object_ref: str) -> bool:
    from .models import ApprovalRoute

    try:
        route_id = int((object_ref or "").split(":")[-1])
    except ValueError:
        return False
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or user.state == "dismissed":
        return False
    return ApprovalRoute.objects.filter(pk=route_id).exists()


def _available(user) -> bool:
    from .models import ApprovalAssignment, ApprovalRoute

    return (ApprovalAssignment.objects.filter(user=user).exists()
            or ApprovalRoute.objects.filter(initiator=user).exists())


def notification_kinds() -> list:
    return [
        NotificationKind(code=ASSIGNMENT, title="Задание согласования", module=MODULE, order=250,
                         external_text="Вам назначено задание согласования", default_channels=("portal", "email"),
                         available=_available, still_relevant=_assignment_relevant),
        NotificationKind(code=DECISION, title="Решение по согласованию", module=MODULE, order=251,
                         external_text="По маршруту согласования принято решение", default_channels=("portal", "email"),
                         available=_available, still_relevant=_route_relevant),
        NotificationKind(code=RETURNED, title="Возврат на доработку", module=MODULE, order=252,
                         external_text="Маршрут согласования возвращён", default_channels=("portal", "email"),
                         available=_available, still_relevant=_route_relevant),
        NotificationKind(code=REMINDER, title="Напоминание о сроке задания", module=MODULE, order=253,
                         external_text="Приближается срок задания согласования", default_channels=("portal", "email"),
                         available=_available, still_relevant=_assignment_relevant),
        NotificationKind(code=OVERDUE, title="Просроченное задание согласования", module=MODULE, order=254,
                         external_text="Срок задания согласования наступил", default_channels=("portal", "email"),
                         available=_available, still_relevant=_assignment_relevant),
    ]
