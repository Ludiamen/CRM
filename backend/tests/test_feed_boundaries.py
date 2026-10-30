"""T-7136: границы модуля «Лента» (FR-641, FR-601). Сценарии спеки — «Модуль выключен», «Главная», «Сквозной поиск».

`feed` подключается к ядру и прежним модулям только точками расширения, шиной и публичными службами (CONTRACT-007, 3.3,
3.4, 4.2, 4.3, 2.2); без регистраций `feed` (`support_feed.without_feed`) главная, меню, поиск, каталог уведомлений и
прочие страницы работают как после среза 006. Охрана `is_installed` проверяется мягко, по образцу `lists` (решение 55 задач
среза 006): строка `apps.is_installed("apps.<имя>")` есть где-то в пакете `apps/feed` для каждого из импортируемых `org`,
`notify`. Имена кода среза импортируются внутри тестов. Маршруты `asgi` без `feed` — через
`support_feed.reload_asgi_without_feed()` (решение 52 задач)."""
import ast
import contextlib
import re

import pytest

from tests import support
from tests import support_feed as feed
from tests.support import model

pytestmark = pytest.mark.django_db

POINTS_17 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
             "notification_kinds", "top_bar_items", "search_providers", "ticket_card_parts")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
STRUCTURE = "apps.org.services.structure"
DISPATCH = "apps.notify.services.dispatch"
LIVE = "apps.notify.services.live"
FEED_MODELS = ("Post", "Recipient", "FeedComment", "PostLike", "CommentLike", "ReadMark", "EventAnswer", "Shown",
               "FeedFile", "FeedSettings")
PREVIOUS_APPS = ("core", "org", "notify", "knowledge", "servicedesk", "lists", "search")
BANNED_APPS = ("servicedesk", "knowledge", "lists", "search")
FEED_POINTS = {"menu_items", "home_body", "search_providers", "notification_kinds", "file_purposes", "audit_labels",
               "stand_reset"}
WORD = "кофемашина"
NOTICE_KEY = "boundary-probe-notice"
NOTICE_TEXT = "Проба границ: напоминание модуля"


# --- разбор импортов (как в test_lists_boundaries.py) ----------------------------------------------------------------

def _targets(source: str, package: list[str], *, with_strings: bool = True) -> set[str]:
    """Абсолютные имена, от которых зависит файл (`ast`): `import a.b`; `from a.b import c` — имя `a.b.c`; относительные
    импорты; `import_module("…")`/`__import__("…")`; при `with_strings` — ещё строка-путь модуля целиком вне докстрингов."""
    tree = ast.parse(source)
    docstrings = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
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


def _scan(*parts: str, bad, with_strings: bool = True) -> list[str]:
    root = support.BACKEND_DIR.joinpath(*parts)
    files = sorted(root.rglob("*.py"))
    assert files, f"нет исходников в {root}"
    offenders = []
    for path in files:
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        hits = sorted(n for n in _targets(path.read_text(encoding="utf-8"), list(rel.parts[:-1]),
                                          with_strings=with_strings) if bad(n))
        if hits:
            offenders.append(f"{path.relative_to(support.BACKEND_DIR)}: {hits}")
    return offenders


def _check_scanner(bad, package: list[str], found: tuple[str, ...], clean: tuple[str, ...], *, with_strings=True) -> None:
    """Сам разбор находит нарушения на образцах и не срабатывает на чистых (иначе пустой список ничего не доказывает)."""
    for sample in found:
        assert any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), f"разбор не нашёл: {sample}"
    for sample in clean:
        assert not any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), f"ложное срабатывание: {sample}"


def _feed_sources() -> dict:
    root = support.BACKEND_DIR / "apps" / "feed"
    paths = sorted(root.rglob("*.py"))
    assert paths, "нет исходников в apps/feed"
    return {p: p.read_text(encoding="utf-8") for p in paths}


