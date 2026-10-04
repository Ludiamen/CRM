"""Загрузка и разбор файла календаря (PLAN-002, «Рабочий календарь»; CONTRACT-002, § 4.6).

Файл — CSV открытых данных Минтруда: заголовок и по строке на год. Перевод в особые дни идёт по обычной
неделе пн–пт и от `WorkCalendar.work_weekdays` не зависит. Номер версии календаря увеличивает
`calendar.bump_version()` (на фиксации).
"""
import calendar as std_calendar
import csv
import datetime
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.services import audit

from ..models import CalendarUpload, CalendarYear, SpecialDay, WorkCalendar
from . import calendar as calendar_service
from .errors import OrgError

MAX_BYTES = 1_048_576
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь",
          "Ноябрь", "Декабрь")
COLUMNS = 18  # год, 12 месяцев, рабочие дни, нерабочие дни и три столбца часов
TOTAL_KEYS = ("holidays_on_weekdays", "moved_days_off", "moved_workdays", "short_days", "work_days")
HOURS_PER_DAY = 8
SHORT_HOURS = 1
BAD_FORMAT = "Файл не похож на календарь Минтруда: проверьте заголовки и число столбцов."


@dataclass
class ParsedYear:
    """Разобранный год: особые дни по возрастанию даты и итоги из пяти ключей."""

    year: int
    days: list[tuple[datetime.date, str]]
    totals: dict


