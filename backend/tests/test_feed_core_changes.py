"""T-7137: изменения ядра, `org`, `knowledge` и прежнее поведение (FR-601, FR-605, FR-612, FR-624, FR-626, FR-633, FR-641).

План: «Изменения кода прежних срезов» — строки `core/extensions.py` (точка `home_body`), `core/views/pages.py` и шаблоны
главной, `core/context.py` и `menu_for`, `templates/base.html`, `core/models/files.py`, `core/services/comments.py`,
`core/services/pdn_patterns.py` и `knowledge/services/pdn.py`, `org/services/structure.py`; «Модель данных» — «Ядро и
прежние модули». Контракт: CONTRACT-007, 3.1 (ядро), 4.1 (`org.services.structure`), 2.1 (`StoredFile.Purpose.FEED`),
решения контракта К12 (текст узла числа при нуле), К14 (`subtree_member_ids`, `unit_chains`).

Каждое изменение проверяется вместе с тестом прежнего поведения. Заглушки точек расширения (`home_body`, `menu_items`,
`home_notices`) регистрируются внутри `support_feed.without_feed()`: регистрации ленты на время блока сняты, прочее ядро
остаётся (так прежняя главная проверяется на том же реестре, что и в портале). Код среза на уровне модуля не
импортируется."""
import ast
import contextlib
import inspect
import json
import re
from datetime import timedelta

import pytest
from django.http import HttpResponse

from tests import support
from tests import support_feed as feed
from tests import support_org as org

pytestmark = pytest.mark.django_db

POINTS_17 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
             "notification_kinds", "top_bar_items", "search_providers", "ticket_card_parts")
# выражения `knowledge/services/pdn.py:11-12` до среза 007, дословно
EMAIL_PATTERN = r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}(?![\w-])"
PHONE_PATTERN = r"(?<![\d+])(?:\+7|8)[ \t\-()]*(?:\d[ \t\-()]*){9}\d(?!\d)"
MENU_KEYS = {"url", "title", "icon", "order"}


# --- помощники только этого файла -------------------------------------------------------------------------------------

@contextlib.contextmanager
def _registered(point: str, func):
    """Временная регистрация функции в точке ядра (снимается после блока, даже внутри `without_feed`)."""
    from apps.core import extensions

    extensions.register(point, func)
    try:
        yield
    finally:
        registry = extensions._registry[point]
        if func in registry:
            registry.remove(func)


def _menu_links(html: str) -> list[tuple[str, str]]:
    """Пункты `nav#main-menu` по порядку: (адрес, подпись)."""
    nav = re.search(r'<nav id="main-menu".*?</nav>', html, re.S)
    assert nav, "в оболочке нет nav#main-menu"
    return [(href, re.sub(r"\s+", " ", label).strip()) for href, label in re.findall(
        r'<a class="menu-item[^"]*" href="([^"]*)"[^>]*>.*?<span class="menu-label">(.*?)</span>', nav.group(0), re.S)]


def _item_block(html: str, href: str) -> str:
    found = re.search(r'<a class="menu-item[^"]*" href="' + re.escape(href) + r'".*?</a>', html, re.S)
    assert found, f"в меню нет пункта {href}"
    return found.group(0)


def _probe_menu(state: dict, *, live: str | None = None, href: str = "/probe-core/"):
    def menu_items():
        item = {"permissions": (), "url": href, "title": "Проба ядра", "icon": "icons/gear.html", "order": 90,
                "visible": lambda user: True, "badge": lambda user: state["count"]}
        if live:
            item["live_badge"] = live
        return [item]

    return menu_items


def _page(client, path="/me/"):
    response = client.get(path)
    assert response.status_code == 200, f"{path}: статус {response.status_code}"
    return response.content.decode()


# --- core/extensions.py: точка home_body ------------------------------------------------------------------------------

def test_points_end_with_home_body_as_eighteenth_point():
    """FR-641: `POINTS` ядра — восемнадцать имён, `home_body` последней; `_registry` содержит ключ на каждое имя
    (CONTRACT-007, 3.1; `support_feed.POINTS_007`)."""
    from apps.core import extensions

    assert len(extensions.POINTS) == 18
    assert extensions.POINTS[-1] == "home_body" and tuple(extensions.POINTS[17:]) == feed.POINTS_007
    assert set(extensions._registry) == set(extensions.POINTS)


