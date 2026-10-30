"""T-7105: лента, курсор, фильтры, белый список (FR-602, FR-626, FR-635, NFR-608).

Первая страница и «Ещё записи» по курсору `(published_at, id)`, записи после открытия страницы, пустые состояния,
каждый фильтр и их сочетания, белый список ключей и значений (значения — параметры SQL, ссылки и адрес соединения
строятся из разобранных значений), форма фильтров, показы при `GET /feed/more/` только с заголовком `HX-Request`.
Разделы 10.2, 12.1, 12.2 контракта `CONTRACT-007.md`; план «Лента, курсор, блок важных, фильтры».

Код среза на уровне модуля не импортируется (CONTRACT-007, «Правила для всех тестов»).
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_feed as feed
from tests import support_org

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
UTC = dt_timezone.utc


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


# --- помощники только этого файла ------------------------------------------------------------------------------

def _author(name="Автор Лентов", **extra):
    return factories.make_user(full_name=name, **extra)


def _page(client, path="/", **extra) -> Node:
    response = client.get(path, **extra)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    return tree(response)


def _hx(client, path) -> Node:
    """Запрос HTMX: фрагмент разбирается как разметка."""
    return _page(client, path, **support.HX)


def ids_in(scope: Node) -> list[int]:
    return [int(n.attrs["data-post-id"]) for n in scope.find("article", data_post_id=True)]


def list_ids(doc: Node) -> list[int]:
    """Номера записей основной ленты `ol#feed-list` по порядку."""
    holder = doc.first(id="feed-list")
    assert holder is not None, "на странице нет #feed-list"
    return ids_in(holder)


def block_ids(doc: Node) -> list[int]:
    holder = doc.first(id="feed-important")
    return ids_in(holder) if holder is not None else []


def more_link(scope: Node):
    return scope.first(data_feed_more=True)


def _ids_desc(posts) -> list[int]:
    """Номера записей от новых к старым (по времени, при равенстве — по номеру)."""
    return [pk for _, pk in sorted(((p.published_at, p.pk) for p in posts), reverse=True)]


def _flat(value):
    """Все скалярные значения вложенных параметров запроса."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _flat(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flat(item)
    elif value is not None:
        yield value


def _date_of(value: str) -> date:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise AssertionError(f"не дата в виде ДД.ММ.ГГГГ или ГГГГ-ММ-ДД: {value!r}")


def _utc_midnight(clock, year=2026, month=3, day=12):
    clock.set(datetime(year, month, day, 0, 0, tzinfo=UTC))


def _posts_by_minutes(author, count, *, to=("all",), kind="post"):
    """`count` записей от `author`: i-я опубликована за `count - i` минут до «сейчас» (последняя — новее всех)."""
    now = timezone.now()
    return [feed.make_post(author, kind, to=to, text=f"Запись {i}", published_at=now - timedelta(minutes=count - i))
            for i in range(count)]


# --- FR-602: страницы и курсор ----------------------------------------------------------------------------------

def test_45_posts_paginate_20_20_5_and_more_button_disappears():
    """FR-602: 45 записей — 20, потом 20, потом 5, кнопка «Ещё записи» после последней страницы исчезает; порядок —
    от новых к старым."""
    posts = _posts_by_minutes(_author(), 45)
    expected = _ids_desc(posts)
    reader = feed.as_plain()
    doc = _page(reader.client)
    assert list_ids(doc) == expected[:20]
    link = more_link(doc)
    assert link is not None and link.attrs["hx-get"].startswith("/feed/more/?")
    second = _hx(reader.client, link.attrs["hx-get"])
    assert ids_in(second) == expected[20:40]
    link = more_link(second)
    assert link is not None
    third = _hx(reader.client, link.attrs["hx-get"])
    assert ids_in(third) == expected[40:]
    assert more_link(third) is None, "после последней страницы кнопки нет"


def test_cursor_paginates_100_posts_with_same_published_at_without_loss_or_repeat():
    """FR-602: 100 записей с одним временем публикации — курсор `(время, номер)` без потерь и повторов."""
    author = _author()
    same = timezone.now() - timedelta(days=1)
    posts = [feed.make_post(author, "post", to=("all",), text=f"Запись {i}", published_at=same) for i in range(100)]
    reader = feed.as_plain()
    doc = _page(reader.client)
    collected = list_ids(doc)
    link, pages = more_link(doc), 1
    while link is not None:
        pages += 1
        assert pages <= 10, "страницы не кончаются"
        fragment = _hx(reader.client, link.attrs["hx-get"])
        collected += ids_in(fragment)
        link = more_link(fragment)
    assert pages == 5
    assert len(collected) == len(set(collected)) == 100, "потери или повторы записей"
    assert collected == sorted((p.pk for p in posts), reverse=True)


