"""T-7122: получатели при каждой рассылке живых обновлений (FR-606, FR-626, FR-627, FR-628).

План: «Живые обновления» (рассылка, шаг 1, группы), «Правка и удаление» (получатели удаления снимаются до удаления);
CONTRACT-007: 5.5 (`live.publish_event`), 5.8 (`layer_spy`), 11.1 (группы, `feed.event`, `action` по действию), 11.3
(кадры), решения 6 (г), 7, 18 задач. Рассылка идёт после фиксации: действие выполняется внутри
`django_capture_on_commit_callbacks(execute=True)`. Состав получателей видит `layer_spy` (группы `feed.u.<id>`), доставку —
настоящие соединения `/ws/feed/` и `/ws/notify/` через `support_notify.ws_run`. Действия — обычные запросы по путям плана
(`/feed/posts/`, `/feed/<id>/comments/` и так далее): имён служб тест не знает. Код среза на уровне модуля не импортируется.
"""
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as ff
from tests import support_org as org
from tests.support import HX
from tests.support_notify import ws_fragments, ws_run

pytestmark = pytest.mark.django_db


# --- помощники только этого файла -----------------------------------------------------------------------------

def _writer(name: str = "Автор Авторов") -> ff.Session:
    return ff.as_writer(full_name=name)


def _plain(name: str = "Читатель Читателев") -> ff.Session:
    return ff.as_plain(full_name=name)


def _publish(session, *recipients, text: str = "Текст новой записи", kind: str = "post", **extra):
    data = {"kind": kind, "text": text, "to": [f"p{person.pk}" for person in recipients], **extra}
    return session.client.post("/feed/posts/", data, **HX)


def _comment(session, post, text: str = "Новый комментарий"):
    return session.client.post(f"/feed/{post.pk}/comments/", {"text": text}, **HX)


def _like(session, post):
    return session.client.post(f"/feed/{post.pk}/like/", **HX)


def _edit(session, post, recipients, text: str = "Правленый текст"):
    return session.client.post(f"/feed/{post.pk}/edit/",
                               {"text": text, "to": [f"p{person.pk}" for person in recipients]}, **HX)


def _comment_row(post):
    return support.model("core.Comment").objects.get(object_ref=f"feed.post:{post.pk}")


def _do(capture, action):
    """Действие и его рассылка после фиксации (внутри потока теста)."""
    with capture(execute=True):
        return action()


def _spied(capture, action, *, passthrough: bool = False):
    with ff.layer_spy(passthrough=passthrough) as spy:
        response = _do(capture, action)
    return spy, response


def _feed_groups(spy) -> set[str]:
    return {group for group in spy.by_group if group.startswith("feed.u.")}


def _gid(user) -> str:
    return f"feed.u.{user.pk}"


def _nid(user) -> str:
    return f"notify.u.{user.pk}"


def _events(spy) -> list[dict]:
    return [message for _, message in spy.calls if isinstance(message, dict) and message.get("type") == "feed.event"]


def _badges(frames: list[str]) -> list:
    """Фрагменты `#menu-badge-feed` во всех кадрах колокольчика."""
    found = []
    for frame in frames:
        fragment = ws_fragments(frame).get("menu-badge-feed")
        if fragment is not None:
            found.append(fragment)
    return found


def _banners(frames: list[str]) -> list:
    found = []
    for frame in frames:
        fragment = ws_fragments(frame).get("feed-new")
        if fragment is not None:
            found.append(fragment)
    return found


async def _open(hub, session, query: str = "", ids=()):
    """Соединение `/ws/feed/` и `sync` с номерами страницы; ждёт служебный кадр `#feed-synced`."""
    conn = await ff.ws_client(session, query, hub=hub)
    assert conn.accepted, "соединение ленты не принято"
    await ff.send_sync(conn, ids, timezone.now())
    for _ in range(6):
        frame = await conn.receive(2.0)
        assert frame is not None, "на `sync` нет ответа"
        if 'id="feed-synced"' in frame:
            return conn
    raise AssertionError("служебного кадра #feed-synced нет")


