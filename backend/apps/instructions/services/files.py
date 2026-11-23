"""Файлы основания, отчётов и частей (срез 010, T-10211; NFR-722; CONTRACT-010, 5.1, 12.1)."""
from apps.core.models import StoredFile
from apps.core.services import files as core_files, uploads
from apps.instructions.models import InstructionFile
from apps.instructions.services import access
from apps.instructions.texts import InstructionsError

MAX_BYTES = 20 * 1024 * 1024
LIMIT = 10
EXECUTABLE = (b"MZ", b"\\x7fELF", b"#!", b"\\xca\\xfe\\xba\\xbe")


def _check_type(data: bytes, name: str) -> None:
    lower = (name or "").lower()
    if lower.endswith((".exe", ".com", ".bat", ".cmd", ".msi", ".scr", ".dll", ".sh")) or data.startswith(EXECUTABLE):
        raise InstructionsError("file_type", "file")
    if data.startswith(b"PK\\x03\\x04") and len(data) > 7 and data[6] & 0x01:
        raise InstructionsError("file_type", "file")
    if data.startswith(b"Rar!\\x1a\\x07"):
        raise InstructionsError("file_type", "file")


def store(actor, instruction, upload, *, kind, report=None, part=None) -> InstructionFile:
    """Принять файл к поручению (основание, отчёт или часть)."""
    if kind not in ("basis", "report", "part"):
        raise InstructionsError("file_missing", "file")
    if kind == "basis":
        allowed = access.can_edit_fields(actor, instruction)
    elif report is not None:
        allowed = access.can_report(actor, instruction, report.date)
    elif part is not None:
        allowed = access.can_add_part(actor, instruction, part.date)
    else:
        from apps.instructions.models import InstructionMember

        allowed = (actor.pk == instruction.assignee_id
                   or InstructionMember.objects.filter(instruction=instruction, user=actor).exists())
    if not allowed:
        raise InstructionsError("file_missing", "file")
    data = upload.read()
    if len(data) > MAX_BYTES:
        raise InstructionsError("file_too_big", "file")
    _check_type(data, getattr(upload, "name", ""))
    if report is not None and InstructionFile.objects.filter(report=report).count() >= LIMIT:
        raise InstructionsError("report_limit", "file")
    if part is not None and InstructionFile.objects.filter(part=part).count() >= LIMIT:
        raise InstructionsError("report_limit", "file")
    stored = uploads.store(data, getattr(upload, "name", "файл"), "instruction")
    return InstructionFile.objects.create(instruction=instruction, kind=kind, report=report, part=part,
                                          file=stored, name=getattr(upload, "name", "файл")[:255],
                                          uploaded_by=actor)


def bind(report=None, part=None, file_ids=()) -> int:
    """Привязать непривязанные файлы к отчёту или части."""
    target = report or part
    if target is None:
        return 0
    instruction = report.instruction if report is not None else part.date.instruction
    rows = list(InstructionFile.objects.filter(pk__in=list(file_ids), instruction=instruction,
                                               report__isnull=True, part__isnull=True))
    if len(rows) > LIMIT:
        raise InstructionsError("report_limit", "file")
    for row in rows:
        if report is not None:
            row.report = report
            row.kind = "report"
        else:
            row.part = part
            row.kind = "part"
        row.save(update_fields=["report", "part", "kind"])
    return len(rows)


def content(instruction, entry: InstructionFile, viewer):
    """Путь к оригиналу для X-Accel; строки `pending`/`quarantine` — состояния проверки."""
    if not access.visible(viewer, instruction):
        from django.http import Http404

        raise Http404
    stored = entry.file
    if stored.status == "pending":
        return "pending"
    if stored.status == "quarantine":
        return "quarantine"
    if stored.status != "clean":
        return None
    return core_files.attachment_path(stored)


def still_waiting(stored) -> bool:
    return stored.status == "pending"


def clean(stored) -> list:
    return uploads.move(stored, StoredFile.Status.CLEAN)


def found(stored, signature: str) -> list:
    return uploads.move(stored, StoredFile.Status.QUARANTINE, signature)


def file_purposes() -> list:
    """Запись точки `file_purposes` ядра для назначения `instruction`."""
    from apps.core.extensions import FilePurpose

    return [FilePurpose(purpose="instruction", still_waiting=still_waiting, clean=clean, found=found)]
