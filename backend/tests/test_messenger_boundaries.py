"""T-8125: границы модуля «Мессенджер» (FR-643, FR-645, FR-649, FR-650, FR-662, FR-667).

План: «Сверка с конституцией», «Точки расширения ядра и шина событий», «Модуль и выключение»; CONTRACT-008: 1.1, 1.4,
2.1, 2.2, 3.1, 3.4, 4.1-4.4. `messenger` подключается к ядру и прежним модулям только точками расширения, шиной и
публичными службами: из `org` — `apps.org.services.structure`, из `notify` — `dispatch.create` и `live.group`, модели
`org`, `notify` и `feed` не импортируются. Без его регистраций (`support_messenger.without_messenger`) меню, поиск,
каталог уведомлений, карточка сотрудника, форма узла, `/notifications/` и колокольчик работают как после среза 007.
Имена кода среза импортируются внутри тестов: сбор (`pytest --collect-only`) проходит до появления кода.
"""
import ast
import dataclasses
import importlib
import re

import pytest

from tests import support
from tests import support_messenger as sm

pytestmark = pytest.mark.django_db

APP = "apps.messenger"
PREVIOUS_APPS = ("core", "org", "notify", "feed")
ORG_STRUCTURE = "apps.org.services.structure"
DISPATCH = "apps.notify.services.dispatch"
NOTIFY_PAGES = "apps.notify.services.pages"
LIVE = "apps.notify.services.live"
MESSENGER_MODELS = ("Chat", "ChatMember", "ChatRead", "Message", "MessageAttachment", "MessengerSettings")
# POINTS ядра до среза 008 (CONTRACT-008, 3.1): прежние восемнадцать имён в прежнем порядке
POINTS_18 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
             "notification_kinds", "top_bar_items", "search_providers", "ticket_card_parts", "home_body")
POINTS_19 = POINTS_18 + sm.POINTS_008
# регистрации `register_all()` в порядке строк плана (CONTRACT-008, 3.4; решение К8): `stand_reset` — последняя
REGISTRATIONS = (
    ("menu_items", "apps.messenger.extensions", "menu_items"),
    ("card_sections", "apps.messenger.extensions", "card_sections"),
    ("notification_kinds", "apps.messenger.notify_kinds", "notification_kinds"),
    ("search_providers", "apps.messenger.services.search", "search_providers"),
    ("file_purposes", "apps.messenger.services.files", "file_purposes"),
    ("audit_labels", "apps.messenger.audit_labels", "audit_labels"),
    ("unit_form_parts", "apps.messenger.unit_form", "form_parts"),
    ("stand_reset", "apps.messenger.stand", "stand_reset"),
)
# точки, которые мессенджер не использует (CONTRACT-008, 3.4): колокольчик остаётся за `notify`
UNUSED_POINTS = ("top_bar_items", "home_notices", "home_body", "role_sources", "role_usage", "staff_directory",
                 "day_marks", "unit_usage", "mail_renderers", "login_links", "ticket_card_parts")
# строки-пути `apps.messenger`, которые контракт разрешает прежним модулям: `apps.is_installed("apps.messenger")`
# (признак `bell_link`, 3.3) и имя журнала сбоев полей формы узла `apps.messenger.unit_form` (3.2)
ALLOWED_PATHS = frozenset({"apps.messenger", "apps.messenger.unit_form"})
MENU_TITLES = ("Мессенджер", "Настройки мессенджера")
MENU_URLS = tuple(sm.MENU_008)
WORD = "принтер"
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
STYLE_ATTR = re.compile(r"\sstyle\s*=", re.I)
EVENT_ATTR = re.compile(r"\son[a-z]+\s*=", re.I)


# --- разбор импортов (как в test_feed_boundaries.py, test_kb_boundaries.py) -----------------------------------

