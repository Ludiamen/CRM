"""T-7106: блок важных, состав записи, сборка карточек без N+1 (FR-602, FR-603, FR-614, FR-620, FR-635, NFR-601).

Блок важных над лентой (когда он показан, кто в него входит, как записи уходят из него и не повторяются в ленте, «Ещё
записи» и плашка), состав записи (автор, фото, «→», адресаты, время, «изменено», части с постоянными `id`, меню
«Править» / «Удалить», последние три комментария), число запросов страницы и массивы номеров в параметрах.
Разделы 10.2, 12.1, 12.3 контракта `CONTRACT-007.md`; план «Лента, курсор, блок важных, фильтры», «Запись в ленте и
карточка».

Код среза на уровне модуля не импортируется (CONTRACT-007, «Правила для всех тестов»).
"""
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_feed as feed
from tests import support_org

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


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


# --- помощники только этого файла ------------------------------------------------------------------------------

def _author(name="Автор Лентов", **extra):
    return factories.make_user(full_name=name, **extra)


def _page(client, path="/", **extra) -> Node:
    response = client.get(path, **extra)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    return tree(response)


def _hx(client, path) -> Node:
    return _page(client, path, **support.HX)


def ids_in(scope: Node) -> list[int]:
    return [int(n.attrs["data-post-id"]) for n in scope.find("article", data_post_id=True)]


def list_ids(doc: Node) -> list[int]:
    holder = doc.first(id="feed-list")
    assert holder is not None, "на странице нет #feed-list"
    return ids_in(holder)


def block_ids(doc: Node) -> list[int]:
    holder = doc.first(id="feed-important")
    return ids_in(holder) if holder is not None else []


def article(doc: Node, post) -> Node:
    node = doc.first("article", id=f"feed-post-{post.pk}")
    assert node is not None, f"записи {post.pk} нет на странице"
    return node


def _flat(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _flat(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flat(item)
    elif value is not None:
        yield value


def _author_href(post_node: Node):
    """Адрес ссылки ФИО автора (`None`, если ФИО — текст) и сам узел `[data-feed-author]`."""
    node = post_node.first(data_feed_author=True)
    assert node is not None, "нет [data-feed-author]"
    if node.tag == "a":
        return node.attrs.get("href"), node
    link = node.first("a")
    return (link.attrs.get("href") if link is not None else None), node


def _normal_posts(author, count, *, first_minutes_ago=30):
    """`count` обычных записей «Всем» (самая новая — последняя), старше любых записей теста с меньшим отступом."""
    now = timezone.now()
    return [feed.make_post(author, "post", to=("all",), text=f"Запись {i}",
                           published_at=now - timedelta(minutes=first_minutes_ago - i)) for i in range(count)]


# --- FR-602: показ блока важных ---------------------------------------------------------------------------------

def test_important_block_shown_only_for_all_and_important_without_author_or_period():
    """FR-602, FR-635: блок `#feed-important` показан при фильтрах «Все» и «Важные» без «Автор» и периода; если
    непрочитанных действующих важных у читателя нет — узла нет."""
    author = _author()
    reader = feed.as_plain()
    important = feed.make_important(author, to=(reader.user,))
    for path in ("/", "/?f=all", "/?f=important"):
        doc = _page(reader.client, path)
        block = doc.first(id="feed-important", data_feed_important=True)
        assert block is not None and block_ids(doc) == [important.pk], path
    outsider = feed.as_plain()
    assert _page(outsider.client).first(id="feed-important") is None, "важная не ему — блока нет"


def test_important_block_absent_for_events_mine_mentions_and_with_author_or_period():
    """FR-602, FR-635: при «События», «Мои», «Упоминают меня» и при заданных «Автор» или периоде блока нет, а важная
    запись, подходящая под фильтр, стоит в ленте по времени."""
    author = _author()
    reader = feed.as_plain()
    important = feed.make_important(author, to=("all",))
    for path in ("/?f=events", "/?f=mine", "/?f=mentions"):
        doc = _page(reader.client, path)
        assert doc.first(id="feed-important") is None, path
        assert important.pk not in list_ids(doc), path
    for path in (f"/?author={author.pk}", "/?from=01.01.2026", "/?to=01.01.2099", f"/?f=important&author={author.pk}",
                 "/?f=important&from=01.01.2026", f"/?f=all&author={author.pk}&from=01.01.2026&to=2099-01-01"):
        doc = _page(reader.client, path)
        assert doc.first(id="feed-important") is None, path
        assert list_ids(doc) == [important.pk], path


# --- FR-602, FR-614: состав блока -------------------------------------------------------------------------------

def test_important_block_holds_visible_unexpired_unread_others_important_with_read_button():
    """FR-602, FR-614: в блоке — видимые чужие важные записи с неистёкшим сроком, которые читатель не отметил; у каждой
    кнопка «Прочитано»; истёкшие, свои, прочитанные и невидимые в блок не входят."""
    author, stranger = _author(), _author("Другой Сотрудник")
    reader = feed.as_plain()
    now = timezone.now()
    first = feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=3))
    second = feed.make_important(author, to=(reader.user,), published_at=now - timedelta(minutes=2))
    feed.make_important(author, until=now - timedelta(hours=1), to=("all",), published_at=now - timedelta(days=2))
    feed.make_important(reader.user, to=("all",), published_at=now - timedelta(minutes=1))
    read = feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=4))
    support.model("feed.ReadMark").objects.create(post=read, user=reader.user, read_at=now)
    feed.make_important(author, to=(stranger,), published_at=now - timedelta(minutes=5))
    doc = _page(reader.client)
    assert sorted(block_ids(doc)) == sorted([first.pk, second.pk])
    for post in (first, second):
        imp = doc.first(id=f"feed-post-{post.pk}-imp")
        button = imp.first(data_action="read")
        assert button is not None and button.text() == "Прочитано"


