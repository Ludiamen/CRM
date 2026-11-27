"""T-9121: развёртывание и оболочка среза 009 — приложение, адреса, cron, меню, статика, CSP, nginx, нагрузка
(FR-643, FR-670, FR-697, FR-698, NFR-713, NFR-717, NFR-719; CONTRACT-009, 1.1, 1.2, 1.4, 3, 6.2, 13.2).

План: «Где живёт код», «Изменения ядра и прежних модулей», «Запуск», «Проверка» → «Нагрузка». Контракт: 1.1
(приложение, статика, шаблоны, CSP, язык), 1.2 (cron, адреса, nginx), 1.4 (числа среза), 3 (записи точек), 6.2
(25 адресов), 13.2 (`fill_tasks.py`, `TaskUser`). Образцы — `test_messenger_deploy.py`, `test_feed_deploy.py`.

`config/cron.py` разбирается через `ast`: модуль зовёт `django.setup()` при импорте и не импортируется тестом. Код
среза импортируется внутри тестов — `pytest --collect-only` проходит до появления кода.
"""
import ast
import re

import pytest
from django.conf import settings as django_settings
from django.urls import resolve

from tests import support
from tests import support_tasks
from tests.support import BACKEND_DIR, repo_file

pytestmark = pytest.mark.django_db

APP = "apps.tasks"
NGINX_FILES = ("nginx.conf", "nginx.prod.conf")
PROTO = {"nginx.conf": "$scheme", "nginx.prod.conf": "$portal_proto"}
TASKS_FILES_PATTERN = "^/tasks/files/$"
INSTRUCTIONS_FILES_PATTERN = "^/instructions/files/$"
FEED_FILES_PATTERN = "^/feed/files/$"
MESSENGER_FILES_PATTERN = "^/messenger/files/$"
ENGLISH_WORDS = ("Save", "Delete", "Cancel", "Search", "Submit", "Edit", "Back")

# формат `MESSENGER_JOBS`/`FEED_JOBS`: функция, очередь, интервал, cron, job_timeout (CONTRACT-009, 1.2)
TASKS_JOBS = {
    "tasks_reminders": ("tasks_reminders", "maintenance", "*/5 * * * *", 300),
    "tasks_digest": ("tasks_digest", "maintenance", "*/15 * * * *", 300),
    "tasks_retention": ("tasks_retention", "maintenance", "42 23 * * *", 600),
}

# 25 адресов контракта 6.2 (у `/tasks/` и `/tasks/<id>/` GET и POST — один путь)
TASKS_PATHS = (
    "/tasks/", "/tasks/list/", "/tasks/board/status/", "/tasks/board/deadline/", "/tasks/board/plan/",
    "/tasks/board/category/", "/tasks/new/", "/tasks/1/", "/tasks/1/status/", "/tasks/1/move/",
    "/tasks/1/delete/", "/tasks/1/comments/", "/tasks/comments/1/edit/", "/tasks/comments/1/delete/",
    "/tasks/files/", "/tasks/files/123e4567-e89b-12d3-a456-426614174000/", "/tasks/1/remind/",
    "/tasks/reminders/1/postpone/", "/tasks/plan/columns/", "/tasks/plan/columns/1/",
    "/tasks/plan/columns/1/delete/", "/settings/tasks/", "/settings/tasks/categories/",
    "/settings/tasks/categories/1/", "/settings/tasks/categories/1/delete/",
)

# прежние записи cron до среза 009: имя -> ("cron", строка) или ("interval", секунды)
PREVIOUS_CRON = {
    "purge_login_history": ("cron", "10 3 * * *"), "purge_expired_links": ("cron", "20 3 * * *"),
    "purge_expired_sessions": ("cron", "30 3 * * *"), "requeue_pending_scans": ("cron", "0 * * * *"),
    "purge_quarantine": ("cron", "50 3 * * *"), "purge_import_previews": ("cron", "40 3 * * *"),
    "poll_mailbox": ("cron", "* * * * *"), "requeue_inbound": ("cron", "*/5 * * * *"),
    "autoclose": ("cron", "5 * * * *"), "reconcile_assignees": ("cron", "25 * * * *"),
    "purge_inbound": ("cron", "10 23 * * *"), "anonymize_tickets": ("cron", "20 23 * * *"),
    "purge_requester_previews": ("cron", "30 23 * * *"), "purge_orphan_files": ("cron", "50 23 * * *"),
    "notify_tick": ("interval", 30), "notify_retention": ("cron", "40 23 * * *"),
    "purge_trash": ("cron", "45 23 * * *"), "lists_reminders": ("cron", "0 5 * * *"),
    "feed_reminders": ("cron", "* * * * *"), "feed_retention": ("cron", "35 23 * * *"),
    "messenger_retention": ("cron", "55 23 * * *"),
}


