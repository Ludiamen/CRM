"""T-6114: связь записей списков с заявками — раздел «Записи списков» в карточке заявки, подбор записи, привязка и
отвязка, «Связанные заявки» в карточке записи, обезличенная заявка, удаление записи, выключенный `servicedesk`
(FR-514, FR-523, FR-524, FR-528). Сценарии 2 и 11 спеки.

Что проверяется: запись точки `ticket_card_parts` (`apps.lists.ticket_parts`); `render(request, ref)` и разметка раздела
(CONTRACT-006, 11.8); `/lists/ticket-pick/`, POST `/lists/ticket-links/` и `/lists/ticket-links/<id>/delete/`
(10.2); строка «Связанные заявки» в карточке записи (11.5); ответы «нет — 404 как у несуществующего» (решение 31 задач).
Код среза на уровне модуля не импортируется (CONTRACT-006, шапка): имена берутся внутри тестов и через
`support.model`; разбор разметки — помощник только этого файла (образец — test_kb_tickets.py).
"""
from html.parser import HTMLParser

import pytest

from tests import factories, support
from tests import support_lists as lists
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

# --- разбор разметки (помощник только этого файла) -------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
ARCHIVED = "в архиве"
RECORD_ARCHIVED = "Запись в архиве"


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
    """Потомки `scope` по тегу и атрибутам; имя атрибута с дефисом — через `_` (`data_action="x"`)."""
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}

    def match(node) -> bool:
        if tag is not None and node.tag != tag:
            return False
        for name, expected in wanted.items():
            if name not in node.attrs:
                return False
            if expected is not True and node.attrs[name] != expected:
                return False
        return True

    return [node for node in scope.walk() if match(node)]


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста ------------------------------------------------------------------------------------------

def _ticket(*, subject: str | None = None, **over):
    """Очередь и видимая её участникам заявка."""
    queue = sd.make_queue()
    over = dict(over)
    if subject is not None:
        over["subject"] = subject
    return queue, sd.make_ticket(queue=queue, **over)


def _reader(queue, *lsts, **extra):
    """Сотрудник, который читает все `lsts` (одна роль) и состоит в узле очереди: видит её заявки."""
    role = factories.make_role()
    for lst in lsts:
        lists.grant_list(lst, role, "read")
    user = support.make_employee(roles=[role], **extra)
    org.make_member(user, queue.unit)
    return lists.Session(user, support.logged_in(user))


def _member_without_lists(queue, **extra):
    """Сотрудник очереди (видит заявки), которому не открыт ни один список."""
    user = support.make_employee(**extra)
    org.make_member(user, queue.unit)
    return lists.Session(user, support.logged_in(user))


def _link(record, ticket, user=None):
    """Строка `TicketLink` прямой записью (`linked_by` — модель плана; по умолчанию автор записи)."""
    return model("lists.TicketLink").objects.create(
        record=record, ticket_number=ticket.number, linked_by=user or record.created_by)


def _links(**filters):
    return model("lists.TicketLink").objects.filter(**filters)


def _page(client, number):
    response = client.get(f"/tickets/{number}/")
    assert response.status_code == 200, f"карточка заявки #{number}: {response.status_code}"
    return tree(response)


def _part(root):
    """Оболочка раздела по ключу записи или `None`."""
    found = q(root, "div", data_card_part="lists-records")
    assert len(found) <= 1, f"оболочек lists-records: {len(found)}"
    return found[0] if found else None


def _section_rows(scope) -> dict:
    """Строки раздела: `{id связи: li}`."""
    section = q1(scope, data_lists_ticket_section=True)
    return {int(li.attrs["data-ticket-link-id"]): li for li in q(section, "li", data_ticket_link_id=True)}


def _pick(client, ticket, text):
    response = client.get("/lists/ticket-pick/", {"ticket": ticket.number, "q": text})
    assert response.status_code == 200, f"подбор «{text}»: {response.status_code}"
    return [int(li.attrs["data-pick-id"]) for li in q(tree(response), "li", data_pick_id=True)]


def _post_link(client, ticket, record, *, number=None):
    return client.post("/lists/ticket-links/",
                       {"ticket": number if number is not None else ticket.number, "record": record.pk}, **HX)


def _post_unlink(client, link):
    return client.post(f"/lists/ticket-links/{link.pk}/delete/", **HX)