def test_post_published_after_opened_not_returned_by_more(clock):
    """FR-602: запись, опубликованная после открытия страницы, в «Ещё записи» не попадает и не вытесняет другие
    (она приходит плашкой, FR-627)."""
    old = _posts_by_minutes(_author(), 25)
    expected = _ids_desc(old)
    reader = feed.as_plain()
    doc = _page(reader.client)
    link = more_link(doc)
    assert link is not None
    clock.advance(seconds=60)
    newer = feed.make_post(_author("Другой Автор"), "post", to=("all",), text="Новая", published_at=timezone.now())
    fragment = _hx(reader.client, link.attrs["hx-get"])
    assert ids_in(fragment) == expected[20:]
    assert newer.pk not in ids_in(fragment)
    assert newer.pk in list_ids(_page(reader.client)), "при следующем открытии запись на первой странице"


def test_invalid_before_or_opened_returns_first_page_not_500():
    """FR-602, FR-635 (решение контракта К31): неверные `before` и `opened` — как отсутствующие, первая страница, не 500."""
    expected = _ids_desc(_posts_by_minutes(_author(), 25))[:20]
    reader = feed.as_plain()
    now_iso = quote(timezone.now().isoformat())
    for path in ("/feed/more/?before=garbage&opened=zzz",
                 "/feed/more/?before=2026-13-45T00:00:00,abc&opened=" + now_iso,
                 "/feed/more/?before=,&opened=",
                 "/feed/more/?before=1,2,3",
                 "/feed/more/?opened=zzz",
                 "/feed/more/?before=%00&opened=%00"):
        assert ids_in(_page(reader.client, path)) == expected, path
    assert list_ids(_page(reader.client, "/?before=zzz&opened=yyy")) == expected
    valid_before = quote(f"{timezone.now().isoformat()},1")
    assert reader.client.get(f"/feed/more/?before={valid_before}&opened=zzz").status_code == 200


def test_feed_without_addressed_posts_says_no_posts_yet():
    """FR-602: у сотрудника нет видимых записей — «Записей пока нет» (`[data-empty-state="feed"]`), записей нет."""
    other = _author("Другой Сотрудник")
    feed.make_post(_author(), "post", to=(other,), text="Не вам")
    doc = _page(feed.as_plain().client)
    empty = doc.first(data_empty_state="feed")
    assert empty is not None and "Записей пока нет" in empty.text()
    assert doc.first(data_empty_state="feed-filter") is None
    assert not doc.find("article", data_post_id=True)


def test_empty_filter_result_says_no_posts_by_filter():
    """FR-635: пусто по фильтру — «По фильтру записей нет» (`[data-empty-state="feed-filter"]`), а не «Записей пока нет»."""
    feed.make_post(_author(), "post", to=("all",), text="Есть запись")
    reader = feed.as_plain()
    doc = _page(reader.client, "/?f=events")
    empty = doc.first(data_empty_state="feed-filter")
    assert empty is not None and "По фильтру записей нет" in empty.text()
    assert doc.first(data_empty_state="feed") is None
    lonely = feed.as_plain()
    doc = _page(lonely.client, "/?f=mine")
    assert "По фильтру записей нет" in doc.first(data_empty_state="feed-filter").text()


# --- FR-635: фильтры --------------------------------------------------------------------------------------------

def test_default_filter_all_shows_visible_posts_newest_first():
    """FR-602, FR-635: фильтр «Все» (по умолчанию) — записи, которые сотрудник видит (всем, ему, его подразделению,
    свои), от новых к старым; чужие адресные не видны."""
    reader = feed.as_plain()
    other = _author("Другой Сотрудник")
    author = _author()
    mine_unit, foreign_unit = support_org.make_unit(), support_org.make_unit()
    support_org.make_member(reader.user, mine_unit)
    now = timezone.now()
    p_all = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=6))
    p_person = feed.make_post(author, "post", to=(reader.user,), published_at=now - timedelta(minutes=5))
    p_unit = feed.make_post(author, "post", to=(mine_unit,), published_at=now - timedelta(minutes=4))
    p_own = feed.make_post(reader.user, "post", to=(other,), published_at=now - timedelta(minutes=3))
    feed.make_post(author, "post", to=(other,), published_at=now - timedelta(minutes=2))
    feed.make_post(author, "post", to=(foreign_unit,), published_at=now - timedelta(minutes=1))
    expected = [p_own.pk, p_unit.pk, p_person.pk, p_all.pk]
    assert list_ids(_page(reader.client)) == expected
    assert list_ids(_page(reader.client, "/?f=all")) == expected


