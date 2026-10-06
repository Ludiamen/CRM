"""T-3114: карточка заявки и лента (FR-227, FR-242, FR-243, FR-245, FR-246, FR-248, NFR-214). Сценарии 3 и 2 спеки.

Слайдер и страница, две колонки, элементы ленты (письма, ответы, комментарии, события) по `(at, id)` с авторами и
вложениями, время по Москве, тексты событий по-русски, внутренний комментарий, отметка согласия, «Закрыл:»,
экранирование HTML, неизменяемость ленты и поля `last_message_*`. Код среза на уровне модуля не импортируется:
имена берутся внутри тестов (CONTRACT-003, шапка).
"""
import importlib
import re
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MARKER_TAG = "marquee"   # тег, которого в разметке портала нет: «живой» он означал бы исполненный HTML


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}
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

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def inside(self, other) -> bool:
        return any(a is other for a in self.ancestors())


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


def _match(node, tag, attrs) -> bool:
    if tag is not None and node.tag != tag:
        return False
    for name, expected in (attrs or {}).items():
        if name not in node.attrs:
            return False
        value = node.attrs[name]
        if expected is True:
            continue
        if callable(expected):
            if not expected(value):
                return False
        elif value != expected:
            return False
    return True


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя атрибута с дефисом — через `_` (`data_field="number"`)."""
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    return [node for node in scope.walk() if _match(node, tag, wanted)]


def qs(scope, tag=None, **attrs) -> list:
    """Как `q`, но и сам `scope` считается: зацепка может стоять на самом элементе или на его потомке."""
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    return ([scope] if _match(scope, tag, wanted) else []) + q(scope, tag, **attrs)


def qs1(scope, tag=None, **attrs):
    found = qs(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


def has_class(name):
    return lambda value: name in value.split()


def order_of(root, node) -> int:
    for index, item in enumerate(root.walk()):
        if item is node:
            return index
    raise AssertionError("элемент не найден в документе")


# --- данные теста ---------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _staff(queue=None, **user_extra):
    """Участник очереди (сотрудник в её узле). Возвращает (пользователь, очередь)."""
    queue = queue or sd.make_queue()
    user = support.make_employee(**user_extra)
    org.make_member(user, queue.unit)
    return user, queue


def _open(user, number, *, hx: bool = False):
    client = support.logged_in(user)
    return client, client.get(f"/tickets/{number}/", **(HX if hx else {}))


def _card_page(user, number, *, hx: bool = False):
    """(клиент, дерево, корень карточки): ответ 200 и ровно один `[data-ticket-card]`."""
    client, response = _open(user, number, hx=hx)
    assert response.status_code == 200, f"карточка #{number}: {response.status_code}"
    root = tree(response)
    return client, root, q1(root, data_ticket_card=True)


def _feed(card) -> Node:
    return q1(card, "ol", data_feed=True)


def _li(card, entry_id) -> Node:
    return q1(_feed(card), "li", data_entry_id=str(entry_id))


def _stored_file(ticket, entry, name, *, status="clean"):
    """Принятое вложение: файл `clean` (или иной статус), `owner=None`, строка `Attachment` у элемента."""
    StoredFile, Attachment = model("core.StoredFile"), model("servicedesk.Attachment")
    stored = StoredFile.objects.create(purpose="attachment", owner=None, size=5, sha256="0" * 64,
                                       content_type="text/plain", status=status)
    Attachment.objects.create(ticket=ticket, entry=entry, file=stored, name=name, size=5,
                              created_at=stored.created_at)
    return stored


def _set_at(entry, moment: datetime) -> None:
    model("servicedesk.TicketEntry").objects.filter(pk=entry.pk).update(at=moment)
    entry.at = moment


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=dt_timezone.utc)


def _snapshot(entries) -> dict:
    """Неизменяемые поля элементов ленты: по ним проверяется, что элемент не менялся."""
    Entry = model("servicedesk.TicketEntry")
    result = {}
    for entry in entries:
        fresh = Entry.objects.get(pk=entry.pk)
        result[fresh.pk] = (fresh.kind, fresh.text, fresh.author_id, fresh.author_email, fresh.author_name,
                            fresh.at, fresh.event, fresh.data, fresh.ticket_id)
    return result


def _mixed_entries(ticket, authors, count: int, *, with_files: bool = True):
    """`count` элементов разных видов с разными авторами; вложения у письма и ответа."""
    kinds = ["incoming", "reply", "comment", "event"]
    made = []
    for i in range(count):
        kind = kinds[i % 4]
        author = authors[i % len(authors)] if kind in ("reply", "comment") else None
        over = {}
        if kind == "event":
            over = {"event": "status_changed", "data": {"before": "Новая", "after": "В работе",
                                                         "before_id": 1, "after_id": 2, "reason": "manual"}}
        if kind == "reply":
            over = {"send_state": "queued"}
        entry = sd.make_entry(ticket, kind, author=author, text="" if kind == "event" else f"Текст {i}", **over)
        if with_files and kind in ("incoming", "reply"):
            _stored_file(ticket, entry, f"файл-{i}.txt")
        made.append(entry)
    return made


# --- карточка: слайдер, страница, колонки -------------------------------------------------------------------

def test_card_htmx_request_returns_slider_fragment():
    """FR-242: запрос HTMX из списка получает фрагмент слайдера `.slider-panel` с картой `data-layout="slider"`."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    client, response = _open(user, ticket.number, hx=True)
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "<html" not in body.lower() and "<body" not in body.lower(), "фрагмент слайдера — не страница целиком"
    root = tree(response)
    panel = q1(root, class_=has_class("slider-panel"))
    card = q1(root, data_ticket_card=True)
    assert card.attrs.get("data-layout") == "slider"
    assert card.attrs.get("data-number") == str(ticket.number)
    assert card.attrs.get("data-kind") == "new"
    assert card is panel or card.inside(panel), "карточка слайдера лежит внутри .slider-panel"
    closers = q(panel, data_slider_close=True)
    assert closers, "у слайдера есть [data-slider-close]"


