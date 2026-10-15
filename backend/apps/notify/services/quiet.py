"""Публичный интерфейс уведомлений: тихие часы (PLAN-004, «Где живёт код»)."""
import datetime
import logging

from django.utils import timezone

from apps.org.services import calendar

log = logging.getLogger(__name__)

MODE_CALENDAR = "calendar"
MODE_OWN = "own"
MODE_NONE = "none"


def _mode(prefs) -> str:
    """Режим тихих часов; нет строки настроек — «по рабочему календарю»."""
    return prefs.quiet_mode if prefs is not None else MODE_CALENDAR


def _own_working(prefs, local: datetime.datetime) -> bool:
    """«Свои часы»: интервал через полночь относится ко дню начала; праздники не учитываются."""
    days, start, end = list(prefs.own_days or []), prefs.own_start, prefs.own_end
    if start is None or end is None:
        return False
    now = local.time()
    if start < end:
        return local.weekday() in days and start <= now < end
    if start == end:
        return False
    if local.weekday() in days and now >= start:
        return True
    return (local.weekday() - 1) % 7 in days and now < end


def is_working(prefs, moment: datetime.datetime) -> bool:
    """Рабочее ли время сотрудника в `moment` (время считается по Москве)."""
    mode = _mode(prefs)
    if mode == MODE_NONE:
        return True
    if mode == MODE_OWN:
        return _own_working(prefs, timezone.localtime(moment))
    return calendar.is_working_time(moment)


def next_start(prefs, moment: datetime.datetime) -> datetime.datetime | None:
    """Сам `moment`, если он в рабочее время, иначе ближайшее начало рабочего времени.

    `None` бывает только в режиме календаря: за 400 суток рабочего дня нет.
    """
    mode = _mode(prefs)
    if mode == MODE_NONE:
        return timezone.localtime(moment)  # ответ — по Москве (CONTRACT-004 § 6.6)
    if mode == MODE_CALENDAR:
        return calendar.next_working_start(moment)
    local = timezone.localtime(moment)
    if _own_working(prefs, local):
        return local
    days, start = list(prefs.own_days or []), prefs.own_start
    if not days or start is None:
        return None
    for offset in range(8):
        day = local.date() + datetime.timedelta(days=offset)
        if day.weekday() not in days:
            continue
        candidate = datetime.datetime.combine(day, start, tzinfo=local.tzinfo)
        if candidate > local:
            return candidate
    return None


def validate_own_hours(days, start, end) -> tuple[list[int], datetime.time, datetime.time]:
    """Проверка ввода «своих часов»: дни по возрастанию без повторов, «с» не равно «до»."""
    from apps.notify.services import NotifyError

    if start is None or end is None:
        raise NotifyError("own_incomplete", "Укажите время начала и конца своих часов", field="own_start")
    days = list(days or [])
    if not days:
        raise NotifyError("own_no_days", "Отметьте хотя бы один день недели для своих часов", field="own_days")
    if any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        raise NotifyError("own_bad_day", "День недели указан неверно", field="own_days")
    if start == end:
        raise NotifyError("own_same_time", "Начало и конец своих часов не должны совпадать", field="own_end")
    return sorted(set(days)), start, end
