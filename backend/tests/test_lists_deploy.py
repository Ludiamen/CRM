"""T-6125: развёртывание среза 006 — приложение, расписание, nginx, CSP, шаблоны и скрипты, язык и время, нагрузка,
том файлов, словарь текстов (FR-530, FR-536, FR-543, FR-544, FR-546, NFR-505, NFR-506, NFR-510, NFR-513, NFR-514).
Сценарии «Запуск», «Новые компоненты и лицензии» (пакетов не проверяем: решение 42 задач), «Безопасный вывод, язык,
узкий экран», «Нагрузка», «Резервная копия и восстановление».

Контракт: CONTRACT-006 — 1.1 (приложение, статика, шаблоны, CSP, язык и время), 1.2 (cron, nginx, том файлов), 12
(тексты), 13.2 (нагрузка). Правило «полночь UTC» применено для показа времени (03:00 против 00:00); дополнительно часы
ставятся на 21:30 UTC, когда по Москве уже следующие сутки (00:30 11-го числа). Код среза импортируется внутри тестов.
"""
import ast
import re
import string
from datetime import datetime, timezone as dt_timezone

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support, support_lists as lists
from tests.support import BACKEND_DIR, repo_file

PLAIN = pytest.mark.django_db

NGINX_FILES = ("nginx.conf", "nginx.prod.conf")
LISTS_FILES_PATTERN = "^/lists/[0-9]+/[0-9]+/files/$"
ENGLISH_WORDS = ("Save", "Delete", "Cancel", "Search", "Submit", "Edit", "Back")
REFUSAL_LOAD = "Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."


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


def lists_files_location(name: str) -> tuple[str, str]:
    """(регулярное выражение адреса, тело) блока `location ~ ^/lists/[0-9]+/[0-9]+/files/$` файла nginx."""
    text = uncommented(deploy_text(name))
    found = re.search(r"location\s+~\*?\s+(\S*lists\S*files\S*)\s*\{", text)
    assert found, f"{name}: нет location с шаблоном адреса загрузки файла записи /lists/<id>/<n>/files/"
    return found.group(1), location_body(text, r"~\*?\s+" + re.escape(found.group(1)))


def tickets_location_body(name: str) -> str:
    return location_body(uncommented(deploy_text(name)), re.escape(r"~ ^/tickets/(new/|[0-9]+/reply/)$"))


def cron_source() -> str:
    return (BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")


def cron_registrations() -> list[dict]:
    """Вызовы `register(...)` в config/cron.py (разбор дерева): полный путь функции, очередь, cron, имя, job_timeout."""
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
                          "name": options.get("name"), "job_timeout": options.get("job_timeout"),
                          "line": node.lineno})
    return found


def _world():
    """Управляющий, список с полями «строка» и «дата и время» (в таблице) и одна запись."""
    session = lists.as_manager()
    lst = lists.make_list(created_by=session.user)
    text_field = lists.add_field(lst, "string", "Модель", show_in_table=True)
    when_field = lists.add_field(lst, "datetime", "Срок поставки", show_in_table=True)
    record = lists.make_record(lst, "Принтер", {text_field.code: "HP"}, created_by=session.user)
    return session, lst, record, text_field, when_field


# --- приложение и расписание ------------------------------------------------------------------------------------------

def test_lists_is_in_installed_apps_after_knowledge_and_before_search():
    """FR-543: в конце `INSTALLED_APPS` — `apps.servicedesk`, `apps.notify`, `apps.knowledge`, `apps.lists`,
    `apps.search`; метка `lists`, класс `ListsConfig`, `verbose_name` «Списки» (раздел 1.1)."""
    from django.apps import apps
    from django.conf import settings

    assert list(settings.INSTALLED_APPS)[-5:] == [
        "apps.servicedesk", "apps.notify", "apps.knowledge", "apps.lists", "apps.search"]
    config = apps.get_app_config("lists")
    assert type(config).__name__ == "ListsConfig"
    assert config.label == "lists"
    assert config.verbose_name == "Списки"