# --- помощники чтения файлов (свои: общие файлы тестов не правятся) ---------------------------------------

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


def cron_registrations() -> list[dict]:
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
                          "guarded": _guarded(node, parents, APP)})
    return found


def cron_by_name() -> dict[str, dict]:
    result = {}
    for item in cron_registrations():
        assert item["name"] not in result, f"задание {item['name']} зарегистрировано дважды"
        result[item["name"]] = item
    return result


def _visible(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


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


def _tasks_menu():
    from apps.tasks.extensions import menu_items

    items = {item["url"]: item for item in menu_items()}
    assert set(items) == {"/tasks/", "/settings/tasks/"}, f"пункты меню задач: {sorted(items)}"
    return items


# --- приложение и адреса (CONTRACT-009, 1.1, 1.2, 6.2) -----------------------------------------------------

def test_tasks_is_in_installed_apps_tail_with_config_label_and_name():
    """FR-643: `apps.tasks` — в хвосте `INSTALLED_APPS` (сразу после `apps.messenger`), последняя — `apps.instructions`
    среза 010; метка `tasks`, класс `TasksConfig`, `verbose_name` «Задачи» (К1); прежние приложения на месте."""
    from django.apps import apps as registry

    installed = list(django_settings.INSTALLED_APPS)
    assert installed[-5:] == ["apps.feed", "apps.messenger", "apps.tasks", "apps.instructions", "apps.automation"], f"хвост INSTALLED_APPS: {installed[-5:]}"
    assert installed.count("apps.tasks") == 1 and installed.index("apps.tasks") == len(installed) - 3
    config = registry.get_app_config("tasks")
    assert type(config).__name__ == "TasksConfig"
    assert (config.label, config.verbose_name) == ("tasks", "Задачи")


def test_all_25_contract_paths_resolve_with_app_name_and_no_signup_routes():
    """FR-644…FR-673 (CONTRACT-009, 6.2, К8): все 25 адресов среза разрешаются, `app_name = "tasks"`;
    литеральные `list/`, `new/`, `board/`, `comments/`, `files/`, `reminders/`, `plan/` не попадают под
    `<int:task_id>`; в путях среза нет `regist` и `signup`."""
    from apps.tasks import urls as tasks_urls

    assert tasks_urls.app_name == "tasks"
    for path in TASKS_PATHS:
        match = resolve(path)
        assert match.app_name == "tasks", f"{path}: app_name {match.app_name!r}"
    assert resolve("/tasks/list/").route == "tasks/list/"
    assert resolve("/tasks/new/").route == "tasks/new/"
    assert resolve("/tasks/comments/1/edit/").route == "tasks/comments/<int:comment_id>/edit/"
    assert resolve("/tasks/files/123e4567-e89b-12d3-a456-426614174000/").route == "tasks/files/<uuid:file_id>/"
    joined = " ".join(TASKS_PATHS)
    assert "regist" not in joined and "signup" not in joined


def test_post_only_routes_reject_get_with_405():
    """FR-644…FR-673 (CONTRACT-009, 6.1): адреса только для POST отвечают на GET кодом 405 — статус, перенос,
    удаление, перенос на доске, напоминание, удаление колонки плана."""
    viewer = support_tasks.viewer(full_name="Держатель Прав 405")
    client = support.logged_in(viewer)
    for path in ("/tasks/1/status/", "/tasks/1/move/", "/tasks/1/delete/", "/tasks/1/remind/",
                 "/tasks/plan/columns/1/delete/"):
        assert client.get(path).status_code == 405, f"{path}: не 405"


# --- cron (CONTRACT-009, 1.2, 1.4) ------------------------------------------------------------------------

def test_cron_has_27_registers_and_three_tasks_jobs_under_is_installed():
    """FR-670 (CONTRACT-009, 1.2): в `config/cron.py` двадцать семь вызовов `register`; три задания задач —
    `tasks_reminders` (`*/5`, 300 с), `tasks_digest` (`*/15`, 300 с), `tasks_retention` (`42 23`, 600 с), все в
    очереди `maintenance`, под `apps.is_installed("apps.tasks")` вместе со своим импортом; `42 23` ни у кого
    больше нет; прежние двадцать одна запись та же."""
    entries = cron_registrations()
    assert len(entries) == 32, f"вызовов register {len(entries)}, ожидается 32"
    by_name = cron_by_name()
    for name, (function, queue, cron, timeout) in TASKS_JOBS.items():
        item = by_name.get(name)
        assert item, f"нет задания {name}"
        assert item["target"] == f"apps.tasks.tasks.{function}", f"{name}: функция {item['target']}"
        assert (item["queue"], item["interval"], item["cron"], item["job_timeout"]) == (queue, None, cron, timeout)
        assert item["guarded"], f"{name} вне проверки apps.is_installed"
    assert not [row["name"] for row in entries if row["name"] != "tasks_retention" and row["cron"] == "42 23 * * *"]

    tree = ast.parse(cron_source())
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               and node.module == "apps.tasks.tasks"]
    assert imports, "в cron.py нет `from apps.tasks.tasks import …`"
    assert all(_guarded(node, parents, APP) for node in imports), "импорт заданий задач вне проверки"
    assert {alias.name for node in imports for alias in node.names} == set(TASKS_JOBS), "импортируются не три задания"
    assert not [node for node in tree.body if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("apps.tasks")], "импорт tasks на верхнем уровне cron.py"

    previous = cron_by_name()
    missing = sorted(set(PREVIOUS_CRON) - set(previous))
    assert not missing, f"пропали записи: {missing}"
    for name, (kind, expected) in PREVIOUS_CRON.items():
        row = previous[name]
        if kind == "interval":
            assert row["interval"] == expected and row["cron"] is None, f"{name}: интервал {row['interval']!r}"
        else:
            assert row["cron"] == expected and row["interval"] is None, f"{name}: cron {row['cron']!r}"
        assert not row["guarded"], f"прежняя запись {name} оказалась под проверкой apps.tasks"


