"""Службы поручений: переназначение при увольнении (T-10202; FR-722; CONTRACT-010, 5.1).

Создание, правка, снятие и связь с задачами добавляют T-10203/T-10206/T-10214.
"""
from django.db import transaction

from apps.core.services import audit
from apps.instructions.models import Instruction


def reassign(user_id, **data) -> int:
    """Подписчик `core.user_dismissed`: контроль возвращается постановщику.

    Исполнитель автоматически не заменяется — нового назначает автор (FR-722).
    """
    instruction_controller = Instruction.objects.filter(
        controller_id=user_id, closed_at__isnull=True, deleted_at__isnull=True).exclude(author_id=user_id)
    changed = 0
    with transaction.atomic():
        for row in list(instruction_controller):
            before = row.controller_id
            row.controller_id = row.author_id
            row.save(update_fields=["controller"])
            audit.record("instructions.reassigned", object_type="instructions.instruction", object_id=row.pk,
                         before={"controller": before, "reason": "уволен"},
                         after={"controller": row.controller_id})
            changed += 1
    return changed

# --- создание и правка (T-10203; FR-700…704, 718) -------------------------------------------------

import datetime  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.core.widgets import moscow_today  # noqa: E402
from apps.instructions.models import (InstructionBasisKind, InstructionMember,  # noqa: E402
                                      InstructionReportDate)
from apps.instructions.services import access  # noqa: E402
from apps.instructions.services import dates as dates_service  # noqa: E402
from apps.instructions.texts import InstructionsError  # noqa: E402

MAX_TITLE = 300
MAX_TEXT = 10_000


def _text(value, limit, code, field) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise InstructionsError(code, field)
    return text


def _title(value) -> str:
    text = (value or "").strip()
    if not 1 <= len(text) <= MAX_TITLE:
        raise InstructionsError("title_range", "title")
    return text


def _as_date(value, code, field):
    if value in (None, ""):
        raise InstructionsError(code, field)
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        raise InstructionsError(code, field) from None


def _user(value):
    if value is None or value == "":
        return None
    if hasattr(value, "pk"):
        return value
    return get_user_model().objects.filter(pk=value).first()


def _assignee(value):
    person = _user(value)
    if person is None:
        raise InstructionsError("assignee_required", "assignee")
    if getattr(person, "state", "") == "dismissed":
        raise InstructionsError("assignee_dismissed", "assignee")
    return person


def _members(users, assignee) -> list:
    cleaned, seen = [], set()
    for value in users or ():
        person = _user(value)
        if person is None:
            continue
        if person.pk == assignee.pk:
            raise InstructionsError("member_is_assignee", "members")
        if getattr(person, "state", "") == "dismissed":
            raise InstructionsError("member_dismissed", "members")
        if person.pk in seen:
            raise InstructionsError("member_duplicate", "members")
        seen.add(person.pk)
        cleaned.append(person)
    return cleaned


def _basis(value):
    kind = value if isinstance(value, InstructionBasisKind) else InstructionBasisKind.objects.filter(pk=value).first()
    if kind is None or not kind.active:
        raise InstructionsError("basis_unknown", "basis_kind")
    return kind


def _iso(day) -> str:
    return day.isoformat() if day else ""


def _store_members(instruction, users) -> None:
    InstructionMember.objects.filter(instruction=instruction).exclude(user__in=users).delete()
    existing = set(InstructionMember.objects.filter(instruction=instruction).values_list("user_id", flat=True))
    InstructionMember.objects.bulk_create([InstructionMember(instruction=instruction, user=person)
                                           for person in users if person.pk not in existing])


@transaction.atomic
def create(actor, *, title, text="", basis_kind, basis_number, basis_date, assignee, deadline,
           members=(), controller=None, periodicity="", dates=()) -> Instruction:
    """Создать поручение; проверки текста, основания, срока, исполнителя, состава и прав."""
    person = _assignee(assignee)
    if not access.can_assign(actor, person):
        raise InstructionsError("assignee_forbidden", "assignee")
    if basis_kind in (None, ""):
        raise InstructionsError("basis_required", "basis_kind")
    kind = _basis(basis_kind)
    number = (basis_number or "").strip()
    if not number:
        raise InstructionsError("basis_required", "basis_number")
    document_date = _as_date(basis_date, "basis_required", "basis_date")
    if deadline in (None, ""):
        raise InstructionsError("deadline_required", "deadline")
    due = _as_date(deadline, "deadline_required", "deadline")
    if due < moscow_today():
        raise InstructionsError("deadline_past", "deadline")
    owner = actor if controller in (None, "") else _user(controller)
    if owner is None:
        raise InstructionsError("controller_dismissed", "controller")
    if getattr(owner, "state", "") == "dismissed":
        raise InstructionsError("controller_dismissed", "controller")
    people = _members(members, person)
    now = timezone.now()
    row = Instruction.objects.create(
        title=_title(title), text=_text(text, MAX_TEXT, "text_long", "text"), basis_kind=kind,
        basis_number=number[:100], basis_date=document_date, author=actor, controller=owner, assignee=person,
        deadline=due, original_deadline=due, ladder={}, created_at=now, updated_at=now)
    _store_members(row, people)
    audit.record("instructions.created", actor=actor, object_type="instructions.instruction", object_id=row.pk,
                 after={"title": row.title, "assignee": person.full_name, "deadline": _iso(due),
                        "basis": f"{kind.title} {number} от {_iso(document_date)}"})
    if periodicity or dates:
        dates_service.build(row, periodicity=periodicity, dates=dates)
    return row


