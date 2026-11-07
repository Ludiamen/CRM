"""T-7223 regressions: ранний объём T-7223 + follow-up T-7222a.

Покрытия, которых не хватало в прежних фокус-наборах:
A1 — у сообщения `new` пустой `variants`;
A4 — в `like`/`comment_like` `owner` — автор объекта, а не нажавший «Нравится»;
B1 — верхнеуровневый `since` в `add` убирает записи из `pending`;
B3 — `post=<id>` засевает `ids` и суммарный предел `ids` 300;
B4 — `/feed/new/` ограничивает общий результат 50 записями (важные + обычные);
B5 — вставленные через `/feed/new/` записи получают имена упомянутых.
"""
import json
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as ff
from tests import support_notify as notify
from tests.support import HX

pytestmark = pytest.mark.django_db


def _writer(name: str = "Автор Авторов") -> ff.Session:
    return ff.as_writer(full_name=name)


def _plain(name: str = "Читатель Читателев") -> ff.Session:
    return ff.as_plain(full_name=name)


def _publish(session, *recipients, text: str = "Текст новой записи", kind: str = "post", **extra):
    data = {"kind": kind, "text": text, "to": [f"p{person.pk}" for person in recipients], **extra}
    return session.client.post("/feed/posts/", data, **HX)


def _like(session, post):
    return session.client.post(f"/feed/{post.pk}/like/", **HX)


def _events(spy) -> list[dict]:
    """Различные сообщения `feed.event` (одно и то же сообщение уходит во все группы)."""
    seen, result = set(), []
    for _, message in spy.calls:
        if isinstance(message, dict) and message.get("type") == "feed.event":
            fingerprint = json.dumps(message, sort_keys=True, default=str)
            if fingerprint not in seen:
                seen.add(fingerprint)
                result.append(message)
    return result


def _event(spy, action: str) -> dict:
    found = [m for m in _events(spy) if m["action"] == action]
    assert len(found) == 1, f"ожидалось одно сообщение feed.event ({action}), получено {len(found)}"
    return found[0]


async def _open(hub, reader, query: str = "", ids=(), since=None):
    """Подключение /ws/feed/, sync, ответ на него."""
    conn = await ff.ws_client(reader, query, hub=hub)
    assert conn.accepted, f"соединение /ws/feed/?{query} не принято"
    await ff.send_sync(conn, ids, since or (timezone.now() - timedelta(minutes=30)))
    answer = ""
    for _ in range(6):
        frame = await conn.receive(2.0)
        if frame is None:
            break
        answer += frame
        if 'id="feed-synced"' in frame:
            break
    assert notify.ws_fragments(answer).get("feed-synced") is not None
    return conn


async def _open_card(hub, reader, post_id: int):
    """Подключение карточки (?post=<id>): без sync, просто drain начальных кадров."""
    conn = await ff.ws_client(reader, f"post={post_id}", hub=hub)
    assert conn.accepted, "соединение карточки не принято"
    await _drain(conn, 0.3)
    return conn


async def _drain(conn, wait: float = 0.3) -> str:
    frames = []
    while True:
        frame = await conn.receive(wait)
        if frame is None:
            break
        frames.append(frame)
    return "".join(frames)


async def _send_event(user, message) -> None:
    """Сообщение `feed.event` в личную группу `feed.u.<id>` слоя каналов."""
    from channels.layers import get_channel_layer

    target = getattr(user, "user", user)
    await get_channel_layer().group_send(f"feed.u.{target.pk}", message)


# --- A1: new → variants {} -----------------------------------------------------------------------------------------

def test_new_message_has_empty_variants(django_capture_on_commit_callbacks):
    """A1: у `new` пустой `variants`, meta присутствует."""
    author, reader = _writer(), _plain()
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True):
            response = _publish(author, reader.user, text="Новая запись")
    assert response.status_code == 200
    message = _event(spy, "new")
    assert message["variants"] == {}, "у `new` variants должен быть пустым словарём"
    assert set(message["meta"]) == {"kind", "author", "mentioned", "published_at"}


