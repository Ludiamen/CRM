"""T-7119: комментарии ленты (FR-623, FR-624, FR-627, FR-633, FR-642).

План: «Комментарии», «Модель данных» (`FeedComment`), «Контракты» (`/feed/<id>/comments/`, `/feed/comments/<cid>/…`),
«Тексты отказов»; CONTRACT-007: 2.1, 2.2, 5.4, 5.8, 10.2, 11.1, 12.3, 13.1. Комментарии базы знаний не меняются
(SPEC-007, сценарий 4 п. 6). Код среза на уровне модуля не импортируется: имена берутся внутри тестов или через
`support.model`. Тексты отказов — литералы контракта (решение 19 задач).
"""
import importlib
import itertools
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support
from tests import support_feed as fd
from tests import support_kb as kb
from tests.support import HX

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
EMPTY = "Напишите текст"
LIMIT_4000 = "Предел: 4000 знаков"
FILES_LIMIT = "У комментария уже 3 файла"


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

_names = itertools.count(1)


def _Comment():
    return support.model("core.Comment")


def _FeedComment():
    return support.model("feed.FeedComment")


def _FeedFile():
    return support.model("feed.FeedFile")


def _post(author=None, *, to=("all",), **extra):
    return fd.make_post(author or support.make_employee(), to=to, **extra)


def _url(post) -> str:
    return f"/feed/{post.pk}/comments/"


def _add(session, post, text, *, nh=True, **fields):
    return session.client.post(_url(post), {"text": text, **fields}, **(HX if nh else {}))


def _ids(scope) -> list[int]:
    """Номера комментариев в порядке разметки (`data-comment-id`)."""
    return [int(node.attrs["data-comment-id"]) for node in q(scope, data_comment_id=True)]


def _card(session, post) -> Node:
    response = session.client.get(f"/feed/{post.pk}/")
    assert response.status_code == 200, f"/feed/{post.pk}/: {response.status_code}"
    return tree(response)


def _comments_of(post):
    return list(_Comment().objects.filter(object_ref=f"feed.post:{post.pk}").order_by("created_at", "id"))


def _eight(post, author, *, start=None):
    start = start or datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    return [fd.comment(post, author, f"комментарий {i}", created_at=start + timedelta(minutes=i)) for i in range(1, 9)]


def _error(scope, code):
    """Элемент отказа с кодом `code` (`[data-error][data-code]`)."""
    return [node for node in q(scope, data_error=True, data_code=code)]


# --- добавление (FR-623, FR-624) ------------------------------------------------------------------------

def test_viewer_adds_comment_core_comment_and_feed_comment_with_lowercase_object_ref():
    """FR-623, FR-624: комментарий — строка `core.Comment` с `object_ref` `feed.post:<id>` строчными и строка `FeedComment`."""
    post = _post()
    viewer = fd.as_plain(full_name="Комментатор Первый")
    response = _add(viewer, post, "  Первый комментарий к записи  ")
    assert response.status_code == 200
    (created,) = _Comment().objects.filter(author=viewer.user)
    assert created.object_ref == f"feed.post:{post.pk}" and created.object_ref == created.object_ref.lower()
    assert created.text == "Первый комментарий к записи", "края обрезаны ядром"
    (extra,) = _FeedComment().objects.all()
    assert extra.pk == created.pk and extra.comment_id == created.pk and extra.post_id == post.pk
    assert _FeedComment().objects.filter(post=post).count() == 1
    ordinary = _add(viewer, post, "Второй, без HTMX", nh=False)
    assert ordinary.status_code == 302
    second = _Comment().objects.filter(author=viewer.user).order_by("id").last()
    assert ordinary["Location"] == f"/feed/{post.pk}/#c{second.pk}"


def test_comment_response_appends_comment_at_bottom_with_author_and_time_and_clears_field(clock):
    """FR-623: ответ HTMX — фрагмент с новым комментарием (автор, время) и очищенным полем; на карточке он внизу."""
    clock.set(fd.moscow(2026, 3, 10, 14, 5))
    post = _post()
    older = fd.comment(post, post.author, "уже был", created_at=clock._now - timedelta(hours=1))
    writer = fd.as_plain(full_name="Новый Комментатор")
    response = _add(writer, post, "добавлен без перезагрузки")
    assert response.status_code == 200
    assert "<html" not in html_of(response).lower()
    fragment = tree(response)
    created = _Comment().objects.exclude(pk=older.pk).get()
    row = q1(fragment, id=f"c{created.pk}")
    assert row.attrs["data-comment-id"] == str(created.pk)
    assert "добавлен без перезагрузки" in row.text() and "Новый Комментатор" in row.text()
    stamp = q1(row, "time", data_at=True)
    assert stamp.text() == fd.moscow_text(fd.moscow(2026, 3, 10, 14, 5))
    assert datetime.fromisoformat(stamp.attrs["datetime"]) == fd.moscow(2026, 3, 10, 14, 5)
    field = q1(fragment, "textarea", name="text")
    assert field.raw_text().strip() == "", "поле очищено"
    assert q(fragment, data_error=True) == []
    assert _ids(_card(writer, post)) == [older.pk, created.pk], "новый — внизу"