def _ref(ticket):
    from apps.core.extensions import TicketRef

    return TicketRef(number=ticket.number, closed=ticket.kind == "closed", has_resolution=bool(ticket.resolution))


def _render(user, ticket):
    """`ticket_parts.render(request, ref)` напрямую, как зовёт её карточка."""
    from django.test import RequestFactory

    from apps.lists import ticket_parts

    request = RequestFactory().get(f"/tickets/{ticket.number}/")
    request.user = user
    request.session = {}  # контекстный процессор оболочки читает сессию (решение Opus Р2)
    return ticket_parts.render(request, _ref(ticket))


def _card(client, lst, record):
    response = client.get(f"/lists/{lst.pk}/{record.number}/")
    assert response.status_code == 200, f"карточка записи: {response.status_code}"
    return tree(response)


def _related(root) -> dict:
    """Строки «Связанные заявки» карточки записи: `{номер заявки: li}`."""
    found = q(root, data_lists_related_tickets=True)
    if not found:
        return {}
    return {int(li.attrs["data-ticket-number"]): li for li in q(found[0], "li", data_ticket_number=True)}


# --- запись точки и вывод раздела --------------------------------------------------------------------------

def test_ticket_card_part_registered_as_lists_records_section_20_after_knowledge_parts():
    """FR-528: в `ticket_card_parts` зарегистрирована функция модуля `apps.lists.ticket_parts`, отдающая ровно одну
    часть `TicketCardPart("lists-records", "section", 20, render)`; она стоит после записи `knowledge`."""
    from apps.core import extensions

    registered = extensions.registered("ticket_card_parts")
    modules = [getattr(func, "__module__", "") for func in registered]
    mine = [i for i, name in enumerate(modules) if name.startswith("apps.lists")]
    assert len(mine) == 1, f"записей lists в ticket_card_parts: {modules}"
    assert modules[mine[0]] == "apps.lists.ticket_parts"
    parts = list(registered[mine[0]]())
    assert len(parts) == 1
    part = parts[0]
    assert (part.key, part.kind, part.order) == ("lists-records", "section", 20)
    assert callable(part.render)
    knowledge = [i for i, name in enumerate(modules) if name.startswith("apps.knowledge")]
    assert knowledge and max(knowledge) < mine[0], f"lists должен идти после knowledge: {modules}"
    knowledge_orders = [p.order for i in knowledge for p in registered[i]()]
    assert knowledge_orders and max(knowledge_orders) < 20


def test_ticket_section_shown_with_link_button_to_viewer_who_sees_ticket_and_reads_a_list():
    """FR-528: смотрящий видит заявку и читает список — в карточке есть оболочка `lists-records` с разделом «Записи
    списков», полем поиска и кнопкой «Привязать запись», даже если связей нет; у строки — кнопка «Отвязать»."""
    queue, ticket = _ticket()
    empty_ticket = sd.make_ticket(queue=queue)
    lst = lists.make_list("Оборудование Т")
    record = lists.make_record(lst, "Ноутбук Dell")
    link = _link(record, ticket)
    viewer = _reader(queue, lst)

    root = _page(viewer.client, ticket.number)
    wrapper = _part(root)
    assert wrapper is not None, "раздела «Записи списков» нет"
    section = q1(wrapper, data_lists_ticket_section=True)
    assert "Записи списков" in wrapper.text()
    assert q1(section, "input", data_lists_picker="ticket") is not None
    assert q1(section, "button", data_action="ticket-link") is not None
    assert "Привязать запись" in section.text()
    rows = _section_rows(wrapper)
    assert list(rows) == [link.pk]
    assert len(q(rows[link.pk], "button", data_action="ticket-unlink")) == 1

    root = _page(viewer.client, empty_ticket.number)
    wrapper = _part(root)
    assert wrapper is not None, "без связей раздел всё равно есть"
    assert _section_rows(wrapper) == {}
    assert q1(wrapper, "input", data_lists_picker="ticket") is not None

    assert isinstance(_render(viewer.user, ticket), str) and _render(viewer.user, ticket).strip()


