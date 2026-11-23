"""Срок хранения поручений (срез 010, T-10213; NFR-729; CONTRACT-010, 5.1, 14).

Удаляются только снятые с контроля поручения старше срока хранения (календарное вычитание лет, К14), вместе с
отчётами, частями, файлами и переносами; строки `StoredFile` назначения `instruction` — с диском после фиксации.
Неснятые не удаляются никогда; повторный запуск идемпотентен.
"""
from django.db import transaction
from django.utils import timezone

from apps.core.models import StoredFile
from apps.core.services import audit, files as core_files
from apps.instructions.models import (Instruction, InstructionFile, InstructionReminder, InstructionReport,
                                      InstructionReportDate, InstructionReportPart, InstructionTransfer)
from apps.instructions.services import settings as settings_service

OBJECT_TYPE = "instructions.settings"


@transaction.atomic
def purge(now=None) -> dict:
    """Убрать закрытые поручения по сроку; вернуть счётчики."""
    now = now or timezone.now()
    years = settings_service.get().retention_years
    cutoff = settings_service.cutoff(years, now)
    rows = list(Instruction.objects.filter(closed_at__lt=cutoff, deleted_at__isnull=True))
    result = {"instructions": 0, "reports": 0, "parts": 0, "files": 0, "transfers": 0}
    if not rows:
        return result
    paths = []
    stored_ids = []
    for row in rows:
        entries = list(InstructionFile.objects.filter(instruction=row).select_related("file"))
        for entry in entries:
            stored_ids.append(entry.file_id)
            try:
                paths.append(core_files.attachment_path(entry.file))
            except Exception:  # noqa: BLE001 — путь собирается по состоянию
                pass
        result["reports"] += InstructionReport.objects.filter(instruction=row).count()
        result["parts"] += InstructionReportPart.objects.filter(date__instruction=row).count()
        result["files"] += len(entries)
        result["transfers"] += InstructionTransfer.objects.filter(instruction=row).count()
        result["instructions"] += 1
    ids = [row.pk for row in rows]
    InstructionReminder.objects.filter(instruction_id__in=ids).delete()
    Instruction.objects.filter(pk__in=ids).delete()
    StoredFile.objects.filter(pk__in=stored_ids, purpose="instruction").delete()
    from django.db import connection

    transaction.on_commit(lambda: core_files.remove_paths(paths), using=connection.alias)
    audit.record("instructions.retention_purged", object_type=OBJECT_TYPE, object_id="1",
                 after={"instructions": result["instructions"], "reports": result["reports"],
                        "files": result["files"]})
    return result
