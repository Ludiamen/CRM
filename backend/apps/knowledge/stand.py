"""Очистка данных среза командой стенда (PLAN-005, «Проход в браузере»; CONTRACT-005, 1.3, 13).

`stand_reset` — функция точки `stand_reset`: возвращает данные среза к состоянию сразу после миграций (`0002_initial_data`):
стирает статьи, версии, рубрики (кроме «Общее»), теги, связи со статьями (файлы, заявки), подписки на рубрики, комментарии
ядра с `object_ref`, начинающимся с `knowledge.article:`, и файлы статей (строка `ArticleFile`, затем `StoredFile`, затем
файл в `incoming/`, `attachments/`, `quarantine/`); рубрику «Общее», `KnowledgeSettings` и права возвращает функция `seed`
миграции 0002 (решение 27). Вложения заявок и чужие комментарии не трогаются; очередь `files` не чистится: задания проверки
удалённых файлов выходят тихо. Идёт под владельцем схемы (алиас `migrate`). Общая очистка таблиц ядра с каскадом уже могла
стереть часть таблиц среза, поэтому функция не рассчитывает на их строки.

Здесь же — проверка стенда `require_stand()` для команд `e2e_kb_*` (образец — команды `notify`; копия, а не импорт).
Регистрация точки в `extensions.py` — вне этого файла.
"""
import importlib
import os
import pathlib
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.core.management.base import CommandError
from django.db import connections, transaction
from django.db.models.signals import m2m_changed

from apps.core.models import Comment, Role, StoredFile
from apps.core.services import files as core_files
from apps.core.services import permissions as core_permissions

from .models import (Article, ArticleFile, ArticleVersion, Rubric, RubricSubscription, Tag, TicketLink)

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
COMMENT_PREFIX = "knowledge.article:"
# Имя модуля начинается с цифры, поэтому `importlib`
_initial = importlib.import_module("apps.knowledge.migrations.0002_initial_data")


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


def _article_file_paths(db: str) -> list[pathlib.Path]:
    """Пути файлов статей на диске: для каждого `StoredFile` из строк `ArticleFile` — по его состоянию проверки."""
    stored_ids = list(ArticleFile.objects.using(db).values_list("file_id", flat=True))
    paths = []
    for stored in StoredFile.objects.using(db).filter(pk__in=stored_ids):
        try:
            paths.append(core_files.attachment_path(stored))
        except KeyError:  # состояние без пути на диске
            continue
    return paths


def _erase(db: str) -> list[pathlib.Path]:
    """Стирает данные среза в порядке зависимостей `PROTECT`; возвращает пути файлов статей для стирания с диска."""
    paths = _article_file_paths(db)
    Comment.objects.using(db).filter(object_ref__startswith=COMMENT_PREFIX).delete()
    stored_ids = list(ArticleFile.objects.using(db).values_list("file_id", flat=True))
    ArticleFile.objects.using(db).all().delete()
    StoredFile.objects.using(db).filter(pk__in=stored_ids).delete()
    TicketLink.objects.using(db).all().delete()
    RubricSubscription.objects.using(db).all().delete()
    ArticleVersion.objects.using(db).all().delete()
    Article.objects.using(db).all().delete()
    Tag.objects.using(db).all().delete()
    for depth in sorted(set(Rubric.objects.using(db).filter(is_default=False).values_list("depth", flat=True)),
                        reverse=True):  # глубокие раньше: родитель защищён `PROTECT`
        Rubric.objects.using(db).filter(is_default=False, depth=depth).delete()
    return paths


def _seed(db: str) -> None:
    """«Общее», `KnowledgeSettings` и права — функцией данных миграции 0002 (реестр `apps`, алиас базы `migrate`).

    Выдача прав ролям шлёт сигнал ядра, обработчик которого читает записи через соединение `default`; после общей очистки
    таблиц ядра (`TRUNCATE`, ещё не зафиксированный) такое чтение ждало бы снятия замка. Обработчик на время вызова
    отключается: ключи прав стирает сама команда сброса (`*perms:*`) в конце.
    """
    through = Role.permissions.through
    uid = "core-perms-role-permissions"
    m2m_changed.disconnect(sender=through, dispatch_uid=uid)
    try:
        _initial.seed(django_apps, SimpleNamespace(connection=SimpleNamespace(alias=db)))
    finally:
        m2m_changed.connect(core_permissions._role_permissions_changed, sender=through, dispatch_uid=uid)


def stand_reset() -> None:
    """Приводит данные среза к состоянию после миграций; идёт под владельцем схемы (алиас `migrate`), если он настроен."""
    db = "migrate" if "migrate" in connections.databases else "default"
    with transaction.atomic(using=db):
        paths = _erase(db)
        _seed(db)
    core_files.remove_paths(paths)  # после фиксации: файл без строки лучше строки без файла