async def _open_bell(hub, session):
    """Соединение колокольчика `/ws/notify/`; число при подключении прочитано."""
    conn = await hub.connect(session.client)
    assert conn.accepted
    assert await conn.receive() is not None, "число при подключении не пришло"
    return conn


async def _drain(conn, timeout: float = 0.6) -> list[str]:
    frames = []
    while True:
        frame = await conn.receive(timeout)
        if frame is None:
            return frames
        frames.append(frame)


# --- получатели -----------------------------------------------------------------------------------------------------

def test_publish_frame_is_sent_only_after_commit_into_personal_feed_groups(django_capture_on_commit_callbacks):
    """FR-627: рассылка идёт после фиксации; сообщение `feed.event` уходит в личные группы `feed.u.<id>` тех, кто
    видит запись (адресат и автор), и не уходит постороннему; в каждую группу — одно сообщение."""
    author, reader, stranger = _writer(), _plain("Адресат Адресатов"), _plain("Посторонний Лиц")
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True) as callbacks:
            response = _publish(author, reader.user)
            assert response.status_code == 200
            assert callbacks, "рассылка ставится в `transaction.on_commit`"
            assert spy.calls == [], "до фиксации сообщений слоя нет"
    post = support.model("feed.Post").objects.get(author=author.user)
    assert post.pk
    assert _feed_groups(spy) == {_gid(author.user), _gid(reader.user)}
    assert _gid(stranger.user) not in spy.by_group
    for group in _feed_groups(spy):
        assert [m["type"] for m in spy.by_group[group]] == ["feed.event"], "в группу уходит одно сообщение"
    message = spy.by_group[_gid(reader.user)][0]
    assert message["post"] == post.pk and message["action"] == "new"


def test_recipients_are_visibility_audience_computed_at_each_broadcast(django_capture_on_commit_callbacks):
    """FR-628, FR-606: получатели каждой рассылки — `visibility.audience(post)` на момент рассылки: пришедший в узел
    получает следующую, ушедший — нет."""
    from apps.feed.services import visibility

    author = _writer()
    unit = org.make_unit("Отдел связи")
    first, second, newcomer = _plain("Первый Узлов"), _plain("Второй Узлов"), _plain("Третий Узлов")
    for member in (first, second):
        org.make_member(member.user, unit)
    person = _plain("Человек Личный")
    post = ff.make_post(author.user, to=[unit, person.user])

    spy, _ = _spied(django_capture_on_commit_callbacks, lambda: _like(author, post))
    expected = {f"feed.u.{pk}" for pk in visibility.audience(post)}
    assert _feed_groups(spy) == expected
    assert {_gid(first.user), _gid(second.user), _gid(person.user), _gid(author.user)} == expected

    org.make_member(newcomer.user, unit)
    spy, _ = _spied(django_capture_on_commit_callbacks, lambda: _like(author, post))
    assert _gid(newcomer.user) in _feed_groups(spy)
    assert _feed_groups(spy) == {f"feed.u.{pk}" for pk in visibility.audience(post)}

    support.model("org.Membership").objects.filter(user=first.user).delete()
    spy, _ = _spied(django_capture_on_commit_callbacks, lambda: _like(author, post))
    assert _gid(first.user) not in _feed_groups(spy)
    assert _feed_groups(spy) == {f"feed.u.{pk}" for pk in visibility.audience(post)}


def test_post_only_to_petrov_gives_other_open_sockets_no_banner_count_or_fragment_on_publish(
        django_capture_on_commit_callbacks):
    """FR-628, FR-606: запись адресована только Петрову — у других сотрудников с открытой лентой нет ни плашки, ни числа
    у «Ленты», ни фрагмента; у Петрова (контроль) плашка «Новых записей: 1» и число 1."""
    capture = django_capture_on_commit_callbacks
    author, petrov = _writer(), _plain("Петров Пётр")
    others = [_plain("Иванов Иван"), ff.as_moderator(full_name="Модераторов Михаил")]

    async def scenario(hub):
        petrov_feed, petrov_bell = await _open(hub, petrov), await _open_bell(hub, petrov)
        other_feeds = [await _open(hub, other) for other in others]
        other_bells = [await _open_bell(hub, other) for other in others]
        response = await hub.do(_do, capture, lambda: _publish(author, petrov.user))
        assert response.status_code == 200
        banners = _banners(await _drain(petrov_feed))
        assert banners and banners[-1].attrs["data-count"] == "1", "Петров не получил плашку"
        assert [b.attrs["data-count"] for b in _badges(await _drain(petrov_bell))][-1:] == ["1"], "число у Петрова"
        for conn in other_feeds:
            assert await _drain(conn) == [], "посторонний получил кадр ленты"
        for conn in other_bells:
            assert _badges(await _drain(conn)) == [], "посторонний получил число «Ленты»"

    ws_run(scenario)