def test_important_filter_shows_only_important_including_expired():
    """FR-635: «Важные» — все записи вида «Важное», в том числе с истёкшим сроком (в блоке — непрочитанные действующие,
    в ленте — остальные); сообщений и событий нет."""
    reader = feed.as_plain()
    author = _author()
    now = timezone.now()
    feed.make_post(author, "post", to=("all",), text="Обычная")
    feed.make_event(author, start=now + timedelta(days=3), to=("all",))
    active = feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=5))
    expired = feed.make_important(author, until=now - timedelta(hours=1), to=("all",),
                                  published_at=now - timedelta(days=2))
    read = feed.make_important(author, to=("all",), published_at=now - timedelta(minutes=4))
    support.model("feed.ReadMark").objects.create(post=read, user=reader.user, read_at=now)
    own = feed.make_important(reader.user, to=("all",), published_at=now - timedelta(minutes=3))
    doc = _page(reader.client, "/?f=important")
    assert set(block_ids(doc)) | set(list_ids(doc)) == {active.pk, expired.pk, read.pk, own.pk}
    assert set(list_ids(doc)) >= {expired.pk, read.pk, own.pk}
    assert len(block_ids(doc)) + len(list_ids(doc)) == 4


def test_events_filter_shows_only_events():
    """FR-635: «События» — только записи вида «Событие» (в том числе уже начавшиеся)."""
    reader = feed.as_plain()
    author = _author()
    now = timezone.now()
    feed.make_post(author, "post", to=("all",))
    feed.make_important(author, to=("all",))
    future = feed.make_event(author, start=now + timedelta(days=2), to=("all",), published_at=now - timedelta(minutes=2))
    started = feed.make_event(author, start=now - timedelta(hours=3), to=("all",), published_at=now - timedelta(minutes=1))
    assert list_ids(_page(reader.client, "/?f=events")) == [started.pk, future.pk]


def test_mine_filter_shows_only_own_posts():
    """FR-635: «Мои» — записи, где сотрудник автор (любого вида и кому бы ни были адресованы)."""
    reader = feed.as_plain()
    author = _author()
    other = _author("Другой Сотрудник")
    now = timezone.now()
    feed.make_post(author, "post", to=("all",))
    own_post = feed.make_post(reader.user, "post", to=(other,), published_at=now - timedelta(minutes=2))
    own_important = feed.make_important(reader.user, to=("all",), published_at=now - timedelta(minutes=1))
    doc = _page(reader.client, "/?f=mine")
    assert list_ids(doc) == [own_important.pk, own_post.pk] and not block_ids(doc)


def test_mentions_filter_finds_mention_of_to_addressee_and_mention_in_comment():
    """FR-635 (V4 раздела 6): «Упоминают меня» — упоминание в записи (в том числе у адресата «Кому») и в её
    комментарии; адресат без упоминания и упоминание другого — не находятся; запись один раз."""
    reader = feed.as_plain()
    author, stranger = _author(), _author("Другой Сотрудник")
    now = timezone.now()
    addressee_mentioned = feed.make_post(author, "post", to=(reader.user,), mentions=[reader.user],
                                         published_at=now - timedelta(minutes=5))
    via_comment = feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=4))
    feed.comment(via_comment, stranger, "Смотри", mentions=[reader.user])
    only_mention = feed.make_post(author, "post", to=(stranger,), mentions=[reader.user],
                                  published_at=now - timedelta(minutes=3))
    feed.make_post(author, "post", to=(reader.user,), published_at=now - timedelta(minutes=2))
    feed.make_post(author, "post", to=("all",), mentions=[stranger], published_at=now - timedelta(minutes=1))
    ids = list_ids(_page(reader.client, "/?f=mentions"))
    assert ids == [only_mention.pk, via_comment.pk, addressee_mentioned.pk]