def test_read_important_leaves_block_and_stands_in_feed_by_time_without_button():
    """FR-614: после «Прочитано» запись уходит из блока и встаёт в ленту по времени публикации; кнопки больше нет,
    отметка остаётся."""
    author = _author()
    reader = feed.as_plain()
    now = timezone.now()
    older = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=120))
    important = feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=60))
    newer = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=1))
    doc = _page(reader.client)
    assert block_ids(doc) == [important.pk] and list_ids(doc) == [newer.pk, older.pk]
    response = reader.client.post(f"/feed/{important.pk}/read/", **support.HX)
    assert response.status_code == 200
    assert not tree(response).find(data_action="read"), "во фрагменте записи кнопки нет"
    assert support.model("feed.ReadMark").objects.filter(post=important, user=reader.user).count() == 1
    doc = _page(reader.client)
    assert doc.first(id="feed-important") is None or not block_ids(doc)
    assert list_ids(doc) == [newer.pk, important.pk, older.pk]
    assert not article(doc, important).find(data_action="read")


def test_expired_important_not_in_block_stands_in_feed_as_regular_without_reminder():
    """FR-602, FR-614: после срока важная запись из блока уходит, стоит в ленте как обычная по времени, без кнопки
    «Прочитано» и с пометкой «было важным»."""
    author = _author()
    reader = feed.as_plain()
    now = timezone.now()
    older = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(days=3))
    expired = feed.make_important(author, until=now - timedelta(hours=1), to=("all",), published_at=now - timedelta(days=2))
    doc = _page(reader.client)
    assert doc.first(id="feed-important") is None
    assert list_ids(doc) == [expired.pk, older.pk]
    node = article(doc, expired)
    assert not node.find(data_action="read")
    was = node.first(data_feed_was_important=True)
    assert was is not None and "было важным" in was.text()


def test_own_important_not_in_block_and_stands_in_feed_by_time():
    """FR-602, FR-614: своя важная запись в блок не входит, кнопки «Прочитано» у автора нет, запись — в ленте по
    времени."""
    reader = feed.as_plain()
    other = _author()
    now = timezone.now()
    older = feed.make_post(other, "post", to=("all",), published_at=now - timedelta(minutes=10))
    own = feed.make_important(reader.user, to=("all",), published_at=now - timedelta(minutes=5))
    newer = feed.make_post(other, "post", to=("all",), published_at=now - timedelta(minutes=1))
    doc = _page(reader.client)
    assert doc.first(id="feed-important") is None
    assert list_ids(doc) == [newer.pk, own.pk, older.pk]
    assert not article(doc, own).find(data_action="read")


