"""Срез 009 «Задачи»: правка полей и статусы (T-9106; FR-678, FR-679).

`tasks.services.tasks.update` и `change_status` проверяют права, пишут журнал «было/стало» и событие ленты,
обновляют `updated_at`; «Готово» ставит `completed_at` и снимает напоминания, возврат — снимает `completed_at`
(CONTRACT-009, 6.2, 10.1).
"""
import pytest

from tests import support, support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db


def service():
    from apps.tasks.services import tasks as module
    return module


def errors():
    from apps.tasks.services import errors as module
    return module


def _member(unit, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit)
    return user


def _marked(unit, mark, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit, mark=mark)
    return user


def _events(task, action="tasks.changed"):
    return list(support.model("core.AuditEvent").objects.filter(
        action=action, object_id=str(task.pk)).order_by("id"))


def test_update_fields_writes_before_after_and_updates_timestamp():
    """FR-678, FR-694: правка названия, описания и срока пишет `tasks.changed` «было/стало» по каждому полю и
    обновляет `updated_at`; исполнитель полей не правит — 403/отказ службы."""
    from datetime import timedelta

    from django.utils import timezone

    author = support_tasks.staff_user()
    task = support_tasks.make_task(author=author, title="Старое", description="Было")
    before = task.updated_at
    new_deadline = timezone.localdate() + timedelta(days=2)

    service().update(author, task, title="Новое", description="Стало", deadline=new_deadline)
    task.refresh_from_db()
    assert (task.title, task.description, task.deadline) == ("Новое", "Стало", new_deadline)
    assert task.updated_at > before
    event = _events(task)[-1]
    assert event.before["title"] == "Старое" and event.after["title"] == "Новое"
    assert event.before["description"] == "Было" and event.after["description"] == "Стало"
    assert "deadline" in event.after


def test_assignee_cannot_edit_fields_but_manager_of_assignee_can():
    """FR-678: поля правят автор и руководитель/заместитель узла исполнителя; сам исполнитель — нет,
    руководитель узла автора — нет."""
    tree = support_org.make_tree({"Автор": {}, "Исполнитель": {}})
    author = _member(tree["Автор"])
    assignee = _member(tree["Исполнитель"])
    author_head = _marked(tree["Автор"], "head")
    assignee_head = _marked(tree["Исполнитель"], "deputy")
    task = support_tasks.make_task(author=author, assignee=assignee)

    with pytest.raises(errors().TasksError) as raised:
        service().update(assignee, task, title="Сам")
    assert (raised.value.code, raised.value.field) == ("edit_forbidden", "title")
    with pytest.raises(errors().TasksError):
        service().update(author_head, task, title="Руководитель автора")
    changed = service().update(assignee_head, task, title="Руководитель исполнителя")
    assert changed.title == "Руководитель исполнителя"


def test_status_flow_and_completed_at():
    """FR-679: «Начать» → «В работе», «Завершить» → «Готово» ставит `completed_at`; возврат в работу снимает его;
    четыре статуса допустимы, неизвестный — `status_invalid`."""
    from django.utils import timezone

    author = support_tasks.staff_user()
    task = support_tasks.make_task(author=author)
    service().change_status(author, task, "in_progress")
    task.refresh_from_db()
    assert task.status == "in_progress" and task.completed_at is None
    service().change_status(author, task, "done")
    task.refresh_from_db()
    assert task.status == "done" and task.completed_at is not None
    service().change_status(author, task, "in_progress")
    task.refresh_from_db()
    assert task.status == "in_progress" and task.completed_at is None
    with pytest.raises(errors().TasksError) as raised:
        service().change_status(author, task, "archived")
    assert (raised.value.code, raised.value.field) == ("status_invalid", "status")


def test_status_rights_executor_coexecutor_author_manager_not_observer():
    """FR-678, FR-679: статус меняют исполнитель, соисполнитель, постановщик, руководитель и заместитель узла
    исполнителя; наблюдатель получает `status_forbidden`."""
    tree = support_org.make_tree({"Узел": {}})
    author = support_tasks.staff_user()
    assignee = _member(tree["Узел"])
    coexecutor, observer = support.make_employee(), support.make_employee()
    head = _marked(tree["Узел"], "head")
    task = support_tasks.make_task(author=author, assignee=assignee)
    support_tasks.add_member(task, coexecutor, role="coexecutor")
    support_tasks.add_member(task, observer, role="observer")
    for viewer in (assignee, coexecutor, author, head):
        service().change_status(viewer, task, "in_progress")
        service().change_status(viewer, task, "new")
    with pytest.raises(errors().TasksError) as raised:
        service().change_status(observer, task, "in_progress")
    assert (raised.value.code, raised.value.field) == ("status_forbidden", "status")


def test_done_cancels_reminders_and_return_does_not_restore_them():
    """FR-689: «Готово» снимает все напоминания; возврат в работу не восстанавливает снятые автоматические —
    новый расчёт идёт при следующей смене срока."""
    task = support_tasks.make_task()
    Reminder = support.model("tasks.TaskReminder")
    from django.utils import timezone

    Reminder.objects.create(task=task, user=task.assignee, kind="auto_due", moment=timezone.now())
    service().change_status(task.author, task, "done")
    assert support_tasks.reminders_of(task) == []
    service().change_status(task.author, task, "new")
    assert support_tasks.reminders_of(task) == []


def test_noop_update_writes_no_event():
    """FR-694: повторное сохранение тех же значений не пишет `tasks.changed` (журнал только по изменениям)."""
    author = support_tasks.staff_user()
    task = support_tasks.make_task(author=author, title="Та же")
    service().update(author, task, title="Та же")
    assert _events(task) == []