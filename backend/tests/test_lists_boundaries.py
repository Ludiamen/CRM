"""T-6126: границы модуля «Списки» (FR-543). Сценарии спеки — «Модуль выключен», «Карточка заявки», «Сквозной поиск»,
«Закреплённое».

`lists` подключается к ядру и прежним модулям только точками расширения, шиной и публичными службами (CONTRACT-006,
3.2, 3.3, 3.4, 4.5, 15); без регистраций `lists` (`support_lists.without_lists`) меню, поиск, карточки сотрудника и
заявки и каталог уведомлений работают как после среза 005. Охрана `is_installed` проверяется мягко, по образцу базы
знаний (решение 55 задач): строка `apps.is_installed("apps.<имя>")` есть где-то в пакете `apps/lists` для каждого из
импортируемых `servicedesk`, `notify`, `org`. Имена кода среза импортируются внутри тестов."""
import ast
import re

import pytest

from tests import support, support_lists
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

POINTS_15 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
             "notification_kinds", "top_bar_items")
POINTS_17 = POINTS_15 + ("search_providers", "ticket_card_parts")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
PUBLIC = "apps.servicedesk.services.public"
DISPATCH = "apps.notify.services.dispatch"
ORG_SERVICES = "apps.org.services"
LISTS_MODELS = ("List", "Field", "Choice", "Record", "UniqueValue", "Change", "Access", "UserView", "TicketLink",
                "ReminderSent", "ImportJob", "RecordFile")
FOREIGN_APPS = ("servicedesk", "org", "notify", "knowledge", "search")
WORD = "плоттер"


# --- разбор импортов (как в test_kb_boundaries.py) --------------------------------------------------------------

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


def _read(*parts: str) -> str:
    path = support.BACKEND_DIR.joinpath(*parts)
    assert path.is_file(), f"нет файла {path.relative_to(support.BACKEND_DIR)}"
    return path.read_text(encoding="utf-8")


def _lists_sources() -> dict:
    paths = sorted(support.BACKEND_DIR.joinpath("apps", "lists").rglob("*.py"))
    return {p: p.read_text(encoding="utf-8") for p in paths}


def _imported_anywhere(root: str) -> bool:
    """Есть ли в `apps/lists/**` импорт (без строк-путей) чего-либо из `root`."""
    for path, text in _lists_sources().items():
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        if any(_under(n, root) for n in _targets(text, list(rel.parts[:-1]), with_strings=False)):
            return True
    return False


# --- помощники данных ---------------------------------------------------------------------------------------

def _reader_in_queue(*codes: str):
    """Участник очереди (видит её заявки). Возвращает (пользователь, очередь)."""
    queue = sd.make_queue()
    user = support.make_with_permissions(*codes)
    org.make_member(user, queue.unit)
    return user, queue


def _card_html(user, ticket) -> str:
    response = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200, f"карточка #{ticket.number}: {response.status_code}"
    return response.content.decode()


def _own(point: str) -> list:
    """Функции точки, определённые в модулях `apps.lists.*`."""
    from apps.core import extensions

    return [f for f in extensions.registered(point) if getattr(f, "__module__", "").startswith("apps.lists")]