def _imported_anywhere(root: str) -> bool:
    """Есть ли в `apps/feed/**` импорт (без строк-путей) чего-либо из `root`."""
    for path, text in _feed_sources().items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        if any(_under(n, root) for n in _targets(text, list(rel.parts[:-1]), with_strings=False)):
            return True
    return False


def _own(point: str) -> list:
    """Функции точки, определённые в модулях `apps.feed.*`."""
    from apps.core import extensions

    return [f for f in extensions.registered(point) if getattr(f, "__module__", "").startswith("apps.feed")]


@contextlib.contextmanager
def _registered(point: str, func):
    """Временная регистрация функции в точке ядра; снимается после блока (регистрации вне `without_feed` — на нас)."""
    from apps.core import extensions

    extensions.register(point, func)
    try:
        yield
    finally:
        registry = extensions._registry[point]
        if func in registry:
            registry.remove(func)


def _notice(user):
    return [{"key": NOTICE_KEY, "level": "warning", "text": NOTICE_TEXT}]


def _menu_links(html: str) -> list[tuple[str, str]]:
    """Пункты `nav#main-menu` по порядку: (адрес, подпись)."""
    nav = re.search(r'<nav id="main-menu".*?</nav>', html, re.S)
    assert nav, "в оболочке нет nav#main-menu"
    return [(href, re.sub(r"\s+", " ", label).strip()) for href, label in re.findall(
        r'<a class="menu-item[^"]*" href="([^"]*)"[^>]*>.*?<span class="menu-label">(.*?)</span>', nav.group(0), re.S)]


# --- FR-641: границы импортов (план «Модуль и выключение»; CONTRACT-007, 4.3) --------------------------------------

def test_core_org_notify_knowledge_servicedesk_lists_search_do_not_import_feed():
    """FR-641: ни один файл `apps/core/**`, `org`, `notify`, `knowledge`, `servicedesk`, `lists`, `search` не
    импортирует `apps.feed` (ни `import`, ни `import_module`, ни строка-путь вне докстрингов); сам разбор находит
    нарушения на образцах."""

    def bad(name):
        return _under(name, "apps.feed")

    _check_scanner(bad, ["apps", "core", "services"],
                   ("from apps.feed.services import posts", "import apps.feed", "from apps import feed",
                    "from ...feed import tasks", "import importlib\nimportlib.import_module('apps.feed.tasks')",
                    "x = 'apps.feed.extensions'"),
                   ('"""apps.feed в докстринге"""\n# apps.feed в комментарии\nimport os',
                    "from apps.core import extensions", "event = 'feed.post_all'"))
    offenders = []
    for app in PREVIOUS_APPS:
        offenders += _scan("apps", app, bad=bad)
    assert offenders == [], f"прежний модуль знает о feed: {offenders}"


def test_feed_does_not_import_models_of_org_notify_or_other_apps_and_imports_nothing_from_servicedesk_knowledge_lists_search():
    """FR-641: в `apps/feed/**` нет импорта моделей `org`, `notify`; нет никакого импорта из `servicedesk`, `knowledge`,
    `lists`, `search` (ни `import`, ни `import_module`, ни строка-путь); сам разбор находит нарушения на образцах;
    модели среза на месте (пустой пакет ничего не доказывает)."""
    from django.apps import apps

    def bad(name):
        return any(_under(name, f"apps.{app}.models") for app in ("org", "notify")) \
            or any(_under(name, f"apps.{app}") for app in BANNED_APPS)

    _check_scanner(bad, ["apps", "feed", "services"],
                   ("from apps.org.models import Unit", "import apps.notify.models", "from apps.org import models",
                    "from ...notify.models import Notification", "x = 'apps.org.models.Unit'",
                    "from apps.servicedesk.services import public", "from apps.knowledge.services import render",
                    "from apps.lists.services import access", "import apps.search.parse",
                    "import importlib\nimportlib.import_module('apps.lists.tasks')"),
                   ('"""apps.org.models в докстринге"""\nimport os', "from apps.org.services import structure",
                    "from apps.notify.services import dispatch", "from apps.core.models import User",
                    "from ..models import Post"))
    assert _scan("apps", "feed", bad=bad) == []
    names = {m.__name__ for m in apps.get_app_config("feed").get_models()}
    assert set(FEED_MODELS) <= names, f"в приложении нет моделей: {sorted(set(FEED_MODELS) - names)}"


