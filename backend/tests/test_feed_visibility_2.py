"""T-7103: одна функция видимости во всех местах (FR-604, FR-606, FR-628, FR-630, FR-634, FR-635, FR-636).
CONTRACT-007, раздел 6 (места V1-V12), 10.1, 10.2; решение 18 задач.

Приём: запись, которую сотрудник не видит, неотличима от несуществующей (`support.same_failure` в пределах одного
клиента) и не попадает ни в ленту, ни в фильтры, ни в поиск, ни в рассылку, ни в число «Ленты». Контрольный сотрудник,
который запись видит, нужен, чтобы тест не прошёл от пустой страницы. Код среза на уровне модуля не импортируется.
"""
from datetime import timedelta, timezone as dt_timezone
from urllib.parse import urlencode

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as ff
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db

MISSING = 999999


@pytest.fixture(autouse=True)
def _storage(protected_root, monkeypatch):
    ff.scan_clean(monkeypatch)


def _employee(name: str, **extra):
    return support.make_employee(full_name=name, **extra)


def _session(user) -> ff.Session:
    return ff.Session(user, support.logged_in(user))


class World:
    """Автор, видящий адресат и посторонний, которому записи не адресованы."""

    def __init__(self, outsider_session=None):
        self.author = _employee("Автор Авторов")
        self.friend = _session(_employee("Друг Другов"))
        self.outsider = outsider_session or _session(_employee("Посторонний Лиц"))

    def post(self, kind="post", **extra):
        return ff.make_post(self.author, kind, to=[self.friend.user], **extra)


def _shows(session, path: str, post) -> bool:
    response = session.client.get(path)
    assert response.status_code == 200
    return ff.post_part(response.content.decode(), post.pk) is not None


def _assert_hidden_like_missing(session, hidden_path: str, missing_path: str, method: str = "get", data=None):
    send = getattr(session.client, method)
    hidden = send(hidden_path, data or {})
    missing = send(missing_path, data or {})
    assert hidden.status_code == 404
    assert support.same_failure(hidden, missing)


# --- V1-V4: лента, «Ещё записи», фильтры ------------------------------------------------------------------------------

def test_invisible_post_absent_from_first_feed_page():
    """FR-606: на первой странице ленты невидимой записи нет, видящему — есть."""
    world = World()
    post = world.post(text="Невидимый_текст_для_ленты")
    assert _shows(world.friend, "/", post)
    response = world.outsider.client.get("/")
    assert response.status_code == 200
    assert ff.post_part(response.content.decode(), post.pk) is None
    assert "Невидимый_текст_для_ленты" not in response.content.decode()


def test_invisible_post_absent_from_more_posts():
    """FR-606: «Ещё записи» (`/feed/more/`) не отдаёт невидимую запись."""
    world = World()
    post = world.post()
    before = (timezone.now() + timedelta(days=1)).astimezone(dt_timezone.utc).isoformat()
    path = "/feed/more/?" + urlencode({"before": f"{before},{10 ** 9}"})
    assert _shows(world.friend, path, post)
    response = world.outsider.client.get(path)
    assert response.status_code == 200
    assert ff.post_part(response.content.decode(), post.pk) is None


def test_invisible_post_absent_under_important_filter():
    """FR-606: фильтр «Важные» не показывает невидимую важную запись."""
    world = World()
    post = ff.make_important(world.author, to=[world.friend.user])
    assert _shows(world.friend, "/?f=important", post)
    assert not _shows(world.outsider, "/?f=important", post)


def test_invisible_post_absent_under_events_filter():
    """FR-606: фильтр «События» не показывает невидимое событие."""
    world = World()
    post = ff.make_event(world.author, start=timezone.now() + timedelta(days=2), to=[world.friend.user])
    assert _shows(world.friend, "/?f=events", post)
    assert not _shows(world.outsider, "/?f=events", post)


def test_mine_filter_excludes_post_of_other_author_where_i_am_addressee():
    """FR-635: «Мои» — только записи, где я автор; запись другого автора, адресованная мне, не входит."""
    world = World()
    foreign = world.post(text="Запись другого автора")
    mine = ff.make_post(world.friend.user, to=[world.author])
    assert _shows(world.friend, "/", foreign)
    assert _shows(world.friend, "/?f=mine", mine)
    assert not _shows(world.friend, "/?f=mine", foreign)


