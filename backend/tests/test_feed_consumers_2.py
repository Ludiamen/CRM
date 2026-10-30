"""T-7125: сообщения `sync` и `add`, плашка «Новых записей» и `GET /feed/new/` (FR-602, FR-626, FR-627, FR-628,
FR-635, NFR-608).

Соединение `/ws/feed/` ведёт `support_feed.ws_client` внутри `support_notify.ws_run`; на `sync` потребитель всегда
отвечает служебным кадром `#feed-synced`, поэтому каждый сценарий начинается с `sync` и ответа на него (после ответа
группа `feed.u.<id>` уже подписана). Сообщения слоя (`feed.event`, CONTRACT-007 11.1) тесты шлют в личную группу
напрямую: так проверяется сам потребитель — разбор фильтра по `meta` без запросов к базе, `pending`, плашка, кадры
только о записях из `ids`. Рассылка из служб — один тест (новый комментарий с настоящей публикацией).
Кадры сервера читаются целиком до паузы (`_drain`): плашка и служебный кадр могут прийти одним или разными кадрами.
Разделы 10.2, 11.1–11.3, 12.2 контракта `CONTRACT-007.md`; план «Живые обновления» и «Лента, курсор, блок важных,
фильтры».

Код среза на уровне модуля не импортируется (CONTRACT-007, «Правила для всех тестов»).
"""
import json
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_feed as feed
from tests import support_notify as notify

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
ROLES = ("reader", "author", "moderator")
LIMIT_BYTES = 16384


# --- разбор разметки ответов HTTP (помощник только этого файла; образец — test_feed_page.py) --------------------------

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

    def find(self, tag=None, **attrs) -> list:
        """Потомки по тегу и атрибутам; имя с дефисом пишется через `_`, `True` — «атрибут есть»."""
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        found = []
        for node in self.walk():
            if tag is not None and node.tag != tag:
                continue
            if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
                found.append(node)
        return found

    def first(self, tag=None, **attrs):
        found = self.find(tag, **attrs)
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


def post_ids(scope) -> list[int]:
    return [int(n.attrs["data-post-id"]) for n in scope.find("article", data_post_id=True)] if scope else []


# --- данные теста -----------------------------------------------------------------------------------------------

def _author(name="Автор Лентов"):
    return factories.make_user(full_name=name)


def _ago(minutes=0, *, seconds=0) -> datetime:
    return (timezone.now() - timedelta(minutes=minutes, seconds=seconds)).replace(microsecond=0)


def _post(author, *, minutes_ago=120, kind="post", to=("all",), **extra):
    """Видимая всем запись, по умолчанию давняя (раньше любого `since` теста)."""
    published = extra.pop("published_at", None) or _ago(minutes_ago)
    if kind == "important":
        return feed.make_important(author, to=to, published_at=published, **extra)
    if kind == "event":
        return feed.make_event(author, start=timezone.now() + timedelta(days=2), to=to, published_at=published, **extra)
    return feed.make_post(author, "post", to=to, published_at=published, **extra)


# --- сообщения слоя и кадры -------------------------------------------------------------------------------------

async def _send_event(user, message) -> None:
    """Сообщение `feed.event` в личную группу `feed.u.<id>` слоя каналов (`user` — `Session` или `core.User`)."""
    from channels.layers import get_channel_layer

    target = getattr(user, "user", user)
    await get_channel_layer().group_send(f"feed.u.{target.pk}", message)


def _new_message(post, *, mentioned=(), published_at=None) -> dict:
    published = published_at or post.published_at
    return {"type": "feed.event", "post": post.pk, "action": "new", "owner": post.author_id, "comment": None,
            "moderators": [], "staff_viewers": [], "variants": {},
            "meta": {"kind": post.kind, "author": post.author_id, "mentioned": list(mentioned),
                     "published_at": published.isoformat()}}


def _variants(html: str) -> dict:
    """Один и тот же фрагмент во всех классах: выбор варианта проверяет T-7123, здесь важен только сам кадр."""
    return {f"{role}:{link}": html for role in ROLES for link in (0, 1)}


def _post_message(post, action="post", *, html=None, comment=None) -> dict:
    marker = html or f'<div id="feed-post-{post.pk}-body" hx-swap-oob="true">Правка записи {post.pk}</div>'
    return {"type": "feed.event", "post": post.pk, "action": action, "owner": post.author_id, "comment": comment,
            "moderators": [], "staff_viewers": [], "variants": _variants(marker)}


