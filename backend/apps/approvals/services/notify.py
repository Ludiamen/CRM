"""Уведомления согласований (PLAN-014, T-14032)."""


def _dispatch(kind, drafts) -> None:
    from apps.notify.services import dispatch

    dispatch.create(kind, drafts)


def _draft(user_id, text, url, object_ref=""):
    from apps.core.extensions import Draft

    return Draft(user_id=user_id, text=text, url=url, object_ref=object_ref)


def _route_url(route) -> str:
    return f"/approvals/routes/{route.pk}/"


def assignment(route, assignment) -> None:
    from ..notify_kinds import ASSIGNMENT, assignment_ref

    text = (f"Задание согласования: {route.template_name}, "
            f"{assignment.stage_run.title}, №{route.subject_number}")
    _dispatch(ASSIGNMENT, [_draft(assignment.user_id, text, _route_url(route), assignment_ref(assignment.pk))])


def decision(route, assignment, actor) -> None:
    from ..notify_kinds import DECISION, RETURNED, route_ref

    kind = RETURNED if assignment.decision == "returned" else DECISION
    text = (f"Маршрут {route.template_name} №{route.subject_number}: "
            f"{assignment.get_decision_display()}")
    _dispatch(kind, [_draft(route.initiator_id, text, _route_url(route), route_ref(route.pk))])


def returned(route, assignment) -> None:
    decision(route, assignment, assignment.user)


def _due(route, assignment, kind, text) -> None:
    from ..notify_kinds import assignment_ref

    drafts = [
        _draft(assignment.user_id, text, _route_url(route), assignment_ref(assignment.pk)),
        _draft(route.initiator_id, text, _route_url(route), assignment_ref(assignment.pk)),
    ]
    seen = set()
    unique = []
    for draft in drafts:
        if draft.user_id not in seen:
            seen.add(draft.user_id)
            unique.append(draft)
    _dispatch(kind, unique)


def reminder(assignment) -> None:
    from ..notify_kinds import REMINDER

    route = assignment.stage_run.route
    _due(route, assignment, REMINDER,
         f"Напоминание: срок задания {assignment.stage_run.title} по маршруту №{route.subject_number}")


def overdue(assignment) -> None:
    from ..notify_kinds import OVERDUE

    route = assignment.stage_run.route
    _due(route, assignment, OVERDUE,
         f"Просрочено задание {assignment.stage_run.title} по маршруту №{route.subject_number}")