def test_lists_reminders_cron_entry_runs_remind_deadlines_at_0_5_in_maintenance_with_timeout_600():
    """FR-530: запись `lists_reminders`: `apps.lists.tasks.remind_deadlines`, очередь `maintenance`,
    `cron="0 5 * * *"`, `job_timeout=600`; импорт функции стоит выше первого вызова `register` (раздел 1.2)."""
    by_name = {item["name"]: item for item in cron_registrations()}
    item = by_name.get("lists_reminders")
    assert item, "нет задания lists_reminders"
    assert item["target"] == "apps.lists.tasks.remind_deadlines", f"функция задания: {item['target']}"
    assert item["queue"] == "maintenance"
    assert item["cron"] == "0 5 * * *"
    assert item["job_timeout"] == 600
    tree = ast.parse(cron_source())
    imports = [node.lineno for node in tree.body if isinstance(node, ast.ImportFrom)
               and node.module == "apps.lists.tasks" and any(a.name == "remind_deadlines" for a in node.names)]
    assert imports, "в cron.py нет `from apps.lists.tasks import remind_deadlines`"
    assert imports[0] < min(entry["line"] for entry in cron_registrations()), "импорт ниже первого register"


def test_cron_has_no_other_maintenance_entry_at_0_5():
    """FR-530: минута 0 часа 5 в очереди `maintenance` занята только `lists_reminders` (ежечасное
    `requeue_pending_scans` — очередь `mail`, это не нарушение; раздел 1.2)."""
    entries = cron_registrations()
    assert "lists_reminders" in {item["name"] for item in entries}, "нет задания lists_reminders"
    same_time = [item["name"] for item in entries
                 if item["name"] != "lists_reminders" and item["queue"] == "maintenance" and item["cron"] == "0 5 * * *"]
    assert not same_time, f"то же время в очереди maintenance у других заданий: {same_time}"
    own = [item for item in entries if item["name"] == "lists_reminders"]
    assert len(own) == 1 and own[0]["cron"] == "0 5 * * *" and own[0]["queue"] == "maintenance"


def test_cron_module_has_eighteen_register_calls():
    """FR-530: в `config/cron.py` восемнадцать вызовов `register` (семнадцать прежних и `lists_reminders`)."""
    entries = cron_registrations()
    assert len(entries) == 18, f"вызовов register {len(entries)}, ожидается 18 (17 прежних и lists_reminders)"
    assert "lists_reminders" in {item["name"] for item in entries}


def test_cron_has_no_cleanup_job_for_list_records():
    """FR-544: записи списков хранятся без срока — в cron есть одно задание модуля `lists` (`remind_deadlines`) и
    нет заданий очистки записей: ни одной другой функции из `apps.lists`, ни имени с `lists` кроме `lists_reminders`."""
    entries = cron_registrations()
    own = [item for item in entries if (item["target"] or "").startswith("apps.lists.")]
    assert [item["target"] for item in own] == ["apps.lists.tasks.remind_deadlines"], \
        f"задания модуля lists в cron: {[item['target'] for item in own]}"
    extra = [item["name"] for item in entries
             if item["name"] != "lists_reminders" and "list" in (item["name"] or "").lower()]
    assert not extra, f"лишние задания со словом list в имени: {extra}"
    assert not [item["name"] for item in entries
                if re.search(r"(purge|cleanup|retention|trash)", item["name"] or "") and "lists" in (item["target"] or "")]


# --- nginx ------------------------------------------------------------------------------------------------------------