def test_card_direct_address_returns_full_page():
    """FR-242: прямой адрес — страница целиком с `data-layout="page"`, без слайдера."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    client, response = _open(user, ticket.number)
    assert response.status_code == 200
    assert "<html" in response.content.decode("utf-8").lower(), "прямой адрес отдаёт страницу целиком"
    root = tree(response)
    card = q1(root, data_ticket_card=True)
    assert card.attrs.get("data-layout") == "page"
    assert card.attrs.get("data-number") == str(ticket.number)
    assert not q(root, class_=has_class("slider-panel")), "на странице слайдера нет"


def test_card_has_fields_column_and_feed_column():
    """FR-242: внутри корня сначала колонка полей `[data-card-fields]`, затем колонка ленты `[data-card-feed]`."""
    user, queue = _staff()
    requester = sd.make_requester(full_name="Заявитель Заявителев")
    ticket = sd.make_ticket(queue=queue, requester=requester, subject="Не работает принтер")
    sd.make_entry(ticket, "incoming", text="Здравствуйте")
    for layout_hx in (False, True):
        client, root, card = _card_page(user, ticket.number, hx=layout_hx)
        fields = q1(card, data_card_fields=True)
        feed_col = q1(card, data_card_feed=True)
        assert order_of(root, fields) < order_of(root, feed_col), "поля идут раньше ленты"
        assert not feed_col.inside(fields) and not fields.inside(feed_col)
        assert q(feed_col, "ol", data_feed=True), "лента — в колонке ленты"
        for name in ("number", "subject", "status", "queue", "category", "priority", "complexity", "client-unit",
                     "source", "requester", "requester-name", "requester-email", "assignee", "created"):
            field = q1(fields, data_field=name)
            assert q(field, data_field_label=True) or q(fields, data_field_label=name), f"у поля {name} нет подписи"
        assert str(ticket.number) in q1(fields, data_field="number").text()
        assert "Не работает принтер" in q1(fields, data_field="subject").text()
        # пустые поля помечены, ответственный — словом «не назначен», категория — «не заполнено»
        assignee = q1(fields, data_field="assignee")
        assert assignee.attrs.get("data-empty") == "true" and "не назначен" in assignee.text()
        category = q1(fields, data_field="category")
        assert category.attrs.get("data-empty") == "true" and "не заполнено" in category.text()
        assert q1(fields, data_field="complexity").attrs.get("data-empty") == "true"
        assert q1(fields, data_field="subject").attrs.get("data-empty") != "true"
        # поля закрытой заявки, согласия и связей у открытой заявки без них отсутствуют
        for name in ("closed-by", "resolution", "consent", "previous", "continuation"):
            assert not q(card, data_field=name), f"у открытой заявки без связей поля {name} нет"


def test_card_markup_for_narrow_width_puts_feed_under_fields():
    """FR-242: до 600 px лента идёт под полями без дополнительной вёрстки — порядок колонок в разметке и одна разметка."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    sd.make_entry(ticket, "incoming", text="Письмо")
    shapes = []
    for hx in (False, True):
        client, root, card = _card_page(user, ticket.number, hx=hx)
        fields = q1(card, data_card_fields=True)
        feed_col = q1(card, data_card_feed=True)
        assert order_of(root, fields) < order_of(root, feed_col), "лента идёт после полей"
        assert fields.inside(card) and feed_col.inside(card)
        assert not [s for s in q(card, "script") if not s.attrs.get("src")], "в карточке нет встроенных скриптов (CSP)"
        shapes.append([sorted(k for k in n.attrs if k.startswith("data-")) for n in (fields, feed_col)])
    assert shapes[0] == shapes[1], "слайдер и страница — одна разметка колонок"


# --- лента: порядок, виды, авторы, время ----------------------------------------------------------------------

def test_feed_ordered_by_time_with_authors_and_attachments_in_one_query():
    """FR-243: лента по `(at, id)`, с авторами и вложениями; `replies.feed` — не больше двух запросов при любой длине."""
    replies = _svc("replies")
    user, queue = _staff()
    other = support.make_employee()
    ticket = sd.make_ticket(queue=queue)
    now = timezone.now()
    late = sd.make_entry(ticket, "comment", author=user, text="поздний", at=now - timedelta(hours=1))
    early = sd.make_entry(ticket, "incoming", text="ранний", at=now - timedelta(hours=3))
    middle = sd.make_entry(ticket, "reply", author=other, text="средний", at=now - timedelta(hours=2),
                           send_state="queued")
    tie_a = sd.make_entry(ticket, "comment", author=user, text="один", at=now - timedelta(minutes=30))
    tie_b = sd.make_entry(ticket, "comment", author=other, text="два", at=now - timedelta(minutes=30))
    _stored_file(ticket, early, "письмо.txt")
    file_out = _stored_file(ticket, middle, "ответ.txt")
    expected = [e.pk for e in sorted([late, early, middle, tie_a, tie_b], key=lambda e: (e.at, e.pk))]
    assert expected[:3] == [early.pk, middle.pk, late.pk] and expected[3:] == [tie_a.pk, tie_b.pk]

    client, root, card = _card_page(user, ticket.number)
    shown = [int(li.attrs["data-entry-id"]) for li in q(_feed(card), "li", data_entry=True)]
    assert shown == expected, "элементы ленты — по (at, id), а не по номеру"
    assert "письмо.txt" in q1(_li(card, early.pk), "ul", data_attachments=True).text()
    reply_files = q1(_li(card, middle.pk), "ul", data_attachments=True)
    assert "ответ.txt" in reply_files.text()
    assert any(a.attrs.get("href") == f"/tickets/{ticket.number}/files/{file_out.pk}/" for a in q(reply_files, "a")), (
        "у ответа — ссылка на чистый файл")

    feed_items = replies.feed(ticket)
    assert [item.entry.pk for item in feed_items] == expected
    assert feed_items[1].author_name == other.full_name and feed_items[0].author_kind == "requester"

    # число запросов не растёт с числом элементов (решение Opus B1-2: не больше двух)
    counts = {}
    for size in (5, 50):
        sample = sd.make_ticket(queue=queue)
        _mixed_entries(sample, [user, other, support.make_employee()], size)
        with CaptureQueriesContext(connection) as ctx:
            items = replies.feed(sample)
            for item in items:
                _ = (item.author_name, item.author_kind, item.author_dismissed, item.mail_status)
                _ = list(item.entry.attachments.all())
        assert len(items) == size
        counts[size] = len(ctx)
    assert counts[5] <= 2 and counts[50] <= 2, f"лента — не больше двух запросов, получили {counts}"
    assert counts[5] == counts[50], f"число запросов не зависит от длины ленты, получили {counts}"

    # страница карточки тоже не делает запрос на каждый элемент: число запросов одно при 5 и при 50 элементах
    others = [support.make_employee() for _ in range(3)]
    small = sd.make_ticket(queue=queue)
    large = sd.make_ticket(queue=queue)
    _mixed_entries(small, others, 5)
    _mixed_entries(large, others, 50)
    assert client.get(f"/tickets/{small.number}/").status_code == 200   # прогрев: права, сессия

    def measure(number):
        calls = []

        def wrapper(execute, sql, params, many, context):
            calls.append(sql)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(wrapper):
            response = client.get(f"/tickets/{number}/")
        assert response.status_code == 200
        return len(calls)

    assert measure(large.number) - measure(small.number) < 10, "число запросов страницы растёт с длиной ленты (N+1)"


