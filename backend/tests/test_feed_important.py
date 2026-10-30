"""T-7112: важное — сроки, «Прочитано», «Прочитали N из M» (FR-605, FR-613, FR-614, FR-615, FR-620, FR-642,
NFR-611). Сценарий 2 спеки среза 007.

Срок хранится моментом окончания — полночь Europe/Moscow после последнего дня срока («День» — день после публикации,
«Неделя» — D + 7, «Месяц» — то же число следующего месяца или последний день месяца, «До даты» — указанная дата);
дата «До даты» — завтра … через год; срок при правке меняется только вместе с полями срока; «Прочитано» (необратимо, не
автору, не после срока); блок важных и «было важным»; «Прочитали N из M» (M — действующие адресаты без автора);
списки `/feed/<id>/reads/`; проверка базы «вид — срок». План: «Важное», «Модель данных» (срок важного), «Контракты»;
CONTRACT-007, 5.4, 10.2, 12.3, 13.2. Код среза на уровне модуля не импортируется: имена берутся внутри тестов.
Время — часы `clock`; проверки «по Москве» — на 21:30 и 00:00 UTC (CONTRACT-007, правила для всех тестов).
"""
import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests import support
from tests import support_feed as feed
from tests.support import HX

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
DATE_PASSED = "Дата уже прошла"
TOO_FAR = "Срок — не позже чем через год"
READ_AUTHOR = "Автор не отмечает свою запись прочитанной"
READ_EXPIRED = "Срок важного уже истёк"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, _Node) else parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())

    def raw_text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, _Node) else parts.append(child)

        collect(self)
        return "".join(parts)

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(response_or_html) -> _Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
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


# --- данные теста -----------------------------------------------------------------------------------------

def _Post():
    return support.model("feed.Post")


def _ReadMark():
    return support.model("feed.ReadMark")


def _day(year, month, day, hour=0, minute=0):
    return feed.moscow(year, month, day, hour, minute)


def _form(**over) -> dict:
    data = {"kind": "important", "text": "Важное сообщение", "to": ["all"], "term": "day"}
    data.update(over)
    return {name: value for name, value in data.items() if value is not None}


def _publish(session, **fields):
    return session.client.post("/feed/posts/", _form(**fields))


def _edit(session, post, **fields):
    data = {"text": post.text, "to": ["all"]}
    data.update(fields)
    return session.client.post(f"/feed/{post.pk}/edit/", data)


def _last_post():
    return _Post().objects.order_by("-id").first()


def _person(name: str, **extra):
    return support.make_employee(full_name=name, totp=False, **extra)


def _bulk_people(count: int, prefix: str, state: str = "active") -> list:
    """`count` сотрудников одной вставкой (без входа; пароль не задаётся); у уволенных проставлено `dismissed_at`."""
    User = support.model("core.User")
    now = timezone.now()
    unusable = make_password(None)
    users = [User(email=f"{prefix.lower()}-{number}-{uuid.uuid4().hex[:6]}@example.com",
                  full_name=f"{prefix}{number:02d} Тестов", state=state, password=unusable,
                  activated_at=now if state == "active" else None,
                  dismissed_at=now if state == "dismissed" else None)
             for number in range(count)]
    return User.objects.bulk_create(users)


def _mark_read(post, users, at=None) -> None:
    for user in users:
        _ReadMark().objects.create(post=post, user=user, read_at=at or timezone.now())


def _feed_notifications() -> int:
    return support.model("notify.Notification").objects.filter(kind__startswith="feed.").count()


def _error(response, field: str, code: str):
    assert response.status_code == 200, f"ждали 200 с отказом, получили {response.status_code}"
    return q1(tree(response), None, data_error=field, data_code=code)


def _article(response, post):
    return q1(tree(response), "article", data_post_id=str(post.pk))


def _imp(response, post):
    return q1(tree(response), None, id=f"feed-post-{post.pk}-imp")


def _feed_ids(response) -> list[int]:
    lists = q(tree(response), "ol", id="feed-list")
    assert len(lists) == 1, "на странице нет ленты `ol#feed-list`"
    return [int(node.attrs["data-post-id"]) for node in q(lists[0], "article", data_post_id=True)]