def _check_lists_files_location(name):
    """Общая проверка для двух файлов: шаблон адреса — только загрузка файла (`/lists/<id>/<n>/files/`), скачивание
    и удаление под него не подпадают; предел тела — 55m; общий — 6m; всего четыре location с 55m (раздел 1.4)."""
    pattern, body = lists_files_location(name)
    assert pattern == LISTS_FILES_PATTERN, f"{name}: шаблон {pattern!r}"
    assert re.search(pattern, "/lists/12/34/files/")
    assert not re.search(pattern, "/lists/12/34/files/5/") and not re.search(pattern, "/lists/12/34/files/5/delete/")
    assert not re.search(pattern, "/lists/12/import/")
    assert "client_max_body_size 55m" in directives(body), f"{name}: в location нет client_max_body_size 55m"
    top = uncommented(deploy_text(name))
    assert re.search(r"^\s{4}client_max_body_size 6m;", top, re.M), f"{name}: общий предел 6m изменён"
    assert len(re.findall(r"client_max_body_size\s+55m;", top)) == 4, f"{name}: location с 55m должно быть четыре"


def test_nginx_dev_config_has_lists_files_location_with_55m_limit():
    """FR-536, NFR-505: `deploy/nginx.conf` — `location ~ ^/lists/[0-9]+/[0-9]+/files/$` с
    `client_max_body_size 55m;`; адреса скачивания и удаления под него не подпадают; общий предел 6m не менялся."""
    _check_lists_files_location("nginx.conf")


def test_nginx_prod_config_has_lists_files_location_with_55m_limit():
    """FR-536, NFR-505: то же в `deploy/nginx.prod.conf`."""
    _check_lists_files_location("nginx.prod.conf")


def test_lists_files_location_repeats_proxy_directives_in_both_configs():
    """FR-536, NFR-505: в новом `location` повторены директивы `proxy_*` (из `location /` они не наследуются):
    `proxy_pass http://portal_web`, `proxy_http_version 1.1`, `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`
    (`$scheme` в dev, `$portal_proto` в prod), `Upgrade`, `Connection`, `proxy_read_timeout 75s`; набор имён
    директив совпадает с блоком `tickets` того же файла (раздел 1.2)."""
    proto = {"nginx.conf": "$scheme", "nginx.prod.conf": "$portal_proto"}
    for name in NGINX_FILES:
        _, body = lists_files_location(name)
        own = directives(body)
        for wanted in ("proxy_pass http://portal_web", "proxy_http_version 1.1", "proxy_set_header Host $http_host",
                       "proxy_set_header X-Forwarded-For $remote_addr",
                       f"proxy_set_header X-Forwarded-Proto {proto[name]}",
                       "proxy_set_header Upgrade $http_upgrade",
                       "proxy_set_header Connection $connection_upgrade", "proxy_read_timeout 75s"):
            assert wanted in own, f"{name}: в location файлов записи нет `{wanted};`"

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


def _csp_paths():
    session, lst, record, _text, _when = _world()
    return session, ["/lists/", f"/lists/{lst.pk}/", f"/lists/{lst.pk}/{record.number}/",
                     f"/lists/{lst.pk}/{record.number}/label/"]


@PLAIN
def test_lists_pages_send_csp_without_unsafe_inline_in_script_src():
    """NFR-506: `/lists/`, `/lists/<id>/`, `/lists/<id>/<n>/`, `/lists/<id>/<n>/label/` отдают
    `Content-Security-Policy`: `script-src 'self'` без `'unsafe-inline'` и `'unsafe-eval'`; новых директив срез не
    вводит (раздел 1.1)."""
    from django.conf import settings

    session, paths = _csp_paths()
    known = {name.lower() for name in settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]}
    for path in paths:
        directives_map = _csp(session.client.get(path), path)
        assert directives_map.get("script-src") == ["'self'"], f"{path}: script-src {directives_map.get('script-src')}"
        assert not set(directives_map) - known, f"{path}: новые директивы {set(directives_map) - known}"


@PLAIN
def test_csp_img_src_on_lists_pages_allows_data_and_no_external_addresses():
    """NFR-506: `img-src 'self' data:` на страницах списков (QR этикетки — `data:`); ни `http:`, ни `https:`, ни
    `*`, ни внешних адресов."""
    session, paths = _csp_paths()
    for path in paths:
        sources = _csp(session.client.get(path), path).get("img-src")
        assert sources is not None, f"{path}: нет img-src"
        assert sorted(sources) == ["'self'", "data:"], f"{path}: img-src {sources}"
        assert not [s for s in sources if s in ("http:", "https:", "*") or "//" in s or "." in s]