def _docstrings(tree) -> set[int]:
    """Идентификаторы строк-докстрингов модуля, классов и функций: их строки-пути нарушением не считаются."""
    found = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _targets(source: str, package: list[str], *, with_strings: bool = True) -> set[str]:
    """Абсолютные имена, от которых зависит файл (`ast`): `import a.b`; `from a.b import c` — имя `a.b.c`;
    относительные импорты; `import_module("…")`/`__import__("…")`; при `with_strings` — ещё строка-путь модуля
    целиком вне докстрингов."""
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


def _strings(source: str) -> set[str]:
    """Строки-пути модулей в файле (`ast`), без строк-докстрингов и без аргументов импорта."""
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in docstrings and MODULE_PATH.fullmatch(node.value)}


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


def _check_scanner(bad, package: list[str], found: tuple[str, ...], clean: tuple[str, ...], *, with_strings=True) -> None:
    """Сам разбор находит нарушения на образцах и не срабатывает на чистых (иначе пустой список ничего не
    доказывает)."""
    for sample in found:
        assert any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), f"разбор не нашёл: {sample}"
    for sample in clean:
        assert not any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), \
            f"ложное срабатывание: {sample}"


def _imported_anywhere(root: str) -> bool:
    """Есть ли в `apps/messenger/**` импорт (без строк-путей) чего-либо из `root`."""
    for path, text in _sources("apps", "messenger").items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        if any(_under(n, root) for n in _targets(text, list(rel.parts[:-1]), with_strings=False)):
            return True
    return False


def _is_messenger(func) -> bool:
    return getattr(func, "__module__", "").startswith(APP)


def _own(point: str) -> list:
    """Функции точки, определённые в модулях `apps.messenger.*`."""
    from apps.core import extensions

    return [f for f in extensions.registered(point) if _is_messenger(f)]


