"""T-7118: удаление записи, правка и удаление комментария (FR-621, FR-622, FR-632, FR-639). План: «Правка и удаление»
(удаление записи, комментарий), «Журнал», «Контракты» (`/feed/<id>/delete/`, `/feed/comments/<cid>/edit/`,
`/feed/comments/<cid>/delete/`); CONTRACT-007: 5.3 (`posts.delete`), 5.4 (`comments.*`), 5.7, 5.8 (запись удалена между
проверкой и вставкой), 8.1 (журнал), 10.2, 12.3.

Запись удаляет автор или модератор, который её видит; чужой комментарий — автор комментария или такой модератор, автор
записи чужие комментарии не удаляет; в журнал пишется только удаление чужого модератором, без текста. Диск стирается
после фиксации (`django_capture_on_commit_callbacks`, решение 6 (г) задач); замок записи — по SQL; гонка «запись удалена
между проверкой и вставкой» — подмена `delete_post_between_check_and_insert` и `SET CONSTRAINTS ALL IMMEDIATE`
(решение 15 задач). Код среза на уровне модуля не импортируется.
"""
import datetime
import json
import pathlib
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.conf import settings as django_settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests.support import HX

pytestmark = pytest.mark.django_db

TEXT_NOT_FOUND = "Не найдено"
TEXT_FILES_LIMIT = "У комментария уже 3 файла"


# --- разбор разметки (помощник только этого файла) -----------------------------------------------------------------

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


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
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


def tree(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- помощники файла ------------------------------------------------------------------------------------------

def _m(label: str):
    return support.model(label)


def _world():
    """Автор с правом «Писать всем», два адресата, модератор-адресат, посторонний и запись для всех них."""
    author, viewer, other = fd.as_writer(), fd.as_plain(), fd.as_plain()
    moderator, outsider = fd.as_moderator(), fd.as_plain()
    post = fd.make_post(author.user, to=(viewer.user, other.user, moderator.user), text="Запись автора")
    return SimpleNamespace(author=author, viewer=viewer, other=other, moderator=moderator, outsider=outsider,
                           post=post)


def _delete(session, post, hx=False):
    return session.client.post(f"/feed/{post.pk}/delete/", **(HX if hx else {}))


def _comment_delete(session, comment, hx=False):
    return session.client.post(f"/feed/comments/{comment.pk}/delete/", **(HX if hx else {}))


def _comment_edit(session, comment, text, hx=False, **extra):
    data = {"text": text}
    data.update(extra)
    return session.client.post(f"/feed/comments/{comment.pk}/edit/", data, **(HX if hx else {}))


def _post_exists(post) -> bool:
    return _m("feed.Post").objects.filter(pk=post.pk).exists()


def _comment_exists(comment) -> bool:
    return (_m("core.Comment").objects.filter(pk=comment.pk).exists()
            or _m("feed.FeedComment").objects.filter(pk=comment.pk).exists())


def _events(prefix: str = "feed.") -> list:
    return list(_m("core.AuditEvent").objects.filter(action__startswith=prefix).order_by("id"))


def _disk_paths(feed_file) -> list:
    from apps.core.services import files

    paths = [files.attachment_path(feed_file.file)]
    if feed_file.thumb:
        paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / feed_file.thumb)
    return paths


def _in_dump(event, marker: str) -> bool:
    return marker in json.dumps([event.before, event.after], ensure_ascii=False)


# --- удаление записи -------------------------------------------------------------------------------------------

def test_author_deletes_own_post_with_comments_likes_reads_answers_shown_and_recipients():
    """FR-621: автор удаляет свою запись — вместе с комментариями, отметками, прочтениями, ответами, показами,
    файлами и адресатами; обычный ответ — 302 на `/`, ответ HTMX — 200 с `hx-swap-oob="delete"`."""
    w = _world()
    now = timezone.now()
    post = fd.make_event(w.author.user, start=now + datetime.timedelta(days=2),
                         to=(w.viewer.user, w.moderator.user), text="Событие автора")
    first = fd.comment(post, w.viewer.user)
    fd.comment(post, w.author.user)
    fd.like(post, w.viewer.user)
    fd.like(first, w.author.user)
    fd.attach(post)
    fd.attach(first)
    _m("feed.ReadMark").objects.create(post=post, user=w.viewer.user, read_at=now)
    _m("feed.EventAnswer").objects.create(post=post, user=w.viewer.user, answer="go", answered_at=now)
    _m("feed.Shown").objects.create(post=post, user=w.viewer.user, shown_at=now)
    ref = f"feed.post:{post.pk}"
    assert _m("core.Comment").objects.filter(object_ref=ref).count() == 2
    response = _delete(w.author, post)
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert not _post_exists(post)
    for label in ("Recipient", "PostLike", "CommentLike", "ReadMark", "EventAnswer", "Shown", "FeedFile",
                  "FeedComment"):
        assert _m(f"feed.{label}").objects.filter(post_id=post.pk).count() == 0, label
    assert not _m("core.Comment").objects.filter(object_ref=ref).exists()
    htmx_post = fd.make_post(w.author.user, to=(w.viewer.user,))
    answer = _delete(w.author, htmx_post, hx=True)
    assert answer.status_code == 200
    html = answer.content.decode("utf-8")
    assert f'id="feed-post-{htmx_post.pk}"' in html
    assert 'hx-swap-oob="delete"' in html
    assert not _post_exists(htmx_post)