def test_non_viewer_add_or_list_comments_returns_404():
    """FR-623: не видящему запись `GET` и `POST` `/feed/<id>/comments/` — 404 «Не найдено», как у несуществующей; комментария нет."""
    hidden = _post(to=(support.make_employee(),))
    outsider = fd.as_plain()
    missing = hidden.pk + 1000
    got = outsider.client.get(_url(hidden))
    assert got.status_code == 404
    assert support.same_failure(got, outsider.client.get(f"/feed/{missing}/comments/"))
    posted = outsider.client.post(_url(hidden), {"text": "чужой комментарий"}, **HX)
    assert posted.status_code == 404
    assert support.same_failure(posted, outsider.client.post(f"/feed/{missing}/comments/", {"text": "чужой комментарий"}, **HX))
    assert _Comment().objects.count() == 0 and _FeedComment().objects.count() == 0


# --- отказы (FR-623, FR-633, FR-642) ---------------------------------------------------------------------

def test_empty_comment_refused_with_write_text_reason():
    """FR-623, FR-642: пустой или из пробелов комментарий — 200, причина «Напишите текст» у поля `text`, записей нет."""
    post = _post()
    viewer = fd.as_plain()
    for nh in (True, False):
        for blank in ("", "   \n\t "):
            response = _add(viewer, post, blank, nh=nh)
            assert response.status_code == 200
            (reason,) = _error(tree(response), "empty_text")
            assert reason.attrs["data-error"] == "text" and EMPTY in reason.text()
    assert _Comment().objects.count() == 0 and _FeedComment().objects.count() == 0


def test_comment_4000_chars_accepted_4001_refused_with_limit_reason():
    """FR-623, FR-642: 4000 знаков принимаются; 4001 — 200 с причиной «Предел: 4000 знаков» у поля `text`, записи нет."""
    post = _post()
    viewer = fd.as_plain()
    accepted = _add(viewer, post, "я" * 4000)
    assert accepted.status_code == 200 and q(tree(accepted), data_error=True) == []
    assert [len(c.text) for c in _Comment().objects.filter(author=viewer.user)] == [4000]
    refused = _add(viewer, post, "я" * 4001)
    assert refused.status_code == 200
    (reason,) = _error(tree(refused), "too_long")
    assert reason.attrs["data-error"] == "text" and LIMIT_4000 in reason.text()
    assert _Comment().objects.filter(author=viewer.user).count() == 1
    assert _FeedComment().objects.count() == 1


def test_comment_three_files_accepted_fourth_refused_with_reason():
    """FR-633, FR-642: три файла прикрепляются к комментарию; четвёртый — отказ «У комментария уже 3 файла», ничего не сохранено."""
    post = _post()
    viewer = fd.as_plain()
    three = [fd.attach(None, f"файл{i}.txt", uploaded_by=viewer.user) for i in range(3)]
    accepted = _add(viewer, post, "с тремя файлами", files=[f.pk for f in three])
    assert accepted.status_code == 200 and q(tree(accepted), data_error=True) == []
    (created,) = _Comment().objects.filter(author=viewer.user)
    assert sorted(_FeedFile().objects.filter(comment=created).values_list("pk", flat=True)) == sorted(f.pk for f in three)
    assert {f.post_id for f in _FeedFile().objects.filter(comment=created)} == {post.pk}, "файл комментария знает запись"
    four = [fd.attach(None, f"новый{i}.txt", uploaded_by=viewer.user) for i in range(4)]
    refused = _add(viewer, post, "с четырьмя файлами", files=[f.pk for f in four])
    assert refused.status_code == 200
    (reason,) = _error(tree(refused), "comment_files_limit")
    assert reason.attrs["data-error"] in ("files", "file") and FILES_LIMIT in reason.text()
    assert _Comment().objects.filter(author=viewer.user).count() == 1, "отказ — ничего не сохранено"
    assert _FeedFile().objects.filter(pk__in=[f.pk for f in four], comment__isnull=True, post__isnull=True).count() == 4


