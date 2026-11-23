"""Получатели уведомлений поручений (срез 010, T-10209; FR-711; CONTRACT-010, 9.2).

Возвращает `{user_id: код вида}`; один человек получает одно сообщение. Свои действия не уведомляются.
"""
from apps.instructions.models import InstructionMember


def _coexecutors(instruction):
    return [row.user for row in InstructionMember.objects.filter(instruction=instruction).select_related("user")]


def _put(target: dict, user, code: str) -> None:
    if user is not None:
        target[user.pk] = code


def recipients(instruction, event, actor=None) -> dict:
    """Кому и какой вид уведомления для события."""
    actor_id = getattr(actor, "pk", None)
    target = {}
    assignee = instruction.assignee
    coexecutors = _coexecutors(instruction)
    controller = instruction.controller
    author = instruction.author
    if event in ("assigned", "deadline", "report_due"):
        code = {"assigned": "instructions.assigned", "deadline": "instructions.deadline",
                "report_due": "instructions.report_due"}[event]
        for person in [assignee, *coexecutors]:
            if person.pk != actor_id:
                _put(target, person, code)
    elif event == "report_overdue":
        for person in (controller, author):
            if person.pk != actor_id:
                _put(target, person, "instructions.report_overdue")
    elif event == "overdue":
        for person in [assignee, *coexecutors, controller, author]:
            if person.pk != actor_id:
                _put(target, person, "instructions.overdue")
    elif event == "report_submitted":
        for person in (controller, author):
            if person.pk != actor_id:
                _put(target, person, "instructions.report_submitted")
    elif event in ("report_accepted", "report_returned"):
        code = f"instructions.{event}"
        for person in [assignee, *coexecutors]:
            if person.pk != actor_id:
                _put(target, person, code)
    elif event == "transfer_requested":
        for person in (controller, author):
            if person.pk != actor_id:
                _put(target, person, "instructions.transfer")
    elif event == "transfer_decided":
        if assignee.pk != actor_id:
            _put(target, assignee, "instructions.transfer")
    elif event == "digest":
        for person in (controller, author):
            _put(target, person, "instructions.digest")
    return target