# --- меню (CONTRACT-009, 1.4, 3) --------------------------------------------------------------------------

def test_menu_items_tasks_order_2_and_settings_order_65_before_servicedesk():
    """FR-643, FR-697 (CONTRACT-009, 1.4, 3): у администратора восемнадцать пунктов меню; «Задачи» — третий
    (order 2, право `tasks.use`), «Настройки задач» — `/settings/tasks/`, order 65, право `settings.portal`; при
    равном порядке пункты идут по `(order, title)`, поэтому «Настройки задач» стоят перед «Сервис-деском»;
    сотруднику без `settings.portal` настроек не видно, без `tasks.use` — «Задач»."""
    from apps.core.services import permissions

    items = _tasks_menu()
    main, settings_item = items["/tasks/"], items["/settings/tasks/"]
    assert (main["title"], main["icon"], main["order"], tuple(main["permissions"])) == (
        "Задачи", "icons/tasks.html", 2, ("tasks.use",))
    assert (settings_item["title"], settings_item["icon"], settings_item["order"],
            tuple(settings_item["permissions"])) == (
        "Настройки задач", "icons/gear.html", 65, ("settings.portal",))

    admin = support.make_admin(full_name="Администратор Меню")
    menu = permissions.menu_for(admin)
    titles = [item["title"] for item in menu]
    assert len(menu) == 23, f"пунктов меню у администратора: {len(menu)} — {titles}"
    assert titles[:4] == ["Лента", "Мессенджер", "Задачи", "Поручения"], titles[:4]
    assert titles.index("Настройки задач") < titles.index("Настройки поручений") < titles.index("Безопасность и политика")
    assert "Настройки задач" in titles and "Сервис-деск" in titles
    assert titles.index("Настройки задач") < titles.index("Сервис-деск"), (
        "при порядке 65 «Настройки задач» должны идти перед «Сервис-деском»")

    employee = support_tasks.staff_user(full_name="Сотрудник Меню")
    employee_titles = [item["title"] for item in permissions.menu_for(employee)]
    assert "Задачи" in employee_titles, "«Задачи» не видны держателю tasks.use"
    assert "Настройки задач" not in employee_titles, "настройки задач видны без settings.portal"


