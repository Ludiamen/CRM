"""T-9123: изменения ядра и прежних модулей для среза 009 (FR-643, FR-649, FR-662, FR-674…FR-699).

План: «Изменения ядра и прежних модулей» — `Purpose.TASK` и миграция `core 0012`, права `tasks.use`/`tasks.assign`
и миграция `core 0013`, `org.services.structure.managed_units`, `config/settings.py`, `config/urls.py`,
`config/cron.py`; «Точки расширения ядра» — семь записей задач без подписок на шину; CONTRACT-009: 1.1 (точки,
`ready()`), 1.2 (cron, адреса), 1.4 (девятнадцать точек), 2.2 (Purpose, права, `managed_units`, прежнее поведение без
`apps.tasks`), 3 (записи точек), 4 (`visible`).

Код среза на уровне модуля не импортируется; `config/cron.py` и `config/urls.py` разбираются через `ast` (cron зовёт
`django.setup()` при импорте). Секретов и ПДн нет.
"""
import ast
import contextlib
import importlib
import re
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.db import connection, connections, migrations
from django.test.utils import CaptureQueriesContext

from tests import support
from tests import support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db

APP = "apps.tasks"
POINTS_19 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers",
             "login_links", "notification_kinds", "top_bar_items", "search_providers", "ticket_card_parts",
             "home_body", "unit_form_parts")
REGISTRATIONS = (
    ("menu_items", "apps.tasks.extensions", "menu_items"),
    ("notification_kinds", "apps.tasks.notify_kinds", "notification_kinds"),
    ("search_providers", "apps.tasks.services.search", "search_providers"),
    ("card_sections", "apps.tasks.extensions", "card_sections"),
    ("audit_labels", "apps.tasks.audit_labels", "audit_labels"),
    ("file_purposes", "apps.tasks.services.files", "file_purposes"),
    ("stand_reset", "apps.tasks.stand", "stand_reset"),
)
TASKS_MODULES = ("apps.tasks.extensions", "apps.tasks.notify_kinds", "apps.tasks.audit_labels",
                 "apps.tasks.stand", "apps.tasks.services")


# --- помощники файла --------------------------------------------------------------------------------------

def _migration(module: str):
    return importlib.import_module(f"apps.core.migrations.{module}")


def _migration_class(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")


def _assigned(cls):
    return {target.id: node.value for node in cls.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)}


def _guarded(node, parents, app: str) -> bool:
    current = parents.get(node)
    wanted = re.compile(r"(\w+\.)*is_installed\(\"" + re.escape(app) + r"\"\)")
    while current is not None:
        if isinstance(current, ast.If):
            test = ast.unparse(current.test).replace("'", '"').replace(" ", "")
            if wanted.fullmatch(test):
                return True
        current = parents.get(current)
    return False


def _own(point: str) -> list:
    from apps.core import extensions

    return [func for func in extensions.registered(point)
            if getattr(func, "__module__", "").startswith(APP)]


@contextlib.contextmanager
def _without_tasks():
    """«Без `apps.tasks`»: снимает регистрации задач и отвечает «нет» на `is_installed("apps.tasks")`."""
    from django.apps import apps as registry

    from apps.core import extensions

    saved = {point: list(funcs) for point, funcs in extensions._registry.items()}
    dependent = "apps.instructions"
    for funcs in extensions._registry.values():
        funcs[:] = [func for func in funcs
                    if not getattr(func, "__module__", "").startswith((APP, dependent))]
    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        return False if app_name in (APP, dependent) else real(app_name)

    registry.is_installed = is_installed
    try:
        yield
    finally:
        registry.is_installed = real
        for point, funcs in saved.items():
            extensions._registry[point][:] = funcs


# --- Purpose.TASK и миграция core 0012 --------------------------------------------------------------------

def test_purpose_task_is_last_and_migration_0012_alters_purpose():
    """FR-662, FR-693 (CONTRACT-009, 2.2): `StoredFile.Purpose` — восемь значений, `TASK = "task"` («вложение
    задачи») перед `instruction` среза 010; `max_length` 16 и умолчание `photo` не менялись; миграция
    `core 0012_storedfile_task_purpose` — один `AlterField` поля `purpose`, зависит от `0011`; строку с назначением
    `task` можно создать."""
    StoredFile = support.model("core.StoredFile")
    assert tuple(StoredFile.Purpose.values) == ("photo", "attachment", "knowledge", "lists", "feed", "messenger",
                                                "task", "instruction")
    assert StoredFile.Purpose.TASK == "task" and StoredFile.Purpose.TASK.label == "вложение задачи"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0012_storedfile_task_purpose.py"
    assert path.is_file(), "нет миграции core/0012_storedfile_task_purpose.py"
    assigned = _assigned(_migration_class(path))
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0011_storedfile_messenger_purpose")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and isinstance(operations[0], ast.Call) \
        and operations[0].func.attr == "AlterField"
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in operations[0].keywords if kw.arg in ("model_name", "name")}
    assert keywords == {"model_name": "storedfile", "name": "purpose"}

    row = StoredFile.objects.create(purpose="task", owner=None, size=1, sha256="0" * 64,
                                    content_type="application/octet-stream", status="pending")
    row.refresh_from_db()
    assert row.purpose == "task"