# --- шаблоны и скрипты ------------------------------------------------------------------------------------------------

def _template_files() -> list:
    root = BACKEND_DIR / "templates" / "lists"
    assert root.is_dir(), f"нет каталога шаблонов {root}"
    found = sorted(root.rglob("*.html"))
    assert found, "в templates/lists нет шаблонов"
    return found


def _tags(text: str) -> list[str]:
    return re.findall(r"<[A-Za-z][^<>]*>", text)


def test_lists_templates_have_no_style_attribute():
    """NFR-506: в `templates/lists/` нет атрибута `style=`; шаблоны на месте (раздел 1.1)."""
    files = _template_files()
    bad = [str(path.relative_to(BACKEND_DIR)) for path in files
           if any(re.search(r"\sstyle\s*=", tag, re.I) for tag in _tags(path.read_text(encoding="utf-8")))]
    assert not bad, f"атрибут style= в шаблонах: {bad}"


def test_lists_templates_have_no_inline_event_handlers():
    """NFR-506: в `templates/lists/` нет атрибутов обработчиков `on…=`."""
    files = _template_files()
    bad = [str(path.relative_to(BACKEND_DIR)) for path in files
           if any(re.search(r"\son[a-z]+\s*=", tag, re.I) for tag in _tags(path.read_text(encoding="utf-8")))]
    assert not bad, f"обработчики on…= в шаблонах: {bad}"


def _visible(html: str) -> str:
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


@PLAIN
def test_lists_scripts_are_external_files_in_static_lists():
    """NFR-506: `static/lists/lists.js` и `lists.css` — внешние файлы без `eval(` и `new Function`; шаблоны страниц
    списков подключают их тегами `<script defer src=…>` и `<link rel="stylesheet">`; встроенных скриптов в шаблонах
    нет; `_assets.html` файлов среза не подключает (решение 59 задач; раздел 1.1)."""
    for name in ("lists.js", "lists.css", "labels.css"):
        path = BACKEND_DIR / "static" / "lists" / name
        assert path.is_file(), f"нет файла static/lists/{name}"
        assert path.read_text(encoding="utf-8").strip(), f"{name}: пустой файл"
    script = (BACKEND_DIR / "static" / "lists" / "lists.js").read_text(encoding="utf-8")
    assert "eval(" not in script and "new Function" not in script, "lists.js: eval или new Function"
    assets = (BACKEND_DIR / "templates" / "_assets.html").read_text(encoding="utf-8")
    assert "static/lists" not in assets and "lists/lists." not in assets, "_assets.html подключает файлы среза"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in _template_files())
    for tag in re.findall(r"<script\b[^>]*>", sources, re.I):
        assert re.search(r"\bsrc\s*=", tag), f"встроенный скрипт без src в шаблонах: {tag}"
    assert re.search(r"<script\b(?=[^>]*\bdefer\b)(?=[^>]*\bsrc=\"[^\"]*lists/lists[^\"/]*\.js\")[^>]*>", sources), \
        "в шаблонах нет <script defer src=…lists/lists.js>"
    assert re.search(r"<link\b(?=[^>]*\brel=\"stylesheet\")(?=[^>]*\bhref=\"[^\"]*lists/lists[^\"/]*\.css\")[^>]*>",
                     sources), "в шаблонах нет <link rel=\"stylesheet\" href=…lists/lists.css>"
    session, lst, record, _text, _when = _world()
    html = session.client.get(f"/lists/{lst.pk}/").content.decode()
    assert re.search(r"<script\b(?=[^>]*\bdefer\b)[^>]*\bsrc=\"[^\"]*lists/lists[^\"/]*\.js\"", html), \
        "страница списка не подключает lists.js"
    assert re.search(r"<link\b[^>]*\bhref=\"[^\"]*lists/lists[^\"/]*\.css\"", html), "страница списка не подключает lists.css"


