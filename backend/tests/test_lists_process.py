"""T-15010/T-15012: настройка процесса и стадий (FR-851…FR-858, FR-865; CONTRACT-015).

Служба `lists.services.process`: включение и повторное включение, автор, стадии, порядок, удаление,
права стадии, обязательные поля, скрытие поля. Представления — T-15011; проверка вкладки — e2e.
"""
import pytest
from django.core.exceptions import PermissionDenied

from apps.lists.services import process
from apps.lists.services.errors import ListsError
from tests import factories, support
from tests import support_lists as ll

pytestmark = pytest.mark.django_db


def make_process(lst, **extra):
    return support.model("lists.ListProcess").objects.create(list=lst, **extra)


def stage(lst, title, order, kind="open"):
    proc = process.get_process(lst) or make_process(lst)
    return support.model("lists.ProcessStage").objects.create(process=proc, title=title, order=order, kind=kind)


def test_ensure_requires_manage():
    lst = ll.make_list()
    reader = ll.as_reader(lst)
    with pytest.raises(PermissionDenied):
        process.ensure(lst, reader.user)
    manager = ll.as_manager()
    proc = process.ensure(lst, manager.user)
    assert proc.enabled is False
    assert proc.author is None


def test_save_settings_validates_schedule():
    lst = ll.make_list()
    manager = ll.as_manager()
    with pytest.raises(ListsError) as error:
        process.save_settings(lst, manager.user, launch_mode="schedule", period="weekly", weekday=None,
                              time_value="09:00")
    assert error.value.code == "stage_schedule_invalid"
    with pytest.raises(ListsError):
        process.save_settings(lst, manager.user, launch_mode="schedule", period="monthly", monthday=31,
                              time_value="09:00")
    proc = process.save_settings(lst, manager.user, title="Сверка", launch_mode="schedule", period="daily",
                                 time_value="09:00", template="Сверка — {дата}")
    assert proc.schedule_period == "daily"
    assert proc.schedule_time.strftime("%H:%M") == "09:00"
    assert process.process_title(proc, lst) == "Сверка"


def test_enable_requires_open_stage():
    lst = ll.make_list()
    manager = ll.as_manager()
    stage(lst, "Закрыта", 1, kind="closed")
    with pytest.raises(ListsError) as error:
        process.save_settings(lst, manager.user, enabled=True)
    assert error.value.code == "stage_last_open"


def test_enable_moves_only_stageless_records_and_bumps_version():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = stage(lst, "Новая", 1)
    second = stage(lst, "Закрыта", 2, kind="closed")
    fresh = ll.make_record(lst, title="Без стадии")
    archived = ll.make_record(lst, title="В архиве", archived=True)
    done = ll.make_record(lst, title="Завершена")
    done.stage = second
    done.save(update_fields=["stage"])
    proc = process.save_settings(lst, manager.user, enabled=True)
    fresh.refresh_from_db()
    archived.refresh_from_db()
    done.refresh_from_db()
    assert proc.enabled and proc.author == manager.user
    assert fresh.stage_id == first.pk
    assert fresh.version == 2
    assert archived.stage_id is None
    assert done.stage_id == second.pk


def test_reenable_keeps_stages_and_new_record_gets_first_open():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = stage(lst, "Новая", 1)
    old = ll.make_record(lst, title="Старая")
    process.save_settings(lst, manager.user, enabled=True)
    process.save_settings(lst, manager.user, enabled=False)
    while_disabled = ll.make_record(lst, title="Пока выключен")
    process.save_settings(lst, manager.user, enabled=True)
    old.refresh_from_db()
    while_disabled.refresh_from_db()
    assert old.stage_id == first.pk
    assert while_disabled.stage_id == first.pk


def test_enable_changes_author_on_reenable():
    lst = ll.make_list()
    first = ll.as_manager()
    stage(lst, "Новая", 1)
    process.save_settings(lst, first.user, enabled=True)
    assert process.get_process(lst).author == first.user
    second = ll.as_manager()
    process.save_settings(lst, second.user, enabled=False)
    process.save_settings(lst, second.user, enabled=True)
    assert process.get_process(lst).author == second.user