def test_block_posts_not_repeated_in_feed_and_not_counted_in_page_of_20():
    """FR-602: записи блока в 20 записей страницы не входят и в основной ленте не повторяются; «Ещё записи» отдаёт
    остальные обычные записи."""
    author = _author()
    reader = feed.as_plain()
    normal = _normal_posts(author, 25)
    now = timezone.now()
    important = [feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=3 - i)) for i in range(3)]
    doc = _page(reader.client)
    expected = [p.pk for p in reversed(normal)]
    assert sorted(block_ids(doc)) == sorted(p.pk for p in important)
    assert list_ids(doc) == expected[:20]
    link = doc.first(data_feed_more=True)
    assert link is not None
    fragment = _hx(reader.client, link.attrs["hx-get"])
    assert ids_in(fragment) == expected[20:]
    assert not set(ids_in(fragment)) & {p.pk for p in important}


def test_more_and_new_exclude_block_posts_by_sql_condition_without_ids_in_url(clock):
    """FR-602: «Ещё записи» и вставка по плашке не повторяют записи блока условием в SQL: номеров блока нет ни в адресе,
    ни в параметрах запроса; новая важная запись встаёт в блок, новая обычная — наверх ленты."""
    author = _author()
    reader = feed.as_plain()
    normal = _normal_posts(author, 25)
    now = timezone.now()
    block = [feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=3 - i)) for i in range(2)]
    doc = _page(reader.client)
    assert sorted(block_ids(doc)) == sorted(p.pk for p in block)
    link = doc.first(data_feed_more=True)
    query = parse_qs(urlsplit(link.attrs["hx-get"]).query)
    assert set(query) <= {"before", "opened", "f", "author", "from", "to"}, "в адресе только курсор и фильтр"
    with feed.queries_with_params() as pairs:
        fragment = _hx(reader.client, link.attrs["hx-get"])
    assert ids_in(fragment) == [p.pk for p in reversed(normal)][20:]
    texts = " ".join(sql.lower() for sql, _ in pairs)
    assert "important_until" in texts and "feed_readmark" in texts, "условие блока должно быть в SQL"
    block_set = {p.pk for p in block}
    for _, params in pairs:
        for item in (params if isinstance(params, (list, tuple)) else ()):
            if isinstance(item, (list, tuple, set, frozenset)):
                assert not block_set & set(_flat(item)), "номера блока переданы в запрос"
    opened = doc.first(id="feed-live").attrs["data-opened"]
    clock.advance(seconds=120)
    fresh_important = feed.make_important(author, to=("all",), published_at=timezone.now())
    fresh_normal = feed.make_post(author, "post", to=("all",), text="Свежая", published_at=timezone.now())
    update = _hx(reader.client, "/feed/new/?since=" + quote(opened))
    into_block = update.find(hx_swap_oob="afterbegin:#feed-important")
    into_list = update.find(hx_swap_oob="afterbegin:#feed-list")
    assert into_block and ids_in(into_block[0]) == [fresh_important.pk]
    assert into_list and ids_in(into_list[0]) == [fresh_normal.pk]
    assert not set(ids_in(update)) & block_set


def test_mentioned_unread_important_in_feed_by_time_under_mentions_and_only_in_block_under_all():
    """FR-602, FR-635 (сценарий 11): непрочитанная важная запись с упоминанием читателя — при «Все» только в блоке, при
    «Упоминают меня» (блока нет) — в ленте по времени."""
    author = _author()
    reader = feed.as_plain()
    important = feed.make_important(author, to=("all",), mentions=[reader.user])
    doc = _page(reader.client)
    assert block_ids(doc) == [important.pk] and important.pk not in list_ids(doc)
    doc = _page(reader.client, "/?f=mentions")
    assert doc.first(id="feed-important") is None
    assert list_ids(doc) == [important.pk]