def test_post_delete_removes_core_comments_via_delete_for_and_feed_comment_rows(monkeypatch):
    """FR-621: комментарии ядра убирает `comments.delete_for("feed.post:<id>")`; строки `FeedComment` уходят каскадом;
    комментарии других записей целы."""
    from apps.core.services import comments as core_comments

    w = _world()
    kept_post = fd.make_post(w.author.user, to=(w.viewer.user,))
    kept = fd.comment(kept_post, w.viewer.user)
    gone = [fd.comment(w.post, w.viewer.user), fd.comment(w.post, w.other.user)]
    calls, real = [], core_comments.delete_for

    def spy(object_ref):
        calls.append(object_ref)
        return real(object_ref)

    monkeypatch.setattr(core_comments, "delete_for", spy)
    assert _delete(w.author, w.post).status_code == 302
    assert calls == [f"feed.post:{w.post.pk}"]
    for item in gone:
        assert not _comment_exists(item)
    assert _comment_exists(kept)


def test_post_delete_removes_post_and_comment_likes():
    """FR-621: отметки «Нравится» записи и её комментариев удаляются; отметки другой записи остаются."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user)
    fd.like(w.post, w.other.user)
    fd.like(comment, w.author.user)
    kept_post = fd.make_post(w.author.user, to=(w.viewer.user,))
    kept_like = fd.like(kept_post, w.viewer.user)
    assert _delete(w.author, w.post).status_code == 302
    assert not _m("feed.PostLike").objects.filter(post_id=w.post.pk).exists()
    assert not _m("feed.CommentLike").objects.filter(post_id=w.post.pk).exists()
    assert not _m("feed.CommentLike").objects.filter(comment_id=comment.pk).exists()
    assert _m("feed.PostLike").objects.filter(pk=kept_like.pk).exists()


def test_post_delete_removes_post_and_comment_files_in_all_scan_states_with_stored_file_rows():
    """FR-621: файлы записи и комментариев в любом состоянии проверки (проверяется, чистый, карантин) удаляются
    вместе со строками `StoredFile`; файл другой записи остаётся."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user)
    attached = []
    for status in ("pending", "clean", "quarantine"):
        attached.append(fd.attach(w.post, name=f"запись-{status}.txt", status=status))
        attached.append(fd.attach(comment, name=f"комментарий-{status}.txt", status=status))
    stored_ids = [item.file_id for item in attached]
    feed_ids = [item.pk for item in attached]
    kept_post = fd.make_post(w.author.user, to=(w.viewer.user,))
    kept = fd.attach(kept_post)
    assert _delete(w.author, w.post).status_code == 302
    assert not _m("feed.FeedFile").objects.filter(pk__in=feed_ids).exists()
    assert not _m("core.StoredFile").objects.filter(pk__in=stored_ids).exists()
    assert _m("feed.FeedFile").objects.filter(pk=kept.pk).exists()
    assert _m("core.StoredFile").objects.filter(pk=kept.file_id).exists()