def test_feed_shows_letters_replies_comments_and_events_together():
    """FR-243: в ленте вместе письма, ответы, внутренние комментарии и события — каждый со своей зацепкой."""
    replies = _svc("replies")
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    incoming = sd.make_entry(ticket, "incoming", text="Письмо заявителя")
    reply = sd.make_entry(ticket, "reply", author=user, text="Ответ", send_state="queued")
    comment = sd.make_entry(ticket, "comment", author=user, text="Заметка")
    event = replies.add_event(ticket, "status_changed", actor=None, data={
        "before": "Новая", "after": "В работе", "before_id": 1, "after_id": 2, "reason": "manual"})
    client, root, card = _card_page(user, ticket.number)
    items = q(_feed(card), "li", data_entry=True)
    assert [(li.attrs["data-entry-id"], li.attrs["data-kind"]) for li in items] == [
        (str(incoming.pk), "incoming"), (str(reply.pk), "reply"), (str(comment.pk), "comment"),
        (str(event.pk), "event")]
    for li in items:
        assert q(li, "time", data_at=True), "у каждого элемента есть время"
    assert "ответ исполнителя" in qs1(_li(card, reply.pk), data_reply_label=True).text()
    assert "поставлен в очередь" in qs1(_li(card, reply.pk), data_send_state="queued").text()
    assert "внутренний" in qs1(_li(card, comment.pk), data_internal=True).text()
    assert _li(card, event.pk).attrs.get("data-event") == "status_changed"
    assert not qs(_li(card, incoming.pk), data_internal=True) and not qs(_li(card, reply.pk), data_internal=True)
    assert [item.entry.kind for item in replies.feed(ticket)] == ["incoming", "reply", "comment", "event"]


def test_feed_authors_staff_name_dismissed_mark_requester_and_participant_address():
    """FR-243: автор — имя сотрудника (уволенный с «(уволен)»), «заявитель <адрес>», «участник <адрес>»; у системы нет."""
    replies = _svc("replies")
    user, queue = _staff()
    active = support.make_employee(full_name="Орлов Борис Сергеевич")
    gone = support.make_employee(full_name="Громов Денис Игоревич")
    ticket = sd.make_ticket(queue=queue)
    requester_address = ticket.requester_email
    participant_address = factories.new_email("cc").lower()
    sd.make_participant(ticket, participant_address, name="Копиев Пётр")
    from_active = sd.make_entry(ticket, "comment", author=active, text="от действующего")
    from_gone = sd.make_entry(ticket, "comment", author=gone, text="от уволенного")
    from_requester = sd.make_entry(ticket, "incoming", text="от заявителя",
                                   author_email=requester_address, author_name="")
    from_participant = sd.make_entry(ticket, "incoming", text="от участника", author_email=participant_address,
                                     author_name="Копиев Пётр")
    system = replies.add_event(ticket, "status_changed", actor=None, data={
        "before": "Новая", "after": "В работе", "before_id": 1, "after_id": 2, "reason": "manual"})
    model("core.User").objects.filter(pk=gone.pk).update(state="dismissed")

    client, root, card = _card_page(user, ticket.number)
    author = q1(_li(card, from_active.pk), data_author=True)
    assert author.attrs.get("data-author-kind") == "staff"
    assert "Орлов" in author.text() and "Борис" in author.text() and "(уволен)" not in author.text()
    assert author.attrs.get("data-dismissed") != "true"
    dismissed = q1(_li(card, from_gone.pk), data_author=True)
    assert dismissed.attrs.get("data-author-kind") == "staff" and dismissed.attrs.get("data-dismissed") == "true"
    assert "Громов" in dismissed.text() and "Денис" in dismissed.text() and "(уволен)" in dismissed.text()
    requester = q1(_li(card, from_requester.pk), data_author=True)
    assert requester.attrs.get("data-author-kind") == "requester"
    assert "заявитель" in requester.text() and requester_address in requester.text()
    participant = q1(_li(card, from_participant.pk), data_author=True)
    assert participant.attrs.get("data-author-kind") == "participant"
    assert "участник" in participant.text() and participant_address in participant.text()
    assert not q(_li(card, system.pk), data_author=True), "у события системы автора нет"

    by_id = {item.entry.pk: item for item in replies.feed(ticket)}
    assert (by_id[from_active.pk].author_kind, by_id[from_active.pk].author_dismissed) == ("staff", False)
    assert (by_id[from_gone.pk].author_kind, by_id[from_gone.pk].author_dismissed) == ("staff", True)
    assert by_id[from_requester.pk].author_kind == "requester"
    assert by_id[from_requester.pk].author_address == requester_address
    assert by_id[from_participant.pk].author_kind == "participant"
    assert by_id[from_participant.pk].author_address == participant_address
    assert by_id[system.pk].author_kind == "system"