def test_post_only_to_petrov_gives_other_open_sockets_no_fragment_or_count_on_comment(
        django_capture_on_commit_callbacks):
    """FR-628, FR-606: комментарий к записи только для Петрова не даёт другим ни фрагмента, ни числа, даже если номер
    записи есть в `ids` их соединения; Петров (контроль) получает вставку комментария."""
    capture = django_capture_on_commit_callbacks
    author, petrov = _writer(), _plain("Петров Пётр")
    others = [_plain("Иванов Иван"), ff.as_moderator(full_name="Модераторов Михаил")]
    post = ff.make_post(author.user, to=[petrov.user])

    async def scenario(hub):
        petrov_feed = await _open(hub, petrov, ids=[post.pk])
        other_feeds = [await _open(hub, other, ids=[post.pk]) for other in others]
        other_bells = [await _open_bell(hub, other) for other in others]
        response = await hub.do(_do, capture, lambda: _comment(author, post))
        assert response.status_code == 200
        frames = await _drain(petrov_feed)
        assert any(f"beforeend:#feed-post-{post.pk}-comments" in frame for frame in frames), "Петров без комментария"
        for conn in other_feeds:
            assert await _drain(conn) == [], "посторонний получил фрагмент комментария"
        for conn in other_bells:
            assert _badges(await _drain(conn)) == []

    ws_run(scenario)


def test_employee_moved_out_of_unit_gets_no_next_broadcast_of_unit_post(django_capture_on_commit_callbacks):
    """FR-628, FR-606: пока сотрудник в узле, он получает кадры о записи узла; после перевода в другой узел следующая
    рассылка до него не доходит (ни кадр записи, ни число «Ленты»)."""
    capture = django_capture_on_commit_callbacks
    author, mover = _writer(), _plain("Переведённый Узлов")
    here, there = org.make_unit("Прежний отдел"), org.make_unit("Новый отдел")
    org.make_member(mover.user, here)
    post = ff.make_post(author.user, to=[here])

    async def scenario(hub):
        feed, bell = await _open(hub, mover, ids=[post.pk]), await _open_bell(hub, mover)
        await hub.do(_do, capture, lambda: _comment(author, post, "Первый"))
        before = await _drain(feed)
        assert any(f"feed-post-{post.pk}-comments" in frame for frame in before), "контроль: кадр до перевода"
        await _drain(bell)
        await hub.do(lambda: support.model("org.Membership").objects.filter(user=mover.user).update(unit=there))
        await hub.do(_do, capture, lambda: _comment(author, post, "Второй"))
        assert await _drain(feed) == [], "после перевода кадр записи узла пришёл"
        assert _badges(await _drain(bell)) == []

    ws_run(scenario)


def test_unit_newcomer_gets_next_broadcast_about_earlier_unit_post(django_capture_on_commit_callbacks):
    """FR-628: пришедший в узел позже публикации видит запись узла и получает следующую рассылку о ней (группы
    подразделений не используются, состав считается при каждой рассылке)."""
    author = _writer()
    unit = org.make_unit("Отдел приёма")
    old_member, newcomer = _plain("Старожил Узлов"), _plain("Новичок Узлов")
    org.make_member(old_member.user, unit)
    post = ff.make_post(author.user, to=[unit], published_at=timezone.now() - timedelta(days=3))

    spy, _ = _spied(django_capture_on_commit_callbacks, lambda: _like(author, post))
    assert _gid(old_member.user) in _feed_groups(spy) and _gid(newcomer.user) not in _feed_groups(spy)

    org.make_member(newcomer.user, unit)
    spy, _ = _spied(django_capture_on_commit_callbacks, lambda: _comment(author, post))
    assert _gid(newcomer.user) in _feed_groups(spy), "новичок узла не получил рассылку о прежней записи"
    assert any(m["post"] == post.pk and m["action"] == "comment" for m in spy.by_group[_gid(newcomer.user)])


