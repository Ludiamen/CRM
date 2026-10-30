"""T-7121: показы и число непрочитанного (FR-626).

План: «Непрочитанное» (показ, число, число многим, обновление числа), «Главная, меню и число у «Ленты»»;
CONTRACT-007: 1.4, 3.1 (узел числа), 5.4 (`unread.count`, `counts`, `mark_shown`), 10.2, 12.2. Время — часы `clock`
(`unread.count(user, now=…)`, решения 5 и 59 задач); SQL — литерал с параметрами. Код среза на уровне модуля не
импортируется.
"""
import importlib
from datetime import timedelta
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_feed as fd
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def raw_text(self) -> str:
        parts = []
        for child in self.children:
            parts.append(child.raw_text() if isinstance(child, Node) else child)
        return "".join(parts)

    def text(self) -> str:
        return " ".join(self.raw_text().split())

    def inside(self, other) -> bool:
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
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


def html_of(response) -> str:
    return response.content.decode("utf-8")


def tree(response_or_html) -> Node:
    parser = _Tree()
    parser.feed(response_or_html if isinstance(response_or_html, str) else html_of(response_or_html))
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; `_` в имени — дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста ---------------------------------------------------------------------------------------

NOON = fd.moscow(2026, 3, 10, 12, 0)


def _unread():
    return importlib.import_module("apps.feed.services.unread")


def _Shown():
    return support.model("feed.Shown")


def _shown_ids(user) -> set[int]:
    return set(_Shown().objects.filter(user=user).values_list("post_id", flat=True))


def _posts(count, author=None, *, base=None, to=("all",), step_minutes=1, **extra):
    """`count` записей автора с возрастающим временем публикации (по минуте); возвращает по порядку публикации."""
    author = author or support.make_employee()
    base = base or (NOON - timedelta(hours=2))
    return [fd.make_post(author, to=to, published_at=base + timedelta(minutes=step_minutes * i),
                         text=f"запись {i}", **extra) for i in range(count)]


def _badge(response_or_html) -> Node:
    """Узел числа «Ленты» в разметке или фрагменте."""
    return q1(tree(response_or_html), id="menu-badge-feed")


def _count_of(node) -> int:
    return int(node.attrs["data-count"])


def _post_ids(response) -> list[int]:
    return [int(node.attrs["data-post-id"]) for node in q(tree(response), data_post_id=True)]


def _opened(page) -> str:
    return q1(page, id="feed-live").attrs["data-opened"]


# --- показы пишутся до оболочки (FR-626) ------------------------------------------------------------------

def test_feed_page_records_shown_before_shell_render_and_badge_excludes_shown(clock):
    """FR-626: страница ленты пишет показы до рендера оболочки: число у «Ленты» в том же ответе уже без показанных."""
    clock.set(NOON)
    posts = _posts(3)
    viewer = fd.as_plain()
    assert _unread().count(viewer.user) == 3
    response = viewer.client.get("/")
    assert response.status_code == 200
    assert _shown_ids(viewer.user) == {p.pk for p in posts}
    badge = _badge(response)
    assert _count_of(badge) == 0, "в том же ответе число уже без показанных"
    assert "d-none" in badge.attrs["class"].split()


def test_three_unread_posts_shown_on_feed_page_badge_drops_to_zero(clock):
    """FR-626 (сценарий 8 п. 5): три непрочитанные записи; число 3 на другой странице, после ленты — 0."""
    clock.set(NOON)
    _posts(3)
    viewer = fd.as_plain()
    assert _count_of(_badge(viewer.client.get("/notifications/"))) == 3
    assert viewer.client.get("/").status_code == 200
    assert _count_of(_badge(viewer.client.get("/notifications/"))) == 0
    assert _unread().count(viewer.user) == 0


def _first_page_and_more_link(viewer):
    page = tree(viewer.client.get("/"))
    (link,) = q(page, data_feed_more=True)
    return page, link.attrs["hx-get"]


def test_feed_more_with_hx_request_records_shown_and_returns_oob_badge(clock):
    """FR-626: `GET /feed/more/` с `HX-Request` пишет показы и возвращает узел числа с `hx-swap-oob`."""
    clock.set(NOON)
    posts = _posts(25)
    viewer = fd.as_plain()
    _page, more = _first_page_and_more_link(viewer)
    assert len(_shown_ids(viewer.user)) == 20
    response = viewer.client.get(more, **HX)
    assert response.status_code == 200
    assert len(_post_ids(response)) == 5
    assert _shown_ids(viewer.user) == {p.pk for p in posts}
    badge = _badge(response)
    assert badge.attrs.get("hx-swap-oob") == "true" and _count_of(badge) == 0