def test_previous_seventeen_points_keep_their_order():
    """FR-641: прежние семнадцать точек — в прежнем порядке (срезы `[:9]` и `[9:15]` прежних тестов не сдвигаются)."""
    from apps.core import extensions

    assert tuple(extensions.POINTS[:17]) == POINTS_17
    assert tuple(extensions.POINTS[:9]) == POINTS_17[:9] and tuple(extensions.POINTS[9:15]) == POINTS_17[9:15]


def test_home_body_uses_first_registered_function_and_skips_others():
    """FR-601, FR-641: `core.views.pages.home` отдаёт ответ первой зарегистрированной функции `home_body`
    (`(request) -> HttpResponse`) и прочие не зовёт; функции вызывается запрос вошедшего сотрудника."""
    user = support.make_employee()
    client = support.logged_in(user)
    calls = []

    def first(request):
        calls.append(("first", request.user.pk))
        return HttpResponse("ПЕРВАЯ")

    def second(request):
        calls.append(("second", request.user.pk))
        raise AssertionError("вторая функция home_body не должна вызываться")

    with feed.without_feed():
        with _registered("home_body", first), _registered("home_body", second):
            response = client.get("/")
    assert response.status_code == 200 and response.content.decode() == "ПЕРВАЯ"
    assert calls == [("first", user.pk)]