def test_block_shown_with_empty_feed_prints_no_empty_text():
    """FR-602: если блок важных показан, а основная лента пуста, текста «Записей пока нет» нет."""
    author = _author()
    reader = feed.as_plain()
    important = feed.make_important(author, to=("all",))
    for path in ("/", "/?f=important"):
        response = reader.client.get(path)
        doc = tree(response)
        assert block_ids(doc) == [important.pk] and list_ids(doc) == [], path
        assert not doc.find(data_empty_state=True), path
        assert "Записей пока нет" not in response.content.decode("utf-8")


# --- NFR-601: сборка без N+1 ------------------------------------------------------------------------------------

def _populate(viewer, count):
    """`count` полностью заполненных записей для `viewer` (у каждой свой автор, адресаты — подразделение, человек,
    упоминание; четыре комментария, отметки записи и комментария, два файла, правка) и постоянные добавки: событие с
    ответом читателя и непрочитанная важная запись (блок)."""
    now = timezone.now()
    unit = support_org.make_unit()
    support_org.make_member(viewer, unit)
    commenters = [_author(f"Комментатор {i}") for i in range(3)]
    posts = []
    for i in range(count):
        author = _author(f"Автор {i}")
        post = feed.make_post(author, "post", to=(unit, viewer, commenters[0]), mentions=[viewer, commenters[1]],
                              text=f"Запись {i}", published_at=now - timedelta(minutes=i + 10),
                              edited_at=(now - timedelta(minutes=1)) if i % 2 == 0 else None)
        comments = [feed.comment(post, commenters[j % 3], f"Комментарий {j}",
                                 created_at=now - timedelta(minutes=i + 9) + timedelta(seconds=j)) for j in range(4)]
        for liker in commenters:
            feed.like(post, liker)
        feed.like(comments[0], commenters[0])
        feed.attach(post, f"файл{i}.pdf", b"data")
        feed.attach(post, "схема.png")
        posts.append(post)
    editor = _author("Организатор")
    event = feed.make_event(editor, start=now + timedelta(days=2), to=(unit,), published_at=now - timedelta(minutes=5))
    support.model("feed.EventAnswer").objects.create(post=event, user=viewer, answer="go", answered_at=now)
    feed.make_important(editor, to=(unit,), published_at=now - timedelta(minutes=4))
    return posts, event


def test_page_query_count_equal_for_1_and_20_fully_populated_posts():
    """NFR-601: число запросов страницы `/` не зависит от числа записей — на 1 и на 20 полностью заполненных записях
    равно (`capture_sql`)."""
    counts = {}
    feed.as_plain().client.get("/")   # прогрев общих кэшей, чтобы первая страница не считалась дороже второй
    for count in (1, 20):
        reader = feed.as_plain()
        _populate(reader.user, count)
        assert reader.client.get("/me/").status_code == 200, "прогрев кэша прав"
        with feed.capture_sql() as sqls:
            response = reader.client.get("/")
        assert response.status_code == 200
        doc = tree(response)
        assert len(list_ids(doc)) == min(count + 1, 20) and len(block_ids(doc)) == 1
        counts[count] = len(sqls)
    assert counts[1] == counts[20], f"число запросов зависит от числа записей: {counts}"


def test_card_data_loaded_by_post_ids_array_parameter():
    """NFR-601: данные карточек страницы (авторы, адресаты, файлы, отметки, комментарии) читаются запросами с номерами
    страницы одним массивом `= ANY(%s)`, а не отдельными параметрами."""
    reader = feed.as_plain()
    _populate(reader.user, 5)
    with feed.queries_with_params() as pairs:
        response = reader.client.get("/")
    doc = tree(response)
    page_ids = set(list_ids(doc))
    assert len(page_ids) == 6
    by_array = []
    for sql, params in pairs:
        params = params if isinstance(params, (list, tuple)) else ()
        for item in params:
            if isinstance(item, (list, tuple, set, frozenset)) and page_ids <= set(_flat(item)):
                by_array.append(sql)
                assert "any(" in sql.lower(), "массив номеров не через ANY(%s)"
                break
        scalars = [item for item in params if not isinstance(item, (list, tuple, set, frozenset, dict))]
        assert len(page_ids & {v for v in scalars if isinstance(v, int)}) < 2, "номера страницы переданы по одному"
    assert len(by_array) >= 3, f"запросов с массивом номеров страницы: {len(by_array)}"