def _html(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, f"{path}: статус {response.status_code}"
    return response.content.decode()


def _menu_links(html: str) -> list[tuple[str, str]]:
    """Пункты `nav#main-menu` по порядку: (адрес, подпись)."""
    nav = re.search(r'<nav id="main-menu".*?</nav>', html, re.S)
    assert nav, "в оболочке нет nav#main-menu"
    row = re.compile(r'<a class="menu-item[^"]*" href="([^"]*)"[^>]*>.*?<span class="menu-label">(.*?)</span>', re.S)
    return [(href, re.sub(r"\s+", " ", label).strip()) for href, label in row.findall(nav.group(0))]


# --- FR-643, FR-650, FR-662: границы импортов (CONTRACT-008, 4.1-4.3) -------------------------------------------

def test_no_previous_module_imports_apps_messenger():
    """FR-643: ни один файл `apps/core/**`, `org`, `notify`, `feed` не импортирует `apps.messenger` (ни `import`, ни
    `import_module`, ни строка-путь вне докстрингов); из строк-путей допустимы только названные контрактом
    `"apps.messenger"` (аргумент `apps.is_installed` для признака `bell_link`, 3.3) и `"apps.messenger.unit_form"`
    (имя журнала сбоев полей формы узла, 3.2); сам разбор находит нарушения на образцах."""

    def bad(name):
        return _under(name, APP)

    _check_scanner(bad, ["apps", "core", "services"],
                   ("from apps.messenger.services import members", "import apps.messenger", "from apps import messenger",
                    "from ...messenger import tasks", "x = 'apps.messenger.extensions'",
                    "import importlib\nimportlib.import_module('apps.messenger.views')"),
                   ('"""apps.messenger в докстринге"""\n# apps.messenger в комментарии\nimport os',
                    "from apps.core import extensions", "event = 'messenger.chat_deleted'"))
    offenders = []
    for app in PREVIOUS_APPS:
        offenders += _scan("apps", app, bad=bad, with_strings=False)
        for path, text in _sources("apps", app).items():
            extra = sorted(name for name in _strings(text) if _under(name, APP) and name not in ALLOWED_PATHS)
            if extra:
                offenders.append(f"{path.relative_to(support.BACKEND_DIR)}: строки-пути {extra}")
    assert offenders == [], f"прежний модуль знает о messenger: {offenders}"


def test_messenger_does_not_import_org_notify_feed_models():
    """FR-643, FR-650, FR-663: в `apps/messenger/**` нет импорта `apps.feed` и моделей `org`, `notify`; из `apps.org`
    импортируется только `apps.org.services.structure`, из `apps.notify` — только `dispatch` (`create`) и `live`
    (`group`), каждый вызов — под `apps.is_installed`; у моделей среза нет связей в чужие приложения, подразделение —
    число `Chat.unit_id`; сам разбор находит нарушения на образцах."""
    from django.apps import apps
    from django.db.models import PositiveIntegerField

    def bad(name):
        return _under(name, "apps.feed") or any(_under(name, f"apps.{app}.models") for app in ("org", "notify"))

    _check_scanner(bad, ["apps", "messenger", "services"],
                   ("from apps.org.models import Unit", "import apps.notify.models", "from apps.feed.models import Post",
                    "from ...feed.services import text", "x = 'apps.feed.services.posts'",
                    "import importlib\nimportlib.import_module('apps.feed.tasks')"),
                   ('"""apps.feed.models в докстринге"""\nimport os', "from apps.org.services import structure",
                    "from apps.notify.services import dispatch", "from apps.core.models import User",
                    "from ..models import Chat"))
    assert _scan("apps", "messenger", bad=bad, with_strings=False) == []

    def bad_org(name):
        return _under(name, "apps.org") and not _under(name, ORG_STRUCTURE)

    _check_scanner(bad_org, ["apps", "messenger", "services"],
                   ("from apps.org.models import Unit", "from apps.org import extensions", "import apps.org.views",
                    "from apps.org.services import refs", "from ...org.stand import stand_reset"),
                   ("from apps.org.services import structure", "from apps.org.services.structure import unit_refs",
                    "from ...org.services import structure"), with_strings=False)
    assert _scan("apps", "messenger", bad=bad_org, with_strings=False) == []
    assert _imported_anywhere(ORG_STRUCTURE), "`messenger` не использует `apps.org.services.structure`"

    def bad_notify(name):
        return _under(name, "apps.notify") and not (_under(name, DISPATCH) or _under(name, LIVE)
                                                          or _under(name, NOTIFY_PAGES))

    _check_scanner(bad_notify, ["apps", "messenger", "services"],
                   ("from apps.notify.services import kinds", "import apps.notify.models", "from apps.notify import tasks",
                    "from ...notify.services.delivery import external_text", "from apps.notify.services import prefs"),
                   ("from apps.notify.services import dispatch", "from apps.notify.services import live",
                    "from apps.notify.services.dispatch import create", "from apps.notify.services.live import group",
                    "from apps.core.extensions import NotificationKind"), with_strings=False)
    assert _scan("apps", "messenger", bad=bad_notify, with_strings=False) == []
    assert _imported_anywhere(DISPATCH), "`messenger` не использует `apps.notify.services.dispatch`"
    assert _imported_anywhere(LIVE), "`messenger` не использует `apps.notify.services.live`"
    allowed = {"dispatch": {"create"}, "live": {"group"}}
    for path, text in _sources("apps", "messenger").items():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "apps.notify.services":
                for alias in node.names:
                    if alias.name not in allowed:
                        continue
                    name = alias.asname or alias.name
                    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                            and isinstance(n.value, ast.Name) and n.value.id == name}
                    assert used <= allowed[alias.name], \
                        f"{path.name}: из {alias.name} используется {sorted(used - allowed[alias.name])}"
            if isinstance(node, ast.ImportFrom) and node.module in (DISPATCH, LIVE):
                wanted = "create" if node.module == DISPATCH else "group"
                assert {alias.name for alias in node.names} <= {wanted}, \
                    f"{path.name}: из {node.module} импортируется {[alias.name for alias in node.names]}"

    sources = _sources("apps", "messenger")
    for app in ("org", "notify"):
        assert _imported_anywhere(f"apps.{app}"), f"`messenger` не импортирует apps.{app}"
        guard = re.compile(r"is_installed\(\s*[\"']apps\." + app + r"[\"']\s*\)")
        assert any(guard.search(text) for text in sources.values()), \
            f'нигде в `apps/messenger` нет проверки `apps.is_installed("apps.{app}")`'

    models = {m.__name__: m for m in apps.get_app_config("messenger").get_models()}
    assert set(MESSENGER_MODELS) <= set(models), f"в приложении нет моделей: {sorted(set(MESSENGER_MODELS) - set(models))}"
    seen = 0
    for name, chat_model in models.items():
        for field in chat_model._meta.get_fields():
            if field.is_relation and not field.auto_created:
                seen += 1
                label = field.related_model._meta.app_label
                assert label in ("core", "messenger"), f"{name}.{field.name} ведёт в приложение {label}"
    assert seen > 0, "у моделей `messenger` нет ни одной связи"
    unit_id = models["Chat"]._meta.get_field("unit_id")
    assert isinstance(unit_id, PositiveIntegerField) and not unit_id.is_relation and unit_id.null


