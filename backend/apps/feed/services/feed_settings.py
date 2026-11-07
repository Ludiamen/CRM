"""Настройки ленты: срок хранения записей (срез 007; CONTRACT-007, 2.2, 2.3, 5.5).

Уменьшение срока — только с подтверждением (второй шаг страницы настройки): без него
служба возвращает число записей, которые удалит ближайшее ночное задание, и не меняет
строку. Журнал ``feed.retention_changed`` пишется при реальном изменении — «было /
стало» в годах (CONTRACT-007, 8.1). Строка замыкается ``select_for_update``:
конкурентные сохранения читают одно и то же «было» под замком.
"""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.feed.models import FeedSettings
from apps.feed.services import retention
from apps.feed.services.errors import FeedError

DEFAULT_YEARS = 3     # строка первой установки (миграция данных, план)
MIN_YEARS = 1        # границы срока, план «Настройка»
MAX_YEARS = 10
ACTION = "feed.retention_changed"


@dataclass(frozen=True)
class SaveResult:
    """Итог сохранения: сохранено ли значение и сколько записей удалит уменьшение без подтверждения."""

    saved: bool
    to_delete: int | None = None


def get() -> FeedSettings:
    """Возвращает единственную строку настроек, создавая её при отсутствии."""
    row, _ = FeedSettings.objects.get_or_create(pk=1, defaults={"retention_years": DEFAULT_YEARS})
    return row


def _locked() -> FeedSettings:
    """Строка настроек под замком: существует всегда (миграция), создаётся на всякий случай."""
    row = FeedSettings.objects.select_for_update().filter(pk=1).first()
    if row is None:
        row = FeedSettings.objects.create(pk=1, retention_years=DEFAULT_YEARS)
    return row


def save(actor, years: int, *, confirmed: bool = False, now=None) -> SaveResult:
    """Сохраняет срок хранения 1–10 лет; уменьшение — только с подтверждением.

    Вне 1–10 — ``FeedError("retention_range", "retention_years")``. Уменьшение без
    ``confirmed`` не трогает строку и возвращает ``to_delete`` — число записей,
    которые удалит ночное задание по новой границе в тот же ``now`` (CONTRACT-007, 5.5).
    Изменение пишет журнал ``feed.retention_changed`` и ``updated_at`` / ``updated_by``;
    неизменное значение не журналируется. Всё — одной транзакцией под замком строки.
    """
    if not isinstance(years, int) or isinstance(years, bool) or not MIN_YEARS <= years <= MAX_YEARS:
        raise FeedError("retention_range", "retention_years")
    if now is None:
        now = timezone.now()
    with transaction.atomic():
        row = _locked()
        current = row.retention_years
        if years < current and not confirmed:
            return SaveResult(saved=False, to_delete=retention.count_older(years, now))
        if years != current:
            row.retention_years = years
            row.updated_at = now
            row.updated_by = actor
            row.save(update_fields=["retention_years", "updated_at", "updated_by"])
            audit.record(ACTION, actor=actor, object_type="feed.settings", object_id=row.pk,
                         before={"years": current}, after={"years": years})
        return SaveResult(saved=True)
