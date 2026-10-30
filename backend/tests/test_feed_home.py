"""T-7104: главная — тело ленты, меню «Лента» и узел живого числа (FR-601, FR-626, FR-627, FR-641).

Сценарий 14 спеки среза 007. Порядок тела главной, меню (первый пункт «Лента», «Главной» нет; без модуля — прежняя
«Главная»), запись `menu_items`, узел `#menu-badge-feed` (скрыт при нуле, «99+» при числе больше 99, без
`data-menu-badge`), прежняя разметка числа у других пунктов, узел `#feed-live` и два соединения `ws-connect` на `/`,
вход и второй фактор. Раздел 3.1, 3.3, 12.2, 12.5 контракта `CONTRACT-007.md`.

Код среза на уровне модуля не импортируется (CONTRACT-007, «Правила для всех тестов»): службы берутся внутри тестов.
Напоминание модуля «о сроке в записи списка» тест заводит сам (точка `home_notices` с тестовой функцией): модуль
«Списки» главной напоминаний не даёт, а FR-601 требует блок напоминаний любого модуля над формой и лентой.
"""
import contextlib
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_feed as feed

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
NOTICE_CODE = "list-record-deadline"
NOTICE_TEXT = "Истекает срок в записи списка «Ноутбук Лидер»"


# --- разбор разметки (помощник только этого файла; образец — test_lists_reminders_2.py) -------------------------

class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    @property
    def classes(self) -> set:
        return set(self.attrs.get("class", "").split())

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())

    def find(self, tag=None, cls=None, **attrs) -> list:
        """Потомки по тегу, классу и атрибутам; имя с дефисом пишется через `_`, `True` — «атрибут есть»."""
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        found = []
        for node in self.walk():
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and cls not in node.classes:
                continue
            if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
                found.append(node)
        return found

    def first(self, tag=None, cls=None, **attrs):
        found = self.find(tag, cls, **attrs)
        return found[0] if found else None

    def inside(self, ancestor) -> bool:
        node = self.parent
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(source) -> Node:
    parser = _Tree()
    parser.feed(source if isinstance(source, str) else source.content.decode("utf-8"))
    return parser.root


def order_of(doc: Node, node: Node) -> int:
    """Номер узла в порядке обхода разметки (для проверки «выше / ниже»)."""
    for index, candidate in enumerate(doc.walk()):
        if candidate is node:
            return index
    raise AssertionError("узел не найден в разметке")


# --- помощники только этого файла ------------------------------------------------------------------------------

@contextlib.contextmanager
def _registered(point: str, func):
    """Временная регистрация функции в точке расширения ядра (снимается после блока)."""
    from apps.core import extensions

    extensions.register(point, func)
    try:
        yield
    finally:
        registry = extensions._registry[point]
        if func in registry:
            registry.remove(func)


def _notice_func(user):
    return [{"key": NOTICE_CODE, "level": "warning", "text": NOTICE_TEXT, "url": "/lists/", "link": "Открыть список"}]


def _page(client, path="/", **extra):
    response = client.get(path, **extra)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    return tree(response)


def _menu(doc: Node) -> list[dict]:
    """Пункты левого меню по порядку: адрес, подпись, узел ссылки."""
    nav = doc.first(id="main-menu")
    assert nav is not None, "в оболочке нет nav#main-menu"
    items = []
    for link in nav.find("a", cls="menu-item"):
        label = link.first("span", cls="menu-label")
        items.append({"href": link.attrs.get("href", ""), "label": label.text() if label else link.text(), "node": link})
    return items


def _author(name="Автор Лентов", **extra):
    return factories.make_user(full_name=name, **extra)


def _unread_posts(author, count: int, *, start: int = 0) -> list:
    """Записи «Всем» от `author`, опубликованные за последние сутки (непрочитанные для остальных)."""
    now = timezone.now()
    return [feed.make_post(author, "post", to=("all",), text=f"Запись {start + i}",
                           published_at=now - timedelta(minutes=start + i + 1)) for i in range(count)]


def _date_of(value: str) -> date:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise AssertionError(f"не дата в виде ДД.ММ.ГГГГ или ГГГГ-ММ-ДД: {value!r}")


def _notices_of(doc: Node) -> list[tuple]:
    holder = doc.first(data_home_notices=True)
    assert holder is not None, "нет блока [data-home-notices]"
    return [(n.attrs.get("data-notice"), n.attrs.get("data-year"), n.text()) for n in holder.find(data_notice=True)]


# --- FR-601: тело главной ---------------------------------------------------------------------------------------

