"""Недельная сводка поручений (срез 010, T-10209; FR-712; CONTRACT-010, 9.3).

Первый рабочий день недели, начало рабочего дня получателя; атомарный `cache.add` на сотрудника; пустая сводка не
отправляется. Получатели — контролёр и постановщик открытых поручений.
"""
import datetime

from django.core.cache import cache
from django.utils import timezone

from apps.core.extensions import Draft
from apps.instructions.models import Instruction
from apps.instructions.services import notify_rules
from apps.org.services import calendar
from apps.notify.services import dispatch

WINDOW = datetime.timedelta(days=30)


def _relevant(instruction, today) -> bool:
    if instruction.closed_at is not None or instruction.deleted_at is not None:
        return False
    if instruction.deadline <= today + WINDOW:
        return True
    return any(row.due_date <= today + WINDOW for row in instruction.report_dates.all())


def _text(rows) -> str:
    if not rows:
        return ""
    titles = "; ".join(f"№{row.pk} {row.title}" for row in rows[:20])
    return f"На контроле: {titles}"


def send(now=None) -> int:
    """Отправить сводки; вернуть число уведомлений."""
    now = now or timezone.now()
    if not calendar.is_working_time(now):
        return 0
    local = timezone.localtime(now)
    if local.weekday() != 0:
        return 0
    today = local.date()
    open_rows = list(Instruction.objects.filter(closed_at__isnull=True, deleted_at__isnull=True)
                     .prefetch_related("report_dates"))
    by_user: dict[int, list] = {}
    for row in open_rows:
        if not _relevant(row, today):
            continue
        for user_id in notify_rules.recipients(row, "digest"):
            by_user.setdefault(user_id, []).append(row)
    week = today.isocalendar()[:2]
    drafts = []
    for user_id, rows in by_user.items():
        key = f"instructions:digest:{week[0]}-{week[1]}:{user_id}"
        if not cache.add(key, 1, timeout=8 * 24 * 3600):
            continue
        drafts.append(Draft(user_id=user_id, text=_text(rows), url="/instructions/?preset=control",
                            object_ref="instructions.digest"))
    return len(dispatch.create("instructions.digest", drafts))