async def _drain(conn, wait: float = 0.3) -> str:
    """Все кадры, пришедшие подряд (пауза `wait` с без кадра — конец), одной строкой."""
    frames = []
    while True:
        frame = await conn.receive(wait)
        if frame is None:
            break
        frames.append(frame)
    return "".join(frames)


async def _open(hub, reader, query="", ids=(), since=None):
    """Подключение, `sync`, ответ на него (служебный кадр обязателен); возвращает соединение и текст ответа."""
    conn = await feed.ws_client(reader, query, hub=hub)
    assert conn.accepted, f"соединение /ws/feed/?{query} не принято (код {conn.close_code})"
    await feed.send_sync(conn, ids, since or _ago(30))
    answer = await _drain(conn)
    assert notify.ws_fragments(answer).get("feed-synced") is not None, "на sync нет служебного кадра #feed-synced"
    return conn, answer


def _banner(text):
    return notify.ws_fragments(text).get("feed-new")


def _count(text):
    """`data-count` последней плашки в кадрах; `None` — плашки нет."""
    banner = _banner(text)
    return int(banner.attrs["data-count"]) if banner is not None else None


def _href(text) -> str:
    links = [unescape(value) for value in re.findall(r'hx-get="([^"]+)"', text) if value.startswith("/feed/new/")]
    assert links, "в плашке нет ссылки hx-get на /feed/new/"
    return links[-1]


