"""Отчёты и части отчёта (срез 010, T-10205; FR-706, 707, 723; CONTRACT-010, 5.1, 7).

Сводный отчёт ответственного — к отчётной дате или к сроку (`date=None`, один на автора). Часть принадлежит
отчётной дате и переживает возврат. Отправка снимает `pending`-напоминания даты; решение одно на дату.
"""
from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.instructions.models import (InstructionReport, InstructionReportDate, InstructionReportPart,
                                      InstructionReminder)
from apps.instructions.services import access
from apps.instructions.texts import InstructionsError

MAX_TEXT = 10_000
FILE_LIMIT = 10


def _text(value) -> str:
    text = (value or "").strip()
    if not text:
        raise InstructionsError("report_empty", "text")
    if len(text) > MAX_TEXT:
        raise InstructionsError("report_long", "text")
    return text


def _files(values) -> tuple:
    values = tuple(values or ())
    if len(values) > FILE_LIMIT:
        raise InstructionsError("report_limit", "file")
    return values


def _date(instruction, value):
    if value in (None, ""):
        return None
    if isinstance(value, InstructionReportDate):
        if value.instruction_id != instruction.pk:
            raise InstructionsError("report_date_unknown", "date")
        return value
    row = InstructionReportDate.objects.filter(pk=value, instruction=instruction).first()
    if row is None:
        raise InstructionsError("report_date_unknown", "date")
    return row


@transaction.atomic
def submit(actor, instruction, *, date=None, text, files=()) -> InstructionReport:
    """Отправить сводный отчёт к дате или сроку; дата переходит в «на проверке»."""
    if instruction.closed_at is not None:
        raise InstructionsError("report_closed", "text")
    date_row = _date(instruction, date)
    if not access.can_report(actor, instruction, date_row):
        raise InstructionsError("report_forbidden", "text")
    body = _text(text)
    _files(files)
    now = timezone.now()
    if date_row is None:
        report, _ = InstructionReport.objects.update_or_create(
            instruction=instruction, date=None, author=actor,
            defaults={"text": body, "submitted_at": now, "decision": "pending", "decided_by": None,
                      "decided_at": None, "comment": ""})
    else:
        report = InstructionReport.objects.create(
            instruction=instruction, date=date_row, author=actor, text=body, submitted_at=now)
        date_row.state = "review"
        date_row.closed_at = None
        date_row.save(update_fields=["state", "closed_at"])
        InstructionReminder.objects.filter(instruction=instruction, date=date_row, state="pending").update(
            state="cancelled")
    audit.record("instructions.report_submitted", actor=actor, object_type="instructions.instruction",
                 object_id=instruction.pk,
                 after={"report": report.pk, "date": date_row.pk if date_row else None})
    return report


@transaction.atomic
def add_part(actor, instruction, report_date, *, text, files=()) -> InstructionReportPart:
    """Добавить часть отчёта соисполнителя или ответственного к отчётной дате."""
    if instruction.closed_at is not None:
        raise InstructionsError("report_closed", "text")
    if not access.can_add_part(actor, instruction, report_date):
        raise InstructionsError("part_forbidden", "text")
    body = _text(text)
    _files(files)
    if InstructionReportPart.objects.filter(date=report_date, author=actor).exists():
        raise InstructionsError("part_duplicate", "text")
    part = InstructionReportPart.objects.create(date=report_date, author=actor, text=body)
    audit.record("instructions.part_added", actor=actor, object_type="instructions.instruction",
                 object_id=instruction.pk, after={"date": report_date.pk, "author": actor.pk})
    return part


@transaction.atomic
def decide(actor, report, *, accept, comment="") -> InstructionReport:
    """Решение контролёра по сводному отчёту: принять или вернуть с причиной."""
    instruction = report.instruction
    if not access.can_decide(actor, instruction):
        raise InstructionsError("decision_forbidden", "comment")
    if report.decision != "pending":
        raise InstructionsError("decision_state", "comment")
    reason = (comment or "").strip()
    if not accept and not reason:
        raise InstructionsError("return_comment_required", "comment")
    if len(reason) > 2_000:
        raise InstructionsError("return_comment_required", "comment")
    now = timezone.now()
    report.decision = "accepted" if accept else "returned"
    report.decided_by = actor
    report.decided_at = now
    report.comment = reason
    report.save(update_fields=["decision", "decided_by", "decided_at", "comment"])
    if report.date_id is not None:
        date_row = report.date
        date_row.state = "accepted" if accept else "returned"
        date_row.closed_at = now if accept else None
        date_row.save(update_fields=["state", "closed_at"])
    audit.record("instructions.report_accepted" if accept else "instructions.report_returned", actor=actor,
                 object_type="instructions.instruction", object_id=instruction.pk,
                 after={"report": report.pk, "date": report.date_id, "comment": reason})
    return report