def test_feed_more_without_hx_request_records_no_shown(clock):
    """FR-626: без `HX-Request` `/feed/more/` отдаёт записи, но показов не пишет и узла числа не несёт."""
    clock.set(NOON)
    _posts(25)
    viewer = fd.as_plain()
    _page, more = _first_page_and_more_link(viewer)
    response = viewer.client.get(more)
    assert response.status_code == 200
    assert len(_post_ids(response)) == 5
    assert len(_shown_ids(viewer.user)) == 20, "новых показов нет"
    assert q(tree(response), id="menu-badge-feed") == []
    assert _unread().count(viewer.user) == 5


def _open_then_publish_two(clock):
    """Сотрудник открыл ленту с тремя записями; потом коллега опубликовал ещё две. Возвращает (сессия, since, новые)."""
    clock.set(NOON)
    _posts(3)
    viewer = fd.as_plain()
    since = _opened(tree(viewer.client.get("/")))
    clock.advance(minutes=5)
    fresh = _posts(2, base=NOON + timedelta(minutes=1), step_minutes=1)
    assert _unread().count(viewer.user) == 2
    return viewer, since, fresh


def test_feed_new_with_hx_request_records_shown_and_badge_drops_by_two(clock):
    """FR-626 (сценарий 8 п. 12): `GET /feed/new/` с `HX-Request` пишет показы двух новых записей; число падает на 2."""
    viewer, since, fresh = _open_then_publish_two(clock)
    response = viewer.client.get("/feed/new/", {"since": since}, **HX)
    assert response.status_code == 200
    assert sorted(_post_ids(response)) == sorted(p.pk for p in fresh)
    assert {p.pk for p in fresh} <= _shown_ids(viewer.user)
    badge = _badge(response)
    assert badge.attrs.get("hx-swap-oob") == "true" and _count_of(badge) == 0
    assert _unread().count(viewer.user) == 0


def test_feed_new_without_hx_request_records_no_shown(clock):
    """FR-626: без `HX-Request` `/feed/new/` показов не пишет и числа не несёт; записи остаются непрочитанными."""
    viewer, since, fresh = _open_then_publish_two(clock)
    shown_before = _shown_ids(viewer.user)
    response = viewer.client.get("/feed/new/", {"since": since})
    assert response.status_code == 200
    assert sorted(_post_ids(response)) == sorted(p.pk for p in fresh)
    assert _shown_ids(viewer.user) == shown_before
    assert q(tree(response), id="menu-badge-feed") == []
    assert _unread().count(viewer.user) == 2


def test_post_card_records_shown_and_badge_excludes_post(clock):
    """FR-626: карточка записи пишет показ этой записи; число в том же ответе уже без неё."""
    clock.set(NOON)
    first, second = _posts(2)
    viewer = fd.as_plain()
    response = viewer.client.get(f"/feed/{first.pk}/")
    assert response.status_code == 200
    assert _shown_ids(viewer.user) == {first.pk}
    assert _count_of(_badge(response)) == 1
    assert _unread().count(viewer.user) == 1


# --- запись показа (FR-626) ------------------------------------------------------------------------------

def test_shown_written_by_single_insert_on_conflict_do_nothing_repeat_show_no_error(clock):
    """FR-626: показы пишутся одним `INSERT … ON CONFLICT DO NOTHING` пачкой; повторный показ — не ошибка, дублей нет."""
    clock.set(NOON)
    posts = _posts(5)
    viewer = support.make_employee()
    ids = [p.pk for p in posts]
    with fd.queries_with_params() as pairs:
        _unread().mark_shown(viewer, ids)
    inserts = [(sql, params) for sql, params in pairs if "insert into" in sql.lower() and "feed_shown" in sql.lower()]
    assert len(inserts) == 1, f"одна пачка — один INSERT, получили {len(inserts)}"
    sql, params = inserts[0]
    assert "on conflict do nothing" in " ".join(sql.lower().split())
    assert "%s" in sql, "значения — параметры"
    flat = repr(params)
    assert all(str(number) in flat for number in ids), "номера записей переданы параметрами"
    assert _shown_ids(viewer) == set(ids)
    extra = _posts(1, base=NOON - timedelta(hours=1))[0]
    _unread().mark_shown(viewer, ids + [extra.pk])
    assert _shown_ids(viewer) == set(ids) | {extra.pk}
    assert _Shown().objects.filter(user=viewer).count() == 6


