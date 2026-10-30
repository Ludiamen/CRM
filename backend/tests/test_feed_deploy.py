"""T-7135: развёртывание среза 007 — приложение, расписание, адреса, nginx, слой каналов, том файлов, зависимости, CSP,
шаблоны и скрипты, язык и время, нагрузка, индекс показов, словарь текстов (FR-618, FR-633, FR-638, FR-641, FR-642,
NFR-604, NFR-605, NFR-610, NFR-611, NFR-612, NFR-613, NFR-614).
Сценарии плана «Запуск», «Новые компоненты и лицензии», «Безопасный вывод, язык, узкий экран», «Нагрузка»,
«Проверка», «Модуль и выключение».

Контракт: CONTRACT-007 — 1.1 (приложение, статика, шаблоны, CSP, язык и время), 1.2 (cron, адреса, nginx, слой каналов,
том файлов, зависимости, индекс `Shown(post_id)`, решение 60), 13.1–13.2 (тексты, ответ на В1, раздел 16.4), 14.3
(нагрузка), 5.9 (`feed_pages`). Записи `config/cron.py` и `config/urls.py` разбираются через `ast` (решение 52 задач:
модуль `config.cron` вызывает `django.setup()` при импорте, его не импортируем). Правило «полночь UTC» применено для
показа времени (03:00 против 00:00). Код среза импортируется внутри тестов.
"""
import ast
import re
import string
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest

from tests import support
from tests import support_feed as feed
from tests.support import BACKEND_DIR, repo_file

PLAIN = pytest.mark.django_db

NGINX_FILES = ("nginx.conf", "nginx.prod.conf")
FEED_FILES_PATTERN = "^/feed/files/$"
ENGLISH_WORDS = ("Save", "Delete", "Cancel", "Search", "Submit", "Edit", "Back")
REFUSAL_LOAD = "Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
PROTO = {"nginx.conf": "$scheme", "nginx.prod.conf": "$portal_proto"}

# прежние восемнадцать записей `config/cron.py`: имя -> ("cron", строка) или ("interval", секунды)
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
}

# имена пакетов `requirements.txt` после среза 006 (пакетов среза 007 нет)
PREVIOUS_PACKAGES = (
    "django", "psycopg", "psycopg-pool", "django-rq", "rq", "django-environ", "django-otp", "cryptography", "qrcode",
    "argon2-cffi", "ua-parser", "django-csp", "gunicorn", "uvicorn", "uvicorn-worker", "pillow", "openpyxl",
    "et-xmlfile", "defusedxml", "redis", "channels", "channels-redis", "websockets", "msgpack", "asgiref",
    "markdown-it-py", "mdurl", "nh3")

NGINX_PROTECTED = ["/protected/attachments/", "/protected/inbound/", "/protected/"]
COMPOSE_VOLUMES = ["postgres-data", "valkey-data", "clamav-db", "test-venv", "media", "protected", "backups"]


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


def feed_files_locations(name: str) -> list[tuple[str, str]]:
    """Все `location` с `client_max_body_size 25m` файла nginx: (шаблон адреса, тело)."""
    text = uncommented(deploy_text(name))
    found = []
    for header in re.findall(r"location\s+([^{]+?)\s*\{", text):
        body = location_body(text, re.escape(header))
        if "client_max_body_size 25m" in directives(body):
            found.append((header.split(None, 1)[-1], body))
    return found


def tickets_location_body(name: str) -> str:
    return location_body(uncommented(deploy_text(name)), re.escape(r"~ ^/tickets/(new/|[0-9]+/reply/)$"))


def cron_source() -> str:
    return (BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")


def _guarded_by_feed(node, parents) -> bool:
    """Узел лежит внутри `if apps.is_installed("apps.feed"):` (проверка условия — по тексту без пробелов и кавычек)."""
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.If):
            test = ast.unparse(current.test).replace("'", '"').replace(" ", "")
            if re.fullmatch(r"(\w+\.)*is_installed\(\"apps\.feed\"\)", test):
                return True
        current = parents.get(current)
    return False


def cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в config/cron.py (разбор дерева): полный путь функции, очередь, cron, интервал, имя,
    job_timeout, строка, признак «под проверкой apps.feed»."""
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
                          "guarded": _guarded_by_feed(node, parents)})
    return found


def by_name() -> dict[str, dict]:
    return {item["name"]: item for item in cron_registrations()}


# --- приложение и расписание ------------------------------------------------------------------------------------------

def test_feed_is_last_in_installed_apps_after_search():
    """FR-641: в конце `INSTALLED_APPS` — `apps.servicedesk`, `apps.notify`, `apps.knowledge`, `apps.lists`,
    `apps.search`, `apps.feed`; метка `feed`, класс `FeedConfig`, `verbose_name` «Лента» (раздел 1.1)."""
    from django.apps import apps
    from django.conf import settings

    assert list(settings.INSTALLED_APPS)[-6:] == feed.APPS_TAIL
    assert list(settings.INSTALLED_APPS)[-1] == "apps.feed"
    config = apps.get_app_config("feed")
    assert type(config).__name__ == "FeedConfig"
    assert config.label == "feed"
    assert config.verbose_name == "Лента"


def test_feed_reminders_cron_entry_runs_remind_events_every_minute_in_notify_with_timeout_120():
    """FR-618: запись `feed_reminders`: `apps.feed.tasks.remind_events`, очередь `notify`, `cron="* * * * *"`,
    `job_timeout=120` (раздел 1.2)."""
    function, queue, interval, cron, timeout = feed.FEED_JOBS["feed_reminders"]
    assert (function, queue, interval, cron, timeout) == ("remind_events", "notify", None, "* * * * *", 120)
    item = by_name().get("feed_reminders")
    assert item, "нет задания feed_reminders"
    assert item["target"] == "apps.feed.tasks.remind_events", f"функция задания: {item['target']}"
    assert item["queue"] == "notify"
    assert item["cron"] == "* * * * *" and item["interval"] is None
    assert item["job_timeout"] == 120


def test_feed_retention_cron_entry_runs_retention_night_at_23_35_in_maintenance_with_timeout_600():
    """FR-638: запись `feed_retention`: `apps.feed.tasks.retention_night`, очередь `maintenance`, `cron="35 23 * * *"`,
    `job_timeout=600` (раздел 1.2)."""
    function, queue, interval, cron, timeout = feed.FEED_JOBS["feed_retention"]
    assert (function, queue, interval, cron, timeout) == ("retention_night", "maintenance", None, "35 23 * * *", 600)
    item = by_name().get("feed_retention")
    assert item, "нет задания feed_retention"
    assert item["target"] == "apps.feed.tasks.retention_night", f"функция задания: {item['target']}"
    assert item["queue"] == "maintenance"
    assert item["cron"] == "35 23 * * *" and item["interval"] is None
    assert item["job_timeout"] == 600


def test_feed_cron_entries_are_under_is_installed_guard():
    """FR-641: обе записи `feed_*` и импорт `from apps.feed.tasks import remind_events, retention_night` лежат внутри
    `if apps.is_installed("apps.feed"):`; прежние записи вне этой проверки (решение 52 задач, разбор `ast`)."""
    entries = cron_registrations()
    own = [item for item in entries if item["name"] in ("feed_reminders", "feed_retention")]
    assert len(own) == 2, "нет обеих записей feed_*"
    assert all(item["guarded"] for item in own), "запись feed_* вне проверки apps.is_installed"
    assert not [item["name"] for item in entries if item["name"] not in ("feed_reminders", "feed_retention")
                and item["guarded"]], "прежняя запись оказалась под проверкой apps.feed"
    tree = ast.parse(cron_source())
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == "apps.feed.tasks"]
    assert imports, "в cron.py нет `from apps.feed.tasks import …`"
    assert all(_guarded_by_feed(node, parents) for node in imports), "импорт apps.feed.tasks вне проверки"
    names = {alias.name for node in imports for alias in node.names}
    assert names == {"remind_events", "retention_night"}, f"импортируются {sorted(names)}"
    top_level = [node for node in tree.body if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps.feed")]
    assert not top_level, "импорт apps.feed на верхнем уровне cron.py"


def test_cron_has_no_other_entry_at_23_35():
    """FR-638: минута 35 часа 23 занята только `feed_retention` (в любой очереди; раздел 1.2)."""
    entries = cron_registrations()
    assert "feed_retention" in {item["name"] for item in entries}, "нет задания feed_retention"
    same_time = [item["name"] for item in entries if item["name"] != "feed_retention" and item["cron"] == "35 23 * * *"]
    assert not same_time, f"то же время у других заданий: {same_time}"
    own = [item for item in entries if item["name"] == "feed_retention"]
    assert len(own) == 1 and own[0]["cron"] == "35 23 * * *" and own[0]["queue"] == "maintenance"


def test_cron_module_has_twenty_register_calls():
    """FR-618, FR-638: в `config/cron.py` двадцать вызовов `register` (восемнадцать прежних, `feed_reminders` и
    `feed_retention`)."""
    entries = cron_registrations()
    assert len(entries) == 20, f"вызовов register {len(entries)}, ожидается 20 (18 прежних и две записи ленты)"
    assert {"feed_reminders", "feed_retention"} <= {item["name"] for item in entries}


def test_previous_eighteen_cron_entries_keep_names_and_minutes():
    """FR-641: прежние восемнадцать записей — те же имена и те же минуты (у `notify_tick` — интервал 30 с)."""
    entries = by_name()
    missing = sorted(set(PREVIOUS_CRON) - set(entries))
    assert not missing, f"пропали записи: {missing}"
    for name, (kind, expected) in PREVIOUS_CRON.items():
        item = entries[name]
        if kind == "interval":
            assert item["interval"] == expected and item["cron"] is None, f"{name}: интервал {item['interval']}"
        else:
            assert item["cron"] == expected and item["interval"] is None, f"{name}: cron {item['cron']!r}"
    assert len(entries) - len(PREVIOUS_CRON) == 2, "кроме прежних должны быть ровно две записи"


def test_feed_urls_are_included_under_is_installed_guard():
    """FR-641: в `config/urls.py` подключение `include("apps.feed.urls")` стоит внутри
    `if apps.is_installed("apps.feed"):` и нигде больше; прочие подключения не под этой проверкой (решение 52 задач)."""
    path = BACKEND_DIR / "config" / "urls.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    includes = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "include"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)]
    feed_calls = [node for node in includes if node.args[0].value == "apps.feed.urls"]
    assert len(feed_calls) == 1, f"подключений apps.feed.urls: {len(feed_calls)}"
    assert _guarded_by_feed(feed_calls[0], parents), "include(apps.feed.urls) вне проверки apps.is_installed"
    others = [node.args[0].value for node in includes if node.args[0].value != "apps.feed.urls"
              and _guarded_by_feed(node, parents)]
    assert not others, f"под проверкой apps.feed подключено лишнее: {others}"
    assert len(includes) >= 8, "прежние подключения адресов исчезли"


# --- nginx ------------------------------------------------------------------------------------------------------------

def _check_feed_files_location(name):
    """Общая проверка для двух файлов: ровно один `location` с 25m — шаблон `^/feed/files/$` (загрузка одного файла);
    адреса записей и файлов под него не подпадают; общий предел 6m не менялся; с 55m — прежние четыре (раздел 1.2)."""
    found = feed_files_locations(name)
    assert len(found) == 1, f"{name}: location с client_max_body_size 25m — {len(found)}, нужен один"
    pattern, body = found[0]
    assert pattern == FEED_FILES_PATTERN, f"{name}: шаблон {pattern!r}"
    assert re.search(pattern, "/feed/files/")
    for other in ("/feed/files/5/", "/feed/12/", "/feed/12/files/", "/feed/", "/feed/files/5/delete/"):
        assert not re.search(pattern, other), f"{name}: {other} попал под шаблон загрузки"
    top = uncommented(deploy_text(name))
    assert re.search(r"^\s{4}client_max_body_size 6m;", top, re.M), f"{name}: общий предел 6m изменён"
    assert len(re.findall(r"client_max_body_size\s+25m;", top)) == 1, f"{name}: location с 25m должно быть один"


def test_nginx_dev_config_has_feed_files_location_with_25m_limit():
    """FR-633, NFR-604: `deploy/nginx.conf` — `location ~ ^/feed/files/$` с `client_max_body_size 25m;`."""
    _check_feed_files_location("nginx.conf")


def test_nginx_prod_config_has_feed_files_location_with_25m_limit():
    """FR-633, NFR-604: то же в `deploy/nginx.prod.conf`."""
    _check_feed_files_location("nginx.prod.conf")


def test_feed_files_location_repeats_proxy_directives_in_both_configs():
    """FR-633, NFR-604: в новом `location` повторены директивы `proxy_*` (из `location /` они не наследуются):
    `proxy_pass http://portal_web`, `proxy_http_version 1.1`, `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`
    (`$scheme` в dev, `$portal_proto` в prod), `Upgrade`, `Connection`; набор имён директив совпадает с блоком
    `tickets` того же файла (раздел 1.2)."""
    for name in NGINX_FILES:
        found = feed_files_locations(name)
        assert len(found) == 1, f"{name}: нет location загрузки файла ленты"
        own = directives(found[0][1])
        for wanted in ("proxy_pass http://portal_web", "proxy_http_version 1.1", "proxy_set_header Host $http_host",
                       "proxy_set_header X-Forwarded-For $remote_addr",
                       f"proxy_set_header X-Forwarded-Proto {PROTO[name]}",
                       "proxy_set_header Upgrade $http_upgrade",
                       "proxy_set_header Connection $connection_upgrade"):
            assert wanted in own, f"{name}: в location файлов ленты нет `{wanted};`"

        def names(items):
            return {" ".join(item.split()[:2]) if item.startswith("proxy_set_header") else item.split()[0]
                    for item in items}

        assert names(own) == names(directives(tickets_location_body(name))), f"{name}: набор директив не как у tickets"


def test_nginx_previous_four_55m_locations_and_common_6m_limit_unchanged():
    """FR-633, FR-641: прежние четыре `location` с `client_max_body_size 55m` — `= /request/`, tickets, `kb`, `lists` —
    на месте, других с 55m нет; общий предел 6m не менялся."""
    expected = ["= /request/", r"~ ^/tickets/(new/|[0-9]+/reply/)$", "~ ^/kb/[0-9]+/files/$",
                "~ ^/lists/[0-9]+/[0-9]+/files/$"]
    for name in NGINX_FILES:
        text = uncommented(deploy_text(name))
        with55 = [header for header in location_headers(name)
                  if "client_max_body_size 55m" in directives(location_body(text, re.escape(header)))]
        assert with55 == expected, f"{name}: location с 55m: {with55}"
        assert len(re.findall(r"client_max_body_size\s+55m;", text)) == 4, f"{name}: число 55m"
        assert re.search(r"^\s{4}client_max_body_size 6m;", text, re.M), f"{name}: общий предел 6m изменён"


def test_nginx_ws_location_unchanged_in_both_configs():
    """FR-641: `location /ws/` не менялся — он префиксный и уже покрывает `/ws/feed/`: те же директивы, что до среза,
    время чтения и записи — час, без буферизации (`$scheme` в dev, `$portal_proto` в prod)."""
    for name in NGINX_FILES:
        text = uncommented(deploy_text(name))
        assert [h for h in location_headers(name) if "ws" in h] == ["/ws/"], f"{name}: location для WebSocket изменились"
        assert directives(location_body(text, "/ws/")) == [
            "proxy_pass http://portal_web", "proxy_http_version 1.1", "proxy_set_header Host $http_host",
            "proxy_set_header X-Forwarded-For $remote_addr", f"proxy_set_header X-Forwarded-Proto {PROTO[name]}",
            "proxy_set_header Upgrade $http_upgrade", "proxy_set_header Connection $connection_upgrade",
            "proxy_read_timeout 3600s", "proxy_send_timeout 3600s", "proxy_buffering off"], f"{name}: /ws/ изменён"
        assert "/ws/feed/" not in text, f"{name}: для /ws/feed/ не нужен свой location"


# --- том protected, зависимости, слой каналов --------------------------------------------------------------------------

@PLAIN
def test_feed_files_and_thumbs_live_in_protected_volume_and_backup_script_unchanged(protected_root):
    """NFR-613: оригинал файла ленты — под `PROTECTED_ROOT` (`incoming/` или `attachments/`), эскиз —
    `attachments/thumbs/<id StoredFile>.jpg`; новых томов и внутренних `location` nginx нет; `backup/backup.sh` и
    `RESTORE.md` слова `feed` не содержат (раздел 1.2)."""
    from apps.core.services import files as core_files

    row = feed.attach(None, write=True, thumb=True, status="clean")
    stored = row.file
    assert stored.purpose == "feed"
    path = core_files.attachment_path(stored)
    assert path.parent.parent == protected_root and path.parent.name in ("incoming", "attachments")
    assert path.is_file()
    thumb = protected_root / row.thumb
    assert row.thumb == f"attachments/thumbs/{stored.pk}.jpg" and thumb.is_file()
    assert thumb.parent == protected_root / "attachments" / "thumbs"
    for name in NGINX_FILES:
        internal = re.findall(r"location\s+(\S+)\s*\{", uncommented(deploy_text(name)))
        assert [item for item in internal if item.startswith("/protected/")] == NGINX_PROTECTED, \
            f"{name}: набор внутренних location изменён"
    compose = uncommented(deploy_text("docker-compose.yml")) + "\n"
    volumes = re.search(r"^volumes:\s*\n((?:  \S.*\n)+)", compose, re.M)
    assert volumes
    assert re.findall(r"^  ([A-Za-z0-9_-]+):", volumes.group(1), re.M) == COMPOSE_VOLUMES
    for name in (("backup", "backup.sh"), ("RESTORE.md",)):
        assert not re.search(r"(?i)\bfeed\b", deploy_text(*name)), f"{'/'.join(name)}: упоминание ленты"


def test_no_new_packages_and_no_slice_007_line_in_requirements():
    """FR-641: в `requirements.txt` нет пакетов, добавленных срезом 007, и нет строки «Срез 007»: набор имён пакетов тот
    же, что после среза 006 (план, «Новые компоненты и лицензии»)."""
    text = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    assert not re.search(r"(?i)срез\s*007", text), "в requirements.txt есть строка среза 007"
    names = [re.split(r"[=<>~!\[; ]", line.strip(), 1)[0].lower() for line in text.splitlines()
             if line.strip() and not line.strip().startswith("#")]
    assert names == list(PREVIOUS_PACKAGES), f"набор пакетов изменён: {sorted(set(names) ^ set(PREVIOUS_PACKAGES))}"


def test_channel_layers_publish_key_has_same_address_and_prefix_with_2s_timeouts():
    """FR-641, NFR-614: `CHANNEL_LAYERS` — два ключа; `default` прежний (таймаут чтения 30 с); `publish` — тот же адрес и
    префикс `crm-asgi`, `socket_timeout` и `socket_connect_timeout` по 2 с, `max_connections` 300 (раздел 1.2)."""
    from django.conf import settings

    layers = settings.CHANNEL_LAYERS
    assert set(layers) == {"default", "publish"}
    default, publish = layers["default"], layers["publish"]
    assert default["BACKEND"] == publish["BACKEND"] == "channels_redis.core.RedisChannelLayer"
    assert default["CONFIG"]["hosts"] == [{"address": settings.VALKEY_URL, "socket_timeout": 30,
                                           "max_connections": 300, "socket_connect_timeout": 2}]
    assert publish["CONFIG"]["hosts"] == [{"address": settings.VALKEY_URL, "socket_timeout": 2,
                                           "max_connections": 300, "socket_connect_timeout": 2}]
    assert default["CONFIG"]["prefix"] == publish["CONFIG"]["prefix"] == "crm-asgi"
    assert publish["CONFIG"]["hosts"][0]["address"] == default["CONFIG"]["hosts"][0]["address"]


# --- CSP --------------------------------------------------------------------------------------------------------------

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


def _viewer_and_post():
    """Сотрудник с правом настройки портала (видит `/settings/feed/`) и его запись для всех (его же правка)."""
    user = support.make_with_permissions("settings.portal", "feed.post_all")
    post = feed.make_post(user, to=("all",), text="Проба страницы")
    return user, post, support.logged_in(user)


@PLAIN
def test_home_and_feed_pages_send_csp_without_unsafe_inline_in_script_src():
    """NFR-605: `/`, `/feed/<id>/`, `/settings/feed/` отдают `Content-Security-Policy`: `script-src 'self'` без
    `'unsafe-inline'` и `'unsafe-eval'`, `connect-src 'self'`; новых директив срез не вводит (раздел 1.1)."""
    from django.conf import settings

    _user, post, client = _viewer_and_post()
    known = {name.lower() for name in settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]}
    for path in ("/", f"/feed/{post.pk}/", "/settings/feed/"):
        policy = _csp(client.get(path), path)
        assert policy.get("script-src") == ["'self'"], f"{path}: script-src {policy.get('script-src')}"
        assert policy.get("connect-src") == ["'self'"], f"{path}: connect-src {policy.get('connect-src')}"
        assert "'unsafe-inline'" not in policy.get("script-src", []) and "'unsafe-eval'" not in policy.get("script-src", [])
        assert not set(policy) - known, f"{path}: новые директивы {set(policy) - known}"


# --- шаблоны и скрипты ------------------------------------------------------------------------------------------------

def _template_files() -> list:
    root = BACKEND_DIR / "templates" / "feed"
    assert root.is_dir(), f"нет каталога шаблонов {root}"
    found = sorted(root.rglob("*.html"))
    assert found, "в templates/feed нет шаблонов"
    notices = BACKEND_DIR / "templates" / "_home_notices.html"
    assert notices.is_file(), "нет общего фрагмента templates/_home_notices.html"
    return found + [notices]


def _tags(text: str) -> list[str]:
    return re.findall(r"<[A-Za-z][^<>]*>", text)


def test_feed_templates_have_no_style_attribute():
    """NFR-605: в `templates/feed/` и `_home_notices.html` нет атрибута `style=`; шаблоны на месте (раздел 1.1)."""
    files = _template_files()
    bad = [str(path.relative_to(BACKEND_DIR)) for path in files
           if any(re.search(r"\sstyle\s*=", tag, re.I) for tag in _tags(path.read_text(encoding="utf-8")))]
    assert not bad, f"атрибут style= в шаблонах: {bad}"


def test_feed_templates_have_no_inline_event_handlers():
    """NFR-605: в `templates/feed/` и `_home_notices.html` нет атрибутов обработчиков `on…=`."""
    files = _template_files()
    bad = [str(path.relative_to(BACKEND_DIR)) for path in files
           if any(re.search(r"\son[a-z]+\s*=", tag, re.I) for tag in _tags(path.read_text(encoding="utf-8")))]
    assert not bad, f"обработчики on…= в шаблонах: {bad}"


def _visible(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@PLAIN
def test_feed_scripts_are_external_files_in_static_feed():
    """NFR-605: `static/feed/feed.js` и `feed.css` — внешние файлы без `eval(` и `new Function`; шаблоны страниц ленты
    подключают их тегами `<script defer src=…>` и `<link rel="stylesheet">`; встроенных скриптов в шаблонах нет;
    `_assets.html` файлов среза не подключает (решение 34 задач; раздел 1.1)."""
    for name in ("feed.js", "feed.css"):
        path = BACKEND_DIR / "static" / "feed" / name
        assert path.is_file(), f"нет файла static/feed/{name}"
        assert path.read_text(encoding="utf-8").strip(), f"{name}: пустой файл"
    script = (BACKEND_DIR / "static" / "feed" / "feed.js").read_text(encoding="utf-8")
    assert "eval(" not in script and "new Function" not in script, "feed.js: eval или new Function"
    assets = (BACKEND_DIR / "templates" / "_assets.html").read_text(encoding="utf-8")
    assert "static/feed" not in assets and "feed/feed." not in assets, "_assets.html подключает файлы среза"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in _template_files())
    for tag in re.findall(r"<script\b[^>]*>", sources, re.I):
        assert re.search(r"\bsrc\s*=", tag), f"встроенный скрипт без src в шаблонах: {tag}"
    assert re.search(r"<script\b(?=[^>]*\bdefer\b)(?=[^>]*\bsrc=\"[^\"]*feed/feed[^\"/]*\.js[^\"]*\")[^>]*>", sources), \
        "в шаблонах нет <script defer src=…feed/feed.js>"
    assert re.search(r"<link\b(?=[^>]*\brel=\"stylesheet\")(?=[^>]*\bhref=\"[^\"]*feed/feed[^\"/]*\.css[^\"]*\")[^>]*>",
                     sources), "в шаблонах нет <link rel=\"stylesheet\" href=…feed/feed.css>"
    _user, post, client = _viewer_and_post()
    for path in ("/", f"/feed/{post.pk}/", "/settings/feed/"):
        html = client.get(path).content.decode()
        assert re.search(r"<script\b(?=[^>]*\bdefer\b)[^>]*\bsrc=\"[^\"]*feed/feed[^\"/]*\.js\"", html), \
            f"{path}: страница не подключает feed.js"
        assert re.search(r"<link\b[^>]*\bhref=\"[^\"]*feed/feed[^\"/]*\.css\"", html), f"{path}: нет feed.css"


# --- язык и время -----------------------------------------------------------------------------------------------------

@PLAIN
def test_feed_pages_texts_are_russian():
    """NFR-611: страницы ленты по-русски: надписи интерфейса на месте, английских надписей нет; страницы —
    `support_feed.feed_pages(post)` (раздел 1.1, 13.3)."""
    _user, post, client = _viewer_and_post()
    labels = {"/": ("Лента", "Опубликовать"), "/settings/feed/": ("Хранить записи ленты, лет",)}
    paths = feed.feed_pages(post)
    assert set(labels) <= set(paths), "страницы с надписями не входят в feed_pages"
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        text = _visible(response.content.decode())
        assert len(re.findall("[а-яА-ЯёЁ]{3,}", text)) >= 3, f"{path}: русского текста нет"
        for label in labels.get(path, ()):
            assert label in text, f"{path}: нет надписи «{label}»"
        for word in ENGLISH_WORDS:
            assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text), \
                f"{path}: английская надпись {word!r}"


def _marks(html: str) -> list[tuple[str, str]]:
    return [(attrs, re.sub(r"\s+", " ", text).strip())
            for attrs, text in re.findall(r"<time\b([^>]*\bdata-at\b[^>]*)>(.*?)</time>", html, re.S)]


@PLAIN
def test_feed_times_are_shown_in_moscow_at_utc_midnight_for_post_event_and_edited_mark(clock):
    """NFR-611: часы на полночь UTC 10.03.2026 (в Москве — 03:00) и на 21:30 UTC того же дня (в Москве уже 11.03.2026
    00:30): время публикации, начало события и отметка «изменено» показаны по Москве в `time[data-at]` (текст —
    «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве для момента из атрибута `datetime`); время в UTC в разметке не встречается."""
    cases = ((datetime(2026, 3, 10, 0, 0, tzinfo=dt_timezone.utc), "10.03.2026 03:00", "10.03.2026 00:00"),
             (datetime(2026, 3, 10, 21, 30, tzinfo=dt_timezone.utc), "11.03.2026 00:30", "10.03.2026 21:30"))
    for moment, shown, utc_text in cases:
        assert feed.moscow_text(moment) == shown
        clock.set(moment)
        author = support.make_employee()
        reader = feed.as_plain()
        post = feed.make_post(author, to=("all",), published_at=moment, edited_at=moment, text="Запись со временем")
        event = feed.make_event(author, start=moment, end=moment + timedelta(hours=1), to=("all",),
                                title="Событие со временем", edited_at=moment)
        for target, texts in ((post, {shown}), (event, {shown})):
            path = f"/feed/{target.pk}/"
            response = reader.client.get(path)
            assert response.status_code == 200, f"{path}: статус {response.status_code}"
            html = response.content.decode()
            marks = _marks(html)
            assert len(marks) >= 2, f"{path}: time[data-at] — {len(marks)}, ожидается не меньше 2"
            for attrs, text in marks:
                iso = re.search(r'datetime="([^"]+)"', attrs)
                assert iso, f"{path}: у time нет datetime"
                at = datetime.fromisoformat(iso.group(1).replace("Z", "+00:00"))
                assert text == feed.moscow_text(at), f"{path}: время {text!r} при datetime {iso.group(1)}"
            shown_texts = {text for _attrs, text in marks}
            assert texts <= shown_texts, f"{path}: нет времени {sorted(texts - shown_texts)}"
            assert utc_text not in html, f"{path}: время в UTC {utc_text!r}"
        home = _marks(reader.client.get("/").content.decode())
        assert home and shown in {text for _attrs, text in home}, "на главной время публикации не по Москве"


# --- нагрузка ---------------------------------------------------------------------------------------------------------

def test_load_suite_has_fill_feed_script_requiring_stand_flag_and_feed_user_class():
    """NFR-612: `backend/tests/load/fill_feed.py` есть: без `E2E_STAND=1` — `sys.exit` с текстом контракта до
    импорта моделей; пределы `LOAD_POSTS=50000`, `LOAD_COMMENTS=200000`; строка итога `fill_feed: posts=… comments=…
    likes=…`; в `locustfile.py` есть класс `FeedUser` с `wait_time` и двумя соединениями (`/ws/notify/`, `/ws/feed/`);
    нагрузка не запускается (раздел 14.3)."""
    load = BACKEND_DIR / "tests" / "load"
    script = load / "fill_feed.py"
    assert script.is_file(), "нет backend/tests/load/fill_feed.py"
    text = script.read_text(encoding="utf-8")
    assert "E2E_STAND" in text
    assert "fill_feed: posts=" in text and "comments=" in text and "likes=" in text
    assert re.search(r"LOAD_POSTS.{0,40}50000", text) and re.search(r"LOAD_COMMENTS.{0,40}200000", text), \
        "нет значений по умолчанию LOAD_POSTS=50000 и LOAD_COMMENTS=200000"
    tree = ast.parse(text)
    guard = None
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.If) and "E2E_STAND" in ast.get_source_segment(text, node.test):
            guard = index
            break
    assert guard is not None, "нет проверки E2E_STAND на верхнем уровне"
    body = ast.get_source_segment(text, tree.body[guard])
    assert re.search(r"sys\.exit\(", body) and REFUSAL_LOAD in body, "нет sys.exit с текстом контракта 14.3"
    for node in tree.body[:guard]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            assert not [item for item in names if item.split(".")[0] in ("apps", "django")], \
                f"импорт {names} раньше проверки стенда"
    locust_text = (load / "locustfile.py").read_text(encoding="utf-8")
    classes = {node.name: node for node in ast.parse(locust_text).body if isinstance(node, ast.ClassDef)}
    assert "FeedUser" in classes, "в locustfile.py нет класса FeedUser"
    segment = ast.get_source_segment(locust_text, classes["FeedUser"])
    assert "wait_time" in segment
    assert "/ws/notify/" in segment and "/ws/feed/" in segment, "FeedUser держит не оба соединения"


# --- индекс показов (решение 60) -------------------------------------------------------------------------------------

@PLAIN
def test_shown_post_has_index_so_commit_fk_check_skips_full_scan():
    """FR-638, NFR-610 (решение 60, ответ владельца 2026-10-30): у таблицы `feed_shown` есть индекс, первый столбец которого
    — `post_id`: при фиксации пачки ночного задания база ищет ссылки на удалённую запись по индексу, а не просмотром
    таблицы показов целиком (раздел 1.2). Индекс (`user_id`, `post_id`) уникальности не считается."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s", ["feed_shown"])
        rows = cursor.fetchall()
    assert rows, "таблицы feed_shown нет или у неё нет индексов"
    firsts = {}
    for name, definition in rows:
        found = re.search(r"USING\s+\w+\s*\(\s*\"?(\w+)\"?", definition)
        assert found, f"не разобран индекс {definition}"
        firsts[name] = found.group(1)
    assert "post_id" in firsts.values(), f"нет индекса с первым столбцом post_id: {firsts}"