def _block_ids(response) -> list[int]:
    blocks = q(tree(response), None, id="feed-important")
    if not blocks:
        return []
    return [int(node.attrs["data-post-id"]) for node in q(blocks[0], "article", data_post_id=True)]


def _reads_link(scope, post) -> bool:
    """Есть ли в `scope` (или он сам) ссылка на списки прочитавших `/feed/<id>/reads/`."""
    path = f"/feed/{post.pk}/reads/"
    nodes = [scope, *scope.walk()]
    return any(node.tag == "a" and (node.attrs.get("hx-get") == path or node.attrs.get("href") == path)
               for node in nodes)


# --- срок: моменты окончания ---------------------------------------------------------------------------------

def test_day_term_published_10_10_at_15_ends_at_12_10_moscow_midnight(clock):
    """FR-613, сценарий 2 п. 9: «День», публикация 10.10 в 15:00 — срок до 12.10 00:00 по Москве."""
    from apps.feed.services import important

    writer = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))

    response = _publish(writer, term="day")

    assert response.status_code == 302
    post = _last_post()
    assert post.kind == "important"
    assert post.published_at == _day(2026, 10, 10, 15, 0)
    assert post.important_until == _day(2026, 10, 12, 0, 0)
    assert important.until("day", None, date(2026, 10, 10)) == _day(2026, 10, 12)


def test_term_counts_from_moscow_date_when_clock_is_at_utc_midnight(clock):
    """FR-613, NFR-611: отсчёт идёт от даты по Москве, а не по UTC — на полночь UTC (03:00 по Москве) и на 21:30
    UTC предыдущего дня (00:30 по Москве уже следующей даты)."""
    writer = feed.as_writer()

    clock.set(datetime(2026, 10, 10, 0, 0, tzinfo=UTC))
    assert _publish(writer, term="day").status_code == 302
    assert _last_post().important_until == _day(2026, 10, 12)

    clock.set(datetime(2026, 10, 9, 21, 30, tzinfo=UTC))
    assert _publish(writer, term="day").status_code == 302
    assert _last_post().important_until == _day(2026, 10, 12)
    assert _publish(writer, term="week").status_code == 302
    assert _last_post().important_until == _day(2026, 10, 18)


def test_week_term_ends_at_moscow_midnight_after_day_plus_7(clock):
    """FR-613: «Неделя» — полночь по Москве после дня D + 7 (D = 10.10 — до 18.10 00:00)."""
    from apps.feed.services import important

    writer = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))

    assert _publish(writer, term="week").status_code == 302

    assert _last_post().important_until == _day(2026, 10, 18)
    assert important.until("week", None, date(2026, 10, 10)) == _day(2026, 10, 18)
    assert important.until("week", None, date(2026, 12, 28)) == _day(2027, 1, 5)


def test_month_term_from_january_31_ends_after_february_28_or_29(clock):
    """FR-613: «Месяц» — то же число следующего месяца, а если его нет — последний день месяца; срок кончается
    в полночь после этого дня (31.01.2026 — после 28.02, 31.01.2028 — после 29.02)."""
    from apps.feed.services import important

    writer = feed.as_writer()
    clock.set(_day(2026, 1, 31, 12, 0))

    assert _publish(writer, term="month").status_code == 302

    assert _last_post().important_until == _day(2026, 3, 1)
    assert important.until("month", None, date(2026, 1, 31)) == _day(2026, 3, 1)
    assert important.until("month", None, date(2028, 1, 31)) == _day(2028, 3, 1)
    assert important.until("month", None, date(2026, 3, 31)) == _day(2026, 5, 1)
    assert important.until("month", None, date(2026, 10, 10)) == _day(2026, 11, 11)
    assert important.until("month", None, date(2026, 12, 15)) == _day(2027, 1, 16)