# --- A4: owner лайка — автор объекта, не лайкающий -----------------------------------------------------------------

def test_post_like_owner_is_post_author_not_liker(django_capture_on_commit_callbacks):
    """A4: `like` записи: `owner` — автор записи, а не нажавший «Нравится»."""
    author, liker, watcher = _writer(), _plain("Болельщик Ку"), _plain("Зритель Узлов")
    post = ff.make_post(author.user, to=[liker.user, watcher.user])
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True):
            response = _like(liker, post)
    assert response.status_code == 200
    message = _event(spy, "like")
    assert message["owner"] == author.user.pk, "owner лайка записи — автор записи"


def test_comment_like_owner_is_comment_author_not_liker(django_capture_on_commit_callbacks):
    """A4: `comment_like`: `owner` — автор комментария, а не нажавший «Нравится»."""
    author, commenter, liker = _writer(), _plain("Комментатор Ку"), _plain("Болельщик Ку")
    post = ff.make_post(author.user, to=[commenter.user, liker.user])
    comment = ff.comment(post, commenter.user, "Комментарий")
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True):
            response = liker.client.post(f"/feed/comments/{comment.pk}/like/", **HX)
    assert response.status_code == 200
    message = _event(spy, "comment_like")
    assert message["owner"] == commenter.user.pk, "owner лайка комментария — автор комментария"
    assert message["comment"] == comment.pk


# --- B1: add + верхнеуровневый since очищает pending ----------------------------------------------------------------

def test_add_top_level_since_drops_pending_not_later_than_it():
    """B1: `{"add": [...], "since": ISO}` убирает из pending записи не позже since."""
    author, reader = _writer(), _plain()
    since = timezone.now() - timedelta(minutes=30)
    old = ff.make_post(author.user, to=[reader.user], published_at=since - timedelta(minutes=1))
    first = ff.make_post(author.user, to=[reader.user], published_at=since + timedelta(minutes=2))
    second = ff.make_post(author.user, to=[reader.user], published_at=since + timedelta(minutes=3))

    async def scenario(hub):
        conn = await _open(hub, reader, ids=[old.pk], since=since)
        await _send_event(reader, {"type": "feed.event", "post": first.pk, "action": "new",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [], "variants": {},
                                   "meta": {"kind": "post", "author": author.user.pk,
                                            "mentioned": [], "published_at": first.published_at.isoformat()}})
        await _send_event(reader, {"type": "feed.event", "post": second.pk, "action": "new",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [], "variants": {},
                                   "meta": {"kind": "post", "author": author.user.pk,
                                            "mentioned": [], "published_at": second.published_at.isoformat()}})
        assert notify.ws_fragments(await _drain(conn)).get("feed-new").attrs.get("data-count") == "2"

        await ff.send_add(conn, [first.pk, second.pk], since=first.published_at)
        await _drain(conn)

        third = await hub.do(lambda: ff.make_post(
            author.user, to=[reader.user], published_at=since + timedelta(minutes=4)))
        await _send_event(reader, {"type": "feed.event", "post": third.pk, "action": "new",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [], "variants": {},
                                   "meta": {"kind": "post", "author": author.user.pk,
                                            "mentioned": [], "published_at": third.published_at.isoformat()}})
        banner = notify.ws_fragments(await _drain(conn)).get("feed-new")
        assert banner.attrs.get("data-count") == "2", "первая запись убрана по since, остались вторая и третья"
        await _send_event(reader, {"type": "feed.event", "post": first.pk, "action": "post",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [],
                                   "variants": {"reader:0": f'<div id="feed-post-{first.pk}-body">x</div>'}})
        assert f"feed-post-{first.pk}-body" in await _drain(conn), "номер из add попал в ids"

    notify.ws_run(scenario)


# --- B3: post= засевает ids; общий предел 300 ---------------------------------------

