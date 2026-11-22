"""T-9118: срок хранения задач — только удалённые, отсчёт от удаления, календарное вычитание лет, файлы и
комментарии, идемпотентность, смена срока в журнале (FR-695, FR-696, NFR-715).

Источники: PLAN-009 «Удаление, срок хранения» (удаляются только задачи с `deleted_at <= today − retention_years`;
вычитание лет календарное, 29 февраля → 28 февраля; вместе с файлами (строки, диск после фиксации) и комментариями;
непривязанные файлы старше 24 часов; одна запись `tasks.retention_purged` только при удалении > 0; повтор без
ошибок; действующие не удаляются); CONTRACT-009: 1.2 (cron `42 23 * * *`, очередь `maintenance`), 2.1 (`TaskSettings`),
5.1 (`retention.purge(now)`, `tasks_retention(now=…)`), 10.1 (`tasks.retention_changed`, `tasks.retention_purged`),
12.1 (`retention_range`, `retention_decrease`), К17 (календарное вычитание), К18.

Задание зовётся синхронно с `now=…`; диск стирается после фиксации — проверка через
`django_capture_on_commit_callbacks`. Код среза импортируется внутри тестов, модели — через `support.model`.
"""
import hashlib
import importlib
import json
import mimetypes
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 22, 23, 42, tzinfo=MSK)
BOUNDARY = datetime(2023, 11, 22, 23, 42, tzinfo=MSK)        # NOW − 3 года (срок по умолчанию)
OLD = BOUNDARY - timedelta(days=30)
YOUNG = BOUNDARY + timedelta(days=10)
DAY = timedelta(days=1)
PURGED = "tasks.retention_purged"
CHANGED = "tasks.retention_changed"
SETTINGS_URL = "/settings/tasks/"


# --- помощники файла ---------------------------------------------------------------------------------------------

def _settings(years: int = 3):
    row, _ = support.model("tasks.TaskSettings").objects.update_or_create(
        pk=1, defaults={"retention_years": years})
    return row


def _purge(now):
    from apps.tasks.tasks import tasks_retention

    return tasks_retention(now=now)


