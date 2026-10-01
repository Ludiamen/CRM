"""Политика и пороги безопасности (T-201, FR-027, FR-036, NFR-005).

Значения читаются из базы при каждом обращении, без кэша. Администратор может
только ужесточать утверждённые значения (границы — CONTRACT.md, «Решения Opus»);
значение вне границ — отказ с объяснением, какая граница нарушена.
"""
import re
from dataclasses import dataclass

from django.db import transaction

from apps.core.models import SecuritySettings

from . import audit

FIELDS = (
    "password_min_length", "password_history", "password_max_age_days", "idle_timeout_minutes",
    "account_lock_limit", "account_lock_minutes", "ip_lock_limit", "ip_lock_min_accounts",
    "ip_lock_window_minutes", "ip_lock_minutes", "login_history_days",
)


@dataclass(frozen=True)
class Bound:
    low: int
    high: int
    title: str
    unit: str = ""
    optional: bool = False  # пусто допустимо («нет»)


BOUNDS = {
    "password_min_length": Bound(12, 128, "Минимальная длина пароля", "символов"),
    "password_history": Bound(5, 24, "Запрет повтора последних паролей", "паролей"),
    "password_max_age_days": Bound(30, 365, "Срок действия пароля", "дней", optional=True),
    "idle_timeout_minutes": Bound(5, 60, "Время бездействия до выхода", "минут"),
    "account_lock_limit": Bound(3, 5, "Неудач до блокировки записи", "попыток"),
    "account_lock_minutes": Bound(15, 1440, "Срок блокировки записи", "минут"),
    "ip_lock_limit": Bound(5, 100, "Неудач с адреса до его блокировки", "попыток"),
    "ip_lock_min_accounts": Bound(2, 20, "Разных записей для блокировки адреса", "записей"),
    "ip_lock_window_minutes": Bound(5, 60, "Окно подсчёта неудач с адреса", "минут"),
    "ip_lock_minutes": Bound(15, 1440, "Срок блокировки адреса", "минут"),
    "login_history_days": Bound(30, 365, "Срок хранения истории входов", "дней"),
}


class SettingsError(Exception):
    """Значения вне границ: `errors` — {поле: сообщение}."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def get() -> SecuritySettings:
    """Единственная строка настроек (создаётся миграцией)."""
    return SecuritySettings.objects.get()


def as_dict(row: SecuritySettings) -> dict:
    return {name: getattr(row, name) for name in FIELDS}


def _parse(name: str, raw) -> int | None:
    bound = BOUNDS[name]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if bound.optional:
            return None
        raise ValueError(f"{bound.title}: введите целое число от {bound.low} до {bound.high}.")
    if isinstance(raw, bool) or not (isinstance(raw, int) or (isinstance(raw, str) and re.fullmatch(r"-?\d+", raw.strip()))):
        raise ValueError(f"{bound.title}: нужно целое число от {bound.low} до {bound.high}.")
    value = int(raw)
    if value < bound.low:
        raise ValueError(f"{bound.title}: не меньше {bound.low} {bound.unit} (введено {value}); "
                         f"допустимо от {bound.low} до {bound.high}.")
    if value > bound.high:
        raise ValueError(f"{bound.title}: не больше {bound.high} {bound.unit} (введено {value}); "
                         f"допустимо от {bound.low} до {bound.high}.")
    return value


def validate(data: dict) -> dict:
    """Проверяет форму целиком; при ошибках — SettingsError, ничего не меняя."""
    cleaned, errors = {}, {}
    for name in FIELDS:
        try:
            cleaned[name] = _parse(name, data.get(name))
        except ValueError as e:
            errors[name] = str(e)
    if errors:
        raise SettingsError(errors)
    return cleaned


def update(data: dict, *, actor, ip=None) -> SecuritySettings:
    """Сохраняет форму целиком или не сохраняет; изменение пишется в журнал «было / стало»."""
    cleaned = validate(data)
    with transaction.atomic():
        row = SecuritySettings.objects.select_for_update().get()
        before = as_dict(row)
        for name, value in cleaned.items():
            setattr(row, name, value)
        row.save()
        if before == cleaned:
            return row
        audit.record("security_settings.updated", actor=actor, object_type="security_settings", object_id=row.pk,
                     before=before, after=cleaned, ip=ip)
    return row