# --- язык и время -----------------------------------------------------------------------------------------------------

@PLAIN
def test_lists_pages_texts_are_russian():
    """NFR-510: страницы списков по-русски: названные в 12.4 надписи на месте, английских надписей интерфейса нет;
    страницы — `support_lists.list_pages(lst, record)` (раздел 1.1)."""
    session, lst, record, _text, _when = _world()
    base, card = f"/lists/{lst.pk}/", f"/lists/{lst.pk}/{record.number}/"
    labels = {
        "/lists/": ("Списки", "Создать список"),
        base: ("Добавить запись", "Загрузить из таблицы", "Все", "Архив"),
        base + "settings/": ("Основное", "Поля", "Права"),
        base + "settings/fields/": ("Основное", "Поля", "Права", "Добавить поле"),
        base + "settings/access/": ("Читают", "Правят"),
        card: ("Изменить", "В архив", "Этикетка", "История"),
    }
    paths = lists.list_pages(lst, record)
    assert set(labels) <= set(paths), "страницы с надписями не входят в list_pages"
    for path in paths:
        response = session.client.get(path)
        assert response.status_code == 200, f"{path}: статус {response.status_code}"
        text = _visible(response.content.decode())
        assert len(re.findall("[а-яА-ЯёЁ]{3,}", text)) >= 3, f"{path}: русского текста нет"
        for label in labels.get(path, ()):
            assert label in text, f"{path}: нет надписи «{label}»"
        for word in ENGLISH_WORDS:
            assert not re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text), f"{path}: английская надпись {word!r}"


def _marks(html: str) -> list[tuple[str, str]]:
    return [(attrs, re.sub(r"\s+", " ", text).strip())
            for attrs, text in re.findall(r"<time\b([^>]*\bdata-at\b[^>]*)>(.*?)</time>", html, re.S)]


def _check_marks(html: str, path: str, moment: datetime, shown: str, utc_text: str, *, at_least: int = 1):
    marks = _marks(html)
    assert len(marks) >= at_least, f"{path}: time[data-at] — {len(marks)}, ожидается не меньше {at_least}"
    for attrs, text in marks:
        assert text == shown, f"{path}: время {text!r}, ожидается {shown!r}"
        iso = re.search(r'datetime="([^"]+)"', attrs)
        assert iso, f"{path}: у time нет datetime"
        assert datetime.fromisoformat(iso.group(1).replace("Z", "+00:00")) == moment, f"{path}: datetime {iso.group(1)}"
    assert utc_text not in html, f"{path}: время в UTC {utc_text!r}"


