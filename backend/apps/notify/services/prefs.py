"""Публичный интерфейс уведомлений: личные настройки — действующая таблица «вид × канал» и сохранение
(PLAN-004, «Каталог видов и каналы», «Личные настройки»; CONTRACT-004, 6.4)."""
import datetime
import logging
from dataclasses import dataclass

from django.db import transaction

from apps.core.services import audit

from ..models import ChatBinding, PushSubscription, UserNotifySettings
from . import kinds, quiet
from . import settings as notify_settings
from .errors import NotifyError

log = logging.getLogger(__name__)

_MODES = ("calendar", "own", "none")


@dataclass(frozen=True)
class Row:
    """Строка таблицы: вид и ячейки «включён у вида» (без учёта доступности канала)."""

    kind: object
    cells: dict


@dataclass(frozen=True)
class Channel:
    """Доступность канала: `reason` — `""`, `channel_disabled`, `not_bound` или `no_subscriptions`."""

    available: bool
    reason: str = ""


@dataclass(frozen=True)
class Table:
    """Действующая таблица сотрудника."""

    rows: list
    channels: dict
    fixed: list
    web_push_available: bool
    web_push_reason: str


def row_of(user_id: int) -> UserNotifySettings | None:
    """Строка личных настроек или `None`."""
    return UserNotifySettings.objects.filter(user_id=user_id).first()


def _listed(kind, matrix: dict, defaults: dict) -> list[str]:
    """Включённые внешние каналы вида: `matrix`, затем значения администратора, затем `default_channels`."""
    if kind.code in matrix:
        source = matrix[kind.code]
    elif kind.code in defaults:
        source = defaults[kind.code]
    else:
        source = kind.default_channels
    return [channel for channel in kinds.EXTERNAL if channel in source]


def channels_for(user_id: int, kind) -> list[str]:
    """Внешние каналы вида, включённые у сотрудника, без учёта доступности (её проверяет `dispatch`)."""
    row = row_of(user_id)
    return _listed(kind, (row.matrix if row else None) or {}, notify_settings.get().defaults or {})


def _channels(user_id: int) -> tuple[dict, bool, str]:
    """Доступность пяти каналов, а также Web Push при закрытой вкладке и причина."""
    states = {"portal": Channel(True), "email": Channel(True), "push": Channel(True)}
    for channel in ("telegram", "max"):
        if not notify_settings.channel_on(channel):
            states[channel] = Channel(False, "channel_disabled")
        elif not ChatBinding.objects.filter(user_id=user_id, channel=channel).exists():
            states[channel] = Channel(False, "not_bound")
        else:
            states[channel] = Channel(True)
    if not notify_settings.channel_on("webpush"):
        push_available, push_reason = False, "channel_disabled"
    elif not PushSubscription.objects.filter(user_id=user_id).exists():
        push_available, push_reason = False, "no_subscriptions"
    else:
        push_available, push_reason = True, ""
    return {name: states[name] for name in kinds.CHANNELS}, push_available, push_reason


def channel_states(user_id: int) -> dict:
    """Доступность каналов, как `Table.channels`."""
    return _channels(user_id)[0]


def effective(user) -> Table:
    """Действующая таблица: строки — доступные сотруднику виды без обязательных; ячейки — по правилу `_listed`."""
    row = row_of(user.pk)
    matrix = (row.matrix if row else None) or {}
    defaults = notify_settings.get().defaults or {}
    rows, fixed = [], []
    for kind in kinds.catalog():
        if kind.mandatory:
            fixed.append(kind)
        elif kind.available(user):
            on = _listed(kind, matrix, defaults)
            cells = {"portal": True, **{channel: channel in on for channel in kinds.EXTERNAL}}
            rows.append(Row(kind=kind, cells=cells))
    channels, push_available, push_reason = _channels(user.pk)
    return Table(rows=rows, channels=channels, fixed=fixed, web_push_available=push_available,
                 web_push_reason=push_reason)


