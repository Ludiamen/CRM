"""T-9124: сброс стенда задач и проверка стенда (FR-674…FR-699; CONTRACT-009, 1.3).

План: «Проверка» → «данные установки и стенд»; «Удаление, срок хранения» (файлы задач в томе `protected`).
Контракт: 1.3 (точка `stand_reset` модуля `tasks`: транзакция, таблицы, файлы, восстановление, порядок,
`require_stand`), 2.1 (`TaskSettings`), 15 (К-решения). Сброс проверяется прямым вызовом
`apps.tasks.stand.stand_reset()`; данные создаются и читаются через соединение `migrate` (как `test_messenger_stand.py`),
«после фиксации» проверяется внутри `django_capture_on_commit_callbacks`. Код среза импортируется внутри тестов —
`pytest --collect-only` проходит до появления моделей и `stand_reset`.
"""
import contextlib
from datetime import timedelta

import pytest
from django.core.management.base import CommandError
from django.db import connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
TABLES = ("TaskFile", "TaskComment", "TaskReminder", "TaskMember", "Task", "PlanColumn", "TaskCategory",
          "TaskSettings")


# --- помощники сброса (свои: фабрики support_tasks пишут через `default`) ---------------------------------

def _on(label: str):
    return support.model(label).objects.using("migrate")


def _person(name: str):
    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name=name, state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _stored(status: str, data: bytes, *, purpose: str = "task", write: bool = True):
    """`StoredFile` через `migrate` и путь его файла на диске (`incoming/`, `attachments/`, `quarantine/`)."""
    from apps.core.services import files as core_files

    stored = _on("core.StoredFile").create(
        purpose=purpose, owner=None, size=len(data), sha256="0" * 64, content_type="application/octet-stream",
        status=status, scanned_at=timezone.now() if status != "pending" else None)
    path = core_files.attachment_path(stored)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return stored, path


def _stand_data(author, reader, protected_root) -> dict:
    """По строке во всех таблицах `tasks` через `migrate`: категория, колонка плана, задача с участником, комментарием,
    напоминанием и вложениями во всех состояниях проверки; настройка со сроком 7 лет; `kept` — файл другого
    назначения."""
    now = timezone.now()
    category = _on("tasks.TaskCategory").create(title="Работа", position=0)
    column = _on("tasks.PlanColumn").create(user=author, title="Сегодня", position=0)
    task = _on("tasks.Task").create(
        title="Задача стенда", description="Описание задачи стенда", deadline=now.date() + timedelta(days=3),
        author=author, assignee=reader, status="in_progress", category=category, plan_column=column)
    _on("tasks.TaskMember").create(task=task, user=author, role="observer")
    comment = _on("tasks.TaskComment").create(task=task, author=reader, text="Комментарий стенда")
    _on("tasks.TaskReminder").create(task=task, user=reader, kind="manual", moment=now + timedelta(days=1),
                                     state="pending")
    _on("tasks.TaskSettings").update_or_create(
        pk=1, defaults={"retention_years": 7, "updated_by": author, "updated_at": now})

    files = []
    for index, status in enumerate(("pending", "clean", "quarantine")):
        stored, path = _stored(status, f"task body {status}".encode())
        row = _on("tasks.TaskFile").create(task=task, comment=comment if index == 0 else None, file=stored,
                                           name=f"файл-{status}.txt", uploaded_by=author)
        files.append({"stored": stored, "path": path, "row": row, "write": True})
    stored, path = _stored("clean", b"ghost task body", write=False)
    row = _on("tasks.TaskFile").create(task=task, comment=None, file=stored, name="без файла.txt", uploaded_by=author)
    files.append({"stored": stored, "path": path, "row": row, "write": False})

    kept_stored, kept_path = _stored("clean", b"other purpose", purpose="attachment")
    kept_path.parent.mkdir(parents=True, exist_ok=True)
    kept_path.write_bytes(b"other purpose")
    return {"task": task, "category": category, "column": column, "comment": comment, "files": files,
            "kept": (kept_stored, kept_path)}


def _counts() -> dict[str, int]:
    return {name: _on(f"tasks.{name}").count() for name in TABLES}


def _row_state():
    settings = list(_on("tasks.TaskSettings").order_by("pk").values_list(
        "pk", "retention_years", "updated_by_id", "updated_at"))
    categories = list(_on("tasks.TaskCategory").order_by("pk").values_list("title", flat=True))
    return settings, categories


@contextlib.contextmanager
def _commit_callbacks(capture):
    with capture(using="default", execute=True) as on_default, \
            capture(using="migrate", execute=True) as on_migrate:
        yield on_default, on_migrate


