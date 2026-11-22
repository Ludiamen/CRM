"""Срез 009 «Задачи»: права-данные (T-9004; FR-676, FR-678).

`tasks.use` и `tasks.assign` — строки `core.Permission`, выданные встроенным ролям миграцией `core 0013`
(PLAN-009, «Права»; ADR-0018 п. 13). Поведение правки и постановки задач проверяет T-9103.
"""
import ast

import pytest

from tests import support, support_org
from tests import support_tasks
from tests.support import model

pytestmark = pytest.mark.django_db

CODES = ("tasks.use", "tasks.assign")


def _role(name):
    return model("core.Role").objects.get(name=name, is_builtin=True)


def _codes(role) -> set:
    return set(role.permissions.values_list("code", flat=True))


def test_tasks_permissions_created_and_granted_to_builtin_roles():
    """FR-676, FR-678: права `tasks.use` («Работа с задачами») и `tasks.assign` («Ставить задачи другим
    сотрудникам») созданы данными установки с русскими названиями; миграция `core 0013` зависит от `0012`;
    оба права есть у «Администратора портала» и «Сотрудника ИТ» и не выданы «Руководителю» по умолчанию."""
    rows = dict(model("core.Permission").objects.filter(code__in=CODES).values_list("code", "title"))
    assert set(rows) == set(CODES) and all(isinstance(title, str) and title for title in rows.values())

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0013_tasks_permissions.py"
    assert path.is_file(), "нет миграции core/0013_tasks_permissions.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0012_storedfile_task_purpose")]

    assert _codes(_role(support.ADMIN_ROLE)) >= set(CODES)
    assert _codes(_role(support.STAFF_ROLE)) >= set(CODES)
    assert not _codes(_role(support.MANAGER_ROLE)) & set(CODES)


def test_role_without_tasks_assign_does_not_allow_assigning_to_another():
    """FR-676, FR-678: роль с одним `tasks.use` даёт работу с задачами, но не право ставить задачу другому;
    `tasks.assign` появляется у держателя только после выдачи права роли (права — данные, ADR-0018 п. 13)."""
    from apps.core.services import permissions

    user = support.make_with_permissions("tasks.use")
    assert permissions.has_permission(user, "tasks.use")
    assert not permissions.has_permission(user, "tasks.assign")
    assert permissions.permissions_of(user, fresh=True) == frozenset({"tasks.use"})

    user.roles.first().permissions.add(model("core.Permission").objects.get(code="tasks.assign"))
    fresh = model("core.User").objects.get(pk=user.pk)
    assert "tasks.assign" in permissions.permissions_of(fresh, fresh=True), "право роли действует со следующего запроса"

    no_role = support.make_employee()
    assert not permissions.permissions_of(no_role, fresh=True) & set(CODES)

# --- права постановки, правки, статуса и удаления (T-9103; FR-676, FR-678, FR-695) ------------------------------

def tasks_service():
    from apps.tasks.services import tasks as module
    return module


def access_service():
    from apps.tasks.services import access as module
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
    support_org.make_member(user, mark=mark, unit=unit)
    return user


def test_create_for_self_and_for_managed_employee_allowed():
    """FR-676: сотрудник с `tasks.use` ставит задачу себе; руководитель и заместитель узла — себе и сотруднику
    своего узла и вложенного (ADR-0009, ADR-0018 п. 12)."""
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    employee = _member(tree["Группа"])
    head = _marked(tree["Отдел"], "head")
    deputy = _marked(tree["Отдел"], "deputy")
    own = tasks_service().create(employee, title="Себе", assignee=employee)
    assert (own.author_id, own.assignee_id, own.status) == (employee.pk, employee.pk, "new")
    for actor in (head, deputy):
        task = tasks_service().create(actor, title="Подчинённому", assignee=employee)
        assert task.assignee_id == employee.pk


def test_create_for_stranger_forbidden_and_error_has_field():
    """FR-676, FR-678: иной адресат отклоняется — `TasksError` с кодом `assignee_forbidden` и полем `assignee`;
    задача не создаётся; право `tasks.assign` без управления узлом не помогает."""
    tree = support_org.make_tree({"Отдел": {}, "Чужой": {}})
    outsider = _member(tree["Чужой"])
    head = _marked(tree["Отдел"], "head")
    for actor in (support_tasks.staff_user(), head):
        with pytest.raises(errors().TasksError) as raised:
            tasks_service().create(actor, title="Чужому", assignee=outsider)
        assert (raised.value.code, raised.value.field) == ("assignee_forbidden", "assignee")