def test_feed_item_has_moscow_time_and_author():
    """FR-243, NFR-207: время элемента — по Москве `ДД.ММ.ГГГГ ЧЧ:ММ`, `data-at` — ISO со смещением +03:00; есть автор."""
    user, queue = _staff()
    author = support.make_employee(full_name="Белов Артём Олегович")
    ticket = sd.make_ticket(queue=queue)
    night = sd.make_entry(ticket, "comment", author=author, text="ночью")
    new_year = sd.make_entry(ticket, "comment", author=author, text="в новый год")
    _set_at(night, _utc("2026-03-14 21:30"))        # 15.03.2026 00:30 по Москве (день сменился)
    _set_at(new_year, _utc("2026-12-31 21:15"))     # 01.01.2027 00:15 по Москве (год сменился)
    client, root, card = _card_page(user, ticket.number)
    for entry, shown, instant in ((night, "15.03.2026 00:30", "2026-03-14 21:30"),
                                  (new_year, "01.01.2027 00:15", "2026-12-31 21:15")):
        li = _li(card, entry.pk)
        stamp = q1(li, "time", data_at=True)
        assert stamp.text() == shown, f"время элемента по Москве: ждали {shown}, получили {stamp.text()!r}"
        parsed = datetime.fromisoformat(stamp.attrs["data-at"])
        assert parsed.utcoffset() == timedelta(hours=3), "data-at — со смещением Москвы"
        assert parsed == _utc(instant)
        assert "Белов" in q1(li, data_author=True).text()


# --- события ленты по-русски ----------------------------------------------------------------------------

def _event(ticket, code, data, actor=None):
    return _svc("replies").add_event(ticket, code, actor=actor, data=data)


def _event_text(card, entry) -> str:
    li = _li(card, entry.pk)
    assert li.attrs.get("data-kind") == "event" and li.attrs.get("data-event") == entry.event
    return li.text()


def test_ticket_field_events_in_russian_for_each_kind():
    """FR-243: события полей заявки и очереди — одной строкой по-русски: «было → стало», «не назначен», «не задано»."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    ev = {
        "assign_first": _event(ticket, "assignee_changed", {"before": "", "after": "Иван Петров", "before_id": None,
                                                            "after_id": 11}),
        "assign_next": _event(ticket, "assignee_changed", {"before": "Иван Петров", "after": "Анна Орлова",
                                                           "before_id": 11, "after_id": 12}),
        "reconciled": _event(ticket, "assignee_reconciled", {"before": "Анна Орлова", "before_id": 12}),
        "transfer": _event(ticket, "transferred", {"from": "Сеть", "to": "Принтеры", "from_id": 1, "to_id": 2,
                                                   "reason_text": "Нужна замена картриджа"}),
        "transfer_plain": _event(ticket, "transferred", {"from": "Принтеры", "to": "Сеть", "from_id": 2, "to_id": 1,
                                                         "reason_text": ""}),
        "queue": _event(ticket, "queue_changed", {"from": "Сеть", "to": "Серверы", "from_id": 1, "to_id": 3}),
        "queue_unmarked": _event(ticket, "queue_changed", {"from": "Серверы", "to": "Общая", "from_id": 3,
                                                           "to_id": 4, "reason": "queue_unmarked"}),
        "category": _event(ticket, "category_changed", {"before": "Сеть", "after": "Принтеры", "before_id": 1,
                                                        "after_id": 2}),
        "priority": _event(ticket, "priority_changed", {"before": "Средняя", "after": "Высокая", "before_id": 2,
                                                        "after_id": 3}),
        "complexity": _event(ticket, "complexity_changed", {"before": "", "after": "Лёгкий", "before_id": None,
                                                            "after_id": 5}),
        "unit": _event(ticket, "client_unit_changed", {"before": "Бухгалтерия", "after": "", "before_id": 7,
                                                       "after_id": None}),
        "name": _event(ticket, "requester_name_changed", {}),
        "status": _event(ticket, "status_changed", {"before": "Новая", "after": "В работе", "before_id": 1,
                                                    "after_id": 2, "reason": "assigned"}),
        "removed": _event(ticket, "participant_removed", {"participant_id": sd.make_participant(ticket, removed_by=user).pk}),
        "continued": _event(ticket, "continued", {"number": 4321}),
    }
    client, root, card = _card_page(user, ticket.number)
    text = {key: _event_text(card, entry) for key, entry in ev.items()}

    def check(key, *words):
        for word in words:
            assert word in text[key], f"событие {key}: нет «{word}» в «{text[key]}»"

    check("assign_first", "ответственный", "не назначен", "Иван Петров", "→")
    check("assign_next", "ответственный", "Иван Петров", "Анна Орлова", "→")
    check("reconciled", "ответственный снят", "больше не участник очереди")
    check("transfer", "передана в очередь", "Сеть", "Принтеры", "причина: Нужна замена картриджа")
    check("transfer_plain", "передана в очередь", "Принтеры", "Сеть")
    assert "причина" not in text["transfer_plain"], "без текста причины части «причина» нет"
    check("queue", "очередь", "Сеть", "Серверы", "→")
    assert "очередь снята" not in text["queue"]
    check("queue_unmarked", "очередь", "Серверы", "Общая", "очередь снята")
    check("category", "категория", "Сеть", "Принтеры", "→")
    check("priority", "критичность", "Средняя", "Высокая", "→")
    check("complexity", "сложность", "не задано", "Лёгкий", "→")
    check("unit", "подразделение", "Бухгалтерия", "не задано", "→")
    check("name", "ФИО заявителя изменено")
    check("status", "статус", "Новая", "В работе", "→")
    check("removed", "участник снят")
    check("continued", "продолжение", "#4321")
    page = q1(root, data_ticket_card=True).text()
    for raw in ("before_id", "after_id", "queue_unmarked", "reason_text"):
        assert raw not in page, f"ключ или код «{raw}» в разметку не выводится"


def test_delivery_attachment_and_closing_events_in_russian():
    """FR-243: события недоставки, неотправки ответа, вложений, закрытия и открытия заново — по-русски по § 14.5."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    reply = sd.make_entry(ticket, "reply", author=user, text="Ответ", send_state="not_sent")
    ev = {
        "failed": _event(ticket, "mail_failed", {"mail_kind": "reply", "entry_id": reply.pk}),
        "closed_ticket": _event(ticket, "reply_not_sent", {"reason": "ticket_closed", "entry_id": reply.pk}),
        "quarantine": _event(ticket, "reply_not_sent", {"reason": "quarantine", "entry_id": reply.pk,
                                                        "name": "вирус.exe"}),
        "encrypted": _event(ticket, "reply_not_sent", {"reason": "encrypted", "entry_id": reply.pk,
                                                       "name": "секрет.zip"}),
        "rejected": _event(ticket, "attachment_rejected", {"name": "пароль.zip", "reason": "encrypted"}),
        "quarantined": _event(ticket, "attachment_quarantined", {"name": "заражён.docx"}),
        "closed": _event(ticket, "closed", {"status": "Решена", "status_id": 4, "resolution": "Заменили кабель"}),
        "autoclosed": _event(ticket, "autoclosed", {"status": "Закрыта автоматически", "status_id": 6, "days": 7}),
        "reopened_manual": _event(ticket, "reopened", {"via": "manual", "status": "В работе", "status_id": 2}),
        "reopened_mail": _event(ticket, "reopened", {"via": "mail", "status": "В работе", "status_id": 2}),
    }
    client, root, card = _card_page(user, ticket.number)
    text = {key: _event_text(card, entry) for key, entry in ev.items()}

    def check(key, *words):
        for word in words:
            assert word in text[key], f"событие {key}: нет «{word}» в «{text[key]}»"

    check("failed", "письмо не доставлено", "ответ исполнителя")
    check("closed_ticket", "ответ не отправлен", "заявка закрыта")
    check("quarantine", "ответ не отправлен", "вирус.exe", "в карантине")
    check("encrypted", "ответ не отправлен", "секрет.zip", "архив с паролем")
    check("rejected", "вложение", "пароль.zip", "не принято", "архив с паролем")
    check("quarantined", "вложение в карантине", "заражён.docx")
    check("closed", "заявка закрыта", "Решена", "решение", "Заменили кабель")
    check("autoclosed", "заявка закрыта автоматически", "Закрыта автоматически")
    check("reopened_manual", "заявка открыта заново", "вручную")
    check("reopened_mail", "заявка открыта заново", "письмом заявителя")
    assert "quarantine" not in " ".join(text.values()) and "ticket_closed" not in " ".join(text.values())