def test_org_and_notify_import_no_messenger():
    """FR-650, FR-667: ни один файл `apps/org/**` и `apps/notify/**` не импортирует `apps.messenger`; шов проходит по
    публичным средствам — `org` читает точку `unit_form_parts` (`registered("unit_form_parts")`), `notify` спрашивает
    `apps.is_installed("apps.messenger")` для признака `bell_link`; точка `top_bar_items` остаётся за `notify`."""
    from apps.core import extensions

    def bad(name):
        return _under(name, APP)

    _check_scanner(bad, ["apps", "org", "views"],
                   ("from apps.messenger.services import department", "import apps.messenger", "from apps import messenger",
                    "from ...messenger import tasks",
                    "import importlib\nimportlib.import_module('apps.messenger.notify_kinds')"),
                   ('"""apps.messenger в докстринге"""\n# apps.messenger в комментарии\nimport os',
                    "from apps.core import extensions", "logger = logging.getLogger(\"apps.messenger.unit_form\")"),
                   with_strings=False)
    offenders = _scan("apps", "org", bad=bad, with_strings=False) + _scan("apps", "notify", bad=bad, with_strings=False)
    assert offenders == [], f"org или notify знает о messenger: {offenders}"
    assert any(re.search(r"registered\(\s*[\"']unit_form_parts[\"']\s*\)", text)
               for text in _sources("apps", "org").values()), \
        "`org` не читает точку `unit_form_parts` — поля формы узла приходят не из точки"
    assert any(re.search(r"is_installed\(\s*[\"']apps\.messenger[\"']\s*\)", text)
               for text in _sources("apps", "notify").values()), \
        'нигде в `apps/notify` нет проверки `apps.is_installed("apps.messenger")` для адреса колокольчика'
    items = [(f.__module__, f.__name__) for f in extensions.registered("top_bar_items")]
    assert ("apps.notify.extensions", "top_bar_items") in items, "колокольчик в верхней панели регистрирует не notify"
    assert [module for module, _ in items if module.startswith(APP)] == [], "мессенджер занял точку top_bar_items"


# --- FR-643, FR-667: записи точек, порядок register_all (CONTRACT-008, 3.4) --------------------------------------

