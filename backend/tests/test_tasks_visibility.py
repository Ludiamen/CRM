"""Срез 009 «Задачи»: видимость задачи (T-9104; FR-677, FR-686).

`tasks.services.access.visible(viewer, task)` — автор, участники, руководители и заместители автора и исполнителя
по цепочке вышестоящих; администратор чужих не видит; удалённая задача невидима; состав считается на момент
просмотра (CONTRACT-009, раздел 4; ADR-0018 п. 9).
"""
import pytest

from tests import support, support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db


def access():
    from apps.tasks.services import access as module
    return module


def _member(unit, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit)
    return user


def _marked(unit, mark, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit, mark=mark)
    return user


def test_author_assignee_coexecutor_and_observer_see_task():
    """FR-677: задача видна постановщику, исполнителю, соисполнителю и наблюдателю; посторонний её не видит."""
    author, assignee = support.make_employee(), support.make_employee()
    coexecutor, observer, outsider = support.make_employee(), support.make_employee(), support.make_employee()
    task = support_tasks.make_task(author=author, assignee=assignee)
    support_tasks.add_member(task, coexecutor, role="coexecutor")
    support_tasks.add_member(task, observer, role="observer")
    for viewer in (author, assignee, coexecutor, observer):
        assert access().visible(viewer, task), viewer
    assert not access().visible(outsider, task)


def test_heads_and_deputies_of_author_and_assignee_units_see_task_by_chain():
    """FR-677: руководители и заместители узлов автора и исполнителя по цепочке вышестоящих видят задачу;
    заместитель равен руководителю; руководитель чужого узла — нет."""
    tree = support_org.make_tree({"Направление": {"Отдел автора": {}, "Отдел исполнителя": {}},
                                  "Чужой": {}})
    author = _member(tree["Отдел автора"])
    assignee = _member(tree["Отдел исполнителя"])
    task = support_tasks.make_task(author=author, assignee=assignee)
    above_author = _marked(tree["Направление"], "head")
    above_assignee = _marked(tree["Направление"], "deputy")
    own_author = _marked(tree["Отдел автора"], "head")
    own_assignee = _marked(tree["Отдел исполнителя"], "deputy")
    outsider = _marked(tree["Чужой"], "head")
    for viewer in (own_author, own_assignee, above_author, above_assignee):
        assert access().visible(viewer, task), viewer
    assert not access().visible(outsider, task)


def test_administrator_does_not_see_foreign_task():
    """FR-677, ADR-0018 п. 9: администратор портала чужих задач не видит — ответ как у несуществующей."""
    admin = support.make_admin()
    task = support_tasks.make_task()
    assert not access().visible(admin, task)


def test_deleted_task_is_invisible_to_everyone():
    """FR-695: мягко удалённая задача (`deleted_at IS NOT NULL`) не видна никому, включая автора и участников."""
    task = support_tasks.make_task()
    member = support.make_employee()
    support_tasks.add_member(task, member, role="observer")
    for viewer in (task.author, task.assignee, member):
        assert access().visible(viewer, task)
    from apps.tasks.services import tasks as service

    service.soft_delete(task.author, task)
    task.refresh_from_db()
    for viewer in (task.author, task.assignee, member):
        assert not access().visible(viewer, task)


def test_transfer_changes_visibility_at_view_time():
    """FR-686: переведённый сотрудник пропадает у прежнего руководителя и появляется у нового — состав считается
    на момент просмотра, без копий."""
    tree = support_org.make_tree({"Первый": {}, "Второй": {}})
    employee = _member(tree["Первый"])
    first_head = _marked(tree["Первый"], "head")
    second_head = _marked(tree["Второй"], "head")
    task = support_tasks.make_task(author=employee, assignee=employee)
    assert access().visible(first_head, task) and not access().visible(second_head, task)

    from apps.org.services import membership

    membership.transfer_member(employee, tree["Первый"], tree["Второй"], actor=first_head)
    assert not access().visible(first_head, task)
    assert access().visible(second_head, task)


def test_dismissed_author_breaks_chain_visibility():
    """FR-677: уволенный автор не состоит в узлах — его прежний руководитель больше не видит задачу."""
    tree = support_org.make_tree({"Отдел": {}})
    author = _member(tree["Отдел"])
    head = _marked(tree["Отдел"], "head")
    task = support_tasks.make_task(author=author)
    assert access().visible(head, task)
    support.model("core.User").objects.filter(pk=author.pk).update(state="dismissed")
    # задача читается заново: связанный автор не должен остаться в кэше объекта со старым состоянием
    task = support.model("tasks.Task").objects.get(pk=task.pk)
    assert not access().visible(support.model("core.User").objects.get(pk=head.pk), task)