def test_comment_htmx_refusal_returns_200_fragment_with_reason_and_entered_text():
    """FR-642: отказ на запрос HTMX — 200, фрагмент без `<html>` с причиной у поля и введённым текстом."""
    post = _post()
    viewer = fd.as_plain()
    entered = "ы" * 4001
    response = _add(viewer, post, entered)
    assert response.status_code == 200
    assert "<html" not in html_of(response).lower()
    fragment = tree(response)
    (reason,) = _error(fragment, "too_long")
    assert reason.attrs["data-error"] == "text"
    assert q1(fragment, "textarea", name="text").raw_text().strip() == entered, "введённое остаётся"
    assert q(fragment, data_comment_id=True) == [], "нового комментария во фрагменте нет"
    assert _Comment().objects.count() == 0


# --- список (FR-623) ---------------------------------------------------------------------------------------

def test_comments_flat_list_ordered_by_created_at_then_id():
    """FR-623: список плоский, по `created_at`, затем по номеру; вложенных комментариев нет."""
    post = _post()
    author = support.make_employee()
    base = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    late = fd.comment(post, author, "позже всех", created_at=base + timedelta(hours=2))
    same_first = fd.comment(post, author, "в ту же минуту, раньше по номеру", created_at=base + timedelta(hours=1))
    same_second = fd.comment(post, author, "в ту же минуту, позже по номеру", created_at=base + timedelta(hours=1))
    earliest = fd.comment(post, author, "раньше всех, создан последним", created_at=base)
    viewer = fd.as_plain()
    page = _card(viewer, post)
    assert _ids(page) == [earliest.pk, same_first.pk, same_second.pk, late.pk]
    rows = q(page, data_comment_id=True)
    assert not any(a is not b and a.inside(b) for a in rows for b in rows), "список плоский"
    fragment = viewer.client.get(_url(post), **HX)
    assert fragment.status_code == 200
    assert _ids(tree(fragment)) == [earliest.pk, same_first.pk, same_second.pk, late.pk]


def test_feed_shows_last_three_comments_and_show_all_8():
    """FR-623: лента показывает последние три комментария и ссылку «Показать все 8» с `hx-get` на `/feed/<id>/comments/`."""
    post = _post()
    comments = _eight(post, post.author)
    viewer = fd.as_plain()
    response = viewer.client.get("/")
    assert response.status_code == 200
    card = q1(tree(response), "article", id=f"feed-post-{post.pk}")
    assert _ids(card) == [c.pk for c in comments[-3:]]
    link = q1(card, "a", data_feed_comments_all=True)
    assert "Показать все 8" in link.text() and link.attrs["hx-get"] == _url(post)
    assert "8" in q1(card, id=f"feed-post-{post.pk}-ccount").text()


def test_comments_fragment_returns_all_eight_in_order():
    """FR-623: `GET /feed/<id>/comments/` — фрагмент со всеми восемью комментариями по времени, без `<html>`."""
    post = _post()
    comments = _eight(post, post.author)
    viewer = fd.as_plain()
    response = viewer.client.get(_url(post), **HX)
    assert response.status_code == 200
    assert "<html" not in html_of(response).lower()
    assert _ids(tree(response)) == [c.pk for c in comments]


def test_post_card_shows_all_comments():
    """FR-623: карточка `/feed/<id>/` показывает все комментарии записи и не предлагает «Показать все»."""
    post = _post()
    comments = _eight(post, post.author)
    other = _post()
    fd.comment(other, other.author, "комментарий другой записи")
    page = _card(fd.as_plain(), post)
    assert q1(page, data_feed_page="card") is not None
    assert _ids(page) == [c.pk for c in comments]
    assert q(page, "a", data_feed_comments_all=True) == []


def test_comment_shows_author_photo_name_and_time(clock):
    """FR-623: у комментария — фото автора, ФИО и время по Москве (`time[data-at]`)."""
    from apps.core.services import files

    clock.set(fd.moscow(2026, 3, 10, 14, 5))
    post = _post()
    author = support.make_employee(full_name="Автор Фотографов")
    author.photo = support.model("core.StoredFile").objects.create(
        purpose="photo", owner=author, size=10, sha256="0" * 64, content_type="image/jpeg", status="clean")
    author.save()
    written = fd.comment(post, author, "с фото", created_at=fd.moscow(2026, 3, 10, 14, 5))
    page = _card(fd.as_plain(), post)
    row = q1(page, id=f"c{written.pk}")
    assert "Автор Фотографов" in row.text()
    assert files.photo_url(author, 96) in [img.attrs.get("src") for img in q(row, "img")]
    stamp = q1(row, "time", data_at=True)
    assert stamp.text() == fd.moscow_text(fd.moscow(2026, 3, 10, 14, 5))
    assert datetime.fromisoformat(stamp.attrs["datetime"]) == fd.moscow(2026, 3, 10, 14, 5)


