"""T-5129: развёртывание и стенд среза 005 (FR-406, FR-417, FR-418, FR-422, FR-426, FR-433, FR-445, NFR-404, NFR-405,
NFR-409, NFR-412, NFR-413). Сценарии «Запуск», «Новые компоненты», «Проверка» (безопасность заголовков, стенд, команды
приёмки), «Резервная копия и восстановление».

Контракт: CONTRACT-005 — 1.1 (зависимости, приложения, скрипты), 1.2 (расписание, nginx, CSP, шаблоны, язык и время),
1.3 (сброс стенда), 1.4 и 13 (команды стенда и нагрузка), 16 и 17. Сброс стенда проверяется прямым вызовом
`apps.knowledge.stand.stand_reset()` (контракт 1.3, решение З8; команда `e2e_reset_stand` здесь не запускается: она
чистит все таблицы ядра). Данные сброса создаются и читаются через соединение `migrate`.
"""
import ast
import re
from datetime import datetime, timedelta
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

from tests import support, support_kb as kb
from tests.support import BACKEND_DIR, repo_file

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
OPEN_MARKERS = ("mit", "bsd", "apache", "lgpl", "unlicense", "psf", "python software", "hpnd", "isc", "0bsd", "mpl")
NEW_PACKAGES = ("markdown-it-py", "mdurl", "nh3")
ASSET_ORDER = ("kb-link.js", "kb-editor.js", "search.js")
NGINX_FILES = ("nginx.conf", "nginx.prod.conf")


# --- помощники чтения файлов (свои: общие файлы тестов не правятся) -------------------------------------------------

def deploy_text(*parts: str) -> str:
    return repo_file("deploy", *parts).read_text(encoding="utf-8")


