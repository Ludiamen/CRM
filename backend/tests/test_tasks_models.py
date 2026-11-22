"""Срез 009 «Задачи»: модель данных и изменения ядра (FR-674…FR-699).

T-9002: назначение файла `task` в конце перечня и миграция `core 0012` (FR-693). Остальные тесты моделей
добавляет T-9101.
"""
import ast

import pytest
from django.utils import timezone

from tests import support
from tests import support_tasks as tasks

pytestmark = pytest.mark.django_db


# --- core/models/files.py и миграция 0012 --------------------------------------------------------------------------

def test_purpose_task_is_last():
    """FR-693: `StoredFile.Purpose.TASK = "task"` («вложение задачи») — последним; прежние шесть значений и
    подписи те же, `max_length` 16 и значение по умолчанию `photo` не менялись; миграция
    `core 0012_storedfile_task_purpose` — одна операция `AlterField` поля `purpose`, зависит от `0011`; строку
    с назначением `task` можно создать (CONTRACT-009, 2.1)."""
    StoredFile = support.model("core.StoredFile")
    assert StoredFile.Purpose.choices == [
        ("photo", "фото"), ("attachment", "вложение"), ("knowledge", "файл статьи"),
        ("lists", "файл записи списка"), ("feed", "вложение ленты"), ("messenger", "вложение сообщения чата"),
        ("task", "вложение задачи")]
    assert tuple(StoredFile.Purpose.values) == (
        "photo", "attachment", "knowledge", "lists", "feed", "messenger", "task")
    assert StoredFile.Purpose.TASK == "task" and list(StoredFile.Purpose.values)[-1] == "task"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"
    assert len(StoredFile.Purpose.TASK) <= field.max_length

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0012_storedfile_task_purpose.py"
    assert path.is_file(), "нет миграции core/0012_storedfile_task_purpose.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0011_storedfile_messenger_purpose")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and isinstance(operations[0], ast.Call) and operations[0].func.attr == "AlterField"
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in operations[0].keywords
                if kw.arg in ("model_name", "name")}
    assert keywords == {"model_name": "storedfile", "name": "purpose"}

    row = StoredFile.objects.create(purpose="task", owner=None, size=1, sha256="0" * 64,
                                    content_type="application/octet-stream", status="pending")
    row.refresh_from_db()
    assert row.purpose == "task"

# --- модели и ограничения (T-9101; FR-674, FR-675, FR-679, FR-682, FR-683) -------------------------------------

def _m(label):
    return support.model(label)


def _index_fields(model) -> list[tuple]:
    return [tuple(index.fields) for index in model._meta.indexes]


def _unique_sets(model) -> list[tuple]:
    """Уникальные наборы полей модели: `unique`, `unique_together` и `UniqueConstraint` без условия."""
    result = [(field.name,) for field in model._meta.fields if field.unique and not field.primary_key]
    result += [tuple(item) for item in (model._meta.unique_together or ())]
    for constraint in model._meta.constraints:
        fields = tuple(getattr(constraint, "fields", ()) or ())
        if fields and getattr(constraint, "condition", None) is None:
            result.append(fields)
    return result


def test_task_fields_limits_number_is_pk_and_statuses():
    """FR-674, FR-679: у `Task` поля плана — `title` (300), `description` (10 000), `deadline` (дата, пусто),
    `author`/`assignee` (FK на `core.User`, PROTECT), статус из четырёх значений, `category`/`plan_column`
    (SET_NULL), `created_at`/`updated_at`/`completed_at`/`deleted_at`; номер задачи — `pk`."""
    Task = _m("tasks.Task")
    fields = {field.name: field for field in Task._meta.get_fields()}
    assert {"title", "description", "deadline", "author", "assignee", "status", "category", "plan_column",
            "created_at", "updated_at", "completed_at", "deleted_at"} <= set(fields)
    assert fields["title"].max_length == 300
    assert fields["description"].max_length == 10_000
    assert fields["deadline"].get_internal_type() == "DateField" and fields["deadline"].null
    for name in ("author", "assignee"):
        assert fields[name].many_to_one and fields[name].remote_field.on_delete.__name__ == "PROTECT"
    for name in ("category", "plan_column"):
        assert fields[name].many_to_one and fields[name].remote_field.on_delete.__name__ == "SET_NULL"
    status = fields["status"]
    assert [(value, label) for value, label in status.choices] == [
        ("new", "Новая"), ("in_progress", "В работе"), ("waiting", "Ждёт"), ("done", "Готово")]
    assert status.default == "new"
    assert fields["deleted_at"].null and fields["completed_at"].null
    assert Task._meta.pk.name == "id"


