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


def test_grid_and_direct_views_hide_unreadable_stage():
    lst = ll.make_list()
    process = make_process(lst)
    hidden_stage = make_stage(process, "Скрыта", 1)
    visible_stage = make_stage(process, "Открыта", 2)
    allow(hidden_stage, factories.make_role(), "read")
    hidden = record_at(lst, hidden_stage, "Скрытая запись")
    visible = record_at(lst, visible_stage, "Видимая запись")
    reader = ll.as_reader(lst)
    page = reader.client.get(f"/lists/{lst.pk}/")
    body = page.content.decode()
    assert page.status_code == 200
    assert "Видимая запись" in body
    assert "Скрытая запись" not in body
    assert reader.client.get(f"/lists/{lst.pk}/{hidden.number}/").status_code == 404
    assert reader.client.get(f"/lists/{lst.pk}/{hidden.number}/history/").status_code == 404
    assert reader.client.get(f"/lists/{lst.pk}/{visible.number}/").status_code == 200


def test_stage_filter_does_not_list_unreadable_stage():
    lst = ll.make_list()
    process = make_process(lst)
    hidden = make_stage(process, "Секретная стадия", 1)
    allow(hidden, factories.make_role(), "read")
    reader = ll.as_reader(lst)
    body = reader.client.get(f"/lists/{lst.pk}/").content.decode()
    assert "Секретная стадия" not in body


def test_legacy_history_without_ids_is_masked():
    from apps.lists.services import history as history_service

    lst = ll.make_list()
    target_list = ll.make_list()
    process = make_process(target_list)
    hidden_stage = make_stage(process, "Скрыта", 1)
    allow(hidden_stage, factories.make_role(), "read")
    hidden = record_at(target_list, hidden_stage, "Секретная цель")
    field = ll.add_field(lst, "record", "Ссылка", target=target_list)
    record = ll.make_record(lst, values={field.code: [hidden.pk]})
    role = factories.make_role()
    ll.grant_list(target_list, role, "read")
    reader = ll.as_reader(lst)
    reader.user.roles.add(role)
    from apps.core.services import permissions
    from django.core.cache import cache

    cache.delete(permissions._key(reader.user.pk))
    history_service.write(record, "changed", [{"field": field.code, "name": field.name,
                                                "before": "Секретная цель — №1", "after": ""}], record.updated_by)
    rows = list(support.model("lists.Change").objects.filter(record=record))
    shown = history_service.for_viewer(rows, lst, reader.user)
    assert shown[0].changes[0]["before"] == "запись недоступного списка"