def uncommented(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def pins_of(file: str) -> set[str]:
    lines = (BACKEND_DIR / file).read_text(encoding="utf-8").splitlines()
    return {line.split("#", 1)[0].strip() for line in lines if line.split("#", 1)[0].strip()}


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


def kb_files_location(name: str) -> tuple[str, str]:
    """(регулярное выражение адреса, тело) блока `location ~ ^/kb/[0-9]+/files/$` файла nginx."""
    text = uncommented(deploy_text(name))
    found = re.search(r"location\s+~\*?\s+(\S*kb\S*files\S*)\s*\{", text)
    assert found, f"{name}: нет location с шаблоном адреса вложения статьи /kb/<id>/files/"
    return found.group(1), location_body(text, r"~\*?\s+" + re.escape(found.group(1)))


def tickets_location_body(name: str) -> str:
    return location_body(uncommented(deploy_text(name)), re.escape(r"~ ^/tickets/(new/|[0-9]+/reply/)$"))


def cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в config/cron.py (разбор дерева): полный путь функции, очередь, cron, имя, job_timeout."""
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
                          "name": options.get("name"), "job_timeout": options.get("job_timeout")})
    return found


# --- приложения, расписание, зависимости ------------------------------------------------------------------------------

def test_knowledge_and_search_are_in_installed_apps_after_notify():
    """FR-433, FR-445: в конце `INSTALLED_APPS` — `apps.notify`, затем `apps.knowledge`, затем `apps.lists` (срез 006,
    CONTRACT-006, раздел 1.1), затем `apps.search` (решение 3 задач), последним — `apps.feed` среза 007 (CONTRACT-007); у приложений метки `knowledge` и `search`,
    у `knowledge` `verbose_name` «База знаний» (раздел 1.1)."""
    from django.apps import apps
    from django.conf import settings
    from tests.support_feed import APPS_TAIL

    assert list(settings.INSTALLED_APPS)[-5:] == APPS_TAIL[1:] == [
        "apps.notify", "apps.knowledge", "apps.lists", "apps.search", "apps.feed"]
    assert apps.get_app_config("knowledge").label == "knowledge"
    assert apps.get_app_config("search").label == "search"
    assert apps.get_app_config("knowledge").verbose_name == "База знаний"


def test_purge_trash_is_registered_in_cron_with_45_23_maintenance_timeout_600():
    """FR-417: `config/cron.py` — семнадцатая запись: `purge_trash` (`apps.knowledge.tasks.purge_trash`), очередь
    `maintenance`, `cron="45 23 * * *"`, `job_timeout=600` (раздел 1.2); всего записей двадцать — восемнадцатая
    `lists_reminders` среза 006 (CONTRACT-006, раздел 1.2), девятнадцатая и двадцатая — задания среза 007."""
    registrations = cron_registrations()
    assert len(registrations) == 20, (
        f"вызовов register {len(registrations)}, ожидается 20 (16 прежних, purge_trash, lists_reminders и два задания среза 007)")
    by_name = {item["name"]: item for item in registrations}
    assert "lists_reminders" in by_name, "нет задания lists_reminders среза 006"
    item = by_name.get("purge_trash")
    assert item, "нет задания purge_trash"
    assert item["target"] == "apps.knowledge.tasks.purge_trash", f"функция задания: {item['target']}"
    assert item["queue"] == "maintenance"
    assert item["cron"] == "45 23 * * *"
    assert item["job_timeout"] == 600


def test_cron_has_no_other_entry_on_minute_45_of_hour_23():
    """FR-417: минута 45 часа 23 занята только `purge_trash`; рядом 23:40 `notify_retention` и 23:50
    `purge_orphan_files` остаются на своих местах (раздел 1.2)."""
    by_name = {item["name"]: item for item in cron_registrations()}
    assert "purge_trash" in by_name, "нет задания purge_trash"
    same_time = [name for name, item in by_name.items() if name != "purge_trash" and item["cron"] == "45 23 * * *"]
    assert not same_time, f"то же время у других заданий: {same_time}"
    assert by_name["purge_trash"]["cron"] == "45 23 * * *"
    assert by_name["notify_retention"]["cron"] == "40 23 * * *"
    assert by_name["purge_orphan_files"]["cron"] == "50 23 * * *"


def test_requirements_pin_markdown_it_py_mdurl_nh3_exact_versions():
    """NFR-405: `requirements.txt` закрепляет `markdown-it-py==4.2.0`, `mdurl==0.1.2`, `nh3==0.3.7` знаком `==`;
    блок «Срез 005» со ссылкой на PLAN-005; других новых строк нет (раздел 1.1)."""
    pins = pins_of("requirements.txt")
    for pin in ("markdown-it-py==4.2.0", "mdurl==0.1.2", "nh3==0.3.7"):
        assert pin in pins, f"нет строки {pin}"
    for name in NEW_PACKAGES:
        loose = [pin for pin in pins if re.match(rf"^{re.escape(name)}\s*(>=|~=|<=|>|<|!=)", pin)]
        assert not loose, f"версия не закреплена точно: {loose}"
    text = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    block = text.split("Срез 005", 1)
    assert len(block) == 2 and "PLAN-005" in block[1].splitlines()[0], "нет комментария «Срез 005 … PLAN-005»"
    after = [line.split("#", 1)[0].strip() for line in block[1].splitlines()[1:]]
    assert [line for line in after if line] == ["markdown-it-py==4.2.0", "mdurl==0.1.2", "nh3==0.3.7"]


def test_new_packages_have_open_licenses_and_no_vendor_static_entry():
    """NFR-405: установленные `markdown-it-py`, `mdurl`, `nh3` — открытая лицензия (MIT); сторонней статики у среза
    нет: в `static/vendor/VERSIONS.md` записей этих пакетов и среза нет (раздел 1.1, план)."""
    from importlib import metadata

    for name in NEW_PACKAGES:
        meta = metadata.metadata(name)
        declared = " ".join([meta.get("License-Expression", ""), meta.get("License", "")[:300]]).lower()
        classifiers = " ".join(c for c in meta.get_all("Classifier", []) if c.startswith("License")).lower()
        text = declared if declared.strip() else classifiers
        assert any(re.search(rf"(?<![a-z]){re.escape(marker)}" + (r"(?![a-z])" if len(marker) <= 3 else ""), text)
                   for marker in OPEN_MARKERS), f"{name}: открытая лицензия не опознана ({text[:80]!r})"
        assert "proprietary" not in text and "commercial" not in text, f"{name}: платная лицензия"
    versions = (BACKEND_DIR / "static" / "vendor" / "VERSIONS.md").read_text(encoding="utf-8").lower()
    for word in ("markdown-it", "mdurl", "nh3", "kb-editor", "kb-link"):
        assert word not in versions, f"в VERSIONS.md запись среза: {word}"


# --- nginx ------------------------------------------------------------------------------------------------------------

def _check_kb_files_location(name):
    """Общая проверка для двух файлов (вызывается тестами dev и prod): шаблон адреса — только вложение
    (`/kb/<id>/files/`), скачивание `/kb/<id>/files/<N>/` под него не подпадает; предел тела — 55m; общий — 6m."""
    pattern, body = kb_files_location(name)
    assert pattern == "^/kb/[0-9]+/files/$", f"{name}: шаблон {pattern!r}"
    assert re.search(pattern, "/kb/12/files/") and not re.search(pattern, "/kb/12/files/3/")
    assert not re.search(pattern, "/kb/12/files/3/delete/")
    assert "client_max_body_size 55m" in directives(body), f"{name}: в location нет client_max_body_size 55m"
    top = uncommented(deploy_text(name))
    assert re.search(r"^\s{4}client_max_body_size 6m;", top, re.M), f"{name}: общий предел 6m изменён"


def test_nginx_dev_config_has_kb_files_location_with_55m_limit():
    """FR-422, NFR-404: `deploy/nginx.conf` — `location ~ ^/kb/[0-9]+/files/$` с `client_max_body_size 55m;`; адрес
    скачивания под него не подпадает; общий предел 6m не менялся; блок рядом с блоком `tickets`."""
    _check_kb_files_location("nginx.conf")
    text = uncommented(deploy_text("nginx.conf"))
    assert abs(text.index("/kb/[0-9]+/files/") - text.index("/tickets/(new/")) < 1500, "блок не рядом с блоком tickets"


def test_nginx_prod_config_has_kb_files_location_with_55m_limit():
    """FR-422, NFR-404: то же в `deploy/nginx.prod.conf`."""
    _check_kb_files_location("nginx.prod.conf")
    text = uncommented(deploy_text("nginx.prod.conf"))
    assert abs(text.index("/kb/[0-9]+/files/") - text.index("/tickets/(new/")) < 1500, "блок не рядом с блоком tickets"


def test_kb_files_location_repeats_proxy_directives_in_both_configs():
    """FR-422, NFR-404: в новом `location` повторены директивы `proxy_*` (из `location /` они не наследуются):
    `proxy_pass http://portal_web`, `proxy_http_version 1.1`, `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`
    (`$scheme` в dev, `$portal_proto` в prod), `Upgrade`, `Connection`, `proxy_read_timeout 75s`; набор имён
    директив совпадает с блоком `tickets` того же файла (раздел 1.2)."""
    proto = {"nginx.conf": "$scheme", "nginx.prod.conf": "$portal_proto"}
    for name in NGINX_FILES:
        _, body = kb_files_location(name)
        own = directives(body)
        for wanted in ("proxy_pass http://portal_web", "proxy_http_version 1.1", "proxy_set_header Host $http_host",
                       "proxy_set_header X-Forwarded-For $remote_addr",
                       f"proxy_set_header X-Forwarded-Proto {proto[name]}",
                       "proxy_set_header Upgrade $http_upgrade",
                       "proxy_set_header Connection $connection_upgrade", "proxy_read_timeout 75s"):
            assert wanted in own, f"{name}: в location вложений статьи нет `{wanted};`"

        def names(items):
            return {" ".join(item.split()[:2]) if item.startswith("proxy_set_header") else item.split()[0]
                    for item in items}

        assert names(own) == names(directives(tickets_location_body(name))), f"{name}: набор директив не как у tickets"


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


def _kb_paths_for_manager():
    session = kb.as_manager()
    article = kb.make_published()
    return session, ["/kb/", f"/kb/{article.pk}/", "/kb/new/"]


@PLAIN
def test_kb_pages_send_csp_without_unsafe_inline_in_script_src():
    """NFR-405: страницы `/kb/`, `/kb/<id>/`, `/kb/new/` отдают `Content-Security-Policy`: `script-src 'self'` без
    `'unsafe-inline'` и `'unsafe-eval'`; новых директив срез не вводит (раздел 1.2)."""
    from django.conf import settings

    session, paths = _kb_paths_for_manager()
    known = {name.lower() for name in settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]}
    for path in paths:
        directives_map = _csp(session.client.get(path), path)
        assert directives_map.get("script-src") == ["'self'"], f"{path}: script-src {directives_map.get('script-src')}"
        assert not set(directives_map) - known, f"{path}: новые директивы {set(directives_map) - known}"


@PLAIN
def test_search_pages_send_csp_without_unsafe_inline_in_script_src():
    """NFR-405: `/search/?q=…` отдаёт `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`."""
    session = kb.as_reader()
    path = "/search/?q=" + "принтер"
    directives_map = _csp(session.client.get(path), path)
    assert directives_map.get("script-src") == ["'self'"]
    fragment = session.client.get(path, **support.HX)
    assert _csp(fragment, path + " (HTMX)").get("script-src") == ["'self'"]


@PLAIN
def test_csp_img_src_on_kb_and_search_has_no_external_addresses():
    """NFR-405: `img-src 'self' data:` на страницах базы знаний и поиска; ни `http:`, ни `https:`, ни `*`, ни
    внешних адресов."""
    session, paths = _kb_paths_for_manager()
    for path in paths + ["/search/?q=" + "принтер"]:
        sources = _csp(session.client.get(path), path).get("img-src")
        assert sources is not None, f"{path}: нет img-src"
        assert sorted(sources) == ["'self'", "data:"], f"{path}: img-src {sources}"
        assert not [s for s in sources if s in ("http:", "https:", "*") or "//" in s or "." in s]


# --- шаблоны и скрипты --------------------------------------------------------------------------------------------------

def _template_files() -> list:
    found = []
    for folder in ("knowledge", "search"):
        root = BACKEND_DIR / "templates" / folder
        assert root.is_dir(), f"нет каталога шаблонов {root}"
        found += sorted(root.rglob("*.html"))
    return found


def _tags(text: str) -> list[str]:
    return re.findall(r"<[A-Za-z][^<>]*>", text)


def test_knowledge_and_search_templates_have_no_style_attribute():
    """NFR-405: в `templates/knowledge/` и `templates/search/` нет атрибута `style=` (выравнивание таблицы статьи —
    классами `kb-al-*`); шаблоны на месте (раздел 1.2)."""
    files = _template_files()
    assert any("knowledge" in str(path) for path in files), "в templates/knowledge нет шаблонов"
    assert any(f"{BACKEND_DIR / 'templates' / 'search'}" in str(path) for path in files), "в templates/search нет шаблонов"
    bad = [str(path.relative_to(BACKEND_DIR)) for path in files
           if any(re.search(r"\sstyle\s*=", tag, re.I) for tag in _tags(path.read_text(encoding="utf-8")))]
    assert not bad, f"атрибут style= в шаблонах: {bad}"


def test_knowledge_and_search_templates_have_no_inline_event_handlers():
    """NFR-405: в тех же шаблонах нет атрибутов обработчиков `on…=`."""
    files = _template_files()
    assert any("knowledge" in str(path) for path in files), "в templates/knowledge нет шаблонов"
    bad = [str(path.relative_to(BACKEND_DIR)) for path in files
           if any(re.search(r"\son[a-z]+\s*=", tag, re.I) for tag in _tags(path.read_text(encoding="utf-8")))]
    assert not bad, f"обработчики on…= в шаблонах: {bad}"


def test_slice_scripts_are_external_files_listed_in_assets_partial():
    """NFR-405: `static/js/kb-link.js`, `kb-editor.js`, `search.js` — внешние файлы без `eval(` и `new Function`
    и без встроенной разметки скрипта; подключены в `templates/_assets.html` в порядке: `kb-link.js`, затем
    `kb-editor.js`, затем `search.js` (решение 9 задач; раздел 1.1)."""
    assets = (BACKEND_DIR / "templates" / "_assets.html").read_text(encoding="utf-8")
    positions = []
    for name in ASSET_ORDER:
        path = BACKEND_DIR / "static" / "js" / name
        assert path.is_file(), f"нет файла static/js/{name}"
        source = path.read_text(encoding="utf-8")
        assert source.strip(), f"{name}: пустой файл"
        assert "eval(" not in source and "new Function" not in source, f"{name}: eval или new Function"
        assert not name.startswith("notify"), name
        found = re.search(r"<script\b[^>]*\bsrc=\"[^\"]*" + re.escape(name) + r"[^\"]*\"", assets)
        assert found, f"в _assets.html нет подключения {name}"
        positions.append(found.start())
    assert positions == sorted(positions), "порядок подключения: kb-link.js, kb-editor.js, search.js"


# --- язык и время -----------------------------------------------------------------------------------------------------

ENGLISH_WORDS = ("Save", "Delete", "Cancel", "Search", "Submit", "Edit", "Back")   # ровно список п. 17.31


def _visible(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@PLAIN
def test_kb_pages_and_search_page_texts_are_russian():
    """NFR-409: страницы базы знаний и результатов поиска по-русски: названные в 12.1 и 12.3 надписи на месте,
    английских надписей интерфейса нет; пути — `support_kb.RUSSIAN_PAGES` и `article_pages` (раздел 1.2)."""
    session = kb.as_manager()
    article = kb.make_published(title="Настройка принтера", text="Текст про принтер")
    kb.add_version(article, text="Новый текст про принтер")
    labels = {
        "/kb/": ("Новые и изменённые", "Новая статья", "Корзина"),
        "/kb/new/": ("Сохранить черновик", "Сохраните черновик"),
        "/kb/trash/": ("Корзина пуста",),
        "/kb/settings/": ("Сохранить",),
        "/search/?q=" + "впн": ("Ничего не найдено",),
        f"/kb/{article.pk}/": ("Править", "История", "Комментарии", "Отправить"),
        f"/kb/{article.pk}/edit/": ("Сохранить",),
        f"/kb/{article.pk}/history/": ("Сравнить выбранные версии",),
        f"/kb/{article.pk}/versions/1/": ("Восстановить эту версию", "Удалить версию"),
    }
    paths = list(dict.fromkeys(list(kb.RUSSIAN_PAGES) + list(kb.article_pages(article))))
    for path in paths:
        response = session.client.get(path)
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        text = _visible(response.content.decode())
        assert len(re.findall("[а-яА-ЯёЁ]{3,}", text)) >= 3, f"{path}: русского текста нет"
        for label in labels.get(path, ()):
            assert label in text, f"{path}: нет надписи «{label}»"
        for word in ENGLISH_WORDS:
            assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text), f"{path}: английская надпись {word!r}"


@PLAIN
def test_kb_times_are_shown_in_moscow_at_utc_midnight(clock):
    """NFR-409: часы на полночь UTC 10.03.2026 (в Москве — 03:00): статья, версия, комментарий и корзина показывают
    «10.03.2026 03:00» в `time[data-at]` (атрибут `datetime` — тот же момент); «10.03.2026 00:00» нет (раздел 1.2)."""
    moment = kb.utc_midnight(clock, 2026, 3, 10)
    assert kb.moscow_text(moment) == "10.03.2026 03:00"
    session = kb.as_manager()
    article = kb.make_published(title="Статья про время")
    kb.add_version(article, text="Правка")
    kb.make_comment(article, author=session.user)
    trashed = kb.make_trashed(title="Статья в корзине")
    pages = [f"/kb/{article.pk}/", f"/kb/{article.pk}/history/", "/kb/trash/"]
    for path in pages:
        response = session.client.get(path)
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        html = response.content.decode()
        marks = re.findall(r"<time\b([^>]*\bdata-at\b[^>]*)>(.*?)</time>", html, re.S)
        assert marks, f"{path}: нет time[data-at]"
        for attrs, text in marks:
            assert re.sub(r"\s+", " ", text).strip() == "10.03.2026 03:00", f"{path}: время {text!r}"
            iso = re.search(r'datetime="([^"]+)"', attrs)
            assert iso, f"{path}: у time нет datetime"
            assert datetime.fromisoformat(iso.group(1).replace("Z", "+00:00")) == moment, f"{path}: datetime {iso.group(1)}"
        assert "10.03.2026 00:00" not in html, f"{path}: время в UTC"
    assert trashed.pk  # статья корзины создана до страницы корзины


# --- том protected и резервная копия ----------------------------------------------------------------------------------

@PLAIN
def test_article_files_live_in_protected_volume_and_backup_script_is_unchanged(protected_root, django_capture_on_commit_callbacks):
    """NFR-413: файл статьи кладётся в том `protected` (`incoming/<id>` под `PROTECTED_ROOT`, строка `StoredFile` с
    `purpose="knowledge"`); новых томов и внутренних `location` nginx нет; `backup/backup.sh` и `RESTORE.md` слов
    `knowledge` и `kb` не содержат (раздел 1.2)."""
    from apps.core.services import files as core_files
    from apps.knowledge.services import files as article_files

    session = kb.as_editor()
    article = kb.make_draft(author=session.user)
    body = kb.png_bytes()
    with django_capture_on_commit_callbacks(execute=False):
        row = article_files.attach(session.user, article.pk, SimpleUploadedFile("схема.png", body, "image/png"))
    stored = row.file
    assert stored.purpose == "knowledge"
    path = core_files.attachment_path(stored)
    assert path.parent.parent == protected_root and path.parent.name in ("incoming", "attachments")
    assert path.read_bytes() == body
    for name in NGINX_FILES:
        text = uncommented(deploy_text(name))
        internal = re.findall(r"location\s+(\S+)\s*\{", text)
        assert [item for item in internal if item.startswith("/protected/")] == \
            ["/protected/attachments/", "/protected/inbound/", "/protected/"], f"{name}: набор внутренних location изменён"
    # `uncommented` склеивает строки без завершающего перевода — без него последний том не попал бы в выборку
    compose = uncommented(deploy_text("docker-compose.yml")) + "\n"
    volumes = re.search(r"^volumes:\s*\n((?:  \S.*\n)+)", compose, re.M)
    assert volumes
    assert re.findall(r"^  ([A-Za-z0-9_-]+):", volumes.group(1), re.M) == [
        "postgres-data", "valkey-data", "clamav-db", "test-venv", "media", "protected", "backups"]
    for name in (("backup", "backup.sh"), ("RESTORE.md",)):
        text = deploy_text(*name)
        assert not re.search(r"(?i)\b(knowledge|kb)\b", text), f"{'/'.join(name)}: упоминание базы знаний"


# --- сброс стенда (прямой вызов функции точки, контракт 1.3) -------------------------------------------------------------

def _on(model_name: str):
    return support.model(model_name).objects.using("migrate")


def _owner():
    """Сотрудник, созданный через `migrate`."""
    from tests import factories

    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name="Автор Статьев", state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _stored(purpose: str, status: str, data: bytes, root, *, write: bool = True):
    from apps.core.services import files as core_files

    stored = _on("core.StoredFile").create(
        purpose=purpose, owner=None, size=len(data), sha256="0" * 64, content_type="application/octet-stream",
        status=status, scanned_at=timezone.now() if status != "pending" else None)
    path = core_files.attachment_path(stored)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return stored, path


def _slice_data():
    """Данные среза через `migrate`: рубрика, статья с версией, тег, три файла статьи, связь, подписка, комментарий."""
    now = timezone.now()
    author = _owner()
    rubric = _on("knowledge.Rubric").create(name="Сеть", parent=None, depth=1)
    article = _on("knowledge.Article").create(
        title="Статья стенда", text="Текст", html="<p>Текст</p>", plain="Текст", rubric=rubric, state="published",
        author=author, created_at=now, updated_by=author, updated_at=now, version_no=1, published_at=now)
    _on("knowledge.ArticleVersion").create(
        article=article, number=1, author=author, created_at=now, comment="", title=article.title, text=article.text,
        html=article.html, rubric=rubric, rubric_name=rubric.name, tags=["впн"])
    tag = _on("knowledge.Tag").create(name="впн")
    article.tags.through.objects.using("migrate").create(article_id=article.pk, tag_id=tag.pk)
    _on("knowledge.TicketLink").create(article=article, ticket_number=7, linked_by=author, linked_at=now,
                                       from_resolution=False)
    _on("knowledge.RubricSubscription").create(user=author, rubric=rubric, created_at=now)
    comment = _on("core.Comment").create(object_ref=f"knowledge.article:{article.pk}", author=author,
                                         text="Комментарий к статье", created_at=now)
    return author, rubric, article, comment


def _article_files(article, author, root):
    made = []
    for status, name in (("pending", "a.txt"), ("clean", "b.txt"), ("quarantine", "c.txt")):
        stored, path = _stored("knowledge", status, name.encode(), root)
        _on("knowledge.ArticleFile").create(article=article, file=stored, name=name, image_format="", uploaded_by=author,
                                            uploaded_at=timezone.now())
        made.append((stored, path))
    return made


@MIGRATE
def test_stand_reset_knowledge_wipes_slice_data_and_prefixed_comments(protected_root):
    """FR-426: `stand_reset()` стирает статьи, версии, рубрики кроме «Общее», теги, связи с заявками, подписки,
    комментарии ядра с префиксом `knowledge.article:` и файлы статей (строки `ArticleFile` и `StoredFile`, затем
    файл в `incoming/`, `attachments/`, `quarantine/`); рубрика «Общее» остаётся (раздел 1.3)."""
    from apps.knowledge.stand import stand_reset

    author, rubric, article, comment = _slice_data()
    made = _article_files(article, author, protected_root)
    assert all(path.exists() for _, path in made)
    assert _on("knowledge.Article").count() == 1 and _on("knowledge.Rubric").filter(is_default=False).exists()

    stand_reset()

    for name in ("Article", "ArticleVersion", "Tag", "TicketLink", "RubricSubscription", "ArticleFile"):
        assert _on(f"knowledge.{name}").count() == 0, name
    assert not _on("knowledge.Rubric").filter(is_default=False).exists()
    assert _on("knowledge.Rubric").filter(is_default=True).count() == 1
    assert not _on("core.Comment").filter(object_ref__startswith="knowledge.article:").exists()
    for stored, path in made:
        assert not _on("core.StoredFile").filter(pk=stored.pk).exists(), "StoredFile статьи остался"
        assert not path.exists(), f"файл статьи остался на диске: {path.parent.name}"


@MIGRATE
def test_stand_reset_knowledge_keeps_ticket_files_and_other_comments(protected_root):
    """FR-426: `stand_reset()` не трогает файлы и `StoredFile` вложений заявок (`purpose="attachment"`), комментарии
    ядра с другим префиксом `object_ref` и общую очередь `files` (раздел 1.3)."""
    import django_rq

    from apps.knowledge.stand import stand_reset

    author, rubric, article, comment = _slice_data()
    _article_files(article, author, protected_root)
    ticket_files = [_stored("attachment", status, b"ticket " + status.encode(), protected_root)
                    for status in ("pending", "clean", "quarantine")]
    foreign = _on("core.Comment").create(object_ref="servicedesk.ticket:7", author=author, text="Чужой комментарий",
                                         created_at=timezone.now())
    queue = django_rq.get_queue("files")
    queue.enqueue("builtins.len", [1])
    queued = queue.count

    stand_reset()

    for stored, path in ticket_files:
        assert _on("core.StoredFile").filter(pk=stored.pk).exists(), "StoredFile вложения заявки стёрт"
        assert path.read_bytes().startswith(b"ticket "), "файл вложения заявки тронут"
    assert _on("core.Comment").filter(pk=foreign.pk, text="Чужой комментарий").exists()
    assert not _on("core.Comment").filter(pk=comment.pk).exists()
    assert queue.count == queued, "очередь files очищена"


@MIGRATE
def test_stand_reset_knowledge_restores_general_rubric_and_role_permissions():
    """FR-406, FR-418: после общей очистки ядра (рубрика, строка настроек и права стёрты; здесь — вручную через
    `migrate`) `stand_reset()` возвращает рубрику «Общее» (`parent=None`, `depth=1`, `is_default=True`),
    `KnowledgeSettings(pk=1, trash_days=90)`, права `knowledge.edit` и `knowledge.manage` и их выдачу встроенным
    ролям: «Администратор портала» — оба, «Сотрудник ИТ» — `knowledge.edit`, «Руководитель» — ничего (раздел 1.3;
    команду `e2e_reset_stand` тест не запускает — решение З8)."""
    from apps.core import extensions
    from apps.knowledge.stand import stand_reset

    # раздел 1.3: функция зарегистрирована в точке позже `notify`; со срезом 007 последней среди приложений стоит
    # `feed`, `lists` — предпоследней, `knowledge` — третьей с конца (CONTRACT-007, раздел 15: команда зовёт точки в
    # обратном порядке, поэтому `feed` идёт первой, `lists` — второй, `knowledge` — третьей, раньше `notify`)
    names = [func.__module__ for func in extensions.registered("stand_reset")]
    assert "apps.knowledge.stand" in names, "stand_reset модуля knowledge не зарегистрирован в точке"
    assert "apps.notify.stand" in names
    assert names.index("apps.knowledge.stand") > names.index("apps.notify.stand")
    assert "apps.lists.stand" in names, "stand_reset модуля lists не зарегистрирован в точке"
    assert "apps.feed.stand" in names, "stand_reset модуля feed не зарегистрирован в точке"
    assert names.index("apps.feed.stand") == len(names) - 1
    assert names.index("apps.lists.stand") == len(names) - 2
    assert names.index("apps.knowledge.stand") == len(names) - 3
    for rubric in _on("knowledge.Rubric").order_by("-depth"):
        rubric.delete()
    _on("knowledge.KnowledgeSettings").all().delete()
    _on("core.Permission").filter(code__in=kb.PERMISSIONS_005).delete()
    assert not _on("core.Permission").filter(code__in=kb.PERMISSIONS_005).exists()

    stand_reset()

    general = _on("knowledge.Rubric").get(is_default=True)
    assert general.name == "Общее" and general.parent_id is None and general.depth == 1
    assert _on("knowledge.Rubric").count() == 1
    settings_row = _on("knowledge.KnowledgeSettings").get(pk=1)
    assert settings_row.trash_days == 90
    assert {p.code: p.title for p in _on("core.Permission").filter(code__in=kb.PERMISSIONS_005)} == kb.TITLES_005

    def granted(role_name: str) -> set[str]:
        role = _on("core.Role").get(name=role_name, is_builtin=True)
        return set(role.permissions.using("migrate").filter(code__in=kb.PERMISSIONS_005).values_list("code", flat=True))

    assert granted(support.ADMIN_ROLE) == set(kb.PERMISSIONS_005)
    assert granted(support.STAFF_ROLE) == {"knowledge.edit"}
    assert granted(support.MANAGER_ROLE) == set()
    assert not [role for role in _on("core.Role").filter(is_builtin=True).exclude(
        name__in=(support.ADMIN_ROLE, support.STAFF_ROLE, support.MANAGER_ROLE))
        if set(role.permissions.using("migrate").filter(code__in=kb.PERMISSIONS_005))]


# --- команды стенда -----------------------------------------------------------------------------------------------------

def _run(command: str, *args) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def _trash_state(article):
    row = type(article).objects.get(pk=article.pk)
    return row.state, row.deleted_at, row.updated_at, row.version_no


@PLAIN
def test_e2e_kb_trash_shift_and_e2e_kb_purge_refuse_without_stand_flag(monkeypatch, clock, django_assert_num_queries):
    """FR-417: без `E2E_STAND=1` обе команды падают `CommandError` с текстом отказа раньше любого запроса к базе
    (`django_assert_num_queries(0)`); статья в корзине и её срок не меняются, статья не удалена (раздел 1.4, 13)."""
    monkeypatch.delenv("E2E_STAND", raising=False)
    clock.set(kb.moscow(2026, 3, 1, 12))
    trashed = kb.make_trashed()
    before = _trash_state(trashed)
    for command, args in (("e2e_kb_trash_shift", ("--days", "1")), ("e2e_kb_trash_shift", ("--days", "100")),
                          ("e2e_kb_purge", ())):
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                call_command(command, *args, stdout=StringIO())
        assert str(refused.value) == REFUSAL, f"{command} {args}"
    assert _trash_state(trashed) == before, "отказавшая команда изменила данные"


@PLAIN
def test_e2e_kb_trash_shift_and_e2e_kb_purge_work_with_stand_flag(monkeypatch, clock, django_capture_on_commit_callbacks):
    """FR-417: с `E2E_STAND=1` `e2e_kb_trash_shift --days N` сдвигает `deleted_at` статей в корзине на N суток назад
    без `save()` (`updated_at`, `version_no` те же; вывод `kb_trash_shift: days=N shifted=<число>`; пустая корзина —
    `shifted=0`); `e2e_kb_purge` удаляет навсегда статью, пробывшую в корзине дольше срока (90 суток), и печатает
    `kb_purge: purged=<n> skipped=<n> failed=<число>`; свежая статья остаётся (раздел 13)."""
    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(kb.moscow(2026, 3, 1, 12))
    assert _run("e2e_kb_trash_shift", "--days", "5") == "kb_trash_shift: days=5 shifted=0\n"
    old = kb.make_trashed(title="Старая в корзине")
    fresh = kb.make_trashed(title="Свежая в корзине")
    draft = kb.make_draft(title="Черновик не в корзине")
    before = {row.pk: _trash_state(row) for row in (old, fresh, draft)}
    # обе статьи в корзине сдвигаются вместе: «свежую» вернём вперёд прямой записью, чтобы различать срок
    assert _run("e2e_kb_trash_shift", "--days", "91") == "kb_trash_shift: days=91 shifted=2\n"
    type(fresh).objects.filter(pk=fresh.pk).update(deleted_at=before[fresh.pk][1])
    after = {row.pk: _trash_state(row) for row in (old, fresh, draft)}
    assert after[old.pk][1] == before[old.pk][1] - timedelta(days=91)
    assert after[old.pk][2:] == before[old.pk][2:], "обновились updated_at или version_no"
    assert after[draft.pk] == before[draft.pk], "сдвинута статья не из корзины"
    with django_capture_on_commit_callbacks(execute=True):
        output = _run("e2e_kb_purge")
    assert output == "kb_purge: purged=1 skipped=0 failed=0\n", output
    assert not type(old).objects.filter(pk=old.pk).exists(), "статья старше срока не удалена навсегда"
    assert type(fresh).objects.filter(pk=fresh.pk).exists(), "свежая статья в корзине удалена"
    assert type(draft).objects.filter(pk=draft.pk).exists()
    with pytest.raises(CommandError, match="от 1 до 36500"):
        _run("e2e_kb_trash_shift", "--days", "0")


# --- нагрузка ---------------------------------------------------------------------------------------------------------

def test_load_suite_has_fill_articles_script_and_knowledge_user_class():
    """NFR-412: `backend/tests/load/fill_articles.py` есть (отказывает без `E2E_STAND=1`, переменные `LOAD_ARTICLES`,
    `LOAD_RUBRICS`, `LOAD_TAGS`), в `locustfile.py` есть класс `KnowledgeUser` с `wait_time`, берущим `LOAD_WAIT`;
    нагрузка не запускается (раздел 13, решения 13 и 38 задач)."""
    load = BACKEND_DIR / "tests" / "load"
    script = load / "fill_articles.py"
    assert script.is_file(), "нет backend/tests/load/fill_articles.py"
    text = script.read_text(encoding="utf-8")
    for needle in ("E2E_STAND", "LOAD_ARTICLES", "LOAD_RUBRICS", "LOAD_TAGS"):
        assert needle in text, f"в fill_articles.py нет {needle}"
    tree = ast.parse((load / "locustfile.py").read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert "KnowledgeUser" in classes, "в locustfile.py нет класса KnowledgeUser"
    source = ast.get_source_segment((load / "locustfile.py").read_text(encoding="utf-8"), classes["KnowledgeUser"])
    assert "LOAD_WAIT" in source and "wait_time" in source
