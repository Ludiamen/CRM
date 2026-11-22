"""T-9122: границы приложения «Задачи» (FR-643, FR-674…FR-699; CONST «модуль-приложение»).

План: «Сверка с конституцией» (связи — точки расширения ядра и публичные службы `core`, `org`, `notify`),
«Интеграции», «Где живёт код». CONTRACT-009: 1.1 (последнее приложение и выключение), 2.2 (прежнее поведение без
`apps.tasks`), 3 (записи точек), 4 (видимость), 5.1 (публичные службы). `apps.tasks` не импортирует модели чужих
приложений и приложения `feed`, `messenger`, `lists`, `knowledge`, `servicedesk`, `search`, `integrations`; из
`org` и `notify` берутся только публичные службы. Без регистраций задач меню, поиск, карточка, каталог уведомлений
и назначения файлов работают как после среза 008.

Код среза на уровне модуля не импортируется (модели — `support.model`, всё прочее — внутри тестов), поэтому
`pytest --collect-only` проходит до появления кода. Секретов и ПДн нет.
"""
import ast
import contextlib
import importlib
import re

import pytest

from tests import support
from tests import support_tasks

pytestmark = pytest.mark.django_db

APP = "apps.tasks"
ORG_STRUCTURE = "apps.org.services.structure"
ORG_CALENDAR = "apps.org.services.calendar"
NOTIFY_DISPATCH = "apps.notify.services.dispatch"
NOTIFY_QUIET = "apps.notify.services.quiet"
FOREIGN_APPS = ("feed", "messenger", "lists", "knowledge", "servicedesk", "search", "integrations")
TASK_MODELS = ("Task", "TaskMember", "TaskCategory", "PlanColumn", "TaskReminder", "TaskComment", "TaskFile",
               "TaskSettings")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
MENU_TITLES = ("Задачи", "Настройки задач")
MENU_URLS = ("/tasks/", "/settings/tasks/")


# --- разбор импортов (образец — test_messenger_boundaries.py) ---------------------------------------------

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


def _sources(*parts: str) -> dict:
    root = support.BACKEND_DIR.joinpath(*parts)
    paths = sorted(root.rglob("*.py"))
    assert paths, f"нет исходников в {root}"
    return {path: path.read_text(encoding="utf-8") for path in paths}


def _scan(*parts: str, bad, with_strings: bool = True) -> list[str]:
    offenders = []
    for path, text in _sources(*parts).items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        hits = sorted(n for n in _targets(text, list(rel.parts[:-1]), with_strings=with_strings) if bad(n))
        if hits:
            offenders.append(f"{path.relative_to(support.BACKEND_DIR)}: {hits}")
    return offenders


def _check_scanner(bad, package: list[str], found: tuple[str, ...], clean: tuple[str, ...],
                   *, with_strings=True) -> None:
    for sample in found:
        assert any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), f"разбор не нашёл: {sample}"
    for sample in clean:
        assert not any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), \
            f"ложное срабатывание: {sample}"


def _own(point: str) -> list:
    from apps.core import extensions

    return [func for func in extensions.registered(point)
            if getattr(func, "__module__", "").startswith(APP)]


@contextlib.contextmanager
def _without_tasks():
    """«Без `apps.tasks`»: снимает регистрации задач и отвечает «нет» на `is_installed("apps.tasks")`.

    `INSTALLED_APPS` не перезагружается (как `support_feed.without_feed`/`support_messenger.without_messenger`);
    по выходу — в том числе по исключению — регистрации и ответ `is_installed` возвращаются.
    """
    from django.apps import apps as registry

    from apps.core import events, extensions

    saved_points = {point: list(funcs) for point, funcs in extensions._registry.items()}
    for funcs in extensions._registry.values():
        funcs[:] = [func for func in funcs if not getattr(func, "__module__", "").startswith(APP)]
    saved_events = {name: list(handlers) for name, handlers in events._registry.items()}
    for name, handlers in list(events._registry.items()):
        for handler in list(handlers):
            if getattr(handler, "__module__", "").startswith(APP):
                events.unsubscribe(name, handler)
    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        return False if app_name == APP else real(app_name)

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


