"""Срез 010 «Поручения»: напоминания (T-10108; FR-709, 710, 711, NFR-724).

`apps.instructions.services.reminders` и задание `instructions_reminders` — CONTRACT-010, раздел 8, К5, К22.
Тесты зовут задание синхронно с `now=…`; код среза импортируется внутри тестов, чтобы сбор проходил до появления
моделей и служб.
"""
import datetime
from datetime import time
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache

from tests import support
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime.datetime(2026, 11, 22, 12, 0, tzinfo=MSK)  # воскресенье


# --- помощники -----------------------------------------------------------------------------------

def reminders():
    from apps.instructions.services import reminders as module
    return module


def _job(now):
    from apps.instructions.tasks import instructions_reminders

    return instructions_reminders(now=now)


def _instr(created_on, deadline, **extra):
    row = ins.make_instruction(deadline=deadline, **extra)
    support.model("instructions.Instruction").objects.filter(pk=row.pk).update(
        created_at=datetime.datetime.combine(created_on, datetime.time(10), tzinfo=MSK))
    row.refresh_from_db()
    return row


def _stages(row):
    return {item.stage for item in ins.reminders_of(row)}


def _by_stage(row):
    return {item.stage: item for item in ins.reminders_of(row)}


def _pending(row):
    return [item for item in ins.reminders_of(row) if item.state == "pending"]


def _audit(code):
    return list(support.model("core.AuditEvent").objects.filter(action=code).order_by("id"))


def _notes(user=None, kind=None):
    rows = support.model("notify.Notification").objects.filter(kind__startswith="instructions.")
    if user is not None:
        rows = rows.filter(user=user)
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _prefs(user, **fields):
    row, _ = support.model("notify.UserNotifySettings").objects.update_or_create(user=user, defaults=fields)
    return row


def _at(day, hour=9):
    return datetime.datetime.combine(day, time(hour, 0), tzinfo=MSK)


# --- лестница по длине срока ---------------------------------------------------------------------

def test_short_deadline_has_d3_d1_due_and_overdue_only():
    """FR-709: срок не больше месяца — за 3 и 1 рабочий день, начало дня срока и следующий рабочий день; более
    ранних порогов нет."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().plan(row)
    assert _stages(row) == {"d3", "d1", "due", "overdue"}
    by_stage = _by_stage(row)
    assert by_stage["d3"].moment == _at(datetime.date(2026, 1, 15))
    assert by_stage["d1"].moment == _at(datetime.date(2026, 1, 19))
    assert by_stage["due"].moment == _at(datetime.date(2026, 1, 20))
    assert by_stage["overdue"].moment == _at(datetime.date(2026, 1, 21))


def test_mid_deadline_adds_d14_and_d7():
    """FR-709: больше месяца и не больше полугода — ещё за 14 и 7 рабочих дней."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 4, 6))
    reminders().plan(row)
    assert _stages(row) == {"d14", "d7", "d3", "d1", "due", "overdue"}


def test_long_deadline_adds_d30():
    """FR-709: больше полугода — ещё за 30 рабочих дней."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 10, 5))
    reminders().plan(row)
    assert _stages(row) == {"d30", "d14", "d7", "d3", "d1", "due", "overdue"}
    assert _by_stage(row)["d30"].moment == _at(datetime.date(2026, 8, 24))


def test_month_and_half_year_boundaries_are_inclusive():
    """FR-709, К11: ровно месяц — короткая лестница; ровно полгода — средняя; на день больше — длинная."""
    month = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 2, 5))
    reminders().plan(month)
    assert _stages(month) == {"d3", "d1", "due", "overdue"}

    half = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 7, 5))
    reminders().plan(half)
    assert _stages(half) == {"d14", "d7", "d3", "d1", "due", "overdue"}

    over = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 7, 6))
    reminders().plan(over)
    assert "d30" in _stages(over)


def test_past_thresholds_are_not_created():
    """FR-709: прошедшие пороги при создании не создаются — остаются только будущие."""
    today = ins._today()
    row = _instr(today - datetime.timedelta(days=30), today + datetime.timedelta(days=1))
    reminders().plan(row)
    assert _stages(row) == {"due", "overdue"}


def test_recipients_assignee_and_coexecutors_without_author():
    """FR-709, FR-704: напоминания получают исполнитель и соисполнители, постановщик — нет; строки не
    дублируются."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    coexecutor = ins.staff_user()
    ins.add_coexecutor(row, coexecutor)
    reminders().plan(row)
    for stage in ("d3", "d1", "due", "overdue"):
        users = [item.user_id for item in ins.reminders_of(row) if item.stage == stage]
        assert sorted(users) == sorted([row.assignee_id, coexecutor.pk]), stage
    assert row.author_id not in {item.user_id for item in ins.reminders_of(row)}