def test_messenger_registers_points_and_no_top_bar_items(monkeypatch):
    """FR-643, FR-667: `MessengerConfig.ready()` зовёт `register_all()`; регистрации — ровно восемь точек плана в
    порядке `menu_items`, `card_sections`, `notification_kinds`, `search_providers`, `file_purposes`, `audit_labels`,
    `unit_form_parts`, `stand_reset` (решение К8), `stand_reset` — последняя запись точки; меню — два пункта из
    `MENU_008` с баджем и `live_badge="messenger"`, карточка — раздел `profile` порядка 70 без строки для себя и
    уволенного, два вида `messenger.*`, группа поиска «Мессенджер» порядка 61, назначение файлов `messenger`, словарь
    подписей журнала, поле `messenger_chat` порядка 10; `top_bar_items` модуль не регистрирует и не читает."""
    from django.apps import apps as registry

    from apps.core import extensions

    config = registry.get_app_config("messenger")
    assert (config.label, config.verbose_name) == ("messenger", "Мессенджер")

    for point, module, name in REGISTRATIONS:
        funcs = _own(point)
        assert [(f.__module__, f.__name__) for f in funcs] == [(module, name)], f"точка {point}: {funcs}"

    main, settings_item = _own("menu_items")[0]()
    person = support.make_employee(full_name="Иванов Иван Иванович")
    assert [(item["url"], item["title"], item["order"], item["icon"], tuple(item["permissions"]))
            for item in (main, settings_item)] == [
                (sm.MENU_008["/messenger/"]["url"], sm.MENU_008["/messenger/"]["title"],
                 sm.MENU_008["/messenger/"]["order"], sm.MENU_008["/messenger/"]["icon"], ()),
                (sm.MENU_008["/settings/messenger/"]["url"], sm.MENU_008["/settings/messenger/"]["title"],
                 sm.MENU_008["/settings/messenger/"]["order"], sm.MENU_008["/settings/messenger/"]["icon"],
                 ("settings.portal",))]
    assert main["live_badge"] == "messenger" and main["visible"](person)
    assert isinstance(main["badge"](person), int) and "live_badge" not in settings_item

    dismissed = support.make_employee(state="dismissed", full_name="Петров Пётр Петрович")
    sections = _own("card_sections")[0]
    assert [(s.key, s.tab, s.order, s.template) for s in sections(person, support.make_employee())] == [
        ("messenger", "profile", 70, "messenger/_card_write.html")]
    assert sections(person, person) == [], "кнопка «Написать» показана в своей карточке"
    assert sections(person, dismissed) == [], "кнопка «Написать» показана у уволенного"

    kinds = _own("notification_kinds")[0]()
    assert [(k.code, k.title, k.module, k.order) for k in kinds] == [
        (row[0], row[1], row[2], row[3]) for row in sm.MESSENGER_KINDS]

    providers = _own("search_providers")[0]()
    assert [(p.key, p.title, p.order) for p in providers] == [("messenger", "Мессенджер", 61)]
    assert providers[0].available(person), "группа «Мессенджер» доступна не каждому вошедшему"

    purposes = _own("file_purposes")[0]()
    assert [p.purpose for p in purposes] == ["messenger"]
    assert all(callable(getattr(purposes[0], name)) for name in ("still_waiting", "clean", "found"))

    labels = _own("audit_labels")[0]()
    assert {"actions", "fields", "object_types", "values"} <= set(labels)
    assert set(sm.AUDIT_CODES) <= set(labels["actions"]), "в подписях журнала нет всех шести кодов плана"

    parts = _own("unit_form_parts")[0]()
    assert [(p.key, p.order) for p in parts] == [("messenger_chat", 10)]
    assert dataclasses.is_dataclass(parts[0]) and callable(parts[0].render) and callable(parts[0].on_saved)
    assert extensions.registered("unit_form_parts")[-1] is parts[0], "поле формы узла не последнее в точке"

    stand = _own("stand_reset")
    assert extensions.registered("stand_reset")[-3] is stand[0], "stand_reset мессенджера не третья с конца запись точки"
    assert (stand[0].__module__, stand[0].__name__) == ("apps.messenger.stand", "stand_reset")

    for point in UNUSED_POINTS:
        assert _own(point) == [], f"`messenger` зарегистрировал функцию в точке {point}"
    for path, text in _sources("apps", "messenger").items():
        assert not re.search(r"(register|registered)\(\s*[\"']top_bar_items[\"']", text), \
            f"{path.name}: мессенджер трогает точку top_bar_items"

    # порядок вызовов `register_all()`: регистрации снимаются, повторный вызов возвращает их в порядке плана
    expected = [point for point, _, _ in REGISTRATIONS]
    saved = {point: list(funcs) for point, funcs in extensions._registry.items()}
    for funcs in extensions._registry.values():
        funcs[:] = [func for func in funcs if not _is_messenger(func)]
    recorded = []
    real = extensions.register

    def spy(point, func):
        recorded.append(point)
        real(point, func)

    try:
        monkeypatch.setattr(extensions, "register", spy)
        messenger_extensions = importlib.import_module("apps.messenger.extensions")
        if hasattr(messenger_extensions, "register"):
            monkeypatch.setattr(messenger_extensions, "register", spy, raising=False)
        messenger_extensions.register_all()
        assert recorded == expected, f"порядок регистраций: {recorded}"
        for point, module, name in REGISTRATIONS:
            assert [(f.__module__, f.__name__) for f in _own(point)] == [(module, name)], \
                f"повторный register_all не вернул регистрацию точки {point}"
    finally:
        for point, funcs in saved.items():
            extensions._registry[point][:] = funcs


