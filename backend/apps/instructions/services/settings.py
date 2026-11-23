"""Настройки поручений (срез 010, T-10201/T-10213; FR-701, FR-709, NFR-729; CONTRACT-010, 5.1, 10.1).

Одна строка `pk=1`: срок хранения (1–10, по умолчанию 3) и умолчание лестницы. Смена срока пишется в журнал
`instructions.retention_changed` «было / стало». Отсчёт уборки — календарное вычитание лет (К14).
"""
import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.services import audit
from apps.instructions.models import Instruction, InstructionSettings
from apps.instructions.texts import InstructionsError

DEFAULT_LADDER = {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}
OBJECT_TYPE = "instructions.settings"
OBJECT_ID = "1"


def get() -> InstructionSettings:
    """Единственная строка настроек; при отсутствии создаётся с умолчаниями."""
    row, _ = InstructionSettings.objects.get_or_create(
        pk=1, defaults={"retention_years": 3, "default_ladder": dict(DEFAULT_LADDER)})
    return row


def validate_ladder(value) -> dict:
    """Проверить лестницу: `offsets` 1–60 по возрастанию без повторов, `due`/`overdue` — булевы."""
    if value in (None, {}):
        return dict(DEFAULT_LADDER)
    if not isinstance(value, dict):
        raise InstructionsError("ladder_invalid", "ladder")
    offsets = value.get("offsets", [])
    if not isinstance(offsets, (list, tuple)) or not offsets:
        raise InstructionsError("ladder_invalid", "ladder")
    cleaned = []
    for item in offsets:
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= 60:
            raise InstructionsError("ladder_invalid", "ladder")
        cleaned.append(item)
    if cleaned != sorted(cleaned) or len(set(cleaned)) != len(cleaned):
        raise InstructionsError("ladder_invalid", "ladder")
    for name in ("due", "overdue"):
        if not isinstance(value.get(name, True), bool):
            raise InstructionsError("ladder_invalid", "ladder")
    return {"offsets": cleaned, "due": bool(value.get("due", True)), "overdue": bool(value.get("overdue", True))}


@transaction.atomic
def save(actor, *, retention_years=None, default_ladder=None) -> InstructionSettings:
    """Сохранить срок хранения и/или умолчание лестницы; при смене срока — запись журнала."""
    row = get()
    before_years, before_ladder = row.retention_years, row.default_ladder
    if retention_years is not None:
        try:
            years = int(retention_years)
        except (TypeError, ValueError):
            raise InstructionsError("retention_range", "retention_years") from None
        if not 1 <= years <= 10:
            raise InstructionsError("retention_range", "retention_years")
        row.retention_years = years
    if default_ladder is not None:
        row.default_ladder = validate_ladder(default_ladder)
    if row.retention_years == before_years and row.default_ladder == before_ladder:
        return row
    row.updated_at = timezone.now()
    row.updated_by = actor
    row.save(update_fields=["retention_years", "default_ladder", "updated_at", "updated_by"])
    if row.retention_years != before_years:
        audit.record("instructions.retention_changed", actor=actor, object_type=OBJECT_TYPE, object_id=OBJECT_ID,
                     before={"years": before_years}, after={"years": row.retention_years})
    if row.default_ladder != before_ladder:
        audit.record("instructions.retention_changed", actor=actor, object_type=OBJECT_TYPE, object_id=OBJECT_ID,
                     before={"ladder": before_ladder}, after={"ladder": row.default_ladder})
    return row


def _minus_years(day: datetime.date, years: int) -> datetime.date:
    """Календарное вычитание лет: 29.02 → 28.02 (К14)."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def cutoff(years: int, now=None) -> datetime.datetime:
    """Начало дня срока хранения по Москве."""
    local = timezone.localtime(now or timezone.now())
    day = _minus_years(local.date(), years)
    return datetime.datetime.combine(day, datetime.time(0), tzinfo=local.tzinfo)


def purge_count(years: int, now=None) -> int:
    """Сколько снятых поручений старше нового срока хранения (для второго шага уменьшения)."""
    return Instruction.objects.filter(closed_at__lt=cutoff(years, now), deleted_at__isnull=True).count()