def test_mentions_filter_excludes_post_where_i_am_addressee_via_to_but_not_mentioned():
    """FR-635: «Упоминают меня» — только записи со строкой `mention`; адресация через «Кому» не считается."""
    world = World()
    addressed = world.post(text="Мне адресовано")
    mentioned = ff.make_post(world.author, to=[_employee("Другой Адресат")], mentions=[world.friend.user])
    assert _shows(world.friend, "/", addressed)
    assert _shows(world.friend, "/?f=mentions", mentioned)
    assert not _shows(world.friend, "/?f=mentions", addressed)


def test_invisible_post_absent_under_author_filter():
    """FR-606: фильтр «Автор» показывает только видимые записи этого автора."""
    world = World()
    hidden = world.post()
    visible = ff.make_post(world.author, to=[world.outsider.user])
    path = "/?" + urlencode({"author": world.author.pk})
    assert _shows(world.friend, path, hidden)
    assert _shows(world.outsider, path, visible)
    assert not _shows(world.outsider, path, hidden)


def test_invisible_post_absent_under_period_filter():
    """FR-606: фильтр периода «с» / «по» не показывает невидимую запись."""
    world = World()
    moment = ff.moscow(2026, 10, 28, 12)
    hidden = world.post(published_at=moment)
    visible = ff.make_post(world.author, to=[world.outsider.user], published_at=moment)
    path = "/?" + urlencode({"from": "2026-10-28", "to": "2026-10-28"})
    assert _shows(world.friend, path, hidden)
    assert _shows(world.outsider, path, visible)
    assert not _shows(world.outsider, path, hidden)


# --- V5: карточка -----------------------------------------------------------------------------------------------------

def test_invisible_post_card_returns_404_like_missing():
    """FR-604, FR-606: карточка невидимой записи — 404, как у несуществующей."""
    world = World()
    post = world.post()
    assert world.friend.client.get(f"/feed/{post.pk}/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/", f"/feed/{MISSING}/")


# --- V6: поиск -----------------------------------------------------------------------------------------------------------

def test_invisible_post_and_its_comments_absent_from_search_without_count():
    """FR-606, FR-636: запись и её комментарии не находятся поиском и не входят в число группы «Лента»."""
    from apps.core.extensions import ParsedQuery
    from apps.feed.services import search

    world = World()
    post = world.post(text="Квазар виден только друзьям")
    ff.comment(post, world.friend.user, "Квазар в комментарии")
    parsed = ParsedQuery(words=["квазар"], raw="квазар", text="квазар")

    assert len(search.search(world.friend.user, parsed, 20, 0)) == 2
    assert search.count(world.friend.user, parsed) == (2, False)
    assert search.search(world.outsider.user, parsed, 20, 0) == []
    assert search.count(world.outsider.user, parsed) == (0, False)


# --- V7: файлы ---------------------------------------------------------------------------------------------------------

def test_file_of_invisible_post_returns_404_like_missing_file():
    """FR-606, FR-634: файл невидимой записи — 404, как у несуществующего файла."""
    world = World()
    post = world.post()
    file = ff.attach(post, write=True)
    assert world.friend.client.get(f"/feed/files/{file.pk}/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/files/{file.pk}/", f"/feed/files/{MISSING}/")


def test_thumb_of_invisible_post_returns_404_like_missing_file():
    """FR-606, FR-634: эскиз файла невидимой записи — 404, как у несуществующего."""
    world = World()
    post = world.post()
    file = ff.attach(post, write=True, thumb=True)
    assert world.friend.client.get(f"/feed/files/{file.pk}/thumb/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/files/{file.pk}/thumb/", f"/feed/files/{MISSING}/thumb/")


# --- V8: списки ---------------------------------------------------------------------------------------------------------

def test_recipients_list_of_invisible_post_returns_404():
    """FR-606: список адресатов невидимой записи — 404, как у несуществующей."""
    world = World()
    post = world.post()
    assert world.friend.client.get(f"/feed/{post.pk}/to/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/to/", f"/feed/{MISSING}/to/")