# --- права tasks.use/tasks.assign и миграция core 0013 ----------------------------------------------------

def test_tasks_permissions_are_installed_data_and_migration_0013_is_idempotent():
    """FR-674 (CONTRACT-009, 2.2): строки `core.Permission` `tasks.use` («Работа с задачами») и `tasks.assign`
    («Ставить задачи другим сотрудникам») выданы ролям «Администратор портала» и «Сотрудник ИТ»; миграция
    `core 0013_tasks_permissions` зависит от `0012`, её `seed` идемпотентен — повторный запуск не дублирует права и
    не меняет состав ролей."""
    Permission = support.model("core.Permission")
    Role = support.model("core.Role")
    titles = dict(Permission.objects.filter(code__in=("tasks.use", "tasks.assign")).values_list("code", "title"))
    assert titles == {"tasks.use": "Работа с задачами",
                      "tasks.assign": "Ставить задачи другим сотрудникам"}

    for role_name in ("Администратор портала", "Сотрудник ИТ"):
        codes = set(Role.objects.get(name=role_name, is_builtin=True).permissions.values_list("code", flat=True))
        assert {"tasks.use", "tasks.assign"} <= codes, f"{role_name}: {sorted(codes)}"

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0013_tasks_permissions.py"
    assert path.is_file(), "нет миграции core/0013_tasks_permissions.py"
    module = _migration("0013_tasks_permissions")
    assigned = _assigned(_migration_class(path))
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0012_storedfile_task_purpose")]
    operations = [operation for operation in module.operations
                  if isinstance(operation, migrations.RunPython)]
    assert len(operations) == 1, "в миграции прав не один RunPython"

    before = (Permission.objects.count(), Permission.objects.get(code="tasks.use").roles.count())
    editor = SimpleNamespace(connection=connections["default"])
    operations[0].code(django_apps, editor)
    operations[0].code(django_apps, editor)
    after = (Permission.objects.count(), Permission.objects.get(code="tasks.use").roles.count())
    assert after == before, "повторный seed миграции прав задвоил строки или роли"


# --- org.services.structure.managed_units ----------------------------------------------------------------

def test_managed_units_returns_head_deputy_subtree_without_plain_membership():
    """FR-677, ADR-0018 п. 10 (CONTRACT-009, 2.2): `org.services.structure.managed_units` отдаёт узлы с отметкой
    `head`/`deputy` и все вложенные по `path`; обычное членство прав не даёт; заместитель равен руководителю;
    уволенный — `frozenset()`; вызов — два запроса."""
    from apps.org.services import structure

    top = support_org.make_unit("Отдел Управления")
    child = support_org.make_unit("Сектор Управления", parent=top)
    nested = support_org.make_unit("Группа Управления", parent=child)
    head = support_tasks.head_of(top, full_name="Руководитель Управления")
    deputy = support_tasks.deputy_of(top, full_name="Заместитель Управления")
    member = support.make_employee(full_name="Рядовой Участник")
    support_org.make_member(member, top)
    dismissed = support_tasks.deputy_of(top, state="dismissed", full_name="Уволенный Заместитель")
    expected = {top.pk, child.pk, nested.pk}

    with CaptureQueriesContext(connection) as log:
        assert set(structure.managed_units(head)) == expected
    assert len(log.captured_queries) == 2, f"запросов managed_units: {len(log.captured_queries)}"
    assert set(structure.managed_units(deputy)) == expected
    assert structure.managed_units(member) == frozenset(), "обычный участник получил управление"
    assert structure.managed_units(dismissed) == frozenset(), "уволенный получил управление"


# --- config/settings.py, config/urls.py, config/cron.py ---------------------------------------------------

def test_settings_tail_and_tasks_urls_are_guarded():
    """FR-643, FR-644…FR-673 (CONTRACT-009, 1.1, 1.2): `apps.tasks` — последнее приложение; `config/urls.py`
    подключает `include("apps.tasks.urls")` ровно один раз, только внутри `apps.is_installed("apps.tasks")` и после
    `messenger`; обработчики ошибок и прежние подключения на месте."""
    from django.conf import settings

    installed = list(settings.INSTALLED_APPS)
    assert installed[-1] == "apps.instructions" and installed[-2] == "apps.tasks" and installed[-3] == "apps.messenger"

    path = support.BACKEND_DIR / "config" / "urls.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    includes = [node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "include"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    own = [node for node in includes if node.args[0].value == "apps.tasks.urls"]
    assert len(own) == 1, f"подключений apps.tasks.urls: {len(own)}"
    assert _guarded(own[0], parents, APP), "include(apps.tasks.urls) вне проверки apps.is_installed"
    assert [node.args[0].value for node in includes
            if node is not own[0] and _guarded(node, parents, APP)] == [], "под проверкой tasks подключено лишнее"
    assert len(includes) >= 9, "прежние подключения адресов исчезли"
    messenger = [index for index, node in enumerate(includes) if node.args[0].value == "apps.messenger.urls"]
    assert messenger and messenger[0] < includes.index(own[0]), "include задач стоит до include мессенджера"
    assert "handler404" in source and "handler500" in source, "обработчики ошибок пропали"