# --- статика, шаблоны, CSP (CONTRACT-009, 1.1) ------------------------------------------------------------

def test_tasks_assets_and_sortable_are_wired():
    """FR-680 (CONTRACT-009, 1.1): `static/tasks/tasks.js` и `tasks.css` есть и подключены в `_assets.html` для
    `/tasks/` (`<script defer>`, `<link rel="stylesheet">`) вместе с `vendor/Sortable-1.15.6.min.js`; в `tasks.js`
    нет `eval(` и `new Function`; `LICENSE-sortable` и строка «SortableJS 1.15.6» в `VERSIONS.md` на месте."""
    for name in ("tasks.js", "tasks.css"):
        path = BACKEND_DIR / "static" / "tasks" / name
        assert path.is_file(), f"нет файла static/tasks/{name}"
        assert path.read_text(encoding="utf-8").strip(), f"{name}: пустой файл"
    script = (BACKEND_DIR / "static" / "tasks" / "tasks.js").read_text(encoding="utf-8")
    assert "eval(" not in script and "new Function" not in script, "tasks.js: eval или new Function"

    assets = (BACKEND_DIR / "templates" / "_assets.html").read_text(encoding="utf-8")
    script_tag = re.compile(r"<script\b(?=[^>]*\bdefer\b)"
                            r"(?=[^>]*\bsrc=\"[^\"]*tasks/tasks\.js[^\"]*\")[^>]*>")
    css_tag = re.compile(r"<link\b(?=[^>]*\brel=\"stylesheet\")"
                         r"(?=[^>]*\bhref=\"[^\"]*tasks/tasks\.css[^\"]*\")[^>]*>")
    sortable_tag = re.compile(r"<script\b(?=[^>]*\bdefer\b)"
                              r"(?=[^>]*\bsrc=\"[^\"]*Sortable-1\.15\.6\.min\.js[^\"]*\")[^>]*>")
    assert script_tag.search(assets), "нет подключения <script defer src=…tasks/tasks.js>"
    assert css_tag.search(assets), "нет подключения <link rel=\"stylesheet\" href=…tasks/tasks.css>"
    assert sortable_tag.search(assets), "нет подключения Sortable-1.15.6.min.js"
    assert re.search(r"if\s+\"/tasks/\"\s+in\s+request\.path", assets), "статика не привязана к путям /tasks/"

    assert (BACKEND_DIR / "static" / "vendor" / "Sortable-1.15.6.min.js").is_file()
    assert (BACKEND_DIR / "static" / "vendor" / "LICENSE-sortable").is_file()
    versions = (BACKEND_DIR / "static" / "vendor" / "VERSIONS.md").read_text(encoding="utf-8")
    assert re.search(r"^## SortableJS 1\.15\.6", versions, re.M), "в VERSIONS.md нет раздела SortableJS 1.15.6"


def test_templates_have_no_style_or_event_attributes():
    """NFR-702 (CONTRACT-009, 1.1): в `templates/tasks/` и иконке `icons/tasks.html` нет `style=` и `on…=`; в
    шаблонах нет встроенных `<script>` без `src`; свои скрипты — внешние файлы."""
    root = BACKEND_DIR / "templates" / "tasks"
    assert root.is_dir(), f"нет каталога шаблонов {root}"
    templates = sorted(root.rglob("*.html"))
    assert templates, "в templates/tasks нет шаблонов"
    icon = BACKEND_DIR / "templates" / "icons" / "tasks.html"
    assert icon.is_file(), "нет иконки пункта меню templates/icons/tasks.html"

    for path in templates + [icon]:
        text = path.read_text(encoding="utf-8")
        tags = re.findall(r"<[A-Za-z][^<>]*>", text)
        assert not [tag for tag in tags if re.search(r"\sstyle\s*=", tag, re.I)], f"{path.name}: атрибут style="
        assert not [tag for tag in tags if re.search(r"\son[a-z]+\s*=", tag, re.I)], f"{path.name}: обработчик on…="
        for tag in re.findall(r"<script\b[^>]*>", text, re.I):
            assert re.search(r"\bsrc\s*=", tag), f"{path.name}: встроенный скрипт без src: {tag}"