def test_dismissed_and_blocked_employees_are_not_recipients(django_capture_on_commit_callbacks):
    """FR-628, FR-606: уволенные и заблокированные не получатели — ни у записи «Всем», ни у записи узла и человека."""
    author = _writer()
    unit = org.make_unit("Отдел смены")
    active = _plain("Действующий Узлов")
    blocked = support.make_employee(state="blocked", full_name="Блокированный Узлов")
    dismissed = support.make_employee(state="dismissed", full_name="Уволенный Узлов")
    for member in (active.user, blocked, dismissed):
        org.make_member(member, unit)
    person_blocked = support.make_employee(state="blocked", full_name="Блокированный Личный")
    person_dismissed = support.make_employee(state="dismissed", full_name="Уволенный Личный")
    unit_post = ff.make_post(author.user, to=[unit, person_blocked, person_dismissed])
    all_post = ff.make_post(author.user, to=["all"])

    for post in (unit_post, all_post):
        spy, _ = _spied(django_capture_on_commit_callbacks, lambda post=post: _like(author, post))
        groups = _feed_groups(spy)
        assert _gid(active.user) in groups and _gid(author.user) in groups
        for gone in (blocked, dismissed, person_blocked, person_dismissed):
            assert _gid(gone) not in groups, "недействующий сотрудник получил рассылку"
            assert _nid(gone) not in spy.by_group, "недействующему ушло число «Ленты»"


# --- удаление записи ------------------------------------------------------------------------------------------------

def test_post_delete_sends_oob_delete_frame_to_those_who_saw_post_before_delete(django_capture_on_commit_callbacks):
    """FR-627, FR-628: после удаления записи открытые страницы тех, кто её видел, получают
    `<div id="feed-post-<id>" hx-swap-oob="delete">`; не видевший ничего не получает."""
    capture = django_capture_on_commit_callbacks
    author, friend, outsider = _writer(), _plain("Друг Другов"), _plain("Посторонний Лиц")
    post = ff.make_post(author.user, to=[friend.user])

    async def scenario(hub):
        seeing = await _open(hub, friend, ids=[post.pk])
        unrelated = await _open(hub, outsider, ids=[post.pk])
        response = await hub.do(_do, capture, lambda: author.client.post(f"/feed/{post.pk}/delete/", **HX))
        assert response.status_code == 200
        frames = await _drain(seeing)
        gone = [ws_fragments(frame).get(f"feed-post-{post.pk}") for frame in frames]
        gone = [fragment for fragment in gone if fragment is not None]
        assert gone and gone[0].attrs.get("hx-swap-oob") == "delete", "кадра удаления у видевшего нет"
        assert await _drain(unrelated) == [], "не видевший запись получил кадр"

    ws_run(scenario)
    assert not support.model("feed.Post").objects.filter(pk=post.pk).exists()


def test_post_delete_frame_reaches_personal_addressee_although_cascade_removes_addressees(
        django_capture_on_commit_callbacks):
    """FR-628: запись адресована одному человеку; каскад удаления стирает строки адресатов, но кадр удаления ему
    доходит: получатели сняты до удаления и несутся в `on_commit` готовым множеством."""
    capture = django_capture_on_commit_callbacks
    author, addressee = _writer(), _plain("Адресат Единственный")
    post = ff.make_post(author.user, to=[addressee.user])

    async def scenario(hub):
        conn = await _open(hub, addressee, ids=[post.pk])
        await hub.do(_do, capture, lambda: author.client.post(f"/feed/{post.pk}/delete/", **HX))
        frames = await _drain(conn)
        gone = [ws_fragments(frame).get(f"feed-post-{post.pk}") for frame in frames]
        assert any(fragment is not None and fragment.attrs.get("hx-swap-oob") == "delete" for fragment in gone), \
            "адресат не получил кадр удаления"

    ws_run(scenario)
    assert not support.model("feed.Recipient").objects.filter(post_id=post.pk).exists()


