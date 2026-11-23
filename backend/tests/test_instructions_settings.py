"""Срез 010 «Поручения»: настройки (T-10115; FR-701, 709, NFR-729).

`apps.instructions.services.settings` и `/settings/instructions/` — CONTRACT-010, 6.2, 10.1. Код среза импортируется
внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
DEFAULT_LADDER = {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}


def settings_service():
    from apps.instructions.services import settings as module
    return module


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def test_get_returns_single_row_with_defaults():
    """NFR-729: настройки — одна строка `pk=1`; по умолчанию срок хранения 3 года и лестница `[30,14,7,3,1]`."""
    row = settings_service().get()
    assert row.pk == 1 and row.retention_years == 3
    assert row.default_ladder == DEFAULT_LADDER
    assert settings_service().get().pk == row.pk


def test_save_retention_writes_audit_and_checks_range():
    """NFR-729: срок хранения 1–10; смена пишется в журнал `instructions.retention_changed` «было / стало»."""
    actor = support.make_admin()
    row = settings_service().save(actor, retention_years=6)
    assert row.retention_years == 6
    event = support.model("core.AuditEvent").objects.get(action="instructions.retention_changed")
    assert event.before["years"] == 3 and event.after["years"] == 6

    for value in (0, 11):
        err = _err(lambda value=value: settings_service().save(actor, retention_years=value))
        assert (err.code, err.field) == ("retention_range", "retention_years")


def test_save_default_ladder_and_invalid():
    """FR-709: умолчание лестницы сохраняется 1–60 без повторов; иное — `ladder_invalid`."""
    actor = support.make_admin()
    row = settings_service().save(actor, default_ladder={"offsets": [2, 10], "due": False, "overdue": True})
    assert row.default_ladder == {"offsets": [2, 10], "due": False, "overdue": True}
    for ladder in ({"offsets": [0], "due": True, "overdue": True},
                   {"offsets": [5, 5], "due": True, "overdue": True}):
        err = _err(lambda ladder=ladder: settings_service().save(actor, default_ladder=ladder))
        assert (err.code, err.field) == ("ladder_invalid", "ladder")


def test_page_admin_only_and_renders_field(client):
    """CONTRACT-010, 6.2: страница настроек под `settings.portal`; поле срока и лестница; рядовому — 403."""
    support.login(client, support.make_admin())
    page = client.get("/settings/instructions/")
    html = page.content.decode()
    assert page.status_code == 200 and 'data-instructions-page="settings"' in html
    assert 'data-instruction-field="retention_years"' in html
    assert "Хранить поручения, лет" in html

    staff_client = support.logged_in(ins.staff_user())
    assert staff_client.get("/settings/instructions/").status_code == 403
    assert staff_client.post("/settings/instructions/", {"retention_years": 5}).status_code == 403


def test_page_saves_retention_and_shows_range_error(client):
    """CONTRACT-010, 6.2: сохранение — 302; вне 1–10 — 200 с `[data-error="retention_years"]`."""
    support.login(client, support.make_admin())
    saved = client.post("/settings/instructions/", {"retention_years": 5})
    assert saved.status_code == 302
    assert support.model("instructions.InstructionSettings").objects.get(pk=1).retention_years == 5

    bad = client.post("/settings/instructions/", {"retention_years": 0})
    assert bad.status_code == 200
    assert b'data-error="retention_years"' in bad.content and b'data-code="retention_range"' in bad.content


def test_decrease_requires_second_step_with_count(client):
    """NFR-729: уменьшение срока хранения показывает число поручений к уборке; без `confirm` — второй шаг,
    с `confirm=1` — сохранение."""
    actor = support.make_admin()
    old = ins.make_instruction(title="Старое поручение", author=actor, controller=actor, assignee=actor)
    old.closed_at = datetime.datetime(2021, 1, 5, 12, 0, tzinfo=MSK)
    old.save(update_fields=["closed_at"])

    support.login(client, actor)
    first = client.post("/settings/instructions/", {"retention_years": 2})
    html = first.content.decode()
    assert first.status_code == 200 and "data-instructions-confirm" in html
    assert "Ближайшая уборка удалит поручений: 1" in html

    second = client.post("/settings/instructions/", {"retention_years": 2, "confirm": "1"})
    assert second.status_code == 302
    assert support.model("instructions.InstructionSettings").objects.get(pk=1).retention_years == 2