# --- словарь текстов (решение 19 задач, ответ Opus на В1, раздел 16.4) -------------------------------------------------

# Дословно из CONTRACT-007, разделы 13.1–13.2 (обычный пробел U+0020 в числах); `{limit}` — подстановка `str.format`.
TEXTS_13_1 = {
    "empty_text": "Напишите текст",
    "too_long": "Предел: {limit} знаков",
    "no_recipients": "Выберите, кому адресована запись",
    "recipient_invalid": "Выберите, кому адресована запись",
    "too_many_recipients": "Не больше 50 адресатов",
    "too_many_mentions": "Не больше 20 упоминаний",
    "event_title_required": "Укажите название события",
    "event_place_required": "Укажите место события",
    "event_end_before_start": "Конец должен быть позже начала",
    "event_start_passed": "Начало уже прошло",
    "event_started": "Событие началось: время и место не меняются",
    "term_too_far": "Срок — не позже чем через год",
    "date_passed": "Дата уже прошла",
    "answers_closed": "Ответы закрыты: событие началось",
    "post_files_limit": "У записи уже 10 файлов",
    "comment_files_limit": "У комментария уже 3 файла",
    "file_too_big": "Файл больше 20 МБ",
    "file_type": "Файл такого типа не принимается",
    "file_pending": "Файл ещё проверяется",
    "file_quarantine": "Файл в карантине",
    "retention_range": "Срок хранения — от 1 до 10 лет",
    "post_all_denied": "Писать всем вам не разрешено",
    "only_add_recipients": "Адресатов можно только добавить",
    "too_many_unbound": "Слишком много файлов без записи: опубликуйте запись или уберите лишние",
}
TEXTS_13_2 = {
    "event_time_required": "Укажите начало и конец события",
    "file_missing": "Файл не найден",
    "read_author": "Автор не отмечает свою запись прочитанной",
    "read_expired": "Срок важного уже истёк",
}
PROBE_NAMES = ("limit",)
PROBE = {name: f"‹{name}›" for name in PROBE_NAMES}