def test_until_date_term_ends_at_moscow_midnight_after_given_date(clock):
    """FR-613: «До даты» — полночь по Москве после указанной даты."""
    from apps.feed.services import important

    writer = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))

    assert _publish(writer, term="date", until="2026-10-20").status_code == 302

    assert _last_post().important_until == _day(2026, 10, 21)
    assert important.until("date", date(2026, 10, 20), date(2026, 10, 10)) == _day(2026, 10, 21)
    assert important.until("date", date(2026, 12, 31), date(2026, 10, 10)) == _day(2027, 1, 1)


def test_term_choices_are_day_week_month_and_until_date():
    """FR-613, сценарий 2 п. 1: в форме срока — «День», «Неделя», «Месяц», «До даты» и поле даты."""
    writer = feed.as_writer()

    response = writer.client.get("/")

    root = tree(response)
    radios = q(root, "input", type="radio", name="term")
    assert {radio.attrs["value"] for radio in radios} == {"day", "week", "month", "date"}
    block = q1(root, None, data_kind_fields="important")
    for label in ("День", "Неделя", "Месяц", "До даты"):
        assert label in block.text()
    assert q1(block, "input", type="date", name="until")


# --- срок: отказы --------------------------------------------------------------------------------------------

def test_until_date_yesterday_or_today_is_refused_with_date_already_passed_at_term_field(clock):
    """FR-613, FR-642, сценарий 2 п. 7: вчерашняя и сегодняшняя дата — отказ «Дата уже прошла» у поля срока."""
    from apps.feed.services import important
    from apps.feed.services.errors import FeedError

    writer = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))

    for given in ("2026-10-09", "2026-10-10"):
        response = _publish(writer, term="date", until=given)
        assert DATE_PASSED in _error(response, "term", "date_passed").text()
    assert _Post().objects.count() == 0

    for given in (date(2026, 10, 9), date(2026, 10, 10)):
        with pytest.raises(FeedError) as caught:
            important.until("date", given, date(2026, 10, 10))
        assert (caught.value.code, caught.value.field) == ("date_passed", "term")


def test_until_date_in_13_months_is_refused_with_not_later_than_year_and_tomorrow_and_one_year_are_accepted(clock):
    """FR-613, FR-642, сценарий 2 п. 1 и 7: через 13 месяцев — «Срок — не позже чем через год»; завтра и ровно
    через год принимаются."""
    from apps.feed.services import important
    from apps.feed.services.errors import FeedError

    writer = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))

    response = _publish(writer, term="date", until="2027-11-10")
    assert TOO_FAR in _error(response, "term", "term_too_far").text()
    assert _Post().objects.count() == 0
    with pytest.raises(FeedError) as caught:
        important.until("date", date(2027, 11, 10), date(2026, 10, 10))
    assert (caught.value.code, caught.value.field) == ("term_too_far", "term")

    assert _publish(writer, term="date", until="2026-10-11").status_code == 302
    assert _last_post().important_until == _day(2026, 10, 12)
    assert _publish(writer, term="date", until="2027-10-10").status_code == 302
    assert _last_post().important_until == _day(2027, 10, 11)
    assert _Post().objects.count() == 2


def test_term_change_by_edit_to_past_date_or_13_months_is_refused_with_same_reasons(clock):
    """FR-613, FR-620, FR-642: правка срока — те же отказы у поля срока, срок записи не меняется; допустимая дата
    принимается и отсчитывается от даты правки."""
    author = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))
    post = feed.make_important(author.user, until=_day(2026, 10, 12), to=("all",))

    for given, code, text in (("2026-10-09", "date_passed", DATE_PASSED), ("2026-10-10", "date_passed", DATE_PASSED),
                              ("2027-11-10", "term_too_far", TOO_FAR)):
        response = _edit(author, post, term="date", until=given)
        assert text in _error(response, "term", code).text()
        post.refresh_from_db()
        assert post.important_until == _day(2026, 10, 12)

    assert _edit(author, post, term="date", until="2026-10-20").status_code == 302
    post.refresh_from_db()
    assert post.important_until == _day(2026, 10, 21)


# --- «Прочитано» -----------------------------------------------------------------------------------------------