def test_feed_imports_org_only_through_services_structure():
    """FR-641: из `apps.org` пакет `feed` импортирует только `apps.org.services.structure` (`unit_chain_ids`,
    `subtree_member_ids`, `unit_chains`, `all_units`, `unit_refs`); такой импорт есть."""

    def bad(name):
        return _under(name, "apps.org") and not _under(name, STRUCTURE)

    _check_scanner(bad, ["apps", "feed", "services"],
                   ("from apps.org.models import Unit", "from apps.org import extensions", "import apps.org.views",
                    "from ...org.stand import stand_reset", "from apps.org.services import refs",
                    "from apps.org.services.refs import UnitRef"),
                   ("from apps.org.services import structure", "from apps.org.services.structure import unit_refs",
                    "from ...org.services import structure"), with_strings=False)
    assert _scan("apps", "feed", bad=bad, with_strings=False) == []
    assert _imported_anywhere(STRUCTURE), "`feed` не использует `apps.org.services.structure`"


def test_feed_imports_notify_only_through_dispatch_and_live_group():
    """FR-641: из `apps.notify` пакет `feed` импортирует только `apps.notify.services.dispatch` (зовёт `create`) и
    `apps.notify.services.live` (зовёт `group`); такие импорты есть; у файла, который берёт `dispatch` или `live`
    из `apps.notify.services`, обращения к ним — только `dispatch.create` и `live.group`."""

    def bad(name):
        return _under(name, "apps.notify") and not (_under(name, DISPATCH) or _under(name, LIVE))

    _check_scanner(bad, ["apps", "feed", "services"],
                   ("from apps.notify.services import kinds", "import apps.notify.models", "from apps.notify import tasks",
                    "from ...notify.services.delivery import external_text", "from apps.notify.services import prefs"),
                   ("from apps.notify.services import dispatch", "from apps.notify.services import live",
                    "from apps.notify.services.dispatch import create", "from apps.notify.services.live import group",
                    "from apps.core.extensions import NotificationKind"), with_strings=False)
    assert _scan("apps", "feed", bad=bad, with_strings=False) == []
    assert _imported_anywhere(DISPATCH), "`feed` не использует `apps.notify.services.dispatch`"
    assert _imported_anywhere(LIVE), "`feed` не использует `apps.notify.services.live`"
    allowed = {"dispatch": {"create"}, "live": {"group"}}
    for path, text in _feed_sources().items():
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
                assert {a.name for a in node.names} <= {wanted}, \
                    f"{path.name}: из {node.module} импортируется {[a.name for a in node.names]}"


def test_feed_has_is_installed_guard_for_each_org_and_notify_import():
    """FR-641 (мягкая проверка, как у `lists`): для каждого из `org`, `notify`, который `feed` импортирует, в пакете
    `apps/feed` есть строка `apps.is_installed("apps.<имя>")`. Оба импортируются."""
    sources = _feed_sources()
    for app in ("org", "notify"):
        assert _imported_anywhere(f"apps.{app}"), f"`feed` не импортирует apps.{app}"
        guard = re.compile(r"is_installed\(\s*[\"']apps\." + app + r"[\"']\s*\)")
        assert any(guard.search(text) for text in sources.values()), \
            f'нигде в `apps/feed` нет проверки `apps.is_installed("apps.{app}")`'


# --- FR-641: точки расширения (CONTRACT-007, 3.1, 3.3) -------------------------------------------------------------

