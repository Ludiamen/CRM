"""Сброс и заполнение стенда для ленты (срез 007; CONTRACT-007, 1.3, план «Стенд и приёмка»).

`stand_reset` — функция точки `stand_reset`: приводит данные ленты к состоянию сразу после
миграций (`0002_initial_data`). Стирает таблицы ленты (зависимые раньше: `FeedFile`, `CommentLike`,
`FeedComment`, `PostLike`, `ReadMark`, `EventAnswer`, `Shown`, `Recipient`, `Post`, `FeedSettings`
— К7), строки `core.Comment` с `object_ref` `feed.post:…` — и «осиротевшие», если общий сброс ядра
уже стёр `FeedComment` (решение 53); комментарии других модулей не трогает. Файлы ленты: пути
оригиналов и эскизов собираются по строкам `FeedFile`/`StoredFile`, пока они есть, строки
`FeedFile` и их `StoredFile` стираются сразу, диск — после фиксации (`on_commit` того же алиаса,
К-9 CONTRACT-006); каталог эскизов `attachments/thumbs/` стирается целиком (эскизы есть только
у ленты). Возвращает `seed(stand=True)`: «Писать всем» — всем ролям, «Модерировать ленты» —
«Администратору портала», `FeedSettings(pk=1, retention_years=3)`; на время вызова обработчик
`m2m_changed` ядра `core-perms-role-permissions` отключается и возвращается в `finally`
(раздел «Права и данные установки»). Идёт под владельцем схемы (алиас `migrate`) в одной
транзакции; на ленту никто не ссылается, поэтому регистрация — последней, а вызов — первым.

Здесь же — проверка стенда `require_stand()` для команд `e2e_feed_*` (копия образца `lists`,
не импорт). Регистрация точки в `extensions.py` — вне этого файла.
"""
import importlib
import os
import pathlib
import shutil
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.db.models.signals import m2m_changed

from apps.core.models import Comment, Role, StoredFile
from apps.core.services import files as core_files
from apps.core.services import permissions as core_permissions

from .models import (CommentLike, EventAnswer, FeedComment, FeedFile, FeedSettings, Post, PostLike,
                     ReadMark, Recipient, Shown)

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
# Имя модуля начинается с цифры, поэтому `importlib`
_initial = importlib.import_module("apps.feed.migrations.0002_initial_data")


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


def _feed_file_paths(db: str) -> tuple[list[pathlib.Path], list[int]]:
    """Пути файлов ленты на диске (оригиналы и эскизы) и номера их `StoredFile` — по строкам `FeedFile`."""
    paths: list[pathlib.Path] = []
    stored_ids: list[int] = []
    for row in FeedFile.objects.using(db).select_related("file"):
        stored_ids.append(row.file_id)
        try:
            paths.append(core_files.attachment_path(row.file))  # путь зависит от состояния проверки
        except KeyError:  # состояние без пути на диске
            pass
        if row.thumb:
            paths.append(pathlib.Path(settings.PROTECTED_ROOT) / row.thumb)
    return paths, stored_ids


def _erase(db: str) -> list[pathlib.Path]:
    """Стирает таблицы ленты в порядке зависимостей (К7); возвращает пути файлов для стирания с диска."""
    paths, stored_ids = _feed_file_paths(db)
    FeedFile.objects.using(db).all().delete()
    if stored_ids:
        StoredFile.objects.using(db).filter(pk__in=stored_ids).delete()
    for model in (CommentLike, FeedComment, PostLike, ReadMark, EventAnswer, Shown, Recipient, Post,
                  FeedSettings):
        model.objects.using(db).all().delete()
    # комментарии ленты — и «осиротевшие», без строки FeedComment (решение 53); чужие модули не трогаем
    Comment.objects.using(db).filter(object_ref__startswith="feed.post:").delete()
    return paths


def _seed(db: str) -> None:
    """Стартовые данные ленты — функцией данных миграции 0002 (`seed(stand=True)`, реестр `apps`).

    Выдача прав ролям шлёт сигнал ядра, обработчик которого читает записи через соединение
    `default`; после общей очистки таблиц ядра (`TRUNCATE`, ещё не зафиксированный) такое чтение
    ждало бы снятия замка. Обработчик на время вызова отключается и возвращается в `finally`.
    """
    through = Role.permissions.through
    uid = "core-perms-role-permissions"
    m2m_changed.disconnect(sender=through, dispatch_uid=uid)
    try:
        _initial.seed(django_apps, SimpleNamespace(connection=connections[db]), stand=True)
    finally:
        m2m_changed.connect(core_permissions._role_permissions_changed, sender=through, dispatch_uid=uid)


def _wipe_disk(paths) -> None:
    """Стирает файлы ленты и весь каталог эскизов после фиксации; отсутствующее — не ошибка."""
    core_files.remove_paths(paths)
    shutil.rmtree(pathlib.Path(settings.PROTECTED_ROOT) / "attachments" / "thumbs", ignore_errors=True)


def stand_reset() -> None:
    """Приводит данные ленты к состоянию после миграций; идёт под владельцем схемы (алиас `migrate`)."""
    db = "migrate" if "migrate" in connections.databases else "default"
    with transaction.atomic(using=db):
        paths = _erase(db)
        _seed(db)
        transaction.on_commit(lambda: _wipe_disk(paths), using=db)  # файл без строки лучше строки без файла