def test_post_delete_sends_new_feed_count_to_same_viewers(django_capture_on_commit_callbacks):
    """FR-628, FR-627, FR-626: после удаления непрочитанной записи новое число «Ленты» идёт тем же видевшим
    (у адресата 1 → 0), не видевшему — ничего."""
    capture = django_capture_on_commit_callbacks
    author, viewer, outsider = _writer(), _plain("Видевший Узлов"), _plain("Посторонний Лиц")
    post = ff.make_post(author.user, to=[viewer.user])

    async def scenario(hub):
        viewer_bell, outsider_bell = await _open_bell(hub, viewer), await _open_bell(hub, outsider)
        await hub.do(_do, capture, lambda: author.client.post(f"/feed/{post.pk}/delete/", **HX))
        badges = _badges(await _drain(viewer_bell))
        assert badges, "число «Ленты» видевшему не пришло"
        assert badges[-1].attrs["data-count"] == "0"
        assert badges[-1].attrs["hx-swap-oob"] == "true"
        assert _badges(await _drain(outsider_bell)) == [], "не видевший получил число"

    ws_run(scenario)


# --- действия и их `action` -----------------------------------------------------------------------------------------

def test_post_edit_frame_has_action_post_and_reaches_page_with_post_in_ids(django_capture_on_commit_callbacks):
    """FR-627: правка записи — сообщение с `action="post"`; кадр с частью `feed-post-<id>-body` получает только страница,
    у которой номер записи в `ids`."""
    capture = django_capture_on_commit_callbacks
    author, first, second = _writer(), _plain("Первый Читатель"), _plain("Второй Читатель")
    post = ff.make_post(author.user, to=[first.user, second.user])

    async def scenario(hub):
        with_post = await _open(hub, first, ids=[post.pk])
        without_post = await _open(hub, second, ids=[])
        response = await hub.do(_do, capture, lambda: _edit(author, post, [first.user, second.user]))
        assert response.status_code == 200
        frames = await _drain(with_post)
        parts = [ws_fragments(frame).get(f"feed-post-{post.pk}-body") for frame in frames]
        assert any(part is not None and part.attrs.get("hx-swap-oob") == "true" for part in parts)
        assert await _drain(without_post) == [], "страница без записи в `ids` получила кадр"

    with ff.layer_spy(passthrough=True) as spy:
        ws_run(scenario)
    assert [m["action"] for m in _events(spy) if m["post"] == post.pk] == ["post"]


def test_new_comment_frame_has_action_comment_and_reaches_page_with_post_in_ids(django_capture_on_commit_callbacks):
    """FR-627: новый комментарий — `action="comment"` с номером комментария; кадр `beforeend:#feed-post-<id>-comments`
    с `id="c<cid>"` получает страница с записью в `ids`, другая — нет."""
    capture = django_capture_on_commit_callbacks
    author, commenter, watcher, away = _writer(), _plain("Комментатор Ку"), _plain("Зритель Узлов"), _plain("Мимо Узлов")
    post = ff.make_post(author.user, to=[commenter.user, watcher.user, away.user])

    async def scenario(hub):
        on_page = await _open(hub, watcher, ids=[post.pk])
        off_page = await _open(hub, away, ids=[])
        response = await hub.do(_do, capture, lambda: _comment(commenter, post, "Живой комментарий"))
        assert response.status_code == 200
        cid = (await hub.do(_comment_row, post)).pk
        frames = await _drain(on_page)
        joined = "".join(frames)
        assert f'hx-swap-oob="beforeend:#feed-post-{post.pk}-comments"' in joined
        assert f'id="c{cid}"' in joined
        assert await _drain(off_page) == []
        return cid

    with ff.layer_spy(passthrough=True) as spy:
        cid = ws_run(scenario)
    messages = [m for m in _events(spy) if m["post"] == post.pk]
    assert [(m["action"], m["comment"]) for m in messages] == [("comment", cid)]