def test_home_with_empty_home_body_point_renders_previous_home_template():
    """FR-641: точка `home_body` пуста — прежний `home.html`: приветствие по имени, описание портала, карточки «Мой
    профиль» и «Безопасность», заголовок вкладки «Главная»."""
    user = support.make_employee()
    client = support.logged_in(user)
    with feed.without_feed():
        response = client.get("/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "home.html" in [t.name for t in response.templates]
    assert f"Здравствуйте, {user.full_name}!" in html
    assert "Добро пожаловать в портал" in html
    assert 'href="/me/"' in html and "Мой профиль" in html and 'href="/me/security/"' in html and "Безопасность" in html
    assert re.search(r"<title>\s*Главная", html)


# --- core/views/pages.py и templates/_home_notices.html ---------------------------------------------------------------

def test_collect_notices_returns_same_as_previous_home_loop():
    """FR-601: `pages.collect_notices(user)` — тот же список, что строил прежний цикл `home` по `home_notices` (функции в
    порядке регистрации, результаты склеены); без функций — пустой список."""
    from apps.core import extensions
    from apps.core.views import pages

    user = support.make_employee()
    one = [{"key": "probe-1", "text": "Первое"}, {"key": "probe-2", "text": "Второе", "year": 2026}]
    two = [{"key": "probe-3", "text": "Третье", "url": "/lists/", "link": "Открыть"}]

    def func_one(person):
        assert person.pk == user.pk
        return one

    def func_two(person):
        return two

    def func_empty(person):
        return []

    with extensions.empty():
        assert pages.collect_notices(user) == []
        for func in (func_one, func_empty, func_two):
            extensions.register("home_notices", func)
        found = pages.collect_notices(user)
        previous = []
        for func in extensions.registered("home_notices"):
            previous.extend(func(user))
    assert isinstance(found, list) and found == previous == one + two


def test_home_notices_fragment_keeps_previous_data_home_notices_notice_and_year_markup():
    """FR-601, FR-641: общий фрагмент `templates/_home_notices.html` даёт прежнюю разметку `[data-home-notices]` →
    `div.alert.alert-<уровень>[role=status][data-notice][data-year]`, ссылку с текстом (по умолчанию «Перейти»),
    уровень по умолчанию `warning`; без напоминаний блока нет; в `home.html` он подключён один раз, прежнего цикла там
    нет; в `feed/body.html` — один раз."""
    root = support.BACKEND_DIR / "templates"
    fragment = root / "_home_notices.html"
    assert fragment.is_file(), "нет templates/_home_notices.html"
    includes = re.compile(r"\{%\s*include\s+[\"']_home_notices\.html[\"']")
    home_source = (root / "home.html").read_text(encoding="utf-8")
    assert len(includes.findall(home_source)) == 1, "в home.html фрагмент подключён не один раз"
    assert "data-home-notices" not in home_source and "data-notice" not in home_source, "в home.html остался цикл"
    body = root / "feed" / "body.html"
    assert body.is_file(), "нет templates/feed/body.html"
    assert len(includes.findall(body.read_text(encoding="utf-8"))) == 1, "в feed/body.html фрагмент подключён не один раз"

    def notices(user):
        return [{"key": "probe-a", "level": "info", "text": "Проба А", "url": "/lists/", "link": "Открыть", "year": 2026},
                {"key": "probe-b", "text": "Проба Б", "url": "/lists/"},
                {"key": "probe-c", "text": "Проба В"}]

    client = support.logged_in(support.make_employee())
    with feed.without_feed():
        quiet = _page(client, "/")
        with _registered("home_notices", notices):
            html = re.sub(r"\s+", " ", _page(client, "/"))
    assert "data-home-notices" not in quiet, "блок напоминаний при пустом списке"
    assert re.search(r"<div data-home-notices>", html)
    def block(key: str) -> str:
        found = re.search(r'<div class="alert alert-(\w+)" role="status" data-notice="' + key + r'"([^>]*)>(.*?)</div>',
                          html, re.S)
        assert found, f"нет напоминания {key}"
        return found.group(0)

    one, two, three = block("probe-a"), block("probe-b"), block("probe-c")
    assert 'class="alert alert-info"' in one and 'data-year="2026"' in one and "Проба А" in one
    assert re.search(r'<a href="/lists/">\s*Открыть\s*</a>', one)
    assert 'class="alert alert-warning"' in two and "data-year" not in two and "Проба Б" in two
    assert re.search(r'<a href="/lists/">\s*Перейти\s*</a>', two)
    assert 'class="alert alert-warning"' in three and "data-year" not in three and "Проба В" in three and "<a " not in three
    assert html.count("data-year=") == 1


# --- core/context.py: «Главная» и первый пункт меню -------------------------------------------------------------------

def test_shell_omits_home_item_when_menu_has_root_url_item_and_puts_that_item_first():
    """FR-601: если среди пунктов `menu_for` есть пункт с `url="/"`, `context.shell` не добавляет «Главную», а ставит
    этот пункт первым (в разметке одна ссылка на `/`)."""
    def root_menu():
        return [{"permissions": (), "url": "/", "title": "Корень пробы", "icon": "icons/gear.html", "order": 0,
                 "visible": lambda user: True}]

    client = support.logged_in(support.make_employee())
    with feed.without_feed():
        with _registered("menu_items", root_menu):
            links = _menu_links(_page(client, "/me/"))
    assert links[0] == ("/", "Корень пробы"), f"первый пункт: {links[0]}"
    assert ("/", "Главная") not in links
    assert [href for href, _ in links].count("/") == 1


def test_shell_without_root_url_item_puts_home_item_first():
    """FR-641: без пункта с `url="/"` — прежняя «Главная» первой (`/`, значок дома), прочие пункты за ней."""
    client = support.logged_in(support.make_admin())
    with feed.without_feed():
        html = _page(client, "/me/")
    links = _menu_links(html)
    assert links[0] == ("/", "Главная"), f"первый пункт: {links[0]}"
    assert [href for href, _ in links].count("/") == 1 and len(links) > 3


# --- core/services/permissions.py: menu_for и live_badge ---------------------------------------------------------------

def test_menu_for_passes_live_badge_only_to_item_declaring_it():
    """FR-626: элемент `menu_for` получает ключ `live_badge` (строка как есть) только если пункт его объявил; у соседнего
    пункта ключа нет; `badge` вычисляется вызовом `badge(user)` у обоих."""
    from apps.core.services import permissions

    user = support.make_employee()

    def probe():
        return [{"permissions": (), "url": "/probe-a/", "title": "Проба А", "icon": "icons/gear.html", "order": 90,
                 "visible": lambda person: True, "badge": lambda person: 5, "live_badge": "probe-a"},
                {"permissions": (), "url": "/probe-b/", "title": "Проба Б", "icon": "icons/gear.html", "order": 91,
                 "visible": lambda person: True, "badge": lambda person: 3}]

    with feed.without_feed():
        with _registered("menu_items", probe):
            items = {item["url"]: item for item in permissions.menu_for(user)}
    assert items["/probe-a/"]["live_badge"] == "probe-a" and items["/probe-a/"]["badge"] == 5
    assert "live_badge" not in items["/probe-b/"] and items["/probe-b/"]["badge"] == 3
    assert set(items["/probe-b/"]) == MENU_KEYS | {"badge"}


def test_menu_for_keys_of_other_items_unchanged():
    """FR-641: у пунктов без `live_badge` ключи прежние — `url`, `title`, `icon`, `order`, а `badge` — только у тех, что
    его объявили; других ключей (`permissions`, `visible`) в элементе нет."""
    from apps.core.services import permissions

    admin = support.make_admin()
    with feed.without_feed():
        items = permissions.menu_for(admin)
    assert len(items) > 5
    for item in items:
        assert set(item) - {"badge"} == MENU_KEYS, f"{item['url']}: ключи {sorted(item)}"
        assert "live_badge" not in item


# --- templates/base.html: узел живого числа и прежнее число ------------------------------------------------------------

def _live_node(html: str, name: str):
    found = re.search(r'<span\b([^>]*\bid="menu-badge-' + name + r'"[^>]*)>(.*?)</span>', html, re.S)
    assert found, f"нет узла #menu-badge-{name}"
    return found.group(1), re.sub(r"\s+", " ", found.group(2)).strip()


def _render_live(count: int):
    state = {"count": count}
    client = support.logged_in(support.make_employee())
    with feed.without_feed():
        with _registered("menu_items", _probe_menu(state, live="probe")):
            return _page(client, "/me/")


def test_base_renders_live_badge_node_always_hidden_at_zero_with_data_count_and_live_marker():
    """FR-626 (К12): у пункта с `live_badge` узел `<span id="menu-badge-<live_badge>" class="badge …"
    data-menu-live-badge data-count="<N>">` есть всегда и внутри ссылки пункта: при нуле — класс `d-none`,
    `data-count="0"`, текст «0»; `data-menu-badge` у узла нет; при числе больше нуля `d-none` нет."""
    html = _render_live(0)
    attrs, text = _live_node(html, "probe")
    assert "data-menu-live-badge" in attrs and 'data-count="0"' in attrs
    assert "d-none" in re.search(r'class="([^"]*)"', attrs).group(1).split() and "badge" in attrs
    assert "data-menu-badge" not in attrs.replace("data-menu-live-badge", "")
    assert text == "0"
    assert 'id="menu-badge-probe"' in _item_block(html, "/probe-core/")
    assert "data-menu-badge" not in re.sub(r"data-menu-live-badge", "", _item_block(html, "/probe-core/"))
    attrs, text = _live_node(_render_live(7), "probe")
    assert 'data-count="7"' in attrs and "d-none" not in re.search(r'class="([^"]*)"', attrs).group(1).split()
    assert text == "7"


def test_base_live_badge_shows_99_plus_above_99():
    """FR-626: текст узла — цифры при числе до 99 включительно и «99+» при числе больше 99; `data-count` — число как
    есть; узел виден (`d-none` нет)."""
    for count, shown in ((99, "99"), (100, "99+"), (120, "99+")):
        attrs, text = _live_node(_render_live(count), "probe")
        assert text == shown, f"при {count}: текст {text!r}"
        assert f'data-count="{count}"' in attrs, f"при {count}: {attrs}"
        assert "d-none" not in re.search(r'class="([^"]*)"', attrs).group(1).split()


def test_base_other_items_have_data_menu_badge_only_above_zero_in_digits():
    """FR-641: у пунктов без `live_badge` прежняя разметка — `span[data-menu-badge]` только при числе больше нуля,
    цифрами; узла `#menu-badge-…` и `data-menu-live-badge` у них нет."""
    state = {"count": 0}
    client = support.logged_in(support.make_employee())
    with feed.without_feed():
        with _registered("menu_items", _probe_menu(state)):
            for count, expected in ((0, None), (7, "7"), (120, "120")):
                state["count"] = count
                block = _item_block(_page(client, "/me/"), "/probe-core/")
                marks = re.findall(r"<span[^>]*\bdata-menu-badge(?![\w-])[^>]*>(.*?)</span>", block, re.S)
                if expected is None:
                    assert not marks, "при нуле числа нет"
                else:
                    assert [m.strip() for m in marks] == [expected]
                assert "data-menu-live-badge" not in block and 'id="menu-badge-' not in block


def test_base_htmx_config_unchanged_with_default_allow_script_tags():
    """FR-641: `<meta name="htmx-config">` не менялся — `{"allowEval":false,"includeIndicatorStyles":false}`, ключа
    `allowScriptTags` нет (по умолчанию htmx выполняет теги `script`; среда не вставляет их во фрагменты)."""
    client = support.logged_in(support.make_employee())
    for path in ("/me/", "/"):
        html = _page(client, path)
        found = re.search(r'<meta name="htmx-config" content=\'([^\']*)\'>', html)
        assert found, f"{path}: нет meta htmx-config"
        assert found.group(1) == '{"allowEval":false,"includeIndicatorStyles":false}', found.group(1)
        assert json.loads(found.group(1)) == {"allowEval": False, "includeIndicatorStyles": False}


# --- core/models/files.py и миграция 0010 ------------------------------------------------------------------------------

def test_stored_file_purpose_feed_is_last_and_previous_values_unchanged():
    """FR-633: `StoredFile.Purpose.FEED = "feed"` («вложение ленты») — последним; прежние четыре значения и подписи те
    же; `max_length` 16 и значение по умолчанию `photo` не менялись; миграция `core 0010_storedfile_feed_purpose` — одна
    операция `AlterField` поля `purpose` (зависит от `0009`); строку с назначением `feed` можно создать."""
    StoredFile = support.model("core.StoredFile")
    assert StoredFile.Purpose.choices == [
        ("photo", "фото"), ("attachment", "вложение"), ("knowledge", "файл статьи"),
        ("lists", "файл записи списка"), ("feed", "вложение ленты")]
    assert StoredFile.Purpose.FEED == "feed" and list(StoredFile.Purpose.values)[-1] == "feed"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"
    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0010_storedfile_feed_purpose.py"
    assert path.is_file(), "нет миграции core/0010_storedfile_feed_purpose.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0009_storedfile_lists_purpose")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and isinstance(operations[0], ast.Call) and operations[0].func.attr == "AlterField"
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in operations[0].keywords if kw.arg in ("model_name", "name")}
    assert keywords == {"model_name": "storedfile", "name": "purpose"}
    row = StoredFile.objects.create(purpose="feed", owner=None, size=1, sha256="0" * 64,
                                    content_type="application/octet-stream", status="pending")
    row.refresh_from_db()
    assert row.purpose == "feed"


