"""Исполнительская дисциплина (срез 010, T-10210; FR-714, NFR-721; CONTRACT-010, раздел 11, К23).

Две шкалы: по исходному сроку («в срок», «с переносом», «просрочено») и по сроку с переносами («в срок»,
«просрочено»). «Основной узел» — первый не-корневой по `path`, иначе корень. Администратор отчёт не получает.
"""
import datetime

from django.db.models import Q
from django.utils import timezone

from apps.core.widgets import moscow_today
from apps.instructions.models import Instruction, InstructionTransfer
from apps.instructions.services import access
from apps.instructions.texts import InstructionsError
from apps.org.services import structure


def main_unit(person):
    """Первый не-корневой узел цепочки сотрудника по `path`, иначе корень."""
    units = sorted(structure.units_of(person), key=lambda unit: unit.path)
    for unit in units:
        parts = [part for part in unit.path.split("/") if part]
        if len(parts) > 1:
            return structure.Unit.objects.get(pk=int(parts[1]))
    return structure.Unit.objects.get(parent=None)


def _unit_ids(unit=None) -> list[int]:
    if unit is None:
        return []
    return sorted(structure.descendants(unit, include_self=True).values_list("pk", flat=True))


def _final_deadline(instruction, closed_at):
    transfer = (InstructionTransfer.objects.filter(instruction=instruction, state="approved",
                                                  decided_at__lte=closed_at)
                .order_by("-decided_at", "-pk").first())
    return transfer.new_deadline if transfer is not None else instruction.deadline, transfer is not None


def _empty() -> dict:
    return {"in_time": 0, "with_transfer": 0, "overdue": 0, "total": 0,
            "final_in_time": 0, "final_overdue": 0}


def _person_row(person, unit) -> dict:
    return {"kind": "person", "unit": unit.name if unit else "", "person": person.full_name, **_empty()}


def _unit_row(unit) -> dict:
    return {"kind": "unit", "unit": unit.name, "person": "", **_empty()}


def rows(viewer, *, date_from, date_to, unit=None) -> dict:
    """Отчёт по дисциплине за период; 403/`discipline_forbidden` — без права."""
    if not access.can_view_discipline(viewer):
        raise InstructionsError("discipline_forbidden", "unit")
    if isinstance(date_from, str):
        date_from = datetime.date.fromisoformat(date_from)
    if isinstance(date_to, str):
        date_to = datetime.date.fromisoformat(date_to)
    unit_ids = _unit_ids(unit) if unit is not None else sorted(access.managed_units(viewer))
    if not unit_ids:
        return {"rows": [], "closed": [], "open_rows": [], "totals": _empty()}
    start = timezone.make_aware(datetime.datetime.combine(date_from, datetime.time(0)),
                                timezone.get_current_timezone())
    end = timezone.make_aware(datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time(0)),
                              timezone.get_current_timezone())
    closed_query = (Instruction.objects.filter(closed_at__gte=start, closed_at__lt=end,
                                               deleted_at__isnull=True)
                    .extra(where=["instructions_instruction.assignee_id IN ("
                                  "SELECT user_id FROM org_membership WHERE unit_id = ANY(%s))"],
                           params=[unit_ids]))
    closed = list(closed_query.select_related("assignee", "controller"))
    people: dict[int, dict] = {}
    units: dict[int, dict] = {}
    for row in closed:
        person = row.assignee
        unit_row = main_unit(person)
        person_row = people.setdefault(person.pk, _person_row(person, unit_row))
        bucket = units.setdefault(unit_row.pk, _unit_row(unit_row))
        final, has_transfer = _final_deadline(row, row.closed_at)
        closed_day = timezone.localtime(row.closed_at).date()
        if has_transfer:
            original = "with_transfer" if closed_day <= final else "overdue"
        else:
            original = "in_time" if closed_day <= row.original_deadline else "overdue"
        final_key = "final_in_time" if closed_day <= final else "final_overdue"
        for target in (person_row, bucket):
            target[original] += 1
            target[final_key] += 1
            target["total"] += 1

    open_rows = []
    open_query = (Instruction.objects.filter(closed_at__isnull=True, deleted_at__isnull=True,
                                             deadline__lt=moscow_today())
                  .extra(where=["instructions_instruction.assignee_id IN ("
                                "SELECT user_id FROM org_membership WHERE unit_id = ANY(%s))"],
                         params=[unit_ids]))
    for row in open_query.select_related("assignee"):
        unit_row = main_unit(row.assignee)
        open_rows.append({"kind": "person", "unit": unit_row.name, "person": row.assignee.full_name,
                          "instruction": row.pk, **_empty(), "overdue": 1, "total": 1})

    totals = _empty()
    for row in people.values():
        for key in totals:
            totals[key] += row[key]
    return {"rows": list(people.values()) + list(units.values()), "closed": closed,
            "open_rows": open_rows, "totals": totals}