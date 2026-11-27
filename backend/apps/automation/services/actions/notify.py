"""Действие «уведомить» (PLAN-013, T-13030; SPEC-013, FR-800/811/817)."""
from apps.core.extensions import Draft
from apps.notify.services import dispatch

from ...extensions import recipients as recipient_map

KIND = "automation.rule_notice"


def _params(subject, obj) -> dict:
    values = subject.values(obj)
    number = values.get("number") or values.get("id")
    if subject.type == "ticket":
        url = f"/tickets/{number}/"
        object_ref = f"servicedesk.ticket:{number}"
    else:
        url = f"/tasks/{number}/"
        object_ref = f"tasks.task:{number}"
    return {
        "number": str(number),
        "status": values.get("status_name") or "",
        "queue": values.get("queue_name") or "",
        "assignee": values.get("assignee_name") or "не назначен",
        "priority": values.get("priority_name") or "",
        "url": url,
        "_object_ref": object_ref,
    }


def run(row, params, obj, subject, rule) -> None:
    from . import ActionSkip

    codes = params.get("recipients") or []
    found = recipient_map(subject.type)
    user_ids = []
    employee = params.get("employee")
    for code in codes:
        if code == "employee":
            if employee is not None:
                try:
                    user_ids.append(int(employee))
                except (TypeError, ValueError):
                    pass
            continue
        recipient = found.get(code)
        if recipient is None:
            continue
        user_ids.extend(recipient.resolve(rule, obj))
    ordered = list(dict.fromkeys(user_ids))
    if not ordered:
        raise ActionSkip("нет получателей")
    values = subject.values(obj)
    text = str(params.get("text") or "").format(**_params(subject, obj))
    ref = _params(subject, obj)["_object_ref"]
    drafts = []
    from django.contrib.auth import get_user_model

    users = get_user_model().objects.filter(pk__in=ordered, state__in=("active", "blocked"))
    by_id = {user.pk: user for user in users}
    for user_id in ordered:
        user = by_id.get(user_id)
        if user is None or not subject.can_view(user, obj):
            continue
        drafts.append(Draft(user_id=user_id, text=text, url=_params(subject, obj)["url"], object_ref=ref))
    if not drafts:
        raise ActionSkip("нет получателей с доступом")
    dispatch.create(KIND, drafts)