def test_read_by_addressee_creates_read_mark_and_returns_post_fragment_without_read_button():
    """FR-614, сценарий 2 п. 2–3: адресат нажимает «Прочитано» — строка прочтения и фрагмент записи без кнопки."""
    author = feed.as_writer()
    reader = feed.as_plain()
    post = feed.make_important(author.user, to=("all",))
    before = reader.client.get("/")
    assert q(_imp(before, post), "button", data_action="read"), "до прочтения у адресата нет кнопки «Прочитано»"

    response = reader.client.post(f"/feed/{post.pk}/read/", **HX)

    assert response.status_code == 200
    assert "<html" not in response.content.decode("utf-8").lower()
    assert _ReadMark().objects.filter(post=post, user=reader.user).count() == 1
    root = tree(response)
    assert q(root, None, data_post_id=str(post.pk))
    assert not q(root, "button", data_action="read")


def test_read_post_leaves_important_block_and_stands_in_feed_by_publication_time():
    """FR-614, сценарий 2 п. 3: после «Прочитано» запись уходит из блока важных и встаёт в основную ленту по
    времени публикации."""
    author = support.make_employee()
    reader = feed.as_plain()
    now = timezone.now()
    oldest = feed.make_post(author, to=("all",), text="Старая", published_at=now - timedelta(hours=3))
    important = feed.make_important(author, to=("all",), text="Важная", published_at=now - timedelta(hours=2))
    newest = feed.make_post(author, to=("all",), text="Новая", published_at=now - timedelta(hours=1))

    before = reader.client.get("/")
    assert _block_ids(before) == [important.pk]
    assert _feed_ids(before) == [newest.pk, oldest.pk]

    assert reader.client.post(f"/feed/{important.pk}/read/").status_code == 302

    after = reader.client.get("/")
    assert _block_ids(after) == []
    assert not q(tree(after), None, id="feed-important")
    assert _feed_ids(after) == [newest.pk, important.pk, oldest.pk]
    assert not q(_article(after, important), "button", data_action="read")


def test_repeated_read_is_not_an_error_keeps_one_read_mark_and_has_no_undo(clock):
    """FR-614: повтор «Прочитано» — не ошибка, строка одна и с прежним временем; отмены нет."""
    author = feed.as_writer()
    reader = feed.as_plain()
    post = feed.make_important(author.user, to=("all",))

    first = reader.client.post(f"/feed/{post.pk}/read/")
    stamp = _ReadMark().objects.get(post=post, user=reader.user).read_at
    clock.advance(minutes=5)
    second = reader.client.post(f"/feed/{post.pk}/read/")
    third = reader.client.post(f"/feed/{post.pk}/read/", **HX)

    assert (first.status_code, first["Location"]) == (302, "/")
    assert (second.status_code, second["Location"]) == (302, "/")
    assert third.status_code == 200
    marks = _ReadMark().objects.filter(post=post, user=reader.user)
    assert marks.count() == 1
    assert marks.get().read_at == stamp
    root = tree(third)
    assert not q(root, "button", data_action="read")
    assert not q(root, "button", data_action="unread")


def test_read_by_author_is_403_with_reason_and_author_sees_no_read_button():
    """FR-614: у автора кнопки нет, запрос в обход — 403 с причиной в теле, прочтения нет."""
    author = feed.as_writer()
    post = feed.make_important(author.user, to=("all",))

    page = author.client.get("/")
    assert not q(_imp(page, post), "button", data_action="read")

    plain = author.client.post(f"/feed/{post.pk}/read/")
    hx = author.client.post(f"/feed/{post.pk}/read/", **HX)

    assert plain.status_code == 403
    assert hx.status_code == 403
    assert READ_AUTHOR in plain.content.decode("utf-8")
    assert READ_AUTHOR in hx.content.decode("utf-8")
    assert _ReadMark().objects.count() == 0


