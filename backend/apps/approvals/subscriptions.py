"""Подписка автоматики на события согласований (PLAN-014, T-14033)."""
from apps.core import events

MAPPING = {
    "approvals.started": "approval_started",
    "approvals.stage_completed": "approval_stage_completed",
    "approvals.completed": "approval_completed",
    "approvals.rejected": "approval_rejected",
    "approvals.returned": "approval_returned",
    "approvals.cancelled": "approval_cancelled",
}


def _handler(trigger: str):
    def handle(**data):
        from apps.automation.services import rules

        subject_type = data.get("subject_type")
        subject_id = data.get("subject_id")
        event_id = data.get("event_id") or f"{trigger}:{subject_id}"
        if subject_type and subject_id:
            rules.on_event(subject_type, subject_id, trigger, event_id, data)

    handle.__name__ = f"approvals_{trigger}"
    return handle


def register() -> None:
    for event, trigger in MAPPING.items():
        events.subscribe(event, _handler(trigger))
