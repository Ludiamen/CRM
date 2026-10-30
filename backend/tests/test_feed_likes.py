"""T-7120: «Нравится» (FR-625, FR-630).

План: «„Нравится“», «Контракты» (`/feed/<id>/like/`, `/feed/<id>/likes/`, `/feed/comments/<cid>/like/`,
`/feed/comments/<cid>/likes/`); CONTRACT-007: 2.2, 5.4, 5.8, 10.2, 12.3. Гонки — без потоков (решение 6 задач):
подмена `likes.find_mark` и последовательные вызовы. Код среза на уровне модуля не импортируется.
"""
import importlib
from html.parser import HTMLParser

import pytest
from django.db import IntegrityError, transaction

from tests import support
from tests import support_feed as fd
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

def _likes():
    return importlib.import_module("apps.feed.services.likes")


def _PostLike():
    return support.model("feed.PostLike")


def _CommentLike():
    return support.model("feed.CommentLike")


def _post(author=None, *, to=("all",), **extra):
    return fd.make_post(author or support.make_employee(), to=to, **extra)


def _press(session, target, *, nh=True):
    """Нажатие «Нравится»: `target` — запись или комментарий ядра."""
    if target._meta.label_lower == "feed.post":
        path = f"/feed/{target.pk}/like/"
    else:
        path = f"/feed/comments/{target.pk}/like/"
    return session.client.post(path, **(HX if nh else {}))


def _likers_path(target) -> str:
    if target._meta.label_lower == "feed.post":
        return f"/feed/{target.pk}/likes/"
    return f"/feed/comments/{target.pk}/likes/"


def _likers(count, post, target, clock):
    """`count` отметивших по порядку, каждый на минуту позже предыдущего; возвращает сотрудников."""
    people = []
    for number in range(1, count + 1):
        person = support.make_employee(full_name=f"Отметивший Номер{number}")
        fd.like(target, person)
        people.append(person)
        clock.advance(minutes=1)
    return people


def _line(scope) -> str:
    (node,) = q(scope, data_feed_likers=True)
    return node.text()


def _marks(target):
    if target._meta.label_lower == "feed.post":
        return _PostLike().objects.filter(post=target)
    return _CommentLike().objects.filter(comment=target)


def _notices(user):
    return list(support.model("notify.Notification").objects.filter(user=user, kind="feed.like"))


# --- переключатель (FR-625) -------------------------------------------------------------------------------

def test_post_like_first_press_sets_mark_second_removes():
    """FR-625: первое нажатие ставит отметку записи, второе снимает; обычный запрос — 302 на карточку."""
    post = _post()
    viewer = fd.as_plain()
    assert _press(viewer, post).status_code == 200
    (mark,) = _PostLike().objects.filter(post=post)
    assert mark.user_id == viewer.user.pk
    assert _press(viewer, post).status_code == 200
    assert _PostLike().objects.filter(post=post).count() == 0
    ordinary = _press(viewer, post, nh=False)
    assert ordinary.status_code == 302 and ordinary["Location"].startswith(f"/feed/{post.pk}/")
    assert _PostLike().objects.filter(post=post, user=viewer.user).count() == 1


def test_comment_like_first_press_sets_mark_second_removes():
    """FR-625: первое нажатие ставит отметку комментария (с номером записи), второе снимает."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    viewer = fd.as_plain()
    assert _press(viewer, written).status_code == 200
    (mark,) = _CommentLike().objects.filter(comment=written)
    assert mark.user_id == viewer.user.pk and mark.post_id == post.pk
    assert _press(viewer, written).status_code == 200
    assert _CommentLike().objects.filter(comment=written).count() == 0
    ordinary = _press(viewer, written, nh=False)
    assert ordinary.status_code == 302 and ordinary["Location"].startswith(f"/feed/{post.pk}/")
    assert _CommentLike().objects.filter(comment=written, user=viewer.user).count() == 1


def test_like_response_has_button_in_own_state_and_likers_line_with_own_name():
    """FR-625: ответ нажавшему — кнопка в своём состоянии (`aria-pressed`) и строка «Нравится: <его ФИО>»; после снятия — нет."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    viewer = fd.as_plain(full_name="Нажавший Лайкин")
    for target in (post, written):
        pressed = _press(viewer, target)
        assert pressed.status_code == 200
        assert "<html" not in html_of(pressed).lower()
        fragment = tree(pressed)
        assert q1(fragment, "button", data_feed_like=True).attrs["aria-pressed"] == "true"
        assert _line(fragment) == "Нравится: Нажавший Лайкин"
        released = tree(_press(viewer, target))
        assert q1(released, "button", data_feed_like=True).attrs["aria-pressed"] == "false"
        assert all("Нажавший Лайкин" not in node.text() for node in q(released, data_feed_likers=True))


