"""T-9117: журнал задач — создание, «было/стало» по полям, минимальный снимок удаления, комментарии без текста,
журнал только дополняется (FR-694, FR-695, NFR-718).

Источники: PLAN-009 «Права среза»/«Удаление, срок хранения» (изменения полей — `core.services.audit.record` с
«было/стало»; удаление — минимальный снимок по ADR-0018 пп. 15–16); CONTRACT-009: 10.1 (`tasks.created`,
`tasks.changed`, `tasks.comment_changed`, `tasks.deleted` — что в записи), 10.2 (подписи `audit_labels`), 3
(регистрация `audit_labels`), 4 (`can_delete`), 5.1 (`tasks.soft_delete`), 12.1 (`delete_confirm`).

Код среза импортируется внутри тестов, модели — через `support.model`; сбор проходит до появления кода. Проверки
«журнал только дополняется» — те же, что у прежних срезов: права роли `crm_app` на таблицу `core_auditevent`.
"""
import importlib
import json
from datetime import date

import pytest
from django.db import ProgrammingError, connection, transaction

from tests import support
from tests import support_org
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

NOT_FORBIDDEN = {"title", "description", "text", "comments", "comment", "body"}


# --- помощники файла ---------------------------------------------------------------------------------------------

def _tasks():
    return importlib.import_module("apps.tasks.services.tasks")


def _comments():
    return importlib.import_module("apps.tasks.services.comments")


def _events(action: str | None = None) -> list:
    rows = support.model("core.AuditEvent").objects.filter(action__startswith="tasks.")
    if action is not None:
        rows = rows.filter(action=action)
    return list(rows.order_by("id"))


def _dump(events) -> str:
    return json.dumps([[event.action, event.object_type, event.object_id, event.before, event.after]
                       for event in events], ensure_ascii=False)


def _keys(events) -> set[str]:
    found = set()
    for event in events:
        found |= set((event.before or {}).keys()) | set((event.after or {}).keys())
    return found


def _world():
    """Руководитель узла (постановщик) и его подчинённый (исполнитель): служба разрешает ставить задачу."""
    unit = support_org.make_tree({"Узел журнала задач": {}})["Узел журнала задач"]
    author = tasks_helpers.head_of(unit, full_name="Автор Журнала Задач")
    assignee = tasks_helpers.staff_user(full_name="Исполнитель Журнала Задач")
    support_org.make_member(assignee, unit)
    return {"author": author, "assignee": assignee, "unit": unit}


# --- FR-694: создание и изменение полей -------------------------------------------------------------------------

def test_create_writes_tasks_created_with_number_title_assignee_and_deadline():
    """FR-694 (CONTRACT-009, 10.1): создание задачи пишет одну запись `tasks.created` на объект `tasks.task` с
    номером в `object_id`, названием, исполнителем и сроком; других действий журнала задач нет."""
    people = _world()
    author, assignee = people["author"], people["assignee"]
    task = _tasks().create(author, title="Задача в журнал", description="Описание", assignee=assignee,
                           deadline=date(2026, 12, 1))

    events = _events("tasks.created")
    assert len(events) == 1, f"записей tasks.created: {len(events)}"
    event = events[0]
    assert (event.object_type, event.object_id) == ("tasks.task", str(task.pk))
    assert event.actor_id == author.pk
    assert event.after.get("title") == "Задача в журнал"
    assert "2026" in str(event.after.get("deadline")), f"срок в записи: {event.after.get('deadline')!r}"
    assert event.after.get("assignee") not in (None, "")
    assert _events("tasks.changed") == []


def test_every_changed_field_written_as_before_and_after():
    """FR-694 (CONTRACT-009, 10.1): правка полей пишет `tasks.changed` с «было/стало» по каждому из восьми полей —
    `title`, `description`, `deadline`, `status`, `assignee`, `members`, `category`, `plan_column`; неизменённые
    поля в записи не появляются."""
    people = _world()
    author, assignee = people["author"], people["assignee"]
    other = tasks_helpers.staff_user(full_name="Новый Исполнитель Журнала")
    support_org.make_member(other, people["unit"])
    member = tasks_helpers.staff_user(full_name="Новый Соисполнитель Журнала")
    task = _tasks().create(author, title="Старое название", description="Старое описание",
                           assignee=assignee, deadline=date(2026, 12, 1))
    category = tasks_helpers.make_category("Журнал")
    column = tasks_helpers.make_column(author, "Журнал")
    service = _tasks()

    service.update(author, task, title="Новое название", description="Новое описание")
    service.update(author, task, deadline=date(2026, 12, 10))
    service.change_status(assignee, task, "in_progress")
    service.update(author, task, assignee=other)
    service.update(author, task, members=[member])
    service.update(author, task, category=category)
    service.update(author, task, plan_column=column)

    events = _events("tasks.changed")
    assert events, "правки не попали в журнал"
    keys = _keys(events)
    expected = {"title", "description", "deadline", "status", "assignee", "members", "category", "plan_column"}
    assert expected <= keys, f"в журнале нет полей: {sorted(expected - keys)}"
    title_event = next(event for event in events if "title" in (event.after or {}))
    assert title_event.before.get("title") == "Старое название"
    assert title_event.after.get("title") == "Новое название"
    status_event = next(event for event in events if "status" in (event.after or {}))
    assert (status_event.before.get("status"), status_event.after.get("status")) == ("new", "in_progress")
    assert all(event.object_type == "tasks.task" and event.object_id == str(task.pk) for event in events)


# --- FR-695: удаление минимальным снимком -----------------------------------------------------------------------