# --- FR-643, FR-645, FR-649, FR-667: портал без мессенджера (CONTRACT-008, 4.4) ---------------------------------

def test_without_messenger_menu_search_catalog_card_and_unit_form_have_no_trace():
    """FR-643, FR-645, FR-649, FR-667: пока регистрации `messenger` на месте, в меню два его пункта, колокольчик —
    ссылка на `/messenger/notifications/`, `/notifications/` отвечает 302, в поиске есть группа «Мессенджер», в
    каталоге два вида, в карточке коллеги — кнопка «Написать», в форме узла — поле `messenger_chat`. Без регистраций
    (`support_messenger.without_messenger`) меню и страницы прежние: пунктов и следов мессенджера нет, каталог без его
    видов, `/notifications/` — прежняя страница, колокольчик — прежняя кнопка, подписок шины нет; в разметке страниц
    нет `style=` и обработчиков `on…=` (CONTRACT-008, «Правила для всех тестов среза», 12)."""
    from apps.core import events, extensions
    from apps.core.services import permissions
    from apps.notify.services import kinds

    admin = support.make_admin()
    client = support.logged_in(admin)
    person = support.make_employee(full_name="Смирнова Анна Павловна")
    unit_obj = sm.unit("Отдел границ")

    titles = [item["title"] for item in permissions.menu_for(admin)]
    assert titles[:2] == ["Лента", "Мессенджер"], f"«Мессенджер» не второй пункт меню: {titles[:2]}"
    assert set(MENU_TITLES) <= set(titles)
    home = _html(client, "/")
    assert 'href="/messenger/"' in home and "menu-badge-messenger" in home
    assert "data-bell-link" in home and 'href="/messenger/notifications/"' in home
    assert "data-messenger-card-write" in _html(client, f"/staff/{person.pk}/"), "в карточке коллеги нет кнопки"
    assert "data-messenger-card-write" not in _html(client, "/me/"), "кнопка «Написать» видна в своей карточке"
    form = _html(client, f"/structure/{unit_obj.pk}/edit/")
    assert "data-messenger-unit-field" in form and 'name="messenger_chat"' in form, "в форме узла нет поля чата"
    redirected = client.get("/notifications/")
    assert redirected.status_code == 302 and redirected["Location"].startswith("/messenger/notifications/"), \
        "с мессенджером `/notifications/` не ведёт на вкладку «Уведомления»"
    assert set(sm.MESSENGER_CODES) <= {kind.code for kind in kinds.catalog()}, "в каталоге нет видов мессенджера"
    assert [handler for handler in events.subscribers("unit.deleted") if _is_messenger(handler)], \
        "нет подписки мессенджера на unit.deleted"

    full_menu = permissions.menu_for(admin)
    full_catalog = {kind.code for kind in kinds.catalog()}
    assert "messenger" in [provider.key for func in extensions.registered("search_providers")
                           for provider in func()], "при включённом модуле нет поставщика поиска «Мессенджер»"
    pages = ("/", f"/search/?q={WORD}", "/me/", f"/staff/{person.pk}/", f"/structure/{unit_obj.pk}/edit/")
    with sm.without_messenger():
        menu = permissions.menu_for(admin)
        rendered = {path: client.get(path) for path in pages}
        notices = client.get("/notifications/")
        kinds.check()
        rest = kinds.catalog()
        providers = [provider.key for func in extensions.registered("search_providers") for provider in func()]
        handlers = [handler for handler in events.subscribers("unit.deleted") if _is_messenger(handler)]

    assert [item for item in menu if item["title"] in MENU_TITLES or item["url"] in MENU_URLS] == []
    assert [item for item in full_menu if item["url"] not in MENU_URLS] == menu, "прочие пункты меню изменились"
    for path, response in rendered.items():
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        html = response.content.decode()
        assert "/messenger/" not in html, f"{path}: следы мессенджера в разметке"
        assert "menu-badge-messenger" not in html and "data-messenger" not in html, f"{path}: зацепки мессенджера"
        assert "data-bell-link" not in html, f"{path}: колокольчик остался ссылкой на мессенджер"
        assert not STYLE_ATTR.search(html) and not EVENT_ATTR.search(html), f"{path}: style= или on…= в разметке"
    assert notices.status_code == 200, "без мессенджера `/notifications/` не прежняя страница"
    notices_html = notices.content.decode()
    assert "data-bell-toggle" in notices_html and "data-bell-link" not in notices_html, "колокольчик не прежняя кнопка"
    assert "messenger" not in providers, "без мессенджера остался его поставщик поиска"
    assert [kind for kind in rest if kind.code.startswith("messenger.") or kind.module == "Мессенджер"] == []
    assert {kind.code for kind in rest} == full_catalog - set(sm.MESSENGER_CODES)
    assert len(rest) == len(full_catalog) - 2, "без мессенджера каталог изменился не на два вида"
    assert handlers == [], "без мессенджера осталась подписка на unit.deleted"
    assert _menu_links(_html(client, "/"))[0] == ("/", "Лента"), "первым пунктом перестала быть «Лента»"