def test_own_post_not_counted_and_gets_no_shown_row(clock):
    """FR-626 (сценарий 8 п. 5): своя запись непрочитанной не бывает и строки показа не получает."""
    clock.set(NOON)
    viewer = fd.as_plain()
    own = fd.make_post(viewer.user, to=("all",), published_at=NOON - timedelta(hours=1))
    foreign = _posts(1)[0]
    assert _unread().count(viewer.user) == 1, "только чужая"
    assert viewer.client.get("/").status_code == 200
    assert _shown_ids(viewer.user) == {foreign.pk}
    _unread().mark_shown(viewer.user, [own.pk])
    assert own.pk not in _shown_ids(viewer.user), "свои записи не пишутся"
    assert _unread().count(viewer.user) == 0


def test_edit_and_new_comment_do_not_make_shown_post_unread(clock):
    """FR-626 (сценарий 8 п. 11): правка и новый комментарий не делают показанную запись снова непрочитанной."""
    clock.set(NOON)
    writer = fd.as_writer()
    post = fd.make_post(writer.user, to=("all",), published_at=NOON - timedelta(hours=1))
    viewer = fd.as_plain()
    assert viewer.client.get("/").status_code == 200
    assert _unread().count(viewer.user) == 0
    clock.advance(minutes=10)
    edited = writer.client.post(f"/feed/{post.pk}/edit/", {"text": "исправленный текст", "to": ["all"]}, **HX)
    assert edited.status_code == 200
    post.refresh_from_db()
    assert post.edited_at is not None and post.text == "исправленный текст"
    commented = fd.as_plain().client.post(f"/feed/{post.pk}/comments/", {"text": "новый комментарий"}, **HX)
    assert commented.status_code == 200
    assert _unread().count(viewer.user) == 0
    assert _count_of(_badge(viewer.client.get("/notifications/"))) == 0


# --- число (FR-626) --------------------------------------------------------------------------------------

def test_count_includes_only_posts_published_within_30_days(clock):
    """FR-626: считаются записи не старше 30 дней: ровно 30 суток включительно, на секунду раньше — уже нет."""
    clock.set(NOON)
    author = support.make_employee()
    for delta in (timedelta(days=1), timedelta(days=29), timedelta(days=30),
                  timedelta(days=30, seconds=1), timedelta(days=45)):
        fd.make_post(author, to=("all",), published_at=NOON - delta)
    viewer = support.make_employee()
    assert _unread().count(viewer) == 3
    assert _unread().count(viewer, now=NOON + timedelta(days=1)) == 2, "окно сдвигается вместе с `now`"


def test_count_excludes_posts_invisible_to_employee(clock):
    """FR-626: число — только по записям, которые сотрудник видит: «Всем», его узел и вложенные, он лично, упоминание."""
    clock.set(NOON)
    viewer = support.make_employee()
    other = support.make_employee()
    author = support.make_employee()
    root = org.make_unit("Отдел-родитель")
    child = org.make_unit("Отдел-ребёнок", parent=root)
    foreign_unit = org.make_unit("Чужой отдел")
    org.make_member(viewer, child)
    base = NOON - timedelta(hours=3)
    visible = [
        fd.make_post(author, to=("all",), published_at=base),
        fd.make_post(author, to=(child,), published_at=base + timedelta(minutes=1)),
        fd.make_post(author, to=(root,), published_at=base + timedelta(minutes=2)),
        fd.make_post(author, to=(viewer,), published_at=base + timedelta(minutes=3)),
        fd.make_post(author, to=(other,), mentions=(viewer,), published_at=base + timedelta(minutes=4)),
    ]
    fd.make_post(author, to=(foreign_unit,), published_at=base + timedelta(minutes=5))
    fd.make_post(author, to=(other,), published_at=base + timedelta(minutes=6))
    assert _unread().count(viewer) == len(visible)


