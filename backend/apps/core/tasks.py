"""Задания проверки файлов в очереди `files` (T-2216, FR-132, NFR-105; CONTRACT-002 § 3).

`scan_file` отдаёт файл антивирусу и записывает итог; `requeue_pending_scans` раз в час подбирает ожидающие
файлы без задания; `purge_quarantine` ночью стирает файлы карантина старше 30 суток. Ни путь, ни содержимое
файла не попадают в журнал событий и в логи.
"""
import logging
from datetime import timedelta

import django_rq
from django.db import transaction
from django.utils import timezone

from apps.core.models import StoredFile, User
from apps.core.services import audit, files
from apps.integrations.clamav import services as clamav

logger = logging.getLogger(__name__)

# Файл в карантине живёт столько, потом стирается с диска (строка остаётся)
QUARANTINE_KEEP = timedelta(days=30)
# Ожидающий файл без задания подбирается, когда он ждёт дольше этого срока
PENDING_GRACE = timedelta(hours=1)


def _still_waiting(stored: StoredFile, owner: User) -> bool:
    return stored.status == StoredFile.Status.PENDING and owner.photo_pending_id == stored.pk


def scan_file(file_id: str) -> None:
    """Проверяет файл антивирусом и записывает итог (чисто — фото переключается, найдено — карантин).

    Нет строки, файл уже не `pending` или не `photo_pending` владельца — выход без изменений. Недоступный
    антивирус: попытка и ошибка фиксируются, затем исключение идёт наружу — очередь повторит задание.
    """
    stored = StoredFile.objects.select_related("owner").filter(pk=file_id).first()
    if stored is None or not _still_waiting(stored, stored.owner):
        return
    try:
        result = clamav.scan(files.photo_path(stored))
    except clamav.ScanUnavailable:
        # Исключение поднимается после выхода из `atomic`: попытка успевает зафиксироваться
        with transaction.atomic():
            row = StoredFile.objects.select_for_update().filter(pk=file_id).first()
            if row is not None:
                row.attempts += 1
                row.last_error = "антивирус недоступен"
                row.save(update_fields=["attempts", "last_error"])
        logger.warning("scan_file: антивирус недоступен, файл %s, попытка %s", file_id,
                       row.attempts if row else "-")
        raise
    leftovers: list = []
    with transaction.atomic():
        # Порядок замков как в upload_photo/delete_photo: сначала владелец, потом файл (иначе взаимная блокировка)
        owner = User.objects.select_for_update().get(pk=stored.owner_id)
        row = StoredFile.objects.select_for_update().filter(pk=file_id).first()
        if row is None:
            return
        if not _still_waiting(row, owner):
            return
        if result.clean:
            leftovers = files.finish_clean(row, owner)
        else:
            files.finish_quarantine(row, owner, result.signature)
    files.remove_paths(leftovers)


def enqueue_scan(stored_id) -> None:
    """Ставит `scan_file` в очередь `files` после фиксации транзакции, с повторами по плану."""
    from rq import Retry

    queue = django_rq.get_queue(files.QUEUE, commit_mode="on_db_commit")
    queue.enqueue(scan_file, str(stored_id), retry=Retry(max=files.RETRY_MAX, interval=files.RETRY_INTERVALS))


def _queued_ids(queue) -> set[str]:
    """Номера файлов, у которых есть задание в очереди, отложенных и выполняемых."""
    from rq.job import Job

    ids = [job.args[0] for job in queue.jobs if job.args]
    for registry in (queue.scheduled_job_registry, queue.started_job_registry):
        for job_id in registry.get_job_ids():
            job = Job.fetch(job_id, connection=queue.connection)
            if job.func_name == "apps.core.tasks.scan_file" and job.args:
                ids.append(job.args[0])
    return set(ids)


def requeue_pending_scans() -> int:
    """Ставит проверку ожидающим дольше часа файлам без задания; возвращает число поставленных."""
    queue = django_rq.get_queue(files.QUEUE)
    queued = _queued_ids(queue)
    cutoff = timezone.now() - PENDING_GRACE
    count = 0
    for stored in StoredFile.objects.filter(status=StoredFile.Status.PENDING, created_at__lt=cutoff):
        if str(stored.pk) in queued:
            continue
        enqueue_scan(stored.pk)
        count += 1
    return count


def purge_quarantine() -> int:
    """Стирает файлы карантина старше 30 суток; строка остаётся. Возвращает число стёртых файлов."""
    cutoff = timezone.now() - QUARANTINE_KEEP
    count = 0
    for stored in StoredFile.objects.filter(status=StoredFile.Status.QUARANTINE, scanned_at__lt=cutoff):
        path = files.photo_path(stored)
        if path.exists():
            path.unlink()
            count += 1
        User.objects.filter(photo_pending=stored).update(photo_pending=None)
    return count