def test_post_delete_erases_files_and_thumbs_from_disk_only_after_commit(protected_root,
                                                                         django_capture_on_commit_callbacks):
    """FR-621: файлы и эскизы записи и комментариев стираются с диска только после фиксации транзакции."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user)
    items = [fd.attach(w.post, write=True, thumb=True), fd.attach(comment, name="письмо.txt", write=True)]
    paths = [path for item in items for path in _disk_paths(item)]
    assert len(paths) == 3
    assert all(path.exists() for path in paths)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert _delete(w.author, w.post).status_code == 302
    assert not _post_exists(w.post)
    assert callbacks
    assert all(path.exists() for path in paths), "до фиксации диск трогать нельзя"
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in paths)


def test_post_delete_missing_file_on_disk_is_not_error(protected_root, django_capture_on_commit_callbacks):
    """FR-621: файла (и эскиза) уже нет на диске — это не ошибка: запись удалена, ответ 302."""
    w = _world()
    item = fd.attach(w.post, write=False)
    _m("feed.FeedFile").objects.filter(pk=item.pk).update(thumb="attachments/thumbs/999999.jpg")
    assert not any(path.exists() for path in _disk_paths(_m("feed.FeedFile").objects.get(pk=item.pk)))
    with django_capture_on_commit_callbacks(execute=True):
        response = _delete(w.author, w.post)
    assert response.status_code == 302
    assert not _post_exists(w.post)
    assert not _m("feed.FeedFile").objects.filter(pk=item.pk).exists()


def test_post_delete_locks_post_row_with_select_for_update():
    """FR-621: удаление берёт строку записи под `SELECT … FOR UPDATE` (решение 6 задач)."""
    from apps.feed.services import posts

    w = _world()
    with fd.capture_sql() as sqls:
        posts.delete(w.author.user, w.post.pk)
    fd.assert_for_update(sqls, "feed_post")
    assert not _post_exists(w.post)


def test_deleted_post_link_returns_404_same_as_nonexistent():
    """FR-621: ссылка на удалённую запись — 404 «Не найдено», как у несуществующей: карточка, правка, комментарии."""
    w = _world()
    post_id = w.post.pk
    assert _delete(w.author, w.post).status_code == 302
    missing = post_id + 1000
    for session in (w.author, w.viewer, w.moderator):
        for path in ("/feed/{}/", "/feed/{}/edit/", "/feed/{}/comments/"):
            got = session.client.get(path.format(post_id))
            gone = session.client.get(path.format(missing))
            assert got.status_code == gone.status_code == 404, path
            assert TEXT_NOT_FOUND in got.content.decode("utf-8")
            assert TEXT_NOT_FOUND in gone.content.decode("utf-8")


def test_moderator_who_sees_post_deletes_others_post():
    """FR-621: модератор, который видит запись, удаляет чужую запись."""
    w = _world()
    assert w.moderator.client.get(f"/feed/{w.post.pk}/").status_code == 200
    response = _delete(w.moderator, w.post)
    assert response.status_code == 302
    assert not _post_exists(w.post)


def test_moderator_deleting_others_post_writes_post_deleted_audit_with_author_and_time_without_text():
    """FR-621, FR-639: удаление чужой записи модератором — `feed.post_deleted` (`feed.post`, номер записи); в «было» —
    только автор (ФИО) и время публикации; текста записи в журнале нет."""
    w = _world()
    marker = "Служебный-текст-записи-для-журнала"
    post = fd.make_post(w.author.user, to=(w.moderator.user,), text=marker, published_at=fd.moscow(2026, 3, 10, 14, 5))
    assert _delete(w.moderator, post).status_code == 302
    events = _events("feed.post_deleted")
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == w.moderator.user.pk
    assert (event.object_type, event.object_id) == ("feed.post", str(post.pk))
    assert event.before == {"author": w.author.user.full_name, "published_at": "10.03.2026 14:05"}
    assert event.after == {}
    assert not _in_dump(event, marker)


def test_author_deleting_own_post_writes_no_audit():
    """FR-639: автор удаляет свою запись — в журнал ничего не пишется, даже если автор — модератор."""
    w = _world()
    moderator = fd.as_moderator()
    own = fd.make_post(moderator.user, to=(w.viewer.user,))
    plain = fd.make_post(w.author.user, to=(w.viewer.user,))
    assert _delete(moderator, own).status_code == 302
    assert _delete(w.author, plain).status_code == 302
    assert _events("feed.") == []


def test_delete_others_visible_post_without_moderate_returns_403():
    """FR-621: адресат без права модерации видит запись, но удалить её не может — 403; запись цела."""
    w = _world()
    assert w.viewer.client.get(f"/feed/{w.post.pk}/").status_code == 200
    assert _delete(w.viewer, w.post).status_code == 403
    assert _delete(w.viewer, w.post, hx=True).status_code == 403
    assert _post_exists(w.post)
    assert _events("feed.") == []


def test_delete_invisible_post_returns_404():
    """FR-621 (решение 18 задач): удалить невидимую запись — 404 «Не найдено», как несуществующую; запись цела."""
    w = _world()
    missing = w.post.pk + 1000
    got = _delete(w.outsider, w.post)
    gone = w.outsider.client.post(f"/feed/{missing}/delete/")
    assert got.status_code == gone.status_code == 404
    assert TEXT_NOT_FOUND in got.content.decode("utf-8")
    assert _post_exists(w.post)


def test_moderator_not_recipient_gets_404_then_deletes_after_mention_in_comment():
    """FR-621: модератор, которому запись не адресована, получает 404; после упоминания в комментарии он её видит и
    удаляет."""
    w = _world()
    moderator = fd.as_moderator()
    assert _delete(moderator, w.post).status_code == 404
    assert _post_exists(w.post)
    fd.comment(w.post, w.viewer.user, "Нужен модератор", mentions=[moderator.user])
    assert moderator.client.get(f"/feed/{w.post.pk}/").status_code == 200
    assert _delete(moderator, w.post).status_code == 302
    assert not _post_exists(w.post)


def test_post_and_comment_delete_keep_notifications_and_their_link_returns_404():
    """FR-632: уведомления о записи и комментарии не удаляются вместе с ними, а их ссылка ведёт на 404."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch

    w = _world()
    comment = fd.comment(w.post, w.author.user, "Комментарий автора")
    ids = dispatch.create("feed.for_you", [Draft(w.viewer.user.pk, "Запись для вас", f"/feed/{w.post.pk}/",
                                                 f"feed.post:{w.post.pk}")])
    ids += dispatch.create("feed.comment", [Draft(w.viewer.user.pk, "Новый комментарий",
                                                  f"/feed/{w.post.pk}/#c{comment.pk}", f"feed.post:{w.post.pk}")])
    assert len(ids) == 2
    Notification = _m("notify.Notification")
    assert Notification.objects.filter(pk__in=ids).count() == 2
    assert _comment_delete(w.author, comment).status_code == 302
    assert Notification.objects.filter(pk__in=ids).count() == 2
    assert _delete(w.author, w.post).status_code == 302
    assert Notification.objects.filter(pk__in=ids).count() == 2
    assert w.viewer.client.get(f"/feed/{w.post.pk}/").status_code == 404