# --- внутренний комментарий -----------------------------------------------------------------------------

def test_internal_comment_marked_internal_in_feed():
    """FR-245: комментарий из формы карточки появляется в ленте с отметкой «внутренний»; у ответа и письма её нет."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    incoming = sd.make_entry(ticket, "incoming", text="Письмо")
    reply = sd.make_entry(ticket, "reply", author=user, text="Ответ", send_state="queued")
    client, root, card = _card_page(user, ticket.number)
    form = q1(card, "form", data_form="ticket-comment")
    assert q(form, "textarea", name="text") and q(form, "button", type="submit")
    response = client.post(f"/tickets/{ticket.number}/comment/", {"text": "Звонил, абонент недоступен"})
    assert response.status_code == 302 and response["Location"].endswith(f"/tickets/{ticket.number}/")
    comment = model("servicedesk.TicketEntry").objects.get(ticket=ticket, kind="comment")
    assert comment.text == "Звонил, абонент недоступен" and comment.author_id == user.pk
    client, root, card = _card_page(user, ticket.number)
    li = _li(card, comment.pk)
    assert li.attrs.get("data-kind") == "comment"
    assert "внутренний" in qs1(li, data_internal=True).text()
    assert "Звонил, абонент недоступен" in q1(li, data_entry_text=True).text()
    assert not qs(_li(card, incoming.pk), data_internal=True) and not qs(_li(card, reply.pk), data_internal=True)
    hx = client.post(f"/tickets/{ticket.number}/comment/", {"text": "Ещё заметка"}, **HX)
    assert hx.status_code == 200 and q1(tree(hx), data_ticket_card=True) is not None, "успех НХ — карточка"


def test_internal_comment_hidden_from_staff_without_ticket_access():
    """FR-245: сотрудник без доступа к заявке не видит ни карточку, ни комментарий и не может его добавить."""
    user, queue = _staff()
    outsider, _own_queue = _staff()
    holder = support.make_with_permissions("servicedesk.all")
    ticket = sd.make_ticket(queue=queue)
    secret = f"секретная-заметка-{secrets.token_hex(4)}"
    comment = sd.make_entry(ticket, "comment", author=user, text=secret)
    client = support.logged_in(outsider)
    for extra in ({}, HX):
        response = client.get(f"/tickets/{ticket.number}/", **extra)
        assert response.status_code == 404 and secret not in response.content.decode("utf-8")
    listing = client.get("/tickets/?preset=all")
    assert listing.status_code == 200 and secret not in listing.content.decode("utf-8")
    before = model("servicedesk.TicketEntry").objects.filter(ticket=ticket).count()
    posted = client.post(f"/tickets/{ticket.number}/comment/", {"text": "чужая заметка"})
    assert posted.status_code == 404
    assert model("servicedesk.TicketEntry").objects.filter(ticket=ticket).count() == before
    for viewer in (user, holder):
        seen, root, card = _card_page(viewer, ticket.number)
        assert secret in q1(_li(card, comment.pk), data_entry_text=True).text(), "комментарий видят те, у кого доступ"


def test_internal_comment_sends_no_mail(django_capture_on_commit_callbacks):
    """FR-245: внутренний комментарий не уходит письмом ни заявителю, ни участникам; статус и отсчёт не меняются."""
    replies = _svc("replies")
    user, queue = _staff()
    waiting = sd.make_ticket(queue=queue, kind="waiting")
    waiting.waiting_since = timezone.now() - timedelta(hours=5)
    waiting.save(update_fields=["waiting_since"])
    sd.make_participant(waiting, factories.new_email("cc"))
    MailMessage = model("mail.MailMessage")
    before = MailMessage.objects.count()
    status_before, since_before = waiting.status_id, waiting.waiting_since
    client = support.logged_in(user)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/tickets/{waiting.number}/comment/", {"text": "Внутренняя заметка по заявке"})
    assert response.status_code == 302
    with django_capture_on_commit_callbacks(execute=True):
        entry = replies.comment(waiting, text="Ещё одна заметка", actor=user)
    assert entry.kind == "comment" and entry.send_state == ""
    assert sd.ticket_mails(waiting) == [], "по заявке нет ни одного письма"
    assert MailMessage.objects.count() == before, "комментарий не создаёт писем"
    waiting.refresh_from_db()
    assert (waiting.status_id, waiting.waiting_since) == (status_before, since_before)


# --- согласие и закрытая заявка -------------------------------------------------------------------------

def test_form_ticket_card_shows_consent_mark_with_date_and_time():
    """FR-242, FR-227: у заявки с формы в карточке — «согласие на обработку ПДн» с датой и временем по Москве."""
    user, queue = _staff()
    consent = _utc("2026-05-19 21:05")           # 20.05.2026 00:05 по Москве
    form_ticket = sd.make_ticket(queue=queue, consent_at=consent, source=model("servicedesk.Source").objects.get(
        system_code="form"))
    plain = sd.make_ticket(queue=queue)
    client, root, card = _card_page(user, form_ticket.number)
    field = q1(card, data_field="consent")
    text = field.text()
    assert "согласие на обработку ПДн" in text and "20.05.2026 00:05" in text, f"отметка согласия: «{text}»"
    assert q1(card, data_card_fields=True) is not None and field.inside(q1(card, data_card_fields=True))
    client, root, card = _card_page(user, plain.number)
    assert not q(card, data_field="consent"), "у заявки без согласия элемента нет"


def test_closed_ticket_card_shows_who_closed():
    """FR-242, FR-243: у закрытой заявки — «Закрыл: Имя Фамилия» (у уволенного «(уволен)»), решение и только нужные формы."""
    user, queue = _staff()
    closer = support.make_employee(full_name="Иванов Пётр Сергеевич")
    gone = support.make_employee(full_name="Громов Денис Игоревич")
    closed = sd.make_ticket(queue=queue, kind="closed", closed_by=closer, closed_at=timezone.now(),
                            resolution="Заменили патч-корд")
    closed_by_gone = sd.make_ticket(queue=queue, kind="closed", closed_by=gone, closed_at=timezone.now(),
                                    resolution="Перезагрузили")
    no_closer = sd.make_ticket(queue=queue, kind="closed", closed_at=timezone.now())
    open_ticket = sd.make_ticket(queue=queue)
    model("core.User").objects.filter(pk=gone.pk).update(state="dismissed")

    client, root, card = _card_page(user, closed.number)
    assert card.attrs.get("data-kind") == "closed"
    field = q1(card, data_field="closed-by")
    assert "Закрыл: Пётр Иванов" in field.text(), f"«Закрыл:» и «Имя Фамилия»: «{field.text()}»"
    assert "Закрыл" in field.text()
    assert "Заменили патч-корд" in q1(card, data_field="resolution").text()
    assert q(card, "form", data_form="ticket-reopen") and q(card, "form", data_form="ticket-comment")
    for name in ("ticket-reply", "ticket-assign", "ticket-category", "ticket-fields", "ticket-status"):
        assert not q(card, "form", data_form=name), f"у закрытой заявки формы {name} нет"
    assert not q(card, "a", data_action="ticket-close") and not q(card, "a", data_action="ticket-transfer")

    client, root, card = _card_page(user, closed_by_gone.number)
    text = q1(card, data_field="closed-by").text()
    assert "Закрыл: Денис Громов" in text and "(уволен)" in text, f"уволенный закрывший: «{text}»"

    client, root, card = _card_page(user, no_closer.number)   # доп. 28 (а): закрыта без «закрыл»
    assert q1(card, data_field="closed-by").attrs.get("data-empty") == "true"

    client, root, card = _card_page(user, open_ticket.number)
    assert not q(card, data_field="closed-by") and not q(card, data_field="resolution")


# --- экранирование HTML и переводы строк -------------------------------------------------------------------

def _assert_escaped(response, *needles):
    body = response.content.decode("utf-8")
    root = tree(body)
    assert not q(root, MARKER_TAG), f"в ответе живой тег <{MARKER_TAG}>"
    assert f"<{MARKER_TAG}" not in body, f"в ответе нет необработанного <{MARKER_TAG}"
    assert "<script>alert" not in body and "<script>window" not in body
    assert not [n for n in root.walk() if "onerror" in n.attrs or "onclick" in n.attrs], "обработчики событий не живут"
    for needle in needles:
        assert needle in body, f"в ответе нет экранированного «{needle}»"


def test_html_from_incoming_letters_escaped_in_feed():
    """NFR-214: HTML из писем (текст, имя автора) в ленте экранирован и не исполняется."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    hostile = f"<script>alert(1)</script><{MARKER_TAG} onclick=x>жирный</{MARKER_TAG}><img src=x onerror=alert(2)>"
    entry = sd.make_entry(ticket, "incoming", text=hostile, author_email=ticket.requester_email,
                          author_name=f"<{MARKER_TAG}>Имя</{MARKER_TAG}>")
    client, response = _open(user, ticket.number)
    assert response.status_code == 200
    _assert_escaped(response, "&lt;script", f"&lt;{MARKER_TAG}")
    text = q1(_li(q1(tree(response), data_ticket_card=True), entry.pk), data_entry_text=True).text()
    assert "<script>alert(1)</script>" in text, "текст письма показан как текст, а не как разметка"
    hx = client.get(f"/tickets/{ticket.number}/", **HX)
    _assert_escaped(hx, "&lt;script")


