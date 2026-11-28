"""T-15005: права стадии (FR-859…FR-864, FR-888; CONTRACT-015, раздел 4).

Проверяются только службы `lists.services.access`: формула сужения, пустой набор, роли, цепочка узлов,
управляющий, выключенный процесс, запись без стадии. Представления и шаблоны — T-15020.
"""
import pytest

from apps.lists.services import access
from tests import factories, support
from tests import support_lists as ll
from tests import support_org as org

pytestmark = pytest.mark.django_db


def make_process(lst, *, enabled=True):
    return support.model("lists.ListProcess").objects.create(list=lst, enabled=enabled, title="Процесс")


def make_stage(process, title, order, *, kind="open"):
    return support.model("lists.ProcessStage").objects.create(
        process=process, title=title, order=order, kind=kind)


def allow(stage, who, level):
    Access = support.model("lists.ProcessStageAccess")
    if who._meta.label_lower == "core.role":
        return Access.objects.create(stage=stage, level=level, role=who)
    return Access.objects.create(stage=stage, level=level, unit_id=who.pk)


def record_at(lst, stage, title="Запись"):
    record = ll.make_record(lst, title=title)
    record.stage = stage
    record.save(update_fields=["stage"])
    return record


def test_stage_scope_none_for_manager_and_disabled_process():
    lst = ll.make_list()
    process = make_process(lst, enabled=False)
    make_stage(process, "Новая", 1)
    manager = ll.as_manager()
    assert access.stage_scope(manager.user, lst) is None
    reader = ll.as_reader(lst)
    assert access.stage_scope(reader.user, lst) is None


def test_empty_stage_access_inherits_list_rights():
    lst = ll.make_list()
    process = make_process(lst)
    first = make_stage(process, "Новая", 1)
    second = make_stage(process, "Закрыта", 2, kind="closed")
    record = record_at(lst, first)
    reader = ll.as_reader(lst)
    assert access.stage_scope(reader.user, lst).read == {first.pk, second.pk}
    assert access.stage_scope(reader.user, lst).edit == {first.pk, second.pk}
    assert access.can_read_record(reader.user, record)
    assert not access.can_edit_record(reader.user, record)
    editor = ll.as_editor(lst)
    assert access.can_edit_record(editor.user, record)


def test_stage_read_role_narrows_read_but_not_edit():
    lst = ll.make_list()
    process = make_process(lst)
    first = make_stage(process, "Новая", 1)
    second = make_stage(process, "Согласование", 2)
    role = factories.make_role()
    allow(second, role, "read")
    allow(first, factories.make_role(), "read")
    user = support.make_employee(roles=[role])
    ll.grant_list(lst, role, "edit")
    hidden = record_at(lst, first)
    visible = record_at(lst, second)
    scope = access.stage_scope(user, lst)
    assert scope.read == {second.pk}
    assert scope.edit == frozenset()
    assert not access.can_read_record(user, hidden)
    assert access.can_read_record(user, visible)
    assert not access.can_edit_record(user, visible)


def test_stage_edit_role_allows_read_and_edit():
    lst = ll.make_list()
    process = make_process(lst)
    first = make_stage(process, "Новая", 1)
    role = factories.make_role()
    allow(first, role, "edit")
    user = support.make_employee(roles=[role])
    ll.grant_list(lst, role, "edit")
    record = record_at(lst, first)
    assert access.can_read_record(user, record)
    assert access.can_edit_record(user, record)


def test_stage_access_cannot_widen_list_access():
    lst = ll.make_list()
    process = make_process(lst)
    first = make_stage(process, "Новая", 1)
    role = factories.make_role()
    allow(first, role, "edit")
    user = support.make_employee(roles=[role])
    record = record_at(lst, first)
    assert not access.can_read_record(user, record)
    assert not access.can_edit_record(user, record)


def test_unit_chain_includes_parent_units():
    parent = org.make_unit()
    child = org.make_unit(parent=parent)
    lst = ll.make_list()
    process = make_process(lst)
    first = make_stage(process, "Новая", 1)
    allow(first, parent, "read")
    user = support.make_employee()
    org.make_member(user, child)
    ll.grant_list(lst, parent, "read")
    record = record_at(lst, first)
    assert access.can_read_record(user, record)


def test_record_without_stage_uses_list_rights():
    lst = ll.make_list()
    make_process(lst)
    record = ll.make_record(lst)
    reader = ll.as_reader(lst)
    assert access.can_read_record(reader.user, record)
    assert not access.can_edit_record(reader.user, record)


def test_record_condition_filters_hidden_stage():
    lst = ll.make_list()
    process = make_process(lst)
    first = make_stage(process, "Новая", 1)
    second = make_stage(process, "Скрыта", 2)
    role = factories.make_role()
    allow(second, role, "read")
    allow(first, factories.make_role(), "read")
    user = support.make_employee(roles=[role])
    ll.grant_list(lst, role, "read")
    hidden = record_at(lst, first)
    visible = record_at(lst, second)
    plain = ll.make_record(lst)
    Record = support.model("lists.Record")
    found = set(Record.objects.filter(list=lst).filter(access.record_condition(user, lst)).values_list("pk", flat=True))
    assert found == {visible.pk, plain.pk}
    assert hidden.pk not in found
