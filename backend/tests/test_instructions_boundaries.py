"""Срез 010 «Поручения»: границы приложения (T-10119; конституция, «модуль-приложение»).

`apps.instructions` не импортирует модели чужих приложений и приложения ленты, мессенджера, списков, базы знаний,
сервис-деска, поиска и интеграций; из `tasks` — только публичные службы; подписка на шину — только
`core.user_dismissed`. Код среза на уровне модуля не импортируется.
"""
import ast
import contextlib
import importlib
import re

import pytest

from tests import support

pytestmark = pytest.mark.django_db

APP = "apps.instructions"
TASKS_PUBLIC = ("apps.tasks.services.tasks", "apps.tasks.services.access")
FOREIGN_APPS = ("feed", "messenger", "lists", "knowledge", "servicedesk", "search", "integrations")
MENU_TITLES = ("Поручения", "Настройки поручений")
MENU_URLS = ("/instructions/", "/settings/instructions/")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")


def _sources():
    root = support.BACKEND_DIR / "apps" / "instructions"
    return {path: path.read_text(encoding="utf-8") for path in root.rglob("*.py") if "__pycache__" not in str(path)}


def _docstrings(tree) -> set[int]:
    found = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _targets(source: str, package: list[str], *, with_strings: bool = True) -> set[str]:
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                module = node.module or ""
            for alias in node.names:
                found.add(module if alias.name == "*" else f"{module}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
        elif with_strings and isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings and MODULE_PATH.fullmatch(node.value):
            found.add(node.value)
    return found


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def test_imports_are_limited_to_public_services():
    """Конституция: из `tasks` — только `services.tasks`/`services.access`, моделей `tasks` нет; чужие приложения
    не импортируются; из `org` и `notify` — только публичные службы."""
    def bad(name: str) -> bool:
        if any(_under(name, f"apps.{app}") for app in FOREIGN_APPS):
            return True
        if _under(name, "apps.tasks"):
            return not any(_under(name, allowed) for allowed in TASKS_PUBLIC)
        if _under(name, "apps.org"):
            return not (_under(name, "apps.org.services.structure") or _under(name, "apps.org.services.calendar"))
        if _under(name, "apps.notify"):
            return not (_under(name, "apps.notify.services.dispatch") or _under(name, "apps.notify.services.quiet"))
        return any(_under(name, f"apps.{app}.models") for app in ("org", "notify"))

    for path, text in _sources().items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        used = _targets(text, list(rel.parts[:-1]), with_strings=False)
        violations = sorted(name for name in used if bad(name))
        assert not violations, f"{path}: запрещённые импорты {violations}"

    all_used = set()
    for path, text in _sources().items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        all_used |= _targets(text, list(rel.parts[:-1]), with_strings=False)
    assert any(_under(name, "apps.tasks.services.tasks") for name in all_used), "задачи создаются не службой"
    assert any(_under(name, "apps.notify.services.dispatch") for name in all_used), "уведомления не через dispatch"


def test_models_link_only_core_tasks_and_own_app():
    """Конституция: связи моделей поручений ведут только в `core`, `tasks` и собственное приложение."""
    labels = ("Instruction", "InstructionMember", "InstructionReportDate", "InstructionReport",
              "InstructionReportPart", "InstructionFile", "InstructionTransfer", "InstructionReminder",
              "InstructionTask", "InstructionSettings")
    for label in labels:
        model = support.model(f"instructions.{label}")
        for field in model._meta.get_fields():
            remote = getattr(field, "remote_field", None)
            if remote is None:
                continue
            app = getattr(getattr(remote, "model", None), "_meta", None)
            if app is not None:
                assert app.app_label in {"core", "tasks", "instructions"}, f"{label}.{field.name} → {app.app_label}"


def test_only_dismissal_subscription_on_bus():
    """План: единственная подписка на шину — `core.user_dismissed` для переназначения."""
    from apps.core import events

    own = [(name, handler) for name, handlers in events._registry.items() for handler in handlers
           if getattr(handler, "__module__", "").startswith(APP)]
    assert len(own) == 1, f"подписки поручений: {own}"
    assert own[0][0] == "core.user_dismissed"


@contextlib.contextmanager
def _without_instructions():
    from django.apps import apps as registry

    from apps.core import events, extensions

    saved_points = {point: list(funcs) for point, funcs in extensions._registry.items()}
    saved_events = {name: list(handlers) for name, handlers in events._registry.items()}
    for point, funcs in list(extensions._registry.items()):
        extensions._registry[point][:] = [func for func in funcs
                                          if not getattr(func, "__module__", "").startswith(APP)]
    for name, handlers in list(events._registry.items()):
        for handler in list(handlers):
            if getattr(handler, "__module__", "").startswith(APP):
                events.unsubscribe(name, handler)
    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        if app_name == APP or app_name == "apps.tasks":
            return False if app_name == APP else real(app_name)
        return real(app_name)

    registry.is_installed = is_installed
    try:
        yield
    finally:
        registry.is_installed = real
        for point, funcs in saved_points.items():
            extensions._registry[point][:] = funcs
        for name, handlers in saved_events.items():
            for handler in events.subscribers(name):
                events.unsubscribe(name, handler)
            for handler in handlers:
                events.subscribe(name, handler)


def test_without_instructions_menu_and_file_purpose_have_no_trace():
    """Конституция, FR-720: с регистрациями в меню два пункта поручений, в назначениях файлов — `instruction`;
    без приложения следов нет, прочие пункты не меняются."""
    from django.apps import apps as registry

    from apps.core import extensions
    from apps.core.services import permissions

    admin = support.make_admin(full_name="Администратор Границ")
    assert registry.is_installed(APP)
    full_menu = permissions.menu_for(admin)
    assert [item for item in full_menu if item["title"] in MENU_TITLES or item["url"] in MENU_URLS]
    purposes = [purpose for func in extensions.registered("file_purposes")
                if getattr(func, "__module__", "").startswith(APP) for purpose in func()]
    assert [item.purpose for item in purposes] == ["instruction"]

    with _without_instructions():
        menu = permissions.menu_for(admin)
        left = [purpose for func in extensions.registered("file_purposes")
                if getattr(func, "__module__", "").startswith(APP) for purpose in func()]
        installed = registry.is_installed(APP)

    assert not [item for item in menu if item["title"] in MENU_TITLES or item["url"] in MENU_URLS]
    assert [item for item in full_menu if item["url"] not in MENU_URLS] == menu, "прочие пункты меню изменились"
    assert left == []
    assert installed is False
    assert registry.is_installed(APP) is True