def test_author_filter_shows_only_selected_author_posts():
    """FR-635: «Автор» — записи выбранного сотрудника, видимые читателю."""
    reader = feed.as_plain()
    first, second = _author("Первый Автор"), _author("Второй Автор")
    now = timezone.now()
    wanted = [feed.make_post(first, "post", to=("all",), published_at=now - timedelta(minutes=i)) for i in (3, 2)]
    feed.make_post(second, "post", to=("all",), published_at=now - timedelta(minutes=1))
    feed.make_post(first, "post", to=(_author("Не Читатель"),), published_at=now - timedelta(minutes=1))
    assert list_ids(_page(reader.client, f"/?author={first.pk}")) == _ids_desc(wanted)


def test_period_filter_is_inclusive_by_moscow_date_with_clock_at_utc_midnight(clock):
    """FR-635: период «с» / «по» — даты по Москве, обе границы включительно; часы на полночь UTC (сценарий 2 п. 9);
    даты в виде ДД.ММ.ГГГГ и ГГГГ-ММ-ДД."""
    _utc_midnight(clock)
    author = _author()
    reader = feed.as_plain()
    before_day = feed.make_post(author, "post", to=("all",), published_at=feed.moscow(2026, 3, 9, 23, 59))
    day_start = feed.make_post(author, "post", to=("all",), published_at=feed.moscow(2026, 3, 10, 0, 0))
    day_end = feed.make_post(author, "post", to=("all",), published_at=feed.moscow(2026, 3, 10, 23, 59))
    after_day = feed.make_post(author, "post", to=("all",), published_at=feed.moscow(2026, 3, 11, 0, 0))
    for query in ("from=10.03.2026&to=10.03.2026", "from=2026-03-10&to=2026-03-10"):
        assert list_ids(_page(reader.client, "/?" + query)) == [day_end.pk, day_start.pk], query
    assert list_ids(_page(reader.client, "/?from=11.03.2026")) == [after_day.pk]
    assert list_ids(_page(reader.client, "/?to=09.03.2026")) == [before_day.pk]
    assert list_ids(_page(reader.client, "/?from=10.03.2026")) == [after_day.pk, day_end.pk, day_start.pk]


def test_filters_combine_by_and_author_with_period_and_kind_with_period(clock):
    """FR-635: фильтры сочетаются по «и» — автор с периодом, вид с периодом, вид с автором."""
    _utc_midnight(clock)
    first, second = _author("Первый Автор"), _author("Второй Автор")
    reader = feed.as_plain()
    soon = timezone.now() + timedelta(days=5)
    a_day10 = feed.make_post(first, "post", to=("all",), published_at=feed.moscow(2026, 3, 10, 12))
    feed.make_post(first, "post", to=("all",), published_at=feed.moscow(2026, 3, 11, 12))
    feed.make_post(second, "post", to=("all",), published_at=feed.moscow(2026, 3, 10, 13))
    a_event10 = feed.make_event(first, start=soon, to=("all",), published_at=feed.moscow(2026, 3, 10, 14))
    b_event11 = feed.make_event(second, start=soon, to=("all",), published_at=feed.moscow(2026, 3, 11, 14))
    day10 = "from=10.03.2026&to=10.03.2026"
    assert list_ids(_page(reader.client, f"/?author={first.pk}&{day10}")) == [a_event10.pk, a_day10.pk]
    assert list_ids(_page(reader.client, f"/?f=events&{day10}")) == [a_event10.pk]
    assert list_ids(_page(reader.client, f"/?f=events&author={second.pk}")) == [b_event11.pk]
    assert list_ids(_page(reader.client, f"/?f=events&author={second.pk}&{day10}")) == []


def test_more_applies_same_filter_as_first_page():
    """FR-602, FR-635: «Ещё записи» несёт тот же фильтр, что и первая страница."""
    author = _author()
    now = timezone.now()
    events = [feed.make_event(author, start=now + timedelta(days=2), to=("all",),
                              published_at=now - timedelta(minutes=2 * (25 - i))) for i in range(25)]
    normal = [feed.make_post(author, "post", to=("all",), published_at=now - timedelta(minutes=2 * (25 - i) - 1))
              for i in range(25)]
    reader = feed.as_plain()
    doc = _page(reader.client, "/?f=events")
    expected = _ids_desc(events)
    assert list_ids(doc) == expected[:20]
    link = more_link(doc)
    assert link is not None and parse_qs(urlsplit(link.attrs["hx-get"]).query).get("f") == ["events"]
    fragment = _hx(reader.client, link.attrs["hx-get"])
    assert ids_in(fragment) == expected[20:]
    assert not set(ids_in(fragment)) & {p.pk for p in normal}
    assert more_link(fragment) is None