def _publishes(source: str) -> bool:
    """Есть ли в источнике вызов `events.publish(...)` или `publish(...)` шины ядра."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "publish" \
                    and isinstance(func.value, ast.Name) and func.value.id == "events":
                return True
            if isinstance(func, ast.Name) and func.id == "publish":
                return True
    return False


# --- FR-543: границы импортов (план «Модуль и выключение»; CONTRACT-006, 4.5) ------------------------------------

def test_lists_does_not_import_models_of_org_servicedesk_notify_knowledge_search():
    """FR-543: в `apps/lists/**` нет импорта моделей `org`, `servicedesk`, `notify`, `knowledge`, `search`; сам разбор
    находит нарушения на образцах; модели среза на месте (пустой пакет ничего не доказывает)."""
    from django.apps import apps

    def bad(name):
        return any(_under(name, f"apps.{app}.models") for app in FOREIGN_APPS)

    _check_scanner(bad, ["apps", "lists", "services"],
                   ("from apps.org.models import Unit", "import apps.notify.models", "from apps.servicedesk import models",
                    "from ...knowledge.models import Article", "x = 'apps.search.models.Thing'"),
                   ('"""apps.org.models в докстринге"""\nimport os', "from apps.org.services import structure",
                    "from apps.core.models import User", "from ..models import Record"))
    assert _scan("apps", "lists", bad=bad) == []
    names = {m.__name__ for m in apps.get_app_config("lists").get_models()}
    assert set(LISTS_MODELS) <= names, f"в приложении нет моделей: {sorted(set(LISTS_MODELS) - names)}"


def test_lists_imports_servicedesk_only_through_services_public():
    """FR-543: из `apps.servicedesk` пакет `lists` импортирует только `apps.servicedesk.services.public`; такой импорт
    есть (заявки в карточке записи берутся через `public`)."""

    def bad(name):
        return _under(name, "apps.servicedesk") and not _under(name, PUBLIC)

    _check_scanner(bad, ["apps", "lists", "services"],
                   ("from apps.servicedesk.services import tickets", "import apps.servicedesk.models",
                    "from apps.servicedesk import extensions", "from ...servicedesk.services.access import visible_tickets",
                    "import importlib\nimportlib.import_module('apps.servicedesk.views')"),
                   ("from apps.servicedesk.services import public", "from apps.servicedesk.services.public import briefs",
                    "from ...servicedesk.services.public import ticket_brief"), with_strings=False)
    assert _scan("apps", "lists", bad=bad, with_strings=False) == []
    assert _imported_anywhere(PUBLIC), "`lists` не использует `apps.servicedesk.services.public`"


def test_lists_imports_notify_only_through_services_dispatch():
    """FR-543: из `apps.notify` пакет `lists` импортирует только `apps.notify.services.dispatch` (`dispatch.create` —
    единственный вызов `notify`); такой импорт есть."""

    def bad(name):
        return _under(name, "apps.notify") and not _under(name, DISPATCH)

    _check_scanner(bad, ["apps", "lists", "services"],
                   ("from apps.notify.services import kinds", "import apps.notify.models", "from apps.notify import tasks",
                    "from ...notify.services.delivery import external_text"),
                   ("from apps.notify.services import dispatch", "from apps.notify.services.dispatch import create",
                    "from apps.core.extensions import NotificationKind"), with_strings=False)
    assert _scan("apps", "lists", bad=bad, with_strings=False) == []
    assert _imported_anywhere(DISPATCH), "`lists` не использует `apps.notify.services.dispatch`"


def test_lists_imports_org_only_through_services():
    """FR-543: из `apps.org` пакет `lists` импортирует только `apps.org.services` (`structure`, `refs`); такой импорт есть."""

    def bad(name):
        return _under(name, "apps.org") and not _under(name, ORG_SERVICES)

    _check_scanner(bad, ["apps", "lists", "services"],
                   ("from apps.org.models import Unit", "from apps.org import extensions", "import apps.org.views",
                    "from ...org.stand import stand_reset"),
                   ("from apps.org.services import structure", "from apps.org.services.refs import UnitRef",
                    "from ...org.services import structure"), with_strings=False)
    assert _scan("apps", "lists", bad=bad, with_strings=False) == []
    assert _imported_anywhere(ORG_SERVICES), "`lists` не использует `apps.org.services`"


def test_lists_has_is_installed_guard_for_each_of_servicedesk_notify_org_it_imports():
    """FR-543 (решение 55 задач, мягкая проверка): для каждого из `servicedesk`, `notify`, `org`, который `lists`
    импортирует, в пакете `apps/lists` есть строка `apps.is_installed("apps.<имя>")`. Все три импортируются."""
    sources = _lists_sources()
    for app in ("servicedesk", "notify", "org"):
        assert _imported_anywhere(f"apps.{app}"), f"`lists` не импортирует apps.{app}"
        guard = re.compile(r"is_installed\(\s*[\"']apps\." + app + r"[\"']\s*\)")
        assert any(guard.search(text) for text in sources.values()), \
            f'нигде в `apps/lists` нет проверки `apps.is_installed("apps.{app}")`'


def test_core_org_servicedesk_notify_knowledge_search_do_not_import_lists():
    """FR-543: ни один файл `apps/core/**`, `org`, `servicedesk`, `notify`, `knowledge`, `search` не импортирует
    `apps.lists` (ни `import`, ни `import_module`, ни строка-путь вне докстрингов)."""

    def bad(name):
        return _under(name, "apps.lists")

    _check_scanner(bad, ["apps", "core", "services"],
                   ("from apps.lists.services import access", "import apps.lists", "from apps import lists",
                    "from ...lists import card", "import importlib\nimportlib.import_module('apps.lists.tasks')",
                    "x = 'apps.lists.extensions'"),
                   ('"""apps.lists в докстринге"""\n# apps.lists в комментарии\nimport os',
                    "from apps.core import extensions", "event = 'lists.record_created'"))
    offenders = []
    for app in ("core", "org", "servicedesk", "notify", "knowledge", "search"):
        offenders += _scan("apps", app, bad=bad)
    assert offenders == [], f"модуль знает о lists: {offenders}"


# --- FR-543: точки расширения (CONTRACT-006, 3.2) ------------------------------------------------------------------

def test_points_still_have_seventeen_names():
    """FR-543: `POINTS` ядра — по-прежнему ровно семнадцать имён в порядке контракта; `_registry` содержит ключ на
    каждое имя (срез 006 новых точек не вводит)."""
    from apps.core import extensions

    assert tuple(extensions.POINTS) == POINTS_17
    assert len(extensions.POINTS) == 17
    assert set(extensions._registry) == set(POINTS_17)


def test_lists_registers_menu_8_search_50_card_70_ticket_part_20():
    """FR-543: `lists` регистрирует по одной функции в `menu_items` (порядок 8, `/lists/`, «Списки», без права),
    `search_providers` (ключ `lists`, порядок 50), `card_sections` (раздел `lists-pinned`, вкладка профиля, порядок 70) и
    `ticket_card_parts` (часть `lists-records`, раздел, порядок 20)."""
    from apps.lists import card
    from apps.lists import extensions as lists_extensions
    from apps.lists.services import search as lists_search

    menu, providers, sections, parts = (_own(p) for p in ("menu_items", "search_providers", "card_sections",
                                                           "ticket_card_parts"))
    assert [f.__module__ for f in menu] == ["apps.lists.extensions"] and menu[0] is lists_extensions.menu_items
    item = menu[0]()[0]
    assert (item["url"], item["title"], item["order"], tuple(item["permissions"])) == ("/lists/", "Списки", 8, ())
    assert [f.__module__ for f in providers] == ["apps.lists.services.search"]
    assert providers[0] is lists_search.search_providers
    found = providers[0]()
    assert [(p.key, p.title, p.order) for p in found] == [("lists", "Списки", 50)]
    assert len(sections) == 1 and sections[0] is card.card_sections
    assert len(parts) == 1 and parts[0].__module__ == "apps.lists.ticket_parts"
    part = parts[0]()
    assert [(p.key, p.kind, p.order) for p in part] == [("lists-records", "section", 20)]
    # раздел «Закреплённое»: есть строка — порядок 70, вкладка профиля, шаблон; нет строк — пусто
    lst = support_lists.make_list()
    field = support_lists.add_field(lst, "person", "Ответственный")
    person = support.make_employee()
    other = support.make_employee()
    support_lists.make_record(lst, "Плоттер", {field.code: [person.pk]}, created_by=person)
    section = sections[0](person, person)
    assert [(s.key, s.tab, s.order, s.template) for s in section] == [
        ("lists-pinned", "profile", 70, "lists/_card_pinned.html")]
    assert sections[0](other, other) == []


def test_lists_registers_notification_kind_file_purpose_audit_labels_unit_and_role_usage_stand_reset():
    """FR-543: по одной функции `lists` в `notification_kinds`, `file_purposes`, `audit_labels`, `unit_usage`,
    `role_usage`, `stand_reset` — в нужных модулях; точек `role_sources`, `staff_directory`, `day_marks`,
    `home_notices`, `mail_renderers`, `login_links`, `top_bar_items` модуль не использует."""
    expected = {
        "notification_kinds": ("apps.lists.notify_kinds", "notification_kinds"),
        "file_purposes": ("apps.lists.services.files", "file_purposes"),
        "audit_labels": ("apps.lists.audit_labels", "audit_labels"),
        "unit_usage": ("apps.lists.services.links", "unit_usage"),
        "role_usage": ("apps.lists.services.links", "role_usage"),
        "stand_reset": ("apps.lists.stand", "stand_reset"),
    }
    for point, (module, name) in expected.items():
        funcs = _own(point)
        assert [(f.__module__, f.__name__) for f in funcs] == [(module, name)], f"точка {point}: {funcs}"
    kinds = _own("notification_kinds")[0]()
    assert [(k.code, k.module) for k in kinds] == [("lists.deadline", "Списки")]
    purposes = _own("file_purposes")[0]()
    assert [p.purpose for p in purposes] == ["lists"]
    for point in ("role_sources", "staff_directory", "day_marks", "home_notices", "mail_renderers", "login_links",
                  "top_bar_items"):
        assert _own(point) == [], f"`lists` зарегистрировал функцию в точке {point}"


# --- FR-543: меню, поиск, карточки, каталог уведомлений без lists --------------------------------------------------

def test_menu_without_lists_has_no_lists_item():
    """FR-543: без регистраций `lists` в меню нет пункта «Списки» (`/lists/`) ни в `menu_for`, ни в разметке страницы;
    прежние пункты остаются; с включённым модулем пункт есть (порядок 8)."""
    from apps.core.services import permissions

    manager = support_lists.as_manager()
    item = [m for m in permissions.menu_for(manager.user) if m["title"] == "Списки"]
    assert item and item[0]["url"] == "/lists/" and item[0]["order"] == 8, "при включённом модуле нет пункта «Списки»"
    assert 'href="/lists/"' in manager.client.get("/").content.decode()
    with support_lists.without_lists():
        menu = permissions.menu_for(manager.user)
        html = manager.client.get("/").content.decode()
    assert [m for m in menu if m["title"] == "Списки" or m["url"].startswith("/lists/")] == []
    assert any(m["url"] == "/staff/" for m in menu), "пропали прежние пункты меню"
    assert 'href="/lists/"' not in html


def test_search_page_without_lists_renders_without_lists_group():
    """FR-543: без регистраций `lists` страница `/search/` рисуется (200) без группы «Списки»
    (`data-search-group="lists"`), подсчёт группы — пустой ответ, записи в выдаче нет; с модулем группа с записью есть."""
    from apps.core import extensions
    from apps.search import parse, services

    source = support_lists.make_list("Оборудование поиска")
    reader = support_lists.as_reader(source)
    record = support_lists.make_record(source, f"{WORD.capitalize()} Эпсон")
    parsed = parse.parse(WORD)
    assert "lists" in [g.key for g in services.page(reader.user, parsed)], "при включённом модуле нет группы «Списки»"
    assert 'data-search-group="lists"' in reader.client.get(f"/search/?q={WORD}").content.decode()
    with support_lists.without_lists():
        assert "lists" not in [p.key for f in extensions.registered("search_providers") for p in f()]
        assert "lists" not in [g.key for g in services.page(reader.user, parsed)]
        response = reader.client.get(f"/search/?q={WORD}")
        counted = reader.client.get(f"/search/count/?q={WORD}&group=lists")
    assert response.status_code == 200 and 'data-search-group="lists"' not in response.content.decode()
    assert f"/lists/{source.pk}/{record.number}/" not in response.content.decode()
    assert counted.status_code == 200 and counted.content.decode().strip() == "", "подсчёт неизвестной группы — пустой ответ"


def test_employee_card_without_lists_has_no_pinned_section_and_renders():
    """FR-543: пока `lists` включён, у сотрудника с закреплённой записью `/me/` и `/staff/<id>/` (читающим коллегой)
    несут `#lists-pinned` со строкой; без регистраций `lists` обе карточки рисуются (200), раздела и строк нет."""
    from apps.core import extensions

    lst = support_lists.make_list("Оборудование карточки")
    field = support_lists.add_field(lst, "person", "За кем закреплено")
    person = support.make_employee()
    support_lists.make_record(lst, "Ноутбук для карточки", {field.code: [person.pk]}, created_by=person)
    unit = org.make_unit("Отдел карточек")
    colleague = support.make_with_permissions("staff.view")
    org.make_member(colleague, unit)
    support_lists.grant_list(lst, unit, "read")
    own, other = support.logged_in(person), support.logged_in(colleague)
    for client, url in ((own, "/me/"), (other, f"/staff/{person.pk}/")):
        html = client.get(url).content.decode()
        assert 'id="lists-pinned"' in html and "data-pinned-record" in html, f"при включённом модуле нет раздела: {url}"
    with support_lists.without_lists():
        assert extensions.registered("card_sections") == [] or all(
            not f.__module__.startswith("apps.lists") for f in extensions.registered("card_sections"))
        pages = [(url, client.get(url)) for client, url in ((own, "/me/"), (other, f"/staff/{person.pk}/"))]
    for url, response in pages:
        assert response.status_code == 200, f"{url}: {response.status_code}"
        html = response.content.decode()
        assert "lists-pinned" not in html and "data-pinned-record" not in html, f"без lists в карточке раздел: {url}"
        assert "Ноутбук для карточки" not in html


def test_ticket_card_without_lists_has_no_records_part_and_renders(caplog):
    """FR-543: пока `lists` включён, карточка заявки у читающего список участника очереди несёт часть `lists-records`;
    без регистраций `lists` карточка рисуется (200, поля, лента, форма комментария), оболочки части и раздела
    `data-lists-ticket-section` нет, ошибок в журнале нет."""
    from apps.core import extensions

    user, queue = _reader_in_queue("servicedesk.all")
    lst = support_lists.make_list("Оборудование заявки")
    support_lists.grant_list(lst, queue.unit, "read")
    ticket = sd.make_ticket(queue=queue)
    with_lists = _card_html(user, ticket)
    assert 'data-card-part="lists-records"' in with_lists and "data-lists-ticket-section" in with_lists, \
        "при включённом модуле нет части `lists-records`"
    with caplog.at_level("DEBUG"):
        with support_lists.without_lists():
            assert [f for f in extensions.registered("ticket_card_parts")
                    if f.__module__.startswith("apps.lists")] == []
            html = _card_html(user, ticket)
    assert 'data-card-part="lists-records"' not in html and "data-lists-ticket-section" not in html
    assert 'data-ticket-link-id' not in html and 'data-lists-picker="ticket"' not in html
    assert "data-card-fields" in html and "data-card-feed" in html, "карточка потеряла поля или ленту"
    assert 'data-form="ticket-comment"' in html, "пропала форма внутреннего комментария"
    assert [r for r in caplog.records if r.name.startswith("apps.servicedesk") and r.levelno >= 40] == []


def test_notification_catalog_without_lists_has_no_lists_kind():
    """FR-543: без регистраций `lists` каталог видов уведомлений не содержит `lists.deadline` и модуля «Списки», проверка
    каталога проходит, прочие виды те же; с включённым модулем добавляется ровно один вид."""
    from apps.notify.services import kinds

    full = {kind.code: kind for kind in kinds.catalog()}
    assert "lists.deadline" in full, "при включённом модуле в каталоге нет вида `lists.deadline`"
    with support_lists.without_lists():
        kinds.check()
        rest = kinds.catalog()
    assert [k.code for k in rest if k.code.startswith("lists.") or k.module == "Списки"] == []
    assert {k.code for k in rest} == set(full) - {"lists.deadline"}


# --- FR-543: шина и связи (CONTRACT-006, 3.2, 3.3, 2.2) -----------------------------------------------------------

def test_lists_publishes_no_bus_events_and_subscribes_only_to_user_dismissed():
    """FR-543: `lists` не публикует событий шины (нет `events.publish` в `apps/lists/**`) и подписан только на
    `core.user_dismissed` обработчиком `apps.lists.services.links.on_user_dismissed`; сам разбор находит вызов на образцах."""
    from apps.core import events

    assert _publishes("from apps.core import events\nevents.publish('x.y', a=1)")
    assert _publishes("from apps.core.events import publish\npublish('x.y')")
    assert not _publishes("from apps.core import events\nevents.subscribe('x.y', f)")
    publishing = [str(p.relative_to(support.BACKEND_DIR)) for p, text in _lists_sources().items() if _publishes(text)]
    assert publishing == [], f"`lists` публикует события: {publishing}"
    own = {name: [(h.__module__, h.__name__) for h in handlers if getattr(h, "__module__", "").startswith("apps.lists")]
           for name, handlers in events._registry.items()}
    assert {name: found for name, found in own.items() if found} == {
        "core.user_dismissed": [("apps.lists.services.links", "on_user_dismissed")]}


def test_lists_models_have_no_foreign_keys_to_org_and_servicedesk_models():
    """FR-543: ни одно поле связи моделей `lists` не ведёт в приложения `org` и `servicedesk` (подразделение и заявка —
    числа); связи только с `core` и `lists`."""
    from django.apps import apps

    models = {m.__name__: m for m in apps.get_app_config("lists").get_models()}
    assert set(LISTS_MODELS) <= set(models), f"в приложении нет моделей: {sorted(set(LISTS_MODELS) - set(models))}"
    seen = 0
    for name, list_model in models.items():
        for field in list_model._meta.get_fields():
            if field.is_relation and not field.auto_created:
                seen += 1
                assert field.related_model._meta.app_label not in ("org", "servicedesk"), \
                    f"{name}.{field.name} ведёт в приложение {field.related_model._meta.app_label}"
                assert field.related_model._meta.app_label in ("core", "lists"), \
                    f"{name}.{field.name} ведёт в приложение {field.related_model._meta.app_label}"
    assert seen > 0, "у моделей `lists` нет ни одной связи"


def test_access_unit_id_and_ticket_link_ticket_number_are_plain_integers():
    """FR-543: `Access.unit_id` — `PositiveIntegerField(null=True)` без связи, `TicketLink.ticket_number` —
    `PositiveIntegerField` без связи; связи `Access.role` с ролью ядра и `TicketLink.record` с записью остаются."""
    from django.db.models import PositiveIntegerField

    unit_id = model("lists.Access")._meta.get_field("unit_id")
    ticket_number = model("lists.TicketLink")._meta.get_field("ticket_number")
    assert isinstance(unit_id, PositiveIntegerField) and not unit_id.is_relation and unit_id.null
    assert isinstance(ticket_number, PositiveIntegerField) and not ticket_number.is_relation and not ticket_number.null
    assert model("lists.Access")._meta.get_field("role").related_model._meta.label == "core.Role"
    assert model("lists.TicketLink")._meta.get_field("record").related_model._meta.label == "lists.Record"
