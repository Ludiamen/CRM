"""T-8124: развёртывание и оболочка среза 008 — приложение, расписание, адреса, соединение, nginx, том файлов,
зависимости, CSP, шаблоны и статика, язык и время, числа среза, нагрузка, границы импортов (FR-643, FR-661, FR-662,
FR-670, FR-673, NFR-702, NFR-704, NFR-707, NFR-708).

Сценарии плана «Запуск», «Где живёт код», «Безопасный вывод, язык, узкий экран», «Нагрузка», «Проверка»,
«Изменения кода прежних срезов». Контракт — CONTRACT-008: 1.1 (приложение, статика, шаблоны, CSP, язык и время),
1.2 (cron, адреса, соединение, nginx, слой каналов, том файлов, зависимости), 1.4 (числа среза), 12 (зацепки),
14.2 (нагрузка). Образцы — `test_feed_deploy.py` и `test_sd_deploy.py`.

`config/cron.py`, `config/urls.py` и `config/asgi.py` разбираются через `ast`: `config.cron` зовёт `django.setup()`
при импорте, поэтому модуль не импортируется. Код среза импортируется внутри тестов — `pytest --collect-only`
проходит до появления кода среза.
"""
import ast
import re
from datetime import datetime, timezone as dt_timezone

import pytest

from django.conf import settings as django_settings

from tests import support
from tests import support_messenger as messenger
from tests.support import BACKEND_DIR, repo_file

PLAIN = pytest.mark.django_db

APP = "apps.messenger"
NGINX_FILES = ("nginx.conf", "nginx.prod.conf")
PROTO = {"nginx.conf": "$scheme", "nginx.prod.conf": "$portal_proto"}
MESSENGER_FILES_PATTERN = "^/messenger/files/$"
TASKS_FILES_PATTERN = "^/tasks/files/$"
INSTRUCTIONS_FILES_PATTERN = "^/instructions/files/$"
FEED_FILES_PATTERN = "^/feed/files/$"
ENGLISH_WORDS = ("Save", "Delete", "Cancel", "Search", "Submit", "Edit", "Back")
REFUSAL_LOAD = "Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."

# хвост `INSTALLED_APPS` среза 008 (CONTRACT-008, 1.1)
APPS_TAIL = ("apps.servicedesk", "apps.notify", "apps.knowledge", "apps.lists", "apps.search", "apps.feed",
             "apps.messenger", "apps.tasks", "apps.instructions")

# двадцать прежних записей `config/cron.py`: имя -> ("cron", строка) или ("interval", секунды); девятнадцатая и
# двадцатая — записи ленты среза 007, двадцать первая (мессенджер) в перечень не входит
PREVIOUS_CRON = {
    "purge_login_history": ("cron", "10 3 * * *"),
    "purge_expired_links": ("cron", "20 3 * * *"),
    "purge_expired_sessions": ("cron", "30 3 * * *"),
    "requeue_pending_scans": ("cron", "0 * * * *"),
    "purge_quarantine": ("cron", "50 3 * * *"),
    "purge_import_previews": ("cron", "40 3 * * *"),
    "poll_mailbox": ("cron", "* * * * *"),
    "requeue_inbound": ("cron", "*/5 * * * *"),
    "autoclose": ("cron", "5 * * * *"),
    "reconcile_assignees": ("cron", "25 * * * *"),
    "purge_inbound": ("cron", "10 23 * * *"),
    "anonymize_tickets": ("cron", "20 23 * * *"),
    "purge_requester_previews": ("cron", "30 23 * * *"),
    "purge_orphan_files": ("cron", "50 23 * * *"),
    "notify_tick": ("interval", 30),
    "notify_retention": ("cron", "40 23 * * *"),
    "purge_trash": ("cron", "45 23 * * *"),
    "lists_reminders": ("cron", "0 5 * * *"),
    "feed_reminders": ("cron", "* * * * *"),
    "feed_retention": ("cron", "35 23 * * *"),
}

# имена пакетов `requirements.txt` после среза 007 (пакетов и строки среза 008 нет)
PRIOR_PACKAGES = (
    "django", "psycopg", "psycopg-pool", "django-rq", "rq", "django-environ", "django-otp", "cryptography", "qrcode",
    "argon2-cffi", "ua-parser", "django-csp", "gunicorn", "uvicorn", "uvicorn-worker", "pillow", "openpyxl",
    "et-xmlfile", "defusedxml", "redis", "channels", "channels-redis", "websockets", "msgpack", "asgiref",
    "markdown-it-py", "mdurl", "nh3")

# тома и службы `docker-compose.yml` на момент среза 007: срез не добавляет ни одного (план, «Запуск»)
COMPOSE_VOLUMES = ["postgres-data", "valkey-data", "clamav-db", "test-venv", "media", "protected", "backups"]
COMPOSE_SERVICES = ("postgres", "valkey", "web", "web-heavy", "migrate", "worker", "worker-mail", "worker-inbox",
                    "worker-notify", "notify-poller", "backup", "clamav", "scheduler", "nginx", "standtools",
                    "mailpit", "dovecot", "fakebots", "test")

