"""Публичный интерфейс уведомлений: настройки администратора (PLAN-004, «Администратор»; CONTRACT-004, 6.5).

Строка настроек одна (`pk=1`). Внутри модуля `django.conf.settings` импортируется как `dj_settings`.
"""
import logging

from django.conf import settings as dj_settings
from django.db import transaction
from django.utils import timezone

from apps.core.services import audit

from ..models import NotifySettings
from . import kinds
from .errors import NotifyError

log = logging.getLogger(__name__)

CHANNELS = ("webpush", "telegram", "max")
_TITLES = {"webpush": "Web Push", "telegram": "Telegram", "max": "MAX"}
_ENV = {
    "webpush": ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT"),
    "telegram": ("TELEGRAM_BOT_TOKEN",),
    "max": ("MAX_BOT_TOKEN",),
}
# поле -> (название для сообщения, минимум, максимум): границы раздела 2.2
_RANGES = {
    "email_delay_minutes": ("Срок письма, минут", 5, 120),
    "retention_days": ("Срок хранения, дней", 30, 365),
}
_SWITCHES = tuple(f"{channel}_enabled" for channel in CHANNELS)
_ORDER = (*_SWITCHES, *_RANGES, "defaults")  # порядок проверки полей: первая ошибка — единственная
_FIELDS = set(_ORDER)


def get() -> NotifySettings:
    """Строка настроек (`pk=1`); каждый раз читает базу."""
    return NotifySettings.objects.get(pk=1)


def keys_set(channel: str) -> bool:
    """Заданы ли ключи канала в окружении (значений не показывает и не возвращает)."""
    if channel not in _ENV:
        raise ValueError(f"неизвестный канал: {channel}")
    return all(getattr(dj_settings, name, "") for name in _ENV[channel])


def channel_on(channel: str) -> bool:
    """Переключатель включён и ключи заданы: убрали ключ из окружения — канал выключен."""
    if channel not in _ENV:
        raise ValueError(f"неизвестный канал: {channel}")
    return bool(getattr(get(), f"{channel}_enabled")) and keys_set(channel)


def _in_range(field: str, value) -> int:
    title, low, high = _RANGES[field]
    try:
        number = int(value)
        if isinstance(value, bool) or (isinstance(value, float) and value != number):
            raise ValueError
    except (TypeError, ValueError):
        number = None
    if number is None or not low <= number <= high:
        raise NotifyError("out_of_range", f"Значение поля «{title}» должно быть от {low} до {high}", field=field)
    return number


def _bad_defaults() -> NotifyError:
    return NotifyError("bad_defaults", "Значения по умолчанию заданы неверно", field="defaults")


def _normalized_defaults(value) -> dict:
    """Словарь «код вида -> внешние каналы» в порядке каталога, без повторов и без `portal`."""
    if not isinstance(value, dict):
        raise _bad_defaults()
    allowed = {kind.code for kind in kinds.catalog() if not kind.mandatory}
    result = {}
    for code, channels in value.items():
        if code not in allowed or not isinstance(channels, (list, tuple, set, frozenset)):
            raise _bad_defaults()
        if any(channel not in kinds.CHANNELS for channel in channels):
            raise _bad_defaults()
        result[code] = [channel for channel in kinds.EXTERNAL if channel in channels]
    return result


def _effective_list(kind, mapping: dict) -> list:
    if kind.code in mapping:
        return [channel for channel in kinds.EXTERNAL if channel in mapping[kind.code]]
    return [channel for channel in kinds.EXTERNAL if channel in kind.default_channels]


def _defaults_diff(old: dict, new: dict) -> tuple[dict, dict]:
    """«Было / стало» по видам, чей действующий список каналов изменился; ключ — название вида (решение C5)."""
    before, after = {}, {}
    for kind in kinds.catalog():
        if kind.mandatory or _effective_list(kind, old) == _effective_list(kind, new):
            continue
        before[kind.title] = list(old[kind.code]) if kind.code in old else None
        after[kind.title] = list(new[kind.code]) if kind.code in new else None
    return before, after


def update(*, actor, ip=None, **fields) -> NotifySettings:
    """Меняет настройки; журнал `notify.settings_changed` — только изменившиеся поля до и после.

    Ошибка проверки — одна `NotifyError` (первая по порядку полей), ничего не сохраняется.
    """
    bad = set(fields) - _FIELDS
    if bad:
        raise TypeError(f"неожиданные аргументы {sorted(bad)}")
    with transaction.atomic():
        row = NotifySettings.objects.select_for_update().get(pk=1)
        before, after = {}, {}
        new_values = {}
        for field in _ORDER:
            if field not in fields:
                continue
            value = fields[field]
            old = getattr(row, field)
            if field in _SWITCHES:
                new = bool(value)
                channel = field.removesuffix("_enabled")
                if new and not old and not keys_set(channel):
                    raise NotifyError(
                        "keys_missing",
                        f"Канал «{_TITLES[channel]}» нельзя включить: ключи задаются в окружении установки",
                        field=field)
            elif field == "defaults":
                new = _normalized_defaults(value)
            else:
                new = _in_range(field, value)
            if new == old:
                continue
            new_values[field] = new
            if field == "defaults":
                before_defaults, after_defaults = _defaults_diff(old or {}, new)
                if after_defaults or before_defaults:
                    before[field], after[field] = before_defaults, after_defaults
            else:
                before[field], after[field] = old, new
        if new_values:
            for field, new in new_values.items():
                setattr(row, field, new)
            row.save()
        if after:
            audit.record("notify.settings_changed", actor=actor, object_type="notify_settings", object_id="1",
                         before=before, after=after, ip=ip)
        return row


def note_channel_error(channel: str, code: str) -> None:
    """Запоминает последнюю ошибку канала: `{"at": <ISO со смещением>, "code": code}`; журнала нет."""
    with transaction.atomic():
        row = NotifySettings.objects.select_for_update().get(pk=1)
        status = dict(row.channel_status or {})
        status[channel] = {"at": timezone.now().isoformat(), "code": code}
        row.channel_status = status
        row.save(update_fields=["channel_status", "updated_at"])


def clear_channel_error(channel: str) -> None:
    """Удаляет запись об ошибке канала; записи нет — ничего не пишет."""
    with transaction.atomic():
        row = NotifySettings.objects.select_for_update().get(pk=1)
        if channel not in (row.channel_status or {}):
            return
        status = dict(row.channel_status)
        del status[channel]
        row.channel_status = status
        row.save(update_fields=["channel_status", "updated_at"])


def channel_error(channel: str) -> dict | None:
    """Последняя ошибка канала (`at`, `code`) или `None`."""
    status = (get().channel_status or {}).get(channel)
    return dict(status) if status else None