def test_unknown_filter_key_bad_date_and_bad_author_ignored_with_200():
    """FR-635, NFR-608: неизвестный ключ, неверные значения `f`, `author`, `from`, `to` отбрасываются без ошибки —
    ответ 200 и лента как без фильтра."""
    _posts_by_minutes(_author(), 25)
    reader = feed.as_plain()
    expected = list_ids(_page(reader.client))
    assert len(expected) == 20
    for query in ("zzz=1", "f=bogus", "f=ALL", "from=31.02.2026&to=notadate", "author=abc",
                  "author=99999999999999999999", "author=-5", "from=2026-13-45", "to=%00",
                  "f=all%27%3B%20DROP%20TABLE%20feed_post%3B--", "author=1%20OR%201%3D1",
                  "zzz=1&f=bogus&author=abc&from=x&to=y"):
        assert list_ids(_page(reader.client, "/?" + query)) == expected, query


def test_filter_and_cursor_values_are_sql_parameters_not_sql_text(clock):
    """NFR-608: значения фильтра и курсора уходят в SQL параметрами: пробные значения есть среди параметров запросов
    и нет в тексте SQL; значения с SQL-текстом отбрасываются и в запрос не попадают."""
    clock.set(datetime(2026, 3, 12, 12, 34, 56, 789012, tzinfo=UTC))
    author = _author()
    posts = _posts_by_minutes(author, 25)
    reader = feed.as_plain()
    before = datetime(2026, 3, 12, 9, 15, 0, 123456, tzinfo=UTC)
    opened = timezone.now()
    path = ("/feed/more/?before=" + quote(f"{before.isoformat()},987654321") + "&opened=" + quote(opened.isoformat())
            + f"&author={author.pk}&from=10.03.2026&to=11.03.2026")
    with feed.queries_with_params() as pairs:
        assert reader.client.get(path).status_code == 200
    texts = [sql for sql, _ in pairs]
    for probe in ("987654321", "123456", "2026-03", "10.03.2026", "09:15:00", "12:34:56"):
        assert not any(probe in sql for sql in texts), f"значение {probe!r} склеено в текст SQL"
    values = [v for _, params in pairs for v in _flat(params)]
    assert any(str(v) == "987654321" for v in values), "номер курсора — не параметр"
    for moment in (before, opened):
        assert any((isinstance(v, datetime) and v == moment) or (isinstance(v, str) and v.startswith(moment.isoformat()[:19]))
                   for v in values), f"время {moment.isoformat()} — не параметр"
    assert any(v == author.pk or str(v) == str(author.pk) for v in values), "номер автора — не параметр"
    assert any(("2026-03-09" in str(v) or "2026-03-10" in str(v)) for v in values), "начало периода — не параметр"
    assert any(("2026-03-11" in str(v) or "2026-03-12" in str(v)) for v in values), "конец периода — не параметр"
    attack = ("/feed/more/?before=" + quote("1' OR '1'='1") + "&opened=" + quote("1;DROP TABLE feed_post")
              + "&author=" + quote("1 OR 1=1") + "&from=" + quote("';--") + "&to=" + quote('" OR 1=1'))
    with feed.queries_with_params() as pairs:
        assert reader.client.get(attack).status_code == 200
        assert reader.client.get("/?f=" + quote("x' OR 1=1 --") + "&author=" + quote("1; DROP TABLE feed_post")).status_code == 200
    for sql, params in pairs:
        for probe in ("DROP", "OR '1'", ";--"):
            assert probe not in sql, f"значение с SQL-текстом дошло до запроса: {probe!r}"
    assert support.model("feed.Post").objects.count() == len(posts)