# --- восстановление данных установки ----------------------------------------------------------------------

@MIGRATE
def test_stand_reset_returns_settings_and_does_not_restore_categories(protected_root,
                                                                     django_capture_on_commit_callbacks):
    """FR-696 (CONTRACT-009, 1.3): после сброса — одна строка `TaskSettings(pk=1, retention_years=3)` без «кто и
    когда менял»; категории — данные администратора и сбросом не возвращаются; повторный сброс даёт то же состояние
    и ничего не дублирует."""
    from apps.tasks.stand import stand_reset

    author, reader = _person("Автор Настроек Стенда"), _person("Читатель Настроек Стенда")
    _stand_data(author, reader, protected_root)
    assert _on("tasks.TaskSettings").get(pk=1).retention_years == 7
    assert _on("tasks.TaskCategory").count() == 1

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    settings, categories = _row_state()
    assert settings == [(1, 3, None, None)], settings
    assert categories == [], "сброс вернул категории администратора"
    first = _counts()
    assert first == {"TaskFile": 0, "TaskComment": 0, "TaskReminder": 0, "TaskMember": 0, "Task": 0,
                     "PlanColumn": 0, "TaskCategory": 0, "TaskSettings": 1}, first

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()
    assert _row_state() == (settings, categories), "повторный сброс изменил данные установки"
    assert _counts() == first, "повторный сброс задвоил строки"


# --- стирание таблиц и файлов ----------------------------------------------------------------------------

@MIGRATE
def test_stand_reset_wipes_tables_and_task_files_after_commit(protected_root, django_capture_on_commit_callbacks):
    """FR-693, FR-696 (CONTRACT-009, 1.3): стираются все таблицы `tasks` (зависимые раньше), `core.StoredFile`
    назначения `task` во всех состояниях проверки; файлы на диске удаляются только после фиксации (`on_commit`
    соединения `migrate`), файл другого назначения и сотрудники остаются."""
    from apps.tasks.stand import stand_reset

    author, reader = _person("Автор Стенда"), _person("Читатель Стенда")
    data = _stand_data(author, reader, protected_root)
    assert _counts() == {"TaskFile": 4, "TaskComment": 1, "TaskReminder": 1, "TaskMember": 1, "Task": 1,
                         "PlanColumn": 1, "TaskCategory": 1, "TaskSettings": 1}
    assert [item["path"].exists() for item in data["files"]] == [True, True, True, False]
    kept_stored, kept_path = data["kept"]
    assert kept_path.exists()

    with _commit_callbacks(django_capture_on_commit_callbacks) as (on_default, on_migrate):
        stand_reset()
        assert _counts() == {"TaskFile": 0, "TaskComment": 0, "TaskReminder": 0, "TaskMember": 0, "Task": 0,
                             "PlanColumn": 0, "TaskCategory": 0, "TaskSettings": 1}, "остались строки задач"
        assert not _on("core.StoredFile").filter(purpose="task").exists(), "StoredFile задачи остался"
        for item in data["files"]:
            assert item["path"].exists() == item["write"], "файл на диске тронут до фиксации"
    assert on_migrate, "стирание файлов не поставлено в on_commit соединения migrate"

    for item in data["files"]:
        assert not item["path"].exists(), f"файл задачи остался на диске: {item['row'].name}"
    assert _on("core.StoredFile").filter(pk=kept_stored.pk).exists(), "стёрт StoredFile другого назначения"
    assert kept_path.read_bytes() == b"other purpose", "тронут файл другого назначения"
    assert _on("core.User").filter(pk__in=[author.pk, reader.pk]).count() == 2, "сотрудник стёрт"


@MIGRATE
def test_stand_reset_on_empty_tables_creates_settings_and_is_repeatable(protected_root,
                                                                       django_capture_on_commit_callbacks):
    """FR-696 (CONTRACT-009, 1.3): сброс на пустых таблицах задач не падает: создаётся одна строка
    `TaskSettings(pk=1, retention_years=3)`, файлов на диске не появляется и не стирается, повторный запуск даёт то же
    состояние."""
    from apps.tasks.stand import stand_reset

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()
    assert _counts() == {name: 0 for name in TABLES if name != "TaskSettings"} | {"TaskSettings": 1}
    assert _on("tasks.TaskSettings").get(pk=1).retention_years == 3
    assert list(protected_root.iterdir()) == [], "сброс создал или тронул файлы тома protected"

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()
    assert _on("tasks.TaskSettings").count() == 1
    assert list(protected_root.iterdir()) == []


# --- транзакция -------------------------------------------------------------------------------------------

