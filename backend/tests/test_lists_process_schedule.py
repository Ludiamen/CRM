"""T-15040/T-15041: плановый запуск (FR-875…FR-878; CONTRACT-015, раздел 7)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.lists.services import process, schedule
from tests import support
from tests import support_lists as ll

pytestmark = pytest.mark.django_db
MOSCOW = ZoneInfo("Europe/Moscow")


def prepare(*, template="", enabled=True):
    lst = ll.make_list()
    manager = ll.as_manager()
    process.add_stage(lst, manager.user, title="Новая")
    process.save_settings(lst, manager.user, title="Сверка", launch_mode="schedule", period="daily",
                          time_value="09:00", template=template, enabled=enabled)
    return lst, manager


def at(day=1, hour=10):
    return datetime(2026, 12, day, hour, 0, tzinfo=MOSCOW)


def test_due_daily_before_and_after_time():
    lst, manager = prepare()
    proc = process.get_process(lst)
    assert schedule.due(proc, at(hour=8)) is None
    found = schedule.due(proc, at(hour=10))
    assert found is not None and found[0].isoformat() == "2026-12-01"


def test_tick_creates_one_record_per_period():
    lst, manager = prepare(template="Сверка — {дата}")
    result = schedule.tick(at())
    assert result["created"] == 1
    Record = support.model("lists.Record")
    records = list(Record.objects.filter(list=lst))
    assert len(records) == 1
    assert records[0].title == "Сверка — 01.12.2026"
    assert records[0].stage_id is not None
    assert support.model("lists.ProcessLaunch").objects.get(process__list=lst).status == "created"
    again = schedule.tick(at())
    assert again["created"] == 0
    assert Record.objects.filter(list=lst).count() == 1


def test_disabled_process_is_skipped():
    lst, manager = prepare(enabled=False)
    result = schedule.tick(at())
    assert result["skipped"] == 1
    assert not support.model("lists.Record").objects.filter(list=lst).exists()
    launch = support.model("lists.ProcessLaunch").objects.get(process__list=lst)
    assert launch.status == "skipped" and "выключен" in launch.reason


def test_required_field_without_default_is_skipped():
    lst, manager = prepare()
    field = ll.add_field(lst, "string", "Обоснование")
    stage = process.visible_stages(lst)[0]
    support.model("lists.ProcessStageField").objects.create(stage=stage, field=field)
    result = schedule.tick(at())
    assert result["skipped"] == 1
    assert not support.model("lists.Record").objects.filter(list=lst).exists()
    launch = support.model("lists.ProcessLaunch").objects.get(process__list=lst)
    assert launch.status == "skipped" and "обязательные" in launch.reason