def _audit(action: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _soft(task, author):
    importlib.import_module("apps.tasks.services.tasks").soft_delete(author, task)


def _deleted_at(task, moment):
    support.model("tasks.Task").objects.filter(pk=task.pk).update(deleted_at=moment)


def _created_at(task, moment):
    support.model("tasks.Task").objects.filter(pk=task.pk).update(created_at=moment)


def _attach(task, name="файл.txt", data=b"body", *, status="clean", comment=None, write=False):
    stored = support.model("core.StoredFile").objects.create(
        purpose="task", owner=None, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream", status=status,
        scanned_at=timezone.now() if status != "pending" else None)
    if write:
        from apps.core.services import files as core_files

        path = core_files.attachment_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return support.model("tasks.TaskFile").objects.create(
        task=task, comment=comment, file=stored, name=name, uploaded_by=task.author)


def _path(stored):
    from apps.core.services import files as core_files

    return core_files.attachment_path(stored)


def _world():
    return (tasks_helpers.staff_user(full_name="Автор Срока Задач"),
            tasks_helpers.staff_user(full_name="Исполнитель Срока Задач"))


# --- FR-696: только удалённые и отсчёт от удаления -------------------------------------------------------------

def test_only_deleted_tasks_older_than_retention_are_purged():
    """FR-696 (CONTRACT-009, 5.1): уборка удаляет только мягко удалённые задачи старше срока хранения; действующая
    задача с давним созданием и удалённая недавно остаются, возвращается число удалённых."""
    _settings(3)
    author, assignee = _world()
    old_deleted = tasks_helpers.make_task(author=author, assignee=assignee, title="Старая удалённая")
    _soft(old_deleted, author)
    _deleted_at(old_deleted, OLD)
    active_old = tasks_helpers.make_task(author=author, assignee=assignee, title="Действующая давняя")
    _created_at(active_old, datetime(2020, 1, 10, 12, 0, tzinfo=MSK))
    young_deleted = tasks_helpers.make_task(author=author, assignee=assignee, title="Недавно удалённая")
    _soft(young_deleted, author)
    _deleted_at(young_deleted, YOUNG)

    result = _purge(NOW)

    assert result["tasks"] == 1, f"уборка удалила {result['tasks']}"
    tasks = support.model("tasks.Task").objects
    assert not tasks.filter(pk=old_deleted.pk).exists()
    assert tasks.filter(pk=active_old.pk).exists(), "действующая задача удалена по сроку"
    assert tasks.filter(pk=young_deleted.pk).exists(), "удалённая недавно задача удалена"
    rows = _audit(PURGED)
    assert len(rows) == 1 and rows[0].after.get("tasks") == 1


def test_countdown_starts_at_deleted_at_not_created_at():
    """FR-696 (CONTRACT-009, К17): отсчёт — от даты удаления: свежая по созданию, но давно удалённая задача
    удаляется; давняя по созданию, но недавно удалённая — остаётся."""
    _settings(3)
    author, assignee = _world()
    fresh_but_deleted = tasks_helpers.make_task(author=author, assignee=assignee, title="Свежая, но удалена давно")
    _created_at(fresh_but_deleted, NOW - DAY)
    _soft(fresh_but_deleted, author)
    _deleted_at(fresh_but_deleted, OLD)
    old_but_deleted = tasks_helpers.make_task(author=author, assignee=assignee, title="Давняя, но удалена недавно")
    _created_at(old_but_deleted, datetime(2019, 5, 1, 12, 0, tzinfo=MSK))
    _soft(old_but_deleted, author)
    _deleted_at(old_but_deleted, YOUNG)

    assert _purge(NOW)["tasks"] == 1
    tasks = support.model("tasks.Task").objects
    assert not tasks.filter(pk=fresh_but_deleted.pk).exists()
    assert tasks.filter(pk=old_but_deleted.pk).exists(), "срок посчитан от создания, а не удаления"


def test_calendar_year_subtraction_february_29_becomes_28():
    """FR-696 (CONTRACT-009, К17): вычитание лет календарное — 29 февраля становится 28 февраля: при «сейчас»
    29.02.2028 и сроке 3 года задача, удалённая 28.02.2025, уже удаляется, а удалённая 01.03.2025 — нет."""
    _settings(3)
    author, assignee = _world()
    feb28 = tasks_helpers.make_task(author=author, assignee=assignee, title="Удалена 28 февраля")
    _soft(feb28, author)
    _deleted_at(feb28, datetime(2025, 2, 28, 12, 0, tzinfo=MSK))
    mar1 = tasks_helpers.make_task(author=author, assignee=assignee, title="Удалена 1 марта")
    _soft(mar1, author)
    _deleted_at(mar1, datetime(2025, 3, 1, 12, 0, tzinfo=MSK))

    leap_now = datetime(2028, 2, 29, 23, 0, tzinfo=MSK)
    result = _purge(leap_now)

    assert result["tasks"] == 1, f"уборка 29.02 удалила {result['tasks']}"
    tasks = support.model("tasks.Task").objects
    assert not tasks.filter(pk=feb28.pk).exists(), "28.02.2025 не стало границей для 29.02.2028"
    assert tasks.filter(pk=mar1.pk).exists()


# --- FR-696: файлы и комментарии ---------------------------------------------------------------------------------

def test_files_and_comments_removed_with_task_and_disk_after_commit(protected_root,
                                                                   django_capture_on_commit_callbacks):
    """FR-696 (CONTRACT-009, 5.1): удалённая по сроку задача уходит вместе с комментариями и файлами — строки
    `TaskComment`, `TaskFile`, `StoredFile` в транзакции, файл с диска после фиксации; итог задания считает задачи,
    комментарии и файлы; в журнале одна запись `tasks.retention_purged` без названия задачи."""
    _settings(3)
    author, assignee = _world()
    marker = "Удаляемая по сроку задача"
    task = tasks_helpers.make_task(author=author, assignee=assignee, title=marker)
    comments = importlib.import_module("apps.tasks.services.comments")
    comment = comments.add(author, task, "Комментарий удаляемой задачи")
    item = _attach(task, "старый-файл.txt", b"old", comment=comment, write=True)
    path = _path(item.file)
    stored_id = item.file_id
    _soft(task, author)
    _deleted_at(task, OLD)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        result = _purge(NOW)
    assert result["tasks"] == 1 and result["comments"] == 1 and result["files"] == 1, result
    assert not support.model("tasks.Task").objects.filter(pk=task.pk).exists()
    assert not support.model("tasks.TaskComment").objects.filter(task_id=task.pk).exists()
    assert not support.model("tasks.TaskFile").objects.filter(task_id=task.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=stored_id).exists()
    assert path.exists(), "файл стёрт до фиксации"
    for callback in callbacks:
        callback()
    assert not path.exists(), "файл не стёрт с диска"

    rows = _audit(PURGED)
    assert len(rows) == 1
    assert (rows[0].object_type, rows[0].object_id) == ("tasks.settings", "1")
    assert rows[0].after.get("tasks") == 1 and rows[0].after.get("comments") == 1
    assert marker not in json.dumps([rows[0].before, rows[0].after], ensure_ascii=False)


# --- NFR-715: идемпотентность ----------------------------------------------------------------------------------

def test_second_run_is_idempotent_and_writes_one_audit_record():
    """NFR-715 (CONTRACT-009, 5.1): повторный запуск ничего не удаляет, не падает и не пишет вторую запись
    `tasks.retention_purged`; первая запись с числом задач остаётся одна, свежая удалённая задача цела."""
    _settings(3)
    author, assignee = _world()
    first = tasks_helpers.make_task(author=author, assignee=assignee, title="Старая первая")
    second = tasks_helpers.make_task(author=author, assignee=assignee, title="Старая вторая")
    for task, moment in ((first, OLD), (second, OLD - 5 * DAY)):
        _soft(task, author)
        _deleted_at(task, moment)
    survivor = tasks_helpers.make_task(author=author, assignee=assignee, title="Свежая удалённая")
    _soft(survivor, author)
    _deleted_at(survivor, YOUNG)

    assert _purge(NOW)["tasks"] == 2
    assert _purge(NOW)["tasks"] == 0, "повторный запуск что-то удалил"
    assert support.model("tasks.Task").objects.filter(pk=survivor.pk).exists()
    rows = _audit(PURGED)
    assert len(rows) == 1 and rows[0].after.get("tasks") == 2


# --- FR-696: срок — настройка ----------------------------------------------------------------------------------

def test_retention_years_setting_changes_the_boundary():
    """FR-696 (CONTRACT-009, 2.1): срок хранения — настройка `TaskSettings`; при 5 годах задача, удалённая 2 года
    назад, остаётся, при 2 годах — удаляется в той же уборке."""
    _settings(5)
    author, assignee = _world()
    task = tasks_helpers.make_task(author=author, assignee=assignee, title="Два года назад")
    _soft(task, author)
    _deleted_at(task, datetime(2024, 1, 15, 12, 0, tzinfo=MSK))

    assert _purge(NOW)["tasks"] == 0, "срок 5 лет удалил двухлетнюю задачу"
    assert support.model("tasks.Task").objects.filter(pk=task.pk).exists()

    _settings(2)
    assert _purge(NOW)["tasks"] == 1
    assert not support.model("tasks.Task").objects.filter(pk=task.pk).exists()


def test_settings_save_writes_retention_changed_with_years_before_and_after():
    """FR-696 (CONTRACT-009, 10.1, 12.1): смена срока хранения на `/settings/tasks/` пишет
    `tasks.retention_changed` с «было/стало» по ключу `years`; значение сохраняется в строке `pk=1`."""
    _settings(3)
    admin = support.make_admin(full_name="Администратор Срока")
    client = support.logged_in(admin)
    response = client.post(SETTINGS_URL, {"retention_years": "5", "confirm": "1"})
    assert response.status_code == 302, f"сохранение срока: {response.status_code}"
    assert support.model("tasks.TaskSettings").objects.get(pk=1).retention_years == 5

    rows = _audit(CHANGED)
    assert len(rows) == 1, f"записей tasks.retention_changed: {len(rows)}"
    assert (rows[0].object_type, rows[0].object_id) == ("tasks.settings", "1")
    assert rows[0].before.get("years") == 3 and rows[0].after.get("years") == 5, (
        f"было/стало: {rows[0].before} / {rows[0].after}")

    refused = client.post(SETTINGS_URL, {"retention_years": "11", "confirm": "1"})
    assert refused.status_code == 200
    assert "Срок хранения — от 1 до 10 лет" in refused.content.decode("utf-8")
    assert support.model("tasks.TaskSettings").objects.get(pk=1).retention_years == 5