# --- FR-603: состав записи --------------------------------------------------------------------------------------

def test_post_shows_author_photo_arrow_recipients_and_published_time():
    """FR-603: автор (ФИО и фото 96 px), «→», адресаты (подразделение и человек) и время публикации по Москве."""
    reader = feed.as_plain(full_name="Пётр Адресатов")
    author = _author("Анна Автор")
    stored = support.model("core.StoredFile").objects.create(
        purpose="photo", owner=author, size=10, sha256="0" * 64, content_type="image/png", status="clean",
        scanned_at=timezone.now())
    author.photo = stored
    author.save(update_fields=["photo"])
    unit = support_org.make_unit("Отдел сети")
    published = feed.moscow(2026, 3, 10, 12, 30)
    post = feed.make_post(author, "post", to=(unit, reader.user), published_at=published)
    node = article(_page(reader.client), post)
    _, name = _author_href(node)
    assert "Анна Автор" in name.text()
    photos = [img.attrs.get("src") for img in node.find("img")]
    assert f"/staff/{author.pk}/photo/{stored.pk}/96/" in photos
    assert "→" in node.text()
    recipients = node.first(id=f"feed-post-{post.pk}-to").text()
    assert "Отдел сети" in recipients and "Пётр Адресатов" in recipients
    stamp = node.first("time", data_at=True)
    assert datetime.fromisoformat(stamp.attrs["datetime"]) == published
    assert stamp.text() == "10.03.2026 12:30"


def test_author_name_links_to_staff_card_only_for_staff_view_or_accounts_manage():
    """FR-603: ФИО автора — ссылка на `/staff/<id>/` только у читателя с правом `staff.view` или `accounts.manage`;
    у остальных — тот же текст без ссылки."""
    author = _author("Анна Автор")
    post = feed.make_post(author, "post", to=("all",))
    viewers = {"staff": support.logged_in(support.make_with_permissions("staff.view")),
               "accounts": support.logged_in(support.make_with_permissions("accounts.manage")),
               "plain": feed.as_plain().client}
    for who, client in viewers.items():
        href, name = _author_href(article(_page(client), post))
        assert "Анна Автор" in name.text(), who
        if who == "plain":
            assert href is None and not name.find("a"), "ссылки быть не должно"
        else:
            assert href == f"/staff/{author.pk}/", who


def test_dismissed_author_shown_with_dismissed_mark():
    """FR-603: уволенный автор подписан ФИО с пометкой «уволен» (`span[data-dismissed="true"]`); у действующего
    пометки нет."""
    gone = _author("Уволенный Автор", state="dismissed")
    active = _author("Действующий Автор")
    reader = feed.as_plain()
    now = timezone.now()
    gone_post = feed.make_post(gone, "post", to=("all",), published_at=now - timedelta(minutes=2))
    active_post = feed.make_post(active, "post", to=("all",), published_at=now - timedelta(minutes=1))
    doc = _page(reader.client)
    node = article(doc, gone_post)
    assert node.first("span", data_dismissed="true") is not None
    assert "Уволенный Автор" in node.text() and "(уволен)" in node.text()
    assert article(doc, active_post).first(data_dismissed=True) is None


def test_edited_post_shows_edited_with_time_and_unedited_does_not():
    """FR-603, FR-620: у правленной записи — «изменено» со временем правки по Москве (`[data-feed-edited]`), у
    неправленной — нет."""
    author = _author()
    reader = feed.as_plain()
    edited_at = feed.moscow(2026, 3, 11, 9, 5)
    now = timezone.now()
    edited = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=2), edited_at=edited_at)
    plain = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=1))
    doc = _page(reader.client)
    mark = article(doc, edited).first(data_feed_edited=True)
    assert mark is not None and "изменено" in mark.text()
    stamp = mark.first("time", data_at=True)
    assert datetime.fromisoformat(stamp.attrs["datetime"]) == edited_at and stamp.text() == "11.03.2026 09:05"
    assert article(doc, plain).first(data_feed_edited=True) is None