def test_home_body_order_notices_form_filters_empty_banner_important_block_feed():
    """FR-601 (сценарий 14 п. 1): в разметке подряд — напоминания модулей, форма записи, фильтры, пустая плашка,
    блок важных, лента; плашка при загрузке пустая (раздел 12.2)."""
    other = _author()
    feed.make_important(other, to=("all",), text="Важное для всех")
    feed.make_post(other, "post", to=("all",), text="Обычная запись")
    reader = feed.as_plain()
    with _registered("home_notices", _notice_func):
        doc = _page(reader.client)
    holder = doc.first(data_home_notices=True)
    form = doc.first("form", id="feed-form", data_feed_form=True)
    filters = doc.first("form", id="feed-filters", data_feed_filters=True)
    banner = doc.first(id="feed-new")
    block = doc.first(id="feed-important", data_feed_important=True)
    posts = doc.first("ol", id="feed-list", data_feed_list_main=True)
    parts = [holder, form, filters, banner, block, posts]
    assert all(part is not None for part in parts), "на главной нет одной из частей тела (раздел 12.2)"
    positions = [order_of(doc, part) for part in parts]
    assert positions == sorted(positions) and len(set(positions)) == 6, f"порядок частей: {positions}"
    assert banner.text() == "" and not banner.find("a"), "плашка при загрузке пустая"
    assert banner.attrs.get("data-count", "0") == "0"


def test_home_has_no_greeting_and_no_profile_or_security_cards():
    """FR-601: приветствие и карточки «Мой профиль», «Безопасность» и разделов с главной уходят (профиль и
    безопасность остаются в меню и верхней панели)."""
    reader = feed.as_plain()
    response = reader.client.get("/")
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    doc = tree(html)
    assert "Здравствуйте" not in html
    assert "Добро пожаловать в портал" not in html
    assert "Телефон и контакты, роль в портале." not in html
    assert "Пароль, второй фактор, устройства и история входов." not in html
    headings = [h.text() for h in doc.find("h2")]
    assert "Мой профиль" not in headings and "Безопасность" not in headings
    cards = [n for n in doc.find("a", cls="card") if "h-100" in n.classes]
    assert not cards, "карточки разделов прежней главной не выводятся"


def test_home_notices_block_shows_list_record_deadline_notice_above_post_form():
    """FR-601 (сценарий 14 п. 1): напоминание модуля стоит блоком над формой записи и лентой, с прежней разметкой
    `[data-home-notices] [data-notice]`."""
    reader = feed.as_plain()
    with _registered("home_notices", _notice_func):
        doc = _page(reader.client)
    holder = doc.first(data_home_notices=True)
    assert holder is not None
    found = holder.find(data_notice=NOTICE_CODE)
    assert len(found) == 1 and NOTICE_TEXT in found[0].text()
    link = found[0].first("a")
    assert link is not None and link.attrs.get("href") == "/lists/" and link.text() == "Открыть список"
    form = doc.first("form", id="feed-form")
    posts = doc.first("ol", id="feed-list")
    assert order_of(doc, holder) < order_of(doc, form) < order_of(doc, posts)


def test_without_feed_home_is_previous_page_with_same_notices_block():
    """FR-641 (сценарий 14 п. 4): без модуля главная — прежняя страница (приветствие, карточки), напоминания модулей
    те же и в том же блоке; формы, фильтров, ленты и соединения ленты нет."""
    reader = feed.as_plain()
    with _registered("home_notices", _notice_func):
        with_feed = _page(reader.client)
        with feed.without_feed():
            previous = _page(reader.client)
    assert _notices_of(previous) == _notices_of(with_feed) == [(NOTICE_CODE, None, NOTICE_TEXT + " Открыть список")]
    html_text = previous.text()
    assert f"Здравствуйте, {reader.user.full_name}!" in html_text
    headings = [h.text() for h in previous.find("h2")]
    assert "Мой профиль" in headings and "Безопасность" in headings
    for hook in ("feed-form", "feed-filters", "feed-list", "feed-live"):
        assert previous.first(id=hook) is None, hook
    assert with_feed.first(id="feed-form") is not None


# --- FR-601, FR-641: меню ---------------------------------------------------------------------------------------

def test_menu_feed_item_first_leads_to_root_and_home_item_absent():
    """FR-601 (сценарий 14 п. 2): пункт «Лента» первый и ведёт на `/`; пункта «Главная» нет; двух пунктов на один
    адрес нет — у сотрудника без ролей и у администратора."""
    for client in (feed.as_plain().client, support.logged_in(support.make_admin())):
        items = _menu(_page(client, "/me/"))
        assert items, "меню пусто"
        assert (items[0]["href"], items[0]["label"]) == ("/", "Лента"), items[0]
        assert [i["label"] for i in items].count("Главная") == 0
        assert [i["href"] for i in items].count("/") == 1