def test_post_query_seeds_ids_for_card_socket():
    """B3: `?post=<id>` при подключении засевает ids, и кадры о своей записи приходят."""
    author, reader = _writer(), _plain()
    post = ff.make_post(author.user, to=[reader.user])

    async def scenario(hub):
        conn = await _open_card(hub, reader, post.pk)
        await _send_event(reader, {"type": "feed.event", "post": post.pk, "action": "post",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [],
                                   "variants": {"reader:0": f'<div id="feed-post-{post.pk}-body">x</div>'}})
        assert f"feed-post-{post.pk}-body" in await _drain(conn)

    notify.ws_run(scenario)


def test_add_does_not_exceed_total_ids_limit_300():
    """B3: сумма имеющихся ids и добавленных не превышает 300."""
    author, reader = _writer(), _plain()
    post = ff.make_post(author.user, to=[reader.user])
    base = [900_000_000 + i for i in range(295)]

    async def scenario(hub):
        conn = await _open(hub, reader, ids=base, since=timezone.now() - timedelta(minutes=30))
        # 295 + 10 → итого 305, лишние 5 отбрасываются; диапазон не пересекается с base
        await ff.send_add(conn, [post.pk] + [900_001_000 + i for i in range(9)])
        await _drain(conn)
        # 301-й номер отбрасывается: событие о нём не должно дать кадр.
        rejected_id = 900_001_004
        await _send_event(reader, {"type": "feed.event", "post": rejected_id, "action": "post",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [],
                                   "variants": {"reader:0": f'<div id="feed-post-{rejected_id}-body">x</div>'}})
        # первоначальный номер записи должен остаться (важен для функциональности)
        await _send_event(reader, {"type": "feed.event", "post": post.pk, "action": "post",
                                   "owner": author.user.pk, "comment": None,
                                   "moderators": [], "staff_viewers": [],
                                   "variants": {"reader:0": f'<div id="feed-post-{post.pk}-body">x</div>'}})
        frames = await _drain(conn)
        assert f"feed-post-{post.pk}-body" in frames, "пост из add потерян"
        assert f"feed-post-{rejected_id}-body" not in frames, "301-й номер из add не отброшен"

    notify.ws_run(scenario)


# --- B4: /feed/new/ общий предел 50 -------------------------------------------------------------------------------

def test_feed_new_limits_total_inserted_posts_to_50_and_shows_reload():
    """B4: важные + обычные вместе не больше 50; при превышении — ссылка «показать все»."""
    from tests.test_feed_consumers_2 import tree

    author, reader = _writer(), _plain()
    since = timezone.now() - timedelta(minutes=60)
    for i in range(60):
        ff.make_important(author.user, to=[reader.user], published_at=since + timedelta(seconds=i))

    response = reader.client.get("/feed/new/?" + urlencode({"since": since.isoformat()}), **HX)
    assert response.status_code == 200
    doc = tree(response)
    from tests.test_feed_consumers_2 import post_ids
    important_node = doc.first(hx_swap_oob="afterbegin:#feed-important")
    listing_node = doc.first(hx_swap_oob="afterbegin:#feed-list")
    important_count = len(post_ids(important_node)) if important_node else 0
    listing_count = len(post_ids(listing_node)) if listing_node else 0
    total = important_count + listing_count
    assert total == 50, f"ожидалось 50 вставленных записей, получено {total}"
    assert doc.first("a", data_feed_reload=True) is not None, "должна быть ссылка «показать все»"


# --- B5: имена упомянутых в /feed/new/ ------------------------------------------------------------------------------

def test_feed_new_renders_mention_names_in_inserted_cards():
    """B5: вставленные через `/feed/new/` записи показывают имена упомянутых вместо сырых @[id]."""
    from tests.test_feed_consumers_2 import tree

    author, reader, mentioned = _writer(), _plain(), _plain("Упомянутый Узлов")
    since = timezone.now() - timedelta(minutes=60)
    post = ff.make_post(author.user, to=[reader.user], mentions=[mentioned.user],
                        published_at=since + timedelta(minutes=5))

    response = reader.client.get("/feed/new/?" + urlencode({"since": since.isoformat()}), **HX)
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert f">{mentioned.user.full_name}</" in html or mentioned.user.full_name in html
    assert f"@[{mentioned.user.pk}]" not in html
