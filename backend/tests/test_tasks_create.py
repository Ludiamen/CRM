"""Срез 009 «Задачи»: создание задачи (T-9105; FR-674, FR-675).

`tasks.services.tasks.create` проверяет текст, срок, состав и права; создание пишется в журнал `tasks.created`
(CONTRACT-009, 5.1, 6.2). Коды отказов — `TasksError` с полем формы.
"""
from datetime import timedelta

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


def _refused(actor, **fields):
    with pytest.raises(errors().TasksError) as raised:
        service().create(actor, **fields)
    return raised.value


def test_title_is_trimmed_and_keeps_1_to_300_characters():
    """FR-674: название после обрезки — от 1 до 300 знаков; 300 принимается, 301 и пустое отклоняются с
    `title_range`; задача с номером `pk` сохранена."""
    author = support_tasks.staff_user()
    task = service().create(author, title="  " + "я" * 300 + "  ", assignee=author)
    assert task.title == "я" * 300 and task.pk == task.id

    too_long = _refused(author, title="я" * 301, assignee=author)
    assert (too_long.code, too_long.field) == ("title_range", "title")
    empty = _refused(author, title="   ", assignee=author)
    assert (empty.code, empty.field) == ("title_range", "title")


def test_description_limit_and_deadline_date_only():
    """FR-674: описание до 10 000 знаков; срок — дата без времени; 10 001 знак — `description_long`."""
    author = support_tasks.staff_user()
    task = service().create(author, title="С описанием", description="д" * 10_000, assignee=author)
    assert task.description == "д" * 10_000
    error = _refused(author, title="Длинное", description="д" * 10_001, assignee=author)
    assert (error.code, error.field) == ("description_long", "description")

    from django.utils import timezone

    deadline = timezone.localdate() + timedelta(days=3)
    task = service().create(author, title="Со сроком", deadline=deadline, assignee=author)
    assert task.deadline == deadline


def test_deadline_in_past_refused_only_when_deadline_is_set():
    """FR-674, FR-678: срок раньше сегодняшнего дня отклоняется `deadline_past` при создании и смене срока; уже
    ставший прошлым срок не мешает правке других полей (CONTRACT-009, К13)."""
    from django.utils import timezone

    author = support_tasks.staff_user()
    yesterday = timezone.localdate() - timedelta(days=1)
    error = _refused(author, title="Вчера", deadline=yesterday, assignee=author)
    assert (error.code, error.field) == ("deadline_past", "deadline")

    task = support_tasks.make_task(author=author, deadline=yesterday)
    changed = service().update(author, task, title="Новое название")
    assert changed.title == "Новое название" and changed.deadline == yesterday


def test_members_are_active_unique_and_never_assignee():
    """FR-675: соисполнители и наблюдатели — действующие сотрудники без повторов и без исполнителя; уволенный —
    `member_dismissed`, повтор — `member_duplicate`, исполнитель в составе — `member_is_assignee`."""
    author = support_tasks.staff_user()
    peer = support.make_employee()
    dismissed = support.make_employee(state="dismissed")
    error = _refused(author, title="Состав", assignee=author, members=[dismissed])
    assert (error.code, error.field) == ("member_dismissed", "members")
    error = _refused(author, title="Состав", assignee=author, members=[peer, peer])
    assert (error.code, error.field) == ("member_duplicate", "members")
    error = _refused(author, title="Состав", assignee=author, members=[author])
    assert (error.code, error.field) == ("member_is_assignee", "members")

    task = service().create(author, title="Состав", assignee=author, members=[peer])
    members = list(support.model("tasks.TaskMember").objects.filter(task=task).values_list("user_id", "role"))
    assert members == [(peer.pk, "coexecutor")]


def test_create_writes_audit_event_with_number_and_assignee():
    """FR-674, FR-694: создание пишет `tasks.created` с номером, названием, исполнителем и сроком; объект —
    `task`, тип `tasks.task`."""
    author = support_tasks.staff_user()
    task = service().create(author, title="Журнал", assignee=author)
    event = support.model("core.AuditEvent").objects.filter(action="tasks.created", object_id=str(task.pk)).get()
    assert event.object_type == "tasks.task" and event.actor_id == author.pk
    assert event.after["title"] == "Журнал" and "assignee" in event.after


def test_create_with_optional_category_and_plan_column():
    """FR-682, FR-683: категория и личная колонка плана — необязательны; без выбора категория пуста, колонка пуста
    (показывается в первой колонке доски)."""
    author = support_tasks.staff_user()
    category = support_tasks.make_category("Работа")
    column = support_tasks.make_column(author, "Сегодня")
    with_category = service().create(author, title="С категорией", assignee=author, category=category)
    assert with_category.category_id == category.pk
    with_column = service().create(author, title="С колонкой", assignee=author, plan_column=column)
    assert with_column.plan_column_id == column.pk
    plain = service().create(author, title="Без всего", assignee=author)
    assert plain.category_id is None and plain.plan_column_id is None