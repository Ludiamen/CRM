"""Сброс данных задач на стенде (срез 009, T-9010; CONTRACT-009, 1.3).

`stand_reset()` приводит данные задач к состоянию сразу после миграций:
- стирает таблицы по `TABLES` (зависимые раньше: `TaskFile`, `TaskComment`, `TaskReminder`, `TaskMember`, `Task`,
  `PlanColumn`, `TaskCategory`, `TaskSettings`);
- стирает строки `core.StoredFile` назначения `task`, собранные по строкам `TaskFile` до их удаления;
- файлы оригиналов удаляет с диска после фиксации (`on_commit` того же алиаса);
- возвращает данные установки: `TaskSettings(pk=1, retention_years=3)`.

Идёт под владельцем схемы (алиас `migrate`, если он настроен, иначе `default`) в одной транзакции. На задачи никто
не ссылается, поэтому регистрация точки — последней записью `register_all`, а вызов в общей команде сброса —
первым (функции зовутся в обратном порядке).

Здесь же — проверка стенда `require_stand()` для команд `e2e_tasks_*` (копия образца `feed`/`messenger`, не импорт).
Модели импортируются внутри `stand_reset`: каркас T-9010 живёт до моделей T-9201.
"""
import os

from django.core.management.base import CommandError

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."

# Порядок стирания: зависимые раньше (файл — до комментария и задачи: `PROTECT` на `StoredFile`).
TABLES = (
    "tasks_taskfile",
    "tasks_taskcomment",
    "tasks_taskreminder",
    "tasks_taskmember",
    "tasks_task",
    "tasks_plancolumn",
    "tasks_taskcategory",
    "tasks_tasksettings",
)
FILE_PURPOSE = "task"


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


def stand_reset() -> None:
    """Сброс данных задач под владельцем схемы в одной транзакции (CONTRACT-009, 1.3)."""
    from django.conf import settings as django_settings
    from django.db import connections, transaction

    from apps.core.models import StoredFile
    from apps.core.services import files as core_files
    from apps.tasks.models import (PlanColumn, Task, TaskCategory, TaskComment, TaskFile, TaskMember,
                                   TaskReminder, TaskSettings)

    alias = "migrate" if "migrate" in django_settings.DATABASES else "default"

    with transaction.atomic(using=alias):
        anchor = connections[alias]
        paths = []
        for entry in TaskFile.objects.using(alias).select_related("file"):
            try:
                paths.append(core_files.attachment_path(entry.file))
            except Exception:  # noqa: BLE001 — путь собирается по состоянию; сбой не отменяет сброс
                pass
        for stored in StoredFile.objects.using(alias).filter(purpose=FILE_PURPOSE):
            try:
                paths.append(core_files.attachment_path(stored))
            except Exception:  # noqa: BLE001
                pass
        for model in (TaskFile, TaskComment, TaskReminder, TaskMember, Task, PlanColumn, TaskCategory, TaskSettings):
            model.objects.using(alias).all().delete()
        StoredFile.objects.using(alias).filter(purpose=FILE_PURPOSE).delete()
        TaskSettings.objects.using(alias).get_or_create(pk=1, defaults={"retention_years": 3})
        transaction.on_commit(lambda: core_files.remove_paths(paths), using=anchor.alias)