def test_points_tuple_has_eighteen_names_and_feed_uses_home_body_last():
    """FR-641: `POINTS` ядра — ровно восемнадцать имён: прежние семнадцать в прежнем порядке и `home_body` последней;
    `_registry` содержит ключ на каждое имя; точку `home_body` занимает единственная функция `feed`
    (`apps.feed.views.home.body`); `feed` использует новую точку одну."""
    from apps.core import extensions

    assert tuple(extensions.POINTS) == POINTS_17 + feed.POINTS_007
    assert len(extensions.POINTS) == 18 and extensions.POINTS[-1] == "home_body"
    assert set(extensions._registry) == set(extensions.POINTS)
    own = _own("home_body")
    assert [(f.__module__, f.__name__) for f in own] == [("apps.feed.views.home", "body")]
    assert extensions.registered("home_body")[:1] == own, "функция feed не первая в точке home_body"


def test_feed_registers_menu_items_feed_at_root_order_0_with_live_badge_and_feed_settings_order_63():
    """FR-641, FR-601: `feed` регистрирует одну функцию `menu_items` (`apps.feed.extensions.menu_items`): «Лента» —
    `url="/"`, `order=0`, `icon="icons/feed.html"`, без прав, видна любому вошедшему, `badge` — число непрочитанных,
    `live_badge="feed"`; «Настройки ленты» — `/settings/feed/`, `order=63`, `icons/gear.html`, право `settings.portal`,
    без `live_badge`."""
    from apps.feed.services import unread

    funcs = _own("menu_items")
    assert [(f.__module__, f.__name__) for f in funcs] == [("apps.feed.extensions", "menu_items")]
    items = funcs[0]()
    assert len(items) == 2
    main, settings_item = items
    assert (main["url"], main["title"], main["order"], main["icon"]) == (
        feed.MENU_FEED["url"], feed.MENU_FEED["title"], feed.MENU_FEED["order"], feed.MENU_FEED["icon"])
    assert tuple(main["permissions"]) == () and main["live_badge"] == "feed"
    reader, author = support.make_employee(), support.make_employee()
    assert main["visible"](reader), "пункт «Лента» виден не каждому вошедшему"
    feed.make_post(author, to=("all",))
    assert main["badge"](reader) == unread.count(reader) == 1
    assert (settings_item["url"], settings_item["title"], settings_item["order"], settings_item["icon"]) == (
        feed.MENU_FEED_SETTINGS["url"], feed.MENU_FEED_SETTINGS["title"], feed.MENU_FEED_SETTINGS["order"],
        feed.MENU_FEED_SETTINGS["icon"])
    assert tuple(settings_item["permissions"]) == ("settings.portal",)
    assert "live_badge" not in settings_item


def test_feed_registers_home_body_and_search_provider_feed_order_60():
    """FR-641: `home_body` — `apps.feed.views.home.body`; `search_providers` — одна функция
    `apps.feed.services.search.search_providers` с одной группой: ключ `feed`, «Лента», порядок 60 (после «Списков» 50),
    доступна любому вошедшему."""
    from apps.core import extensions

    assert [(f.__module__, f.__name__) for f in _own("home_body")] == [("apps.feed.views.home", "body")]
    funcs = _own("search_providers")
    assert [(f.__module__, f.__name__) for f in funcs] == [("apps.feed.services.search", "search_providers")]
    found = funcs[0]()
    assert [(p.key, p.title, p.order) for p in found] == [feed.FEED_SEARCH]
    assert found[0].available(support.make_employee()), "группа «Лента» доступна не каждому"
    orders = {p.key: p.order for f in extensions.registered("search_providers") for p in f()}
    assert orders["lists"] == 50 and orders["feed"] == 60