# --- гонки: нарушение уникальности и повторное удаление (FR-625) ----------------------------------------

def test_two_post_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing(monkeypatch):
    """FR-625: два «создать» подряд оставляют одну отметку: нарушение уникальности перехвачено и считается «уже есть»."""
    post = _post()
    viewer = support.make_employee()
    calls = fd.mark_created_between_check_and_insert(monkeypatch)
    assert _likes().toggle_post(viewer, post.pk) is True
    assert _likes().toggle_post(viewer, post.pk) is True, "вторая вставка упёрлась в уникальность — отметка стоит"
    assert [kind for kind, _target, _user in calls] == ["post", "post"]
    assert _PostLike().objects.filter(post=post, user=viewer).count() == 1, "и транзакция жива"


def test_two_comment_like_creates_in_a_row_leave_one_mark_duplicate_caught_as_existing(monkeypatch):
    """FR-625: то же для комментария — одна отметка, второй вызов считает её «уже есть»."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    viewer = support.make_employee()
    calls = fd.mark_created_between_check_and_insert(monkeypatch)
    assert _likes().toggle_comment(viewer, written.pk) is True
    assert _likes().toggle_comment(viewer, written.pk) is True
    assert [(kind, target) for kind, target, _user in calls] == [("comment", written.pk)] * 2
    assert _CommentLike().objects.filter(comment=written, user=viewer).count() == 1


def test_two_post_like_deletes_in_a_row_raise_no_error(monkeypatch):
    """FR-625: два «удалить» подряд — удаление отсутствующей строки не ошибка; отметки нет."""
    post = _post()
    viewer = support.make_employee()
    fd.like(post, viewer)
    likes = _likes()
    monkeypatch.setattr(likes, "find_mark", lambda kind, target_id, user_id: True)   # «отметка есть» всегда
    assert likes.toggle_post(viewer, post.pk) is False
    assert likes.toggle_post(viewer, post.pk) is False, "строки уже нет: не ошибка"
    assert _PostLike().objects.filter(post=post).count() == 0


def test_two_comment_like_deletes_in_a_row_raise_no_error(monkeypatch):
    """FR-625: то же для комментария."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    viewer = support.make_employee()
    fd.like(written, viewer)
    likes = _likes()
    monkeypatch.setattr(likes, "find_mark", lambda kind, target_id, user_id: True)
    assert likes.toggle_comment(viewer, written.pk) is False
    assert likes.toggle_comment(viewer, written.pk) is False
    assert _CommentLike().objects.filter(comment=written).count() == 0


def test_one_mark_per_user_unique_constraint_on_post_and_comment_likes():
    """FR-625: в базе одна отметка сотрудника на запись и на комментарий; другому сотруднику та же цель доступна."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    first, second = support.make_employee(), support.make_employee()
    for target, count in ((post, _PostLike), (written, _CommentLike)):
        fd.like(target, first)
        with pytest.raises(IntegrityError), transaction.atomic():
            fd.like(target, first)
        fd.like(target, second)
        assert _marks(target).count() == 2


# --- строка отметивших и полный список (FR-625) -----------------------------------------------------------

def test_post_likers_line_two_names_and_three_more_latest_first(clock):
    """FR-625: пять отметок — «Нравится: <ФИО>, <ФИО> и ещё 3», первыми отметившие последними; «и ещё 3» ведёт на полный список."""
    post = _post()
    people = _likers(5, post, post, clock)
    page = tree(fd.as_plain().client.get("/"))
    card = q1(page, "article", id=f"feed-post-{post.pk}")
    assert _line(card) == f"Нравится: {people[4].full_name}, {people[3].full_name} и ещё 3"
    (more,) = [a for a in q(q1(card, data_feed_likers=True), "a")]
    assert "и ещё 3" in more.text() and more.attrs["hx-get"] == f"/feed/{post.pk}/likes/"


def test_comment_likers_line_latest_first(clock):
    """FR-625: у комментария строка отметивших — «Нравится: <ФИО>, <ФИО>», последний отметивший первым."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    people = _likers(2, post, written, clock)
    page = tree(fd.as_plain().client.get(f"/feed/{post.pk}/"))
    row = q1(page, id=f"c{written.pk}")
    assert _line(row) == f"Нравится: {people[1].full_name}, {people[0].full_name}"


