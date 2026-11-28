"""T-15021/T-15024: переход по стадиям (FR-863, FR-867…FR-874; CONTRACT-015, раздел 5)."""
import pytest
from django.http import Http404

from apps.lists.services import process, transitions
from apps.lists.services.errors import (StageChanged, StageForbidden, StageRequired, VersionConflict)
from tests import factories, support
from tests import support_lists as ll

pytestmark = pytest.mark.django_db


def setup_list(*titles, **kwargs):
    lst = ll.make_list()
    manager = ll.as_manager()
    proc = process.ensure(lst, manager.user)
    proc.enabled = True
    proc.save(update_fields=["enabled"])
    stages = [support.model("lists.ProcessStage").objects.create(process=proc, title=title, order=index + 1)
              for index, title in enumerate(titles)]
    return lst, manager, proc, stages


def place(record, stage):
    record.stage = stage
    record.save(update_fields=["stage"])
    return record


def test_move_updates_stage_version_history_and_journal():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = place(ll.make_record(lst), first)
    result = transitions.move(record, second, base_version=record.version, expected_stage=first.pk,
                              actor=manager.user)
    record.refresh_from_db()
    assert result.repeated is False
    assert record.stage_id == second.pk
    assert record.version == 2
    change = support.model("lists.Change").objects.filter(record=record, kind="stage").get()
    assert change.changes[0]["before"] == "Новая"
    assert change.changes[0]["after"] == "Работа"
    move = support.model("lists.StageMove").objects.get(record=record)
    assert move.to_stage_key == second.pk
    assert support.model("core.AuditEvent").objects.filter(action="lists.record_stage_changed").exists()


def test_repeat_returns_saved_result_without_second_history():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = place(ll.make_record(lst), first)
    transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)
    again = transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)
    assert again.repeated is True
    assert support.model("lists.Change").objects.filter(record=record, kind="stage").count() == 1


def test_other_target_from_stale_version_conflicts():
    lst, manager, proc, (first, second, third) = setup_list("Новая", "Работа", "Готово")
    record = place(ll.make_record(lst), first)
    transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)
    with pytest.raises(VersionConflict):
        transitions.move(record, third, base_version=1, expected_stage=first.pk, actor=manager.user)


def test_same_stage_is_noop():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = place(ll.make_record(lst), first)
    result = transitions.move(record, first, base_version=1, expected_stage=first.pk, actor=manager.user)
    assert result.repeated is True
    assert not support.model("lists.StageMove").objects.filter(record=record).exists()


def test_stage_changed():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = place(ll.make_record(lst), first)
    with pytest.raises(StageChanged):
        transitions.move(record, second, base_version=1, expected_stage=second.pk, actor=manager.user)


def test_reader_cannot_move():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = place(ll.make_record(lst), first)
    reader = ll.as_reader(lst)
    with pytest.raises(StageForbidden):
        transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=reader.user)


def test_unreadable_target_forbidden():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = place(ll.make_record(lst), first)
    role = factories.make_role()
    support.model("lists.ProcessStageAccess").objects.create(stage=first, level="edit", role=role)
    support.model("lists.ProcessStageAccess").objects.create(stage=second, level="read", role=factories.make_role())
    user = support.make_employee(roles=[role])
    ll.grant_list(lst, role, "edit")
    with pytest.raises(StageForbidden):
        transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=user)


def test_target_required_field_and_effective_state():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    field = ll.add_field(lst, "string", "Обоснование")
    support.model("lists.ProcessStageField").objects.create(stage=second, field=field)
    record = place(ll.make_record(lst), first)
    with pytest.raises(StageRequired):
        transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)
    record.values = {field.code: "нужно"}
    record.save(update_fields=["values"])
    transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)
    record.refresh_from_db()
    assert record.stage_id == second.pk


def test_explicit_clear_of_required_field_is_refused():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    field = ll.add_field(lst, "string", "Обоснование")
    support.model("lists.ProcessStageField").objects.create(stage=first, field=field)
    record = place(ll.make_record(lst, values={field.code: "было"}), first)
    with pytest.raises(StageRequired):
        transitions.move(record, second, base_version=1, expected_stage=first.pk,
                         values={field.code: ""}, actor=manager.user)


def test_required_file_must_exist():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    field = ll.add_field(lst, "file", "Договор")
    support.model("lists.ProcessStageField").objects.create(stage=second, field=field)
    record = place(ll.make_record(lst), first)
    with pytest.raises(StageRequired):
        transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)
    ll.attach_file(record, field)
    transitions.move(record, second, base_version=1, expected_stage=first.pk, actor=manager.user)


def test_move_from_no_stage_and_repeat_after_target_deleted():
    lst, manager, proc, (first, second) = setup_list("Новая", "Работа")
    record = ll.make_record(lst)
    result = transitions.move(record, first, base_version=1, expected_stage=None, actor=manager.user)
    assert result.repeated is False
    move = support.model("lists.StageMove").objects.get(record=record)
    assert move.from_stage_key is None
    assert support.model("lists.Change").objects.get(record=record, kind="stage").changes[0]["before"] == "Без стадии"
    transitions.move(record, second, base_version=2, expected_stage=first.pk, actor=manager.user)
    process.delete_stage(first, manager.user)
    again = transitions.move(record, first, base_version=1, expected_stage=None, actor=manager.user)
    assert again.repeated is True