def test_ticket_section_render_returns_none_when_viewer_reads_no_list():
    """FR-528, FR-514: заявку видит, но не читает ни одного списка — `render` отдаёт `None`, раздела и слов «Записи
    списков» в карточке нет; при этом у читающего другого сотрудника раздел есть."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    lists.make_record(lst, "Запись")
    outsider = _member_without_lists(queue)

    assert _render(outsider.user, ticket) is None
    root = _page(outsider.client, ticket.number)
    assert _part(root) is None
    assert q(root, data_lists_ticket_section=True) == []
    assert "Записи списков" not in root.text()

    reader = _reader(queue, lst)
    assert _part(_page(reader.client, ticket.number)) is not None


def test_ticket_section_render_returns_none_for_invisible_ticket():
    """FR-528, FR-514: заявку не видит (чужая очередь или нет такой) — `render` отдаёт `None`, даже если сотрудник
    читает список; страница заявки — 404."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    reader = lists.as_reader(lst)  # читает список, но не состоит в узле очереди

    assert _render(reader.user, ticket) is None
    ghost = type("Ghost", (), {"number": 987654, "kind": "new", "resolution": ""})()
    assert _render(reader.user, ghost) is None
    assert reader.client.get(f"/tickets/{ticket.number}/").status_code == 404


def test_ticket_section_row_shows_name_dash_list_linking_to_record_card():
    """FR-528: строка раздела — `li[data-ticket-link-id]` со ссылкой на карточку записи и текстом «Название — Список»;
    у записи не в архиве пометки «в архиве» нет."""
    queue, ticket = _ticket()
    lst = lists.make_list("Лицензии Т")
    record = lists.make_record(lst, "Office 2021")
    link = _link(record, ticket)
    viewer = _reader(queue, lst)

    row = _section_rows(_page(viewer.client, ticket.number))[link.pk]
    anchors = [a for a in q(row, "a")
               if a.attrs.get("href", "").rstrip("/").endswith(f"/lists/{lst.pk}/{record.number}")]
    assert anchors, "в строке нет ссылки на карточку записи"
    assert "Office 2021 — Лицензии Т" in row.text()
    assert q(row, data_lists_archived=True) == []


def test_ticket_section_hides_linked_record_of_unreadable_list():
    """FR-528, FR-514: связанная запись списка, которого смотрящий не читает, ему не показывается: ни строки, ни
    названия записи, ни названия списка; запись читаемого списка на месте."""
    queue, ticket = _ticket()
    readable = lists.make_list("Читаемый список")
    closed_list = lists.make_list("Закрытый список")
    visible = lists.make_record(readable, "Видимая запись")
    hidden = lists.make_record(closed_list, "Скрытая запись")
    visible_link = _link(visible, ticket)
    hidden_link = _link(hidden, ticket)
    viewer = _reader(queue, readable)

    response = viewer.client.get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    rows = _section_rows(tree(response))
    assert list(rows) == [visible_link.pk]
    assert hidden_link.pk not in rows
    body = response.content.decode("utf-8")
    assert "Скрытая запись" not in body and "Закрытый список" not in body


def test_ticket_section_marks_archived_linked_record_in_archive():
    """FR-523, FR-528: запись в архиве остаётся в заявке со ссылкой и пометкой `[data-lists-archived]` «в архиве»;
    у записи не в архиве пометки нет."""
    queue, ticket = _ticket()
    lst = lists.make_list("Расходники")
    live = lists.make_record(lst, "Картридж живой")
    old = lists.make_record(lst, "Картридж старый", archived=True)
    live_link = _link(live, ticket)
    old_link = _link(old, ticket)
    viewer = _reader(queue, lst)

    rows = _section_rows(_page(viewer.client, ticket.number))
    assert set(rows) == {live_link.pk, old_link.pk}
    mark = q1(rows[old_link.pk], data_lists_archived=True)
    assert ARCHIVED in mark.text()
    assert q1(rows[old_link.pk], "a").attrs["href"].rstrip("/").endswith(f"/lists/{lst.pk}/{old.number}")
    assert q(rows[live_link.pk], data_lists_archived=True) == []


# --- подбор записи -----------------------------------------------------------------------------------------