def test_post_likers_list_of_invisible_post_returns_404():
    """FR-606: список отметивших запись — 404 тому, кто запись не видит."""
    world = World()
    post = world.post()
    ff.like(post, world.friend.user)
    assert world.friend.client.get(f"/feed/{post.pk}/likes/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/likes/", f"/feed/{MISSING}/likes/")


def test_comment_likers_list_of_invisible_post_returns_404():
    """FR-606: список отметивших комментарий невидимой записи — 404."""
    world = World()
    post = world.post()
    note = ff.comment(post, world.friend.user, "Комментарий")
    ff.like(note, world.author)
    assert world.friend.client.get(f"/feed/comments/{note.pk}/likes/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/comments/{note.pk}/likes/",
                                f"/feed/comments/{MISSING}/likes/")


def test_reads_list_of_invisible_post_returns_404():
    """FR-606: список прочитавших невидимой записи — 404 (автору он доступен)."""
    world = World()
    post = ff.make_important(world.author, to=[world.friend.user])
    assert _session(world.author).client.get(f"/feed/{post.pk}/reads/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/reads/", f"/feed/{MISSING}/reads/")


def test_answers_list_of_invisible_post_returns_404():
    """FR-606: список ответивших на невидимое событие — 404 (автору он доступен)."""
    world = World()
    post = ff.make_event(world.author, start=timezone.now() + timedelta(days=2), to=[world.friend.user])
    assert _session(world.author).client.get(f"/feed/{post.pk}/answers/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/answers/", f"/feed/{MISSING}/answers/")


def test_comments_list_of_invisible_post_returns_404():
    """FR-606: все комментарии невидимой записи — 404."""
    world = World()
    post = world.post()
    ff.comment(post, world.friend.user, "Комментарий")
    assert world.friend.client.get(f"/feed/{post.pk}/comments/").status_code == 200
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/comments/", f"/feed/{MISSING}/comments/")


# --- V9: уведомления ----------------------------------------------------------------------------------------------------

def test_still_relevant_false_for_transferred_out_recipient_so_mail_not_sent():
    """FR-606, FR-630: после перевода из подразделения адресат запись больше не видит — `still_relevant` ложно для
    записи и комментария, письмо и сводка не уходят."""
    from apps.feed.notify_kinds import still_relevant

    unit, other = org.make_unit("Отдел ИТ"), org.make_unit("Бухгалтерия")
    member = _employee("Переведённый Сотрудник")
    org.make_member(member, unit)
    author = _employee("Автор Авторов")
    post = ff.make_post(author, to=[unit])
    note = ff.comment(post, author, "Комментарий")
    assert still_relevant(member.pk, f"feed.post:{post.pk}") is True
    assert still_relevant(member.pk, f"feed.post:{post.pk}:c{note.pk}") is True

    support.model("org.Membership").objects.filter(user=member, unit=unit).delete()
    org.make_member(member, other)

    assert still_relevant(member.pk, f"feed.post:{post.pk}") is False
    assert still_relevant(member.pk, f"feed.post:{post.pk}:c{note.pk}") is False


# --- V10: рассылка и число «Ленты» -----------------------------------------------------------------------------------

def test_live_broadcast_sends_no_frame_about_invisible_post(django_capture_on_commit_callbacks):
    """FR-606, FR-628: рассылка о записи и комментарии идёт только в группы тех, кто запись видит."""
    from apps.feed.services import comments, posts

    world = World()
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True):
            post = posts.publish(world.author, {"text": "Запись для друга", "to": [f"p{world.friend.user.pk}"]})
        with django_capture_on_commit_callbacks(execute=True):
            comments.add(world.friend.user, post.pk, "Ответ друга")

    assert f"feed.u.{world.friend.user.pk}" in spy.by_group
    for user in (world.outsider.user,):
        assert f"feed.u.{user.pk}" not in spy.by_group
        assert f"notify.u.{user.pk}" not in spy.by_group