def test_stage_add_update_delete_and_order():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = process.add_stage(lst, manager.user, title="Новая")
    second = process.add_stage(lst, manager.user, title="Работа", kind="open")
    with pytest.raises(ListsError) as error:
        process.add_stage(lst, manager.user, title="новая")
    assert error.value.code == "stage_title_uniq"
    process.move_stage(second, "up", manager.user)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (second.order, first.order) == (1, 2)
    closed = process.add_stage(lst, manager.user, title="Закрыта", kind="closed")
    process.update_stage(second, manager.user, title="Работа", kind="closed")
    with pytest.raises(ListsError) as error:
        process.update_stage(first, manager.user, title="Новая", kind="closed")
    assert error.value.code == "stage_last_open"
    process.delete_stage(closed, manager.user)
    with pytest.raises(ListsError) as error:
        process.delete_stage(first, manager.user)
    assert error.value.code == "stage_last_open"
    extra = process.add_stage(lst, manager.user, title="Ещё открыта")
    process.delete_stage(first, manager.user)
    process.delete_stage(second, manager.user)
    with pytest.raises(ListsError):
        process.delete_stage(extra, manager.user)


def test_delete_stage_with_records_is_refused():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = process.add_stage(lst, manager.user, title="Новая")
    process.add_stage(lst, manager.user, title="Ещё", kind="open")
    record = ll.make_record(lst)
    record.stage = first
    record.save(update_fields=["stage"])
    with pytest.raises(ListsError) as error:
        process.delete_stage(first, manager.user)
    assert error.value.code == "stage_has_records"
    assert error.value.params["count"] == 1


def test_stage_access_narrow_and_fields():
    lst = ll.make_list()
    manager = ll.as_manager()
    first = process.add_stage(lst, manager.user, title="Новая")
    role = factories.make_role()
    with pytest.raises(ListsError) as error:
        process.save_stage_access(first, manager.user, narrow=True, read=(), edit=())
    assert error.value.code == "stage_access_empty"
    process.save_stage_access(first, manager.user, narrow=True, read=[f"role:{role.pk}"], edit=())
    Access = support.model("lists.ProcessStageAccess")
    assert Access.objects.filter(stage=first, level="read", role=role).exists()
    field = ll.add_field(lst, "string", "Обоснование")
    process.save_stage_fields(first, manager.user, [field.code])
    assert support.model("lists.ProcessStageField").objects.filter(stage=first, field=field).exists()
    process.hide_field(field, manager.user)
    assert not support.model("lists.ProcessStageField").objects.filter(stage=first, field=field).exists()


def test_process_tab_and_stage_pages():
    manager = ll.as_manager()
    lst = ll.make_list()
    url = f"/lists/{lst.pk}/settings/process/"
    page = manager.client.get(url)
    assert page.status_code == 200
    assert "Стадии" in page.content.decode()
    response = manager.client.post(url, {"title": "Закупки", "launch_mode": "manual"})
    assert response.status_code == 302
    assert process.get_process(lst) is not None
    new = manager.client.post(f"{url}stages/new/", {"title": "Новая", "kind": "open"})
    assert new.status_code == 302
    enabled = manager.client.post(url, {"title": "Закупки", "launch_mode": "manual", "enabled": "on"})
    assert enabled.status_code == 302
    first = process.visible_stages(lst)[0]
    page = manager.client.get(f"{url}stages/{first.pk}/")
    assert page.status_code == 200
    role = factories.make_role()
    field = ll.add_field(lst, "string", "Обоснование")
    saved = manager.client.post(f"{url}stages/{first.pk}/", {
        "title": "Новая", "kind": "open", "narrow": "on",
        "readers": [f"role:{role.pk}"], "fields": [field.code]})
    assert saved.status_code == 302
    assert support.model("lists.ProcessStageField").objects.filter(stage=first, field=field).exists()

    reader = ll.as_reader(lst)
    assert reader.client.get(url).status_code == 403