def _time(value, field: str):
    """Время из `datetime.time` или строки `ЧЧ:ММ`; пусто — `None` (оставить прежнее)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime.time):
        return value
    try:
        return datetime.datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        # поле отказа `own_incomplete` — всегда `own_start` (CONTRACT-004 § 6.2), какое бы время ни было нечитаемым
        raise NotifyError("own_incomplete", "Укажите время начала и конца своих часов", field="own_start") from None


def _days(value) -> list:
    """Дни недели: целые или строки из цифр; остальное оставляется как есть — отказ даст `validate_own_hours`."""
    return [int(day) if isinstance(day, str) and day.strip().isdigit() else day for day in value]


def _hhmm(value):
    """Время — строкой `ЧЧ:ММ`, остальное без изменений."""
    return value.strftime("%H:%M") if isinstance(value, datetime.time) else value


def save(user, *, table=None, quiet_mode=None, own_days=None, own_start=None, own_end=None, ip=None) -> bool:
    """Сохраняет таблицу и тихие часы; возвращает, изменилось ли что-то. Журнал — одной записью."""
    if quiet_mode is not None and quiet_mode not in _MODES:
        raise NotifyError("bad_quiet_mode", "Выберите один из трёх вариантов тихих часов", field="quiet_mode")
    with transaction.atomic():
        row = UserNotifySettings.objects.select_for_update().filter(user_id=user.pk).first()
        old_mode = row.quiet_mode if row else "calendar"
        old_days = list(row.own_days or []) if row else []
        old_start, old_end = (row.own_start, row.own_end) if row else (None, None)

        # --- таблица: применяются только доступные каналы; matrix пишется, только если ячейка изменилась ---
        cells_before, cells_after, new_matrix = {}, {}, None
        if table is not None:
            current = effective(user)
            states = current.channels
            snapshot, changed = {}, False
            for item in current.rows:
                chosen = set(table.get(item.kind.code, [])) if item.kind.code in table else None
                applied = []
                for channel in kinds.EXTERNAL:
                    now_on = item.cells[channel]
                    if chosen is not None and states[channel].available:
                        wanted = channel in chosen
                    else:
                        wanted = now_on
                    if wanted:
                        applied.append(channel)
                    if wanted != now_on:
                        changed = True
                        cells_before[item.kind.title] = [c for c in kinds.EXTERNAL if item.cells[c]]
                        cells_after[item.kind.title] = None  # заполняется ниже полным списком
                snapshot[item.kind.code] = applied
            if changed:
                matrix = dict(row.matrix) if row and row.matrix else {}
                matrix.update(snapshot)
                new_matrix = matrix
                for item in current.rows:
                    if item.kind.title in cells_after:
                        cells_after[item.kind.title] = snapshot[item.kind.code]

        # --- тихие часы ---
        new_mode, new_days, new_start, new_end = old_mode, old_days, old_start, old_end
        if quiet_mode is not None:
            new_mode = quiet_mode
        if new_mode == "own" and (quiet_mode is not None or own_days is not None or own_start not in (None, "")
                                  or own_end not in (None, "")):
            if own_days is not None:  # пустой список — «ни одного дня» (отказ own_no_days), None — не передано
                new_days = _days(own_days)
            start, end = _time(own_start, "own_start"), _time(own_end, "own_end")
            new_start = start if start is not None else old_start
            new_end = end if end is not None else old_end
            new_days, new_start, new_end = quiet.validate_own_hours(new_days, new_start, new_end)

        before, after = {}, {}
        if cells_after:
            before["cells"], after["cells"] = cells_before, cells_after
        for key, old, new in (("quiet_mode", old_mode, new_mode), ("own_days", old_days, new_days),
                              ("own_start", old_start, new_start), ("own_end", old_end, new_end)):
            if old != new:
                before[key] = _hhmm(old)
                after[key] = _hhmm(new)
        if not before and not after:
            return False

        if row is None:
            row = UserNotifySettings(user_id=user.pk)
        if new_matrix is not None:
            row.matrix = new_matrix
        row.quiet_mode, row.own_days, row.own_start, row.own_end = new_mode, new_days, new_start, new_end
        row.save()
        audit.record("notify.user_settings_changed", actor=user, object_type="user", object_id=user.pk,
                     before=before, after=after, ip=ip)
        if any(key in after for key in ("quiet_mode", "own_days", "own_start", "own_end")):
            from . import dispatch
            dispatch.replan_digest(user.pk)
        return True