def test_feed_counter_does_not_grow_for_invisible_post(django_capture_on_commit_callbacks):
    """FR-606, FR-628: число «Ленты» посторонний не получает: `unread.count` не растёт, видящему — растёт."""
    from apps.feed.services import posts, unread

    world = World()
    friend_before = unread.count(world.friend.user)
    outsider_before = unread.count(world.outsider.user)
    with django_capture_on_commit_callbacks(execute=True):
        posts.publish(world.author, {"text": "Запись для друга", "to": [f"p{world.friend.user.pk}"]})
    assert unread.count(world.friend.user) == friend_before + 1
    assert unread.count(world.outsider.user) == outsider_before


# --- V11: действия ------------------------------------------------------------------------------------------------------

def test_read_answer_and_like_on_invisible_post_return_404():
    """FR-606: «Прочитано», ответ на событие и «Нравится» к невидимой записи — 404, как у несуществующей."""
    world = World()
    important = ff.make_important(world.author, to=[world.friend.user])
    event = ff.make_event(world.author, start=timezone.now() + timedelta(days=2), to=[world.friend.user])
    plain = world.post()
    _assert_hidden_like_missing(world.outsider, f"/feed/{important.pk}/read/", f"/feed/{MISSING}/read/", "post")
    _assert_hidden_like_missing(world.outsider, f"/feed/{event.pk}/answer/", f"/feed/{MISSING}/answer/", "post",
                                {"answer": "go"})
    _assert_hidden_like_missing(world.outsider, f"/feed/{plain.pk}/like/", f"/feed/{MISSING}/like/", "post")
    assert not support.model("feed.ReadMark").objects.filter(post=important).exists()
    assert not support.model("feed.EventAnswer").objects.filter(post=event).exists()
    assert not support.model("feed.PostLike").objects.filter(post=plain).exists()


def test_new_comment_edit_and_delete_on_invisible_post_return_404():
    """FR-606: новый комментарий, правка и удаление невидимой записи — 404 (даже модератору без адресации)."""
    world = World(outsider_session=ff.as_moderator())
    post = world.post()
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/comments/", f"/feed/{MISSING}/comments/", "post",
                                {"text": "Комментарий"})
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/edit/", f"/feed/{MISSING}/edit/", "post",
                                {"text": "Правка"})
    _assert_hidden_like_missing(world.outsider, f"/feed/{post.pk}/delete/", f"/feed/{MISSING}/delete/", "post")
    assert support.model("feed.Post").objects.filter(pk=post.pk, text="Текст записи").exists()
    assert not support.model("feed.FeedComment").objects.filter(post=post).exists()


def test_edit_delete_and_like_of_comment_on_invisible_post_return_404():
    """FR-606: правка, удаление и «Нравится» комментария невидимой записи — 404 (даже модератору без адресации)."""
    world = World(outsider_session=ff.as_moderator())
    post = world.post()
    note = ff.comment(post, world.friend.user, "Комментарий друга")
    _assert_hidden_like_missing(world.outsider, f"/feed/comments/{note.pk}/edit/",
                                f"/feed/comments/{MISSING}/edit/", "post", {"text": "Правка"})
    _assert_hidden_like_missing(world.outsider, f"/feed/comments/{note.pk}/delete/",
                                f"/feed/comments/{MISSING}/delete/", "post")
    _assert_hidden_like_missing(world.outsider, f"/feed/comments/{note.pk}/like/",
                                f"/feed/comments/{MISSING}/like/", "post")
    assert support.model("core.Comment").objects.filter(pk=note.pk, text="Комментарий друга").exists()
    assert not support.model("feed.CommentLike").objects.filter(comment=note).exists()


def test_invisible_post_response_same_code_page_and_not_found_text_as_missing():
    """FR-604, FR-606: ответ о невидимой записи — тот же код, та же обычная страница и тот же текст «Не найдено», что
    у несуществующей; ничто в ответе не выдаёт, что запись есть."""
    world = World()
    post = world.post(text="Невидимый_текст_для_ответа")
    hidden = world.outsider.client.get(f"/feed/{post.pk}/")
    missing = world.outsider.client.get(f"/feed/{MISSING}/")
    assert hidden.status_code == missing.status_code == 404
    assert "Не найдено" in hidden.content.decode()
    assert "Не найдено" in missing.content.decode()
    assert "Невидимый_текст_для_ответа" not in hidden.content.decode()
    assert support.same_failure(hidden, missing)
