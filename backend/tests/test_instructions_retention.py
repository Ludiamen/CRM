"""Срез 010 «Поручения»: срок хранения (T-10118; NFR-729).

`apps.instructions.services.retention` и задание `instructions_retention` — CONTRACT-010, 5.1, 10.1, 14.
Код среза импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support, support_tasks
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")


def retention():
    from apps.instructions.services import retention as module
    return module


def _job(now):
    from apps.instructions.tasks import instructions_retention

    return instructions_retention(now=now)


def _at(day, hour=23):
    return datetime.datetime.combine(day, datetime.time(hour, 30), tzinfo=MSK)


def _old(title="Старое поручение", closed_on=datetime.date(2020, 1, 10)):
    row = ins.make_instruction(title=title)
    row.closed_at = _at(closed_on)
    row.save(update_fields=["closed_at"])
    return row


def _world(row, protected_root):
    """Отчёт, часть, файл, перенос, напоминание и связь с задачей у закрытого поручения."""
    from apps.core.services import files as core_files, uploads

    report = support.model("instructions.InstructionReport").objects.create(
        instruction=row, date=None, author=row.assignee, text="Секретный итог", decision="accepted")
    due = ins.add_report_date(row, datetime.date(2020, 1, 1))
    part = support.model("instructions.InstructionReportPart").objects.create(
        date=due, author=row.assignee, text="Секретная часть")
    stored = uploads.store(b"old body", "старый.txt", "instruction")
    entry = support.model("instructions.InstructionFile").objects.create(
        instruction=row, kind="report", report=report, file=stored, name="старый.txt", uploaded_by=row.assignee)
    transfer = support.model("instructions.InstructionTransfer").objects.create(
        instruction=row, old_deadline=row.deadline, new_deadline=row.deadline, reason="Старый перенос",
        requested_by=row.assignee, state="approved", decided_by=row.controller, decided_at=_at(datetime.date(2020, 1, 5)))
    reminder = support.model("instructions.InstructionReminder").objects.create(
        instruction=row, date=None, user=row.assignee, kind="deadline", stage="d3",
        moment=_at(datetime.date(2020, 1, 8)), state="sent")
    task = support_tasks.make_task(title="Связанная задача", author=row.assignee, assignee=row.assignee)
    support.model("instructions.InstructionTask").objects.create(
        instruction=row, task=task, created_by=row.assignee)
    return {"report": report, "due": due, "part": part, "stored": stored, "entry": entry,
            "transfer": transfer, "reminder": reminder, "task": task,
            "path": core_files.attachment_path(stored)}


def test_purges_only_closed_older_than_retention(protected_root):
    """NFR-729: удаляются только снятые с контроля поручения старше срока хранения; неснятые и свежие остаются."""
    support.model("instructions.InstructionSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": 3})
    old = _old()
    recent = _old("Свежее", datetime.date(2022, 1, 10))
    open_row = ins.make_instruction(title="На контроле")
    result = retention().purge(_at(datetime.date(2023, 6, 1)))
    Instruction = support.model("instructions.Instruction")
    assert result["instructions"] == 1
    assert not Instruction.objects.filter(pk=old.pk).exists()
    assert Instruction.objects.filter(pk=recent.pk).exists()
    assert Instruction.objects.filter(pk=open_row.pk).exists()


def test_purge_removes_parts_files_transfers_reminders_and_links(protected_root,
                                                                 django_capture_on_commit_callbacks):
    """NFR-729: каскадом уходят отчёты, части, файлы, переносы, напоминания и связи с задачами; файл с диска —
    после фиксации."""
    support.model("instructions.InstructionSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": 3})
    row = _old()
    world = _world(row, protected_root)
    with django_capture_on_commit_callbacks(execute=True):
        result = retention().purge(_at(datetime.date(2023, 6, 1)))

    assert result["instructions"] == 1
    for model in ("InstructionReport", "InstructionReportPart", "InstructionFile", "InstructionTransfer",
                  "InstructionReminder", "InstructionTask"):
        assert not support.model(f"instructions.{model}").objects.filter(instruction=row).exists(), model
    assert not support.model("core.StoredFile").objects.filter(pk=world["stored"].pk).exists()
    assert not world["path"].exists(), "файл остался на диске"


def test_purge_journal_has_no_text_and_only_when_removed(protected_root):
    """NFR-729: журнал `instructions.retention_purged` — только когда что-то удалено, без текста поручения."""
    support.model("instructions.InstructionSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": 3})
    assert _job(_at(datetime.date(2023, 6, 1)))["instructions"] == 0
    assert not support.model("core.AuditEvent").objects.filter(action="instructions.retention_purged").exists()

    row = _old(title="Секретное название")
    _job(_at(datetime.date(2023, 6, 1)))
    event = support.model("core.AuditEvent").objects.get(action="instructions.retention_purged")
    assert "Секретное название" not in str(event.after) and "Секретное название" not in str(event.before)


def test_purge_is_idempotent(protected_root):
    """NFR-729, NFR-724: повторный запуск не находит ничего, не падает и не пишет второй записи журнала."""
    support.model("instructions.InstructionSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": 3})
    _old()
    now = _at(datetime.date(2023, 6, 1))
    first = _job(now)
    second = _job(now)
    assert first["instructions"] == 1
    assert second == {"instructions": 0, "reports": 0, "parts": 0, "files": 0, "transfers": 0}
    assert support.model("core.AuditEvent").objects.filter(action="instructions.retention_purged").count() == 1


def test_leap_day_uses_calendar_subtraction(protected_root):
    """NFR-729, К14: 29.02 при календарном вычитании лет становится 28.02 — граница не сдвигает уборку."""
    support.model("instructions.InstructionSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": 3})
    row = _old("Родилось 29 февраля", datetime.date(2020, 2, 29))
    before = retention().purge(_at(datetime.date(2023, 2, 28)))
    assert before["instructions"] == 0, "поручение удалено раньше календарной границы"
    after = retention().purge(_at(datetime.date(2023, 3, 1)))
    assert after["instructions"] == 1