@PLAIN
def test_lists_times_are_shown_in_moscow_at_utc_midnight_in_dates_history_and_import_summary(clock):
    """NFR-510: часы на полночь UTC 10.03.2026 (в Москве — 03:00) и на 21:30 UTC того же дня (в Москве уже 11.03.2026
    00:30): значение «дата и время» в карточке и таблице, строка истории и итог загрузки показывают время по
    Москве в `time[data-at]` (атрибут `datetime` — тот же момент); время в UTC в разметке не встречается (раздел 1.1)."""
    from apps.lists.services import history

    Change = support.model("lists.Change")
    cases = ((datetime(2026, 3, 10, 0, 0, tzinfo=dt_timezone.utc), "10.03.2026 03:00", "10.03.2026 00:00"),
             (datetime(2026, 3, 10, 21, 30, tzinfo=dt_timezone.utc), "11.03.2026 00:30", "10.03.2026 21:30"))
    for moment, shown, utc_text in cases:
        assert lists.moscow_text(moment) == shown
        clock.set(moment)
        session, lst, record, _text, when_field = _world()
        stored = moment.strftime("%Y-%m-%dT%H:%M:00Z")
        record.values = {**record.values, when_field.code: stored}
        record.save(update_fields=["values"])
        change = history.write(record, "created", [], session.user)
        Change.objects.filter(pk=change.pk).update(at=moment)
        card = f"/lists/{lst.pk}/{record.number}/"
        # значение «дата и время» в карточке; все отметки времени карточки — один и тот же момент
        html = session.client.get(card).content.decode()
        _check_marks(html, card, moment, shown, utc_text)
        assert re.search(r"data-lists-value=\"" + re.escape(when_field.code) + r"\"[^>]*>(?:(?!</li>|</tr>|</div>).)*?"
                         + re.escape(shown), html, re.S), f"{card}: значения поля нет в [data-lists-value]"
        # история
        history_path = card + "history/"
        response = session.client.get(history_path)
        assert response.status_code == 200
        _check_marks(response.content.decode(), history_path, moment, shown, utc_text)
        assert 'data-change-kind="created"' in response.content.decode()
        # таблица
        grid = session.client.get(f"/lists/{lst.pk}/").content.decode()
        assert shown in grid and utc_text not in grid, f"таблица: время не по Москве ({shown})"
        # итог загрузки
        upload = session.client.post(f"/lists/{lst.pk}/import/", {
            "file": SimpleUploadedFile("загрузка.csv", lists.csv_of(["Название"], [["Из файла"]]), "text/csv")})
        assert upload.status_code == 302, f"загрузка файла: статус {upload.status_code}"
        job_path = upload["Location"]
        assert re.fullmatch(rf"/lists/{lst.pk}/import/\d+/", job_path), job_path
        preview = session.client.post(job_path, {"map.0": "title"})
        assert preview.status_code == 200
        done = session.client.post(job_path + "confirm/")
        assert done.status_code == 200
        html = done.content.decode()
        assert 'data-lists-notice="import-summary"' in html, "нет итога загрузки"
        tail = html[html.index('data-lists-notice="import-summary"'):]
        _check_marks(tail, job_path + "confirm/", moment, shown, utc_text)


# --- нагрузка ---------------------------------------------------------------------------------------------------------

def test_load_suite_has_fill_lists_script_requiring_stand_flag_and_lists_user_class():
    """NFR-513: `backend/tests/load/fill_lists.py` есть: без `E2E_STAND=1` — `sys.exit` с текстом контракта до
    импорта моделей; строка итога `fill_lists: lists=… records=…`; в `locustfile.py` есть класс `ListsUser` с
    `wait_time`; нагрузка не запускается (раздел 13.2)."""
    load = BACKEND_DIR / "tests" / "load"
    script = load / "fill_lists.py"
    assert script.is_file(), "нет backend/tests/load/fill_lists.py"
    text = script.read_text(encoding="utf-8")
    assert "E2E_STAND" in text
    assert "fill_lists: lists=" in text and "records=" in text
    tree = ast.parse(text)
    guard = None
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.If) and "E2E_STAND" in ast.get_source_segment(text, node.test):
            guard = index
            break
    assert guard is not None, "нет проверки E2E_STAND на верхнем уровне"
    body = ast.get_source_segment(text, tree.body[guard])
    assert re.search(r"sys\.exit\(", body) and REFUSAL_LOAD in body, "нет sys.exit с текстом контракта 13.2"
    for node in tree.body[:guard]:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            assert not [item for item in names if item.split(".")[0] in ("apps", "django")], \
                f"импорт {names} раньше проверки стенда"
    locust_text = (load / "locustfile.py").read_text(encoding="utf-8")
    classes = {node.name: node for node in ast.parse(locust_text).body if isinstance(node, ast.ClassDef)}
    assert "ListsUser" in classes, "в locustfile.py нет класса ListsUser"
    assert "wait_time" in ast.get_source_segment(locust_text, classes["ListsUser"])


# --- том protected и резервная копия ----------------------------------------------------------------------------------

NGINX_PROTECTED = ["/protected/attachments/", "/protected/inbound/", "/protected/"]
COMPOSE_VOLUMES = ["postgres-data", "valkey-data", "clamav-db", "test-venv", "media", "protected", "backups"]