def test_comment_edit_and_comment_delete_frames_have_comment_edit_and_comment_delete_actions(
        django_capture_on_commit_callbacks):
    """FR-627: правка комментария — `action="comment_edit"`, кадр `#c<cid>` с `hx-swap-oob="outerHTML"`; удаление —
    `action="comment_delete"`, кадр `#c<cid>` с `hx-swap-oob="delete"`; в обоих — номер комментария."""
    capture = django_capture_on_commit_callbacks
    author, commenter, watcher = _writer(), _plain("Комментатор Ку"), _plain("Зритель Узлов")
    post = ff.make_post(author.user, to=[commenter.user, watcher.user])
    row = ff.comment(post, commenter.user, "Исходный текст")

    async def scenario(hub):
        conn = await _open(hub, watcher, ids=[post.pk])
        edited = await hub.do(_do, capture, lambda: commenter.client.post(
            f"/feed/comments/{row.pk}/edit/", {"text": "Исправленный текст"}, **HX))
        assert edited.status_code == 200
        fragment = [ws_fragments(f).get(f"c{row.pk}") for f in await _drain(conn)]
        fragment = [item for item in fragment if item is not None]
        assert fragment and fragment[0].attrs.get("hx-swap-oob") == "outerHTML"
        deleted = await hub.do(_do, capture, lambda: commenter.client.post(
            f"/feed/comments/{row.pk}/delete/", **HX))
        assert deleted.status_code == 200
        fragment = [ws_fragments(f).get(f"c{row.pk}") for f in await _drain(conn)]
        fragment = [item for item in fragment if item is not None]
        assert fragment and fragment[0].attrs.get("hx-swap-oob") == "delete"

    with ff.layer_spy(passthrough=True) as spy:
        ws_run(scenario)
    messages = [m for m in _events(spy) if m["post"] == post.pk]
    assert [(m["action"], m["comment"]) for m in messages] == [("comment_edit", row.pk), ("comment_delete", row.pk)]


def test_post_like_and_comment_like_frames_have_like_and_comment_like_actions(django_capture_on_commit_callbacks):
    """FR-627: «Нравится» записи — `action="like"` (комментария нет), кадр с частью `feed-post-<id>-likers`;
    «Нравится» комментария — `action="comment_like"` с номером комментария, страница с записью получает кадр."""
    capture = django_capture_on_commit_callbacks
    author, fan, watcher = _writer(), _plain("Болельщик Ку"), _plain("Зритель Узлов")
    post = ff.make_post(author.user, to=[fan.user, watcher.user])
    row = ff.comment(post, author.user, "Комментарий автора")

    async def scenario(hub):
        conn = await _open(hub, watcher, ids=[post.pk])
        liked = await hub.do(_do, capture, lambda: _like(fan, post))
        assert liked.status_code == 200
        parts = [ws_fragments(f).get(f"feed-post-{post.pk}-likers") for f in await _drain(conn)]
        assert any(part is not None and part.attrs.get("hx-swap-oob") == "true" for part in parts)
        comment_liked = await hub.do(_do, capture, lambda: fan.client.post(f"/feed/comments/{row.pk}/like/", **HX))
        assert comment_liked.status_code == 200
        assert await _drain(conn), "кадра об отметке комментария нет"

    with ff.layer_spy(passthrough=True) as spy:
        ws_run(scenario)
    messages = [m for m in _events(spy) if m["post"] == post.pk]
    assert [(m["action"], m["comment"]) for m in messages] == [("like", None), ("comment_like", row.pk)]


def test_read_and_event_answer_frames_have_read_and_answer_actions(django_capture_on_commit_callbacks):
    """FR-627: «Прочитано» — `action="read"` (кадр с частью `-imp`), ответ на событие — `action="answer"` (кадр с
    частью `-event`); владелец — автор записи."""
    capture = django_capture_on_commit_callbacks
    author, reader, watcher = _writer(), _plain("Читающий Ку"), _plain("Зритель Узлов")
    important = ff.make_important(author.user, to=[reader.user, watcher.user])
    event = ff.make_event(author.user, start=timezone.now() + timedelta(days=3), to=[reader.user, watcher.user])

    async def scenario(hub):
        conn = await _open(hub, watcher, ids=[important.pk, event.pk])
        read = await hub.do(_do, capture, lambda: reader.client.post(f"/feed/{important.pk}/read/", **HX))
        assert read.status_code == 200
        frames = await _drain(conn)
        assert any(ws_fragments(f).get(f"feed-post-{important.pk}-imp") is not None for f in frames)
        answered = await hub.do(_do, capture, lambda: reader.client.post(
            f"/feed/{event.pk}/answer/", {"answer": "go"}, **HX))
        assert answered.status_code == 200
        frames = await _drain(conn)
        assert any(ws_fragments(f).get(f"feed-post-{event.pk}-event") is not None for f in frames)

    with ff.layer_spy(passthrough=True) as spy:
        ws_run(scenario)
    actions = [(m["post"], m["action"], m["owner"]) for m in _events(spy)]
    assert actions == [(important.pk, "read", author.user.pk), (event.pk, "answer", author.user.pk)]


