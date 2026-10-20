"""Настройки базы знаний: срок хранения корзины (PLAN-005, «Корзина и ночная очистка»; FR-417)."""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.core.services import audit

from ..models import KnowledgeSettings
from . import SettingsError, access

DEFAULT_TRASH_DAYS = 90
MIN_TRASH_DAYS = 7
MAX_TRASH_DAYS = 365


def get() -> KnowledgeSettings:
    """Строка настроек `pk=1`; если её нет — создаётся со сроком 90 суток."""
    return KnowledgeSettings.objects.get_or_create(pk=1, defaults={"trash_days": DEFAULT_TRASH_DAYS})[0]


def update(user, trash_days: int) -> KnowledgeSettings:
    """Меняет срок корзины (право `knowledge.manage`, 7–365 включительно); журнал `knowledge.trash_days_changed`
    пишется только при изменении значения."""
    if not access.can_manage(user):
        raise PermissionDenied
    try:
        days = int(str(trash_days).strip())
    except (TypeError, ValueError):
        raise SettingsError("out_of_range", "trash_days") from None
    if not MIN_TRASH_DAYS <= days <= MAX_TRASH_DAYS:
        raise SettingsError("out_of_range", "trash_days")
    with transaction.atomic():
        get()
        row = KnowledgeSettings.objects.select_for_update().get(pk=1)
        if row.trash_days == days:
            return row
        before = row.trash_days
        row.trash_days = days
        row.save(update_fields=["trash_days"])
        audit.record("knowledge.trash_days_changed", actor=user, object_type="knowledge.article", object_id="",
                     before={"days": before}, after={"days": days})
    return row