# --- правка комментария -----------------------------------------------------------------------------------------

def test_comment_author_edits_text_via_core_update_sets_edited_at_and_changed_mark_without_audit(monkeypatch, clock):
    """FR-622, FR-639: автор правит свой комментарий через `comments.update` ядра; `FeedComment.edited_at` ставится,
    карточка показывает «изменено»; в журнал правка не пишется."""
    from apps.core.services import comments as core_comments

    w = _world()
    comment = fd.comment(w.post, w.viewer.user, "Старый комментарий")
    calls, real = [], core_comments.update

    def spy(target, text):
        calls.append((target.pk, text))
        return real(target, text)

    monkeypatch.setattr(core_comments, "update", spy)
    clock.advance(minutes=3)
    response = _comment_edit(w.viewer, comment, "Новый комментарий")
    assert response.status_code == 302
    assert response["Location"] == f"/feed/{w.post.pk}/#c{comment.pk}"
    assert calls == [(comment.pk, "Новый комментарий")]
    assert _m("core.Comment").objects.get(pk=comment.pk).text == "Новый комментарий"
    assert _m("feed.FeedComment").objects.get(pk=comment.pk).edited_at == timezone.now()
    page = tree(w.viewer.client.get(f"/feed/{w.post.pk}/"))
    node = q(page, id=f"c{comment.pk}")
    assert len(node) == 1
    marks = q(node[0], data_feed_edited=True)
    assert marks and "изменено" in marks[0].text()
    assert _events("feed.") == []
    assert not _m("core.AuditEvent").objects.filter(action__icontains="comment").exists()


def test_comment_edit_new_mention_adds_post_recipient():
    """FR-622: упоминание, добавленное правкой комментария, делает человека адресатом записи."""
    w = _world()
    newcomer = fd.as_plain()
    comment = fd.comment(w.post, w.viewer.user, "Старый комментарий")
    assert newcomer.client.get(f"/feed/{w.post.pk}/").status_code == 404
    response = _comment_edit(w.viewer, comment, f"Новый комментарий для @[{newcomer.user.pk}]")
    assert response.status_code == 302
    assert _m("feed.Recipient").objects.filter(post=w.post, user=newcomer.user, via="mention").count() == 1
    assert newcomer.client.get(f"/feed/{w.post.pk}/").status_code == 200


