"""Задания поручений (срез 010; T-10208/T-10209/T-10213; CONTRACT-010, 1.2, 9).

`instructions_reminders` — каждые 5 минут; `instructions_digest` — сводка; `instructions_retention` — уборка.
Время — параметр; тихие часы проверяются перед отправкой (К5).
"""
import datetime

from django.core.cache import cache
from django.utils import timezone

from apps.core.extensions import Draft
from apps.instructions.services import digest as digest_service, reminders
from apps.notify.services import dispatch, quiet

TEXT = {
    "instructions.deadline": "Срок поручения приближается",
    "instructions.overdue": "Поручение просрочено",
    "instructions.report_due": "Нужен отчёт по поручению",
    "instructions.report_overdue": "Отчёт по поручению просрочен",
}


def _draft(instruction, user, code, text=None):
    return Draft(user_id=user.pk, text=f"{text or TEXT[code]}: №{instruction.pk}",
                 url=f"/instructions/{instruction.pk}/", object_ref=f"instructions.instruction:{instruction.pk}")


def instructions_reminders(now=None) -> int:
    """Отправить созревшие напоминания и просрочки отчётов; вернуть число отправленных."""
    now = now or timezone.now()
    sent = 0
    for row in reminders.due(now):
        prefs = dispatch.user_prefs(row.user_id)
        start = quiet.next_start(prefs, row.moment)
        key = f"instructions:reminder-none:{row.pk}"
        if start is None:
            if cache.add(key, 1, timeout=24 * 3600):
                row.moment = now
                row.save(update_fields=["moment"])
                continue
            row.state = "cancelled"
            row.save(update_fields=["state"])
            from apps.core.services import audit

            audit.record("instructions.reminder_failed", object_type="instructions.instruction",
                         object_id=row.instruction_id, after={"reminder": row.pk, "user": row.user_id})
            continue
        if start > now:
            row.moment = start
            row.save(update_fields=["moment"])
            continue
        if row.kind == "report":
            code = "instructions.report_due"
        else:
            code = "instructions.overdue" if row.stage == "overdue" else "instructions.deadline"
        dispatch.create(code, [_draft(row.instruction, row.user, code)])
        row.state = "sent"
        row.save(update_fields=["state"])
        cache.delete(key)
        sent += 1
    sent += _report_overdue(now)
    return sent


def _report_overdue(now) -> int:
    """Уведомить контролёра и автора о непришедшем отчёте со следующего рабочего дня после даты."""
    from apps.instructions.models import InstructionReportDate
    from apps.instructions.services import notify_rules

    local = timezone.localtime(now)
    today = local.date()
    sent = 0
    for date_row in InstructionReportDate.objects.filter(state="waiting", due_date__lt=today).select_related(
            "instruction"):
        if date_row.reports.exists():
            continue
        day = reminders._next_work(date_row.due_date)
        if reminders._work_start(day) > now:
            continue
        key = f"instructions:report-overdue:{date_row.pk}"
        if not cache.add(key, 1, timeout=30 * 24 * 3600):
            continue
        for user_id in notify_rules.recipients(date_row.instruction, "report_overdue"):
            user = date_row.instruction.controller if user_id == date_row.instruction.controller_id \
                else date_row.instruction.author
            dispatch.create("instructions.report_overdue",
                            [_draft(date_row.instruction, user, "instructions.report_overdue")])
            sent += 1
    return sent


def instructions_digest(now=None) -> int:
    """Недельная сводка."""
    return digest_service.send(now)


def instructions_retention(now=None) -> dict:
    """Ночная уборка по сроку хранения (T-10213)."""
    from apps.instructions.services import retention

    return retention.purge(now or timezone.now())