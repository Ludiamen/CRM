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


# --- T-10122: settings/urls/cron/точки ------------------------------------------------------------

APP = "apps.instructions"
POINTS_19 = (
    "menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections", "day_marks",
    "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
    "notification_kinds", "top_bar_items", "search_providers", "ticket_card_parts", "home_body", "unit_form_parts",
)
REGISTRATIONS = {
    "menu_items": ("apps.instructions.extensions", "menu_items"),
    "notification_kinds": ("apps.instructions.notify_kinds", "notification_kinds"),
    "audit_labels": ("apps.instructions.audit_labels", "audit_labels"),
    "file_purposes": ("apps.instructions.services.files", "file_purposes"),
    "stand_reset": ("apps.instructions.stand", "stand_reset"),
}


def _own(point):
    from apps.core import extensions

    return [func for func in extensions.registered(point) if func.__module__.startswith(APP)]


def _cron_calls():
    from tests.support import BACKEND_DIR

    source = (BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def guarded(node):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, ast.If):
                text = ast.unparse(current.test).replace("'", '"')
                if 'is_installed("apps.instructions")' in text:
                    return True
            current = parents.get(current)
        return False

    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            first = node.args[0] if node.args else None
            target = aliases.get(first.id, first.id) if isinstance(first, ast.Name) else None
            options = {kw.arg: (ast.literal_eval(kw.value) if isinstance(kw.value, ast.Constant) else None)
                       for kw in node.keywords}
            calls.append({"target": target, **options, "guarded": guarded(node)})
    return calls


def test_settings_tail_and_instructions_urls_are_guarded():
    """FR-700…723 (CONTRACT-010, 1.1): `apps.instructions` — последнее приложение; `config/urls.py` подключает
    `apps.instructions.urls` ровно один раз, под `apps.is_installed("apps.instructions")`, после задач."""
    from django.conf import settings

    installed = list(settings.INSTALLED_APPS)
    assert installed[-1] == APP and installed[-2] == "apps.tasks"

    path = support.BACKEND_DIR / "config" / "urls.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    includes = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "include" and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    own = [node for node in includes if node.args[0].value == "apps.instructions.urls"]
    assert len(own) == 1
    current = parents.get(own[0])
    guarded = False
    while current is not None:
        if isinstance(current, ast.If):
            test = ast.unparse(current.test).replace("'", '"').replace(" ", "")
            if 'is_installed("apps.instructions")' in test:
                guarded = True
                break
        current = parents.get(current)
    assert guarded, "include поручений вне проверки установки"


def test_cron_has_27_registers_and_three_guarded_instructions_jobs():
    """FR-711, NFR-729: три задания поручений в cron с расписанием и очередью `maintenance`, под проверкой
    установки; всего 27 вызовов."""
    calls = _cron_calls()
    assert len(calls) == 27, f"вызовов register {len(calls)}"
    expected = {
        "instructions_reminders": ("apps.instructions.tasks.instructions_reminders", "*/5 * * * *", 300),
        "instructions_digest": ("apps.instructions.tasks.instructions_digest", "*/15 * * * *", 300),
        "instructions_retention": ("apps.instructions.tasks.instructions_retention", "43 23 * * *", 600),
    }
    by_name = {item.get("name"): item for item in calls}
    for name, (target, cron, timeout) in expected.items():
        item = by_name.get(name)
        assert item is not None, f"нет задания {name}"
        assert (item["target"], item["queue_name"], item["cron"], item["job_timeout"]) == (
            target, "maintenance", cron, timeout)
        assert item["guarded"], f"{name} вне проверки установки"


def test_points_stay_19_and_instructions_register_expected_points():
    """FR-700…723 (CONTRACT-010, 3): `POINTS` ядра — те же девятнадцать; поручения регистрируют меню, виды,
    подписи, назначение файла и сброс стенда; `stand_reset` — последняя запись точки."""
    from apps.core import extensions

    assert tuple(extensions.POINTS) == POINTS_19 and len(extensions.POINTS) == 19
    assert set(extensions._registry) == set(POINTS_19)
    for point, (module, name) in REGISTRATIONS.items():
        own = _own(point)
        assert [(func.__module__, func.__name__) for func in own] == [(module, name)], point
    assert _own("search_providers") == [], "поручения не регистрируют поиск"
    assert _own("card_sections") == [], "поручения не регистрируют раздел карточки"
    assert extensions.registered("stand_reset")[-1].__module__ == "apps.instructions.stand"
