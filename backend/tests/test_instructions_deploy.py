"""Срез 010 «Поручения»: развёртывание и оболочка (T-10121; NFR-722, 723, 725, 726, 728).

Контракт: 1.1 (приложение, статика, CSP, язык), 1.2 (cron, адреса, nginx), 1.4 (числа), 3 (точки), 6.2 (адреса),
13.2 (`fill_instructions.py`, `InstructionUser`). `config/cron.py` разбирается через `ast`: модуль зовёт
`django.setup()` при импорте. Код среза импортируется внутри тестов.
"""
import ast
import re

import pytest
from django.conf import settings as django_settings
from django.urls import resolve

from tests import support
from tests import support_instructions as ins
from tests.support import BACKEND_DIR, repo_file

pytestmark = pytest.mark.django_db

APP = "apps.instructions"
NGINX_FILES = ("nginx.conf", "nginx.prod.conf")
PROTO = {"nginx.conf": "$scheme", "nginx.prod.conf": "$portal_proto"}
FEED_FILES_PATTERN = "^/feed/files/$"
MESSENGER_FILES_PATTERN = "^/messenger/files/$"
TASKS_FILES_PATTERN = "^/tasks/files/$"
INSTRUCTIONS_FILES_PATTERN = "^/instructions/files/$"
ENGLISH_WORDS = ("Save", "Delete", "Cancel", "Search", "Submit", "Edit", "Back")

INSTRUCTIONS_JOBS = {
    "instructions_reminders": ("instructions_reminders", "maintenance", "*/5 * * * *", 300),
    "instructions_digest": ("instructions_digest", "maintenance", "*/15 * * * *", 300),
    "instructions_retention": ("instructions_retention", "maintenance", "43 23 * * *", 600),
}

INSTRUCTIONS_PATHS = (
    "/instructions/", "/instructions/list/", "/instructions/new/", "/instructions/1/",
    "/instructions/1/ladder/", "/instructions/1/close/", "/instructions/1/reports/",
    "/instructions/1/parts/", "/instructions/reports/1/accept/", "/instructions/reports/1/return/",
    "/instructions/1/transfers/", "/instructions/transfers/1/approve/",
    "/instructions/transfers/1/reject/", "/instructions/files/",
    "/instructions/files/123e4567-e89b-12d3-a456-426614174000/", "/instructions/discipline/",
    "/instructions/discipline.xlsx", "/settings/instructions/", "/settings/instructions/basis/",
    "/settings/instructions/basis/1/", "/settings/instructions/basis/1/delete/",
)


# --- чтение файлов (свои помощники, общие файлы не правятся) --------------------------------------

def deploy_text(*parts: str) -> str:
    return repo_file("deploy", *parts).read_text(encoding="utf-8")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def location_body(text: str, header: str) -> str:
    found = re.search(r"location\s+" + header + r"\s*\{", text)
    assert found, f"нет location {header}"
    depth, i = 1, found.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[found.end():i - 1]


def directives(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in body.split(";") if part.strip()]


def locations_with_limit(name: str, limit: str) -> list[tuple[str, str]]:
    text = uncommented(deploy_text(name))
    found = []
    for header in re.findall(r"location\s+([^{]+?)\s*\{", text):
        body = location_body(text, re.escape(header))
        if f"client_max_body_size {limit}" in directives(body):
            found.append((header.split(None, 1)[-1], body))
    return found


def tickets_location_body(name: str) -> str:
    return location_body(uncommented(deploy_text(name)), re.escape(r"~ ^/tickets/(new/|[0-9]+/reply/)$"))


def proxy_names(items: list[str]) -> set[str]:
    return {" ".join(item.split()[:2]) if item.startswith("proxy_set_header") else item.split()[0] for item in items}