def test_html_from_form_escaped_in_card():
    """NFR-214: HTML из формы (тема, ФИО заявителя, текст заявки) в полях карточки экранирован."""
    user, queue = _staff()
    subject = f"<{MARKER_TAG}>Тема</{MARKER_TAG}>"
    ticket = sd.make_ticket(queue=queue, subject=subject, requester_name=f"<{MARKER_TAG}>Имя</{MARKER_TAG}>",
                            consent_at=timezone.now())
    sd.make_entry(ticket, "incoming", text=f"<script>alert(1)</script><{MARKER_TAG}>текст</{MARKER_TAG}>",
                  author_email=ticket.requester_email, author_name=ticket.requester_name)
    client, response = _open(user, ticket.number)
    assert response.status_code == 200
    _assert_escaped(response, f"&lt;{MARKER_TAG}", "&lt;script")
    card = q1(tree(response), data_ticket_card=True)
    assert subject in q1(card, data_field="subject").text(), "тема показана буквами, а не разметкой"
    assert f"<{MARKER_TAG}>Имя</{MARKER_TAG}>" in q1(card, data_field="requester-name").text()


def test_html_in_reply_and_comment_escaped(django_capture_on_commit_callbacks):
    """NFR-214, FR-245: HTML в ответе исполнителя и во внутреннем комментарии (в том числе присланном из формы) экранирован."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    reply = sd.make_entry(ticket, "reply", author=user, send_state="queued",
                          text=f"<{MARKER_TAG}>ответ</{MARKER_TAG}><script>alert(1)</script>")
    client = support.logged_in(user)
    with django_capture_on_commit_callbacks(execute=True):
        posted = client.post(f"/tickets/{ticket.number}/comment/", {
            "text": f"<{MARKER_TAG}>заметка</{MARKER_TAG}><script>alert(3)</script>"})
    assert posted.status_code == 302
    comment = model("servicedesk.TicketEntry").objects.get(ticket=ticket, kind="comment")
    response = client.get(f"/tickets/{ticket.number}/")
    _assert_escaped(response, f"&lt;{MARKER_TAG}", "&lt;script")
    card = q1(tree(response), data_ticket_card=True)
    assert f"<{MARKER_TAG}>ответ</{MARKER_TAG}>" in q1(_li(card, reply.pk), data_entry_text=True).text()
    assert f"<{MARKER_TAG}>заметка</{MARKER_TAG}>" in q1(_li(card, comment.pk), data_entry_text=True).text()


def test_line_breaks_rendered_over_escaping():
    """NFR-214, FR-243: переводы строк текста — `<br>` (`linebreaksbr` поверх экранирования); теги внутри — текстом."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    sd.make_entry(ticket, "incoming", text=f"строка один\nстрока два\r\n<{MARKER_TAG}>строка три</{MARKER_TAG}>",
                  author_email=ticket.requester_email)
    client, response = _open(user, ticket.number)
    body = response.content.decode("utf-8")
    found = re.search(r"data-entry-text[^>]*>(.*?)</(?:div|p|span|li)>", body, re.S)
    assert found, "нет элемента [data-entry-text]"
    inner = found.group(1)
    assert re.search(r"строка один\s*<br\s*/?>\s*строка два", inner), f"перевод строки не стал <br>: {inner!r}"
    assert re.search(r"строка два\s*<br\s*/?>\s*&lt;" + MARKER_TAG, inner), f"CRLF и экранирование: {inner!r}"
    assert f"&lt;{MARKER_TAG}&gt;строка три" in inner
    assert not q(tree(body), MARKER_TAG)
    assert len(q(q1(tree(body), "ol", data_feed=True), "br")) >= 2