def test_ticket_pick_finds_unarchived_records_of_readable_lists_by_word_prefix_of_name_and_text_fields():
    """FR-528: подбор ищет записи не в архиве читаемых списков по началу слова названия и видимого текстового поля
    (префиксный запрос по вектору записи); запись без совпадения не выдаётся; `tickets.pick` возвращает те же записи."""
    queue, ticket = _ticket()
    lst = lists.make_list("Расходники")
    note = lists.add_field(lst, "text", "Заметка")
    owner = support.make_employee()
    by_name = lists.make_record(lst, "Принтер лазерный", {note.code: "Стоит в бухгалтерии"}, created_by=owner)
    by_text = lists.make_record(lst, "Расходник", {note.code: "Картридж синий"}, created_by=owner)
    other = lists.make_record(lst, "Монитор", {note.code: "Склад"}, created_by=owner)
    viewer = _reader(queue, lst)

    assert _pick(viewer.client, ticket, "принт") == [by_name.pk]
    assert _pick(viewer.client, ticket, "картр") == [by_text.pk]
    assert other.pk not in _pick(viewer.client, ticket, "принт") + _pick(viewer.client, ticket, "картр")

    from apps.lists.services import tickets

    assert [r.pk for r in tickets.pick(viewer.user, ticket.number, "принт")] == [by_name.pk]


def test_ticket_pick_finds_record_by_number_and_by_whole_unique_value():
    """FR-528: запись находится по её номеру и по запросу целиком, равному значению уникального поля (без учёта
    регистра и пробелов по краям); значение скрытого уникального поля записи не находит (V15)."""
    queue, ticket = _ticket()
    lst = lists.make_list("Техника")
    serial = lists.add_field(lst, "string", "Серийный номер", unique=True)
    service_serial = lists.add_field(lst, "string", "Служебный номер", unique=True, hidden=True)
    owner = support.make_employee()
    first = lists.make_record(lst, "Первая", {serial.code: "SN5CD1234XYZ"}, created_by=owner)
    second = lists.make_record(lst, "Вторая", {}, created_by=owner)
    third = lists.make_record(lst, "Третья", {service_serial.code: "HID7788QWE"}, created_by=owner)
    viewer = _reader(queue, lst)
    assert (first.number, second.number, third.number) == (1, 2, 3)

    assert _pick(viewer.client, ticket, "2") == [second.pk]
    assert _pick(viewer.client, ticket, "  sn5cd1234xyz ") == [first.pk]
    assert _pick(viewer.client, ticket, "SN5CD1234XYZ") == [first.pk]
    assert _pick(viewer.client, ticket, "HID7788QWE") == []

    from apps.lists.services import tickets

    assert [r.pk for r in tickets.pick(viewer.user, ticket.number, "sn5cd1234xyz")] == [first.pk]
    assert tickets.pick(viewer.user, ticket.number, "hid7788qwe") == []


def test_ticket_pick_returns_at_most_ten_rows():
    """FR-528: из двенадцати подходящих записей подбор отдаёт не больше десяти `li[data-pick-id]`."""
    queue, ticket = _ticket()
    lst = lists.make_list("Принтеры")
    owner = support.make_employee()
    for number in range(12):
        lists.make_record(lst, f"Принтер модель {number}", created_by=owner)
    viewer = _reader(queue, lst)

    assert len(_pick(viewer.client, ticket, "принтер")) == 10

    from apps.lists.services import tickets

    assert len(tickets.pick(viewer.user, ticket.number, "принтер")) == 10


def test_ticket_pick_excludes_archived_records_and_records_of_unreadable_lists():
    """FR-523, FR-528, FR-514: запись в архиве и запись списка, которого смотрящий не читает, не выдаются; запись
    читаемого списка не в архиве — выдаётся."""
    queue, ticket = _ticket()
    readable = lists.make_list("Читаемый")
    closed_list = lists.make_list("Закрытый")
    owner = support.make_employee()
    live = lists.make_record(readable, "Сканер рабочий", created_by=owner)
    lists.make_record(readable, "Сканер архивный", archived=True, created_by=owner)
    lists.make_record(closed_list, "Сканер чужой", created_by=owner)
    viewer = _reader(queue, readable)

    assert _pick(viewer.client, ticket, "сканер") == [live.pk]

    from apps.lists.services import tickets

    assert [r.pk for r in tickets.pick(viewer.user, ticket.number, "сканер")] == [live.pk]


