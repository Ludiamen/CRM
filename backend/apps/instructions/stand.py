"""Сброс данных поручений на стенде (срез 010, T-10008; CONTRACT-010, 1.3).

`stand_reset()` приводит данные поручений к состоянию сразу после миграций:
- стирает таблицы по `TABLES` (зависимые раньше: напоминания, переносы, файлы, части, отчёты, даты, участники,
  связи с задачами, поручения, виды основания, настройки);
- стирает строки `core.StoredFile` назначения `instruction`, собранные по строкам `InstructionFile` до удаления;
- файлы оригиналов удаляет с диска после фиксации (`on_commit` того же алиаса);
- возвращает данные установки: `InstructionSettings(pk=1, retention_years=3, default_ladder=…)` и четыре вида
  основания (`get_or_create` по названию, порядок 0–3).

Идёт под владельцем схемы (алиас `migrate`, если он настроен, иначе `default`) в одной транзакции. На поручения
никто не ссылается, поэтому регистрация точки — последней записью `register_all`, а вызов в общей команде сброса —
первым (функции зовутся в обратном порядке).

Здесь же — проверка стенда `require_stand()` для команд `e2e_instructions_*` (копия образца `tasks`/`messenger`,
не импорт). Модели импортируются внутри `stand_reset`: каркас T-10008 живёт до моделей T-10201.
"""
import os

from django.core.management.base import CommandError

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."

# Порядок стирания: зависимые раньше; файл — до отчёта, части и поручения (`PROTECT` на `StoredFile`).
TABLES = (
    "instructions_instructionreminder",
    "instructions_instructiontransfer",
    "instructions_instructionfile",
    "instructions_instructionreportpart",
    "instructions_instructionreport",
    "instructions_instructionreportdate",
    "instructions_instructionmember",
    "instructions_instructiontask",
    "instructions_instruction",
    "instructions_instructionbasiskind",
    "instructions_instructionsettings",
)
FILE_PURPOSE = "instruction"

BASIS_KINDS = ("Приказ", "Протокол совещания", "Письмо", "Устное указание")
DEFAULT_LADDER = {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


def stand_reset() -> None:
    """Сброс данных поручений под владельцем схемы в одной транзакции (CONTRACT-010, 1.3)."""
    from django.conf import settings as django_settings
    from django.db import connections, transaction

    from apps.core.models import StoredFile
    from apps.core.services import files as core_files

    try:
        from apps.instructions.models import (Instruction, InstructionBasisKind, InstructionFile, InstructionMember,
                                              InstructionReminder, InstructionReport, InstructionReportDate,
                                              InstructionReportPart, InstructionSettings, InstructionTask,
                                              InstructionTransfer)
    except ImportError:
        # Каркас T-10008 до моделей T-10201: таблиц поручений ещё нет, стирать нечего. Ветку снимает T-10201.
        return

    alias = "migrate" if "migrate" in django_settings.DATABASES else "default"

    with transaction.atomic(using=alias):
        anchor = connections[alias]
        paths = []
        for entry in InstructionFile.objects.using(alias).select_related("file"):
            try:
                paths.append(core_files.attachment_path(entry.file))
            except Exception:  # noqa: BLE001 — путь собирается по состоянию; сбой не отменяет сброс
                pass
        for stored in StoredFile.objects.using(alias).filter(purpose=FILE_PURPOSE):
            try:
                paths.append(core_files.attachment_path(stored))
            except Exception:  # noqa: BLE001
                pass
        for model in (InstructionReminder, InstructionTransfer, InstructionFile, InstructionReportPart,
                      InstructionReport, InstructionReportDate, InstructionMember, InstructionTask,
                      Instruction, InstructionBasisKind, InstructionSettings):
            model.objects.using(alias).all().delete()
        StoredFile.objects.using(alias).filter(purpose=FILE_PURPOSE).delete()
        InstructionSettings.objects.using(alias).get_or_create(
            pk=1, defaults={"retention_years": 3, "default_ladder": dict(DEFAULT_LADDER)})
        for position, title in enumerate(BASIS_KINDS):
            InstructionBasisKind.objects.using(alias).get_or_create(title=title, defaults={"position": position})
        transaction.on_commit(lambda: core_files.remove_paths(paths), using=anchor.alias)