def test_comment_author_name_is_link_only_for_staff_view_or_accounts_manage():
    """FR-623: ФИО автора комментария — ссылка на `/staff/<id>/` только при праве `staff.view` или `accounts.manage`."""
    post = _post()
    author = support.make_employee(full_name="Автор Ссылочный")
    written = fd.comment(post, author, "комментарий")
    href = f"/staff/{author.pk}/"
    plain = fd.as_plain()
    viewer_staff = fd.as_plain()
    kb.grant(viewer_staff.user, "staff.view")
    viewer_manage = fd.as_plain()
    kb.grant(viewer_manage.user, "accounts.manage")
    for session, expected in ((plain, False), (viewer_staff, True), (viewer_manage, True)):
        row = q1(_card(session, post), id=f"c{written.pk}")
        assert "Автор Ссылочный" in row.text()
        assert bool([a for a in q(row, "a") if a.attrs.get("href") == href]) is expected


def test_comment_menu_edit_delete_shown_by_right():
    """FR-623, FR-622: «Править» — только автору комментария; «Удалить» — автору и модератору, который видит запись; автору записи — нет."""
    post = _post(support.make_employee())
    writer = fd.as_plain()
    written = fd.comment(post, writer.user, "чужой для всех, кроме автора")
    moderator = fd.as_moderator()
    outsider = fd.as_plain()
    post_author = fd.Session(post.author, support.logged_in(post.author))
    expected = ((writer, True, True), (moderator, False, True), (post_author, False, False), (outsider, False, False))
    for session, can_edit, can_delete in expected:
        row = q1(_card(session, post), id=f"c{written.pk}")
        assert bool(q(row, "button", data_action="comment-edit")) is can_edit, f"править: {session.user.pk}"
        assert bool(q(row, "button", data_action="comment-delete")) is can_delete, f"удалить: {session.user.pk}"


def test_comment_has_escaped_reply_hook_with_author_id_and_name():
    """FR-623: «Ответить» — `button[data-action=reply]` с номером и ФИО автора; значения экранированы."""
    post = _post()
    author = support.make_employee(full_name='Пётр <b>Жирный</b> & "Кавычкин"')
    written = fd.comment(post, author, "комментарий для ответа")
    response = fd.as_plain().client.get(f"/feed/{post.pk}/")
    assert response.status_code == 200
    assert "<b>Жирный</b>" not in html_of(response), "ФИО не вставлено разметкой"
    row = q1(tree(response), id=f"c{written.pk}")
    hook = q1(row, "button", data_action="reply")
    assert hook.attrs["data-reply-id"] == str(author.pk)
    assert hook.attrs["data-reply-name"] == 'Пётр <b>Жирный</b> & "Кавычкин"'


# --- одна транзакция, кадры после фиксации (FR-623, FR-627) ------------------------------------------------

def test_comment_with_mentions_files_and_notifications_rolls_back_together_on_dispatch_error(monkeypatch):
    """FR-623: комментарий, упоминания, файлы и уведомления — одна транзакция; сбой `dispatch.create` откатывает всё."""
    comments = importlib.import_module("apps.feed.services.comments")
    post = _post()
    writer = support.make_employee()
    mentioned = support.make_employee(full_name="Упомянутый Сотрудник")
    attached = fd.attach(None, "схема.txt", uploaded_by=writer)

    def broken(kind_code, drafts):
        raise RuntimeError("сбой уведомлений (подмена теста)")

    monkeypatch.setattr("apps.notify.services.dispatch.create", broken)
    with pytest.raises(RuntimeError):
        comments.add(writer, post.pk, f"Привет, @[{mentioned.pk}]", files=[attached.pk])
    assert _Comment().objects.count() == 0 and _FeedComment().objects.count() == 0
    Recipient = support.model("feed.Recipient")
    assert Recipient.objects.filter(post=post, via="mention").count() == 0, "упоминание откатилось"
    attached.refresh_from_db()
    assert attached.post_id is None and attached.comment_id is None, "файл остался непривязанным"