def test_comment_edit_by_other_or_moderator_returns_403():
    """FR-622: чужой комментарий правит только его автор: другой адресат, модератор и автор записи получают 403 на GET
    и POST; комментарий цел."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user, "Мой комментарий")
    for session in (w.other, w.moderator, w.author):
        assert session.client.get(f"/feed/comments/{comment.pk}/edit/").status_code == 403
        assert _comment_edit(session, comment, "Чужая правка").status_code == 403
    assert _m("core.Comment").objects.get(pk=comment.pk).text == "Мой комментарий"
    assert _m("feed.FeedComment").objects.get(pk=comment.pk).edited_at is None


def test_comment_edit_or_delete_on_invisible_post_returns_404():
    """FR-622 (решение 18 задач): правка и удаление комментария невидимой записи — 404; комментарий цел."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user, "Мой комментарий")
    assert w.outsider.client.get(f"/feed/comments/{comment.pk}/edit/").status_code == 404
    assert _comment_edit(w.outsider, comment, "Чужая правка").status_code == 404
    assert _comment_delete(w.outsider, comment).status_code == 404
    assert _comment_exists(comment)
    assert _m("core.Comment").objects.get(pk=comment.pk).text == "Мой комментарий"


# --- удаление комментария ------------------------------------------------------------------------------------------

def test_comment_author_deletes_own_comment_without_audit():
    """FR-622, FR-639: автор удаляет свой комментарий (обычный ответ — 302 на запись, HTMX — 200 с
    `hx-swap-oob="delete"`); в журнал это не пишется."""
    w = _world()
    first = fd.comment(w.post, w.viewer.user, "Первый")
    second = fd.comment(w.post, w.viewer.user, "Второй")
    plain = _comment_delete(w.viewer, first)
    assert plain.status_code == 302
    assert plain["Location"] == f"/feed/{w.post.pk}/"
    answer = _comment_delete(w.viewer, second, hx=True)
    assert answer.status_code == 200
    html = answer.content.decode("utf-8")
    assert f'id="c{second.pk}"' in html
    assert 'hx-swap-oob="delete"' in html
    assert not _comment_exists(first)
    assert not _comment_exists(second)
    assert _events("feed.") == []


def test_moderator_who_sees_post_deletes_others_comment_with_comment_deleted_audit_without_text():
    """FR-622, FR-639: модератор, который видит запись, удаляет чужой комментарий; `feed.comment_deleted`
    (`feed.comment`, номер): автор, время комментария, номер записи; текста нет."""
    w = _world()
    marker = "Служебный-текст-комментария-для-журнала"
    comment = fd.comment(w.post, w.viewer.user, marker, created_at=fd.moscow(2026, 3, 10, 14, 5))
    assert _comment_delete(w.moderator, comment).status_code == 302
    assert not _comment_exists(comment)
    events = _events("feed.comment_deleted")
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == w.moderator.user.pk
    assert (event.object_type, event.object_id) == ("feed.comment", str(comment.pk))
    assert event.before == {"author": w.viewer.user.full_name, "created_at": "10.03.2026 14:05",
                            "post": w.post.pk}
    assert event.after == {}
    assert not _in_dump(event, marker)


def test_post_author_cannot_delete_others_comment_403():
    """FR-622: автор записи чужой комментарий не удаляет — 403; комментарий цел, журнал пуст."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user, "Чужой комментарий")
    assert _comment_delete(w.author, comment).status_code == 403
    assert _comment_delete(w.author, comment, hx=True).status_code == 403
    assert _comment_exists(comment)
    assert _events("feed.") == []


def test_comment_delete_removes_its_likes_files_and_stored_files_and_erases_disk_after_commit(
        protected_root, django_capture_on_commit_callbacks):
    """FR-622: удаление комментария убирает его отметки, файлы и строки `StoredFile`; диск стирается после фиксации;
    отметки и файлы записи остаются."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user, "Комментарий с файлами")
    like = fd.like(comment, w.other.user)
    item = fd.attach(comment, name="картинка.png", write=True, thumb=True)
    own_like = fd.like(w.post, w.other.user)
    own_file = fd.attach(w.post, write=True)
    paths = _disk_paths(item)
    own_paths = _disk_paths(own_file)
    assert all(path.exists() for path in paths + own_paths)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert _comment_delete(w.viewer, comment).status_code == 302
    assert not _m("feed.CommentLike").objects.filter(pk=like.pk).exists()
    assert not _m("feed.FeedFile").objects.filter(pk=item.pk).exists()
    assert not _m("core.StoredFile").objects.filter(pk=item.file_id).exists()
    assert all(path.exists() for path in paths), "до фиксации диск трогать нельзя"
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in paths)
    assert all(path.exists() for path in own_paths)
    assert _m("feed.PostLike").objects.filter(pk=own_like.pk).exists()
    assert _m("feed.FeedFile").objects.filter(pk=own_file.pk).exists()


