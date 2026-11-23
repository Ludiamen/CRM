"""Срез 010 «Поручения»: связь с задачами (T-10112; FR-716).

`apps.instructions.services.instructions.link_task` и модель `InstructionTask` — CONTRACT-010, 5.1, 11.
Код среза и задачи импортируются внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.db import IntegrityError, transaction

from tests import support, support_org, support_tasks
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def instructions():
    from apps.instructions.services import instructions as module
    return module


def tasks():
    from apps.tasks.services import tasks as module
    return module


def _base():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    head = ins.head_of(tree["Отдел"])
    assignee = ins.staff_user()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    return tree, head, controller, assignee, row


def test_link_creates_task_and_link_row():
    """FR-716: исполнитель создаёт задачу из поручения по правилам среза 009; связь — `InstructionTask` с
    автором связи."""
    tree, head, controller, assignee, row = _base()
    task = instructions().link_task(assignee, row, title="Шаг поручения",
                                    deadline=ins._today() + datetime.timedelta(days=3))
    assert task.title == "Шаг поручения" and task.author_id == assignee.pk
    link = support.model("instructions.InstructionTask").objects.get(instruction=row, task=task)
    assert link.created_by_id == assignee.pk


def test_without_tasks_use_link_is_forbidden():
    """FR-716: без `tasks.use` задачу не создать — `task_forbidden` у поля `task`."""
    tree, head, controller, assignee, row = _base()
    plain = support.make_employee()
    support_org.make_member(plain, tree["Группа"])
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        instructions().link_task(plain, row, title="Нельзя")
    assert (caught.value.code, caught.value.field) == ("task_forbidden", "task")


def test_link_existing_task_only_when_visible():
    """FR-716: связать можно только видимую задачу; чужая — `task_missing`."""
    tree, head, controller, assignee, row = _base()
    outsider = support.make_employee()
    visible = support_tasks.make_task(title="Видимая исполнителю", author=assignee, assignee=assignee)
    foreign = support_tasks.make_task(title="Чужая", author=outsider, assignee=outsider)

    linked = instructions().link_task(assignee, row, task=visible)
    assert linked.pk == visible.pk
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        instructions().link_task(assignee, row, task=foreign)
    assert (caught.value.code, caught.value.field) == ("task_missing", "task")


def test_duplicate_link_is_unique():
    """FR-716, модель: связь `(instruction, task)` уникальна."""
    tree, head, controller, assignee, row = _base()
    task = support_tasks.make_task(title="Одна связь", author=assignee, assignee=assignee)
    instructions().link_task(assignee, row, task=task)
    Link = support.model("instructions.InstructionTask")
    with pytest.raises(IntegrityError), transaction.atomic():
        Link.objects.create(instruction=row, task=task, created_by=assignee)


def test_completed_task_does_not_change_instruction_state():
    """FR-716: завершение задачи не меняет статус поручения и не снимает его с контроля — отчёт пишет
    исполнитель."""
    tree, head, controller, assignee, row = _base()
    task = instructions().link_task(assignee, row, title="Закрыть шаг",
                                    deadline=ins._today() + datetime.timedelta(days=2))
    tasks().change_status(assignee, task, "in_progress")
    tasks().change_status(assignee, task, "done")
    row.refresh_from_db()
    assert row.closed_at is None
    from apps.instructions.services import dates

    assert dates.state_of(row) == "control"


def test_task_deleted_with_instruction_and_task_cascade():
    """FR-716: связь удаляется каскадом вместе с задачей и поручением."""
    tree, head, controller, assignee, row = _base()
    task = support_tasks.make_task(title="Каскад", author=assignee, assignee=assignee)
    instructions().link_task(assignee, row, task=task)
    Link = support.model("instructions.InstructionTask")
    task.delete()
    assert not Link.objects.filter(instruction=row, task_id=task.pk).exists()

    second = support_tasks.make_task(title="Каскад поручения", author=assignee, assignee=assignee)
    instructions().link_task(assignee, row, task=second)
    row.delete()
    assert not Link.objects.filter(task=second).exists()


def test_card_shows_task_only_to_those_who_see_it(client):
    """FR-716: связанная задача видна в карточке только тем, кому видна сама задача; остальным карточка
    поручения задачу не показывает (и чужим поручение — 404)."""
    tree, head, controller, assignee, row = _base()
    task = instructions().link_task(assignee, row, title="Видна не всем",
                                    deadline=ins._today() + datetime.timedelta(days=2))
    assert "Видна не всем" in support.logged_in(assignee).get(f"/instructions/{row.pk}/").content.decode()
    assert "Видна не всем" not in support.logged_in(controller).get(f"/instructions/{row.pk}/").content.decode()

    outsider = ins.staff_user()
    support_org.make_member(outsider, support_org.make_tree({"Чужой": {}})["Чужой"])
    assert support.logged_in(outsider).get(f"/instructions/{row.pk}/").status_code == 404