# --- слой `publish` и карточка --------------------------------------------------------------------------------------

def test_broadcast_goes_through_publish_layer_one_message_per_recipient_group(django_capture_on_commit_callbacks):
    """FR-627: рассылка идёт через слой `publish` (фабрика зовётся с `"publish"`), в каждую личную группу `feed.u.<id>` —
    ровно одно сообщение `feed.event`, в группы колокольчика — по одному `notify.html`."""
    author = _writer()
    people = [_plain(f"Получатель Номер{i}") for i in range(5)]
    spy, response = _spied(django_capture_on_commit_callbacks,
                           lambda: _publish(author, *[person.user for person in people]))
    assert response.status_code == 200
    assert spy.aliases and set(spy.aliases) == {"publish"}, "слой должен быть `publish`"
    expected = {_gid(person.user) for person in people} | {_gid(author.user)}
    assert _feed_groups(spy) == expected
    for group in expected:
        kinds = [message["type"] for message in spy.by_group[group]]
        assert kinds == ["feed.event"], f"группа {group}: {kinds}"
    for person in people:
        counts = [m for m in spy.by_group.get(_nid(person.user), []) if m.get("type") == "notify.html"]
        assert len(counts) == 1, "число «Ленты» — одно сообщение `notify.html` на группу"


def test_post_card_socket_gets_frames_about_its_post(django_capture_on_commit_callbacks):
    """FR-627: соединение карточки (`?post=<id>`) получает кадры о своей записи (без сообщения `sync`) и не получает
    кадры о других записях."""
    capture = django_capture_on_commit_callbacks
    author, viewer = _writer(), _plain("Зритель Карточки")
    post = ff.make_post(author.user, to=[viewer.user])
    other = ff.make_post(author.user, to=[viewer.user])

    async def scenario(hub):
        conn = await ff.ws_client(viewer, f"post={post.pk}", hub=hub)
        assert conn.accepted
        await _drain(conn, 0.3)
        await hub.do(_do, capture, lambda: _comment(author, other, "О другой записи"))
        assert await _drain(conn) == [], "кадр о чужой для карточки записи пришёл"
        await hub.do(_do, capture, lambda: _comment(author, post, "О своей записи"))
        frames = await _drain(conn)
        assert any(f"beforeend:#feed-post-{post.pk}-comments" in frame for frame in frames)

    ws_run(scenario)


def test_socket_on_page_without_feed_gets_no_feed_frames(django_capture_on_commit_callbacks):
    """FR-627: страница без ленты держит только соединение колокольчика: на ней нет ни плашки, ни частей записи;
    число «Ленты» приходит (оно на любой странице). Контроль: страница с лентой кадры получает."""
    capture = django_capture_on_commit_callbacks
    author, bell_only, with_feed = _writer(), _plain("Без Ленты"), _plain("С Лентой")

    async def scenario(hub):
        bell = await _open_bell(hub, bell_only)
        feed = await _open(hub, with_feed)
        response = await hub.do(_do, capture, lambda: _publish(author, bell_only.user, with_feed.user))
        assert response.status_code == 200
        assert _banners(await _drain(feed)), "контроль: страница с лентой плашки не получила"
        frames = await _drain(bell)
        assert _badges(frames), "число «Ленты» на странице без ленты не пришло"
        joined = "".join(frames)
        assert not re.search(r'id="feed-(new|synced|post-\d+)', joined), "на странице без ленты пришёл кадр ленты"

    ws_run(scenario)