def test_ticket_pick_for_invisible_ticket_returns_404():
    """FR-528, FR-514: заявку не видит или её нет — 404, как у несуществующей; видящий заявку получает 200."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    lists.make_record(lst, "Принтер")
    stranger = lists.as_reader(lst)
    viewer = _reader(queue, lst)

    assert stranger.client.get("/lists/ticket-pick/", {"ticket": ticket.number, "q": "принтер"}).status_code == 404
    assert stranger.client.get("/lists/ticket-pick/", {"ticket": 987654, "q": "принтер"}).status_code == 404
    assert viewer.client.get("/lists/ticket-pick/", {"ticket": ticket.number, "q": "принтер"}).status_code == 200


# --- привязка и отвязка -------------------------------------------------------------------------------------

def test_link_post_creates_link_with_who_and_when_and_leaves_record_unchanged(clock):
    """FR-528: POST `/lists/ticket-links/` создаёт одну связь «запись — заявка» с автором (`linked_by`) и временем
    (`linked_at`); сама запись (поля, версия, история) не меняется."""
    clock.set(lists.moscow(2026, 10, 25, 14, 30))
    queue, ticket = _ticket()
    lst = lists.make_list("Оборудование Т")
    record = lists.make_record(lst, "Ноутбук Dell")
    viewer = _reader(queue, lst, full_name="Привязкин Пётр")
    Record, Change = model("lists.Record"), model("lists.Change")
    before = Record.objects.filter(pk=record.pk).values().get()
    changes = Change.objects.filter(record=record).count()

    clock.set(lists.moscow(2026, 10, 25, 15, 45))
    assert _post_link(viewer.client, ticket, record).status_code == 200

    link = _links().get()
    assert (link.record_id, link.ticket_number) == (record.pk, ticket.number)
    assert link.linked_by == viewer.user
    assert link.linked_at == lists.moscow(2026, 10, 25, 15, 45)
    assert Record.objects.filter(pk=record.pk).values().get() == before
    assert Change.objects.filter(record=record).count() == changes


def test_link_post_returns_whole_section_fragment_for_htmx():
    """FR-528: ответ на привязку — 200 и фрагмент раздела целиком (без `<html>`): в нём и прежняя, и новая связь."""
    queue, ticket = _ticket()
    lst = lists.make_list("Оборудование Т")
    old = lists.make_record(lst, "Старая запись")
    new = lists.make_record(lst, "Новая запись")
    old_link = _link(old, ticket)
    viewer = _reader(queue, lst)

    response = _post_link(viewer.client, ticket, new)
    assert response.status_code == 200
    assert "<html" not in response.content.decode("utf-8").lower()
    root = tree(response)
    new_link = _links(record=new).get()
    rows = _section_rows(root)
    assert set(rows) == {old_link.pk, new_link.pk}
    new_row = rows[new_link.pk]
    assert any(a.attrs.get("href", "").rstrip("/").endswith(f"/lists/{lst.pk}/{new.number}") for a in q(new_row, "a"))
    assert "Новая запись — Оборудование Т" in new_row.text()
    assert q1(root, "input", data_lists_picker="ticket") is not None


def test_link_post_missing_record_and_unreadable_list_record_give_same_404():
    """FR-528, FR-514: записи нет и запись списка, которого смотрящий не читает, — один и тот же ответ 404 без данных
    записи; связей не создаётся."""
    queue, ticket = _ticket()
    readable = lists.make_list("Читаемый")
    closed_list = lists.make_list("Закрытый список")
    foreign = lists.make_record(closed_list, "Чужая запись")
    viewer = _reader(queue, readable)
    ghost = type("Ghost", (), {"pk": 987654})()

    missing = _post_link(viewer.client, ticket, ghost)
    hidden = _post_link(viewer.client, ticket, foreign)
    assert missing.status_code == hidden.status_code == 404
    body = hidden.content.decode("utf-8")
    assert "Чужая запись" not in body and "Закрытый список" not in body
    assert _links().count() == 0


def test_link_post_for_invisible_ticket_returns_404_like_missing_ticket():
    """FR-528, FR-514: заявку не видит — 404, как у несуществующей заявки; связь не создаётся."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    record = lists.make_record(lst, "Запись")
    stranger = lists.as_reader(lst)  # читает список, заявку не видит

    hidden = _post_link(stranger.client, ticket, record)
    missing = _post_link(stranger.client, ticket, record, number=987654)
    assert hidden.status_code == missing.status_code == 404
    assert _links().count() == 0