def test_create_for_self_needs_only_tasks_use():
    """FR-676: создание себе — всем с `tasks.use`; право `tasks.assign` не нужно."""
    user = support.make_with_permissions("tasks.use")
    task = tasks_service().create(user, title="Своя", assignee=user)
    assert task.author_id == user.pk


def test_edit_fields_author_or_manager_of_assignee_not_manager_of_author():
    """FR-678: поля правят автор и руководитель/заместитель узла **исполнителя**; руководитель узла постановщика
    чужую задачу не правит (ADR-0018 п. 10)."""
    tree = support_org.make_tree({"Отдел автора": {}, "Отдел исполнителя": {}})
    author = _member(tree["Отдел автора"])
    assignee = _member(tree["Отдел исполнителя"])
    author_head = _marked(tree["Отдел автора"], "head")
    assignee_head = _marked(tree["Отдел исполнителя"], "head")
    task = tasks_service().create(author, title="Задача", assignee=assignee)
    assert access_service().can_edit_fields(author, task)
    assert access_service().can_edit_fields(assignee, task) is False
    assert access_service().can_edit_fields(assignee_head, task)
    assert access_service().can_edit_fields(author_head, task) is False


def test_status_executor_coexecutor_author_manager_but_not_observer():
    """FR-678, FR-679: статус меняют исполнитель, соисполнитель, постановщик, руководитель и заместитель узла
    исполнителя; наблюдатель — нет."""
    tree = support_org.make_tree({"Отдел автора": {}, "Отдел исполнителя": {}})
    author = _member(tree["Отдел автора"])
    assignee = _member(tree["Отдел исполнителя"])
    coexecutor = support.make_employee()
    observer = support.make_employee()
    assignee_head = _marked(tree["Отдел исполнителя"], "head")
    task = tasks_service().create(author, title="Задача", assignee=assignee)
    support_tasks.add_member(task, coexecutor, role="coexecutor")
    support_tasks.add_member(task, observer, role="observer")
    for viewer in (assignee, coexecutor, author, assignee_head):
        assert access_service().can_change_status(viewer, task), viewer
    assert not access_service().can_change_status(observer, task)


def test_delete_author_or_manager_of_assignee_and_soft_delete():
    """FR-695: удаляют автор и руководитель/заместитель узла исполнителя; удаление мягкое — `deleted_at`
    заполнен, напоминания сняты, задача исчезает из видимости."""
    tree = support_org.make_tree({"Отдел автора": {}, "Отдел исполнителя": {}})
    author = _member(tree["Отдел автора"])
    assignee = _member(tree["Отдел исполнителя"])
    author_head = _marked(tree["Отдел автора"], "head")
    assignee_head = _marked(tree["Отдел исполнителя"], "head")
    task = tasks_service().create(author, title="Задача", assignee=assignee)
    assert access_service().can_delete(author, task) and access_service().can_delete(assignee_head, task)
    assert not access_service().can_delete(author_head, task) and not access_service().can_delete(assignee, task)
    tasks_service().soft_delete(author, task)
    task.refresh_from_db()
    assert task.deleted_at is not None
    assert not access_service().visible(author, task)
    assert support_tasks.reminders_of(task) == []


def test_foreign_and_deleted_task_answer_404(client):
    """FR-677, FR-695: чужая и удалённая задача отвечают 404 одинаково (страница «Не найдено»), без подробностей;
    администратор портала чужих задач не видит."""
    tree = support_org.make_tree({"Отдел": {}})
    outsider = _member(tree["Отдел"])
    task = support_tasks.make_task()
    for viewer in (outsider, support.make_admin()):
        page = support.logged_in(viewer).get(f"/tasks/{task.pk}/")
        assert page.status_code == 404
    tasks_service().soft_delete(task.author, task)
    page = support.logged_in(task.author).get(f"/tasks/{task.pk}/")
    assert page.status_code == 404


def test_pages_require_tasks_use(client):
    """FR-676: без `tasks.use` страница списка отвечает 403, со правом — 200 (CONTRACT-009, 6.1)."""
    without = support.logged_in(support.make_employee())
    assert without.get("/tasks/").status_code == 403
    allowed = support.logged_in(support_tasks.staff_user())
    assert allowed.get("/tasks/").status_code == 200
