"""Адаптер заявки для согласований (PLAN-014, T-14011)."""
from apps.approvals.extensions import ApprovalSubject

from .models import Ticket
from .services import access


def approval_subject() -> ApprovalSubject:
    return ApprovalSubject(
        type="ticket",
        title="Заявка",
        load=_load,
        lock=_lock,
        brief=_brief,
        can_view=access.can_view,
        can_work=access.can_work,
        url=lambda ticket: f"/tickets/{ticket.number}/",
    )


def _query():
    return Ticket.objects.select_related("status", "queue", "assignee")


def _load(pk: int):
    return _query().filter(pk=pk).first()


def _lock(pk: int):
    return _query().select_for_update(of=("self",)).filter(pk=pk).first()


def _brief(ticket) -> dict:
    return {
        "number": ticket.number,
        "title": ticket.subject,
        "status": ticket.status.name,
        "description": ticket.resolution or "",
        "queue": ticket.queue.name,
        "url": f"/tickets/{ticket.number}/",
        "closed": ticket.closed_at is not None,
    }
