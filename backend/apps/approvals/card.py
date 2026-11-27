"""Блок «Согласования» в карточках заявки и задачи (PLAN-014, T-14014/T-14041)."""
from django.template.loader import render_to_string

from apps.core.extensions import TaskCardPart, TicketCardPart

from .models import ApprovalRoute, ApprovalTemplate


def ticket_card_parts() -> list[TicketCardPart]:
    return [TicketCardPart(key="approvals-ticket", kind="section", order=40, render=_ticket)]


def task_card_parts() -> list[TaskCardPart]:
    return [TaskCardPart(key="approvals-task", order=40, render=_task)]


def _context(request, subject_type: str, subject_id: int) -> dict:
    from .extensions import subjects

    adapter = subjects().get(subject_type)
    subject = adapter.load(subject_id) if adapter is not None else None
    route = (ApprovalRoute.objects.filter(subject_type=subject_type, subject_id=subject_id)
             .order_by("-started_at", "-pk").first())
    templates = ApprovalTemplate.objects.filter(subject_type=subject_type, enabled=True).order_by("name")
    if adapter is not None and subject is not None:
        if not adapter.can_view(request.user, subject):
            route = None
        if not adapter.can_work(request.user, subject):
            templates = templates.none()
    return {"route": route, "templates": templates}


def _ticket(request, ref) -> str | None:
    if not ref.pk:
        return None
    context = _context(request, "ticket", ref.pk)
    if context["route"] is None and not context["templates"].exists():
        return None
    return render_to_string("approvals/_card_block.html",
                            {**context, "subject_type": "ticket",
                             "subject_id": ref.pk, "subject_title": f"№{ref.number}"}, request=request)


def _task(request, ref) -> str | None:
    context = _context(request, "task", ref.number)
    if context["route"] is None and not context["templates"].exists():
        return None
    return render_to_string("approvals/_card_block.html",
                            {**context, "subject_type": "task",
                             "subject_id": ref.number, "subject_title": f"№{ref.number}"}, request=request)