def test_report_dates_get_r3_and_r1():
    """FR-709: о каждой отчётной дате — за 3 и 1 рабочий день; это вид `report`, а не срок."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 3, 2))
    due = ins.add_report_date(row, datetime.date(2026, 1, 19))  # понедельник
    reminders().plan(row)
    mine = [item for item in ins.reminders_of(row) if item.kind == "report" and item.date_id == due.pk]
    by_stage = {item.stage: item for item in mine}
    assert set(by_stage) == {"r3", "r1"}
    assert by_stage["r1"].moment == _at(datetime.date(2026, 1, 16))
    assert by_stage["r3"].moment == _at(datetime.date(2026, 1, 14))


# --- своя лестница и умолчание -------------------------------------------------------------------

def test_custom_ladder_offsets_become_d_stages():
    """FR-709, К22: своя лестница `[5, 2]` даёт пороги `d5` и `d2`; `due`/`overdue` — по флагам."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().set_ladder(row.author, row, {"offsets": [5, 2], "due": True, "overdue": False})
    reminders().plan(row)
    assert _stages(row) == {"d5", "d2", "due"}


def test_empty_ladder_uses_settings_default():
    """FR-709, NFR-729: пустая лестница — умолчание настроек `[30, 14, 7, 3, 1]`; короткий срок берёт только
    применимые пороги."""
    support.model("instructions.InstructionSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": 3,
                        "default_ladder": {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}})
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().plan(row)
    assert _stages(row) == {"d3", "d1", "due", "overdue"}


def test_ladder_invalid_rejects_bad_offsets():
    """FR-709: пороги — 1–60, по возрастанию, без повторов; иное — `ladder_invalid` у поля `ladder`."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    for ladder in ({"offsets": [0], "due": True, "overdue": True},
                   {"offsets": [61], "due": True, "overdue": True},
                   {"offsets": [5, 5], "due": True, "overdue": True},
                   {"offsets": [5, 3], "due": True, "overdue": True},
                   {"offsets": ["5"], "due": True, "overdue": True}):
        from apps.instructions.texts import InstructionsError

        with pytest.raises(InstructionsError) as caught:
            reminders().set_ladder(row.author, row, ladder)
        assert (caught.value.code, caught.value.field) == ("ladder_invalid", "ladder")


def test_ladder_edit_touches_only_future_pending_not_sent():
    """FR-709: правка лестницы пересчитывает только будущие `pending`; отправленные строки не трогаются."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 10, 5))
    reminders().plan(row)
    sent = _by_stage(row)["d3"]
    sent.state = "sent"
    sent.save(update_fields=["state"])
    sent_moment = sent.moment

    reminders().set_ladder(row.author, row, {"offsets": [5, 2], "due": True, "overdue": True})
    stages = _stages(row)
    assert {"d5", "d2", "due", "overdue"} <= stages
    assert not ({"d30", "d14", "d7"} & stages), f"старые пороги остались: {stages}"
    again = support.model("instructions.InstructionReminder").objects.get(pk=sent.pk)
    assert (again.state, again.moment) == ("sent", sent_moment)


# --- тихие часы и None ---------------------------------------------------------------------------