def test_link_post_for_archived_record_refused_with_record_in_archive_text():
    """FR-523, FR-528: запись в архиве не привязывается — 200 с фрагментом раздела и `[role=alert]` с кодом
    `record_archived` («Запись в архиве»); связи нет."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    record = lists.make_record(lst, "Старая запись", archived=True)
    viewer = _reader(queue, lst)

    response = _post_link(viewer.client, ticket, record)
    assert response.status_code == 200
    root = tree(response)
    alert = q1(root, role="alert", data_code="record_archived")
    assert RECORD_ARCHIVED in alert.text()
    assert q1(root, data_lists_ticket_section=True) is not None
    assert _links().count() == 0


def test_link_post_repeat_keeps_single_link_row():
    """FR-528: повторная привязка той же записи к той же заявке — без ошибки и без второй строки."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    record = lists.make_record(lst, "Запись")
    viewer = _reader(queue, lst)

    first = _post_link(viewer.client, ticket, record)
    again = _post_link(viewer.client, ticket, record)
    assert first.status_code == again.status_code == 200
    assert _links(record=record, ticket_number=ticket.number).count() == 1
    assert len(_section_rows(tree(again))) == 1


def test_unlink_post_removes_link_and_returns_section_fragment():
    """FR-528: POST `/lists/ticket-links/<id>/delete/` удаляет связь и отдаёт фрагмент раздела без этой строки;
    другая связь и сама запись остаются; повтор — 404."""
    queue, ticket = _ticket()
    lst = lists.make_list("Оборудование Т")
    gone = lists.make_record(lst, "Отвязываемая")
    kept = lists.make_record(lst, "Остающаяся")
    gone_link = _link(gone, ticket)
    kept_link = _link(kept, ticket)
    viewer = _reader(queue, lst)

    response = _post_unlink(viewer.client, gone_link)
    assert response.status_code == 200
    assert "<html" not in response.content.decode("utf-8").lower()
    assert list(_section_rows(tree(response))) == [kept_link.pk]
    assert not _links(pk=gone_link.pk).exists()
    assert _links(pk=kept_link.pk).exists()
    assert model("lists.Record").objects.filter(pk=gone.pk).exists()
    assert _post_unlink(viewer.client, gone_link).status_code == 404


def test_unlink_post_returns_404_without_ticket_visibility_or_list_read_right():
    """FR-528, FR-514: отвязка без видимости заявки и без чтения списка записи — 404; несуществующая связь — 404;
    связь остаётся."""
    queue, ticket = _ticket()
    lst = lists.make_list("Список записи")
    other = lists.make_list("Другой список")
    record = lists.make_record(lst, "Запись")
    link = _link(record, ticket)
    no_ticket = lists.as_reader(lst)  # список читает, заявку не видит
    no_list = _reader(queue, other)  # заявку видит, список записи не читает
    ghost = type("Ghost", (), {"pk": 987654})()

    assert _post_unlink(no_ticket.client, link).status_code == 404
    assert _post_unlink(no_list.client, link).status_code == 404
    assert _post_unlink(no_list.client, ghost).status_code == 404
    assert _links(pk=link.pk).exists()


def test_link_and_unlink_write_no_audit_record():
    """FR-528: привязка и отвязка в журнал портала не пишутся."""
    queue, ticket = _ticket()
    lst = lists.make_list()
    record = lists.make_record(lst, "Запись")
    viewer = _reader(queue, lst)
    before = support.audit_actions()

    assert _post_link(viewer.client, ticket, record).status_code == 200
    link = _links().get()
    assert _post_unlink(viewer.client, link).status_code == 200

    assert support.audit_actions() == before
    assert not [action for action in support.audit_actions() if action.startswith("lists.")]


# --- карточка записи: «Связанные заявки» ---------------------------------------------------------------------

def test_record_card_related_tickets_show_number_subject_state_only_for_visible_tickets():
    """FR-528, FR-514: «Связанные заявки» в карточке записи — «#N Тема, состояние» по заявкам, которые видит смотрящий;
    невидимая заявка пропускается, её тема в разметке не появляется; `tickets.related` отдаёт те же заявки."""
    queue, mine = _ticket(subject="Не печатает принтер")
    foreign = sd.make_ticket(queue=sd.make_queue(), subject="Чужая секретная тема")
    lst = lists.make_list("Оборудование Т")
    record = lists.make_record(lst, "Принтер HP")
    _link(record, mine)
    _link(record, foreign)
    viewer = _reader(queue, lst)

    response = viewer.client.get(f"/lists/{lst.pk}/{record.number}/")
    assert response.status_code == 200
    rows = _related(tree(response))
    assert list(rows) == [mine.number]
    assert f"#{mine.number} Не печатает принтер, {mine.status.name}" in rows[mine.number].text()
    assert "Чужая секретная тема" not in response.content.decode("utf-8")

    from apps.lists.services import tickets

    assert [brief.number for brief in tickets.related(viewer.user, record)] == [mine.number]