def test_post_parts_have_stable_ids_and_data_post_id():
    """FR-603 (раздел 12.3): запись — `article#feed-post-<id>[data-post-id]`; части `-to`, `-body`, `-files`, `-likers`,
    `-comments`, `-ccount` у любой записи, `-imp` у важной, `-event` у события."""
    author = _author()
    reader = feed.as_plain()
    now = timezone.now()
    plain = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=3))
    important = feed.make_important(reader.user, to=("all",), published_at=now - timedelta(minutes=2))
    event = feed.make_event(author, start=now + timedelta(days=2), to=("all",), published_at=now - timedelta(minutes=1))
    feed.attach(plain, "файл.pdf", b"data")
    feed.like(plain, author)
    feed.comment(plain, author, "Комментарий")
    doc = _page(reader.client)
    common = ("to", "body", "files", "likers", "comments", "ccount")
    for post, extra in ((plain, ()), (important, ("imp",)), (event, ("event",))):
        node = article(doc, post)
        assert node.attrs.get("data-post-id") == str(post.pk)
        for part in common + extra:
            assert node.first(id=f"feed-post-{post.pk}-{part}") is not None, f"нет части {part} у записи {post.pk}"


def test_edit_delete_menu_none_for_reader_both_for_author_delete_only_for_moderator_who_sees():
    """FR-603 (FR-620, FR-621): меню записи — читателю ничего; автору «Править» и «Удалить»; модератору, который видит
    запись, только «Удалить»; запись, которую он не видит, ему не показывается."""
    author = feed.as_plain()
    reader = feed.as_plain()
    moderator = feed.as_moderator()
    other = _author("Другой Сотрудник")
    now = timezone.now()
    post = feed.make_post(author.user, "post", to=("all",), published_at=now - timedelta(minutes=2))
    hidden = feed.make_post(other, "post", to=(reader.user,), published_at=now - timedelta(minutes=1))
    on_reader = article(_page(reader.client), post)
    assert not on_reader.find(data_action="post-edit") and not on_reader.find(data_action="post-delete")
    on_author = article(_page(author.client), post)
    assert on_author.find(data_action="post-edit") and on_author.find(data_action="post-delete")
    moderator_doc = _page(moderator.client)
    on_moderator = article(moderator_doc, post)
    assert not on_moderator.find(data_action="post-edit") and on_moderator.find(data_action="post-delete")
    assert hidden.pk not in list_ids(moderator_doc), "модератор не видит запись, которой он не адресат"
    assert moderator.client.get(f"/feed/{hidden.pk}/").status_code == 404


def test_feed_shows_last_three_comments_and_show_all_count():
    """FR-603: в ленте — последние три комментария и «Показать все N» (`a[data-feed-comments-all]`, `/feed/<id>/comments/`)
    при их числе больше трёх; число — в `-ccount`."""
    author = _author()
    reader = feed.as_plain()
    now = timezone.now()
    many = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=3))
    four = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=2))
    three = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=1))
    cases = {}
    for post, total in ((many, 5), (four, 4), (three, 3)):
        cases[post.pk] = [feed.comment(post, author, f"Комментарий {j}",
                                       created_at=now - timedelta(minutes=30) + timedelta(minutes=j)) for j in range(total)]
    doc = _page(reader.client)
    for post, total in ((many, 5), (four, 4), (three, 3)):
        node = article(doc, post)
        shown = {int(n.attrs["data-comment-id"]) for n in node.find(data_comment_id=True)}
        assert shown == {c.pk for c in cases[post.pk][-3:]}, f"запись {post.pk}"
        link = node.first(data_feed_comments_all=True)
        if total > 3:
            assert link is not None and f"Показать все {total}" in link.text()
            assert link.attrs.get("hx-get") == f"/feed/{post.pk}/comments/"
        else:
            assert link is None
        assert str(total) in node.first(id=f"feed-post-{post.pk}-ccount").text()