def test_without_feed_menu_has_home_item_first_and_no_feed_item():
    """FR-641: без модуля первый пункт — прежняя «Главная» на `/`, пункта «Лента» нет, узла живого числа нет."""
    reader = feed.as_plain()
    with feed.without_feed():
        doc = _page(reader.client, "/me/")
    items = _menu(doc)
    assert (items[0]["href"], items[0]["label"]) == ("/", "Главная")
    assert "Лента" not in [i["label"] for i in items]
    assert doc.first(id="menu-badge-feed") is None


def test_feed_menu_entry_order_0_empty_permissions_badge_unread_count_live_badge_feed():
    """FR-601, FR-626 (раздел 3.3): запись `menu_items` ленты — адрес `/`, «Лента», `order` 0, пустые права, `visible`
    для любого вошедшего, `badge` — число непрочитанных (`unread.count`), `live_badge="feed"`; запись зарегистрирована
    функцией `apps.feed.extensions.menu_items`."""
    from apps.core import extensions
    from apps.feed import extensions as feed_extensions
    from apps.feed.services import unread

    assert any(f.__module__ == "apps.feed.extensions" and f.__name__ == "menu_items"
               for f in extensions.registered("menu_items")), "функция menu_items ленты не зарегистрирована"
    entries = feed_extensions.menu_items()
    entry = next(item for item in entries if item["url"] == "/")
    for name in ("url", "title", "order", "icon"):
        assert entry[name] == feed.MENU_FEED[name], name
    assert tuple(entry["permissions"]) == ()
    assert entry["live_badge"] == "feed"
    other = _author()
    _unread_posts(other, 3)
    reader = feed.as_plain()
    admin = support.make_admin()
    assert entry["visible"](reader.user) and entry["visible"](admin)
    assert entry["badge"](reader.user) == unread.count(reader.user) == 3
    settings_entry = next(item for item in entries if item["url"] == "/settings/feed/")
    assert settings_entry["order"] == feed.MENU_FEED_SETTINGS["order"]


def test_feed_menu_item_visible_to_employee_without_roles():
    """FR-601: «Лента» открыта каждому вошедшему — сотрудник без ролей видит пункт, а `menu_for` отдаёт его первым."""
    from apps.core.services import permissions

    plain = feed.as_plain()
    assert not plain.user.roles.exists()
    first = permissions.menu_for(plain.user)[0]
    assert (first["url"], first["title"]) == ("/", "Лента")
    doc = _page(plain.client)
    assert _menu(doc)[0]["label"] == "Лента"


# --- FR-626: узел живого числа ----------------------------------------------------------------------------------

def _live_badge(doc: Node):
    badge = doc.first("span", id="menu-badge-feed")
    assert badge is not None, "нет узла #menu-badge-feed"
    return badge


def test_feed_badge_node_present_at_zero_hidden_with_data_count_and_live_marker_without_data_menu_badge():
    """FR-626 (раздел 3.1): узел числа есть всегда — при нуле скрыт классом `d-none`, `data-count="0"`, `data-menu-live-badge`
    есть, `data-menu-badge` нет; при числе больше нуля — виден, число цифрами, `data-menu-badge` по-прежнему нет."""
    reader = feed.as_plain()
    badge = _live_badge(_page(reader.client, "/me/"))
    assert "data-menu-live-badge" in badge.attrs and badge.attrs.get("data-count") == "0"
    assert "d-none" in badge.classes and "data-menu-badge" not in badge.attrs
    assert badge.text() == "0"
    _unread_posts(_author(), 3)
    doc = _page(reader.client, "/me/")
    badge = _live_badge(doc)
    assert badge.attrs.get("data-count") == "3" and "d-none" not in badge.classes and badge.text() == "3"
    assert "data-menu-live-badge" in badge.attrs and "data-menu-badge" not in badge.attrs
    link = next(i["node"] for i in _menu(doc) if i["href"] == "/")
    assert badge.inside(link) and not link.find(data_menu_badge=True)


def test_feed_badge_shows_99_plus_at_120_and_100_and_digits_at_99():
    """FR-626: 99 непрочитанных — «99»; 100 — «99+» и `data-count="100"`; 120 — «99+», `data-count` не выше 100."""
    reader = feed.as_plain()
    author = _author()
    _unread_posts(author, 99)
    badge = _live_badge(_page(reader.client, "/me/"))
    assert (badge.text(), badge.attrs["data-count"]) == ("99", "99")
    _unread_posts(author, 1, start=99)
    badge = _live_badge(_page(reader.client, "/me/"))
    assert (badge.text(), badge.attrs["data-count"]) == ("99+", "100")
    _unread_posts(author, 20, start=100)
    badge = _live_badge(_page(reader.client, "/me/"))
    assert (badge.text(), badge.attrs["data-count"]) == ("99+", "100")
    assert "d-none" not in badge.classes