def test_read_after_term_expired_is_403_with_reason(clock):
    """FR-613, FR-614: до конца срока «Прочитано» принимается, с момента окончания срока (включительно) — 403 с
    причиной, строки прочтения нет."""
    author = feed.as_writer()
    early, at_end, late = feed.as_plain(), feed.as_plain(), feed.as_plain()
    clock.set(_day(2026, 10, 10, 15, 0))
    post = feed.make_important(author.user, until=_day(2026, 10, 12), to=("all",))

    clock.set(_day(2026, 10, 11, 23, 59))
    assert early.client.post(f"/feed/{post.pk}/read/").status_code == 302

    clock.set(_day(2026, 10, 12, 0, 0))
    ended = at_end.client.post(f"/feed/{post.pk}/read/")
    clock.set(_day(2026, 10, 12, 0, 1))
    after = late.client.post(f"/feed/{post.pk}/read/", **HX)

    for response in (ended, after):
        assert response.status_code == 403
        assert READ_EXPIRED in response.content.decode("utf-8")
    assert {mark.user_id for mark in _ReadMark().objects.filter(post=post)} == {early.user.pk}


# --- после срока ---------------------------------------------------------------------------------------------

def _expired_with_five_reads(clock):
    author = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))
    post = feed.make_important(author.user, until=_day(2026, 10, 12), to=("all",))
    readers = _bulk_people(5, "Читатель")
    _mark_read(post, readers)
    return author, post, readers


def test_expired_important_is_ordinary_post_with_was_important_and_read_count_without_button_and_block(clock):
    """FR-613, FR-614, сценарий 2 п. 6 и 9: после срока запись — обычная в ленте, без блока важных и кнопки, с
    пометкой «было важным» и «Прочитали 5»."""
    reader = feed.as_plain()
    author, post, readers = _expired_with_five_reads(clock)
    assert _block_ids(reader.client.get("/")) == [post.pk]

    clock.set(_day(2026, 10, 12, 10, 0))
    response = reader.client.get("/")

    assert _block_ids(response) == []
    assert not q(tree(response), None, id="feed-important")
    assert post.pk in _feed_ids(response)
    article = _article(response, post)
    assert not q(article, "button", data_action="read")
    assert "важно до" not in article.text()
    assert "было важным" in q1(article, None, data_feed_was_important=True).text()
    count = q1(article, None, data_feed_reads_count=True).text()
    assert "Прочитали 5" in count
    assert "из" not in count


def test_expired_important_creates_no_unread_reminders_after_reminder_and_night_jobs(clock):
    """FR-613, сценарий 2 п. 6: после срока задания напоминаний и ночное уведомлений о непрочитанном не создают;
    запись остаётся."""
    feed.as_plain()
    author, post, readers = _expired_with_five_reads(clock)
    before = _feed_notifications()

    now = _day(2026, 10, 12, 0, 5)
    clock.set(now)
    result = feed.run_reminders(now)
    deleted = feed.run_retention(now)
    clock.set(_day(2026, 10, 13, 0, 5))
    again = feed.run_reminders(_day(2026, 10, 13, 0, 5))

    assert result.reminded == 0
    assert again.reminded == 0
    assert deleted == 0
    assert _feed_notifications() == before == 0
    assert _Post().objects.filter(pk=post.pk).exists()


def test_making_expired_post_important_again_by_edit_sets_term_from_edit_date_keeps_read_marks_without_notifications(clock):
    """FR-613, FR-620, сценарий 2 п. 9: правкой с новым сроком «Неделя» запись снова важна — срок от даты правки
    (13.10 → до 21.10 00:00), прочтения сохранены, уведомлений нет."""
    reader = feed.as_plain()
    author, post, readers = _expired_with_five_reads(clock)
    clock.set(_day(2026, 10, 13, 12, 0))
    before = _feed_notifications()

    response = _edit(author, post, term="week")

    assert response.status_code == 302
    post.refresh_from_db()
    assert post.kind == "important"
    assert post.important_until == _day(2026, 10, 21)
    assert _ReadMark().objects.filter(post=post).count() == 5
    assert _feed_notifications() == before
    page = reader.client.get("/")
    assert _block_ids(page) == [post.pk]
    assert not q(tree(page), None, data_feed_was_important=True)