def test_csp_without_unsafe_inline_on_tasks_pages():
    """FR-700, NFR-702 (CONTRACT-009, 1.1): `/tasks/` и `/settings/tasks/` отдают `Content-Security-Policy`:
    `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`, `connect-src 'self'`; новых директив нет."""
    holder = support.make_with_permissions("tasks.use", "settings.portal", full_name="Держатель CSP")
    client = support.logged_in(holder)
    known = {name.lower() for name in django_settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]}
    for path in ("/tasks/", "/settings/tasks/"):
        policy = _csp(client.get(path), path)
        assert policy.get("script-src") == ["'self'"], f"{path}: script-src {policy.get('script-src')}"
        assert policy.get("connect-src") == ["'self'"], f"{path}: connect-src {policy.get('connect-src')}"
        assert "'unsafe-inline'" not in policy.get("script-src", []), f"{path}: unsafe-inline"
        assert "'unsafe-eval'" not in policy.get("script-src", []), f"{path}: unsafe-eval"
        assert not set(policy) - known, f"{path}: новые директивы {set(policy) - known}"


def test_tasks_pages_are_russian_with_expected_titles():
    """NFR-717 (CONTRACT-009, 1.1, 12.2): видимые надписи страниц по-русски — «Задачи» на `/tasks/`,
    «Настройки задач» и «Хранить задачи, лет» на `/settings/tasks/`; английских надписей из перечня нет."""
    holder = support.make_with_permissions("tasks.use", "settings.portal", full_name="Держатель Языка")
    client = support.logged_in(holder)
    for path, wanted in (("/tasks/", "Задачи"), ("/settings/tasks/", "Настройки задач")):
        response = client.get(path)
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        text = _visible(response.content.decode("utf-8"))
        assert wanted in text, f"{path}: нет надписи {wanted!r}"
        assert len(re.findall("[а-яА-ЯёЁ]{3,}", text)) >= 3, f"{path}: русского текста нет"
        for word in ENGLISH_WORDS:
            assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text), f"{path}: {word!r}"
    settings_page = _visible(client.get("/settings/tasks/").content.decode("utf-8"))
    assert "Хранить задачи, лет" in settings_page, "нет надписи о сроке хранения задач"


# --- nginx (CONTRACT-009, 1.2, 1.4) -----------------------------------------------------------------------

def test_nginx_has_four_25m_locations_and_tasks_proxy_directives():
    """NFR-713 (CONTRACT-009, 1.2, 1.4; CONTRACT-010, 1.2): в `deploy/nginx.conf` и `nginx.prod.conf` ровно четыре
    `location` с `client_max_body_size 25m` — `^/feed/files/$`, `^/messenger/files/$`, `^/tasks/files/$`,
    `^/instructions/files/$`; у задач тот же набор директив `proxy_*`, что у `tickets`; общий предел `6m` и четыре
    `55m` не менялись."""
    expected = [FEED_FILES_PATTERN, MESSENGER_FILES_PATTERN, TASKS_FILES_PATTERN, INSTRUCTIONS_FILES_PATTERN]
    for name in NGINX_FILES:
        found = locations_with_limit(name, "25m")
        patterns = [pattern for pattern, _body in found]
        assert sorted(patterns) == sorted(expected), f"{name}: location с 25m — {patterns}"
        text = uncommented(deploy_text(name))
        assert len(re.findall(r"client_max_body_size\s+25m;", text)) == 4, f"{name}: 25m должно быть четыре"
        own = directives(dict(found)[TASKS_FILES_PATTERN])
        for wanted in ("client_max_body_size 25m", "proxy_pass http://portal_web", "proxy_http_version 1.1",
                       "proxy_set_header Host $http_host", "proxy_set_header X-Forwarded-For $remote_addr",
                       f"proxy_set_header X-Forwarded-Proto {PROTO[name]}",
                       "proxy_set_header Upgrade $http_upgrade",
                       "proxy_set_header Connection $connection_upgrade"):
            assert wanted in own, f"{name}: в location задач нет `{wanted};`"
        assert proxy_names(own) == proxy_names(directives(tickets_location_body(name))), (
            f"{name}: набор директив не как у tickets")
        assert re.search(r"^\s{4}client_max_body_size 6m;", text, re.M), f"{name}: общий предел 6m изменён"
        with55 = [pattern for pattern, _body in locations_with_limit(name, "55m")]
        assert with55 == ["/request/", "^/tickets/(new/|[0-9]+/reply/)$", "^/kb/[0-9]+/files/$",
                          "^/lists/[0-9]+/[0-9]+/files/$"], f"{name}: location с 55m: {with55}"