def test_comment_delete_keeps_mentioned_people_as_post_recipients():
    """FR-622: адресаты, добавленные упоминанием в комментарии, остаются адресатами записи после его удаления."""
    w = _world()
    mentioned = fd.as_plain()
    comment = fd.comment(w.post, w.viewer.user, "Прошу посмотреть", mentions=[mentioned.user])
    assert _m("feed.Recipient").objects.filter(post=w.post, user=mentioned.user, via="mention").count() == 1
    assert _comment_delete(w.viewer, comment).status_code == 302
    assert not _comment_exists(comment)
    assert _m("feed.Recipient").objects.filter(post=w.post, user=mentioned.user, via="mention").count() == 1
    assert mentioned.client.get(f"/feed/{w.post.pk}/").status_code == 200


def test_comment_edit_adds_new_file_up_to_limit_3_and_removes_marked_file_with_stored_file_and_disk_after_commit(
        protected_root, django_capture_on_commit_callbacks):
    """FR-622: правка комментария добавляет файлы до предела 3 и убирает отмеченные (`remove`) вместе со `StoredFile`
    и файлом на диске после фиксации; четвёртый файл — отказ «У комментария уже 3 файла»."""
    w = _world()
    comment = fd.comment(w.post, w.viewer.user, "Комментарий")
    kept = fd.attach(comment, name="остаётся.txt", write=True)
    removed = fd.attach(comment, name="уходит.png", write=True, thumb=True)
    new = [fd.attach(None, name=f"новый-{number}.txt", uploaded_by=w.viewer.user) for number in range(2)]
    removed_paths = _disk_paths(removed)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = _comment_edit(w.viewer, comment, "Комментарий", files=[item.pk for item in new],
                                 remove=[removed.pk])
    assert response.status_code == 302
    bound = _m("feed.FeedFile").objects.filter(comment_id=comment.pk)
    assert sorted(bound.values_list("pk", flat=True)) == sorted([kept.pk] + [item.pk for item in new])
    assert all(item.post_id == w.post.pk for item in bound)
    assert not _m("feed.FeedFile").objects.filter(pk=removed.pk).exists()
    assert not _m("core.StoredFile").objects.filter(pk=removed.file_id).exists()
    assert all(path.exists() for path in removed_paths), "до фиксации диск трогать нельзя"
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in removed_paths)
    assert all(path.exists() for path in _disk_paths(kept))
    extra = fd.attach(None, name="лишний.txt", uploaded_by=w.viewer.user)
    refused = _comment_edit(w.viewer, comment, "Комментарий", files=[extra.pk])
    assert refused.status_code == 200
    errors = q(tree(refused), data_error="files", data_code="comment_files_limit")
    assert len(errors) == 1
    assert TEXT_FILES_LIMIT in errors[0].text()
    assert _m("feed.FeedFile").objects.filter(comment_id=comment.pk).count() == 3
    assert _m("feed.FeedFile").objects.get(pk=extra.pk).comment_id is None


def test_comment_on_post_deleted_between_check_and_insert_rolls_back_without_orphan_core_comment(monkeypatch):
    """FR-621, FR-622: запись удалена между проверкой и вставкой `FeedComment` — внешний ключ даёт ошибку, транзакция
    откатывается вместе с `core.Comment`, комментария-сироты нет (решение 15 задач; проверка — под
    `SET CONSTRAINTS ALL IMMEDIATE`)."""
    from apps.feed.services import comments

    w = _world()
    deleted = fd.delete_post_between_check_and_insert(monkeypatch)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            comments.add(w.viewer.user, w.post.pk, "Комментарий в удаляемую запись")
    assert deleted == [w.post.pk]
    assert not _post_exists(w.post)
    assert not _m("core.Comment").objects.filter(object_ref=f"feed.post:{w.post.pk}").exists()
    assert not _m("feed.FeedComment").objects.filter(post_id=w.post.pk).exists()