@PLAIN
def test_feed_texts_dictionary_contains_every_key_and_text_of_contract_13_1_and_13_2():
    """FR-642: словарь `apps.feed.texts.TEXTS` содержит каждый код и дословный текст таблиц 13.1–13.2 контракта;
    тексты с подстановками сверяются после `str.format` с одинаковыми пробными значениями (решение 19 задач; ответ
    Opus на В1, CONTRACT-007, 16.4)."""
    from apps.feed.texts import TEXTS

    expected = {**TEXTS_13_1, **TEXTS_13_2}
    assert len(expected) == len(TEXTS_13_1) + len(TEXTS_13_2) == 28, "коды таблиц повторяются или их не 28"
    problems = []
    for code, literal in expected.items():
        if code not in TEXTS:
            problems.append(f"{code}: нет ключа в TEXTS")
            continue
        raw = str(TEXTS[code])
        names = {item[1] for item in string.Formatter().parse(raw) if item[1]}
        unknown = names - set(PROBE_NAMES)
        if unknown:
            problems.append(f"{code}: неожиданные подстановки {sorted(unknown)}")
            continue
        shown, wanted = raw.format(**PROBE), literal.format(**PROBE)
        if shown != wanted:
            problems.append(f"{code}: {shown!r} вместо {wanted!r}")
    assert not problems, "тексты словаря расходятся с контрактом:\n" + "\n".join(problems)