# --- неизменяемость ленты ---------------------------------------------------------------------------------

def test_no_routes_to_edit_or_delete_feed_items():
    """FR-246: маршрутов правки и удаления элементов ленты нет — ни в urls, ни по догадкам из § 12 (404/405)."""
    from django.urls import Resolver404, resolve

    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    reply = sd.make_entry(ticket, "reply", author=user, text="Ответ", send_state="queued")
    comment = sd.make_entry(ticket, "comment", author=user, text="Заметка")
    base = f"/tickets/{ticket.number}"
    paths = []
    for entry in (reply, comment):
        paths += [f"{base}/entries/{entry.pk}/", f"{base}/entries/{entry.pk}/edit/",
                  f"{base}/entries/{entry.pk}/delete/", f"{base}/reply/{entry.pk}/edit/",
                  f"{base}/reply/{entry.pk}/delete/", f"{base}/comment/{entry.pk}/edit/",
                  f"{base}/comment/{entry.pk}/delete/"]
    paths.append(f"{base}/entries/")
    for path in paths:
        with pytest.raises(Resolver404):
            resolve(path)
    for route, _entry in support.all_routes():
        if "tickets/" in route and re.search(r"entries|(reply|comment)/<[^>]+>/(edit|delete|update|remove)", route):
            raise AssertionError(f"в urls есть маршрут правки или удаления элементов ленты: {route}")
    client = support.logged_in(user)
    before = _snapshot([reply, comment])
    for path in paths:
        assert client.get(path).status_code in (404, 405), f"GET {path}"
        assert client.post(path, {"text": "правка"}).status_code in (404, 405), f"POST {path}"
    assert _snapshot([reply, comment]) == before
    card = q1(tree(client.get(f"{base}/")), data_ticket_card=True)
    feed = _feed(card)
    for form in q(feed, "form"):
        assert form.attrs.get("data-form") == "reply-resend", "в элементах ленты нет форм, кроме повторной отправки"
    for link in q(feed, "a"):
        target = link.attrs.get("href", "") + link.attrs.get("hx-get", "") + link.attrs.get("hx-post", "")
        assert not re.search(r"edit|delete|remove", target), f"в ленте ссылка правки или удаления: {target}"