# --- FR-661: маршрут соединения без приложения (CONTRACT-008, 1.2) ----------------------------------------------

def test_asgi_without_messenger_has_no_ws_messenger():
    """FR-661: `config.asgi.websocket_urlpatterns` — список маршрутов `notify`, затем `feed`, затем (при установленном
    приложении) список `messenger.routing.websocket_urlpatterns`; с выключенным приложением (`without_messenger`)
    `ws/messenger/` не отвечает, `ws/notify/` остаётся, `application` на месте; после блока маршруты возвращаются."""
    from apps.feed import routing as feed_routing
    from apps.messenger import routing as messenger_routing
    from apps.notify import routing as notify_routing

    def resolves(module, route: str) -> bool:
        return any(pattern.pattern.match(route) is not None for pattern in module.websocket_urlpatterns)

    base = list(notify_routing.websocket_urlpatterns) + list(feed_routing.websocket_urlpatterns)
    with_messenger = base + list(messenger_routing.websocket_urlpatterns)
    asgi_source = (support.BACKEND_DIR / "config" / "asgi.py").read_text(encoding="utf-8")
    assert re.search(r"is_installed\(\s*[\"']apps\.messenger[\"']\s*\)", asgi_source), \
        'config/asgi.py подключает мессенджер не под apps.is_installed("apps.messenger")'
    asgi = importlib.import_module("config.asgi")
    assert asgi.websocket_urlpatterns == with_messenger, "asgi собрал не список notify + feed + messenger"
    assert resolves(asgi, "ws/notify/"), "нет маршрута ws/notify/"
    with sm.without_messenger() as module:
        assert module.websocket_urlpatterns == base, "без приложения в asgi остались маршруты мессенджера"
        assert not resolves(module, "ws/messenger/"), "маршрут ws/messenger/ остался без приложения"
        assert resolves(module, "ws/notify/"), "без приложения пропал маршрут ws/notify/"
        assert hasattr(module, "application")
    asgi = importlib.import_module("config.asgi")
    assert asgi.websocket_urlpatterns == with_messenger, "после блока маршруты мессенджера не вернулись"
    assert resolves(asgi, "ws/notify/")