def test_count_capped_at_100_badge_shows_99_plus_for_120(clock):
    """FR-626 (сценарий 8 п. 6): непрочитанных 120 — число ограничено 100, у пункта «Лента» — «99+»."""
    clock.set(NOON)
    _posts(120)
    viewer = fd.as_plain()
    assert _unread().count(viewer.user) == 100
    badge = _badge(viewer.client.get("/notifications/"))
    assert _count_of(badge) == 100 and badge.text() == "99+"
    assert "d-none" not in badge.attrs["class"].split()


def test_zero_unread_badge_node_hidden(clock):
    """FR-626: непрочитанных нет — узел числа остаётся в разметке, скрыт классом `d-none`, `data-count="0"`."""
    clock.set(NOON)
    viewer = fd.as_plain()
    badge = _badge(viewer.client.get("/notifications/"))
    assert _count_of(badge) == 0 and "d-none" in badge.attrs["class"].split()
    assert "data-menu-live-badge" in badge.attrs
    assert "data-menu-badge" not in badge.attrs


def test_newcomer_with_50_old_and_3_new_unit_posts_counts_3_and_old_posts_in_feed(clock):
    """FR-626 (сценарий 8 п. 9): новичок отдела, где 50 записей старше 30 дней и 3 новее: число 3, старые — в ленте."""
    clock.set(NOON)
    unit = org.make_unit("Отдел новичка")
    author = support.make_employee()
    old = [fd.make_post(author, to=(unit,), published_at=NOON - timedelta(days=31, minutes=i), text=f"старая {i}")
           for i in range(50)]
    fresh = [fd.make_post(author, to=(unit,), published_at=NOON - timedelta(days=2, minutes=i), text=f"новая {i}")
             for i in range(3)]
    newcomer = fd.as_plain()
    org.make_member(newcomer.user, unit)
    assert _unread().count(newcomer.user) == 3
    assert _count_of(_badge(newcomer.client.get("/notifications/"))) == 3
    response = newcomer.client.get("/")
    shown = _post_ids(response)
    assert set(p.pk for p in fresh) <= set(shown), "новые записи в ленте"
    old_newest_first = [p.pk for p in old]
    assert [i for i in shown if i not in {p.pk for p in fresh}] == old_newest_first[:len(shown) - 3], \
        "старые записи тоже в ленте, от новых к старым"
    assert len(shown) == 20


# --- число многим (FR-626) -------------------------------------------------------------------------------

def test_counts_for_many_equals_count_for_each_of_100_employees(clock):
    """FR-626: `counts` для 100 сотрудников равно `count` каждого: разные узлы, личные адресаты, упоминания, показы, свои записи."""
    clock.set(NOON)
    root = org.make_unit("Общий отдел")
    unit_a = org.make_unit("Отдел А", parent=root)
    unit_b = org.make_unit("Отдел Б")
    people = [support.make_employee(totp=False) for _ in range(98)]
    people.append(support.make_employee(totp=False, state="blocked"))
    people.append(support.make_employee(totp=False, state="dismissed"))
    for index, person in enumerate(people):
        if index % 4 == 0:
            org.make_member(person, unit_a)
        elif index % 4 == 1:
            org.make_member(person, unit_b)
        elif index % 4 == 2:
            org.make_member(person, root)
    author = people[0]
    base = NOON - timedelta(days=3)
    posts = [
        fd.make_post(author, to=("all",), published_at=base),
        fd.make_post(author, to=(unit_a,), published_at=base + timedelta(minutes=1)),
        fd.make_post(author, to=(unit_b,), published_at=base + timedelta(minutes=2)),
        fd.make_post(author, to=(root,), published_at=base + timedelta(minutes=3)),
        fd.make_post(people[5], to=(people[6], people[7]), mentions=(people[8],),
                     published_at=base + timedelta(minutes=4)),
        fd.make_important(people[9], to=(unit_a,), published_at=base + timedelta(minutes=5)),
        fd.make_post(people[1], to=("all",), published_at=NOON - timedelta(days=40)),
    ]
    _unread().mark_shown(people[2], [posts[0].pk, posts[1].pk])
    _unread().mark_shown(people[3], [posts[3].pk])
    ids = [p.pk for p in people]
    counts = _unread().counts(ids)
    assert set(counts) == set(ids), "ключ — каждый переданный номер"
    expected = {p.pk: _unread().count(p) for p in people}
    assert counts == expected
    assert len(set(expected.values())) >= 3, "в наборе есть разные значения: проверка не пустая"