def test_no_view_changes_entry_text(django_capture_on_commit_callbacks):
    """FR-246: ни одно действие карточки не меняет текст, автора и время существующих элементов ленты."""
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    entries = [
        sd.make_entry(ticket, "incoming", text="Письмо заявителя"),
        sd.make_entry(ticket, "reply", author=user, text="Ответ", send_state="queued"),
        sd.make_entry(ticket, "comment", author=user, text="Заметка"),
        _event(ticket, "status_changed", {"before": "Новая", "after": "В работе", "before_id": 1, "after_id": 2,
                                          "reason": "manual"}),
    ]
    before = _snapshot(entries)
    Status, Priority = model("servicedesk.Status"), model("servicedesk.Priority")
    base = f"/tickets/{ticket.number}"
    steps = [
        ("take", {}),
        ("status", {"status": Status.objects.get(kind="in_progress", is_default=True).pk}),
        ("fields", {"priority": Priority.objects.get(name_key="высокая").pk}),
        ("comment", {"text": "Новая заметка"}),
        ("reply", {"text": "Новый ответ"}),
        ("close", {"status": Status.objects.get(kind="closed", is_default=True).pk, "resolution": "Готово"}),
        ("reopen", {}),
    ]
    client = support.logged_in(user)
    for action, data in steps:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(f"{base}/{action}/", data)
        assert response.status_code in (200, 302), f"{action}: {response.status_code}"
    assert _snapshot(entries) == before, "действия карточки изменили существующие элементы ленты"
    assert model("servicedesk.TicketEntry").objects.filter(ticket=ticket).count() > len(entries)


def test_feed_service_only_appends():
    """FR-246: у сервиса ленты нет функций изменения и удаления; добавление не трогает прежние элементы."""
    import apps.servicedesk.services.replies as replies

    forbidden = [n for n in dir(replies) if re.match(r"(update|edit|delete|remove)_", n)]
    assert forbidden == [], f"в replies есть функции изменения ленты: {forbidden}"
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    old = [sd.make_entry(ticket, "incoming", text="Письмо"), sd.make_entry(ticket, "comment", author=user, text="Заметка")]
    before = _snapshot(old)
    count = model("servicedesk.TicketEntry").objects.filter(ticket=ticket).count()
    event = replies.add_event(ticket, "requester_name_changed", actor=user)
    comment = replies.comment(ticket, text="Ещё заметка", actor=user)
    assert event.kind == "event" and event.event == "requester_name_changed" and event.data == {}
    assert event.author_id == user.pk and comment.kind == "comment" and comment.text == "Ещё заметка"
    assert model("servicedesk.TicketEntry").objects.filter(ticket=ticket).count() == count + 2
    assert _snapshot(old) == before
    assert [item.entry.pk for item in replies.feed(ticket)] == [e.pk for e in old] + [event.pk, comment.pk]


# --- последнее сообщение --------------------------------------------------------------------------------------

def _last(ticket):
    ticket.refresh_from_db()
    return ticket.last_message_from, ticket.last_message_at


def test_last_message_updated_only_by_letters_and_replies(django_capture_on_commit_callbacks):
    """FR-248: `last_message_at` и `last_message_from` обновляют письмо заявителя, письмо участника и ответ исполнителя."""
    tickets, replies = _svc("tickets"), _svc("replies")
    user, queue = _staff()
    ticket = sd.make_ticket(queue=queue)
    participant = factories.new_email("cc")
    sd.make_participant(ticket, participant)
    sd.backdate(ticket, "last_message_at", days=3)
    started = timezone.now()
    old_value = ticket.last_message_at
    assert old_value < started - timedelta(days=2)

    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Письмо заявителя")
    sender, moment = _last(ticket)
    assert sender == "requester" and started <= moment <= timezone.now()

    sd.backdate(ticket, "last_message_at", days=2)
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(ticket, author_email=participant, text="Письмо участника")
    sender, moment = _last(ticket)
    assert sender == "requester", "письмо участника — тоже «заявитель»"
    assert started <= moment <= timezone.now()

    sd.backdate(ticket, "last_message_at", days=2)
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        replies.reply(ticket, text="Ответ исполнителя", actor=user)
    sender, moment = _last(ticket)
    assert sender == "staff" and started <= moment <= timezone.now()


def test_last_message_from_requester_or_staff_with_date():
    """FR-248: в списке у заявки — дата последнего сообщения (по Москве) и от кого: «заявитель» или «исполнитель»."""
    Ticket = model("servicedesk.Ticket")
    assert (Ticket.MessageFrom.REQUESTER, Ticket.MessageFrom.STAFF) == ("requester", "staff")
    user, queue = _staff()
    from_requester = sd.make_ticket(queue=queue, last_message_from="requester")
    from_staff = sd.make_ticket(queue=queue, last_message_from="staff")
    Ticket.objects.filter(pk=from_requester.pk).update(last_message_at=_utc("2026-07-01 22:30"))
    Ticket.objects.filter(pk=from_staff.pk).update(last_message_at=_utc("2026-12-31 21:15"))
    client = support.logged_in(user)
    response = client.get("/tickets/?preset=all")
    assert response.status_code == 200
    root = tree(response)
    for ticket, label, shown in ((from_requester, "заявитель", "02.07.2026 01:30"),
                                 (from_staff, "исполнитель", "01.01.2027 00:15")):
        row = q1(root, "tr", data_ticket=str(ticket.number))
        cell = q1(row, data_cell="last-message")
        assert q1(cell, "time", data_at=True).text() == shown, f"дата последнего сообщения по Москве: {shown}"
        mark = qs1(cell, data_last_from=True)
        assert mark.attrs["data-last-from"] == ticket.last_message_from and label in mark.text()


def test_comment_and_event_do_not_change_last_message(django_capture_on_commit_callbacks):
    """FR-248: внутренний комментарий и событие ленты не входят в «последнее сообщение»."""
    replies = _svc("replies")
    user, queue = _staff()
    marks = {}
    for sender in ("requester", "staff"):
        ticket = sd.make_ticket(queue=queue, last_message_from=sender)
        sd.backdate(ticket, "last_message_at", days=5)
        marks[sender] = (ticket, _last(ticket))
    client = support.logged_in(user)
    for sender, (ticket, fixed) in marks.items():
        with django_capture_on_commit_callbacks(execute=True):
            replies.comment(ticket, text="Заметка", actor=user)
            replies.add_event(ticket, "requester_name_changed", actor=user)
            response = client.post(f"/tickets/{ticket.number}/comment/", {"text": "Заметка из формы"})
        assert response.status_code == 302
        assert _last(ticket) == fixed, f"({sender}) комментарий и событие поменяли последнее сообщение"
        assert model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind__in=["comment", "event"]).count() >= 3
