"""Второй фактор записи: единая точка для TOTP и резервных кодов (T-214, T-215)."""
from . import backup_codes, totp


def issue_backup_codes(user, *, actor=None, ip=None) -> list[str]:
    """Выпускает новый набор из 10 открытых кодов, гасит прежний, создаёт и подтверждает `BackupCodeDevice`."""
    return backup_codes.issue(user, actor=actor, ip=ip)


def has_second_factor(user) -> bool:
    """Есть ли у записи подтверждённый второй фактор (иначе — ограниченная сессия)."""
    return totp.has_confirmed(user)


def verify_code(user, code: str) -> bool:
    return totp.verify(user, code)


def verify_backup_code(user, code: str) -> bool:
    return backup_codes.verify(user, code)