def test_record_card_keeps_anonymized_ticket_with_number_and_subject():
    """FR-528: обезличенная по сроку заявка остаётся в «Связанных заявках» — номер и тема на месте, связь не удалена."""
    from apps.servicedesk.services.retention import ANONYMIZED
    from django.utils import timezone

    queue, ticket = _ticket(subject="Старая заявка про сканер", kind="closed", resolution="Починили")
    model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(
        requester_email=ANONYMIZED, requester_name=ANONYMIZED, requester=None, anonymized_at=timezone.now())
    lst = lists.make_list("Оборудование Т")
    record = lists.make_record(lst, "Сканер")
    _link(record, ticket)
    viewer = _reader(queue, lst)

    row = _related(_card(viewer.client, lst, record))[ticket.number]
    assert f"#{ticket.number} Старая заявка про сканер" in row.text()
    assert _links(record=record, ticket_number=ticket.number).count() == 1


def test_purge_record_deletes_ticket_links_and_ticket_section_no_longer_shows_it(django_capture_on_commit_callbacks):
    """FR-524, FR-528: «Удалить навсегда» записи в архиве удаляет её связи с заявками; раздел заявки больше не
    показывает строку, у читающего список раздел остаётся без строк."""
    queue, ticket = _ticket()
    lst = lists.make_list("Оборудование Т")
    record = lists.make_record(lst, "Списанный ноутбук", archived=True)
    survivor = lists.make_record(lst, "Другой ноутбук")
    _link(record, ticket)
    survivor_link = _link(survivor, ticket)
    viewer = _reader(queue, lst)
    manager = lists.as_manager()
    assert len(_section_rows(_page(viewer.client, ticket.number))) == 2

    with django_capture_on_commit_callbacks(execute=True):
        response = manager.client.post(f"/lists/{lst.pk}/{record.number}/purge/")
    assert response.status_code == 302
    assert not model("lists.Record").objects.filter(pk=record.pk).exists()
    assert not _links(record_id=record.pk).exists()
    assert _links(ticket_number=ticket.number).count() == 1

    rows = _section_rows(_page(viewer.client, ticket.number))
    assert list(rows) == [survivor_link.pk]


# --- без servicedesk -----------------------------------------------------------------------------------------

def test_without_servicedesk_record_card_has_no_related_tickets_and_link_urls_return_404(monkeypatch):
    """FR-528: без `apps.servicedesk` в карточке записи нет раздела «Связанные заявки», `render` отдаёт `None`,
    `tickets.related` — пустой список, а `/lists/ticket-pick/`, `/lists/ticket-links/` и отвязка отвечают 404."""
    queue, ticket = _ticket(subject="Заявка про ноутбук")
    lst = lists.make_list("Оборудование Т")
    record = lists.make_record(lst, "Ноутбук")
    link = _link(record, ticket)
    viewer = _reader(queue, lst)
    with_module = _card(viewer.client, lst, record)
    assert list(_related(with_module)) == [ticket.number]

    lists.without_app(monkeypatch, "apps.servicedesk")

    response = viewer.client.get(f"/lists/{lst.pk}/{record.number}/")
    assert response.status_code == 200
    root = tree(response)
    assert q(root, data_lists_related_tickets=True) == []
    assert "Связанные заявки" not in response.content.decode("utf-8")
    assert _render(viewer.user, ticket) is None
    from apps.lists.services import tickets

    assert tickets.related(viewer.user, record) == []
    assert viewer.client.get("/lists/ticket-pick/", {"ticket": ticket.number, "q": "ноут"}).status_code == 404
    assert _post_link(viewer.client, ticket, record).status_code == 404
    assert _post_unlink(viewer.client, link).status_code == 404
    assert _links(pk=link.pk).exists()