def test_plan_shifts_moments_by_personal_quiet_hours():
    """FR-710: момент каждого порога сдвигается `quiet.next_start` по личным настройкам получателя («свои часы»
    10:00–19:00 дают 10:00 вместо 09:00)."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    _prefs(row.assignee, quiet_mode="own", own_days=[0, 1, 2, 3, 4],
           own_start=time(10, 0), own_end=time(19, 0))
    reminders().plan(row)
    due = _by_stage(row)["due"]
    assert due.moment == _at(datetime.date(2026, 1, 20), hour=10)


def test_quiet_none_keeps_pending_then_cancels_with_audit(monkeypatch):
    """FR-710, NFR-724: первый `None` от тихих часов оставляет `pending` до следующего цикла; повторный —
    отмена с журналом `instructions.reminder_failed`; поручение не ломается."""
    cache.clear()
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().plan(row)
    monkeypatch.setattr("apps.instructions.tasks.quiet.next_start", lambda prefs, moment: None)
    due = _at(datetime.date(2026, 1, 15), hour=10)  # d3 созрело

    assert _job(due) == 0
    d3 = _by_stage(row)["d3"]
    assert support.model("instructions.InstructionReminder").objects.get(pk=d3.pk).state == "pending"
    assert _audit("instructions.reminder_failed") == []

    _job(due + datetime.timedelta(minutes=5))
    assert support.model("instructions.InstructionReminder").objects.get(pk=d3.pk).state == "cancelled"
    failed = _audit("instructions.reminder_failed")
    assert len(failed) == 1 and failed[0].object_id == str(row.pk)
    assert support.model("instructions.Instruction").objects.filter(pk=row.pk).exists()


# --- задание: отправка и идемпотентность ---------------------------------------------------------

def test_job_sends_due_reminders_once():
    """NFR-724: задание отправляет созревшие `pending` и помечает `sent`; повторный запуск не создаёт дублей и
    возвращает 0."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().plan(row)
    now = _at(datetime.date(2026, 1, 20), hour=10)
    first = _job(now)
    assert first >= 1
    assert not _pending(row)
    assert {item.state for item in ins.reminders_of(row)} == {"sent"}
    notes = _notes(row.assignee, "instructions.deadline").count()
    assert notes >= 1

    second = _job(now)
    assert second == 0
    assert _notes(row.assignee, "instructions.deadline").count() == notes


def test_overdue_reminder_goes_next_working_day():
    """FR-709: просрочка — следующий рабочий день после срока; уведомление вида `instructions.overdue`."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().plan(row)
    _job(_at(datetime.date(2026, 1, 20), hour=10))
    assert not _notes(row.assignee, "instructions.overdue").exists()
    _job(_at(datetime.date(2026, 1, 21), hour=10))
    assert _notes(row.assignee, "instructions.overdue").exists()


def test_deadline_change_rebuilds_pending_and_keeps_sent():
    """FR-709: смена срока пересчитывает будущие `pending`; отправленное напоминание не меняется."""
    row = _instr(datetime.date(2026, 1, 5), datetime.date(2026, 1, 20))
    reminders().plan(row)
    sent = _by_stage(row)["d1"]
    sent.state = "sent"
    sent.save(update_fields=["state"])
    sent_moment = sent.moment

    row.deadline = datetime.date(2026, 1, 27)
    row.save(update_fields=["deadline"])
    reminders().rebuild(row)

    by_stage = _by_stage(row)
    assert by_stage["due"].moment == _at(datetime.date(2026, 1, 27))
    assert by_stage["overdue"].moment == _at(datetime.date(2026, 1, 28))
    old_sent = support.model("instructions.InstructionReminder").objects.get(pk=sent.pk)
    assert (old_sent.state, old_sent.moment) == ("sent", sent_moment)


def test_report_overdue_notifies_controller_once():
    """FR-709, 711: если отчёт к дате не пришёл, со следующего рабочего дня контролёр получает уведомление
    `instructions.report_overdue`; повторный запуск не дублирует."""
    today = ins._today()
    row = _instr(today - datetime.timedelta(days=10), today + datetime.timedelta(days=30))
    due = ins.add_report_date(row, today - datetime.timedelta(days=1))
    reminders().plan(row)
    now = datetime.datetime.combine(today, time(10), tzinfo=MSK)
    _job(now)
    notes = _notes(row.controller, "instructions.report_overdue")
    assert notes.count() == 1
    _job(now)
    assert notes.count() == 1
    assert support.model("instructions.InstructionReportDate").objects.get(pk=due.pk).state == "waiting"