def test_feed_registers_eight_notification_kinds_file_purpose_audit_labels_and_stand_reset():
    """FR-641: по одной функции `feed` в `notification_kinds` (восемь видов `feed.*`, модуль «Лента»), `file_purposes`
    (назначение `feed`), `audit_labels` (словарь с ключами `actions`, `fields`, `object_types`, `values`) и
    `stand_reset` (`apps.feed.stand.stand_reset`, последняя в точке); все регистрации `feed` — ровно семь точек из
    таблицы плана; прочих точек модуль не использует."""
    from apps.core import extensions

    expected = {
        "notification_kinds": ("apps.feed.notify_kinds", "notification_kinds"),
        "file_purposes": ("apps.feed.services.files", "file_purposes"),
        "audit_labels": ("apps.feed.audit_labels", "audit_labels"),
        "stand_reset": ("apps.feed.stand", "stand_reset"),
    }
    for point, (module, name) in expected.items():
        funcs = _own(point)
        assert [(f.__module__, f.__name__) for f in funcs] == [(module, name)], f"точка {point}: {funcs}"
    kinds = _own("notification_kinds")[0]()
    assert [k.code for k in kinds] == list(feed.FEED_CODES) and len(kinds) == 8
    assert {k.module for k in kinds} == {feed.FEED_MODULE}
    assert [p.purpose for p in _own("file_purposes")[0]()] == ["feed"]
    assert set(_own("audit_labels")[0]()) >= {"actions", "fields", "object_types", "values"}
    assert extensions.registered("stand_reset")[-1] is _own("stand_reset")[0], "stand_reset ленты не последний"
    used = {point for point in extensions.POINTS if _own(point)}
    assert used == FEED_POINTS, f"точки с регистрациями feed: {sorted(used)}"


def test_feed_does_not_register_home_notices():
    """FR-641: в точке `home_notices` функций `feed` нет — напоминания модулей лента читает функцией ядра
    `pages.collect_notices` (в исходниках `apps/feed/views/home.py` она вызывается, регистрации `home_notices` нет)."""
    assert _own("home_notices") == []
    path = support.BACKEND_DIR / "apps" / "feed" / "views" / "home.py"
    assert path.is_file(), "нет apps/feed/views/home.py"
    text = path.read_text(encoding="utf-8")
    assert "collect_notices" in text, "тело главной не зовёт pages.collect_notices"
    for source in _feed_sources().values():
        assert not re.search(r"register\(\s*[\"']home_notices[\"']", source), "feed регистрирует home_notices"


def test_feed_has_no_bus_subscriptions_and_publishes_only_object_viewed():
    """FR-641: `feed` не подписан на события шины (в `events._registry` нет обработчиков из `apps.feed`, в исходниках
    нет `subscribe`/`subscribe_all`) и публикует единственное событие `object.viewed` с `object_ref` и `user_id`;
    публикации есть (карточка записи)."""
    from apps.core import events

    own = {name: [h for h in handlers if getattr(h, "__module__", "").startswith("apps.feed")]
           for name, handlers in events._registry.items()}
    assert {name: found for name, found in own.items() if found} == {}, "у feed есть обработчики шины"
    publishes = []
    for path, text in _feed_sources().items():
        tree = ast.parse(text)
        # голое `publish(...)` считается шиной, только если имя импортировано из `apps.core.events`
        bare_bus = any(isinstance(n, ast.ImportFrom) and n.module == "apps.core.events"
                       and any(a.name == "publish" for a in n.names) for n in ast.walk(tree))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert name not in ("subscribe", "subscribe_all"), f"{path.name}: подписка шины ({name})"
            is_publish = (isinstance(func, ast.Attribute) and func.attr == "publish"
                          and isinstance(func.value, ast.Name) and func.value.id == "events") \
                or (bare_bus and isinstance(func, ast.Name) and func.id == "publish")
            if is_publish:
                assert node.args and isinstance(node.args[0], ast.Constant), f"{path.name}: имя события не литерал"
                publishes.append((node.args[0].value, {kw.arg for kw in node.keywords}))
    assert publishes, "`feed` не публикует object.viewed"
    assert all(item == ("object.viewed", {"object_ref", "user_id"}) for item in publishes), publishes


# --- FR-641: главная, меню, поиск, каталог, asgi, страницы без feed -----------------------------------------------

