"""T-4130: развёртывание среза 004 — службы, очередь, расписание, слой каналов, ASGI, nginx, CSP, переменные окружения,
зависимости, лицензии, восстановление из копии, команда `notify_vapid_keys` (FR-301, FR-324, FR-333, FR-337, FR-338,
NFR-305, NFR-309). Сценарии — «Запуск», «Новые компоненты и лицензии», «Восстановление из копии» плана и § 1.3
контракта.

Читает файлы `deploy/` (служба `test` монтирует их в /app/deploy только для чтения), `backend/config/*.py`,
`backend/requirements*.txt` и `static/vendor/`, как test_sd_deploy.py и test_stack.py (образцы стиля): разбор compose —
по строкам, cron и настроек — деревом `ast`. Часть строк § 1.3 («есть») сделана на Этапе 1 — такие тесты проходят уже
сейчас. Ключи VAPID, которые печатает команда, тест не выводит: сообщения проверок — только `***`.
"""
import ast
import base64
import hashlib
import logging
import re
from importlib import metadata
from io import StringIO

import pytest
from django.core.management import call_command

from tests.support import BACKEND_DIR, repo_file

NOTIFY_SERVICES = ("worker-notify", "notify-poller")
PUSH_HOSTS = ["fcm.googleapis.com", "jmt17.google.com", "*.notify.windows.com", "updates.push.services.mozilla.com"]
OPEN_MARKERS = ("mit", "bsd", "apache", "lgpl", "unlicense", "psf", "python software", "hpnd", "isc", "0bsd", "mpl")


# --- помощники чтения файлов ---------------------------------------------------------------------------------------

def deploy_text(*parts: str) -> str:
    return repo_file("deploy", *parts).read_text(encoding="utf-8")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def compose_services() -> dict[str, str]:
    """Блоки служб docker-compose.yml: имя → текст (без комментариев)."""
    blocks, current, in_services = {}, None, False
    for line in uncommented(deploy_text("docker-compose.yml")).splitlines():
        if re.match(r"^services:\s*$", line):
            in_services = True
        elif re.match(r"^\S", line):
            in_services = False
        elif in_services and (m := re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)):
            current = m.group(1)
            blocks[current] = ""
        elif in_services and current:
            blocks[current] += line + "\n"
    return blocks


def block(name: str) -> str:
    services = compose_services()
    assert name in services, f"в docker-compose.yml нет службы {name}"
    return services[name]


def depends_on(service_block: str) -> dict[str, str]:
    result, in_section, current = {}, False, None
    for line in service_block.splitlines():
        if re.match(r"^    depends_on:\s*$", line):
            in_section = True
        elif in_section and re.match(r"^    \S", line):
            in_section = False
        elif in_section and (m := re.match(r"^      ([A-Za-z0-9_-]+):\s*$", line)):
            current = m.group(1)
            result[current] = ""
        elif in_section and current:
            result[current] += line + "\n"
    return result


def environment_of(service_block: str) -> dict[str, str]:
    """Раздел `environment` службы (словарная форма): имя → значение без кавычек."""
    result, in_section = {}, False
    for line in service_block.splitlines():
        if re.match(r"^    environment:\s*$", line):
            in_section = True
        elif in_section and re.match(r"^    \S", line):
            in_section = False
        elif in_section and (m := re.match(r"^      ([A-Za-z0-9_]+):\s*(.*?)\s*$", line)):
            result[m.group(1)] = m.group(2).strip("\"'")
    return result


def command_of(service_block: str) -> str:
    """Команда службы одной строкой (строка, `>-` или список) без кавычек и скобок."""
    lines = service_block.splitlines()
    for i, line in enumerate(lines):
        if m := re.match(r"^    command:\s*(.*)$", line):
            parts = [m.group(1)]
            for follow in lines[i + 1:]:
                if re.match(r"^      \S", follow) and not re.match(r"^    \S", follow):
                    parts.append(follow.strip())
                else:
                    break
            text = " ".join(parts)
            text = re.sub(r"^[>|][-+]?\s*", "", text)
            return re.sub(r"\s+", " ", re.sub(r"[\[\]\"',]", " ", text)).strip()
    return ""


