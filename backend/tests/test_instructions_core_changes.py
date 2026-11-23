"""Срез 010: изменения ядра (T-10003 и далее). Права — данные, `Purpose`, settings/urls/cron."""
import ast

import pytest

from tests import support
from tests.support import model

pytestmark = pytest.mark.django_db

CODES = ("instructions.use", "instructions.assign")


def test_instructions_permissions_created_and_granted():
    """FR-702, FR-703: права `instructions.use`/`instructions.assign` созданы миграцией `core 0015`,
    зависят от `0014`; выданы «Администратору портала» и «Сотруднику ИТ»."""
    rows = dict(model("core.Permission").objects.filter(code__in=CODES).values_list("code", "title"))
    assert set(rows) == set(CODES) and all(rows.values())
    for name in (support.ADMIN_ROLE, support.STAFF_ROLE):
        role = model("core.Role").objects.get(name=name, is_builtin=True)
        assert set(CODES) <= set(role.permissions.values_list("code", flat=True)), name
    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0015_instructions_permissions.py"
    assert path.is_file()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0014_storedfile_instruction_purpose")]