@PLAIN
def test_record_files_live_in_protected_volume_and_backup_script_and_restore_guide_are_unchanged(
        protected_root, django_capture_on_commit_callbacks):
    """NFR-514, NFR-505: файл записи кладётся в том `protected` (`incoming/<id>` под `PROTECTED_ROOT`, строка
    `StoredFile` с `purpose="lists"`); новых томов и внутренних `location` nginx нет; `backup/backup.sh` и
    `RESTORE.md` слова `lists` не содержат (раздел 1.2)."""
    from apps.core.services import files as core_files
    from apps.lists.services import files as record_files

    lst = lists.make_list()
    file_field = lists.add_field(lst, "file", "Файлы")
    session = lists.as_editor(lst)
    record = lists.make_record(lst, "Договор", created_by=session.user)
    body = b"%PDF-1.4\n% test body\n"
    with django_capture_on_commit_callbacks(execute=False):
        row = record_files.attach(lst, record.number, field_code=file_field.code, name="акт.pdf", data=body,
                                  actor=session.user)
    stored = row.file
    assert stored.purpose == "lists"
    path = core_files.attachment_path(stored)
    assert path.parent.parent == protected_root and path.parent.name in ("incoming", "attachments")
    assert path.read_bytes() == body
    for name in NGINX_FILES:
        text = uncommented(deploy_text(name))
        internal = re.findall(r"location\s+(\S+)\s*\{", text)
        assert [item for item in internal if item.startswith("/protected/")] == NGINX_PROTECTED, \
            f"{name}: набор внутренних location изменён"
    compose = uncommented(deploy_text("docker-compose.yml")) + "\n"
    volumes = re.search(r"^volumes:\s*\n((?:  \S.*\n)+)", compose, re.M)
    assert volumes
    assert re.findall(r"^  ([A-Za-z0-9_-]+):", volumes.group(1), re.M) == COMPOSE_VOLUMES
    for name in (("backup", "backup.sh"), ("RESTORE.md",)):
        assert not re.search(r"(?i)\blists\b", deploy_text(*name)), f"{'/'.join(name)}: упоминание списков"


# --- словарь текстов (решение 25 задач, И3, П5) ----------------------------------------------------------------------