# --- core/services/comments.py -----------------------------------------------------------------------------------------

def test_comments_update_strips_edges_accepts_1_and_4000_chars_and_saves_text():
    """FR-624: `comments.update(comment, text)` обрезает пробелы по краям, принимает от 1 до 4000 знаков, сохраняет
    `text`, возвращает тот же комментарий (номер, автор, `object_ref`, `created_at` не меняются)."""
    from apps.core.services import comments

    author = support.make_employee()
    comment = comments.add(author, "probe.object:1", "Старый текст")
    created = comment.created_at
    for text in ("  Новый текст \n", "я", "ы" * 4000, "  " + "ъ" * 4000 + "  "):
        updated = comments.update(comment, text)
        assert updated.pk == comment.pk and updated.text == text.strip()
        saved = type(comment).objects.get(pk=comment.pk)
        assert saved.text == text.strip() and saved.author_id == author.pk
        assert saved.object_ref == "probe.object:1" and saved.created_at == created


def test_comments_update_rejects_empty_and_4001_chars_with_same_error_codes_as_add():
    """FR-624: пустой (в том числе из пробелов) и больше 4000 знаков — `CommentError("empty")` / `CommentError("too_long")`,
    коды и тексты те же, что у `add`; сохранённый текст при отказе не меняется."""
    from apps.core.services import comments

    author = support.make_employee()
    comment = comments.add(author, "probe.object:2", "Прежний")
    for text, code in (("", "empty"), (" \n\t ", "empty"), ("а" * 4001, "too_long"), ("  " + "б" * 4001, "too_long")):
        with pytest.raises(comments.CommentError) as added:
            comments.add(author, "probe.object:2", text)
        with pytest.raises(comments.CommentError) as updated:
            comments.update(comment, text)
        assert updated.value.code == added.value.code == code
        assert updated.value.message == added.value.message
        assert type(comment).objects.get(pk=comment.pk).text == "Прежний"
    assert comments.CommentError("empty").message == "Введите текст комментария"
    assert comments.CommentError("too_long").message == "Комментарий не длиннее 4000 знаков"