def replicas_of(service_block: str) -> int | None:
    """`deploy.replicas` службы; нет ключа — `None`."""
    in_deploy = False
    for line in service_block.splitlines():
        if re.match(r"^    deploy:\s*$", line):
            in_deploy = True
        elif in_deploy and re.match(r"^    \S", line):
            in_deploy = False
        elif in_deploy and (m := re.match(r"^      replicas:\s*(\d+)\s*$", line)):
            return int(m.group(1))
    return None


def profiles_of(service_block: str) -> set[str] | None:
    """Профили службы (`profiles: ["dev", "test"]`); нет ключа — `None`."""
    m = re.search(r"^    profiles:\s*\[(.*)\]\s*$", service_block, re.M)
    if not m:
        return None
    return {p.strip().strip("\"'") for p in m.group(1).split(",") if p.strip()}


def cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в config/cron.py (разбор дерева): функция, полный путь функции (`target`: `apps.….имя` при
    любой записи импорта), очередь, cron, interval, имя, job_timeout."""
    tree = ast.parse((BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    constants = {node.targets[0].id: node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                 and isinstance(node.value, ast.Constant)}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    aliases = {}  # локальное имя → полный путь (`from a.b import c as d` → d: a.b.c; `import a.b as d` → d: a.b)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]

    def target(node):
        """Полный путь функции в `register(...)` при любой записи импорта: имя, `модуль.имя`, `a.b.c.имя`."""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.insert(0, node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        return ".".join([aliases.get(node.id, node.id), *parts])

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            first = node.args[0] if node.args else None
            function = first.id if isinstance(first, ast.Name) else getattr(first, "attr", None)
            options = {kw.arg: value(kw.value) for kw in node.keywords}
            found.append({"function": function, "target": target(first) if first is not None else None,
                          "queue": options.get("queue_name"), "cron": options.get("cron"),
                          "interval": options.get("interval"), "name": options.get("name"),
                          "job_timeout": options.get("job_timeout")})
    return found


def cron_by_name() -> dict[str, dict]:
    result = {}
    for item in cron_registrations():
        assert item["name"] not in result, f"задание {item['name']} зарегистрировано дважды"
        result[item["name"]] = item
    return result


def settings_env_calls() -> dict[str, dict]:
    """Присваивания `ИМЯ = env…("ИМЯ", default=…)` в config/settings.py: имя переменной окружения → способ и значение."""
    tree = ast.parse((BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            continue
        func = node.func
        base = func.value if isinstance(func, ast.Attribute) else func
        if not (isinstance(base, ast.Name) and base.id == "env"):
            continue
        try:
            options = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg == "default"}
        except ValueError:  # нелитеральный default (выражение) — вызов пропускается, остальные имена проверяются
            continue
        found[node.args[0].value] = {"method": func.attr if isinstance(func, ast.Attribute) else "str",
                                     "has_default": "default" in options, "default": options.get("default")}
    return found


def env_example_lines() -> tuple[dict[str, str], dict[str, str]]:
    """`deploy/.env.example`: действующие строки и закомментированные `# ИМЯ=значение` (имя → значение)."""
    active, commented = {}, {}
    for line in deploy_text(".env.example").splitlines():
        line = line.strip()
        if m := re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line):
            active[m.group(1)] = m.group(2)
        elif m := re.match(r"^#\s*([A-Z][A-Z0-9_]*)=(.*)$", line):
            commented[m.group(1)] = m.group(2)
    return active, commented


# --- службы worker-notify и notify-poller ---------------------------------------------------------------------------

def test_compose_has_worker_notify_on_queue_notify_with_two_replicas():
    """FR-333: `worker-notify` — `rq worker -c config.rq_settings … notify` (одна очередь `notify`), `deploy.replicas: 2`,
    без `container_name`, без тома `protected` (решение 24 задач; § 1.3)."""
    service = block("worker-notify")
    command = command_of(service)
    assert command.startswith("rq worker -c config.rq_settings"), f"команда: {command!r}"
    words = command.split()
    queues = [t for t in words[4:] if not t.startswith("-")]
    assert queues == ["notify"], f"очередь `notify` — единственная и последняя, найдено: {queues}"
    assert words[-1] == "notify", "команда оканчивается именем очереди"
    assert replicas_of(service) == 2, "две копии: зависшая отправка одной не держит остальные"
    assert "container_name" not in service, "у служб с несколькими копиями нет container_name"
    assert "protected" not in service, "том protected у worker-notify не подключается"


def test_compose_notify_services_follow_worker_pattern_env_file_restart_healthy_dependencies_no_profile():
    """FR-333: обе службы среза (`worker-notify`, `notify-poller`) — как `worker-inbox`: образ `crm-portal:local`,
    `env_file: .env`, `restart: unless-stopped`, `DATABASE_MIGRATE_URL: ""`, ожидают `web` и `valkey` в состоянии
    `service_healthy`, без `profiles` и `container_name` (PLAN-004, «Запуск»)."""
    for name in NOTIFY_SERVICES:
        service = block(name)
        assert re.search(r"^    image:\s*crm-portal:local\s*$", service, re.M), f"{name}: образ crm-portal:local"
        assert re.search(r"^    env_file:\s*\.env\s*$", service, re.M), f"{name}: env_file: .env"
        assert re.search(r"^    restart:\s*unless-stopped\s*$", service, re.M), f"{name}: restart: unless-stopped"
        environment = environment_of(service)
        assert "DATABASE_MIGRATE_URL" in environment and environment["DATABASE_MIGRATE_URL"] == "", (
            f"{name}: DATABASE_MIGRATE_URL: \"\" (рабочие процессы не получают права владельца схемы)")
        needs = depends_on(service)
        for dependency in ("web", "valkey"):
            assert dependency in needs, f"{name}: нет ожидания службы {dependency}"
            assert re.search(r"condition:\s*service_healthy", needs[dependency]), f"{name}: {dependency} — service_healthy"
        assert not re.search(r"^    profiles:", service, re.M), f"{name}: без профилей (входит в установку)"
        assert not re.search(r"^    container_name:", service, re.M), f"{name}: без container_name"


def test_compose_has_notify_poller_single_replica_with_notify_poll_command():
    """NFR-309: `notify-poller` запускает `python manage.py notify_poll` ровно в одной копии (ключа `deploy.replicas`
    нет или он равен 1): второй опрашивающий получил бы от Telegram 409 (§ 1.3)."""
    service = block("notify-poller")
    assert command_of(service) == "python manage.py notify_poll"
    assert replicas_of(service) in (None, 1), "ровно одна копия"
    assert not re.search(r"^    scale:", service, re.M), "ключа scale нет"


def test_compose_fakebots_only_in_dev_and_test_profiles():
    """NFR-309: учебная служба ботов `fakebots` — только профили `dev` и `test`, в установку не входит; описание
    службы по § 1.1, токенов ботов в compose нет; служба `test` ждёт её здоровья и смотрит на неё через
    `TELEGRAM_API_BASE` и `MAX_API_BASE`."""
    services = compose_services()
    fake = block("fakebots")
    assert profiles_of(fake) == {"dev", "test"}, "профили fakebots — ровно dev и test"
    assert re.search(r"^    image:\s*python:3\.12-slim-bookworm\s*$", fake, re.M)
    assert re.search(r"^    restart:\s*unless-stopped\s*$", fake, re.M)
    assert command_of(fake) == "python -u /srv/server.py"
    assert "./fakebots:/srv:ro" in fake
    assert re.search(r"127\.0\.0\.1:8099:8099", fake), "порт — только на 127.0.0.1"
    assert "/_test/health" in fake and re.search(r"interval:\s*5s", fake) and re.search(r"retries:\s*20", fake)
    for word in ("TOKEN", "token"):
        assert word not in fake, "токенов в описании fakebots нет"
    # от fakebots зависят только службы профилей dev/test: в установку учебная служба не втягивается
    for name, text in services.items():
        if "fakebots" in depends_on(text):
            assert profiles_of(text), f"{name}: служба установки зависит от fakebots"
            assert profiles_of(text) <= {"dev", "test"}, f"{name}: профили вне dev и test"
    tester = block("test")
    needs = depends_on(tester)
    assert "fakebots" in needs and re.search(r"condition:\s*service_healthy", needs["fakebots"])
    environment = environment_of(tester)
    assert environment.get("TELEGRAM_API_BASE") == "http://fakebots:8099"
    assert environment.get("MAX_API_BASE") == "http://fakebots:8099/max"
    assert not [name for name in environment if "TOKEN" in name], "токенов ботов в compose нет"


def test_bots_are_polled_no_webhook_route_or_inbound_port():
    """NFR-309: боты опрашиваются, а не присылают события: в `apps/notify/urls.py` и `config/urls.py` нет маршрута
    приёма событий ботов, у `worker-notify` и `notify-poller` нет `ports` (§ 1.3, «Входящий доступ ботов»)."""
    pattern = re.compile(r"webhook|hook|updates|\bbot\b", re.I)
    for path in (BACKEND_DIR / "apps" / "notify" / "urls.py", BACKEND_DIR / "config" / "urls.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("path", "re_path")
                    and node.args and isinstance(node.args[0], ast.Constant)):
                route = str(node.args[0].value)
                assert not pattern.search(route), f"{path.name}: маршрут {route!r} похож на приём событий ботов"
    for name in NOTIFY_SERVICES:
        assert not re.search(r"^    ports:", block(name), re.M), f"{name}: входящих портов нет"


# --- очередь, расписание --------------------------------------------------------------------------------------------

def test_rq_queues_include_notify():
    """FR-333: `RQ_QUEUES["notify"] == {"URL": VALKEY_URL, "DEFAULT_TIMEOUT": 120}`; очередь открывается через django_rq
    (§ 1.3, Этап 1)."""
    import django_rq
    from django.conf import settings

    assert settings.RQ_QUEUES["notify"] == {"URL": settings.VALKEY_URL, "DEFAULT_TIMEOUT": 120}
    assert django_rq.get_queue("notify").name == "notify"


def test_cron_notify_tick_interval_30_queue_notify_timeout_120():
    """FR-333: `config/cron.py` регистрирует `notify_tick` (функция `apps.notify.tasks.notify_tick`): очередь `notify`,
    `interval=30` без строки `cron`, `job_timeout=120`; всего в файле семнадцать вызовов `register` (§ 1.3, § 12.3; `purge_trash` среза 005 — семнадцатый)."""
    registrations = cron_registrations()
    assert len(registrations) == 17, f"вызовов register {len(registrations)}, ожидается 17 (14 прежних, 2 среза 004 и 1 среза 005)"
    item = cron_by_name().get("notify_tick")
    assert item, "нет задания notify_tick"
    assert item["target"] == "apps.notify.tasks.notify_tick", f"функция задания: {item['target']}"
    assert item["queue"] == "notify"
    assert item["interval"] == 30
    assert item["cron"] is None, "расписание — interval, строки cron нет"
    assert item["job_timeout"] == 120


def test_cron_notify_retention_at_23_40_utc_queue_maintenance_timeout_600():
    """FR-338: `notify_retention` (функция `apps.notify.tasks.notify_retention`): очередь `maintenance`,
    `cron="40 23 * * *"` по UTC (02:40 по Москве, после копии 01:30 и мимо заданий 003), `job_timeout=600`."""
    by_name = cron_by_name()
    item = by_name.get("notify_retention")
    assert item, "нет задания notify_retention"
    assert item["target"] == "apps.notify.tasks.notify_retention", f"функция задания: {item['target']}"
    assert item["queue"] == "maintenance"
    assert item["cron"] == "40 23 * * *"
    assert item["interval"] is None
    assert item["job_timeout"] == 600
    same_time = [name for name, other in by_name.items() if name != "notify_retention" and other["cron"] == "40 23 * * *"]
    assert not same_time, f"то же время у других заданий: {same_time}"


# --- настройки ------------------------------------------------------------------------------------------------------

def test_notify_is_last_in_installed_apps():
    """FR-301, CONTRACT-005 (решение 3): `apps.notify` стоит сразу после `apps.servicedesk`; за ним — `apps.knowledge`,
    затем `apps.search` — последний элемент `INSTALLED_APPS`. Имя теста прежнее (TASKS-004, T-4130)."""
    from django.conf import settings

    apps = list(settings.INSTALLED_APPS)
    assert apps[-4:] == ["apps.servicedesk", "apps.notify", "apps.knowledge", "apps.search"]


def test_asgi_has_protocol_type_router_origin_validator_and_session_auth():
    """NFR-305: `config/asgi.py` — `ProtocolTypeRouter` с ключами `http` и `websocket`;
    `websocket` — `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(notify.routing.websocket_urlpatterns)))`."""
    from channels.routing import ProtocolTypeRouter
    from channels.security.websocket import OriginValidator

    import config.asgi as asgi

    assert isinstance(asgi.application, ProtocolTypeRouter)
    assert set(asgi.application.application_mapping) == {"http", "websocket"}
    assert isinstance(asgi.application.application_mapping["websocket"], OriginValidator), (
        "проверка Origin по ALLOWED_HOSTS — первое звено соединения")
    source = re.sub(r"\s+", "", (BACKEND_DIR / "config" / "asgi.py").read_text(encoding="utf-8"))
    assert re.search(r"AllowedHostsOriginValidator\(AuthMiddlewareStack\(URLRouter\((?:[\w.]+\.)?websocket_urlpatterns\)\)\)",
                     source), "websocket: AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(…websocket_urlpatterns)))"
    assert '"http":django_asgi_app' in source


def test_channel_layers_use_valkey_with_socket_timeout_30_max_connections_300_connect_timeout_2_and_prefix():
    """NFR-305: `CHANNEL_LAYERS` — `channels_redis.core.RedisChannelLayer` на `VALKEY_URL` (в тестах база 15) с
    `socket_timeout` 30, `max_connections` 300, `socket_connect_timeout` 2 и префиксом `crm-asgi` (F1 Ф4)."""
    from django.conf import settings

    assert settings.VALKEY_URL.endswith("/15"), "в тестах слой каналов — база 15"
    assert settings.CHANNEL_LAYERS == {"default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [{"address": settings.VALKEY_URL, "socket_timeout": 30, "max_connections": 300,
                              "socket_connect_timeout": 2}],
                   "prefix": "crm-asgi"},
    }}


# --- nginx и CSP ----------------------------------------------------------------------------------------------------

def location_body(text: str, header: str) -> str:
    """Тело `location <header> { … }` (header — регулярное выражение между `location` и `{`)."""
    m = re.search(r"location\s+" + header + r"\s*\{", text)
    assert m, f"нет location {header}"
    depth, i = 1, m.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1]


def directives(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in body.split(";") if part.strip()]


def _check_ws_location(name: str) -> None:
    text = uncommented(deploy_text(name))
    own = directives(location_body(text, r"/ws/"))
    main = directives(location_body(text, r"/"))
    for wanted in ("proxy_http_version 1.1", "proxy_read_timeout 3600s", "proxy_send_timeout 3600s", "proxy_buffering off"):
        assert wanted in own, f"{name}: в location /ws/ нет `{wanted};`"
    assert any(d.startswith("proxy_pass ") for d in own), f"{name}: нет proxy_pass"
    assert any(re.fullmatch(r"proxy_set_header Upgrade \$http_upgrade", d) for d in own), f"{name}: нет заголовка Upgrade"
    assert any(re.fullmatch(r"proxy_set_header Connection \$\w+", d) for d in own), f"{name}: нет заголовка Connection"
    inherited = {d for d in main if d.startswith(("proxy_pass ", "proxy_http_version ", "proxy_set_header "))}
    assert inherited <= set(own), f"{name}: не повторены директивы location /: {sorted(inherited - set(own))}"


def test_dev_nginx_has_location_ws_with_upgrade_timeouts_3600_and_buffering_off():
    """NFR-305: `deploy/nginx.conf` — `location /ws/` с повторёнными директивами прокси из `location /` (они не
    наследуются): `proxy_pass`, `proxy_http_version 1.1`, `Upgrade`, `Connection`, `proxy_set_header`;
    `proxy_read_timeout 3600s`, `proxy_send_timeout 3600s`, `proxy_buffering off`."""
    _check_ws_location("nginx.conf")


def test_prod_nginx_has_location_ws_with_upgrade_timeouts_3600_and_buffering_off():
    """NFR-305: то же в `deploy/nginx.prod.conf`."""
    _check_ws_location("nginx.prod.conf")


@pytest.mark.django_db
def test_csp_has_worker_src_self():
    """NFR-305: политика CSP получает `worker-src 'self'` (сервис-воркер), `connect-src 'self'` остаётся; заголовок
    ответа содержит обе директивы."""
    from django.conf import settings

    from tests import support

    directives_map = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]
    assert directives_map.get("worker-src") == ["'self'"]
    assert directives_map.get("connect-src") == ["'self'"]
    header = support.make_client().get("/login/").get("Content-Security-Policy", "")
    assert re.search(r"(^|;\s*)worker-src 'self'(;|$)", header), "в заголовке нет `worker-src 'self'`"
    assert re.search(r"(^|;\s*)connect-src 'self'(;|$)", header), "в заголовке нет `connect-src 'self'`"


# --- переменные окружения -------------------------------------------------------------------------------------------

def test_settings_declare_bot_and_vapid_variables_with_empty_defaults():
    """FR-337: `config/settings.py` читает через `django-environ` `TELEGRAM_BOT_TOKEN`, `MAX_BOT_TOKEN`,
    `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` с пустым значением по умолчанию («пусто — канал
    выключен»)."""
    calls = settings_env_calls()
    for name in ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT"):
        assert name in calls, f"settings.py не читает {name}"
        assert calls[name]["has_default"] and calls[name]["default"] == "", f"{name}: значение по умолчанию — пустая строка"
        assert calls[name]["method"] == "str", f"{name}: строка"


def test_settings_api_base_and_webpush_hosts_have_documented_defaults():
    """FR-337: `TELEGRAM_API_BASE` по умолчанию `https://api.telegram.org`, `MAX_API_BASE` —
    `https://platform-api2.max.ru`, `WEBPUSH_ALLOWED_HOSTS` читается как список (`env.list`) с заданным
    значением по умолчанию."""
    calls = settings_env_calls()
    assert calls["TELEGRAM_API_BASE"]["default"] == "https://api.telegram.org"
    assert calls["MAX_API_BASE"]["default"] == "https://platform-api2.max.ru"
    assert calls["TELEGRAM_API_BASE"]["method"] == "str" and calls["MAX_API_BASE"]["method"] == "str"
    hosts = calls["WEBPUSH_ALLOWED_HOSTS"]
    assert hosts["method"] == "list", "WEBPUSH_ALLOWED_HOSTS — список"
    assert hosts["has_default"] and isinstance(hosts["default"], list) and hosts["default"]


def test_webpush_allowed_hosts_default_is_four_checked_push_services():
    """FR-324: список разрешённых хостов Web Push по умолчанию — четыре проверенные службы: `fcm.googleapis.com`,
    `jmt17.google.com`, `*.notify.windows.com`, `updates.push.services.mozilla.com`."""
    default = settings_env_calls()["WEBPUSH_ALLOWED_HOSTS"]["default"]
    assert len(default) == 4 and sorted(default) == sorted(PUSH_HOSTS), f"найдено: {default}"


def test_env_example_lists_new_variables_with_secrets_empty():
    """FR-337: в `deploy/.env.example` три секрета (`TELEGRAM_BOT_TOKEN`, `MAX_BOT_TOKEN`, `VAPID_PRIVATE_KEY`) — действующие
    строки `ИМЯ=` с пустым значением (заглушка `***` сошла бы за «ключ задан»); остальные пять — закомментированные
    строки `# ИМЯ=значение`, действующих строк с ними нет."""
    active, commented = env_example_lines()
    for name in ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "VAPID_PRIVATE_KEY"):
        assert name in active, f"нет действующей строки {name}="
        assert active[name] == "", f"{name}: значение должно быть пустым"
    for name in ("VAPID_PUBLIC_KEY", "VAPID_SUBJECT", "TELEGRAM_API_BASE", "MAX_API_BASE", "WEBPUSH_ALLOWED_HOSTS"):
        assert name in commented, f"нет строки `# {name}=…`"
        assert name not in active, f"{name} не должна быть действующей"


def test_secret_variables_are_in_secrets_list_of_stack_test():
    """FR-337: `SECRET_ENV_NAMES` в `tests/test_stack.py` дополнен тремя секретами среза (`TELEGRAM_BOT_TOKEN`,
    `MAX_BOT_TOKEN`, `VAPID_PRIVATE_KEY`); прежние восемь остались."""
    tree = ast.parse((BACKEND_DIR / "tests" / "test_stack.py").read_text(encoding="utf-8"))
    names = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "SECRET_ENV_NAMES"):
            names = ast.literal_eval(node.value)
    assert names is not None, "в test_stack.py нет SECRET_ENV_NAMES"
    for name in ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "VAPID_PRIVATE_KEY"):
        assert name in names, f"{name} не в списке секретов"
    for name in ("DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEYS", "BACKUP_CODE_PEPPER", "POSTGRES_PASSWORD",
                 "CRM_OWNER_PASSWORD", "CRM_APP_PASSWORD", "SMTP_PASSWORD", "IMAP_PASSWORD"):
        assert name in names, f"прежний секрет {name} пропал из списка"


# --- зависимости и лицензии -----------------------------------------------------------------------------------------

def _pins(file: str) -> set[str]:
    lines = (BACKEND_DIR / file).read_text(encoding="utf-8").splitlines()
    return {line.split("#", 1)[0].strip() for line in lines if line.split("#", 1)[0].strip()}


def test_requirements_pin_new_dependencies_to_exact_versions():
    """NFR-305: `requirements.txt` закрепляет `channels==4.3.2`, `channels-redis==4.3.0`, `websockets==17.2`,
    `msgpack==1.2.3`, `asgiref==3.12.1`; `redis==8.1.0` остаётся."""
    pins = _pins("requirements.txt")
    for pin in ("channels==4.3.2", "channels-redis==4.3.0", "websockets==17.2", "msgpack==1.2.3", "asgiref==3.12.1",
                "redis==8.1.0"):
        assert pin in pins, f"нет строки {pin}"


def test_requirements_dev_pin_websocket_client():
    """NFR-305: `requirements-dev.txt` закрепляет `websocket-client==1.9.2` (только разработка и нагрузка), в
    `requirements.txt` его нет."""
    assert "websocket-client==1.9.2" in _pins("requirements-dev.txt")
    assert not [pin for pin in _pins("requirements.txt") if pin.startswith("websocket-client")]


def test_new_dependencies_have_open_licenses_in_components_table():
    """NFR-305: «таблица компонентов» (решение E19) — установленные `channels`, `channels-redis`, `msgpack`, `asgiref`,
    `websockets`, `websocket-client` имеют открытую лицензию (те же признаки, что у test_stack); файл
    `static/vendor/LICENSE-htmx-ext-ws` — 0BSD; в `static/vendor/VERSIONS.md` есть запись `htmx-ext-ws` с sha256
    файла."""
    for name in ("channels", "channels-redis", "msgpack", "asgiref", "websockets", "websocket-client"):
        meta = metadata.metadata(name)
        declared = " ".join([meta.get("License-Expression", ""), meta.get("License", "")[:300]]).lower()
        classifiers = " ".join(c for c in meta.get_all("Classifier", []) if c.startswith("License")).lower()
        text = declared if declared.strip() else classifiers
        assert any(re.search(rf"(?<![a-z]){re.escape(marker)}" + (r"(?![a-z])" if len(marker) <= 3 else ""), text)
                   for marker in OPEN_MARKERS), f"{name}: открытая лицензия не опознана ({text[:80]!r})"
        assert "proprietary" not in text and "commercial" not in text, f"{name}: платная лицензия"
    vendor = BACKEND_DIR / "static" / "vendor"
    licence = (vendor / "LICENSE-htmx-ext-ws").read_text(encoding="utf-8")
    assert "Zero Clause" in licence and "Permission to use, copy, modify, and/or distribute" in licence, "ожидается 0BSD"
    versions = (vendor / "VERSIONS.md").read_text(encoding="utf-8")
    assert "htmx-ext-ws" in versions and "0BSD" in versions
    digest = hashlib.sha256((vendor / "htmx-ext-ws-2.0.4.min.js").read_bytes()).hexdigest()
    assert digest in versions, "в VERSIONS.md нет sha256 файла htmx-ext-ws-2.0.4.min.js"


# --- восстановление из копии ----------------------------------------------------------------------------------------

def test_restore_guide_names_worker_notify_and_notify_poller_in_stop_and_start_steps():
    """FR-333: в `deploy/RESTORE.md` в шаге остановки (до `pg_restore`) и в шаге запуска (после
    `servicedesk_after_restore`) названы `worker-notify` и `notify-poller`."""
    text = deploy_text("RESTORE.md")
    stop = re.search(r"(?<!\w)[Оо]станов", text)
    assert stop, "нет шага остановки служб"
    after_stop = text[stop.start():]
    restore = after_stop.find("pg_restore --clean --if-exists")
    assert restore > 0, "нет `pg_restore --clean --if-exists` после остановки"
    stopped = after_stop[:restore]
    after_script = after_stop.find("servicedesk_after_restore")
    assert after_script > restore, "нет `servicedesk_after_restore` после восстановления базы"
    start = re.search(r"[Зз]апуст", after_stop[after_script:])
    assert start, "нет шага запуска служб"
    started = after_stop[after_script + start.start():]
    for service in NOTIFY_SERVICES:
        pattern = rf"(?<![\w-]){re.escape(service)}(?![\w-])"
        assert re.search(pattern, stopped), f"шаг остановки: нет службы {service}"
        assert re.search(pattern, started), f"шаг запуска: нет службы {service}"


# --- команда notify_vapid_keys --------------------------------------------------------------------------------------

BASE64URL_43 = re.compile(r"[A-Za-z0-9_-]{43}")
BASE64URL_87 = re.compile(r"[A-Za-z0-9_-]{87}")


def _run_vapid() -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("notify_vapid_keys", stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@pytest.mark.django_db
def test_vapid_keys_command_prints_pair_for_env():
    """FR-337: `notify_vapid_keys` печатает ровно две строки с переводом строки — `VAPID_PRIVATE_KEY=<base64url, 32
    байта, 43 знака>` и `VAPID_PUBLIC_KEY=<base64url, 65 байт, 87 знаков, первый байт 0x04>`; открытый ключ вычислен
    из закрытого; `stderr` пуст; каждый запуск — новая пара. Значения тест не выводит."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    output, errors = _run_vapid()
    lines = output.split("\n")
    two_lines = len(lines) == 3 and lines[2] == ""
    assert two_lines, "ровно две строки, каждая с переводом строки (***)"
    named = lines[0].startswith("VAPID_PRIVATE_KEY=") and lines[1].startswith("VAPID_PUBLIC_KEY=")
    assert named, "порядок строк: закрытый, затем открытый (***)"
    private, public = lines[0].split("=", 1)[1], lines[1].split("=", 1)[1]
    shaped = bool(BASE64URL_43.fullmatch(private)) and bool(BASE64URL_87.fullmatch(public))
    assert shaped, "формы значений: base64url без дополнения, 43 и 87 знаков (***)"
    private_raw, public_raw = _decode(private), _decode(public)
    sizes = len(private_raw) == 32 and len(public_raw) == 65 and public_raw[0] == 4
    assert sizes, "размеры: 32 байта и 65 байт с первым байтом 0x04 (***)"
    derived = ec.derive_private_key(int.from_bytes(private_raw, "big"), ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    pair_matches = derived == public_raw
    assert pair_matches, "открытый ключ не вычисляется из закрытого (***)"
    assert errors == "", "stderr пуст"
    second, _ = _run_vapid()
    fresh = second.split("\n")[0] != lines[0] and second.split("\n")[1] != lines[1]
    assert fresh, "каждый запуск — новая пара (***)"


@pytest.mark.django_db
def test_vapid_keys_command_writes_nothing_to_journal_or_database(django_assert_num_queries, caplog):
    """FR-337: `notify_vapid_keys` не читает и не пишет базу (0 запросов), не добавляет событий журнала, не меняет
    `NotifySettings` и не пишет значения в журнал приложения (логгеры)."""
    from tests.support import model

    audit, notify_settings = model("core.AuditEvent"), model("notify.NotifySettings")
    audit_before = audit.objects.count()
    settings_before = list(notify_settings.objects.values())
    caplog.set_level(logging.DEBUG)
    with django_assert_num_queries(0):
        output, _ = _run_vapid()
    assert audit.objects.count() == audit_before, "в журнале событий появилась запись"
    assert list(notify_settings.objects.values()) == settings_before, "NotifySettings изменена"
    values = [line.split("=", 1)[1] for line in output.split("\n") if "=" in line]
    leaked = any(value in record.getMessage() for record in caplog.records for value in values)
    assert not leaked, "значение ключа попало в журнал приложения (***)"