def _flat(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _flat(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flat(item)
    elif value is not None:
        yield value


# --- sync ---------------------------------------------------------------------------------------------------------

def test_sync_replaces_ids_and_always_answers_with_feed_synced_frame():
    """FR-627: `sync` заменяет `ids` и в любом случае получает служебный кадр `#feed-synced` (даже когда новых записей
    нет, плашки нет); кадры идут только о записях из последнего `sync`."""
    author, reader = _author(), feed.as_plain()
    first, second = _post(author), _post(author)
    since = _ago(30)

    async def scenario(hub):
        conn = await feed.ws_client(reader, "", hub=hub)
        assert conn.accepted
        await feed.send_sync(conn, [first.pk], since)
        answer = await _drain(conn)
        synced = notify.ws_fragments(answer).get("feed-synced")
        assert synced is not None and synced.attrs.get("hx-swap-oob") == "true"
        assert _count(answer) in (None, 0), "новых записей нет — плашки нет"
        await _send_event(reader, _post_message(first))
        assert f"feed-post-{first.pk}-body" in await _drain(conn)
        await _send_event(reader, _post_message(second))
        assert await _drain(conn) == "", "запись вне ids кадра не получает"
        await feed.send_sync(conn, [second.pk], since)
        again = await _drain(conn)
        assert notify.ws_fragments(again).get("feed-synced") is not None, "второй sync тоже получает служебный кадр"
        await _send_event(reader, _post_message(first))
        assert await _drain(conn) == "", "прежние ids заменены: о первой записи кадров больше нет"
        await _send_event(reader, _post_message(second))
        assert f"feed-post-{second.pk}-body" in await _drain(conn)
        assert conn.close_code is None

    notify.ws_run(scenario)


def test_sync_with_posts_after_since_sends_banner_with_their_count():
    """FR-627: `sync` набирает записи, которые сотрудник видит, опубликованные позже `since`, кроме своих, и при
    непустом наборе шлёт плашку с их числом; записи не позже `since`, чужие невидимые и свои в число не входят."""
    author, reader, stranger = _author(), feed.as_plain(), support.make_employee()
    since = _ago(30)
    for minutes in (5, 6, 7):
        _post(author, published_at=_ago(minutes))
    _post(author, published_at=_ago(60))                                    # раньше since
    _post(author, published_at=_ago(4), to=(stranger,))                     # адресована другому человеку
    _post(reader.user, published_at=_ago(3))                                # своя

    async def scenario(hub):
        conn = await feed.ws_client(reader, "", hub=hub)
        await feed.send_sync(conn, [], since)
        answer = await _drain(conn)
        banner = _banner(answer)
        assert banner is not None and banner.attrs.get("data-count") == "3", answer
        assert "Новых записей: 3" in banner.text
        assert notify.ws_fragments(answer).get("feed-synced") is not None

    notify.ws_run(scenario)


def test_sync_collects_pending_in_one_query_visible_filtered_after_since_without_own():
    """FR-627, FR-628, NFR-608: `pending` набирается одним запросом к записям: видимость, фильтр соединения, время
    после `since` и «кроме своих» — в нём самом, `since` — параметр запроса, а не часть его текста."""
    author, reader = _author(), feed.as_plain()
    other = _author("Другой Автор")
    since = _ago(30)
    _post(author, kind="important", published_at=_ago(5))
    _post(author, kind="important", published_at=_ago(6))
    _post(author, published_at=_ago(7))                                     # обычная — фильтру «Важные» не подходит
    _post(other, kind="important", published_at=_ago(60))                   # раньше since
    _post(reader.user, kind="important", published_at=_ago(4))              # своя

    async def scenario(hub):
        conn = await feed.ws_client(reader, "f=important", hub=hub)
        assert conn.accepted
        with feed.queries_with_params() as pairs:
            await feed.send_sync(conn, [], since)
            answer = await _drain(conn)
        selects = [(sql, params) for sql, params in pairs
                   if re.search(r"\bfeed_post\b", sql) and sql.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 1, [sql for sql, _ in selects]
        sql, params = selects[0]
        assert since.isoformat() not in sql, "время since подставлено в текст запроса"
        assert any(value == since or value == since.isoformat() for value in _flat(params)), params
        assert _count(answer) == 2, "видимые важные позже since, кроме своей и обычной"

    notify.ws_run(scenario)


def test_sync_after_reconnect_gives_banner_for_posts_published_during_outage():
    """FR-627: после обрыва соединения (перезапуск, сбой слоя) новое подключение с тем же `since` и `ids` страницы даёт
    плашку по записям, опубликованным за время обрыва."""
    author, reader = _author(), feed.as_plain()
    shown = _post(author)
    since = _ago(30)

    async def scenario(hub):
        conn, answer = await _open(hub, reader, ids=[shown.pk], since=since)
        assert _count(answer) in (None, 0)
        await conn.disconnect()
        await hub.do(lambda: _post(author, published_at=_ago(1)))
        again, answer = await _open(hub, reader, ids=[shown.pk], since=since)
        assert _count(answer) == 1, "запись, опубликованная за время обрыва, должна дать плашку"
        assert "Новых записей: 1" in _banner(answer).text
        assert again.close_code is None

    notify.ws_run(scenario)


# --- add ----------------------------------------------------------------------------------------------------------

def test_add_appends_ids_and_its_since_drops_pending_not_later_than_it():
    """FR-627, FR-602: `add` добавляет номера в `ids` (кадры о них начинают приходить), а его `since` убирает из
    `pending` записи, опубликованные не позже него; остальные остаются."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    old = _post(author)
    first = _post(author, published_at=since + timedelta(minutes=1))
    second = _post(author, published_at=since + timedelta(minutes=2))
    third = _post(author, published_at=since + timedelta(minutes=3))

    async def scenario(hub):
        conn, _ = await _open(hub, reader, ids=[old.pk], since=since)
        await _send_event(reader, _new_message(first))
        await _send_event(reader, _new_message(second))
        assert _count(await _drain(conn)) == 2
        await feed.send_add(conn, [first.pk, second.pk], since=first.published_at)
        await _drain(conn)
        await _send_event(reader, _new_message(third))
        assert _count(await _drain(conn)) == 2, "первая убрана по since (не позже), остались вторая и третья"
        await _send_event(reader, _post_message(first))
        assert f"feed-post-{first.pk}-body" in await _drain(conn), "номер из add попал в ids"
        await _send_event(reader, _post_message(old))
        assert f"feed-post-{old.pk}-body" in await _drain(conn), "прежние ids остались"

    notify.ws_run(scenario)


# --- пределы и мусор ----------------------------------------------------------------------------------------------

def test_client_message_over_16_kb_closes_with_1009():
    """FR-627: сообщение клиента больше 16 КБ (по байтам, `len(text.encode()) > 16384`) закрывает соединение кодом
    1009; ровно 16 КБ — нет."""
    reader = feed.as_plain()
    base = len(json.dumps({"add": [], "pad": ""}).encode())

    async def scenario(hub):
        conn, _ = await _open(hub, reader)
        await conn.send(json.dumps({"add": [], "pad": "x" * (LIMIT_BYTES - base)}))
        assert await conn.wait_close(0.5) is None and conn.close_code is None, "ровно 16 КБ — не больше предела"
        await conn.send(json.dumps({"add": [], "pad": "x" * (LIMIT_BYTES - base + 1)}))
        assert await conn.wait_close(2.0) == 1009
        wide, _ = await _open(hub, reader)
        await wide.send("я" * (LIMIT_BYTES // 2 + 1))   # 8 193 знака — 16 386 байт: предел считается в байтах
        assert await wide.wait_close(2.0) == 1009

    notify.ws_run(scenario)


def test_ids_over_300_are_dropped():
    """FR-627: в `ids` не больше 300 номеров, лишнее отбрасывается: кадры приходят о номерах из первых трёхсот и не
    приходят о номере за пределом."""
    author, reader = _author(), feed.as_plain()
    inside, outside = _post(author), _post(author)
    fillers = [900_000_000 + index for index in range(400)]
    numbers = [inside.pk] + fillers[:309] + [outside.pk] + fillers[309:349]
    assert len(numbers) == 351 and numbers.index(outside.pk) == 310

    async def scenario(hub):
        conn, _ = await _open(hub, reader, ids=numbers)
        await _send_event(reader, _post_message(outside))
        assert await _drain(conn) == "", "номер за пределом 300 отброшен"
        await _send_event(reader, _post_message(inside))
        assert f"feed-post-{inside.pk}-body" in await _drain(conn)
        assert conn.close_code is None

    notify.ws_run(scenario)


def test_unknown_messages_and_bad_ids_are_ignored_without_server_error():
    """FR-627, NFR-608: не JSON, неизвестные ключи, не те типы, неверные номера и время игнорируются: сервер не
    падает, соединение остаётся, верные номера из того же сообщения принимаются, следующий `sync` отвечает как обычно."""
    author, reader = _author(), feed.as_plain()
    good, added = _post(author), _post(author)
    since = _ago(30)

    async def scenario(hub):
        conn, _ = await _open(hub, reader)
        for text in ("это не json", "{", "null", "[1, 2, 3]", '"sync"', '{"unknown": 1}', '{"sync": "x"}',
                     '{"sync": {"ids": 5}}', '{"sync": {}}', '{"add": "x"}', '{"add": {"a": 1}}',
                     '{"sync": {"ids": [1], "since": "вчера"}}', '{"add": [1], "since": 5}',
                     '{"sync": {"ids": ["1; DROP TABLE feed_post"], "since": "2026-13-45T99:99"}}'):
            await conn.send(text)
        assert await conn.wait_close(0.5) is None and conn.close_code is None, "соединение закрыто мусором"
        await feed.send_sync(conn, [good.pk, "abc", None, -5, {}, [1]], since)
        assert notify.ws_fragments(await _drain(conn)).get("feed-synced") is not None
        await _send_event(reader, _post_message(good))
        assert f"feed-post-{good.pk}-body" in await _drain(conn), "верный номер среди неверных принят"
        await conn.send(json.dumps({"add": [added.pk, "x", None]}))
        await _drain(conn)
        await _send_event(reader, _post_message(added))
        assert f"feed-post-{added.pk}-body" in await _drain(conn), "верный номер среди неверных в add принят"
        assert conn.close_code is None

    notify.ws_run(scenario)


# --- кадры только о записях из ids --------------------------------------------------------------------------------

def test_frames_are_sent_only_about_posts_in_ids():
    """FR-627, FR-628: кадры о правке, удалении, комментарии и отметке приходят только о записях из `ids`; о прочих —
    ни одного (иначе htmx пишет `htmx:oobErrorNoTarget` на каждый чужой кадр)."""
    author, reader = _author(), feed.as_plain()
    shown, other = _post(author), _post(author)

    async def scenario(hub):
        conn, _ = await _open(hub, reader, ids=[shown.pk])
        for action in ("post", "delete", "comment", "like", "read", "answer"):
            await _send_event(reader, _post_message(other, action))
        await _send_event(reader, _post_message(shown))
        frames = await _drain(conn)
        assert f"feed-post-{shown.pk}-body" in frames
        assert f"feed-post-{other.pk}" not in frames, "кадр о записи вне ids отправлен"

    notify.ws_run(scenario)


# --- плашка: фильтры по meta без запросов -------------------------------------------------------------------------

def test_new_action_matches_filter_by_meta_without_database_queries():
    """FR-627, FR-635: событие `new` проверяется по `meta` (вид, автор, упомянутые, время) без единого запроса к базе:
    подходящая запись даёт плашку, неподходящая — нет."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    regular = _post(author, published_at=_ago(5))
    important = _post(author, kind="important", published_at=_ago(4))

    async def scenario(hub):
        conn, _ = await _open(hub, reader, "f=important", since=since)
        with feed.queries_with_params() as pairs:
            await _send_event(reader, _new_message(regular))
            nothing = await _drain(conn)
            await _send_event(reader, _new_message(important))
            banner = await _drain(conn)
        assert pairs == [], f"запросы к базе при разборе new: {[sql for sql, _ in pairs]}"
        assert _count(nothing) in (None, 0), "обычная запись фильтру «Важные» не подходит"
        assert _count(banner) == 1

    notify.ws_run(scenario)


def test_new_banner_follows_all_important_and_events_filters():
    """FR-627, FR-635: «Все» считает любые записи, «Важные» — только вид «Важное», «События» — только вид «Событие»."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    posts = [_post(author, published_at=_ago(6)), _post(author, kind="important", published_at=_ago(5)),
             _post(author, kind="event", published_at=_ago(4))]

    async def scenario(hub):
        everything, _ = await _open(hub, reader, "", since=since)
        important, _ = await _open(hub, reader, "f=important", since=since)
        events, _ = await _open(hub, reader, "f=events", since=since)
        for post in posts:
            await _send_event(reader, _new_message(post))
        assert _count(await _drain(everything)) == 3
        assert _count(await _drain(important)) == 1
        assert _count(await _drain(events)) == 1

    notify.ws_run(scenario)


def test_new_banner_follows_mine_mentions_me_and_author_filters():
    """FR-627, FR-635: «Мои» — автор я (но своя запись в плашку не идёт, поэтому плашки нет совсем), «Упоминают меня» —
    я среди упомянутых в `meta`, «Автор» — автор записи равен выбранному."""
    chosen, other, reader = _author("Выбранный Автор"), _author("Другой Автор"), feed.as_plain()
    stranger = support.make_employee()
    since = _ago(30)
    by_chosen = _post(chosen, published_at=_ago(6))
    by_other = _post(other, published_at=_ago(5))
    own = _post(reader.user, published_at=_ago(4))

    async def scenario(hub):
        mine, _ = await _open(hub, reader, "f=mine", since=since)
        mentions, _ = await _open(hub, reader, "f=mentions", since=since)
        by_author, _ = await _open(hub, reader, f"author={chosen.pk}", since=since)
        await _send_event(reader, _new_message(by_other))
        await _send_event(reader, _new_message(own))
        await _send_event(reader, _new_message(by_other, mentioned=[stranger.pk]))
        await _send_event(reader, _new_message(by_other, mentioned=[reader.user.pk]))
        await _send_event(reader, _new_message(by_chosen))
        assert _count(await _drain(mine)) in (None, 0), "«Мои»: чужие не подходят, своя в плашку не идёт"
        assert _count(await _drain(mentions)) == 1, "«Упоминают меня»: только запись с моим номером в meta.mentioned"
        assert _count(await _drain(by_author)) == 1, "«Автор»: только записи выбранного автора"

    notify.ws_run(scenario)


def test_new_banner_follows_period_filter():
    """FR-627, FR-635: период — время публикации в пределах дат «с» и «по» включительно по Москве (полночь по Москве —
    21:00 UTC предыдущего дня); даты принимаются в видах `ГГГГ-ММ-ДД` и `ДД.ММ.ГГГГ`."""
    author, reader = _author(), feed.as_plain()
    since = datetime(2026, 3, 1, tzinfo=UTC)
    before = _post(author, published_at=datetime(2026, 3, 9, 20, 59, 59, tzinfo=UTC))    # 09.03 23:59:59 по Москве
    first_second = _post(author, published_at=datetime(2026, 3, 9, 21, 0, 0, tzinfo=UTC))  # 10.03 00:00:00
    last_second = _post(author, published_at=datetime(2026, 3, 12, 20, 59, 59, tzinfo=UTC))  # 12.03 23:59:59
    after = _post(author, published_at=datetime(2026, 3, 12, 21, 0, 0, tzinfo=UTC))      # 13.03 00:00:00

    async def scenario(hub):
        iso, _ = await _open(hub, reader, "from=2026-03-10&to=2026-03-12", since=since)
        dotted, _ = await _open(hub, reader, "from=10.03.2026&to=12.03.2026", since=since)
        for post in (before, first_second, last_second, after):
            await _send_event(reader, _new_message(post))
        assert _count(await _drain(iso)) == 2, "10.03 00:00 и 12.03 23:59:59 по Москве входят, остальные нет"
        assert _count(await _drain(dotted)) == 2

    notify.ws_run(scenario)


def test_new_post_not_later_than_since_does_not_go_to_banner():
    """FR-627: запись, опубликованная не позже `since` соединения, в плашку не идёт (строго «позже»)."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    at_since = _post(author, published_at=since)
    earlier = _post(author, published_at=since - timedelta(seconds=1))
    later = _post(author, published_at=since + timedelta(seconds=1))

    async def scenario(hub):
        conn, _ = await _open(hub, reader, since=since)
        await _send_event(reader, _new_message(at_since))
        await _send_event(reader, _new_message(earlier))
        assert _count(await _drain(conn)) in (None, 0)
        await _send_event(reader, _new_message(later))
        assert _count(await _drain(conn)) == 1

    notify.ws_run(scenario)


def test_own_post_does_not_go_to_banner():
    """FR-627: своя запись автора в плашку не идёт (у автора она вставлена ответом на публикацию), чужая идёт."""
    author, reader = _author(), feed.as_plain()
    own = _post(reader.user, published_at=_ago(5))
    foreign = _post(author, published_at=_ago(4))

    async def scenario(hub):
        conn, _ = await _open(hub, reader)
        await _send_event(reader, _new_message(own))
        assert _count(await _drain(conn)) in (None, 0)
        await _send_event(reader, _new_message(foreign))
        assert _count(await _drain(conn)) == 1

    notify.ws_run(scenario)


def test_post_card_socket_gets_no_banner():
    """FR-627: соединение карточки (`?post=<id>`) плашки не получает, но кадры о своей записи получает."""
    author, reader = _author(), feed.as_plain()
    card = _post(author)
    fresh = _post(author, published_at=_ago(5))

    async def scenario(hub):
        conn, answer = await _open(hub, reader, f"post={card.pk}", ids=[card.pk])
        assert _count(answer) in (None, 0)
        await _send_event(reader, _new_message(fresh))
        assert _count(await _drain(conn)) in (None, 0), "карточка плашки не получает"
        await _send_event(reader, _post_message(card))
        assert f"feed-post-{card.pk}-body" in await _drain(conn)

    notify.ws_run(scenario)


def test_deleting_pending_post_updates_banner_and_hides_it_at_zero():
    """FR-627: удаление записи из `pending` убирает её и обновляет плашку; при нуле плашка — тот же узел с `d-none`,
    без текста и ссылки; кадра удаления о записи вне `ids` нет."""
    author, reader = _author(), feed.as_plain()
    first, second = _post(author, published_at=_ago(5)), _post(author, published_at=_ago(4))
    delete_frame = '<div id="feed-post-{id}" hx-swap-oob="delete"></div>'

    async def scenario(hub):
        conn, _ = await _open(hub, reader)
        await _send_event(reader, _new_message(first))
        await _send_event(reader, _new_message(second))
        assert _count(await _drain(conn)) == 2
        await _send_event(reader, _post_message(first, "delete", html=delete_frame.format(id=first.pk)))
        step = await _drain(conn)
        assert _count(step) == 1, "плашка обновлена до одной записи"
        assert f'id="feed-post-{first.pk}"' not in step, "кадр удаления о записи вне ids отправлен"
        await _send_event(reader, _post_message(second, "delete", html=delete_frame.format(id=second.pk)))
        last = await _drain(conn)
        hidden = _banner(last)
        assert hidden is not None and "d-none" in hidden.attrs.get("class", "").split()
        assert hidden.attrs.get("data-count") == "0" and hidden.text == ""
        assert hidden.attrs.get("hx-swap-oob") == "true" and "hx-get" not in last, "скрытая плашка без ссылки"

    notify.ws_run(scenario)


# --- плашка: вид кадра --------------------------------------------------------------------------------------------

def test_banner_is_feed_new_with_new_posts_count_text_and_link_to_feed_new():
    """FR-627: плашка — `#feed-new` с `hx-swap-oob="true"`, `data-count`, текстом «Новых записей: N» и ссылкой `hx-get`
    на `/feed/new/?since=<ISO>&<фильтр>`: `since` — из `sync` (в адресе `+` кодируется `%2B`), фильтр — разобранный
    из соединения."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    posts = [_post(author, kind="event", published_at=_ago(5)), _post(author, kind="event", published_at=_ago(4))]

    async def scenario(hub):
        conn, _ = await _open(hub, reader, f"f=events&author={author.pk}", since=since)
        for post in posts:
            await _send_event(reader, _new_message(post))
        frame = await _drain(conn)
        banner = _banner(frame)
        assert banner is not None
        assert banner.attrs.get("hx-swap-oob") == "true" and banner.attrs.get("data-count") == "2"
        assert "Новых записей: 2" in banner.text
        link = urlsplit(_href(frame))
        assert link.path == "/feed/new/" and "+" not in link.query, "в адресе плюс должен быть закодирован"
        values = parse_qs(link.query)
        assert datetime.fromisoformat(values["since"][0]) == since
        assert values.get("f") == ["events"] and values.get("author") == [str(author.pk)]

    notify.ws_run(scenario)


def test_regular_and_important_posts_give_banner_new_posts_two():
    """FR-627, FR-602: обычная и важная записи, которые сотрудник видит, дают одну плашку «Новых записей: 2»
    (сценарий 8 п. 10)."""
    author, reader = _author(), feed.as_plain()
    regular = _post(author, published_at=_ago(5))
    important = _post(author, kind="important", published_at=_ago(4))

    async def scenario(hub):
        conn, _ = await _open(hub, reader)
        await _send_event(reader, _new_message(regular))
        await _send_event(reader, _new_message(important))
        frame = await _drain(conn)
        assert _count(frame) == 2 and "Новых записей: 2" in _banner(frame).text

    notify.ws_run(scenario)


def test_new_comment_frame_is_beforeend_into_post_comments_and_carries_comment_id(django_capture_on_commit_callbacks):
    """FR-627: комментарий коллеги приходит кадром `beforeend:#feed-post-<id>-comments` с элементом `#c<id>`; в
    сообщении слоя `feed.event` стоят действие `comment` и номер комментария (по нему `feed.js` не вставляет повторно)."""
    author, reader, commenter = _author(), feed.as_plain(), feed.as_plain()
    post = _post(author)

    def comment():
        with django_capture_on_commit_callbacks(execute=True):
            response = commenter.client.post(f"/feed/{post.pk}/comments/", {"text": "Комментарий коллеги"}, **support.HX)
        assert response.status_code == 200
        return support.model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}").order_by("-pk").first().pk

    async def scenario(hub):
        conn, _ = await _open(hub, reader, ids=[post.pk])
        with feed.layer_spy() as spy:
            comment_id = await hub.do(comment)
            frame = await conn.receive(2.0)
        assert frame is not None, "кадр нового комментария не пришёл за 2 с"
        assert f'hx-swap-oob="beforeend:#feed-post-{post.pk}-comments"' in frame
        assert f'id="c{comment_id}"' in frame
        messages = [m for m in spy.by_group.get(f"feed.u.{reader.user.pk}", []) if m.get("action") == "comment"]
        assert len(messages) == 1 and messages[0]["comment"] == comment_id, spy.by_group

    notify.ws_run(scenario)


# --- GET /feed/new/ -----------------------------------------------------------------------------------------------

def _get_new(client, since, query="", **headers):
    return client.get("/feed/new/?" + urlencode({"since": since.isoformat()}) + query, **headers)


def _list_node(doc):
    return doc.first(hx_swap_oob="afterbegin:#feed-list")


def _important_node(doc):
    return doc.first(hx_swap_oob="afterbegin:#feed-important")


def test_feed_new_returns_up_to_50_visible_filtered_posts_after_since():
    """FR-627, FR-602, FR-628: `/feed/new/` — записи после `since`, которые сотрудник видит и которые подходят под
    фильтр (чужие невидимые и записи не позже `since` не входят), наверх ленты `afterbegin:#feed-list`; не больше 50,
    при большем числе — ссылка «показать все» перезагрузкой `a[data-feed-reload]`."""
    author, reader, stranger = _author(), feed.as_plain(), support.make_employee()
    since = _ago(30)
    regular = [_post(author, published_at=_ago(10 - index)) for index in range(3)]
    event = _post(author, kind="event", published_at=_ago(6))
    _post(author, published_at=_ago(5), to=(stranger,))
    _post(author, published_at=_ago(60))

    doc = tree(_get_new(reader.client, since))
    assert set(post_ids(_list_node(doc))) == {post.pk for post in regular} | {event.pk}
    assert doc.first("a", data_feed_reload=True) is None, "до 50 записей ссылки «показать все» нет"
    only_events = tree(_get_new(reader.client, since, "&f=events"))
    assert post_ids(_list_node(only_events)) == [event.pk]

    many = _author("Частый Автор")
    for index in range(60):
        _post(many, published_at=_ago(25, seconds=index))
    crowded = tree(_get_new(reader.client, since, f"&author={many.pk}"))
    assert len(post_ids(_list_node(crowded))) == 50
    assert crowded.first("a", data_feed_reload=True) is not None, "больше 50 — ссылка «показать все»"


def test_feed_new_puts_unread_important_into_shown_important_block():
    """FR-627, FR-602: при показанном блоке важных непрочитанное важное встаёт в `afterbegin:#feed-important`, а не в
    ленту; прочитанное важное и обычная запись — наверх ленты."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    unread = _post(author, kind="important", published_at=_ago(10))
    read = _post(author, kind="important", published_at=_ago(9))
    support.model("feed.ReadMark").objects.create(post=read, user=reader.user, read_at=timezone.now())
    regular = _post(author, published_at=_ago(8))

    doc = tree(_get_new(reader.client, since))
    block, listing = _important_node(doc), _list_node(doc)
    assert block is not None and post_ids(block) == [unread.pk]
    assert set(post_ids(listing)) == {read.pk, regular.pk}, "в блоке важных запись не повторяется в ленте"


def test_feed_new_puts_important_on_top_with_regular_when_block_hidden():
    """FR-627, FR-602, FR-635: когда блок важных не показан (задан «Автор»), важная запись идёт наверх ленты вместе с
    обычными, блока в ответе нет."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    important = _post(author, kind="important", published_at=_ago(10))
    regular = _post(author, published_at=_ago(9))

    doc = tree(_get_new(reader.client, since, f"&author={author.pk}"))
    assert _important_node(doc) is None, "блок важных при фильтре «Автор» не показан"
    assert set(post_ids(_list_node(doc))) == {important.pk, regular.pk}


def test_feed_new_replaces_banner_with_empty_one_with_new_since():
    """FR-627: ответ заменяет плашку пустой: `#feed-new` с `hx-swap-oob="true"`, `d-none`, `data-count="0"`, без текста
    и ссылки, и несёт новый `since` в `data-since` (ISO, UTC, К45) не раньше публикации самой новой из вставленных записей."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    newest = _post(author, published_at=_ago(5))
    _post(author, published_at=_ago(8))

    doc = tree(_get_new(reader.client, since, **support.HX))
    banner = doc.first(id="feed-new")
    assert banner is not None and banner.attrs.get("hx-swap-oob") == "true"
    assert "d-none" in banner.classes and banner.attrs.get("data-count") == "0"
    assert banner.text() == "" and not banner.find("a"), "пустая плашка без текста и ссылки"
    assert "data-since" in banner.attrs, "в пустой плашке нет data-since"
    stamp = datetime.fromisoformat(banner.attrs["data-since"])
    assert stamp.utcoffset() == timedelta(0), "data-since — ISO в UTC"
    assert newest.published_at <= stamp <= timezone.now() + timedelta(minutes=1)


def test_feed_new_records_shown_and_count_only_with_hx_request():
    """FR-627, FR-602, FR-626: без `HX-Request` `/feed/new/` показов не пишет и узла числа не несёт; с ним — записывает
    показы вставленных записей и возвращает `#menu-badge-feed` (`hx-swap-oob`) с числом оставшихся непрочитанных."""
    author, reader = _author(), feed.as_plain()
    since = _ago(30)
    fresh = [_post(author, published_at=_ago(10 - index)) for index in range(3)]
    for index in range(2):                                           # непрочитанные, но раньше since: не вставляются
        _post(author, published_at=_ago(60 + index))
    Shown = support.model("feed.Shown")

    plain = _get_new(reader.client, since)
    assert plain.status_code == 200
    assert tree(plain).first(id="menu-badge-feed") is None
    assert not Shown.objects.filter(user=reader.user).exists()

    htmx = tree(_get_new(reader.client, since, **support.HX))
    assert set(post_ids(_list_node(htmx))) == {post.pk for post in fresh}
    assert set(Shown.objects.filter(user=reader.user).values_list("post_id", flat=True)) == {p.pk for p in fresh}
    badge = htmx.first(id="menu-badge-feed")
    assert badge is not None and badge.attrs.get("hx-swap-oob") == "true"
    assert badge.attrs.get("data-count") == "2" and badge.text() == "2"