# --- FR-649: точка формы узла и её место (CONTRACT-008, 1.4, 3.1) ----------------------------------------------

def test_points_are_19_and_unit_form_parts_last():
    """FR-649: `POINTS` ядра — ровно девятнадцать имён: прежние восемнадцать в прежнем порядке и `unit_form_parts`
    девятнадцатой, в конце кортежа; `_registry` содержит ключ на каждое имя; `UnitFormPart` — датакласс с полями
    `key`, `order`, `render`, `on_saved`; неизвестная точка отказывает `ValueError`."""
    from apps.core import extensions

    assert tuple(extensions.POINTS) == POINTS_19
    assert len(extensions.POINTS) == len(POINTS_19)
    assert extensions.POINTS[-1] == "ticket_task_list" and extensions.POINTS.index("unit_form_parts") == 18
    assert tuple(extensions.POINTS[:18]) == POINTS_18, "прежние точки изменили порядок"
    assert set(extensions._registry) == set(POINTS_19)
    assert dataclasses.is_dataclass(extensions.UnitFormPart)
    assert [field.name for field in dataclasses.fields(extensions.UnitFormPart)] == ["key", "order", "render", "on_saved"]
    sample = extensions.UnitFormPart(key="проба", order=5, render=lambda request, unit: "",
                                     on_saved=lambda unit, post, actor, ip=None: None)
    assert (sample.key, sample.order, sample.render(None, None), sample.on_saved(None, {}, None)) == ("проба", 5, "", None)
    with pytest.raises(ValueError):
        extensions.register("no_such_point", lambda: [])
    with pytest.raises(ValueError):
        extensions.registered("no_such_point")


# --- FR-662: назначения файлов (CONTRACT-008, 1.4, 2.1) --------------------------------------------------------

def test_purposes_are_8_and_instruction_last():
    """FR-662, FR-693: у `StoredFile.Purpose` восемь значений (`support_messenger.PURPOSES_008`), `instruction` — последнее,
    с подписью «вложение задачи»; `messenger` («вложение сообщения чата») на прежнем месте, `max_length` (16) не
    меняется (T-9011, CONTRACT-009 1.4)."""
    stored = support.model("core.StoredFile")
    purpose = stored.Purpose

    assert tuple(purpose.values) == sm.PURPOSES_008
    assert len(purpose.values) == 8 and purpose.values[-1] == "instruction"
    assert purpose.MESSENGER == "messenger" and purpose.MESSENGER.label == "вложение сообщения чата"
    assert purpose.TASK == "task" and purpose.TASK.label == "вложение задачи"
    assert purpose.INSTRUCTION == "instruction" and purpose.INSTRUCTION.label == "вложение поручения"
    assert tuple(purpose.labels) == ("фото", "вложение", "файл статьи", "файл записи списка", "вложение ленты",
                                    "вложение сообщения чата", "вложение задачи", "вложение поручения")
    field = stored._meta.get_field("purpose")
    assert field.max_length == 16, "длина поля назначения изменилась"
    assert dict(field.choices)["messenger"] == "вложение сообщения чата"