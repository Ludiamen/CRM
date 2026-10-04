"""Рабочий календарь: вид дня, рабочее время, настройки, правка дня, версия и кэш отметок
(PLAN-002, «Рабочий календарь»; CONTRACT-002, § 4.5 и § 7).

Время — по `Europe/Moscow`. Разбор файла и применение года — в `calendar_file`.
"""
import datetime
import json
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.core.services import audit, permissions, valkey

from ..models import CalendarYear, SpecialDay, WorkCalendar
from .errors import OrgError

MSK = ZoneInfo("Europe/Moscow")
SEARCH_DAYS = 400
MIN_DAY = datetime.timedelta(hours=2)
SHORT_CUT = datetime.timedelta(hours=1)
VERSION_KEY = "calendar:version"
MARKS_TTL = 7 * 24 * 3600
OFF_KINDS = ("off", "holiday", "day_off")
KINDS = tuple(SpecialDay.Kind.values)


def _settings() -> WorkCalendar:
    return WorkCalendar.objects.first() or WorkCalendar.objects.create()


def _moscow(moment: datetime.datetime) -> datetime.datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("нужно время с часовым поясом")
    return moment.astimezone(MSK)


def _today() -> datetime.date:
    return timezone.now().astimezone(MSK).date()


def _kind(day: datetime.date, weekdays, special: dict, loaded: set) -> str:
    if day.year in loaded and day in special:
        return special[day]
    return "work" if day.weekday() in weekdays else "off"


def day_kind(day: datetime.date) -> str:
    """Вид дня: особый (год загружен), иначе `"work"` или `"off"` по рабочим дням недели."""
    weekdays = _settings().work_weekdays
    loaded = set(CalendarYear.objects.filter(year=day.year).values_list("year", flat=True))
    special = dict(SpecialDay.objects.filter(date=day).values_list("date", "kind")) if loaded else {}
    return _kind(day, weekdays, special, loaded)


def _bounds(kind: str, row: WorkCalendar) -> tuple[datetime.time, datetime.time]:
    end = row.day_end
    if kind == "short":
        end = (datetime.datetime.combine(datetime.date.min, end) - SHORT_CUT).time()
    return row.day_start, end


def is_working_time(moment: datetime.datetime) -> bool:
    """Рабочее ли время: рабочий день и время от начала (включительно) до конца (не включительно)."""
    local = _moscow(moment)
    kind = day_kind(local.date())
    if kind in OFF_KINDS:
        return False
    start, end = _bounds(kind, _settings())
    return start <= local.time() < end


def next_working_start(moment: datetime.datetime) -> datetime.datetime | None:
    """Сам `moment`, если он в рабочее время; иначе ближайшее начало рабочего дня (не дальше 400 суток)."""
    local = _moscow(moment)
    row = _settings()
    first = local.date()
    last = first + datetime.timedelta(days=SEARCH_DAYS)
    loaded = set(CalendarYear.objects.filter(year__range=(first.year, last.year)).values_list("year", flat=True))
    special = dict(SpecialDay.objects.filter(date__range=(first, last)).values_list("date", "kind"))
    for offset in range(SEARCH_DAYS + 1):
        day = first + datetime.timedelta(days=offset)
        kind = _kind(day, row.work_weekdays, special, loaded)
        if kind in OFF_KINDS:
            continue
        start, end = _bounds(kind, row)
        if offset == 0:
            if start <= local.time() < end:
                return local
            if local.time() >= end:
                continue
        return datetime.datetime.combine(day, start, tzinfo=MSK)
    return None


# --- номер версии и отметки месяца ---------------------------------------------------------------

def version() -> int:
    """Номер версии календаря; отсутствующий ключ — 0."""
    return int(valkey.conn().get(VERSION_KEY) or 0)


def bump_version() -> None:
    """Увеличивает номер версии на фиксации транзакции (вызывают все службы, меняющие календарь)."""
    transaction.on_commit(lambda: valkey.conn().incr(VERSION_KEY))


def month_marks(year: int, month: int) -> dict[datetime.date, str]:
    """Дни месяца, у которых вид не `"work"`; результат кэшируется по номеру версии."""
    conn = valkey.conn()
    key = f"calendar:marks:{version()}:{year:04d}-{month:02d}"
    cached = conn.get(key)
    if cached is not None:
        return {datetime.date.fromisoformat(d): k for d, k in json.loads(cached).items()}
    row = _settings()
    loaded = set(CalendarYear.objects.filter(year=year).values_list("year", flat=True))
    first = datetime.date(year, month, 1)
    special = dict(SpecialDay.objects.filter(date__year=year, date__month=month).values_list("date", "kind"))
    marks, day = {}, first
    while day.month == month:
        kind = _kind(day, row.work_weekdays, special, loaded)
        if kind != "work":
            marks[day] = kind
        day += datetime.timedelta(days=1)
    conn.set(key, json.dumps({d.isoformat(): k for d, k in marks.items()}), ex=MARKS_TTL)
    return marks


