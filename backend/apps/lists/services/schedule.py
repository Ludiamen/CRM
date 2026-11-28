"""Плановый запуск процесса (срез 015; PLAN-015, «Плановый запуск»; CONTRACT-015, раздел 7).

Период считается по Москве; строка `ProcessLaunch` с уникальным `(process, period_start)` создаётся первой и
фиксируется вместе с журналом. Ошибка карточки даёт `failed` и не повторяется до следующего периода.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.services import audit
from apps.lists.models import ListProcess, ProcessLaunch, RecordFile
from apps.lists.services import access, process, records, values as values_service
from apps.lists.services.errors import ListsError

MOSCOW = ZoneInfo("Europe/Moscow")
WEEKDAYS = 7


def _moscow_now():
    return timezone.now().astimezone(MOSCOW)


def period_start(process_row: ListProcess, now: datetime) -> date:
    today = now.date()
    if process_row.schedule_period == ListProcess.Period.DAILY:
        return today
    if process_row.schedule_period == ListProcess.Period.WEEKLY:
        target = int(process_row.schedule_weekday or 1)
        return today - timedelta(days=(today.isoweekday() - target) % WEEKDAYS)
    return today.replace(day=1)


def due(process_row: ListProcess, now: datetime):
    """`(period_start, due_at)` текущего периода или `None`, если срок ещё не наступил."""
    if process_row.launch_mode != ListProcess.LaunchMode.SCHEDULE or process_row.schedule_time is None:
        return None
    start = period_start(process_row, now)
    if process_row.schedule_period == ListProcess.Period.WEEKLY:
        target = int(process_row.schedule_weekday or 1)
        start = start + timedelta(days=(target - start.isoweekday()) % WEEKDAYS)
    elif process_row.schedule_period == ListProcess.Period.MONTHLY:
        start = start.replace(day=int(process_row.schedule_monthday or 1))
    moment = datetime.combine(start, process_row.schedule_time, tzinfo=MOSCOW)
    if now < moment:
        return None
    return start, moment


def _defaults(lst, actor):
    from apps.lists.services import schema

    data = {}
    for field in schema.visible_fields(lst):
        if field.hidden or field.default in (None, "", [], {}):
            continue
        if isinstance(field.default, dict) and field.default.get("today"):
            data[field.code] = _moscow_now().strftime("%d.%m.%Y")
        else:
            data[field.code] = values_service.display(field, field.default, actor)
    return data


def _can_fill(first, data, lst) -> bool:
    if first is None:
        return False
    for item in first.required_fields.select_related("field"):
        field = item.field
        if field.type == "file":
            return False
        value = data.get(field.code)
        if not value:
            return False
    return True


def launch(process_row: ListProcess, period: date, now: datetime) -> ProcessLaunch:
    lst = process_row.list
    row, created = ProcessLaunch.objects.get_or_create(
        process=process_row, period_start=period, defaults={"status": ProcessLaunch.Status.SKIPPED})
    if not created:
        return row
    first = process.first_open(lst)
    data = _defaults(lst, process_row.author)
    reason = ""
    if not process_row.enabled:
        reason = "процесс выключен"
    elif first is None:
        reason = "нет открытой стадии"
    elif not _can_fill(first, data, lst):
        reason = "не заполнены обязательные поля первой стадии"
    if reason:
        row.reason = reason
        row.save(update_fields=["reason"])
        audit.record("lists.process_launch_skipped", actor=None, object_type="lists.process",
                     object_id=lst.pk, after={"period": period.isoformat(), "reason": reason})
        return row
    title = (process_row.title_template or "").replace("{дата}", period.strftime("%d.%m.%Y")).strip()
    if not title:
        title = f"{process.process_title(process_row, lst)} — {period.strftime('%d.%m.%Y')}"
    data["title"] = title
    try:
        with transaction.atomic():
            record = records.create_system(lst, data, process_row.author or process_row.list.created_by, stage=first)
            row.status = ProcessLaunch.Status.CREATED
            row.record = record
            row.save(update_fields=["status", "record"])
    except (ListsError, IntegrityError) as error:
        row.status = ProcessLaunch.Status.FAILED
        row.reason = str(error)[:200]
        row.save(update_fields=["status", "reason"])
        audit.record("lists.process_launch_failed", actor=None, object_type="lists.process",
                     object_id=lst.pk, after={"period": period.isoformat(), "reason": row.reason})
    else:
        audit.record("lists.process_launch_created", actor=None, object_type="lists.process",
                     object_id=lst.pk, after={"period": period.isoformat(), "number": record.number})
    return row


def tick(now=None) -> dict:
    now = now or _moscow_now()
    created = skipped = failed = 0
    for process_row in ListProcess.objects.filter(launch_mode=ListProcess.LaunchMode.SCHEDULE).select_related("list"):
        found = due(process_row, now)
        if found is None:
            continue
        if ProcessLaunch.objects.filter(process=process_row, period_start=found[0]).exists():
            continue
        row = launch(process_row, found[0], now)
        if row.status == ProcessLaunch.Status.CREATED:
            created += 1
        elif row.status == ProcessLaunch.Status.FAILED:
            failed += 1
        else:
            skipped += 1
    return {"created": created, "skipped": skipped, "failed": failed}