# --- 1. границы импортов приложения -----------------------------------------------------------------------

def test_tasks_imports_only_public_core_org_and_notify_services():
    """FR-643 (CONST «модуль-приложение»): в `apps/tasks/**` нет импорта `feed`, `messenger`, `lists`, `knowledge`,
    `servicedesk`, `search`, `integrations`; из `org` — только `services.structure`/`services.calendar`, из `notify` —
    только `services.dispatch`/`services.quiet`; модели `org` и `notify` напрямую не импортируются; публичные службы
    `org` и `notify` действительно используются; сам разбор находит нарушения на образцах."""
    def bad(name: str) -> bool:
        if any(_under(name, f"apps.{app}") for app in FOREIGN_APPS):
            return True
        if _under(name, "apps.org"):
            return not (_under(name, ORG_STRUCTURE) or _under(name, ORG_CALENDAR))
        if _under(name, "apps.notify"):
            return not (_under(name, NOTIFY_DISPATCH) or _under(name, NOTIFY_QUIET))
        return any(_under(name, f"apps.{app}.models") for app in ("org", "notify"))

    _check_scanner(bad, ["apps", "tasks", "services"],
                   ("from apps.org.models import Unit", "from apps.notify.models import Notification",
                    "from apps.feed.services import text", "from apps.messenger.services import chats",
                    "import apps.lists.models", "from apps.search import parse",
                    "from apps.integrations.clamav.services import scan",
                    "import importlib\nimportlib.import_module('apps.servicedesk.models')"),
                   ('"""apps.org.models в докстринге"""\nimport os', "from apps.org.services import structure",
                    "from apps.notify.services import dispatch", "from apps.core.models import User",
                    "from ..models import Task"))
    assert _scan("apps", "tasks", bad=bad, with_strings=False) == []

    used = set()
    for path, text in _sources("apps", "tasks").items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        used |= _targets(text, list(rel.parts[:-1]), with_strings=False)
    assert any(_under(name, ORG_STRUCTURE) for name in used), "tasks не использует apps.org.services.structure"
    assert any(_under(name, NOTIFY_DISPATCH) for name in used), "tasks не использует dispatch уведомлений"


def test_models_link_only_to_core_and_tasks():
    """FR-643: у моделей `tasks` есть все восемь моделей плана; каждая связь ведёт только в `core` или `tasks` —
    моделей `org`/`notify` в связях нет (подразделения и уведомления — через публичные службы)."""
    from django.apps import apps as registry

    models = {model.__name__: model for model in registry.get_app_config("tasks").get_models()}
    assert set(TASK_MODELS) <= set(models), f"нет моделей: {sorted(set(TASK_MODELS) - set(models))}"
    seen = 0
    for name, model in models.items():
        for field in model._meta.get_fields():
            if field.is_relation and not field.auto_created:
                seen += 1
                label = field.related_model._meta.app_label
                assert label in ("core", "tasks"), f"{name}.{field.name} ведёт в приложение {label}"
    assert seen > 0, "у моделей tasks нет ни одной связи"


def test_no_previous_app_imports_tasks():
    """FR-643: ни один файл прежних приложений (`core`, `org`, `notify`, `knowledge`, `servicedesk`, `lists`,
    `search`, `feed`, `messenger`, `integrations`) не импортирует `apps.tasks`; `config/urls.py` подключает адреса
    под `apps.is_installed` — это не импорт приложения, а проверка."""
    def bad(name: str) -> bool:
        return _under(name, APP)

    _check_scanner(bad, ["apps", "core", "views"],
                   ("from apps.tasks.models import Task", "import apps.tasks", "from apps import tasks",
                    "import importlib\nimportlib.import_module('apps.tasks.services.list')"),
                   ('"""apps.tasks в докстринге"""\n# apps.tasks в комментарии\nimport os',
                    "from apps.core import extensions", "event = 'tasks.created'"),
                   with_strings=False)
    offenders = []
    for app in ("core", "org", "notify", "knowledge", "servicedesk", "lists", "search", "feed", "messenger",
                "integrations"):
        offenders += _scan("apps", app, bad=bad, with_strings=False)
    assert offenders == [], f"прежний модуль импортирует tasks: {offenders}"


