"""Срез 009 «Задачи»: права-данные (T-9004; FR-676, FR-678).

`tasks.use` и `tasks.assign` — строки `core.Permission`, выданные встроенным ролям миграцией `core 0013`
(PLAN-009, «Права»; ADR-0018 п. 13). Поведение правки и постановки задач проверяет T-9103.
"""
import ast

import pytest

from tests import support
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