def test_comment_live_frame_sent_only_after_commit(django_capture_on_commit_callbacks):
    """FR-623, FR-627: кадр `feed.event` с действием `comment` уходит в слой только после фиксации и несёт номер комментария."""
    comments = importlib.import_module("apps.feed.services.comments")
    post = _post()
    writer = support.make_employee()
    with fd.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            created = comments.add(writer, post.pk, "кадр после фиксации")
            assert spy.calls == [], "до фиксации в слой ничего не уходит"
        for callback in callbacks:
            callback()
    assert spy.aliases and set(spy.aliases) == {"publish"}
    sent = [(group, message) for group, message in spy.calls if message.get("type") == "feed.event"]
    assert sent, "после фиксации кадры ушли"
    assert f"feed.u.{post.author_id}" in {group for group, _ in sent}, "автор записи получил кадр"
    for _group, message in sent:
        assert message["post"] == post.pk and message["action"] == "comment" and message["comment"] == created.pk


# --- комментарии базы знаний не меняются (FR-624) -----------------------------------------------------------

def test_article_comment_edit_like_and_files_via_feed_urls_return_404():
    """FR-624: адреса ленты ищут комментарий только с `object_ref` `feed.post:`; комментарий статьи — 404 даже для его автора."""
    article = kb.make_published()
    author = fd.as_plain()
    written = kb.make_comment(article, author.user, "комментарий статьи")
    cid = written.pk
    missing = cid + 1000
    for session in (author, fd.as_plain()):
        assert session.client.get(f"/feed/comments/{cid}/edit/").status_code == 404
        assert session.client.post(f"/feed/comments/{cid}/edit/", {"text": "правка"}, **HX).status_code == 404
        assert session.client.post(f"/feed/comments/{cid}/delete/", **HX).status_code == 404
        assert session.client.post(f"/feed/comments/{cid}/like/", **HX).status_code == 404
        assert session.client.get(f"/feed/comments/{cid}/likes/").status_code == 404
        upload = SimpleUploadedFile("схема.txt", b"file body", content_type="text/plain")
        response = session.client.post("/feed/files/", {"file": upload, "scope": "comment", "comment": cid})
        assert response.status_code == 404
    assert support.same_failure(author.client.get(f"/feed/comments/{cid}/edit/"),
                                author.client.get(f"/feed/comments/{missing}/edit/"))
    written.refresh_from_db()
    assert written.text == "комментарий статьи"
    assert _Comment().objects.filter(pk=cid).exists()
    assert _FeedComment().objects.count() == 0 and _FeedFile().objects.count() == 0
    assert support.model("feed.CommentLike").objects.count() == 0


def test_core_comment_get_fields_unchanged():
    """FR-624: поля `core.Comment` прежние — `id`, `object_ref`, `author`, `text`, `created_at`; данные ленты — в своих таблицах."""
    Comment = _Comment()
    assert [f.name for f in Comment._meta.get_fields()] == ["id", "object_ref", "author", "text", "created_at"]
    assert [f.name for f in Comment._meta.concrete_fields] == ["id", "object_ref", "author", "text", "created_at"]
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
            [Comment._meta.db_table])
        columns = [row[0] for row in cursor.fetchall()]
    assert columns == ["id", "object_ref", "author_id", "text", "created_at"]
    assert _FeedComment()._meta.get_field("comment").remote_field.related_name == "+"


def test_article_comments_stay_without_edit_mentions_likes_and_files():
    """FR-624: под статьёй по-прежнему без правки, упоминаний, отметок и файлов; маркер `@[id]` в её комментарии — обычный текст."""
    article = kb.make_published()
    reader = fd.as_plain(full_name="Читатель Статьи")
    friend = support.make_employee(full_name="Упомянутый Читатель")
    other = fd.as_plain()
    written = kb.make_comment(article, other.user, "комментарий статьи")
    marker = f"привет @[{friend.pk}]"
    response = reader.client.post(f"/kb/{article.pk}/comments/", {"text": marker}, **HX)
    assert response.status_code == 200
    saved = _Comment().objects.get(author=reader.user)
    assert saved.object_ref == f"knowledge.article:{article.pk}" and saved.text == marker
    page = tree(reader.client.get(f"/kb/{article.pk}/"))
    assert q(page, "button", data_action="comment-edit") == []
    assert q(page, "button", data_action="reply") == []
    assert q(page, "button", data_feed_like=True) == []
    assert q(page, "input", type="file") == []
    assert q(page, "textarea", data_feed_picker=True) == []
    assert q(page, data_mention=True) == [], "маркер упоминанием не стал"
    assert _FeedComment().objects.count() == 0 and _FeedFile().objects.count() == 0
    assert support.model("feed.CommentLike").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0, "адресатов ленты статья не создаёт"
    assert not support.model("notify.Notification").objects.filter(kind__startswith="feed.").exists()
    assert _Comment().objects.get(pk=written.pk).text == "комментарий статьи"