def test_editing_only_text_or_files_keeps_important_until_and_skips_date_passed_check(clock):
    """FR-620: правка текста или файлов срок не пересчитывает и «Дата уже прошла» не проверяет — ни без полей срока,
    ни с сохранённой датой, которая уже сегодня."""
    author = feed.as_writer()
    clock.set(_day(2026, 10, 10, 15, 0))
    post = feed.make_important(author.user, until=_day(2026, 10, 12), to=("all",))
    clock.set(_day(2026, 10, 11, 12, 0))   # сохранённая дата 11.10 — сегодня: при проверке была бы отказом

    only_text = _edit(author, post, text="Новый текст без полей срока")
    assert only_text.status_code == 302
    with_saved_date = _edit(author, post, text="Ещё текст", term="date", until="2026-10-11")
    assert with_saved_date.status_code == 302

    unbound = feed.attach(None, uploaded_by=author.user)
    only_files = _edit(author, post, text="Ещё текст", term="date", until="2026-10-11", files=[unbound.pk])
    assert only_files.status_code == 302

    post.refresh_from_db()
    assert post.text == "Ещё текст"
    assert post.important_until == _day(2026, 10, 12)
    unbound.refresh_from_db()
    assert unbound.post_id == post.pk


def test_edit_form_shows_current_term_as_until_date_with_saved_date():
    """FR-620: форма правки показывает действующий срок как «До даты» с сохранённой датой (последний день срока)."""
    author = feed.as_writer()
    post = feed.make_important(author.user, until=_day(2026, 10, 18), to=("all",))

    response = author.client.get(f"/feed/{post.pk}/edit/")

    root = tree(response)
    radios = q(root, "input", type="radio", name="term")
    assert [radio.attrs["value"] for radio in radios if "checked" in radio.attrs] == ["date"]
    assert q1(root, "input", name="until").attrs.get("value") == "2026-10-17"


# --- «Прочитали N из M» ------------------------------------------------------------------------------------------

def test_author_sees_read_n_of_m_where_m_is_audience_without_author():
    """FR-615, сценарий 2 п. 4: автор видит «Прочитали N из M», M — адресаты без автора (сам автор в «Кому» не
    считается), N — прочитавшие из них."""
    from apps.feed.services import important

    author = feed.as_writer()
    readers = _bulk_people(5, "Адресат")
    post = feed.make_important(author.user, to=(*readers, author.user))
    _mark_read(post, readers[:2])

    card = author.client.get(f"/feed/{post.pk}/")

    count = q1(_imp(card, post), None, data_feed_reads_count=True)
    assert "Прочитали 2 из 5" in count.text()
    assert _reads_link(_imp(card, post), post), "у автора нет ссылки на списки прочитавших"
    stats = important.stats(post)
    assert (stats.read, stats.total) == (2, 5)


def test_fired_and_blocked_addressees_are_outside_n_m_and_lists_m_is_37_of_40():
    """FR-605, FR-615, сценарий 2 п. 11: из 40 адресатов двое уволены и один заблокирован — M равно 37; их нет ни в
    N, ни в списках прочитавших и не прочитавших."""
    from apps.feed.services import important

    author = feed.as_plain()
    active = _bulk_people(37, "Читатель")
    fired = _bulk_people(2, "Уволенный", state="dismissed")
    blocked = _bulk_people(1, "Заблокированный", state="blocked")
    post = feed.make_important(author.user, to=(*active, *fired, *blocked))
    readers = active[:12]
    _mark_read(post, [*readers, fired[0], blocked[0]], at=feed.moscow(2026, 10, 10, 18, 30))

    card = author.client.get(f"/feed/{post.pk}/")
    stats = important.stats(post)
    listing = author.client.get(f"/feed/{post.pk}/reads/")

    assert "Прочитали 12 из 37" in q1(_imp(card, post), None, data_feed_reads_count=True).text()
    assert (stats.read, stats.total) == (12, 37)
    assert listing.status_code == 200
    root = tree(listing)
    read_part = q1(root, None, data_feed_reads="read").text()
    unread_part = q1(root, None, data_feed_reads="unread").text()
    for user in active:
        assert (user.full_name in read_part) == (user in readers)
        assert (user.full_name in unread_part) == (user not in readers)
    body = listing.content.decode("utf-8")
    for user in (*fired, *blocked):
        assert user.full_name not in body