def test_home_without_feed_is_previous_home_with_module_notices():
    """FR-641: без регистраций `feed` точка `home_body` пуста, `/` рисует прежний `home.html` — приветствие,
    карточки разделов и блок напоминаний модулей (`data-home-notices`) — без ленты (`feed-live`, `data-post-id`);
    с регистрациями `feed` на `/` есть узел `#feed-live`."""
    user = support.make_employee()
    client = support.logged_in(user)
    with _registered("home_notices", _notice):
        with_feed = client.get("/")
        assert with_feed.status_code == 200 and 'id="feed-live"' in with_feed.content.decode(), \
            "при включённом модуле на главной нет #feed-live"
        with feed.without_feed():
            response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "home.html" in [t.name for t in response.templates], "главная — не прежний home.html"
    assert f"Здравствуйте, {user.full_name}!" in html
    assert "data-home-notices" in html and f'data-notice="{NOTICE_KEY}"' in html and NOTICE_TEXT in html
    assert "feed-live" not in html and "data-post-id" not in html


def test_menu_without_feed_has_no_feed_items_and_home_item_first():
    """FR-641: без регистраций `feed` в меню нет «Ленты» и «Настроек ленты» ни в `menu_for`, ни в разметке; первым
    стоит прежняя «Главная» (`/`); прочие пункты те же; с модулем первый пункт — «Лента» на `/`, «Главной» нет, у
    администратора на два пункта больше."""
    from apps.core.services import permissions

    admin = support.make_admin()
    client = support.logged_in(admin)
    full = permissions.menu_for(admin)
    with_html = client.get("/me/").content.decode()
    assert _menu_links(with_html)[0] == ("/", "Лента") and ("/", "Главная") not in _menu_links(with_html)
    assert [m["title"] for m in full if m["title"] in ("Лента", "Настройки ленты")] == ["Лента", "Настройки ленты"]
    with feed.without_feed():
        menu = permissions.menu_for(admin)
        html = client.get("/me/").content.decode()
    assert [m for m in menu if m["title"] in ("Лента", "Настройки ленты") or "live_badge" in m
            or m["url"] == "/settings/feed/"] == []
    assert len(menu) == len(full) - 2, "прочие пункты меню изменились"
    assert [m["url"] for m in full if m["url"] != "/settings/feed/" and m["title"] != "Лента"] == [m["url"] for m in menu]
    links = _menu_links(html)
    assert links[0] == ("/", "Главная"), f"первым пунктом не «Главная»: {links[0]}"
    assert "/settings/feed/" not in [href for href, _ in links] and "menu-badge-feed" not in html


def test_search_page_without_feed_renders_without_feed_group():
    """FR-641: без регистраций `feed` страница `/search/` рисуется (200) без группы «Лента»
    (`data-search-group="feed"`), записи ленты в выдаче нет; с модулем группа с записью есть."""
    from apps.core import extensions
    from apps.search import parse, services

    author, reader = support.make_employee(), feed.as_plain()
    post = feed.make_post(author, to=("all",), text=f"Купили {WORD} в переговорную")
    parsed = parse.parse(WORD)
    assert "feed" in [g.key for g in services.page(reader.user, parsed)], "при включённом модуле нет группы «Лента»"
    assert 'data-search-group="feed"' in reader.client.get(f"/search/?q={WORD}").content.decode()
    with feed.without_feed():
        assert "feed" not in [p.key for f in extensions.registered("search_providers") for p in f()]
        assert "feed" not in [g.key for g in services.page(reader.user, parsed)]
        response = reader.client.get(f"/search/?q={WORD}")
    assert response.status_code == 200 and 'data-search-group="feed"' not in response.content.decode()
    assert f"/feed/{post.pk}/" not in response.content.decode()


