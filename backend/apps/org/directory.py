"""Точка ядра `staff_directory`: дополнения списка «Сотрудники» (PLAN-002, «Список „Сотрудники“ и поиск»; FR-130, FR-131)."""
from django.db.models import Exists, Func, OuterRef, Q, Value
from django.db.models.functions import Lower

from apps.core import extensions
from apps.core.models import UserState
from apps.org.models import Membership, Unit


def _no_unit(qs):
    """«Без подразделения»: не уволенные записи без единого членства."""
    return qs.exclude(state=UserState.DISMISSED).exclude(
        Exists(Membership.objects.filter(user_id=OuterRef("pk"))))


def _unit_choices() -> list[tuple[str, str]]:
    """Все узлы в порядке дерева; вложенность показана отступом."""
    return [(str(unit.pk), " " * unit.depth + unit.name) for unit in Unit.objects.order_by("path")]


def _unit_filter(qs, value: str):
    """Члены узла и всех вложенных (путь начинается с пути узла); неизвестный узел — пусто."""
    try:
        unit = Unit.objects.filter(pk=int(value)).first()
    except (TypeError, ValueError):
        return qs.none()
    if unit is None:
        return qs.none()
    return qs.filter(pk__in=Membership.objects.filter(unit__path__startswith=unit.path).values("user_id"))


def _unit_search(text: str) -> Q:
    """Условие `Exists` по названиям узлов человека; `text` уже приведён (нижний регистр, «ё» -> «е»)."""
    names = (Membership.objects.filter(user_id=OuterRef("pk"))
             .annotate(_unit=Func(Lower("unit__name"), Value("ё"), Value("е"), function="translate"))
             .filter(_unit__contains=text))
    return Q(Exists(names))


def staff_directory(viewer) -> extensions.StaffDirectory:
    """Пресет «Без подразделения», фильтр «Подразделение», поиск по узлам, колонка и кнопка загрузки."""
    return extensions.StaffDirectory(
        presets=[extensions.Preset("no_unit", "Без подразделения", _no_unit, 30)],
        filters=[extensions.Filter("unit", "Подразделение", _unit_choices, _unit_filter)],
        search=_unit_search,
        columns=[extensions.Column("unit", "Подразделение", "org/_staff_unit_cell.html", 30)],
        buttons=[extensions.Button("Загрузить из таблицы", "/structure/import/", ("accounts.manage", "org.manage"),
                                   "staff-import")],
    )
