"""T-15022: обязательные поля, файлы и восстановление (FR-867…FR-870, FR-865; CONTRACT-015, раздел 6)."""
import pytest
from django.core.exceptions import PermissionDenied

from apps.lists.services import archive, files, process
from apps.lists.services.errors import StageRequired
from tests import factories, support
from tests import support_lists as ll

pytestmark = pytest.mark.django_db


def prepare(*titles):
    lst = ll.make_list()
    manager = ll.as_manager()
    stages = [process.add_stage(lst, manager.user, title=title) for title in titles]
    process.save_settings(lst, manager.user, enabled=True)
    return lst, manager, stages


def test_delete_last_required_file_is_refused():
    lst, manager, (first, second) = prepare("Новая", "Работа")
    field = ll.add_field(lst, "file", "Договор")
    support.model("lists.ProcessStageField").objects.create(stage=second, field=field)
    record = ll.make_record(lst)
    record.stage = second
    record.save(update_fields=["stage"])
    attached = ll.attach_file(record, field)
    with pytest.raises(StageRequired):
        files.remove(lst, record.number, attached.pk, actor=manager.user)
    second_file = ll.attach_file(record, field, name="второй.pdf")
    files.remove(lst, record.number, attached.pk, actor=manager.user)
    assert support.model("lists.RecordFile").objects.filter(record=record).count() == 1
    assert second_file.pk


def test_reader_cannot_attach_file():
    lst, manager, (first, second) = prepare("Новая", "Работа")
    field = ll.add_field(lst, "file", "Договор")
    record = ll.make_record(lst)
    record.stage = first
    record.save(update_fields=["stage"])
    reader = ll.as_reader(lst)
    from django.core.files.uploadedfile import SimpleUploadedFile

    with pytest.raises(PermissionDenied):
        files.attach(lst, record.number, field_code=field.code, name="a.pdf", data=b"pdf", actor=reader.user)


def test_restore_sets_first_open_stage():
    lst, manager, (first, second) = prepare("Новая", "Работа")
    record = ll.make_record(lst, archived=True)
    restored = archive.restore(lst, record.number, actor=manager.user)
    assert restored.stage_id == first.pk
    assert restored.version == 2


def test_hidden_stage_file_is_not_downloadable():
    lst, manager, (first, second) = prepare("Новая", "Работа")
    support.model("lists.ProcessStageAccess").objects.create(
        stage=second, level="read", role=factories.make_role())
    field = ll.add_field(lst, "file", "Договор")
    record = ll.make_record(lst)
    record.stage = second
    record.save(update_fields=["stage"])
    item = ll.attach_file(record, field)
    reader = ll.as_reader(lst)
    assert reader.client.get(f"/lists/{lst.pk}/{record.number}/files/{item.pk}/").status_code == 404


def test_save_cannot_clear_required_stage_field():
    lst, manager, (first, second) = prepare("Новая", "Работа")
    field = ll.add_field(lst, "string", "Обоснование")
    support.model("lists.ProcessStageField").objects.create(stage=first, field=field)
    record = ll.make_record(lst, values={field.code: "было"})
    record.stage = first
    record.save(update_fields=["stage"])
    from apps.lists.services import records
    from apps.lists.services.errors import ValuesInvalid

    with pytest.raises(ValuesInvalid) as error:
        records.save(lst, record.number, {"title": record.title, field.code: ""},
                     base_version=record.version, actor=manager.user)
    assert field.code in error.value.errors


def test_disabled_process_does_not_block_file_delete():
    lst, manager, (first, second) = prepare("Новая", "Работа")
    field = ll.add_field(lst, "file", "Договор")
    support.model("lists.ProcessStageField").objects.create(stage=first, field=field)
    record = ll.make_record(lst)
    record.stage = first
    record.save(update_fields=["stage"])
    item = ll.attach_file(record, field)
    process.save_settings(lst, manager.user, enabled=False)
    files.remove(lst, record.number, item.pk, actor=manager.user)
    assert not support.model("lists.RecordFile").objects.filter(record=record).exists()