@MIGRATE
def test_stand_reset_runs_in_migration_transaction(protected_root, django_capture_on_commit_callbacks):
    """FR-696 (CONTRACT-009, 1.3): всё стирание и восстановление идёт под алиасом `migrate` в одной
    `transaction.atomic`: `SAVEPOINT` раньше первого `DELETE` таблиц задач, `RELEASE SAVEPOINT` позже последнего
    `DELETE`/`INSERT`, откатов нет; на `default` запросов к таблицам задач и `core_storedfile` нет."""
    from apps.tasks.stand import stand_reset

    _stand_data(_person("Автор Транзакции"), _person("Читатель Транзакции"), protected_root)
    with CaptureQueriesContext(connections["migrate"]) as migrate_log, \
            CaptureQueriesContext(connections["default"]) as default_log:
        with _commit_callbacks(django_capture_on_commit_callbacks):
            stand_reset()
    sqls = [query["sql"] for query in migrate_log.captured_queries]
    deletes = [i for i, sql in enumerate(sqls) if sql.startswith("DELETE FROM") and "tasks_" in sql]
    inserts = [i for i, sql in enumerate(sqls) if sql.startswith("INSERT INTO") and "tasks_" in sql]
    assert deletes, "сброс ничего не стёр на соединении migrate"
    assert inserts, "seed не создал данные установки на соединении migrate"
    opened = [i for i, sql in enumerate(sqls) if sql.startswith("SAVEPOINT")]
    released = [i for i, sql in enumerate(sqls) if sql.startswith("RELEASE SAVEPOINT")]
    assert opened and released, "стирание и seed не завёрнуты в transaction.atomic(using=migrate)"
    assert opened[0] < deletes[0], "первое стирание раньше входа в транзакцию"
    writes = [i for i, sql in enumerate(sqls) if sql.startswith(("DELETE FROM", "INSERT INTO"))]
    assert released[-1] > max(writes), "стирание или seed выполнены после выхода из транзакции"
    assert not [sql for sql in sqls if sql.startswith("ROLLBACK")], "сброс откатывался"
    on_default = [query["sql"] for query in default_log.captured_queries
                  if "tasks_" in query["sql"] or "core_storedfile" in query["sql"]]
    assert not on_default, f"запросы к таблицам сброса на соединении default: {on_default[:2]}"


# --- порядок точки stand_reset ----------------------------------------------------------------------------

def test_tasks_stand_reset_is_registered_last_and_runs_first():
    """FR-643 (CONTRACT-009, 1.3, 15): в точке `stand_reset` функция `apps.tasks.stand.stand_reset`
    зарегистрирована ровно один раз, предпоследней — сразу после `apps.messenger.stand.stand_reset`; последняя —
    `apps.instructions.stand` среза 010; в обратном порядке (как зовёт `e2e_reset_stand`) поручения идут первыми,
    затем задачи, мессенджер и лента."""
    from apps.core import extensions
    from apps.tasks.stand import stand_reset

    registered = list(extensions.registered("stand_reset"))
    names = [func.__module__ for func in registered]
    assert registered.count(stand_reset) == 1, "stand_reset задач не зарегистрирован ровно один раз"
    assert names[-3] == "apps.tasks.stand", f"третья с конца запись точки: {names[-3]}"
    assert names[-2] == "apps.instructions.stand", f"предпоследняя запись точки: {names[-2]}"
    assert names[-1] == "apps.automation.stand", f"последняя запись точки: {names[-1]}"
    assert names[-4] == "apps.messenger.stand", f"перед задачами стоит {names[-4]}, а не messenger"
    call_order = [func.__module__ for func in reversed(registered)]
    assert call_order[0] == "apps.automation.stand", "automation вызывается первым"
    assert call_order[1] == "apps.instructions.stand", "instructions вызывается не вторым"
    assert call_order[2] == "apps.tasks.stand", "tasks вызывается не третьим"
    assert call_order[3] == "apps.messenger.stand", "messenger вызывается не четвёртым"


# --- проверка стенда -------------------------------------------------------------------------------------

@PLAIN
def test_stand_command_refused_without_e2e_stand(monkeypatch, django_assert_num_queries):
    """FR-674 (CONTRACT-009, 1.3): `require_stand()` модуля `stand` без `E2E_STAND=1` (нет переменной, «0», пусто)
    бросает `CommandError(REFUSAL)` раньше любого запроса к базе; `REFUSAL` — текст контракта, своя копия; с
    `E2E_STAND=1` отказ не срабатывает."""
    from apps.tasks import stand

    assert stand.REFUSAL == REFUSAL
    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                stand.require_stand()
        assert str(refused.value) == REFUSAL, repr(value)
    monkeypatch.setenv("E2E_STAND", "1")
    assert stand.require_stand() is None