# --- настройки и правка дня ----------------------------------------------------------------------

def _state(weekdays, start: datetime.time, end: datetime.time) -> dict:
    return {"work_weekdays": [int(d) for d in weekdays], "day_start": start.strftime("%H:%M"),
            "day_end": end.strftime("%H:%M")}


def update_settings(*, work_weekdays, day_start: datetime.time, day_end: datetime.time, actor, ip=None) -> WorkCalendar:
    """Рабочие дни недели и границы дня (FR-143); пустая правка ничего не пишет."""
    days = list(work_weekdays)
    if any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        raise OrgError("bad_weekday", "Рабочие дни недели — числа от 0 (понедельник) до 6 (воскресенье).")
    if not days:
        raise OrgError("no_weekday", "Выберите хотя бы один рабочий день недели.")
    if datetime.datetime.combine(datetime.date.min, day_end) - datetime.datetime.combine(
            datetime.date.min, day_start) < MIN_DAY:
        raise OrgError("day_too_short", "Рабочий день должен кончаться не раньше чем через 2 часа после начала.")
    days = sorted(set(days))
    with transaction.atomic():
        row = WorkCalendar.objects.select_for_update().first() or WorkCalendar.objects.create()
        before = _state(row.work_weekdays, row.day_start, row.day_end)
        after = _state(days, day_start, day_end)
        if before == after and row.day_start == day_start and row.day_end == day_end:
            return row
        row.work_weekdays, row.day_start, row.day_end = days, day_start, day_end
        row.updated_at = timezone.now()
        row.save()
        audit.record("calendar.settings_changed", actor=actor, object_type="calendar", object_id=row.pk,
                     before=before, after=after, ip=ip)
        bump_version()
    return row


def set_day(day: datetime.date, kind: str, *, actor, ip=None) -> None:
    """Вид дня в загруженном году; `""` снимает особую отметку (FR-144)."""
    if kind != "" and kind not in KINDS:
        raise OrgError("bad_kind", "Неизвестный вид дня.")
    if not CalendarYear.objects.filter(year=day.year).exists():
        raise OrgError("year_not_loaded", f"Календарь на {day.year} год не загружен: день править нельзя.")
    with transaction.atomic():
        record = SpecialDay.objects.select_for_update().filter(date=day).first()
        old = record.kind if record else ""
        if old == kind:
            return
        if kind == "":
            record.delete()
        elif record is None:
            SpecialDay.objects.create(date=day, kind=kind, origin=SpecialDay.Origin.MANUAL, changed_by=actor,
                                      changed_at=timezone.now())
        else:
            record.kind, record.origin, record.changed_by, record.changed_at = (
                kind, SpecialDay.Origin.MANUAL, actor, timezone.now())
            record.save()
        audit.record("calendar.day_changed", actor=actor, object_type="calendar", object_id=day.isoformat(),
                     before={"date": day.isoformat(), "kind": old}, after={"date": day.isoformat(), "kind": kind},
                     ip=ip)
        bump_version()


# --- загруженные годы и напоминание --------------------------------------------------------------

def loaded_years() -> list[int]:
    """Загруженные годы по возрастанию."""
    return list(CalendarYear.objects.order_by("year").values_list("year", flat=True))


def missing_years(today: datetime.date | None = None) -> list[int]:
    """Текущий год, если не загружен, и следующий — с 1 декабря, если он не загружен."""
    today = today or _today()
    loaded = set(loaded_years())
    years = [today.year] + ([today.year + 1] if today.month == 12 else [])
    return [year for year in years if year not in loaded]


def calendar_notices(user) -> list[dict]:
    """Точка `home_notices`: напоминание о незагруженном годе — только обладателю `calendar.manage`."""
    if not permissions.has_permission(user, "calendar.manage"):
        return []
    return [{"key": "calendar-year", "year": year, "level": "warning", "url": "/calendar/upload/",
             "link": "Загрузить файл", "text": f"Не загружен производственный календарь на {year} год."}
            for year in missing_years()]