def test_notification_catalog_without_feed_has_no_feed_kinds():
    """FR-641: без регистраций `feed` каталог видов уведомлений не содержит видов `feed.*` и модуля «Лента», проверка
    каталога проходит, прочие виды те же; с модулем добавляются ровно восемь видов."""
    from apps.notify.services import kinds

    full = {kind.code: kind for kind in kinds.catalog()}
    assert set(feed.FEED_CODES) <= set(full), "при включённом модуле в каталоге нет видов ленты"
    with feed.without_feed():
        kinds.check()
        rest = kinds.catalog()
    assert [k.code for k in rest if k.code.startswith("feed.") or k.module == feed.FEED_MODULE] == []
    assert {k.code for k in rest} == set(full) - set(feed.FEED_CODES)
    assert len(full) - len(rest) == 8


def test_asgi_routes_without_feed_app_have_no_ws_feed_and_keep_ws_notify():
    """FR-641: с модулем в `config.asgi.websocket_urlpatterns` есть `ws/feed/` и `ws/notify/`; при выключенном
    приложении (`reload_asgi_without_feed`, решение 52 задач) — только `ws/notify/`, `application` на месте; после блока
    маршрут `ws/feed/` возвращается."""
    import importlib

    def resolves(module, route: str) -> bool:
        return any(p.pattern.match(route) is not None for p in module.websocket_urlpatterns)

    asgi = importlib.import_module("config.asgi")
    assert resolves(asgi, "ws/feed/") and resolves(asgi, "ws/notify/")
    with feed.reload_asgi_without_feed() as module:
        assert not resolves(module, "ws/feed/"), "маршрут ws/feed/ остался без приложения feed"
        assert resolves(module, "ws/notify/"), "пропал маршрут ws/notify/"
        assert hasattr(module, "application")
    asgi = importlib.import_module("config.asgi")
    assert resolves(asgi, "ws/feed/") and resolves(asgi, "ws/notify/"), "после блока маршруты не вернулись"


def test_other_modules_pages_render_without_feed():
    """FR-641: без регистраций `feed` страницы прежних модулей рисуются (200) без следов ленты в разметке: профиль,
    безопасность, списки, база знаний, заявки, структура, уведомления, поиск."""
    admin = support.make_admin()
    client = support.logged_in(admin)
    pages = ("/me/", "/me/security/", "/lists/", "/kb/", "/tickets/", "/structure/", "/notifications/",
             f"/search/?q={WORD}")
    with feed.without_feed():
        responses = [(path, client.get(path)) for path in pages]
    for path, response in responses:
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        html = response.content.decode()
        assert "menu-badge-feed" not in html and "feed-live" not in html and "/settings/feed/" not in html, \
            f"{path}: следы ленты в разметке"


# --- FR-641: связи моделей (CONTRACT-007, 2.2) ---------------------------------------------------------------------

def test_feed_models_have_no_foreign_keys_to_org_or_notify_and_recipient_unit_id_is_plain_integer():
    """FR-641: ни одно поле связи моделей `feed` не ведёт в приложения `org` и `notify` (подразделение — число
    `Recipient.unit_id`, `PositiveIntegerField(null=True)` без связи); связи только с `core` и `feed`."""
    from django.apps import apps
    from django.db.models import PositiveIntegerField

    models = {m.__name__: m for m in apps.get_app_config("feed").get_models()}
    assert set(FEED_MODELS) <= set(models), f"в приложении нет моделей: {sorted(set(FEED_MODELS) - set(models))}"
    seen = 0
    for name, feed_model in models.items():
        for field in feed_model._meta.get_fields():
            if field.is_relation and not field.auto_created:
                seen += 1
                label = field.related_model._meta.app_label
                assert label not in ("org", "notify"), f"{name}.{field.name} ведёт в приложение {label}"
                assert label in ("core", "feed"), f"{name}.{field.name} ведёт в приложение {label}"
    assert seen > 0, "у моделей `feed` нет ни одной связи"
    unit_id = model("feed.Recipient")._meta.get_field("unit_id")
    assert isinstance(unit_id, PositiveIntegerField) and not unit_id.is_relation and unit_id.null