def _decode(content: bytes) -> str:
    if len(content) > MAX_BYTES:
        raise OrgError("too_big", "Файл больше 1 МБ.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise OrgError("not_utf8", "Файл не в кодировке UTF-8.") from None
    if "\x00" in text:
        raise OrgError("not_utf8", "Файл не в кодировке UTF-8: в нём есть нулевой байт.")
    return text.removeprefix("﻿")


def _rows(text: str) -> list[list[str]]:
    try:
        rows = [row for row in csv.reader(io.StringIO(text, newline="")) if row]
    except csv.Error:
        raise OrgError("bad_format", BAD_FORMAT) from None
    if not rows or len(rows[0]) != COLUMNS or [c.strip() for c in rows[0][1:13]] != list(MONTHS):
        raise OrgError("bad_format", BAD_FORMAT)
    if any(len(row) != COLUMNS for row in rows[1:]):
        raise OrgError("bad_format", BAD_FORMAT)
    return rows[1:]


def _year_row(rows: list[list[str]], year: int) -> list[str]:
    for row in rows:
        try:
            if int(row[0].strip()) == year:
                return row
        except ValueError:
            raise OrgError("bad_format", BAD_FORMAT) from None
    raise OrgError("year_missing", f"Загрузка отклонена: в файле нет {year} года.")


def _number(cell: str) -> Decimal:
    try:
        return Decimal(cell.strip().replace(",", ".").replace("\xa0", ""))
    except InvalidOperation:
        raise OrgError("bad_format", BAD_FORMAT) from None


def _cell_marks(cell: str, year: int, month: int) -> list[tuple[datetime.date, str]]:
    """Дни ячейки месяца с пометкой («», «+», «*»)."""
    found, seen = [], set()
    for token in filter(None, (t.strip() for t in cell.split(","))):
        mark = token[-1] if token[-1] in "+*" else ""
        digits = token.rstrip("+*")
        if not digits.isascii() or not digits.isdigit() or len(token) - len(digits) > 1:
            raise OrgError("bad_format", BAD_FORMAT)
        number = int(digits)
        if not 1 <= number <= std_calendar.monthrange(year, month)[1] or number in seen:
            raise OrgError("bad_format", BAD_FORMAT)
        seen.add(number)
        found.append((datetime.date(year, month, number), mark))
    return found


def parse(content: bytes, *, year: int) -> ParsedYear:
    """Разбор файла: размер, строгий UTF-8, заголовки, строка года, перевод и сверка итогов."""
    row = _year_row(_rows(_decode(content)), year)
    days: dict[datetime.date, str] = {}
    off = short = 0
    for month in range(1, 13):
        for day, mark in _cell_marks(row[month], year, month):
            weekend = day.weekday() >= 5
            if mark == "*":
                days[day], short = "short", short + 1
                continue
            off += 1
            if mark == "+":
                days[day] = "day_off"
            elif not weekend:
                days[day] = "holiday"
    listed = {d for d in days} | {d for month in range(1, 13) for d, _ in _cell_marks(row[month], year, month)}
    day = datetime.date(year, 1, 1)
    while day.year == year:
        if day.weekday() >= 5 and day not in listed:
            days[day] = "workday"
        day += datetime.timedelta(days=1)
    work = (datetime.date(year + 1, 1, 1) - datetime.date(year, 1, 1)).days - off
    if (_number(row[13]) != work or _number(row[14]) != off
            or _number(row[15]) != work * HOURS_PER_DAY - short * SHORT_HOURS):
        raise OrgError("totals_mismatch", "Итоги в файле не сходятся с пересчётом: файл повреждён или другого формата.")
    ordered = sorted(days.items())
    counted = [kind for _, kind in ordered]
    totals = {"holidays_on_weekdays": counted.count("holiday"), "moved_days_off": counted.count("day_off"),
              "moved_workdays": counted.count("workday"), "short_days": counted.count("short"), "work_days": work}
    return ParsedYear(year=year, days=ordered, totals=totals)


def make_preview(content: bytes, *, year: int, file_name: str, actor, ip=None) -> CalendarUpload:
    """Предпросмотр: разбор и запись `CalendarUpload`; календарь, журнал и версия не меняются."""
    parsed = parse(content, year=year)
    return CalendarUpload.objects.create(
        year=year, file_name=file_name, created_by=actor, state=CalendarUpload.State.PREVIEW,
        days=[{"date": d.isoformat(), "kind": k} for d, k in parsed.days], totals=parsed.totals)


def preview_warnings(upload: CalendarUpload) -> dict:
    """Что будет заменено и что станет рабочим днём при рабочих субботе или воскресенье."""
    existing = SpecialDay.objects.filter(date__year=upload.year)
    weekdays = (WorkCalendar.objects.first() or WorkCalendar()).work_weekdays
    return {
        "manual_days": existing.filter(origin=SpecialDay.Origin.MANUAL).count(),
        "existing_days": existing.count(),
        "year_loaded": CalendarYear.objects.filter(year=upload.year).exists(),
        "weekend_work": any(d in (5, 6) for d in weekdays),
    }


def apply(upload: CalendarUpload, *, actor, ip=None) -> CalendarYear:
    """Применение: замена особых дней года, `CalendarYear`, событие и версия; повтор ничего не меняет."""
    year = upload.year
    with transaction.atomic():
        locked = CalendarUpload.objects.select_for_update().get(pk=upload.pk)
        if locked.state == CalendarUpload.State.APPLIED:
            upload.state = locked.state
            return CalendarYear.objects.get(year=year)
        now = timezone.now()
        SpecialDay.objects.filter(date__year=year).delete()
        SpecialDay.objects.bulk_create([
            SpecialDay(date=datetime.date.fromisoformat(item["date"]), kind=item["kind"],
                       origin=SpecialDay.Origin.FILE, changed_by=actor, changed_at=now)
            for item in locked.days])
        previous = CalendarYear.objects.select_for_update().filter(year=year).first()
        before = {"year": year, "totals": {k: int(v) for k, v in previous.totals.items()} if previous else {}}
        totals = {k: int(locked.totals[k]) for k in TOTAL_KEYS}
        if previous is None:
            row = CalendarYear.objects.create(year=year, loaded_at=now, loaded_by=actor,
                                              file_name=locked.file_name, totals=totals)
        else:
            previous.loaded_at, previous.loaded_by, previous.file_name, previous.totals = (
                now, actor, locked.file_name, totals)
            previous.save()
            row = previous
        locked.state = CalendarUpload.State.APPLIED
        locked.save(update_fields=["state"])
        upload.state = locked.state
        audit.record("calendar.year_loaded", actor=actor, object_type="calendar", object_id=str(year),
                     before=before, after={"year": year, "totals": totals, "file_name": locked.file_name}, ip=ip)
        calendar_service.bump_version()
    return row