def test_comments_add_list_for_delete_and_delete_for_behave_as_before(clock):
    """FR-624: прежнее поведение `add`, `list_for`, `delete`, `delete_for`: `add` обрезает пробелы и ставит
    `created_at = timezone.now()`; `list_for` — старые первыми, автор и фото одним запросом; `delete` убирает один
    комментарий; `delete_for` — все комментарии объекта и возвращает их число; чужие объекты не трогаются."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.core.services import comments

    first, second = support.make_employee(), support.make_employee()
    one = comments.add(first, "probe.object:3", "  первый  ")
    clock.advance(minutes=1)
    two = comments.add(second, "probe.object:3", "второй")
    clock.advance(minutes=1)
    three = comments.add(first, "probe.object:3", "третий")
    other = comments.add(first, "probe.object:4", "чужой объект")
    assert one.text == "первый" and one.created_at < two.created_at < three.created_at
    assert comments.MAX_LENGTH == 4000
    with CaptureQueriesContext(connection) as queries:
        listed = comments.list_for("probe.object:3")
        names = [(c.author.full_name, c.author.photo) for c in listed]
    assert [c.pk for c in listed] == [one.pk, two.pk, three.pk] and len(names) == 3
    assert len(queries) == 1, f"list_for ходит в базу {len(queries)} раз"
    comments.delete(two)
    assert [c.pk for c in comments.list_for("probe.object:3")] == [one.pk, three.pk]
    assert comments.delete_for("probe.object:3") == 2
    assert comments.list_for("probe.object:3") == [] and [c.pk for c in comments.list_for("probe.object:4")] == [other.pk]
    assert comments.delete_for("probe.object:3") == 0


def test_comments_module_has_no_knowledge_or_article_words():
    """FR-624: в модуле `core/services/comments.py` нет слов `knowledge` и `article` (ядро не знает о модулях)."""
    text = (support.BACKEND_DIR / "apps" / "core" / "services" / "comments.py").read_text(encoding="utf-8").lower()
    assert "knowledge" not in text and "article" not in text


# --- core/services/pdn_patterns.py и knowledge/services/pdn.py ---------------------------------------------------------

def test_pdn_patterns_email_and_phone_keep_previous_expressions_and_knowledge_imports_them():
    """FR-612: `core.services.pdn_patterns.EMAIL` и `PHONE` — те же скомпилированные выражения, что стояли в
    `knowledge/services/pdn.py` (текст и флаги); `knowledge.services.pdn` берёт их импортом
    `from apps.core.services.pdn_patterns import EMAIL, PHONE`, своих `re.compile` для них не держит."""
    from apps.core.services import pdn_patterns
    from apps.knowledge.services import pdn

    assert pdn_patterns.EMAIL.pattern == EMAIL_PATTERN and pdn_patterns.PHONE.pattern == PHONE_PATTERN
    assert pdn_patterns.EMAIL.flags == re.compile(EMAIL_PATTERN).flags
    assert pdn_patterns.PHONE.flags == re.compile(PHONE_PATTERN).flags
    assert pdn.EMAIL is pdn_patterns.EMAIL and pdn.PHONE is pdn_patterns.PHONE
    source = (support.BACKEND_DIR / "apps" / "knowledge" / "services" / "pdn.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom)
                and node.module == "apps.core.services.pdn_patterns" for alias in node.names}
    assert imported == {"EMAIL", "PHONE"}, f"из pdn_patterns импортируется {sorted(imported)}"
    assigned = {t.id for node in tree.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert not assigned & {"EMAIL", "PHONE"}, "в knowledge/services/pdn.py остались собственные EMAIL/PHONE"
    assert "apps.knowledge" not in (support.BACKEND_DIR / "apps" / "core" / "services" / "pdn_patterns.py").read_text(
        encoding="utf-8")


def test_knowledge_find_and_mask_plain_give_same_results_on_string_set():
    """FR-612: `find` и `mask_plain` базы знаний на наборе строк дают те же результаты, что до выноса выражений
    (ожидаемые значения сняты с кода до среза 007): почта и телефон находятся без повторов в порядке первого
    вхождения, маска «[скрыто]», числа и версии не трогаются."""
    from apps.knowledge.services import pdn

    cases = (
        ("Пишите на ivanov@example.test или звоните +7 (900) 123-45-67.",
         ["ivanov@example.test", "+7 (900) 123-45-67"], "Пишите на [скрыто] или звоните [скрыто]."),
        ("Телефон 8 900 123 45 67, резерв 89001234568, почта a.b+c@mail.example.org",
         ["8 900 123 45 67", "89001234568", "a.b+c@mail.example.org"],
         "Телефон [скрыто], резерв [скрыто], почта [скрыто]"),
        ("Цифры 12345 и версия 8.1.2 не телефон, user@host без домена тоже", [],
         "Цифры 12345 и версия 8.1.2 не телефон, user@host без домена тоже"),
        ("Дубль: ivanov@example.test и снова ivanov@example.test", ["ivanov@example.test"],
         "Дубль: [скрыто] и снова [скрыто]"),
        ("Без данных: заявка закрыта", [], "Без данных: заявка закрыта"),
        ("Короткий +7 900 123 45 6 и длинный 8 900 123 45 678", [],
         "Короткий +7 900 123 45 6 и длинный 8 900 123 45 678"),
    )
    for text, found, masked in cases:
        assert pdn.find("Заявка", text) == found, f"find: {text!r}"
        assert pdn.mask_plain(text) == masked, f"mask_plain: {text!r}"
    assert pdn.HIDDEN == "[скрыто]" and pdn.LIMIT == 20


# --- org/services/structure.py ----------------------------------------------------------------------------------------

def _structure_world():
    """Дерево A > B > C, отдельный D; сотрудники: в A, в B, в C, совместитель в B и D, уволенный в C, заблокированный в B.
    Приглашённых нет (в данных их членств нет)."""
    from apps.org.models import Membership

    a = org.make_unit("Отдел А")
    b = org.make_unit("Группа Б", parent=a)
    c = org.make_unit("Сектор В", parent=b)
    d = org.make_unit("Отдел Г")
    people = {"a": support.make_employee(), "b": support.make_employee(), "c": support.make_employee(),
              "both": support.make_employee(), "gone": support.make_employee(state="dismissed"),
              "blocked": support.make_employee(state="blocked")}
    for key, unit in (("a", a), ("b", b), ("c", c), ("both", b), ("both", d), ("gone", c), ("blocked", b)):
        org.make_member(people[key], unit)
    return {"a": a, "b": b, "c": c, "d": d}, people, Membership


def test_subtree_member_ids_equals_descendants_direct_members_with_secondary_jobs_without_dismissed_with_blocked_and_no_invited_in_data():
    """FR-605 (К14): `subtree_member_ids(unit_ids)` — `frozenset` номеров сотрудников, состоящих (основная работа и
    совместительство) в этих узлах или во вложенных: равно объединению прямых членов `descendants` узлов; уволенных
    нет, заблокированные есть; пустой вход и несуществующие номера дают пустое множество. Приглашённых в данных нет."""
    from apps.org.services import structure

    units, people, Membership = _structure_world()
    ids = {key: person.pk for key, person in people.items()}

    def expected(*roots):
        found = set()
        for root in roots:
            for unit in structure.descendants(root):
                found.update(m.user_id for m in Membership.objects.filter(unit=unit).select_related("user")
                             if m.user.state != "dismissed")
        return frozenset(found)

    cases = (((units["a"],), {"a", "b", "c", "both", "blocked"}), ((units["b"],), {"b", "c", "both", "blocked"}),
             ((units["c"],), {"c"}), ((units["d"],), {"both"}), ((units["b"], units["d"]), {"b", "c", "both", "blocked"}))
    for roots, keys in cases:
        result = structure.subtree_member_ids([u.pk for u in roots])
        assert isinstance(result, frozenset)
        assert result == expected(*roots) == frozenset(ids[k] for k in keys), f"узлы {[u.name for u in roots]}"
    assert ids["gone"] not in structure.subtree_member_ids([units["c"].pk])
    assert ids["blocked"] in structure.subtree_member_ids([units["b"].pk])
    assert ids["both"] in structure.subtree_member_ids([units["d"].pk]) and ids["both"] in structure.subtree_member_ids(
        [units["b"].pk])
    for given in ((units["a"].pk,), {units["a"].pk}):
        assert structure.subtree_member_ids(given) == expected(units["a"])
    assert structure.subtree_member_ids([]) == frozenset() and isinstance(structure.subtree_member_ids([]), frozenset)
    assert structure.subtree_member_ids([10 ** 9]) == frozenset()
    assert structure.subtree_member_ids([10 ** 9, units["c"].pk]) == frozenset({ids["c"]})
    root = org.root_unit()
    assert {ids[k] for k in ("a", "b", "c", "both", "blocked")} <= structure.subtree_member_ids([root.pk])


def test_unit_chains_equals_unit_chain_ids_for_each_user_in_two_queries(django_assert_num_queries):
    """FR-605 (К14): `unit_chains(user_ids)` — словарь «номер → `frozenset`» с ключом на каждый переданный номер; значение
    равно `unit_chain_ids(user)`; номер без членства — ключ с пустым множеством; два запроса независимо от числа людей."""
    from apps.core.models import User
    from apps.org.services import structure

    units, people, _Membership = _structure_world()
    loner = support.make_employee()
    chosen = [people["a"], people["b"], people["c"], people["both"], people["blocked"], loner]
    ids = [person.pk for person in chosen]
    with django_assert_num_queries(2):
        result = structure.unit_chains(ids)
    assert set(result) == set(ids) and all(isinstance(value, frozenset) for value in result.values())
    for person in chosen:
        assert result[person.pk] == structure.unit_chain_ids(User.objects.get(pk=person.pk)), f"сотрудник {person.pk}"
    assert result[loner.pk] == frozenset()
    root = org.root_unit()
    assert result[people["both"].pk] >= {root.pk, units["a"].pk, units["b"].pk, units["d"].pk}
    assert units["c"].pk not in result[people["b"].pk] and units["c"].pk in result[people["c"].pk]


def test_previous_structure_functions_keep_names_signatures_and_results():
    """FR-605, FR-641: прежние `unit_chain_ids(user)`, `all_units()`, `unit_refs(ids)`, `descendants(unit, *,
    include_self=True)`, `units_of(user)` — имена, сигнатуры и результаты прежние; новые `subtree_member_ids(unit_ids)` и
    `unit_chains(user_ids)` на месте."""
    from apps.org.services import structure

    def params(func):
        return [(p.name, p.kind, p.default) for p in inspect.signature(func).parameters.values()]

    P = inspect.Parameter
    assert params(structure.unit_chain_ids) == [("user", P.POSITIONAL_OR_KEYWORD, P.empty)]
    assert params(structure.all_units) == []
    assert params(structure.unit_refs) == [("ids", P.POSITIONAL_OR_KEYWORD, P.empty)]
    assert params(structure.descendants) == [("unit", P.POSITIONAL_OR_KEYWORD, P.empty),
                                             ("include_self", P.KEYWORD_ONLY, True)]
    assert params(structure.units_of) == [("user", P.POSITIONAL_OR_KEYWORD, P.empty)]
    assert params(structure.subtree_member_ids) == [("unit_ids", P.POSITIONAL_OR_KEYWORD, P.empty)]
    assert params(structure.unit_chains) == [("user_ids", P.POSITIONAL_OR_KEYWORD, P.empty)]
    for name in ("heads_of", "subordinates_of", "work_units_of", "queue_people", "direct_members", "name_key"):
        assert callable(getattr(structure, name)), f"пропала функция {name}"
    units, people, _Membership = _structure_world()
    a, b, c, d = units["a"], units["b"], units["c"], units["d"]
    chain = structure.unit_chain_ids(people["both"])
    assert isinstance(chain, frozenset) and chain == {org.root_unit().pk, a.pk, b.pk, d.pk}
    assert structure.unit_chain_ids(support.make_employee()) == frozenset()
    listed = structure.all_units()
    assert [u.path for u in listed] == sorted(u.path for u in listed) and {a.pk, b.pk, c.pk, d.pk} <= {u.id for u in listed}
    refs = structure.unit_refs([a.pk, c.pk, 10 ** 9])
    assert set(refs) == {a.pk, c.pk} and refs[a.pk].name == "Отдел А" and refs[a.pk].kind == "department"
    assert structure.unit_refs([]) == {}
    assert [u.pk for u in structure.descendants(a)] == [a.pk, b.pk, c.pk]
    assert [u.pk for u in structure.descendants(a, include_self=False)] == [b.pk, c.pk]
    held = structure.units_of(people["both"])
    assert {u.id for u in held} == {b.pk, d.pk} and [u.path for u in held] == sorted(u.path for u in held)
    assert structure.units_of(people["gone"]) == []
