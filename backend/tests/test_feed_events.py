"""T-7113: событие в ленте — поля, ответы, списки, запреты правки (FR-616, FR-617, FR-619, FR-642). Сценарий 3 спеки
среза 007 (пп. 1, 2, 3, 6, 10, 11, 13, 14).

Публикация и правка идут настоящими адресами `/feed/posts/` и `/feed/<id>/edit/`; ответ — `/feed/<id>/answer/`,
списки — `/feed/<id>/answers/` (CONTRACT-007, 10.2). Тексты отказов — литералы раздела 13 контракта (решение 19
задач), зацепки — раздел 12 (`[data-error]`, `[data-code]`, `[data-feed-event]`, `[data-feed-answers]`). Код среза на
уровне модуля не импортируется; время — только через `clock` (решение 5): события строятся от `timezone.now()`.
Если событие должно «начаться», часы сдвигаются до входа в систему (иначе сессия устарела бы по бездействию).
"""
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests import support_org as org
from tests.support import HX
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")

NEED_TITLE = "Укажите название события"
NEED_PLACE = "Укажите место события"
LIMIT_200 = "Предел: 200 знаков"
NEED_TIMES = "Укажите начало и конец события"
END_AFTER_START = "Конец должен быть позже начала"
START_PASSED = "Начало уже прошло"
EVENT_STARTED = "Событие началось: время и место не меняются"
ANSWERS_CLOSED = "Ответы закрыты: событие началось"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {name: ("" if value is None else value) for name, value in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []
        for child in self.children:
            parts.append(child.text() if isinstance(child, Node) else child)
        return " ".join("".join(parts).split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", [], None)
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
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(body) -> Node:
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    builder = _Builder()
    builder.feed(body)
    builder.close()
    return builder.root


def find(root, tag=None, **attrs):
    """Все элементы с тегом `tag` и атрибутами (`data_x` → `data-x`; значение `True` — «атрибут есть»)."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    out = []
    for node in root.walk():
        if tag and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            out.append(node)
    return out


def event_block(body, post_id):
    nodes = find(parse(body), id=f"feed-post-{post_id}-event")
    return nodes[0] if nodes else None


def answer_buttons(root):
    return find(root, "button", data_action="answer")


def count_of(block, which: str) -> int:
    nodes = find(block, data_feed_answers_count=which)
    assert nodes, f"нет [data-feed-answers-count={which}]"
    return int(re.search(r"\d+", nodes[0].text()).group())


def refusal(body, field, code):
    nodes = find(parse(body), data_error=field, data_code=code)
    return nodes[0] if nodes else None


# --- время и данные -------------------------------------------------------------------------------------

def stamp(moment: datetime) -> str:
    return moment.astimezone(MSK).strftime("%Y-%m-%dT%H:%M")


def minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def tomorrow():
    """Начало через сутки, с точностью до минуты (форма минут не мельче)."""
    return minute(timezone.now()) + timedelta(days=1)


def fields(start, end=None, **over) -> dict:
    data = {"kind": "event", "text": "", "event_title": "Переезд серверной", "event_place": "Корпус 2, ауд. 101",
            "event_start": stamp(start), "event_end": stamp(end or start + timedelta(hours=2))}
    data.update(over)
    return data


def publish(session, data, to=()):
    data = dict(data)
    data["to"] = [f"p{user.pk}" for user in to]
    return session.client.post("/feed/posts/", data, **HX)


def events():
    return model("feed.Post").objects.filter(kind="event")


def notifications():
    return model("notify.Notification").objects.count()


def employee(name: str, **extra):
    return support.make_employee(full_name=name, **extra)


def relogin(user) -> fd.Session:
    return fd.Session(user, support.logged_in(user))


def edit(session, post, **over):
    saved = [f"u{r.unit_id}" if r.kind == "unit" else f"p{r.user_id}"
             for r in model("feed.Recipient").objects.filter(post=post, via="to").order_by("pk")]
    data = fields(post.event_start, post.event_end, text=post.text, event_title=post.event_title,
                  event_place=post.event_place)
    data.update(over)
    data["to"] = saved
    return session.client.post(f"/feed/{post.pk}/edit/", data, **HX)


def started_event(clock, *, hours_before=2, to_extra=(), **kw):
    """Событие, которое началось: создаётся за `hours_before` часа до начала, затем часы идут на 3 часа вперёд.
    Возвращает `(автор, участник, запись)`; входить в систему — после этого."""
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(timezone.now()) + timedelta(hours=hours_before),
                         to=[participant, *to_extra], **kw)
    clock.advance(hours=hours_before + 1)
    return author, participant, post


# --- публикация: поля и отказы --------------------------------------------------------------------------

def test_event_with_title_start_end_place_is_published_with_event_block_and_answer_buttons_for_participant():
    author, participant = fd.as_plain(), fd.as_plain()
    start = tomorrow()
    response = publish(author, fields(start, start + timedelta(hours=2), text="Берите пропуска"), [participant.user])
    assert response.status_code == 200
    post = events().get()
    assert (post.author_id, post.kind, post.event_title, post.event_place) == (
        author.user.pk, "event", "Переезд серверной", "Корпус 2, ауд. 101")
    assert (post.event_start, post.event_end) == (start, start + timedelta(hours=2))
    page = participant.client.get("/")
    block = event_block(page.content, post.pk)
    assert block is not None and "data-feed-event" in block.attrs
    text = block.text()
    assert "Переезд серверной" in text and "Корпус 2, ауд. 101" in text
    assert find(block, "button", data_action="answer", value="go") and find(block, "button", data_action="answer",
                                                                            value="no")


def test_event_block_has_no_answer_buttons_for_author():
    author, participant = fd.as_plain(), fd.as_plain()
    publish(author, fields(tomorrow()), [participant.user])
    post = events().get()
    block = event_block(author.client.get("/").content, post.pk)
    assert block is not None
    assert answer_buttons(block) == []


def test_empty_event_title_is_refused_with_enter_event_title():
    author, participant = fd.as_plain(), fd.as_plain()
    response = publish(author, fields(tomorrow(), event_title=""), [participant.user])
    assert response.status_code == 200
    node = refusal(response.content, "event_title", "event_title_required")
    assert node is not None and NEED_TITLE in node.text()
    assert events().count() == 0


def test_event_title_of_200_chars_is_accepted_and_201_refused_with_limit_200():
    author, participant = fd.as_plain(), fd.as_plain()
    ok = publish(author, fields(tomorrow(), event_title="а" * 200), [participant.user])
    assert ok.status_code == 200 and refusal(ok.content, "event_title", "too_long") is None
    assert events().get().event_title == "а" * 200
    response = publish(author, fields(tomorrow(), event_title="б" * 201), [participant.user])
    assert response.status_code == 200
    node = refusal(response.content, "event_title", "too_long")
    assert node is not None and LIMIT_200 in node.text()
    assert "б" * 201 in response.content.decode()
    assert events().count() == 1


def test_empty_event_place_is_refused_with_enter_event_place():
    author, participant = fd.as_plain(), fd.as_plain()
    response = publish(author, fields(tomorrow(), event_place=""), [participant.user])
    assert response.status_code == 200
    node = refusal(response.content, "event_place", "event_place_required")
    assert node is not None and NEED_PLACE in node.text()
    assert events().count() == 0


def test_event_place_of_200_chars_is_accepted_and_201_refused_with_limit_200():
    author, participant = fd.as_plain(), fd.as_plain()
    ok = publish(author, fields(tomorrow(), event_place="в" * 200), [participant.user])
    assert ok.status_code == 200 and refusal(ok.content, "event_place", "too_long") is None
    assert events().get().event_place == "в" * 200
    response = publish(author, fields(tomorrow(), event_place="г" * 201), [participant.user])
    assert response.status_code == 200
    node = refusal(response.content, "event_place", "too_long")
    assert node is not None and LIMIT_200 in node.text()
    assert events().count() == 1


def test_missing_event_start_or_end_is_refused_with_reason_at_field():
    author, participant = fd.as_plain(), fd.as_plain()
    start = tomorrow()
    no_start = publish(author, fields(start, event_start=""), [participant.user])
    node = refusal(no_start.content, "event_start", "event_time_required")
    assert no_start.status_code == 200 and node is not None and NEED_TIMES in node.text()
    no_end = publish(author, fields(start, event_end=""), [participant.user])
    node = refusal(no_end.content, "event_end", "event_time_required")
    assert no_end.status_code == 200 and node is not None and NEED_TIMES in node.text()
    assert events().count() == 0


def test_event_start_and_end_are_taken_and_shown_in_moscow_time():
    author, participant = fd.as_plain(), fd.as_plain()
    day = timezone.now().astimezone(MSK).date() + timedelta(days=1)
    start = datetime(day.year, day.month, day.day, 10, 0, tzinfo=MSK)
    end = start + timedelta(hours=2)
    publish(author, fields(start, end), [participant.user])
    post = events().get()
    assert post.event_start == start and post.event_end == end
    assert post.event_start.utcoffset() is not None
    block = event_block(participant.client.get("/").content, post.pk)
    shown = [node.text() for node in find(block, "time", data_at=True)]
    assert fd.moscow_text(start) in shown and fd.moscow_text(end) in shown
    assert fd.moscow_text(start).endswith("10:00") and fd.moscow_text(end).endswith("12:00")
    # то же время, введённое как «ДД.ММ.ГГГГ ЧЧ:ММ» (раздел 10.2 контракта)
    second_day = day + timedelta(days=1)
    publish(author, fields(start, end, event_start=f"{second_day:%d.%m.%Y} 10:00",
                           event_end=f"{second_day:%d.%m.%Y} 12:00"), [participant.user])
    other = events().exclude(pk=post.pk).get()
    assert other.event_start == start + timedelta(days=1) and other.event_end == end + timedelta(days=1)


def test_event_end_equal_to_or_before_start_is_refused_with_end_after_start():
    author, participant = fd.as_plain(), fd.as_plain()
    start = tomorrow()
    for end in (start, start - timedelta(hours=1)):
        response = publish(author, fields(start, end), [participant.user])
        assert response.status_code == 200
        node = refusal(response.content, "event_end", "event_end_before_start")
        assert node is not None and END_AFTER_START in node.text()
    assert events().count() == 0


def test_event_start_in_past_is_refused_with_start_already_passed():
    author, participant = fd.as_plain(), fd.as_plain()
    start = minute(timezone.now()) - timedelta(hours=1)
    response = publish(author, fields(start, start + timedelta(hours=3)), [participant.user])
    assert response.status_code == 200
    node = refusal(response.content, "event_start", "event_start_passed")
    assert node is not None and START_PASSED in node.text()
    assert events().count() == 0


def test_event_without_text_is_published():
    author, participant = fd.as_plain(), fd.as_plain()
    response = publish(author, fields(tomorrow(), text=""), [participant.user])
    assert response.status_code == 200
    post = events().get()
    assert post.text == "" and post.event_title == "Переезд серверной"
    assert event_block(participant.client.get("/").content, post.pk) is not None


# --- ответы участников ----------------------------------------------------------------------------------

def test_participant_answers_go_then_changes_to_no_before_start_and_gets_event_block_fragment():
    author, participant = fd.as_plain(), fd.as_plain()
    post = fd.make_event(author.user, start=tomorrow(), to=[participant.user])
    first = participant.client.post(f"/feed/{post.pk}/answer/", {"answer": "go"}, **HX)
    assert first.status_code == 200
    block = event_block(first.content, post.pk)
    assert block is not None and count_of(block, "go") == 1 and count_of(block, "no") == 0
    Answer = model("feed.EventAnswer")
    assert Answer.objects.get(post=post, user=participant.user).answer == "go"
    second = participant.client.post(f"/feed/{post.pk}/answer/", {"answer": "no"}, **HX)
    assert second.status_code == 200
    block = event_block(second.content, post.pk)
    assert block is not None and count_of(block, "go") == 0 and count_of(block, "no") == 1
    assert Answer.objects.filter(post=post, user=participant.user).count() == 1
    assert Answer.objects.get(post=post, user=participant.user).answer == "no"


def test_answer_after_start_is_refused_with_answers_closed_and_buttons_are_gone(clock):
    author, participant, post = started_event(clock)
    session = relogin(participant)
    response = session.client.post(f"/feed/{post.pk}/answer/", {"answer": "go"}, **HX)
    assert response.status_code == 200
    alert = find(parse(response.content), role="alert", data_code="answers_closed")
    assert alert and ANSWERS_CLOSED in alert[0].text()
    assert answer_buttons(parse(response.content)) == []
    assert model("feed.EventAnswer").objects.filter(post=post).count() == 0
    block = event_block(session.client.get("/").content, post.pk)
    assert block is not None and answer_buttons(block) == []


def test_answer_by_author_is_403():
    author, participant = fd.as_plain(), fd.as_plain()
    post = fd.make_event(author.user, start=tomorrow(), to=[participant.user])
    response = author.client.post(f"/feed/{post.pk}/answer/", {"answer": "go"}, **HX)
    assert response.status_code == 403
    assert model("feed.EventAnswer").objects.filter(post=post).count() == 0


def test_go_and_no_counts_are_shown_to_every_viewer():
    author, going, declining, silent = fd.as_plain(), fd.as_plain(), fd.as_plain(), fd.as_plain()
    post = fd.make_event(author.user, start=tomorrow(), to=[going.user, declining.user, silent.user])
    going.client.post(f"/feed/{post.pk}/answer/", {"answer": "go"}, **HX)
    declining.client.post(f"/feed/{post.pk}/answer/", {"answer": "no"}, **HX)
    for viewer in (author, going, declining, silent):
        block = event_block(viewer.client.get("/").content, post.pk)
        assert block is not None
        assert (count_of(block, "go"), count_of(block, "no")) == (1, 1)


def test_answers_lists_go_no_and_not_answered_are_open_to_author():
    author = fd.as_plain()
    going = employee("Идущий Участников")
    declining = employee("Отказавшийся Участников")
    silent = employee("Молчащий Участников")
    post = fd.make_event(author.user, start=tomorrow(), to=[going, declining, silent])
    for user, answer in ((going, "go"), (declining, "no")):
        model("feed.EventAnswer").objects.create(post=post, user=user, answer=answer, answered_at=timezone.now())
    response = author.client.get(f"/feed/{post.pk}/answers/")
    assert response.status_code == 200
    root = parse(response.content)
    assert find(root, "ul", data_feed_list="answers") or find(root, data_feed_list="answers")
    parts = {name: find(root, data_feed_answers=name) for name in ("go", "no", "none")}
    assert all(len(nodes) == 1 for nodes in parts.values())
    assert "Идущий Участников" in parts["go"][0].text() and "Идущий" not in parts["no"][0].text()
    assert "Отказавшийся Участников" in parts["no"][0].text() and "Отказавшийся" not in parts["go"][0].text()
    assert "Молчащий Участников" in parts["none"][0].text()
    assert "Идущий" not in parts["none"][0].text() and "Отказавшийся" not in parts["none"][0].text()
    assert "Тест Тестов" not in " ".join(nodes[0].text() for nodes in parts.values())   # автора в списках нет
    block = event_block(author.client.get("/").content, post.pk)
    assert find(block, data_feed_answers_link=True)


def test_answers_lists_are_403_to_moderator_participant_and_other_viewers_who_see_counts_only():
    author, moderator, participant, other = fd.as_plain(), fd.as_moderator(), fd.as_plain(), fd.as_plain()
    post = fd.make_event(author.user, start=tomorrow(), to=[moderator.user, participant.user, other.user])
    for viewer in (moderator, participant, other):
        assert viewer.client.get(f"/feed/{post.pk}/answers/").status_code == 403
        block = event_block(viewer.client.get("/").content, post.pk)
        assert block is not None
        assert find(block, data_feed_answers_link=True) == []
        assert count_of(block, "go") == 0 and count_of(block, "no") == 0


def test_counts_and_lists_ignore_answers_of_fired_blocked_and_left_audience():
    author = fd.as_plain()
    active = employee("Действующий Ответивший")
    fired = employee("Уволенный Ответивший")
    blocked = employee("Заблокированный Ответивший")
    left = employee("Вышедший Ответивший")
    unit = org.make_unit()
    memberships = {user: org.make_member(user, unit) for user in (active, fired, blocked, left)}
    post = fd.make_event(author.user, start=tomorrow(), to=[unit])
    for user in (active, fired, blocked, left):
        model("feed.EventAnswer").objects.create(post=post, user=user, answer="go", answered_at=timezone.now())
    model("core.User").objects.filter(pk=fired.pk).update(state="dismissed")
    model("core.User").objects.filter(pk=blocked.pk).update(state="blocked")
    memberships[left].delete()
    root = parse(author.client.get(f"/feed/{post.pk}/answers/").content)
    go_text = find(root, data_feed_answers="go")[0].text()
    assert "Действующий Ответивший" in go_text
    for name in ("Уволенный", "Заблокированный", "Вышедший"):
        assert name not in go_text
    block = event_block(author.client.get("/").content, post.pk)
    assert count_of(block, "go") == 1 and count_of(block, "no") == 0


def test_not_answered_list_excludes_fired_and_blocked_participants():
    author = fd.as_plain()
    silent = employee("Молчащий Действующий")
    answered = employee("Ответивший Действующий")
    fired = employee("Уволенный Молчащий")
    blocked = employee("Заблокированный Молчащий")
    post = fd.make_event(author.user, start=tomorrow(), to=[silent, answered, fired, blocked])
    model("feed.EventAnswer").objects.create(post=post, user=answered, answer="go", answered_at=timezone.now())
    model("core.User").objects.filter(pk=fired.pk).update(state="dismissed")
    model("core.User").objects.filter(pk=blocked.pk).update(state="blocked")
    root = parse(author.client.get(f"/feed/{post.pk}/answers/").content)
    none_text = find(root, data_feed_answers="none")[0].text()
    assert "Молчащий Действующий" in none_text
    for name in ("Уволенный", "Заблокированный", "Ответивший"):
        assert name not in none_text


# --- правка события -------------------------------------------------------------------------------------

def test_edit_of_started_event_refuses_start_end_and_place_change_with_event_started(clock):
    author, participant, post = started_event(clock)
    session = relogin(author)
    before = (post.event_start, post.event_end, post.event_place)
    changes = ({"event_start": stamp(post.event_start + timedelta(hours=5)),
                "event_end": stamp(post.event_end + timedelta(hours=5))},
               {"event_end": stamp(post.event_end + timedelta(hours=1))},
               {"event_place": "Другая комната"})
    for change in changes:
        response = edit(session, post, **change)
        assert response.status_code == 200
        nodes = find(parse(response.content), data_code="event_started")
        assert nodes and EVENT_STARTED in nodes[0].text()
        assert nodes[0].attrs.get("data-error") == "event_start"
        post.refresh_from_db()
        assert (post.event_start, post.event_end, post.event_place) == before


def test_edit_of_started_event_changes_title_and_description_without_notifications(clock):
    author, participant, post = started_event(clock, text="Старое описание")
    session = relogin(author)
    notified = notifications()
    response = edit(session, post, event_title="Новое название", text="Новое описание")
    assert response.status_code == 200
    assert find(parse(response.content), data_code=True) == []
    post.refresh_from_db()
    assert (post.event_title, post.text) == ("Новое название", "Новое описание")
    assert post.edited_at is not None
    assert notifications() == notified


def test_edit_moving_start_to_past_is_refused_with_start_already_passed():
    author = fd.as_plain()
    participant = support.make_employee()
    post = fd.make_event(author.user, start=minute(timezone.now()) + timedelta(hours=3), to=[participant])
    before = post.event_start
    response = edit(author, post, event_start=stamp(minute(timezone.now()) - timedelta(hours=1)))
    assert response.status_code == 200
    node = refusal(response.content, "event_start", "event_start_passed")
    assert node is not None and START_PASSED in node.text()
    post.refresh_from_db()
    assert post.event_start == before


def test_answers_are_kept_after_event_edit():
    author = fd.as_plain()
    going, declining = support.make_employee(), support.make_employee()
    post = fd.make_event(author.user, start=tomorrow(), to=[going, declining])
    Answer = model("feed.EventAnswer")
    Answer.objects.create(post=post, user=going, answer="go", answered_at=timezone.now())
    Answer.objects.create(post=post, user=declining, answer="no", answered_at=timezone.now())
    shift = timedelta(days=1)
    response = edit(author, post, event_title="Переименованное событие", event_start=stamp(post.event_start + shift),
                    event_end=stamp(post.event_end + shift))
    assert response.status_code == 200
    post.refresh_from_db()
    assert post.event_title == "Переименованное событие"
    assert {(a.user_id, a.answer) for a in Answer.objects.filter(post=post)} == {
        (going.pk, "go"), (declining.pk, "no")}


# --- ограничения базы -----------------------------------------------------------------------------------

def test_db_check_ties_kind_event_to_filled_event_fields_and_end_after_start():
    Post = model("feed.Post")
    author = support.make_employee()
    now = timezone.now()
    start = now + timedelta(days=1)
    good = dict(author=author, kind="event", text="", published_at=now, event_title="Название", event_place="Место",
                event_start=start, event_end=start + timedelta(hours=1))
    broken = (
        {"event_title": None}, {"event_title": ""}, {"event_place": None}, {"event_place": ""},
        {"event_start": None}, {"event_end": None},
        {"event_end": start}, {"event_end": start - timedelta(minutes=1)},
    )
    for change in broken:
        with pytest.raises(IntegrityError), transaction.atomic():
            Post.objects.create(**{**good, **change})
    # обратное направление: поля события у записи другого вида недопустимы
    for kind in ("post", "important"):
        extra = {"important_until": now + timedelta(days=2)} if kind == "important" else {}
        with pytest.raises(IntegrityError), transaction.atomic():
            Post.objects.create(**{**good, "kind": kind, **extra})
    assert Post.objects.count() == 0
    Post.objects.create(**good)
    assert Post.objects.get().event_end == start + timedelta(hours=1)
