"""Подсказки выбора сотрудников и подразделений в ленте."""

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.db.models import CharField, Value
from django.db.models.functions import Lower, Replace
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.core.models import User
from apps.core.models.accounts import UserState


def _fold_name(expression):
    """Сравнивает ФИО без различия регистра и «ё/е»."""
    return Replace(Lower(expression), Value("ё"), Value("е"), output_field=CharField())


@login_required
@require_GET
def pick(request):
    scope = request.GET.get("scope", "")
    query = request.GET.get("q", "").strip()
    rows = []
    if scope in {"to", "mention", "author"} and len(query) >= 2:
        folded_query = query.lower().replace("ё", "е")
        units_by_id = {}
        org_structure = None
        if scope == "to" and apps.is_installed("apps.org"):
            from apps.org.services import structure as org_structure

            units_by_id = {unit.id: unit for unit in org_structure.all_units()}
        employees = User.objects.annotate(_folded_name=_fold_name("full_name"))
        if scope in {"to", "mention"}:
            employees = employees.exclude(state__in=[UserState.BLOCKED, UserState.DISMISSED])
        employees = employees.filter(_folded_name__contains=folded_query).order_by("_folded_name", "pk")
        people_rows = []
        for person in employees[:20]:
            unit_names = []
            if org_structure:
                for unit in org_structure.units_of(person):
                    names = [units_by_id[int(unit_id)].name for unit_id in unit.path.split("/") if unit_id
                             and int(unit_id) in units_by_id]
                    if names:
                        unit_names.append(" / ".join(names))
            people_rows.append({"value": f"p{person.pk}" if scope != "author" else str(person.pk),
                                "label": person.full_name, "name": person.full_name,
                                "unit": ", ".join(unit_names)})

        unit_rows = []
        if org_structure:
            for unit in units_by_id.values():
                unit_ids = [int(unit_id) for unit_id in unit.path.split("/") if unit_id]
                path_names = [units_by_id[unit_id].name for unit_id in unit_ids if unit_id in units_by_id]
                display_path = " / ".join(path_names)
                folded_path = display_path.lower().replace("ё", "е")
                if folded_query not in unit.name.lower().replace("ё", "е") and folded_query not in folded_path:
                    continue
                unit_rows.append({"value": f"u{unit.id}", "label": unit.name,
                                  "name": unit.name, "unit": display_path})
                if len(unit_rows) >= 20:
                    break

        person_index = unit_index = 0
        while len(rows) < 20 and (person_index < len(people_rows) or unit_index < len(unit_rows)):
            if person_index < len(people_rows):
                rows.append(people_rows[person_index])
                person_index += 1
            if len(rows) < 20 and unit_index < len(unit_rows):
                rows.append(unit_rows[unit_index])
                unit_index += 1
    return render(request, "feed/_picks.html", {"rows": rows})
