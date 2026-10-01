"""Журнал событий: запись только из сервисов (T-210, FR-044…046, инвариант «аудит-изменений»).

Журнал только дописывается: у роли приложения в базе нет UPDATE и DELETE на таблицу.
Пароли, ключи и коды в «было / стало» не попадают: значения таких полей скрываются.
"""
from django.utils import timezone

from apps.core.models import AuditEvent

HIDDEN = "***"

# Имена полей, значения которых скрываются (точное совпадение, без учёта регистра).
SECRET_FIELDS = frozenset({
    "password", "password1", "password2", "current_password", "new_password", "password_hash", "token", "token_hash",
    "secret", "key", "key_encrypted", "totp_key", "code", "codes", "backup_code", "backup_codes", "code_hash",
    "code_encrypted", "pepper", "link", "url",
})


def _scrub(value):
    if isinstance(value, dict):
        return {k: (HIDDEN if str(k).lower() in SECRET_FIELDS else _scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def record(action: str, *, actor=None, object_type: str = "", object_id="", before=None, after=None, ip=None):
    """Записывает событие. `object_id` — строка; `actor` пуст у «системы»."""
    return AuditEvent.objects.create(
        at=timezone.now(),
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id not in (None, "") else "",
        before=_scrub(before or {}),
        after=_scrub(after or {}),
        ip=ip or None,
    )