def test_delete_writes_minimal_snapshot_without_title_description_and_comments():
    """FR-695 (CONTRACT-009, 10.1, ADR-0018 п. 15): мягкое удаление пишет `tasks.deleted` на объект `tasks.task` с
    номером в `object_id` и ровно четырьмя полями снимка; названия, описания и текста комментариев в записи нет."""
    title_marker, description_marker, comment_marker = "Удаляемое название", "Удаляемое описание", "Секретный комментарий"
    people = _world()
    author, assignee = people["author"], people["assignee"]
    task = _tasks().create(author, title=title_marker, description=description_marker, assignee=assignee)
    _comments().add(author, task, comment_marker)

    _tasks().soft_delete(author, task)

    events = _events("tasks.deleted")
    assert len(events) == 1, f"записей tasks.deleted: {len(events)}"
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("tasks.task", str(task.pk), author.pk)
    assert len(event.after) == 4, f"снимок удаления: {event.after}"
    assert set(event.after) & NOT_FORBIDDEN == set(), f"в снимке лишние поля: {sorted(event.after)}"
    dump = _dump(events)
    for marker in (title_marker, description_marker, comment_marker):
        assert marker not in dump, f"в журнал попало: {marker!r}"


# --- FR-694: комментарии без текста ----------------------------------------------------------------------------

def test_comment_edit_and_delete_have_no_text_in_journal():
    """FR-694 (CONTRACT-009, 10.1): правка и удаление комментария — `tasks.comment_changed` без текста; в записи
    только номера задачи и комментария."""
    marker_before, marker_after = "Текст до правки секретный", "Текст после правки секретный"
    people = _world()
    author, assignee = people["author"], people["assignee"]
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None)
    edited = _comments().add(author, task, marker_before)
    removed = _comments().add(author, task, marker_before)

    _comments().edit(author, edited, marker_after)
    _comments().remove(author, removed)

    events = _events("tasks.comment_changed")
    assert len(events) == 2
    assert {event.object_type for event in events} == {"tasks.comment"}
    assert {event.object_id for event in events} == {str(edited.pk), str(removed.pk)}
    dump = _dump(events)
    assert marker_before not in dump and marker_after not in dump, "текст комментария попал в журнал"
    assert str(task.pk) in dump, "в записи нет номера задачи"


def test_ordinary_comment_creation_and_reads_write_no_tasks_journal():
    """FR-694, NFR-718: обычный комментарий и просмотр карточки изменений журнала задач не пишут — только правка и
    удаление комментария дают `tasks.comment_changed`."""
    people = _world()
    author = people["author"]
    task = _tasks().create(author, title="Просмотры без журнала", assignee=author)
    before = {event.pk for event in _events()}
    _comments().add(author, task, "Обычный комментарий")
    support.logged_in(author).get(f"/tasks/{task.pk}/")
    after = {event.pk for event in _events()}
    assert after == before, "комментарий или просмотр карточки попали в журнал задач"
    assert _events("tasks.comment_changed") == []


# --- 10.2: подписи ---------------------------------------------------------------------------------------------

def test_audit_labels_cover_all_actions_fields_and_object_types():
    """CONTRACT-009 10.2: `apps.tasks.audit_labels.audit_labels()` содержит все восемь действий, десять полей и три
    вида объектов с русскими подписями; `values` пуст (значения службы пишут сами)."""
    labels = importlib.import_module("apps.tasks.audit_labels").audit_labels()
    actions = {
        "tasks.created": "Задача создана",
        "tasks.changed": "Задача изменена",
        "tasks.comment_changed": "Комментарий изменён или удалён",
        "tasks.deleted": "Задача удалена",
        "tasks.reminder_set": "Напоминание поставлено",
        "tasks.reminder_failed": "Напоминание не создано",
        "tasks.retention_changed": "Срок хранения задач изменён",
        "tasks.retention_purged": "Задачи удалены по сроку",
    }
    fields = {
        "deadline": "срок", "members": "состав", "category": "категория", "plan_column": "колонка плана",
        "years": "срок хранения, лет", "tasks": "Удалено по сроку, задач",
        "comments": "Удалено по сроку, комментариев", "files": "Удалено по сроку, файлов",
        "reminder": "напоминание", "user": "сотрудник", "moment": "момент", "task": "задача",
    }
    object_types = {"tasks.task": "задача", "tasks.comment": "комментарий задачи",
                    "tasks.settings": "настройки задач"}
    assert labels["actions"] == actions
    assert labels["fields"] == fields
    assert labels["object_types"] == object_types
    assert labels["values"] == {}


# --- NFR-718: журнал только дополняется ------------------------------------------------------------------------

def test_application_role_cannot_update_or_delete_audit_rows():
    """NFR-718 (CONTRACT-009, 10.1; тот же тест, что SPEC-006 NFR-508): у роли `crm_app` нет UPDATE, DELETE и
    TRUNCATE на `core_auditevent`; правка и удаление записей `tasks.*` отвергаются базой, строки не меняются."""
    people = _world()
    author, assignee = people["author"], people["assignee"]
    task = _tasks().create(author, title="Журнал Неизменяем", assignee=assignee)
    _tasks().update(author, task, title="Журнал Изменён")
    events = _events()
    assert events, "записей журнала задач нет"
    ids = sorted(event.pk for event in events)
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(support.model("core.AuditEvent").objects.filter(id__in=ids).order_by("id")
                    .values_list(*columns))

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        support.model("core.AuditEvent").objects.filter(action__startswith="tasks.").update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action LIKE %s", ["tasks.%"])
    assert list(support.model("core.AuditEvent").objects.filter(id__in=ids).order_by("id")
                .values_list(*columns)) == snapshot