def test_cron_has_27_registers_and_three_guarded_tasks_jobs():
    """FR-670 (CONTRACT-009, 1.2, 1.4): в `config/cron.py` двадцать семь вызовов `register`; три задания задач —
    `tasks_reminders` `*/5` (300 с), `tasks_digest` `*/15` (300 с), `tasks_retention` `42 23` (600 с) в очереди
    `maintenance`, каждое под `apps.is_installed("apps.tasks")`; прежние записи те же, срез 010 добавил три."""
    source = (support.BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "register"]
    assert len(calls) == 27, f"вызовов register {len(calls)}, ожидается 27"
    found = {}
    for node in calls:
        options = {kw.arg: (ast.literal_eval(kw.value) if isinstance(kw.value, ast.Constant) else None)
                   for kw in node.keywords}
        target = aliases.get(getattr(node.args[0], "id", ""), "")
        found[options.get("name")] = (target, options.get("queue_name"), options.get("cron"),
                                       options.get("job_timeout"), _guarded(node, parents, APP))
    assert found["tasks_reminders"] == ("apps.tasks.tasks.tasks_reminders", "maintenance", "*/5 * * * *", 300, True)
    assert found["tasks_digest"] == ("apps.tasks.tasks.tasks_digest", "maintenance", "*/15 * * * *", 300, True)
    assert found["tasks_retention"] == ("apps.tasks.tasks.tasks_retention", "maintenance", "42 23 * * *", 600, True)
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and node.module == "apps.tasks.tasks"]
    assert imports and all(_guarded(node, parents, APP) for node in imports), "импорт заданий вне проверки"


# --- точки расширения (CONTRACT-009, 1.1, 3) -------------------------------------------------------------

def test_points_stay_19_and_tasks_registers_seven_points_with_stand_reset_last():
    """FR-643, FR-649, FR-667 (CONTRACT-009, 1.1, 3): `POINTS` ядра — те же девятнадцать имён; `ready()` задач
    регистрирует по одной функции в `menu_items`, `notification_kinds`, `search_providers`, `card_sections`,
    `audit_labels`, `file_purposes`, `stand_reset`; `role_sources` не трогает; `stand_reset` — последняя
    регистрация точки; подписок на шину нет."""
    from apps.core import events, extensions

    assert tuple(extensions.POINTS) == POINTS_19 and len(extensions.POINTS) == 19
    assert set(extensions._registry) == set(POINTS_19)
    for point, module, name in REGISTRATIONS:
        own = _own(point)
        assert [(func.__module__, func.__name__) for func in own] == [(module, name)], f"точка {point}: {own}"
    assert _own("role_sources") == [], "tasks регистрирует role_sources"
    assert extensions.registered("stand_reset")[-2].__module__ == "apps.tasks.stand"
    assert extensions.registered("stand_reset")[-2].__name__ == "stand_reset"
    assert extensions.registered("stand_reset")[-1].__module__ == "apps.instructions.stand"

    own_bus = [handler for handlers in events._registry.values() for handler in handlers
               if getattr(handler, "__module__", "").startswith(APP)]
    assert own_bus == [], f"у задач есть подписки на шину: {own_bus}"


# --- прежнее поведение без приложения (CONTRACT-009, 2.2) -------------------------------------------------

def test_previous_menu_search_card_and_file_purposes_without_tasks():
    """FR-643, FR-649, FR-662 (CONTRACT-009, 2.2): с задачами у администратора восемнадцать пунктов меню, группа
    поиска «Задачи» и назначение файла `task`; без приложения — прежние шестнадцать пунктов, поиск без «Задач»,
    назначений файла задач нет, карточка без раздела задач; прочие пункты не меняются."""
    from apps.core import extensions
    from apps.core.services import permissions

    admin = support.make_admin(full_name="Администратор Прежнего")
    person = support_tasks.staff_user(full_name="Сотрудник Прежнего")
    support_tasks.make_task("Задача прежнего поведения", author=person, assignee=person)

    full_menu = permissions.menu_for(admin)
    assert len(full_menu) == 21, f"пунктов меню с задачами и поручениями: {len(full_menu)}"
    assert "tasks" in [provider.key for func in extensions.registered("search_providers") for provider in func()]

    with _without_tasks():
        menu = permissions.menu_for(admin)
        providers = [provider.key for func in extensions.registered("search_providers") for provider in func()]
        purposes = [purpose.purpose for func in _own("file_purposes") for purpose in func()]
        sections = [section for func in _own("card_sections") for section in func(person, person)]

    assert len(menu) == 17, f"пунктов меню без задач: {len(menu)}"
    assert [item for item in full_menu
            if item["url"] not in ("/tasks/", "/settings/tasks/", "/instructions/",
                                    "/settings/instructions/")] == menu
    assert "tasks" not in providers and purposes == [] and sections == []