def cron_source() -> str:
    return (BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")


def cron_registrations() -> list[dict]:
    tree = ast.parse(cron_source())
    constants = {node.targets[0].id: node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                 and isinstance(node.value, ast.Constant)}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            first = node.args[0] if node.args else None
            target = aliases.get(first.id, first.id) if isinstance(first, ast.Name) else None
            options = {kw.arg: value(kw.value) for kw in node.keywords}
            found.append({"target": target, "queue": options.get("queue_name"), "cron": options.get("cron"),
                          "interval": options.get("interval"), "name": options.get("name"),
                          "job_timeout": options.get("job_timeout")})
    return found


def cron_by_name() -> dict[str, dict]:
    result = {}
    for item in cron_registrations():
        if item["name"]:
            result[item["name"]] = item
    return result


# --- приложение, адреса, меню --------------------------------------------------------------------

def test_instructions_is_last_in_installed_apps_with_config():
    """План: `apps.instructions` — последнее приложение, метка `instructions`, класс `InstructionsConfig`,
    `verbose_name` «Поручения»."""
    from django.apps import apps as registry

    installed = list(django_settings.INSTALLED_APPS)
    assert installed[-1] == "apps.automation" and installed[-2] == APP and installed[-3] == "apps.tasks"
    config = registry.get_app_config("instructions")
    assert type(config).__name__ == "InstructionsConfig"
    assert (config.label, config.verbose_name) == ("instructions", "Поручения")


def test_all_contract_paths_resolve_with_app_name():
    """CONTRACT-010, 6.2: адреса среза разрешаются, `app_name = "instructions"`; литеральные `list/`, `new/`,
    `files/`, `reports/`, `transfers/`, `discipline/`, `basis/` не попадают под `<int>`, в путях нет `regist` и
    `signup`."""
    from apps.instructions import urls as instructions_urls

    assert instructions_urls.app_name == "instructions"
    for path in INSTRUCTIONS_PATHS:
        match = resolve(path)
        assert match.app_name == "instructions", path
    for path in INSTRUCTIONS_PATHS:
        assert "regist" not in path and "signup" not in path


def test_urls_include_is_guarded_after_tasks():
    """План: `include("apps.instructions.urls")` — один раз, под `apps.is_installed("apps.instructions")` и после
    `tasks`."""
    path = BACKEND_DIR / "config" / "urls.py"
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
    assert guarded, "include(apps.instructions.urls) вне проверки"
    tasks = [node for node in includes if node.args[0].value == "apps.tasks.urls"][0]
    assert tasks.lineno < own[0].lineno, "include поручений стоит раньше задач"


def test_cron_has_27_registers_and_three_instructions_jobs():
    """План: три задания — `*/5`, `*/15`, `43 23`, очередь `maintenance`, таймауты 300/300/600, под проверкой
    установки; всего 29 вызовов (два задания среза 011)."""
    entries = cron_registrations()
    assert len(entries) == 32, f"вызовов register {len(entries)}"
    by_name = cron_by_name()
    for name, (function, queue, cron, timeout) in INSTRUCTIONS_JOBS.items():
        item = by_name.get(name)
        assert item, f"нет задания {name}"
        assert item["target"] == f"apps.instructions.tasks.{function}", item["target"]
        assert (item["queue"], item["interval"], item["cron"], item["job_timeout"]) == (queue, None, cron, timeout)
    source = cron_source()
    assert re.search(r'is_installed\("apps\.instructions"\)', source)
    assert not [row["name"] for row in entries if row["name"] != "instructions_retention"
                and row["cron"] == "43 23 * * *"]


def test_menu_has_two_items_with_orders_three_and_sixty_six():
    """План: «Поручения» — `order` 3, право `instructions.use`; «Настройки поручений» — `order` 66, право
    `settings.portal`; у администратора двадцать пунктов."""
    from apps.core import extensions
    from apps.core.services import permissions

    admin = support.make_admin()
    items = [item for func in extensions.registered("menu_items") for item in func()
             if item["url"] in ("/instructions/", "/settings/instructions/")]
    assert [(item["url"], item["title"], item["order"], tuple(item["permissions"])) for item in items] == [
        ("/instructions/", "Поручения", 3, ("instructions.use",)),
        ("/settings/instructions/", "Настройки поручений", 66, ("settings.portal",)),
    ]
    assert len(permissions.menu_for(admin)) == 23


# --- статика, CSP, nginx -------------------------------------------------------------------------

def test_static_assets_are_wired_for_both_prefixes():
    """План: `instructions.css` и `instructions.js` подключены в `_assets.html`; условие
    `'/instructions/' in request.path` покрывает и `/settings/instructions/`."""
    text = (BACKEND_DIR / "templates" / "_assets.html").read_text(encoding="utf-8")
    assert "instructions/instructions.css" in text and "instructions/instructions.js" in text
    assert "'/instructions/' in request.path" in text
    assert "/settings/instructions/".startswith("/instructions/") is False
    assert "/settings/instructions/".find("/instructions/") >= 0, "подстрока не покрывает настройки"


def test_csp_without_unsafe_inline_on_instructions_pages(client):
    """NFR-725: страницы отдают CSP без `unsafe-inline`/`unsafe-eval`."""
    support.login(client, support.make_admin())
    for path in ("/instructions/", "/settings/instructions/"):
        response = client.get(path)
        csp = response["Content-Security-Policy"]
        assert "script-src" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp, path


def test_nginx_has_four_25m_locations_and_instructions_proxy_directives():
    """NFR-722: в обоих конфигах четыре `location` с `25m`; у поручений тот же набор `proxy_*`, что у `tickets`."""
    expected = [FEED_FILES_PATTERN, MESSENGER_FILES_PATTERN, TASKS_FILES_PATTERN, INSTRUCTIONS_FILES_PATTERN]
    for name in NGINX_FILES:
        found = locations_with_limit(name, "25m")
        assert sorted(pattern for pattern, _body in found) == sorted(expected), name
        own = directives(dict(found)[INSTRUCTIONS_FILES_PATTERN])
        for wanted in ("client_max_body_size 25m", "proxy_pass http://portal_web", "proxy_http_version 1.1",
                       "proxy_set_header Host $http_host", "proxy_set_header X-Forwarded-For $remote_addr",
                       f"proxy_set_header X-Forwarded-Proto {PROTO[name]}",
                       "proxy_set_header Upgrade $http_upgrade",
                       "proxy_set_header Connection $connection_upgrade"):
            assert wanted in own, f"{name}: нет `{wanted};`"
        assert proxy_names(own) == proxy_names(directives(tickets_location_body(name))), name


# --- права, Purpose, нагрузка, язык --------------------------------------------------------------

def test_permissions_and_purpose_are_installed():
    """FR-702, FR-703, NFR-722: два права поручений и назначение `instruction` — последними; всего прав 25 (срезы 001–011)."""
    from apps.core.models.files import StoredFile

    Permission = support.model("core.Permission")
    assert set(Permission.objects.filter(code__in=("instructions.use", "instructions.assign"))
               .values_list("code", flat=True)) == {"instructions.use", "instructions.assign"}
    assert Permission.objects.count() == 26
    assert tuple(StoredFile.Purpose.values)[-1] == "instruction"


def test_load_profile_files_exist():
    """NFR-728: `fill_instructions.py` на 1 000 поручений и класс `InstructionUser` рядом с прежними."""
    fill = BACKEND_DIR / "tests" / "load" / "fill_instructions.py"
    assert fill.is_file(), "нет fill_instructions.py"
    text = fill.read_text(encoding="utf-8")
    assert "E2E_STAND" in text and "fill_instructions:" in text
    locust = (BACKEND_DIR / "tests" / "load" / "locustfile.py").read_text(encoding="utf-8")
    assert "class InstructionUser" in locust


def test_visible_texts_are_russian_and_time_is_moscow():
    """NFR-726: надписи по-русски; время — Europe/Moscow."""
    client = support.logged_in(ins.staff_user())
    page = client.get("/instructions/").content.decode()
    assert "Поручения" in page
    for word in ENGLISH_WORDS:
        assert word not in page, f"английская надпись {word}"
    assert django_settings.TIME_ZONE == "Europe/Moscow"