def test_more_link_and_ws_connect_built_from_parsed_values_without_foreign_key(clock):
    """FR-635, NFR-608: ссылка «Ещё записи» и адрес соединения строятся из разобранных значений — чужие ключи и
    неверные значения в них не попадают и в разметку не выводятся."""
    _utc_midnight(clock)
    author = _author()
    now = timezone.now()
    for i in range(25):
        feed.make_event(author, start=now + timedelta(days=3), to=("all",),
                        published_at=feed.moscow(2026, 3, 10, 12, 0) + timedelta(minutes=i))
    reader = feed.as_plain()
    probe = quote("<img src=x onerror=alert(1)>")
    response = reader.client.get(f"/?f=events&author={author.pk}&from=10.03.2026&to=11.03.2026&zzz=evil&{probe}=1")
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    doc = tree(html)
    link = more_link(doc)
    assert link is not None
    target = urlsplit(link.attrs["hx-get"])
    values = parse_qs(target.query)
    assert target.path == "/feed/more/" and set(values) <= {"before", "opened", "f", "author", "from", "to"}
    assert values["f"] == ["events"] and values["author"] == [str(author.pk)]
    live = urlsplit(doc.first(id="feed-live").attrs["ws-connect"])
    assert live.path == "/ws/feed/" and set(parse_qs(live.query)) <= {"f", "author", "from", "to"}
    for foreign in ("zzz", "evil", "onerror"):
        assert foreign not in html, f"чужое значение {foreign!r} выведено в разметку"
    html = reader.client.get("/?f=bogus&author=abc&from=xx").content.decode("utf-8")
    assert "bogus" not in html and "author=abc" not in html and "from=xx" not in html


def _selected_f(form: Node):
    select = form.first("select", name="f")
    if select is not None:
        options = select.find("option")
        chosen = [o for o in options if "selected" in o.attrs]
        return (chosen or options)[0].attrs.get("value"), {o.attrs.get("value") for o in options}
    radios = form.find("input", name="f")
    checked = [r for r in radios if "checked" in r.attrs]
    return (checked[0].attrs.get("value") if checked else None), {r.attrs.get("value") for r in radios}


def test_filter_form_uses_get_and_shows_selected_values():
    """FR-635 (раздел 12.2): `form#feed-filters` — GET; «Все» по умолчанию; выбранные `f`, `author`, `from`, `to`
    отмечены и заполнены; форма не вложена в колокольчик."""
    author = _author()
    reader = feed.as_plain()
    doc = _page(reader.client)
    form = doc.first("form", id="feed-filters", data_feed_filters=True)
    assert form is not None and form.attrs.get("method", "get").lower() == "get"
    assert form.attrs.get("action", "") in ("", "/") and not form.find(name="csrfmiddlewaretoken")
    selected, options = _selected_f(form)
    assert selected == "all" and {"all", "important", "events", "mine", "mentions"} <= options
    assert not form.first("input", name="from").attrs.get("value") and not form.first("input", name="to").attrs.get("value")
    doc = _page(reader.client, f"/?f=events&author={author.pk}&from=10.03.2026&to=2026-03-11")
    form = doc.first("form", id="feed-filters")
    assert _selected_f(form)[0] == "events"
    assert form.first("input", name="author").attrs.get("value") == str(author.pk)
    assert _date_of(form.first("input", name="from").attrs["value"]) == date(2026, 3, 10)
    assert _date_of(form.first("input", name="to").attrs["value"]) == date(2026, 3, 11)
    ancestor, ids = form.parent, []
    while ancestor is not None:
        ids.append(ancestor.attrs.get("id"))
        ancestor = ancestor.parent
    assert "notify-bell" not in ids and "staff-filter" not in ids


# --- FR-626: показы при «Ещё записи» ----------------------------------------------------------------------------

def test_more_without_hx_request_writes_no_shown_and_has_no_badge_node():
    """FR-626: `GET /feed/more/` без `HX-Request` показов не пишет и узла числа `#menu-badge-feed` не несёт."""
    _posts_by_minutes(_author(), 45)
    reader = feed.as_plain()
    response = reader.client.get("/feed/more/")
    assert response.status_code == 200
    doc = tree(response)
    assert len(ids_in(doc)) == 20
    assert doc.first(id="menu-badge-feed") is None
    assert not support.model("feed.Shown").objects.filter(user=reader.user).exists()


def test_more_with_hx_request_writes_shown_and_returns_badge_oob():
    """FR-626: `GET /feed/more/` с `HX-Request` пишет показы показанных записей и возвращает `#menu-badge-feed` с
    `hx-swap-oob="true"` и числом без них."""
    _posts_by_minutes(_author(), 45)
    reader = feed.as_plain()
    fragment = _hx(reader.client, "/feed/more/")
    shown_ids = ids_in(fragment)
    assert len(shown_ids) == 20
    written = set(support.model("feed.Shown").objects.filter(user=reader.user).values_list("post_id", flat=True))
    assert written == set(shown_ids)
    badge = fragment.first(id="menu-badge-feed")
    assert badge is not None and badge.attrs.get("hx-swap-oob") == "true"
    assert badge.attrs.get("data-count") == "25" and badge.text() == "25"