@transaction.atomic
def update(actor, instruction, **fields) -> Instruction:
    """Изменить поля поручения; автору и только до снятия с контроля."""
    if not access.can_edit_fields(actor, instruction):
        raise InstructionsError("edit_forbidden", "title")
    before, after = {}, {}
    if "title" in fields:
        value = _title(fields["title"])
        if value != instruction.title:
            before["title"], after["title"] = instruction.title, value
            instruction.title = value
    if "text" in fields:
        value = _text(fields["text"], MAX_TEXT, "text_long", "text")
        if value != instruction.text:
            before["text"], after["text"] = instruction.text, value
            instruction.text = value
    if "basis_kind" in fields or "basis_number" in fields or "basis_date" in fields:
        kind = _basis(fields.get("basis_kind", instruction.basis_kind_id))
        number = (fields.get("basis_number", instruction.basis_number) or "").strip()
        if not number:
            raise InstructionsError("basis_required", "basis_number")
        document_date = _as_date(fields.get("basis_date", instruction.basis_date), "basis_required", "basis_date")
        basis_text = f"{kind.title} {number} от {_iso(document_date)}"
        old = f"{instruction.basis_kind.title} {instruction.basis_number} от {_iso(instruction.basis_date)}"
        if basis_text != old:
            before["basis"], after["basis"] = old, basis_text
            instruction.basis_kind, instruction.basis_number, instruction.basis_date = kind, number[:100], document_date
    if "assignee" in fields:
        person = _assignee(fields["assignee"])
        if not access.can_assign(actor, person):
            raise InstructionsError("assignee_forbidden", "assignee")
        if person.pk != instruction.assignee_id:
            before["assignee"], after["assignee"] = instruction.assignee_id, person.pk
            instruction.assignee = person
    if "controller" in fields:
        owner = _user(fields["controller"])
        if owner is None or getattr(owner, "state", "") == "dismissed":
            raise InstructionsError("controller_dismissed", "controller")
        if owner.pk != instruction.controller_id:
            before["controller"], after["controller"] = instruction.controller_id, owner.pk
            instruction.controller = owner
    if "deadline" in fields:
        due = _as_date(fields["deadline"], "deadline_required", "deadline")
        if due != instruction.deadline:
            before["deadline"], after["deadline"] = _iso(instruction.deadline), _iso(due)
            instruction.deadline = due
    if "members" in fields:
        people = _members(fields["members"], instruction.assignee)
        old = sorted(InstructionMember.objects.filter(instruction=instruction)
                     .values_list("user__full_name", flat=True))
        new = sorted(person.full_name for person in people)
        if old != new:
            before["members"], after["members"] = old, new
            _store_members(instruction, people)
    instruction.updated_at = timezone.now()
    instruction.save()
    if before:
        audit.record("instructions.changed", actor=actor, object_type="instructions.instruction",
                     object_id=instruction.pk, before=before, after=after)
    if (fields.get("periodicity") or fields.get("dates")) and access.can_edit_fields(actor, instruction):
        dates_service.rebuild(instruction, periodicity=fields.get("periodicity") or None,
                              dates=fields.get("dates") or ())
    return instruction


@transaction.atomic
def close(actor, instruction) -> Instruction:
    """Снять с контроля: только контролёр, при принятом итоговом отчёте и без pending-переноса (FR-707)."""
    from apps.instructions.models import InstructionReminder, InstructionReport, InstructionTransfer

    if instruction.closed_at is not None or actor.pk != instruction.controller_id:
        raise InstructionsError("close_forbidden", "confirm")
    if InstructionTransfer.objects.filter(instruction=instruction, state="pending").exists():
        raise InstructionsError("close_transfer_pending", "confirm")
    if not InstructionReport.objects.filter(instruction=instruction, date__isnull=True,
                                            decision="accepted").exists():
        raise InstructionsError("close_no_report", "confirm")
    now = timezone.now()
    instruction.closed_at = now
    instruction.updated_at = now
    instruction.save(update_fields=["closed_at", "updated_at"])
    InstructionReminder.objects.filter(instruction=instruction, state="pending").update(state="cancelled")
    audit.record("instructions.closed", actor=actor, object_type="instructions.instruction",
                 object_id=instruction.pk, after={"closed_at": now.isoformat()})
    return instruction