def test_tasks_registers_no_bus_subscriptions():
    """FR-643 (план, «Точки расширения ядра»): у среза нет подписок на шину событий — ни один обработчик
    `apps.core.events` не определён в `apps.tasks`."""
    from apps.core import events

    own = [f"{name}:{handler!r}" for name, handlers in events._registry.items() for handler in handlers
           if getattr(handler, "__module__", "").startswith(APP)]
    assert own == [], f"у задач есть подписки на шину: {own}"


# --- 2. приложение отключается без ошибок (CONTRACT-009, 2.2) ---------------------------------------------

def test_without_tasks_menu_search_card_and_file_purpose_have_no_trace():
    """FR-643, FR-649, FR-662, FR-697, FR-698: пока регистрации задач на месте, в меню два их пункта, в поиске
    группа «Задачи», в карточке — раздел, в назначениях файлов — `task`. Без приложения (`_without_tasks`) меню,
    поиск, карточка и назначения файлов прежние: следов задач нет, прочие пункты не меняются; `is_installed`
    отвечает «нет», после блока — снова «да»."""
    from django.apps import apps as registry

    from apps.core import extensions
    from apps.core.services import permissions

    admin = support.make_admin(full_name="Администратор Границ")
    person = support_tasks.staff_user(full_name="Сотрудник С Задачей")
    task = support_tasks.make_task("Задача границ", author=person, assignee=person)

    assert registry.is_installed(APP)
    full_menu = permissions.menu_for(admin.user)
    assert [item for item in full_menu if item["title"] in MENU_TITLES or item["url"] in MENU_URLS]
    assert "tasks" in [provider.key for func in extensions.registered("search_providers")
                       for provider in func()]
    assert [purpose.purpose for func in _own("file_purposes") for purpose in func()] == ["task"]
    assert _own("card_sections")

    with _without_tasks():
        menu = permissions.menu_for(admin.user)
        providers = [provider.key for func in extensions.registered("search_providers") for provider in func()]
        purposes = [purpose.purpose for func in _own("file_purposes") for purpose in func()]
        sections = [section for func in _own("card_sections") for section in func(person, person)]
        installed = registry.is_installed(APP)

    assert not [item for item in menu if item["title"] in MENU_TITLES or item["url"] in MENU_URLS]
    assert [item for item in full_menu if item["url"] not in MENU_URLS] == menu, "прочие пункты меню изменились"
    assert "tasks" not in providers, "без приложения остался поставщик поиска «Задачи»"
    assert purposes == [] and sections == [], "без приложения остались назначение файла или раздел карточки"
    assert installed is False, "is_installed не ответил «нет»"
    assert registry.is_installed(APP) is True, "после блока is_installed не вернулся"
    assert task.pk is not None


def test_search_and_card_pages_open_without_tasks():
    """FR-643, FR-697, FR-698: без приложения `/search/` и карточка сотрудника отвечают 200 и не содержат группы
    «Задачи» и раздела с задачей; прочие группы и вкладки карточки на месте."""
    from tests import support_feed

    admin = support.make_admin(full_name="Администратор Страниц")
    author = support_tasks.staff_user(full_name="Автор Без Приложения")
    task = support_tasks.make_task("След задачи на странице", author=author, assignee=author)
    support_feed.make_post(support_feed.as_writer().user, to=("all",), text="Запись ленты границ")
    client = support.logged_in(admin)

    with _without_tasks():
        search = client.get("/search/", {"q": "След"})
        card = client.get(f"/staff/{author.pk}/")

    assert search.status_code == 200 and card.status_code == 200
    search_html = search.content.decode("utf-8")
    card_html = card.content.decode("utf-8")
    assert 'data-search-group="tasks"' not in search_html
    assert 'data-search-group="feed"' in search_html, "без задач пропала группа «Лента»"
    assert f"/tasks/{task.pk}/" not in card_html and task.title not in card_html, "в карточке остался раздел задач"