"""Перенос срока поручения (срез 010, T-10206; FR-708; CONTRACT-010, 5.1, 6.2).

Запрос — ответственный исполнитель; решает автор или контролёр. Согласование меняет `deadline`, исходный срок
(`original_deadline`) не меняется; история — все строки `InstructionTransfer`.
"""
from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.instructions.models import InstructionTransfer
from apps.instructions.services import access
from apps.instructions.texts import InstructionsError


def _as_date(value):
    import datetime

    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise InstructionsError("transfer_deadline", "new_deadline") from None


@transaction.atomic
def request(actor, instruction, *, new_deadline, reason) -> InstructionTransfer:
    """Запросить перенос срока с причиной."""
    if instruction.closed_at is not None:
        raise InstructionsError("transfer_closed", "reason")
    if not access.can_request_transfer(actor, instruction):
        if actor.pk != instruction.assignee_id:
            raise InstructionsError("transfer_forbidden", "reason")
        raise InstructionsError("transfer_state", "reason")
    due = _as_date(new_deadline)
    if due <= instruction.deadline:
        raise InstructionsError("transfer_deadline", "new_deadline")
    text = (reason or "").strip()
    if not 1 <= len(text) <= 1_000:
        raise InstructionsError("transfer_reason", "reason")
    row = InstructionTransfer.objects.create(
        instruction=instruction, old_deadline=instruction.deadline, new_deadline=due, reason=text,
        requested_by=actor, state="pending")
    audit.record("instructions.transfer_requested", actor=actor, object_type="instructions.instruction",
                 object_id=instruction.pk,
                 after={"old": instruction.deadline.isoformat(), "new": due.isoformat(), "reason": text})
    return row


@transaction.atomic
def decide(actor, transfer, *, approve, comment="") -> InstructionTransfer:
    """Согласовать или отклонить перенос; при согласовании меняется только `deadline`."""
    instruction = transfer.instruction
    if not access.can_decide_transfer(actor, instruction):
        raise InstructionsError("decision_forbidden", "comment")
    if transfer.state != "pending":
        raise InstructionsError("transfer_decided", "reason")
    reason = (comment or "").strip()
    if not approve and not reason:
        raise InstructionsError("return_comment_required", "comment")
    now = timezone.now()
    transfer.state = "approved" if approve else "rejected"
    transfer.decided_by = actor
    transfer.decided_at = now
    transfer.comment = reason
    transfer.save(update_fields=["state", "decided_by", "decided_at", "comment"])
    if approve:
        instruction.deadline = transfer.new_deadline
        instruction.updated_at = now
        instruction.save(update_fields=["deadline", "updated_at"])
    audit.record("instructions.transfer_decided", actor=actor, object_type="instructions.instruction",
                 object_id=instruction.pk,
                 after={"transfer": transfer.pk, "state": transfer.state, "comment": reason})
    return transfer
