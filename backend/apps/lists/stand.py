"""Сброс данных списков на стенде (PLAN-006, «Данные установки и стенд»; CONTRACT-006, 1.3).

`stand_reset` — функция точки `stand_reset`: возвращает данные среза к состоянию сразу после миграций (`0002_initial_data`).
Стирает файлы записей (строки `RecordFile`, затем их `StoredFile`, затем файл в `incoming/`, `attachments/`,
`quarantine/`), связи с заявками, отметки напоминаний, историю, значения уникальности, записи, выбор столбцов, задания
загрузки, права, значения, поля и списки (поля — до списков: у `Field.target` стоит `RESTRICT`); шесть стартовых списков,
право `lists.manage` и права «Сотрудника ИТ» возвращает функция `seed` миграции 0002. Вложения заявок и файлы статей не
трогаются. Идёт под владельцем схемы (алиас `migrate`) в одной транзакции; файлы на диске стираются после её фиксации
(`on_commit` того же алиаса: прямой вызов после `atomic` стёр бы файл до фиксации, если сброс вложен в чужую транзакцию).
Общая очистка таблиц ядра с каскадом уже могла стереть часть таблиц среза, поэтому функция не рассчитывает на их строки.

Здесь же — проверка стенда `require_stand()` для команд `e2e_lists_*` (образец — `apps.knowledge.stand`; копия, а не
импорт). Регистрация точки в `extensions.py` — вне этого файла.
"""
import importlib
import os
import pathlib
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.db.models.signals import m2m_changed

from apps.core.models import Role, StoredFile
from apps.core.services import files as core_files
from apps.core.services import permissions as core_permissions

from .models import (Access, Change, Choice, Field, ImportJob, List, Record, RecordFile, ReminderSent, TicketLink,
                     UniqueValue, UserView)

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
# Имя модуля начинается с цифры, поэтому `importlib`
_initial = importlib.import_module("apps.lists.migrations.0002_initial_data")


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


def _record_file_paths(db: str) -> list[pathlib.Path]:
    """Пути файлов записей на диске: для каждого `StoredFile` из строк `RecordFile` — по его состоянию проверки."""
    stored_ids = list(RecordFile.objects.using(db).values_list("file_id", flat=True))
    paths = []
    for stored in StoredFile.objects.using(db).filter(pk__in=stored_ids):
        try:
            paths.append(core_files.attachment_path(stored))
        except KeyError:  # состояние без пути на диске
            continue
    return paths


def _erase(db: str) -> list[pathlib.Path]:
    """Стирает данные среза в порядке зависимостей `PROTECT` и `RESTRICT`; возвращает пути файлов для стирания с диска."""
    paths = _record_file_paths(db)
    stored_ids = list(RecordFile.objects.using(db).values_list("file_id", flat=True))
    RecordFile.objects.using(db).all().delete()
    StoredFile.objects.using(db).filter(pk__in=stored_ids).delete()
    for model in (TicketLink, ReminderSent, Change, UniqueValue, Record, UserView, ImportJob, Access, Choice, Field,
                  List):
        model.objects.using(db).all().delete()
    return paths


def _seed(db: str) -> None:
    """Стартовые данные — функцией данных миграции 0002 (реестр `apps`, соединение базы `migrate`).

    Выдача прав ролям шлёт сигнал ядра, обработчик которого читает записи через соединение `default`; после общей очистки
    таблиц ядра (`TRUNCATE`, ещё не зафиксированный) такое чтение ждало бы снятия замка. Обработчик на время вызова
    отключается: ключи прав стирает сама команда сброса (`*perms:*`) в конце.
    """
    through = Role.permissions.through
    uid = "core-perms-role-permissions"
    m2m_changed.disconnect(sender=through, dispatch_uid=uid)
    try:
        _initial.seed(django_apps, SimpleNamespace(connection=connections[db]))
    finally:
        m2m_changed.connect(core_permissions._role_permissions_changed, sender=through, dispatch_uid=uid)


def stand_reset() -> None:
    """Приводит данные среза к состоянию после миграций; идёт под владельцем схемы (алиас `migrate`), если он настроен."""
    db = "migrate" if "migrate" in connections.databases else "default"
    with transaction.atomic(using=db):
        paths = _erase(db)
        _seed(db)
        transaction.on_commit(lambda: core_files.remove_paths(paths), using=db)  # файл без строки лучше строки без файла