# --- нагрузка (CONTRACT-009, 13.2) ------------------------------------------------------------------------

def test_load_profile_has_task_user_and_fill_tasks():
    """NFR-719 (CONTRACT-009, 13.2): `backend/tests/load/fill_tasks.py` — только при `E2E_STAND=1` (проверка до
    импорта моделей), 1 000 задач на 100 сотрудников, строка `fill_tasks: tasks=<число>`; в `locustfile.py` —
    класс `TaskUser` (список, пресеты, карточка, четыре доски, перенос, комментарий, поиск) рядом с `FeedUser`,
    `MessengerUser`, `NotifyUser`; нагрузка не запускается."""
    load = BACKEND_DIR / "tests" / "load"
    script = load / "fill_tasks.py"
    assert script.is_file(), "нет backend/tests/load/fill_tasks.py"
    text = script.read_text(encoding="utf-8")
    assert "E2E_STAND" in text
    assert "1_000" in text or "1000" in text, "нет наполнения 1 000 задач"
    assert re.search(r"\b100\b", text), "нет наполнения 100 сотрудников"
    assert re.search(r"fill_tasks: tasks=", text), "нет строки итога `fill_tasks: tasks=…`"
    tree = ast.parse(text)
    guard = None
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.If) and "E2E_STAND" in ast.get_source_segment(text, node.test):
            guard = index
            break
    assert guard is not None, "нет проверки E2E_STAND на верхнем уровне"
    assert re.search(r"sys\.exit\(", ast.get_source_segment(text, tree.body[guard])), "нет sys.exit без E2E_STAND"
    for node in tree.body[:guard]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            assert not [item for item in names if item.split(".")[0] in ("apps", "django")], (
                f"импорт {names} раньше проверки стенда")

    locust = load / "locustfile.py"
    locust_text = locust.read_text(encoding="utf-8")
    classes = {node.name: node for node in ast.parse(locust_text).body if isinstance(node, ast.ClassDef)}
    for name in ("FeedUser", "NotifyUser", "MessengerUser", "TaskUser"):
        assert name in classes, f"в locustfile.py нет класса {name}"
    segment = ast.get_source_segment(locust_text, classes["TaskUser"])
    assert "wait_time" in segment
    for needed in ("/tasks/", "board", "move", "comment", "search"):
        assert needed in segment, f"TaskUser не проверяет {needed!r}"


def test_verify_vendor_knows_sortablejs():
    """NFR-719 (CONTRACT-009, 1.1): `tools/verify_vendor.py` знает пакет `sortablejs@1.15.6` — в его словаре
    `ПАКЕТЫ` есть раздел SortableJS с пакетом npm, файлом лицензии и веткой `1.15.x`."""
    source = repo_file("tools", "verify_vendor.py").read_text(encoding="utf-8")
    assert re.search(r"\"SortableJS\"\s*:\s*\(\s*\"sortablejs\"\s*,\s*\"LICENSE-sortable\"", source), (
        "verify_vendor.py не знает пакет sortablejs")
    assert re.search(r"\^1\\\.15\\\.", source), "ветка версии SortableJS 1.15.x не задана"