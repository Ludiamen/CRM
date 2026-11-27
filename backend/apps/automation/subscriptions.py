"""Подписки автоматизации на события шины (PLAN-013, T-13021/T-13023/T-13024)."""
from apps.core import events

from .services import rules

MAPPING = {
    "servicedesk.ticket_created": ("ticket", "ticket_created"),
    "servicedesk.reply_received": ("ticket", "reply_received"),
    "servicedesk.ticket_field_changed": ("ticket", "ticket_field_changed"),
    "servicedesk.ticket_status_changed": ("ticket", "ticket_status_changed"),
    "servicedesk.ticket_transferred": ("ticket", "ticket_transferred"),
    "servicedesk.ticket_closed": ("ticket", "ticket_closed"),
    "servicedesk.sla_threshold": ("ticket", "sla_threshold"),
    "tasks.task_created": ("task", "task_created"),
    "tasks.task_field_changed": ("task", "task_field_changed"),
    "tasks.task_status_changed": ("task", "task_status_changed"),
    "tasks.task_threshold": ("task", "task_threshold"),
}


def _handler(subject_type: str, trigger: str):
    def handle(**data):
        subject_id = data.get("pk") or data.get("id")
        event_id = data.get("event_id") or f"{trigger}:{subject_id}"
        if trigger == "sla_threshold" and "deadline" in data:
            data = {**data, "sla_deadline": data["deadline"]}
        rules.on_event(subject_type, subject_id, trigger, event_id, data)

    handle.__name__ = f"automation_{subject_type}_{trigger}"
    return handle


_HANDLERS = {event: _handler(subject_type, trigger)
             for event, (subject_type, trigger) in MAPPING.items()}


def register() -> None:
    for event, handler in _HANDLERS.items():
        events.subscribe(event, handler)