# Дословно из CONTRACT-006, разделы 12.1–12.3 (обычный пробел U+0020 в числах); `{…}` — подстановки `str.format`.
TEXTS_12_1 = {
    "unique_taken": "Такое значение уже есть в списке",
    "required": "Обязательное поле",
    "too_long": "Предел: {limit} знаков",
    "required_new_with_records": "Сначала заполните поле у всех записей",
    "unique_repeats": "Значения повторяются: {items}",
    "required_missing": "Не заполнено у записей: {items}",
    "list_has_records": "Нельзя удалить: есть записи",
    "list_referenced": "Нельзя удалить: на список ссылается поле {field} списка {list}",
    "unit_in_records": "подразделение указано в {count} записях списков",
    "unit_in_access": "указано в правах списков: {names}",
    "role_in_access": "Нельзя удалить: указано в правах списков: {names}.",
    "record_referenced": "Нельзя удалить: на запись ссылаются записи: {links}",
    "files_limit": "У записи уже 20 файлов",
    "file_too_big": "Файл больше 20 МБ",
    "file_type_refused": "Файл такого типа не принимается",
    "labels_too_many": "Не больше 100 записей",
    "export_too_many": "Уточните отбор: записей больше 10 000",
    "import_too_big": "Файл больше 5 МБ",
    "import_too_many_rows": "Строк больше 5 000",
    "import_bad_format": "Формат не поддерживается",
    "version_conflict": "Запись уже изменил {who} в {when}",
    "record_archived": "Запись в архиве",
    "record_gone": "Запись удалена",
    "query_short": "Введите не меньше 2 знаков",
    "home_empty": "Списков пока нет. Список — это ваш реестр: оборудование, лицензии, договоры. Создайте первый",
    "home_empty_reader": "Вам пока не открыт ни один список",
    "grid_empty": "В списке пока нет записей",
}
TEXTS_12_2 = {
    "field_has_file": "В поле уже есть файл",
    "import_repeat_in_file": "Значение повторяется в строке {row}",
    "import_no_title": "Не указано название",
    "choice_archived_exists": "Такое значение есть в архиве значений — верните его",
    "field_hidden_meanwhile": "Поле скрыто администратором, значение не сохранится",
    "bulk_result": "В архив: {archived}, пропущено: {skipped}",
    "bulk_too_many": "Не больше 50 записей за раз",
    "vectors_stale": "Поиск по списку обновляется",
    "query_long": "Запрос не длиннее 200 знаков",
}
TEXTS_12_3 = {
    "name_taken": "Список с таким названием уже есть",
    "field_name_taken": "Поле с таким названием уже есть",
    "choice_name_taken": "Такое значение уже есть",
    "fields_limit": "Не больше 50 полей",
    "choices_limit": "Не больше 200 значений",
    "property_not_allowed": "Это свойство недоступно для такого типа поля",
    "thresholds_bad": "Порог — целое число от 1 до 365, не больше трёх порогов, без повторов",
    "currency_bad": "Валюта: RUB, USD или EUR",
    "target_required": "Выберите список",
    "field_has_data": "Нельзя удалить: в поле есть данные",
    "field_locked": "У поля с данными это не меняется",
    "multiple_in_use": "Нельзя выключить: есть записи с несколькими значениями",
    "bad_order": "Порядок полей изменился, обновите страницу",
    "line_break": "Без переносов строк",
    "bad_number": "Введите число",
    "number_digits": "Не больше 15 значащих цифр, до и после запятой — не больше 15",
    "money_digits": "Не больше 13 цифр до запятой и двух после",
    "bad_date": "Введите дату ДД.ММ.ГГГГ",
    "bad_datetime": "Введите дату и время ДД.ММ.ГГГГ ЧЧ:ММ",
    "value_unavailable": "Это значение выбрать нельзя",
    "import_not_found": "Не найдено: {value}",
    "import_ambiguous": "Неоднозначно: {value}",
    "import_two_records": "Уникальные поля указывают на разные записи",
    "import_time_missing": "Укажите время: ДД.ММ.ГГГГ ЧЧ:ММ",
    "bad_file_field": "Выберите поле для файла",
    # ответ 53 (CONTRACT-006, 12.3, 15.3; образец CONTRACT-005, решение 41)
    "write_failed": "Не удалось сохранить файл",
}
# ключи, у которых словарь может хранить фразу вместе с соседней ссылкой: проверяем вхождением. `record_referenced` —
# ровно «…: {links}», хвост собирает служба (ответ 61, CONTRACT-006, 12.1, 15.3): сверяется равенством
CONTAINS_ONLY = ("unique_taken",)
PROBE_NAMES = ("limit", "items", "field", "list", "count", "names", "links", "hidden", "who", "when", "archived",
               "skipped", "row", "value", "number", "url")
PROBE = {name: f"‹{name}›" for name in PROBE_NAMES}


@PLAIN
def test_lists_texts_dictionary_contains_every_key_and_text_of_contract_12_1_to_12_3():
    """FR-546: словарь `apps.lists.texts.TEXTS` содержит каждый код и дословный текст таблиц 12.1–12.3 контракта;
    тексты с подстановками сверяются после `str.format` с одинаковыми пробными значениями (решение 25 задач, И3)."""
    from apps.lists.texts import TEXTS

    expected = {**TEXTS_12_1, **TEXTS_12_2, **TEXTS_12_3}
    assert len(expected) == len(TEXTS_12_1) + len(TEXTS_12_2) + len(TEXTS_12_3), "коды таблиц повторяются"
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
        if code in CONTAINS_ONLY:
            if wanted not in shown:
                problems.append(f"{code}: {shown!r} не содержит {wanted!r}")
        elif shown != wanted:
            problems.append(f"{code}: {shown!r} вместо {wanted!r}")
    assert not problems, "тексты словаря расходятся с контрактом:\n" + "\n".join(problems)