# прежние модули, которые не должны знать о мессенджере (FR-643, CONTRACT-008, 1.1)
PREVIOUS_MODULES = ("core", "org", "notify", "knowledge", "servicedesk", "lists", "search", "feed", "integrations")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")


# --- помощники чтения файлов (свои: общие файлы тестов не правятся) -------------------------------------------------

def deploy_text(*parts: str) -> str:
    return repo_file("deploy", *parts).read_text(encoding="utf-8")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def location_body(text: str, header: str) -> str:
    """Тело `location <header> { … }`; header — регулярное выражение между `location` и `{`."""
    found = re.search(r"location\s+" + header + r"\s*\{", text)
    assert found, f"нет location {header}"
    depth, i = 1, found.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[found.end():i - 1]


def directives(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in body.split(";") if part.strip()]


def location_headers(name: str) -> list[str]:
    return [re.sub(r"\s+", " ", header).strip()
            for header in re.findall(r"location\s+([^{]+?)\s*\{", uncommented(deploy_text(name)))]


def locations_with_limit(name: str, limit: str) -> list[tuple[str, str]]:
    """Все `location` файла nginx с `client_max_body_size <limit>`: (шаблон адреса, тело)."""
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


def _guarded(node, parents, app: str) -> bool:
    """Узел лежит внутри `if apps.is_installed("<app>"):` (сравнение — по тексту условия)."""
    current = parents.get(node)
    wanted = re.compile(r"(\w+\.)*is_installed\(\"" + re.escape(app) + r"\"\)")
    while current is not None:
        if isinstance(current, ast.If):
            test = ast.unparse(current.test).replace("'", '"').replace(" ", "")
            if wanted.fullmatch(test):
                return True
        current = parents.get(current)
    return False


def cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в `config/cron.py` (разбор дерева): полный путь функции, очередь, cron, интервал, имя,
    job_timeout, строка, признак «под проверкой `apps.is_installed("apps.messenger")`»."""
    tree = ast.parse(cron_source())
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
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
                          "job_timeout": options.get("job_timeout"), "line": node.lineno,
                          "guarded": _guarded(node, parents, "apps.messenger")})
    return found


def cron_by_name() -> dict[str, dict]:
    entries = cron_registrations()
    result = {}
    for item in entries:
        assert item["name"] not in result, f"задание {item['name']} зарегистрировано дважды"
        result[item["name"]] = item
    return result


def _targets(source: str, package: list[str], *, with_strings: bool = True) -> set[str]:
    """Абсолютные имена, от которых зависит файл (`ast`): `import a.b`; `from a.b import c` — имя `a.b.c`;
    относительные импорты; `import_module("…")`/`__import__("…")`; при `with_strings` — строка-путь модуля вне
    докстрингов."""
    tree = ast.parse(source)
    docstrings = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
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


def _visible(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _marks(html: str) -> list[tuple[str, str]]:
    """Времена `time[data-at]`: (атрибуты, текст)."""
    return [(attrs, re.sub(r"\s+", " ", text).strip())
            for attrs, text in re.findall(r"<time\b([^>]*\bdata-at\b[^>]*)>(.*?)</time>", html, re.S)]


def _csp(response, path: str) -> dict[str, list[str]]:
    assert response.status_code == 200, f"{path}: статус {response.status_code}"
    header = response.get("Content-Security-Policy", "")
    assert header, f"{path}: нет заголовка Content-Security-Policy"
    result = {}
    for part in header.split(";"):
        words = part.split()
        if words:
            result[words[0]] = words[1:]
    return result


def _messenger_session():
    """Администратор портала (видит `/settings/messenger/`) с групповым чатом, где он создатель, и его клиент."""
    admin = messenger.as_admin()
    peer = messenger.make_user()
    chat = messenger.group(admin, [peer], title="Переезд серверной")
    return admin, chat


# --- приложение, адреса, соединение (CONTRACT-008, 1.1–1.2) ---------------------------------------------------------

def test_messenger_is_last_in_installed_apps():
    """FR-643: в конце `INSTALLED_APPS` — `apps.servicedesk`, `apps.notify`, `apps.knowledge`, `apps.lists`,
    `apps.search`, `apps.feed`, `apps.messenger`, `apps.tasks`, `apps.instructions`; метка `messenger`, класс
    `MessengerConfig`, `verbose_name` «Мессенджер» (CONTRACT-008, 1.1; CONTRACT-009/010). Прежние имена на месте."""
    from django.apps import apps
    from django.conf import settings

    installed = list(settings.INSTALLED_APPS)
    assert tuple(installed[-9:]) == APPS_TAIL, f"хвост INSTALLED_APPS: {installed[-9:]}"
    assert (installed[-4] == "apps.feed" and installed[-3] == APP and installed[-2] == "apps.tasks"
            and installed[-1] == "apps.instructions")
    assert len(installed) == installed.index("apps.messenger") + 3, "после apps.messenger ровно tasks и instructions"
    config = apps.get_app_config("messenger")
    assert type(config).__name__ == "MessengerConfig"
    assert config.label == "messenger"
    assert config.verbose_name == "Мессенджер"


def test_messenger_urls_and_asgi_routes_are_under_is_installed_guard():
    """FR-644…FR-673: `config/urls.py` подключает `include("apps.messenger.urls")` ровно один раз и только внутри
    `if apps.is_installed("apps.messenger"):` (после `feed`); `config/asgi.py` добавляет
    `messenger.routing.websocket_urlpatterns` под той же проверкой, списки `notify`, затем `feed`, затем `messenger`,
    маршрутизатор прежний (CONTRACT-008, 1.2)."""
    urls_path = BACKEND_DIR / "config" / "urls.py"
    urls_tree = ast.parse(urls_path.read_text(encoding="utf-8"))
    parents = {child: parent for parent in ast.walk(urls_tree) for child in ast.iter_child_nodes(parent)}
    includes = [node for node in ast.walk(urls_tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "include"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    own = [node for node in includes if node.args[0].value == "apps.messenger.urls"]
    assert len(own) == 1, f"подключений apps.messenger.urls: {len(own)}"
    assert _guarded(own[0], parents, APP), "include(apps.messenger.urls) вне проверки apps.is_installed"
    others = [node.args[0].value for node in includes
              if node.args[0].value != "apps.messenger.urls" and _guarded(node, parents, APP)]
    assert not others, f"под проверкой apps.messenger подключено лишнее: {others}"
    assert len(includes) >= 8, "прежние подключения адресов исчезли"
    feed_index = [i for i, node in enumerate(includes) if node.args[0].value == "apps.feed.urls"]
    assert feed_index and feed_index[0] < includes.index(own[0]), "include мессенджера стоит до include ленты"
    errors = urls_path.read_text(encoding="utf-8")
    assert "handler404" in errors and "handler500" in errors, "обработчики ошибок пропали"

    asgi_path = BACKEND_DIR / "config" / "asgi.py"
    asgi_tree = ast.parse(asgi_path.read_text(encoding="utf-8"))
    asgi_parents = {child: parent for parent in ast.walk(asgi_tree) for child in ast.iter_child_nodes(parent)}
    imports = [node for node in ast.walk(asgi_tree) if isinstance(node, ast.ImportFrom)
               and ((node.module or "") == "apps.messenger.routing"
                    or ((node.module or "") == "apps.messenger" and any(a.name == "routing" for a in node.names))
                    or ((node.module or "") == "apps" and any(a.name == "messenger" for a in node.names)))]
    assert imports, "в config/asgi.py нет импорта маршрутов мессенджера"
    assert all(_guarded(node, asgi_parents, APP) for node in imports), "импорт маршрутов мессенджера вне проверки"
    top_level = [node for node in asgi_tree.body if isinstance(node, ast.ImportFrom)
                 and (node.module or "").startswith("apps.messenger")]
    assert not top_level, "импорт apps.messenger на верхнем уровне config/asgi.py"
    source = asgi_path.read_text(encoding="utf-8")
    assert re.search(r"websocket_urlpatterns\s*=\s*list\(\s*notify_routing\.websocket_urlpatterns\s*\)", source)
    assert re.search(r"websocket_urlpatterns\s*\+=\s*messenger_routing\.websocket_urlpatterns", source), \
        "маршруты мессенджера не добавлены к списку соединений"
    assert source.index("feed_routing") < source.index("messenger_routing"), "порядок: notify, feed, messenger"
    for needed in ("AllowedHostsOriginValidator", "AuthMiddlewareStack", "URLRouter"):
        assert needed in source, f"маршрутизатор соединений изменён: нет {needed}"


# --- расписание (CONTRACT-008, 1.2, 1.4) ---------------------------------------------------------------------------

def test_cron_has_27_registers_and_messenger_retention_55_23_maintenance():
    """FR-670: в `config/cron.py` двадцать семь вызовов `register`; запись `messenger_retention` —
    `apps.messenger.tasks.retention_night`, очередь `maintenance`, `cron="55 23 * * *"`, `job_timeout=600`, под
    `apps.is_installed("apps.messenger")` вместе со своим импортом; других записей на `55 23 * * *` нет; двадцать
    прежних записей, одна мессенджера и три задач среза 009 — те же имена и минуты (CONTRACT-008, 1.2, 1.4;
    CONTRACT-009, 1.2)."""
    entries = cron_registrations()
    assert len(entries) == 27, (
        f"вызовов register {len(entries)}, ожидается 27 (двадцать прежних, messenger_retention среза 008, три "
        "задания среза 009 и три задания среза 010)")
    function, queue, interval, cron, timeout = messenger.JOBS_008["messenger_retention"]
    item = cron_by_name().get("messenger_retention")
    assert item, "нет задания messenger_retention"
    assert item["target"] == "apps.messenger.tasks.retention_night", f"функция задания: {item['target']}"
    assert (item["queue"], item["interval"], item["cron"], item["job_timeout"]) == (queue, interval, cron, timeout)
    assert item["guarded"], "запись messenger_retention вне проверки apps.is_installed"
    same_time = [row["name"] for row in entries if row["name"] != "messenger_retention" and row["cron"] == cron]
    assert not same_time, f"то же время у других заданий: {same_time}"

    tree = ast.parse(cron_source())
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and node.module == "apps.messenger.tasks"]
    assert imports, "в cron.py нет `from apps.messenger.tasks import retention_night`"
    assert all(_guarded(node, parents, APP) for node in imports), "импорт apps.messenger.tasks вне проверки"
    names = {alias.name for node in imports for alias in node.names}
    assert names == {"retention_night"}, f"импортируются {sorted(names)}"
    assert not [node for node in tree.body if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("apps.messenger")], "импорт мессенджера на верхнем уровне"

    previous = cron_by_name()
    missing = sorted(set(PREVIOUS_CRON) - set(previous))
    assert not missing, f"пропали записи: {missing}"
    for name, (kind, expected) in PREVIOUS_CRON.items():
        row = previous[name]
        if kind == "interval":
            assert row["interval"] == expected and row["cron"] is None, f"{name}: интервал {row['interval']!r}"
        else:
            assert row["cron"] == expected and row["interval"] is None, f"{name}: cron {row['cron']!r}"
        assert not row["guarded"], f"прежняя запись {name} оказалась под проверкой apps.messenger"
    assert len(entries) - len(PREVIOUS_CRON) == 7, (
        "кроме прежних: одна запись мессенджера, три задач среза 009 и три поручений среза 010")


# --- nginx (CONTRACT-008, 1.2, 1.4) --------------------------------------------------------------------------------

def test_nginx_has_four_25m_locations_and_repeated_proxy_directives():
    """FR-662, NFR-704, NFR-713: в обоих конфигах nginx ровно четыре `location` с `client_max_body_size 25m` —
    `^/feed/files/$`, `^/messenger/files/$`, `^/tasks/files/$` (срез 009) и `^/instructions/files/$` (срез 010);
    в новых повторены директивы `proxy_*` из `location /`, набор имён директив тот же, что у блока `tickets`;
    четыре `55m` и общий предел `6m` не менялись (CONTRACT-008, 1.2, 1.4; CONTRACT-009/010, 1.2)."""
    expected = [FEED_FILES_PATTERN, MESSENGER_FILES_PATTERN, TASKS_FILES_PATTERN, INSTRUCTIONS_FILES_PATTERN]
    for name in NGINX_FILES:
        found = locations_with_limit(name, "25m")
        patterns = [pattern for pattern, _body in found]
        assert sorted(patterns) == sorted(expected), f"{name}: location с 25m — {patterns}"
        text = uncommented(deploy_text(name))
        assert len(re.findall(r"client_max_body_size\s+25m;", text)) == 4, f"{name}: 25m должно быть четыре"
        own = directives(dict(found)[MESSENGER_FILES_PATTERN])
        for wanted in ("client_max_body_size 25m", "proxy_pass http://portal_web", "proxy_http_version 1.1",
                       "proxy_set_header Host $http_host", "proxy_set_header X-Forwarded-For $remote_addr",
                       f"proxy_set_header X-Forwarded-Proto {PROTO[name]}",
                       "proxy_set_header Upgrade $http_upgrade",
                       "proxy_set_header Connection $connection_upgrade"):
            assert wanted in own, f"{name}: в location файлов мессенджера нет `{wanted};`"
        assert proxy_names(own) == proxy_names(directives(tickets_location_body(name))), \
            f"{name}: набор директив не как у tickets"
        for other in ("/messenger/files/5/", "/messenger/12/", "/messenger/files/5/thumb/", "/messenger/"):
            assert not re.search(MESSENGER_FILES_PATTERN, other), f"{name}: {other} попал под шаблон загрузки"
        assert re.search(r"^\s{4}client_max_body_size 6m;", text, re.M), f"{name}: общий предел 6m изменён"
        with55 = [pattern for pattern, _body in locations_with_limit(name, "55m")]
        assert with55 == ["/request/", "^/tickets/(new/|[0-9]+/reply/)$", "^/kb/[0-9]+/files/$",
                          "^/lists/[0-9]+/[0-9]+/files/$"], f"{name}: location с 55m: {with55}"


def test_ws_location_and_backup_script_unchanged():
    """FR-661, FR-662, NFR-704: `location /ws/` префиксный и не менялся (тот же набор директив, часы чтения и записи,
    без буферизации; отдельных блоков под `/ws/messenger/` нет); `deploy/backup/backup.sh`, `RESTORE.md`, тома и
    службы `docker-compose.yml` о мессенджере не знают — файлы и эскизы лежат в томе `protected`
    (CONTRACT-008, 1.2)."""
    for name in NGINX_FILES:
        text = uncommented(deploy_text(name))
        assert [header for header in location_headers(name) if "ws" in header] == ["/ws/"], \
            f"{name}: location для WebSocket изменились"
        assert directives(location_body(text, "/ws/")) == [
            "proxy_pass http://portal_web", "proxy_http_version 1.1", "proxy_set_header Host $http_host",
            "proxy_set_header X-Forwarded-For $remote_addr", f"proxy_set_header X-Forwarded-Proto {PROTO[name]}",
            "proxy_set_header Upgrade $http_upgrade", "proxy_set_header Connection $connection_upgrade",
            "proxy_read_timeout 3600s", "proxy_send_timeout 3600s", "proxy_buffering off"], f"{name}: /ws/ изменён"
        assert "/ws/messenger/" not in text, f"{name}: для /ws/messenger/ не нужен свой location"

    script = deploy_text("backup", "backup.sh")
    code = uncommented(script)
    assert not re.search(r"messenger", code, re.I), "backup.sh изменён под мессенджер"
    assert 'pg_dump -Fc -d "$DATABASE_MIGRATE_URL"' in code
    assert "protected-$DAY.tgz" in code and "media-$DAY.tgz" in code and "crm-$DAY.dump" in code
    assert "-mtime +14" in code and "-delete" in code
    assert not re.search(r"messenger", deploy_text("RESTORE.md"), re.I), "RESTORE.md изменён под мессенджер"

    compose = uncommented(deploy_text("docker-compose.yml")) + "\n"
    volumes = re.search(r"^volumes:\s*\n((?:  \S.*\n)+)", compose, re.M)
    assert volumes, "в docker-compose.yml нет раздела volumes"
    assert re.findall(r"^  ([A-Za-z0-9_-]+):", volumes.group(1), re.M) == COMPOSE_VOLUMES, "набор томов изменён"
    section = re.search(r"^services:\s*\n(.*?)^(?:networks|volumes|configs|secrets):\s*\n", compose, re.M | re.S)
    assert section, "в docker-compose.yml нет раздела services"
    services = re.findall(r"^  ([a-z][A-Za-z0-9_-]*):\s*$", section.group(1), re.M)
    assert tuple(services) == COMPOSE_SERVICES, f"набор служб изменён: {services}"
    assert not re.search(r"messenger", compose, re.I), "docker-compose.yml знает о мессенджере"


def test_no_new_packages_and_no_slice_line_in_requirements():
    """NFR-707: в `requirements.txt` нет пакетов, добавленных срезом 008, и нет строки «Срез 008»: набор имён пакетов
    тот же, что после среза 007 (план, «Новые компоненты и лицензии»; CONTRACT-008, 1.2)."""
    text = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert not re.search(r"(?i)срез\s*008", text), "в requirements.txt есть строка среза 008"
    names = [re.split(r"[=<>~!\[; ]", line.strip(), 1)[0].lower() for line in text.splitlines()
             if line.strip() and not line.strip().startswith("#")]
    assert names == list(PRIOR_PACKAGES), f"набор пакетов изменён: {sorted(set(names) ^ set(PRIOR_PACKAGES))}"


# --- слой каналов и числа среза (CONTRACT-008, 1.2, 1.4) ------------------------------------------------------------

def test_channel_layers_keep_two_keys_with_default_30_and_publish_2_seconds():
    """NFR-701: `CHANNEL_LAYERS` — по-прежнему два ключа: `default` (соединения, `socket_timeout` 30) и `publish`
    (рассылка, `socket_timeout` 2), тот же адрес и префикс `crm-asgi`, `max_connections` 300,
    `socket_connect_timeout` 2; словарь срез не меняет (CONTRACT-008, 1.2)."""
    from django.conf import settings

    layers = settings.CHANNEL_LAYERS
    assert set(layers) == {"default", "publish"}, f"ключи CHANNEL_LAYERS: {sorted(layers)}"
    default, publish = layers["default"], layers["publish"]
    assert default["BACKEND"] == publish["BACKEND"] == "channels_redis.core.RedisChannelLayer"
    assert default["CONFIG"]["hosts"] == [{"address": settings.VALKEY_URL, "socket_timeout": 30,
                                           "max_connections": 300, "socket_connect_timeout": 2}]
    assert publish["CONFIG"]["hosts"] == [{"address": settings.VALKEY_URL, "socket_timeout": 2,
                                           "max_connections": 300, "socket_connect_timeout": 2}]
    assert default["CONFIG"]["prefix"] == publish["CONFIG"]["prefix"] == "crm-asgi"


def test_slice_numbers_nineteen_points_thirty_kinds_eight_purposes_and_order_61():
    """FR-649, FR-662, FR-668: числа среза — девятнадцать точек расширения (`unit_form_parts` последняя), тридцать
    видов уведомлений (два `messenger.*` с `order` 80 и 81), восемь значений `StoredFile.Purpose` (`instruction`
    последнее), порядок группы поиска «Мессенджер» 61 сразу после «Ленты» 60 (CONTRACT-008, 1.4)."""
    from apps.core import extensions
    from apps.core.models.files import StoredFile
    from apps.notify.services import kinds as notify_kinds

    assert len(extensions.POINTS) == 19, f"точек расширения {len(extensions.POINTS)}"
    assert tuple(extensions.POINTS[-1:]) == messenger.POINTS_008
    assert set(extensions._registry) == set(extensions.POINTS)
    purposes = tuple(StoredFile.Purpose.values)
    assert purposes == messenger.PURPOSES_008, f"назначения файлов: {purposes}"
    catalog = notify_kinds.catalog()
    assert len(catalog) == 30, f"видов уведомлений {len(catalog)}"
    orders = {kind.code: kind.order for kind in catalog}
    assert (orders.get("messenger.message"), orders.get("messenger.mention")) == (80, 81), orders
    providers = {provider.key: provider for func in extensions.registered("search_providers") for provider in func()}
    assert "messenger" in providers and "feed" in providers, f"провайдеры поиска: {sorted(providers)}"
    assert providers["feed"].order == 60 and providers["messenger"].order == 61, \
        f"порядок групп поиска: feed {providers['feed'].order}, messenger {providers['messenger'].order}"
    assert providers["messenger"].title == "Мессенджер"


@PLAIN
def test_admin_menu_has_16_items_with_messenger_second_and_settings_order_64():
    """FR-643, FR-667: у администратора портала шестнадцать пунктов меню; «Мессенджер» — второй (после «Ленты»,
    `order` 1), «Настройки мессенджера» — `/settings/messenger/` с `order` 64 под правом `settings.portal`;
    сотруднику без этого права настроек мессенджера не видно (CONTRACT-008, 1.4)."""
    from apps.core.services import permissions

    admin, _chat = _messenger_session()
    items = permissions.menu_for(admin.user)
    titles = [item["title"] for item in items]
    assert len(items) == 18, f"пунктов меню у администратора: {len(items)} — {titles}"
    assert titles[:3] == ["Лента", "Мессенджер", "Задачи"], f"первые пункты: {titles[:3]}"
    by_url = {item["url"]: item for item in items}
    assert by_url["/messenger/"]["order"] == 1
    assert by_url["/settings/messenger/"]["order"] == 64
    employee = messenger.make_user()
    employee_titles = [item["title"] for item in permissions.menu_for(employee.user)]
    assert "Мессенджер" in employee_titles, "пункт «Мессенджер» виден не каждому вошедшему"
    assert "Настройки мессенджера" not in employee_titles, "настройки мессенджера видны без settings.portal"


# --- CSP, шаблоны и статика (CONTRACT-008, 1.1) ---------------------------------------------------------------------

@PLAIN
def test_csp_without_unsafe_inline_on_messenger_pages():
    """FR-673, NFR-702: `/messenger/`, `/messenger/chats/<id>/`, `/messenger/notifications/`, `/settings/messenger/`
    отдают `Content-Security-Policy`: `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`,
    `connect-src 'self'`; новых директив срез не вводит (CONTRACT-008, 1.1)."""
    from django.conf import settings

    admin, chat = _messenger_session()
    known = {name.lower() for name in settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]}
    for path in messenger.messenger_pages(chat):
        policy = _csp(admin.client.get(path), path)
        assert policy.get("script-src") == ["'self'"], f"{path}: script-src {policy.get('script-src')}"
        assert policy.get("connect-src") == ["'self'"], f"{path}: connect-src {policy.get('connect-src')}"
        assert "'unsafe-inline'" not in policy.get("script-src", []), f"{path}: unsafe-inline в script-src"
        assert "'unsafe-eval'" not in policy.get("script-src", []), f"{path}: unsafe-eval в script-src"
        assert not set(policy) - known, f"{path}: новые директивы {set(policy) - known}"


def test_templates_have_no_style_or_event_attributes():
    """NFR-702: в `templates/messenger/` и иконке `icons/chat.html` нет `style=` и `on…=`; свои скрипты —
    внешние `static/messenger/messenger.js` (defer) и `messenger.css`, без `eval(` и `new Function`; шаблоны
    мессенджера подключают их через `_assets.html` (CONTRACT-008, 1.1)."""
    root = BACKEND_DIR / "templates" / "messenger"
    assert root.is_dir(), f"нет каталога шаблонов {root}"
    templates = sorted(root.rglob("*.html"))
    assert templates, "в templates/messenger нет шаблонов"
    icon = BACKEND_DIR / "templates" / "icons" / "chat.html"
    assert icon.is_file(), "нет иконки пункта меню templates/icons/chat.html"
    tags = {}
    for path in templates + [icon]:
        tags[path] = re.findall(r"<[A-Za-z][^<>]*>", path.read_text(encoding="utf-8"))
    bad_style = [str(path.relative_to(BACKEND_DIR)) for path, items in tags.items()
                 if any(re.search(r"\sstyle\s*=", tag, re.I) for tag in items)]
    assert not bad_style, f"атрибут style= в шаблонах: {bad_style}"
    bad_events = [str(path.relative_to(BACKEND_DIR)) for path, items in tags.items()
                  if any(re.search(r"\son[a-z]+\s*=", tag, re.I) for tag in items)]
    assert not bad_events, f"обработчики on…= в шаблонах: {bad_events}"

    for name in ("messenger.js", "messenger.css"):
        path = BACKEND_DIR / "static" / "messenger" / name
        assert path.is_file(), f"нет файла static/messenger/{name}"
        assert path.read_text(encoding="utf-8").strip(), f"{name}: пустой файл"
    script = (BACKEND_DIR / "static" / "messenger" / "messenger.js").read_text(encoding="utf-8")
    assert "eval(" not in script and "new Function" not in script, "messenger.js: eval или new Function"

    assets = "\n".join(path.read_text(encoding="utf-8") for path in
                       (BACKEND_DIR / "templates" / "_assets.html", BACKEND_DIR / "templates" / "base.html",
                        *templates))
    script_tag = re.compile(r"<script\b(?=[^>]*\bdefer\b)"
                            r"(?=[^>]*\bsrc=\"[^\"]*messenger/messenger[^\"/]*\.js[^\"]*\")[^>]*>")
    css_tag = re.compile(r"<link\b(?=[^>]*\brel=\"stylesheet\")"
                         r"(?=[^>]*\bhref=\"[^\"]*messenger/messenger[^\"/]*\.css[^\"]*\")[^>]*>")
    assert script_tag.search(assets), "нет подключения <script defer src=…messenger/messenger.js>"
    assert css_tag.search(assets), "нет подключения <link rel=\"stylesheet\" href=…messenger/messenger.css>"
    for source in templates:
        for tag in re.findall(r"<script\b[^>]*>", source.read_text(encoding="utf-8"), re.I):
            assert re.search(r"\bsrc\s*=", tag), f"{source.name}: встроенный скрипт без src: {tag}"


# --- язык и время (CONTRACT-008, 1.1, 12.1, 13.3) -------------------------------------------------------------------

@PLAIN
def test_texts_are_russian_and_time_is_moscow_at_utc_midnight(clock):
    """NFR-708: страницы среза по-русски («Мессенджер» на `/messenger/`, «Хранить сообщения, лет» на
    `/settings/messenger/`), английских надписей нет; часы на полночь UTC 10.03.2026 (в Москве 03:00) и на 21:30 UTC
    того же дня (в Москве 11.03.2026 00:30): время сообщения, превью списка и строки поиска — по Москве в
    `time[data-at]`, текст «ДД.ММ.ГГГГ ЧЧ:ММ» для `datetime`, времени UTC в видимом тексте нет (CONTRACT-008, 1.1)."""
    admin, chat = _messenger_session()
    cases = ((datetime(2026, 3, 10, 0, 0, tzinfo=dt_timezone.utc), "10.03.2026 03:00"),
             (datetime(2026, 3, 10, 21, 30, tzinfo=dt_timezone.utc), "11.03.2026 00:30"))
    for moment, shown in cases:
        assert messenger.moscow_text(moment) == shown
        clock.set(moment)
        # 21,5 часа между кругами — больше таймаута бездействия; сессия продолжается, проверяется время по Москве.
        session_key = admin.client.cookies[django_settings.SESSION_COOKIE_NAME].value
        support.model("core.UserSession").objects.filter(session_key=session_key).update(last_activity=moment)
        messenger.post(chat, admin, text="Кофемашина в переговорной", created_at=moment)
        for path in messenger.messenger_pages(chat):
            response = admin.client.get(path)
            assert response.status_code == 200, f"{path}: статус {response.status_code}"
            text = _visible(response.content.decode())
            assert len(re.findall("[а-яА-ЯёЁ]{3,}", text)) >= 3, f"{path}: русского текста нет"
            for word in ENGLISH_WORDS:
                assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text), \
                    f"{path}: английская надпись {word!r}"
        list_page = admin.client.get("/messenger/")
        assert list_page.status_code == 200, "список чатов не открылся"
        list_html = list_page.content.decode()
        assert "Мессенджер" in _visible(list_html), "на /messenger/ нет надписи «Мессенджер»"
        list_marks = _marks(list_html)
        assert list_marks, "в списке чатов нет time[data-at] с превью"
        assert shown in {text for _attrs, text in list_marks}, f"превью списка не по Москве: {list_marks}"
        chat_html = admin.client.get(f"/messenger/chats/{chat.pk}/")
        assert chat_html.status_code == 200, "беседа не открылась"
        marks = _marks(chat_html.content.decode())
        assert marks, "в беседе нет time[data-at]"
        for attrs, text in marks:
            iso = re.search(r'datetime="([^"]+)"', attrs)
            assert iso, "у time нет datetime"
            at = datetime.fromisoformat(iso.group(1).replace("Z", "+00:00"))
            assert text == messenger.moscow_text(at), f"время {text!r} при datetime {iso.group(1)}"
        assert shown in {text for _attrs, text in marks}, f"время сообщения не по Москве: {marks}"

    settings_page = admin.client.get("/settings/messenger/")
    assert settings_page.status_code == 200, "настройки мессенджера не открылись"
    assert "Хранить сообщения, лет" in _visible(settings_page.content.decode()), "нет надписи о сроке хранения"

    search_html = admin.client.get("/search/", {"q": "кофемашина"}).content.decode()
    group = re.search(r"data-search-group=\"messenger\"", search_html)
    assert group, "в выдаче поиска нет группы «Мессенджер»"
    window = _visible(search_html[group.start():group.start() + 4000])
    assert "00:30" in window, f"строка поиска не показывает время по Москве: {window[:400]}"
    assert "21:30" not in window, "строка поиска показывает время UTC"


# --- нагрузка (CONTRACT-008, 14.2) ----------------------------------------------------------------------------------

def test_load_profile_files_exist_with_three_classes():
    """NFR-707: `backend/tests/load/fill_messenger.py` есть: без `E2E_STAND=1` — `sys.exit` с текстом контракта до
    импорта моделей; `LOAD_CHATS=200`, `LOAD_MESSAGES=50000`; строка итога `fill_messenger: chats=… messages=…
    files=…`; в `locustfile.py` — три класса `FeedUser`, `NotifyUser` и `MessengerUser`, у мессенджера два соединения
    (`/ws/notify/`, `/ws/messenger/?chat=<id>`) и событие `WS messenger frame`; нагрузка не запускается."""
    load = BACKEND_DIR / "tests" / "load"
    script = load / "fill_messenger.py"
    assert script.is_file(), "нет backend/tests/load/fill_messenger.py"
    text = script.read_text(encoding="utf-8")
    assert "E2E_STAND" in text
    assert re.search(r"LOAD_CHATS.{0,40}200", text), "нет значения по умолчанию LOAD_CHATS=200"
    assert re.search(r"LOAD_MESSAGES.{0,40}50000", text), "нет значения по умолчанию LOAD_MESSAGES=50000"
    assert re.search(r"fill_messenger: chats=", text) and "messages=" in text and "files=" in text, \
        "нет строки итога `fill_messenger: chats=… messages=… files=…`"
    tree = ast.parse(text)
    guard = None
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.If) and "E2E_STAND" in ast.get_source_segment(text, node.test):
            guard = index
            break
    assert guard is not None, "нет проверки E2E_STAND на верхнем уровне"
    body = ast.get_source_segment(text, tree.body[guard])
    assert re.search(r"sys\.exit\(", body) and REFUSAL_LOAD in body, "нет sys.exit с текстом контракта 14.2"
    for node in tree.body[:guard]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            assert not [item for item in names if item.split(".")[0] in ("apps", "django")], \
                f"импорт {names} раньше проверки стенда"

    locust_text = (load / "locustfile.py").read_text(encoding="utf-8")
    classes = {node.name: node for node in ast.parse(locust_text).body if isinstance(node, ast.ClassDef)}
    for name in ("FeedUser", "NotifyUser", "MessengerUser"):
        assert name in classes, f"в locustfile.py нет класса {name}"
    segment = ast.get_source_segment(locust_text, classes["MessengerUser"])
    assert "wait_time" in segment
    assert "/ws/notify/" in segment and "/ws/messenger/?chat=" in segment, "MessengerUser держит не оба соединения"
    assert "WS messenger frame" in segment, "нет события `WS messenger frame`"
    assert "4000" in segment, "нет отправки сообщения в 4 000 знаков"


# --- границы импортов (план «Модуль и выключение»; CONTRACT-008, 1.1) ----------------------------------------------

def test_previous_modules_do_not_import_apps_messenger():
    """FR-643: ни один файл `apps/core`, `org`, `notify`, `knowledge`, `servicedesk`, `lists`, `search`, `feed`,
    `integrations` не импортирует `apps.messenger` (ни `import`, ни `from`, ни `import_module`/`__import__`);
    `config/urls.py` и `config/asgi.py` — вне проверки: им разрешено подключать модуль под `apps.is_installed`.
    Строка `apps.messenger.unit_form` в `org` — имя журнала из плана, а не импорт. Сам разбор находит нарушения на
    образцах."""
    def bad(name: str) -> bool:
        return _under(name, APP)

    samples = ("from apps.messenger.services import chats", "import apps.messenger", "from apps import messenger",
               "from ...messenger import tasks", "import importlib\nimportlib.import_module('apps.messenger.tasks')")
    clean = ('"""apps.messenger в докстринге"""\nimport os', "logging.getLogger('apps.messenger.unit_form')",
             "from apps.feed.services import text", "event = 'messenger.message'")
    package = ["apps", "core", "services"]
    for sample in samples:
        assert any(bad(name) for name in _targets(sample, package, with_strings=False)), \
            f"разбор не нашёл: {sample}"
    for sample in clean:
        assert not any(bad(name) for name in _targets(sample, package, with_strings=False)), \
            f"ложное срабатывание: {sample}"

    offenders = []
    for module in PREVIOUS_MODULES:
        root = BACKEND_DIR / "apps" / module
        files = sorted(root.rglob("*.py"))
        assert files, f"нет исходников в {root}"
        for path in files:
            rel = path.relative_to(BACKEND_DIR).with_suffix("")
            hits = sorted(name for name in _targets(path.read_text(encoding="utf-8"), list(rel.parts[:-1]),
                                                    with_strings=False) if bad(name))
            if hits:
                offenders.append(f"{path.relative_to(BACKEND_DIR)}: {hits}")
    assert offenders == [], f"прежний модуль импортирует мессенджер: {offenders}"