def test_ordinary_addressee_sees_only_read_n():
    """FR-615: остальные, кто видит запись, — только «Прочитали N», без «из M» и без ссылки на списки."""
    author = feed.as_writer()
    reader = feed.as_plain()
    others = _bulk_people(4, "Адресат")
    post = feed.make_important(author.user, to=(reader.user, *others))
    _mark_read(post, others[:2])

    card = reader.client.get(f"/feed/{post.pk}/")

    count = q1(_imp(card, post), None, data_feed_reads_count=True)
    assert "Прочитали 2" in count.text()
    assert "из" not in count.text()
    assert not _reads_link(count, post)
    assert not _reads_link(tree(card), post)


def test_reads_list_shows_read_with_time_and_unread_to_author_and_moderator_addressee():
    """FR-615, сценарий 2 п. 4–5: автор и модератор, которому запись адресована, видят «Прочитали» с временем и
    «Не прочитали»."""
    author = feed.as_writer()
    moderator = feed.as_moderator(full_name="Модератор Лентов")
    first, second, silent = _person("Первый Читатель"), _person("Второй Читатель"), _person("Молчун Тихов")
    post = feed.make_important(author.user, to=(first, second, silent, moderator.user))
    _mark_read(post, [first], at=feed.moscow(2026, 10, 10, 18, 30))
    _mark_read(post, [second], at=feed.moscow(2026, 10, 10, 19, 45))

    seen = {}
    for who, session in (("автор", author), ("модератор", moderator)):
        response = session.client.get(f"/feed/{post.pk}/reads/")
        assert response.status_code == 200, who
        root = tree(response)
        q1(root, None, data_feed_list="reads")
        read_part = q1(root, None, data_feed_reads="read")
        unread_part = q1(root, None, data_feed_reads="unread")
        assert "Первый Читатель" in read_part.text() and "Второй Читатель" in read_part.text()
        assert sorted(node.text() for node in q(read_part, "time", data_at=True)) == ["10.10.2026 18:30",
                                                                                     "10.10.2026 19:45"]
        assert "Молчун Тихов" in unread_part.text()
        assert "Первый Читатель" not in unread_part.text()
        seen[who] = (read_part.text(), unread_part.text())
    assert seen["автор"] == seen["модератор"]


def test_reads_list_is_403_to_other_viewers_and_404_to_moderator_not_addressee():
    """FR-615, FR-606: прочим видящим — 403; модератору, которому запись не адресована, — 404 как у несуществующей."""
    author = feed.as_writer()
    reader, other = feed.as_plain(), feed.as_plain()
    moderator = feed.as_moderator()
    post = feed.make_important(author.user, to=(reader.user, other.user))

    forbidden = [session.client.get(f"/feed/{post.pk}/reads/") for session in (reader, other)]
    hidden = moderator.client.get(f"/feed/{post.pk}/reads/")
    missing = moderator.client.get("/feed/999999999/reads/")

    assert [response.status_code for response in forbidden] == [403, 403]
    assert hidden.status_code == 404
    assert support.same_failure(hidden, missing)


# --- база ----------------------------------------------------------------------------------------------------

def test_db_check_ties_kind_important_to_non_empty_important_until():
    """FR-613: проверка базы — `kind='important'` ровно тогда, когда `important_until` не пусто."""
    Post = _Post()
    author = support.make_employee()
    now = timezone.now()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Post.objects.create(author=author, kind="important", text="без срока", published_at=now)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Post.objects.create(author=author, kind="post", text="со сроком", published_at=now,
                                important_until=now + timedelta(days=1))

    Post.objects.create(author=author, kind="important", text="со сроком", published_at=now,
                        important_until=now + timedelta(days=1))
    Post.objects.create(author=author, kind="post", text="обычная", published_at=now)
    assert Post.objects.count() == 2
