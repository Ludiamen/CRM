"""Срез 009 «Задачи»: правило структуры `manages` (T-9102; FR-677, FR-678).

`tasks.services.access.manages(viewer, person)` — пересечение `managed_units(viewer)` с узлами человека
(CONTRACT-009, раздел 4). Заместитель равен руководителю, обычное членство прав не даёт, цепочка вышестоящих
покрывается `managed_units` предка. Код среза импортируется внутри тестов: сбор проходит до кода.
"""
import pytest

from tests import support, support_org

pytestmark = pytest.mark.django_db


def access():
    from apps.tasks.services import access as module
    return module


def _member(unit, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit)
    return user


def _marked(unit, mark, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit, mark=mark)
    return user


def test_manages_head_and_deputy_of_unit_and_all_nested():
    """FR-677, FR-678: руководитель и заместитель узла управляют сотрудниками своего узла и всех вложенных (на
    любую глубину); заместитель получает ровно те же права, что руководитель."""
    tree = support_org.make_tree({"Отдел": {"Группа": {"team:Дежурные": {}}}, "Чужой": {}})
    inside = _member(tree["Группа"])
    nested = _member(tree["Дежурные"])
    outside = _member(tree["Чужой"])
    head = _marked(tree["Отдел"], "head")
    deputy = _marked(tree["Отдел"], "deputy")
    for viewer in (head, deputy):
        assert access().manages(viewer, inside)
        assert access().manages(viewer, nested)
        assert not access().manages(viewer, outside)


def test_manages_ordinary_member_of_parent_does_not_manage_nested():
    """FR-677: рядовой участник вышестоящего узла не управляет вложенными; руководитель вложенного узла не
    управляет сотрудниками вышестоящего."""
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    nested = _member(tree["Группа"])
    above = _member(tree["Отдел"])
    low_head = _marked(tree["Группа"], "head")
    assert not access().manages(above, nested)
    assert not access().manages(low_head, above)


def test_manages_chain_of_superiors_covers_nested_units():
    """FR-677, FR-678: руководитель вышестоящего узла управляет по цепочке — сотрудник вложенного узла ему
    подчинён; перевод сотрудника в другой узел отнимает управление на момент просмотра."""
    tree = support_org.make_tree({"Направление": {"Отдел": {}}, "Другой": {}})
    employee = _member(tree["Отдел"])
    head = _marked(tree["Направление"], "head")
    assert access().manages(head, employee)
    support_org.make_member(employee, tree["Другой"])  # совместительство не отнимает прежний узел
    assert access().manages(head, employee)


def test_manages_dismissed_viewer_or_person_is_false():
    """FR-677, FR-678: уволенный не управляет ничем, даже если отметка руководителя осталась; уволенный
    сотрудник не состоит в узлах — управлять им нельзя."""
    tree = support_org.make_tree({"Отдел": {}})
    head = _marked(tree["Отдел"], "head", state="dismissed")
    employee = _member(tree["Отдел"])
    gone = _member(tree["Отдел"], state="dismissed")
    assert not access().manages(head, employee)
    assert not access().manages(employee, gone)


def test_managed_units_reexports_org_rule():
    """FR-677: `access.managed_units(viewer)` — та же функция структуры: узлы с отметкой и вложенные, без обычных
    членств (T-9003, CONTRACT-009 4)."""
    from apps.org.services import structure

    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    head = _marked(tree["Отдел"], "head")
    assert access().managed_units(head) == structure.managed_units(head) == frozenset(
        {tree["Отдел"].pk, tree["Группа"].pk})
    assert access().managed_units(_member(tree["Отдел"])) == frozenset()