def test_other_menu_items_keep_data_menu_badge_only_above_zero_in_digits():
    """FR-626, FR-641: у пунктов без `live_badge` прежняя разметка — `span[data-menu-badge]` только при числе больше
    нуля, цифрами; узла `#menu-badge-…` у них нет."""
    state = {"count": 0}

    def probe_items():
        return [{"permissions": (), "url": "/probe-badge/", "title": "Проба числа", "icon": "icons/gear.html",
                 "order": 90, "visible": lambda user: True, "badge": lambda user: state["count"]}]

    reader = feed.as_plain()
    with _registered("menu_items", probe_items):
        for count, expected in ((0, None), (7, "7"), (120, "120")):
            state["count"] = count
            doc = _page(reader.client, "/me/")
            link = next(i["node"] for i in _menu(doc) if i["href"] == "/probe-badge/")
            marks = link.find(data_menu_badge=True)
            if expected is None:
                assert not marks, "при нуле числа нет"
            else:
                assert len(marks) == 1 and marks[0].text() == expected
                assert not link.find(data_menu_live_badge=True)
                assert not [n for n in link.walk() if n.attrs.get("id", "").startswith("menu-badge-")]


# --- FR-601, FR-627: соединения на главной ----------------------------------------------------------------------

def test_home_has_feed_live_node_with_ws_connect_and_data_opened(clock):
    """FR-601, FR-627 (раздел 12.5): `#feed-live` — `hx-ext="ws"`, `ws-connect="/ws/feed/?<фильтр>"`, `data-ws="connecting"`,
    `data-opened` — момент открытия страницы; в адресе соединения только разобранные ключи фильтра."""
    other = _author()
    reader = feed.as_plain()
    doc = _page(reader.client)
    live = doc.first(id="feed-live")
    assert live is not None
    assert live.attrs.get("hx-ext") == "ws" and live.attrs.get("data-ws") == "connecting"
    target = urlsplit(live.attrs["ws-connect"])
    assert target.path == "/ws/feed/" and set(parse_qs(target.query)) <= {"f", "author", "from", "to"}
    assert datetime.fromisoformat(live.attrs["data-opened"]) == timezone.now()
    query = f"?f=important&author={other.pk}&from=10.03.2026&to=2026-03-11&zzz=1&post=5"
    doc = _page(reader.client, "/" + query)
    target = urlsplit(doc.first(id="feed-live").attrs["ws-connect"])
    values = parse_qs(target.query)
    assert target.path == "/ws/feed/" and set(values) == {"f", "author", "from", "to"}
    assert values["f"] == ["important"] and values["author"] == [str(other.pk)]
    assert _date_of(values["from"][0]) == date(2026, 3, 10) and _date_of(values["to"][0]) == date(2026, 3, 11)


def test_home_has_two_ws_connect_nodes_bell_and_feed_live():
    """FR-627 (решение 43 (г) задач): на `/` ровно два узла `ws-connect` — колокольчик `/ws/notify/` и `#feed-live`
    `/ws/feed/`."""
    reader = feed.as_plain()
    doc = _page(reader.client)
    nodes = [n for n in doc.walk() if "ws-connect" in n.attrs]
    targets = sorted(urlsplit(n.attrs["ws-connect"]).path for n in nodes)
    assert targets == ["/ws/feed/", "/ws/notify/"], targets
    assert {n.attrs.get("id") for n in nodes if urlsplit(n.attrs["ws-connect"]).path == "/ws/feed/"} == {"feed-live"}


# --- FR-601: вход и второй фактор -------------------------------------------------------------------------------

def test_anonymous_home_redirects_to_login_with_next_and_shows_no_feed():
    """FR-601 (сценарий 12 п. 1): не вошедшего `/` ведёт на вход с возвратом (`next=/`), ленты в ответах нет."""
    _unread_posts(_author(), 2)
    client = support.make_client()
    response = client.get("/")
    assert response.status_code == 302
    target = urlsplit(response["Location"])
    assert target.path == "/login/" and parse_qs(target.query).get("next") == ["/"]
    assert b"feed-" not in response.content
    login_page = client.get(response["Location"])
    assert login_page.status_code == 200
    for hook in (b"feed-form", b"feed-list", b"feed-live", b"menu-badge-feed", b"data-post-id"):
        assert hook not in login_page.content


def test_user_without_second_factor_home_redirects_to_factor_setup():
    """FR-601: вошедшего без второго фактора (ограниченная сессия) `/` ведёт на подключение фактора; ленты нет."""
    from apps.core.services import sessions

    _unread_posts(_author(), 2)
    user = support.make_employee()
    client = support.logged_in(user)
    session = client.session
    session[sessions.LIMITED_KEY] = True
    session.save()
    response = client.get("/")
    assert response.status_code == 302 and response["Location"].endswith("/me/security/totp/")
    assert b"feed-" not in response.content and b"data-post-id" not in response.content
