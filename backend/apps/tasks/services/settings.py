"""Настройки задач (срез 009, T-9201/T-9213; FR-696; CONTRACT-009, 6.2, 10.1).

Строка `TaskSettings(pk=1)` создаётся лениво; срок хранения — 1–10 лет, по умолчанию 3. Смена пишет журнал
`tasks.retention_changed` «было/стало». Подсчёт `pending_count` — для второго шага подтверждения при уменьшении
срока: сколько удалённых задач станет старше новой границы (отсчёт от `deleted_at`, календарное вычитание лет).
"""
import datetime

from django.utils import timezone

from apps.core.services import audit
from apps.tasks.models import Task, TaskSettings
from apps.tasks.services.errors import TasksError

MIN_YEARS, MAX_YEARS, DEFAULT_YEARS = 1, 10, 3


def _years_from(value) -> int:
    try:
        years = int(str(value).strip())
    except (TypeError, ValueError):
        raise TasksError("retention_range", "retention_years") from None
    if not MIN_YEARS <= years <= MAX_YEARS:
        raise TasksError("retention_range", "retention_years")
    return years


def years_ago(today: datetime.date, years: int) -> datetime.date:
    """Календарное вычитание лет: 29 февраля переходит на 28 февраля (CONTRACT-009, К17)."""
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 февраля в невисокосный год
        return today.replace(month=2, day=28, year=today.year - years)


def get() -> TaskSettings:
    """Строка настроек `pk=1`; создаётся при первом обращении со сроком 3 года."""
    settings_row, _created = TaskSettings.objects.get_or_create(pk=1, defaults={"retention_years": DEFAULT_YEARS})
    return settings_row


def save(actor, retention_years, *, ip=None) -> TaskSettings:
    """Сохранить срок хранения; пишет журнал только при изменении."""
    years = _years_from(retention_years)
    settings_row = get()
    before = settings_row.retention_years
    if before != years:
        settings_row.retention_years = years
        settings_row.updated_at = timezone.now()
        settings_row.updated_by = actor
        settings_row.save(update_fields=["retention_years", "updated_at", "updated_by"])
        audit.record("tasks.retention_changed", actor=actor, object_type="tasks.settings", object_id="1", ip=ip,
                     before={"years": before}, after={"years": years})
    return settings_row


def pending_count(retention_years) -> int:
    """Сколько удалённых задач станет старше новой границы хранения (для второго шага)."""
    years = _years_from(retention_years)
    cutoff = years_ago(timezone.localdate(), years)
    return Task.objects.filter(deleted_at__isnull=False, deleted_at__date__lt=cutoff).count()