def test_task_meta_indexes_match_plan():
    """FR-674, FR-685: индексы `Task` — `(assignee, status)`, `deadline`, `author`, `plan_column`, `category`,
    `deleted_at` (CONTRACT-009, 2.1)."""
    indexes = _index_fields(_m("tasks.Task"))
    for wanted in (("assignee", "status"), ("deadline",), ("author",), ("plan_column",), ("category",),
                   ("deleted_at",)):
        assert wanted in indexes, f"нет индекса {wanted}: {indexes}"


def test_task_member_roles_and_unique_task_user():
    """FR-675: у `TaskMember` роли `coexecutor`/`observer`, уникальность `(task, user)`, индекс `user`; роль
    исполнителя в участниках не хранится."""
    TaskMember = _m("tasks.TaskMember")
    field = TaskMember._meta.get_field("role")
    assert [value for value, _label in field.choices] == ["coexecutor", "observer"]
    assert ("task", "user") in _unique_sets(TaskMember)
    assert ("user",) in _index_fields(TaskMember)


def test_category_and_plan_column_titles_unique_and_ordered():
    """FR-682, FR-683: `TaskCategory` — уникальное `title`, индекс `position`; `PlanColumn` — уникальность
    `(user, title)`, индекс `(user, position)`."""
    Category, Column = _m("tasks.TaskCategory"), _m("tasks.PlanColumn")
    assert Category._meta.get_field("title").max_length == 100
    assert ("title",) in _unique_sets(Category)
    assert ("position",) in _index_fields(Category)
    assert Column._meta.get_field("title").max_length == 100
    assert ("user", "title") in _unique_sets(Column)
    assert ("user", "position") in _index_fields(Column)


@pytest.mark.django_db
def test_auto_reminders_unique_while_pending_but_manual_and_cancelled_repeat():
    """FR-687, FR-690, NFR-715: частичный уникальный индекс `(task, user, kind)` при `kind LIKE 'auto%'` и
    `state != 'cancelled'`: два ждущих автоматических напоминания одного вида запрещены, ручные повторяются,
    отменённое автоматическое не мешает новому (CONTRACT-009, 2.1)."""
    from django.db import IntegrityError, transaction

    task = tasks.make_task()
    Reminder = _m("tasks.TaskReminder")
    moment = timezone.now()
    Reminder.objects.create(task=task, user=task.assignee, kind="auto_due", moment=moment)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Reminder.objects.create(task=task, user=task.assignee, kind="auto_due", moment=moment)
    Reminder.objects.create(task=task, user=task.assignee, kind="manual", moment=moment)
    Reminder.objects.create(task=task, user=task.assignee, kind="manual", moment=moment)
    Reminder.objects.filter(kind="auto_due").update(state="cancelled")
    Reminder.objects.create(task=task, user=task.assignee, kind="auto_due", moment=moment)
    assert Reminder.objects.filter(task=task, kind="auto_due").count() == 2


@pytest.mark.django_db
def test_task_comment_and_file_links_and_task_settings_default():
    """FR-693, FR-696: `TaskComment` (`edited_at`, `deleted_at`, индекс `(task, created_at)`), `TaskFile` —
    OneToOne на `core.StoredFile`, пустой `comment` у непривязанного; `TaskSettings` — одна строка `pk=1`,
    срок хранения по умолчанию 3 года."""
    Comment, File, Settings = _m("tasks.TaskComment"), _m("tasks.TaskFile"), _m("tasks.TaskSettings")
    assert Comment._meta.get_field("edited_at").null and Comment._meta.get_field("deleted_at").null
    assert ("task", "created_at") in _index_fields(Comment)
    file_field = File._meta.get_field("file")
    assert file_field.one_to_one and file_field.remote_field.on_delete.__name__ == "PROTECT"
    assert File._meta.get_field("comment").null
    assert ("task",) in _index_fields(File) and ("comment",) in _index_fields(File)
    settings = Settings.objects.create(pk=1)
    assert settings.retention_years == 3
    assert Settings.objects.get(pk=1).pk == 1
