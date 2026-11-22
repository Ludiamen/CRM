"""Ночная уборка задач по сроку хранения (срез 009, T-9213; FR-696, NFR-715; CONTRACT-009, 10.1).

Удаляются только мягко удалённые задачи, у которых `deleted_at` старше границы (календарное вычитание лет от
сегодня). Вместе с задачей удаляются комментарии и строки файлов; файлы с диска — после фиксации. Непривязанные
файлы старше 24 часов чистятся отдельно. Запись `tasks.retention_purged` — только если что-то удалено; повтор без
ошибок и без лишних записей.
"""
import pathlib

from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import StoredFile
from apps.core.services import audit, files as core_files
from apps.tasks.models import Task, TaskFile
from apps.tasks.services import settings as task_settings

BATCH = 1000
UNBOUND_HOURS = 24


def _paths(rows) -> list[pathlib.Path]:
    result = []
    for row in rows:
        try:
            result.append(core_files.attachment_path(row.file))
        except Exception:  # noqa: BLE001 — путь собирается по состоянию
            pass
    return result


def purge(now=None) -> dict:
    """Удалить задачи с истёкшим сроком хранения и старые непривязанные файлы."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    years = task_settings.get().retention_years
    cutoff = task_settings.years_ago(today, years)
    counts = {"tasks": 0, "comments": 0, "files": 0, "unbound": 0}
    deleted_paths: list[pathlib.Path] = []

    while True:
        with transaction.atomic():
            batch = list(Task.objects.filter(deleted_at__isnull=False, deleted_at__date__lte=cutoff)
                         .order_by("pk")[:BATCH])
            if not batch:
                break
            ids = [task.pk for task in batch]
            file_rows = list(TaskFile.objects.filter(task_id__in=ids).select_related("file"))
            deleted_paths.extend(_paths(file_rows))
            counts["comments"] += sum(task.comments.count() for task in batch)
            counts["files"] += len(file_rows)
            stored_ids = [row.file_id for row in file_rows]
            TaskFile.objects.filter(task_id__in=ids).delete()
            StoredFile.objects.filter(pk__in=stored_ids).delete()
            Task.objects.filter(pk__in=ids).delete()
            counts["tasks"] += len(ids)

    stale_before = now - timezone.timedelta(hours=UNBOUND_HOURS)
    with transaction.atomic():
        stale = list(TaskFile.objects.filter(comment__isnull=True, created_at__lt=stale_before)
                     .select_related("file"))
        if stale:
            deleted_paths.extend(_paths(stale))
            stored_ids = [row.file_id for row in stale]
            TaskFile.objects.filter(pk__in=[row.pk for row in stale]).delete()
            StoredFile.objects.filter(pk__in=stored_ids).delete()
            counts["unbound"] = len(stale)

    if deleted_paths:
        transaction.on_commit(lambda: core_files.remove_paths(deleted_paths), using=connection.alias)
    if counts["tasks"]:
        audit.record("tasks.retention_purged", object_type="tasks.settings", object_id="1",
                     after={"tasks": counts["tasks"], "comments": counts["comments"], "files": counts["files"]})
    return counts