def test_post_likes_fragment_lists_all_likers(clock):
    """FR-625: `GET /feed/<id>/likes/` — фрагмент `ul[data-feed-list=likers]` со всеми отметившими, последний первым."""
    post = _post()
    people = _likers(5, post, post, clock)
    response = fd.as_plain().client.get(_likers_path(post), **HX)
    assert response.status_code == 200
    assert "<html" not in html_of(response).lower()
    items = q(q1(tree(response), "ul", data_feed_list="likers"), "li")
    assert [item.text() for item in items] == [p.full_name for p in reversed(people)]


def test_comment_likes_fragment_lists_all_likers(clock):
    """FR-625: `GET /feed/comments/<cid>/likes/` — все отметившие комментарий, последний первым."""
    post = _post()
    written = fd.comment(post, post.author, "комментарий")
    people = _likers(4, post, written, clock)
    response = fd.as_plain().client.get(_likers_path(written), **HX)
    assert response.status_code == 200
    items = q(q1(tree(response), "ul", data_feed_list="likers"), "li")
    assert [item.text() for item in items] == [p.full_name for p in reversed(people)]


# --- уведомление автору, себе — нет (FR-625, FR-630) -------------------------------------------------------

def test_author_likes_own_post_without_notification_to_self(django_capture_on_commit_callbacks):
    """FR-625, FR-630: свою запись отметить можно, уведомления себе нет; отметка другого — одно `feed.like` автору."""
    author = fd.as_plain()
    post = _post(author.user)
    with django_capture_on_commit_callbacks(execute=True):
        assert _press(author, post).status_code == 200
    assert _PostLike().objects.filter(post=post, user=author.user).count() == 1
    assert _notices(author.user) == []
    other = fd.as_plain()
    with django_capture_on_commit_callbacks(execute=True):
        assert _press(other, post).status_code == 200
    assert len(_notices(author.user)) == 1, "чужая отметка уведомляет автора"
    assert _notices(other.user) == []


def test_author_likes_own_comment_without_notification_to_self(django_capture_on_commit_callbacks):
    """FR-625, FR-630: свой комментарий отметить можно, уведомления себе нет; отметка другого — одно `feed.like` автору."""
    post = _post()
    author = fd.as_plain()
    written = fd.comment(post, author.user, "мой комментарий")
    with django_capture_on_commit_callbacks(execute=True):
        assert _press(author, written).status_code == 200
    assert _CommentLike().objects.filter(comment=written, user=author.user).count() == 1
    assert _notices(author.user) == []
    other = fd.as_plain()
    with django_capture_on_commit_callbacks(execute=True):
        assert _press(other, written).status_code == 200
    assert len(_notices(author.user)) == 1
    assert _notices(other.user) == []


# --- невидимая запись (FR-625) -------------------------------------------------------------------------------

def test_post_like_and_likes_of_invisible_post_return_404():
    """FR-625: `like` и `likes` записи, которую сотрудник не видит, — 404, как у несуществующей; отметки нет."""
    hidden = _post(to=(support.make_employee(),))
    outsider = fd.as_plain()
    missing = hidden.pk + 1000
    liked = outsider.client.post(f"/feed/{hidden.pk}/like/", **HX)
    listed = outsider.client.get(f"/feed/{hidden.pk}/likes/")
    assert liked.status_code == 404 and listed.status_code == 404
    assert support.same_failure(liked, outsider.client.post(f"/feed/{missing}/like/", **HX))
    assert support.same_failure(listed, outsider.client.get(f"/feed/{missing}/likes/"))
    assert _PostLike().objects.count() == 0


def test_comment_like_and_likes_of_invisible_post_return_404():
    """FR-625: `like` и `likes` комментария записи, которую сотрудник не видит, — 404, как у несуществующего комментария."""
    hidden = _post(to=(support.make_employee(),))
    written = fd.comment(hidden, hidden.author, "комментарий скрытой записи")
    outsider = fd.as_plain()
    missing = written.pk + 1000
    liked = outsider.client.post(f"/feed/comments/{written.pk}/like/", **HX)
    listed = outsider.client.get(f"/feed/comments/{written.pk}/likes/")
    assert liked.status_code == 404 and listed.status_code == 404
    assert support.same_failure(liked, outsider.client.post(f"/feed/comments/{missing}/like/", **HX))
    assert support.same_failure(listed, outsider.client.get(f"/feed/comments/{missing}/likes/"))
    assert _CommentLike().objects.count() == 0
