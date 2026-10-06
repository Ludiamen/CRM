"""T-3124: список заявок — колонки, пустые состояния, узкая ширина, счётчик, ссылка из карточки (FR-241, FR-277,
FR-280, FR-281, FR-282). Сценарии 4, 8 и 15 спеки.

Колонки и их порядок (FR-277), групповая панель над сеткой (FR-241), пояснения пустых пресетов и кнопка «Новая
заявка» (FR-282, CONTRACT-003 13.2, 14.4), разметка узкой ширины, счётчик пункта меню «Заявки» (FR-280, 6.21 `badge`,
13.5), ссылка «Заявки» в карточке сотрудника (FR-281, `listing.card_link`). Код среза на уровне модуля не
импортируется: имена берутся внутри тестов (CONTRACT-003, шапка).
"""
import contextlib
import importlib
import secrets
from html.parser import HTMLParser

import pytest
from django.db import connection

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

GRID = {**HX, "HTTP_HX_TARGET": "tickets-grid"}
CELLS = ["select", "number", "subject", "requester", "client-unit", "category", "queue", "priority", "status",
         "assignee", "created", "last-message"]
PRESETS = ["mine", "unassigned", "my_queues", "waiting", "closed", "all"]


class _Captured:
    def __init__(self):
        self.captured_queries = []

    def __len__(self):
        return len(self.captured_queries)


@contextlib.contextmanager
def capture_sql():
    """Запросы к базе внутри блока, в том числе запросы тестового клиента: через `connection.execute_wrapper`, а не
    `CaptureQueriesContext` (сигнал `request_started` сбрасывает его журнал; образец — test_sd_capacity.py)."""
    log = _Captured()

    def wrapper(execute, sql, params, many, context):
        log.captured_queries.append({"sql": sql})
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        yield log


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

    def inside(self, other) -> bool:
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


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


def tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом — через `_` (`data_cell="number"`); `True` — любой."""
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        ok = True
        for name, expected in wanted.items():
            if name not in node.attrs:
                ok = False
            elif expected is True:
                continue
            elif callable(expected):
                ok = ok and bool(expected(node.attrs[name]))
            elif node.attrs[name] != expected:
                ok = False
        if ok:
            found.append(node)
    return found


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


def _member(queue=None, **extra):
    """Участник очереди (сотрудник в её узле). Возвращает (пользователь, очередь)."""
    queue = queue or sd.make_queue()
    user = support.make_employee(**extra)
    org.make_member(user, queue.unit)
    return user, queue


def _list(user, query: str = "", **headers):
    response = support.logged_in(user).get("/tickets/" + query, **headers)
    assert response.status_code == 200, f"/tickets/{query}: {response.status_code}"
    return response, tree(response)


def _grid(user, query: str = "preset=all", **headers):
    response, root = _list(user, "?" + query if query else "", **headers)
    return root, q1(root, id="tickets-grid")


def _row(grid, ticket) -> Node:
    return q1(grid, "tr", data_ticket=str(ticket.number))


def _cell(row, name: str) -> Node:
    return q1(row, data_cell=name)


def _last_mark(cell) -> Node:
    """Элемент `[data-last-from]`: сама ячейка или её единственный потомок с этим атрибутом."""
    found = [n for n in [cell] + q(cell, data_last_from=True) if "data-last-from" in n.attrs]
    assert len(found) == 1, f"ожидали один [data-last-from], нашли {len(found)}"
    return found[0]


def _menu_badges(root) -> list:
    menu = q1(root, id="main-menu")
    links = q(menu, "a", class_=has_class("menu-item"), href="/tickets/")
    assert len(links) == 1, "пункт «Заявки» в меню должен быть один"
    return q(links[0], "span", data_menu_badge=True)


def _unassigned_in(queue, count: int, **over) -> list:
    return [sd.make_ticket(queue=queue, **over) for _ in range(count)]


# --- колонки (FR-277) -----------------------------------------------------------------------------------

def test_grid_has_all_columns_in_order():
    """FR-277: у строки заявки двенадцать ячеек (выбор и одиннадцать колонок FR-277) строго в порядке контракта 13.2,
    без лишних; значения ячеек — из заявки; номер — ссылка в слайдер; сортируемые столбцы — `th[data-sort]`."""
    user, queue = _member()
    unit_row = model("servicedesk.ClientUnit").objects.create(name="Бухгалтерия")
    category = sd.make_category("Принтеры", queue=queue)
    priority = model("servicedesk.Priority").objects.get(name_key=org.name_key("Высокая"))
    assignee = support.make_employee(full_name="Сидоров Семён Петрович")
    requester = sd.make_requester(full_name="Орлова Ольга", client_unit=unit_row)
    ticket = sd.make_ticket(queue=queue, requester=requester, subject="Не печатает принтер", category=category,
                            client_unit=unit_row, priority=priority, kind="in_progress", assignee=assignee,
                            status=model("servicedesk.Status").objects.get(kind="in_progress", is_default=True))
    root, grid = _grid(user)
    assert grid.attrs.get("data-tickets-grid") is not None
    row = _row(grid, ticket)
    assert row.attrs["data-kind"] == "in_progress"
    names = [cell.attrs["data-cell"] for cell in q(row, data_cell=True)]
    assert names == CELLS
    assert q(row, "input", type="checkbox", name="numbers", value=str(ticket.number))
    link = q1(_cell(row, "number"), "a", href=f"/tickets/{ticket.number}/")
    assert link.attrs["hx-get"] == f"/tickets/{ticket.number}/" and link.attrs["hx-target"] == "#slider-root"
    assert str(ticket.number) in _cell(row, "number").text()
    assert "Не печатает принтер" in _cell(row, "subject").text()
    assert "Орлова Ольга" in _cell(row, "requester").text()
    assert "Бухгалтерия" in _cell(row, "client-unit").text()
    assert "Принтеры" in _cell(row, "category").text()
    assert queue.unit.name in _cell(row, "queue").text()
    assert "Высокая" in _cell(row, "priority").text()
    assert ticket.status.name in _cell(row, "status").text()
    assert "Сидоров Семён Петрович" in _cell(row, "assignee").text()
    assert _cell(row, "created").text() != ""
    sortable = {th.attrs["data-sort"] for th in q(grid, "th", data_sort=True)}
    assert sortable == {"number", "created", "last_message", "priority"}
    assert {c.attrs["data-cell"] for c in q(grid, data_cell=True)} == set(CELLS)


def test_last_message_shows_time_and_requester_or_executor():
    """FR-277: ячейка «последнее сообщение» — время (`time[data-at]`) и от кого: `[data-last-from]` со значением
    `requester`/`staff` и подписью «заявитель»/«исполнитель»; время разное у заявок с разным `last_message_at`."""
    user, queue = _member()
    from_requester = sd.make_ticket(queue=queue, last_message_from="requester")
    from_staff = sd.make_ticket(queue=queue, last_message_from="staff")
    sd.backdate(from_staff, "last_message_at", days=2)
    root, grid = _grid(user)
    cell_r, cell_s = (_cell(_row(grid, t), "last-message") for t in (from_requester, from_staff))
    mark_r, mark_s = _last_mark(cell_r), _last_mark(cell_s)
    assert mark_r.attrs["data-last-from"] == "requester" and "заявитель" in mark_r.text()
    assert mark_s.attrs["data-last-from"] == "staff" and "исполнитель" in mark_s.text()
    time_r, time_s = q1(cell_r, "time", data_at=True), q1(cell_s, "time", data_at=True)
    assert time_r.attrs["data-at"] and time_s.attrs["data-at"]
    assert time_r.attrs["data-at"] != time_s.attrs["data-at"]


def test_last_message_ignores_comment_and_event():
    """FR-277: внутренний комментарий и событие ленты не меняют «последнее сообщение» в списке (спека: сценарий 4)."""
    user, queue = _member()
    ticket = sd.make_ticket(queue=queue, last_message_from="requester", assignee=user)
    sd.backdate(ticket, "last_message_at", hours=5)
    sd.make_entry(ticket, "incoming")
    before = _cell(_row(_grid(user)[1], ticket), "last-message")
    shown = q1(before, "time", data_at=True).attrs["data-at"]
    ticket.refresh_from_db()
    marker = ticket.last_message_at
    _svc("replies").comment(ticket, text="Внутренняя заметка", actor=user)
    _svc("replies").add_event(ticket, "priority_changed", actor=user,
                              data={"before": "Средняя", "after": "Высокая", "before_id": None, "after_id": None})
    ticket.refresh_from_db()
    assert ticket.last_message_at == marker and ticket.last_message_from == "requester"
    after = _cell(_row(_grid(user)[1], ticket), "last-message")
    assert q1(after, data_last_from=True).attrs["data-last-from"] == "requester"
    assert q1(after, "time", data_at=True).attrs["data-at"] == shown


def test_closed_without_assignee_shows_closed_by_name():
    """FR-277, FR-235 (сценарий 15): у закрытой без ответственного в ячейке ответственного «Закрыл: Имя Фамилия»
    (правило C5: из «Фамилия Имя Отчество» — второе слово и первое), у уволенного рядом «(уволен)»; у открытой без
    ответственного «не назначен»; у заявки с ответственным — его имя (доп. 10, 11)."""
    user, queue = _member()
    closer = support.make_employee(full_name="Иванов Пётр Сергеевич")
    gone = support.make_employee(full_name="Кузнецов Кирилл Львович", state="dismissed")
    closed = sd.make_ticket(queue=queue, kind="closed", assignee=None, closed_by=closer)
    closed_gone = sd.make_ticket(queue=queue, kind="closed", assignee=None, closed_by=gone)
    opened = sd.make_ticket(queue=queue)
    taken = sd.make_ticket(queue=queue, kind="in_progress", assignee=closer)
    closed_nobody = sd.make_ticket(queue=queue, kind="closed")   # без `closed_by` и без ответственного (доп. 28 (а))
    root, grid = _grid(user)
    text = _cell(_row(grid, closed), "assignee").text()
    assert "Закрыл: Пётр Иванов" in text
    gone_cell = _cell(_row(grid, closed_gone), "assignee")
    assert "Закрыл: Кирилл Кузнецов" in gone_cell.text() and "(уволен)" in gone_cell.text()
    assert "не назначен" in _cell(_row(grid, opened), "assignee").text()
    assert "Закрыл" not in _cell(_row(grid, opened), "assignee").text()
    nobody_text = _cell(_row(grid, closed_nobody), "assignee").text()
    assert "не назначен" in nobody_text and "Закрыл" not in nobody_text
    taken_text = _cell(_row(grid, taken), "assignee").text()
    assert "Иванов Пётр Сергеевич" in taken_text and "Закрыл" not in taken_text


def test_requester_column_name_or_address_fallback():
    """FR-277: колонка «заявитель» — ФИО заявки, а при пустом ФИО — адрес (`requester_name`, `requester_email`)."""
    user, queue = _member()
    named = sd.make_ticket(queue=queue, requester=sd.make_requester(email="named@client.test"),
                           requester_name="Волкова Вера", requester_email="named@client.test")
    bare = sd.make_ticket(queue=queue, requester=sd.make_requester(email="bare@client.test"),
                          requester_name="", requester_email="bare@client.test")
    root, grid = _grid(user)
    named_text = _cell(_row(grid, named), "requester").text()
    assert "Волкова Вера" in named_text and "named@client.test" not in named_text
    assert "bare@client.test" in _cell(_row(grid, bare), "requester").text()


def test_grid_read_with_constant_query_count():
    """FR-277: сетка читается одной выборкой со справочниками, узлом и ответственным: число запросов не растёт с числом
    строк (`listing.build` и страница `/tickets/`)."""
    user, queue = _member()
    listing = _svc("listing")
    unit_row = model("servicedesk.ClientUnit").objects.create(name="Склад")
    category = sd.make_category(queue=queue)
    priorities = list(model("servicedesk.Priority").objects.all()[:3])

    def add(count):
        for index in range(count):
            sd.make_ticket(queue=queue, requester=sd.make_requester(full_name=f"Заявитель {secrets_tail()}"),
                           category=category, client_unit=unit_row, priority=priorities[index % len(priorities)],
                           assignee=support.make_employee(), kind="in_progress",
                           status=model("servicedesk.Status").objects.get(kind="in_progress", is_default=True))

    def build_queries():
        listing.build(user, preset="all")   # прогрев: права смотрящего в кэше, справочники
        with capture_sql() as ctx:
            for row in listing.build(user, preset="all").rows:
                for name in ("status", "priority", "category", "assignee", "client_unit", "queue"):
                    str(getattr(row, name))
        return len(ctx)

    def page_queries():
        client = support.logged_in(user)
        client.get("/tickets/?preset=all")   # прогрев: сессия, права, кэши
        with capture_sql() as ctx:
            response = client.get("/tickets/?preset=all")
        assert response.status_code == 200
        return len(ctx), len(q(tree(response), "tr", data_ticket=True))

    add(3)
    small_build, (small_page, small_rows) = build_queries(), page_queries()
    add(27)
    big_build, (big_page, big_rows) = build_queries(), page_queries()
    assert (small_rows, big_rows) == (3, 30)
    assert big_build == small_build
    assert big_page == small_page


def secrets_tail() -> str:
    return secrets.token_hex(3)


# --- групповые действия над сеткой (FR-241) -------------------------------------------------------------

def test_bulk_actions_and_row_checkboxes_markup_above_grid():
    """FR-241: `form#tickets-bulk[data-form="tickets-bulk"]` стоит в `[data-tickets-list]` над сеткой и вне
    `#tickets-grid`; в ней выбор действия (`assign`, `transfer`, `priority`), группы параметров и кнопка отправки;
    у каждой строки флажок `input[name=numbers][form="tickets-bulk"]` в ячейке `select`; при подмене сетки (НХ с
    `HX-Target: tickets-grid`) флажки приходят, а форма остаётся на месте и в ответ не входит."""
    user, queue = _member()
    tickets = _unassigned_in(queue, 3)
    response, root = _list(user, "?preset=all")
    page = q1(root, data_tickets_list=True)
    bulk = q1(page, "form", id="tickets-bulk")
    grid = q1(page, id="tickets-grid")
    assert bulk.attrs["data-form"] == "tickets-bulk" and bulk.inside(page)
    assert not bulk.inside(grid)
    assert order_of(root, bulk) < order_of(root, grid)
    assert [o.attrs["value"] for o in q(q1(bulk, "select", name="action"), "option") if o.attrs.get("value")] == [
        "assign", "transfer", "priority"]
    assert q1(bulk, "select", name="user").inside(q1(bulk, data_bulk_action="assign"))
    group_transfer = q1(bulk, data_bulk_action="transfer")
    assert q1(group_transfer, "select", name="queue") and q1(group_transfer, "textarea", name="reason")
    assert q1(q1(bulk, data_bulk_action="priority"), "select", name="priority")
    assert q1(bulk, "button", type="submit")
    for ticket in tickets:
        row = _row(grid, ticket)
        box = q1(_cell(row, "select"), "input", type="checkbox", name="numbers", value=str(ticket.number))
        assert box.attrs["form"] == "tickets-bulk"
        assert not box.inside(bulk)
    fragment = tree(support.logged_in(user).get("/tickets/?preset=all", **GRID))
    assert not q(fragment, "form", id="tickets-bulk")
    assert len(q(fragment, "input", type="checkbox", name="numbers")) == 3


# --- пустые состояния (FR-282) --------------------------------------------------------------------------

def test_empty_preset_has_explanation_and_action_button():
    """FR-282: пустой пресет — `[data-empty-state="tickets"][data-preset=<код>]` с непустым пояснением и кнопкой
    `a[data-action="ticket-new"][href="/tickets/new/"]` у того, кто может завести заявку; при непустой сетке
    пустого состояния нет."""
    user, queue = _member()
    for code in PRESETS:
        root, grid = _grid(user, f"preset={code}")
        state = q1(root, data_empty_state="tickets", data_preset=code)
        assert state.text() != ""
        button = q1(state, "a", data_action="ticket-new")
        assert button.attrs["href"] == "/tickets/new/" and button.text() != ""
        assert not q(grid, "tr", data_ticket=True)
    sd.make_ticket(queue=queue)
    root, grid = _grid(user, "preset=all")
    assert not q(root, data_empty_state="tickets")
    assert len(q(grid, "tr", data_ticket=True)) == 1


def test_empty_list_new_ticket_button_only_for_creator_right():
    """FR-282: кнопки «Новая заявка» нет ни в пустом состоянии, ни в шапке у того, кто видит список, но не может
    завести заявку (ответственный чужой очереди без членства): пояснение остаётся; у участника очереди обе кнопки есть."""
    foreign_queue = sd.make_queue()
    assignee = support.make_employee()
    sd.make_ticket(queue=foreign_queue, kind="closed", assignee=assignee)
    root, _ = _grid(assignee, "preset=mine")
    state = q1(root, data_empty_state="tickets", data_preset="mine")
    assert state.text() != ""
    assert not q(state, "a", data_action="ticket-new")
    assert not q(root, "a", data_action="ticket-new")
    member, _ = _member()
    root, _ = _grid(member, "preset=mine")
    assert q1(q1(root, data_empty_state="tickets", data_preset="mine"), "a", data_action="ticket-new")
    page = q1(root, data_tickets_list=True)
    header = [n for n in page.children if isinstance(n, Node) and n.tag == "header"][0]
    assert q1(header, "a", data_action="ticket-new").attrs["href"] == "/tickets/new/"


def test_empty_queue_explains_what_will_be_here():
    """FR-282: у участника пустой очереди список по умолчанию («Мои очереди») объясняет, что здесь появится; если
    фильтр или поиск ничего не нашли — другое пояснение («По вашему запросу заявок нет») без кнопки (14.4)."""
    user, queue = _member()
    root, _ = _grid(user, "")
    state = q1(root, data_empty_state="tickets")
    assert state.attrs["data-preset"] == "my_queues"
    assert "очередей" in state.text()
    assert q1(state, "a", data_action="ticket-new")
    sd.make_ticket(queue=queue, subject="Принтер сломался")
    root, _ = _grid(user, "preset=all&q=несуществующеесловоабв")
    found_nothing = q1(root, data_empty_state="tickets")
    assert "По вашему запросу заявок нет" in found_nothing.text()
    assert not q(found_nothing, "a", data_action="ticket-new")


# --- узкая ширина (FR-282) ------------------------------------------------------------------------------

def test_narrow_width_markup_cards_with_subject_status_assignee():
    """FR-282: сетка несёт признак `data-narrow="cards"` (до 576 px строки — карточки), а в каждой строке есть
    ячейки темы, статуса и ответственного с их значениями — то, что карточка показывает; признак стоит и на
    сетке при подмене по НХ."""
    user, queue = _member()
    assignee = support.make_employee(full_name="Белов Борис")
    ticket = sd.make_ticket(queue=queue, subject="Сломался монитор", kind="in_progress", assignee=assignee,
                            status=model("servicedesk.Status").objects.get(kind="in_progress", is_default=True))
    for headers in ({}, GRID):
        response = support.logged_in(user).get("/tickets/?preset=all", **headers)
        grid = q1(tree(response), id="tickets-grid")
        assert grid.attrs["data-narrow"] == "cards" and "data-tickets-grid" in grid.attrs
        row = _row(grid, ticket)
        assert "Сломался монитор" in _cell(row, "subject").text()
        assert ticket.status.name in _cell(row, "status").text()
        assert "Белов Борис" in _cell(row, "assignee").text()
        assert row.inside(q1(grid, "table"))


def test_narrow_width_filter_panel_in_details_no_horizontal_scroll_markup():
    """FR-282: панель фильтра — раскрывающийся блок `details[data-filter-panel]` с формой `#tickets-filter`
    внутри `[data-tickets-list]` после пресетов; в `<head>` есть `<meta name="viewport">` (без него 360 px без
    горизонтальной прокрутки не получить); сама сетка не вынесена за таблицу."""
    user, queue = _member()
    sd.make_ticket(queue=queue)
    response, root = _list(user, "?preset=all")
    page = q1(root, data_tickets_list=True)
    panel = q1(page, "details", data_filter_panel=True)
    form = q1(panel, "form", id="tickets-filter")
    assert form.attrs["data-form"] == "tickets-filter" and form.inside(panel)
    presets = q1(page, "nav", data_presets=True)
    assert order_of(root, presets) < order_of(root, panel)
    head = q1(root, "head")
    assert "width=device-width" in q1(head, "meta", name="viewport").attrs.get("content", "")
    assert q1(q1(page, id="tickets-grid"), "table")
    fragment = tree(support.logged_in(user).get("/tickets/?preset=all", **GRID))
    assert not q(fragment, "details", data_filter_panel=True)


# --- счётчик пункта меню (FR-280) -----------------------------------------------------------------------

def _count_queries(ctx) -> int:
    """Число вхождений `COUNT(` в запросах к таблице заявок (один запрос с двумя агрегатами тоже верен)."""
    return sum(item["sql"].upper().count("COUNT(") for item in ctx.captured_queries
               if "servicedesk_ticket" in item["sql"] and "servicedesk_ticketentry" not in item["sql"])


def test_badge_sums_unassigned_in_my_queues_and_mine_from_requester():
    """FR-280 (сценарий 8): число = открытые без ответственного в моих очередях (4) + мои открытые, где последнее
    сообщение от заявителя (2) = 6; в счёт не входят закрытые, заявки чужой очереди, чужие, свои с сообщением
    исполнителя; `listing.badge` и разметка `span[data-menu-badge]` дают 6."""
    user, queue = _member()
    other_queue = sd.make_queue()
    other_user = support.make_employee()
    _unassigned_in(queue, 3)
    sd.make_ticket(queue=queue, kind="waiting")
    for _ in range(2):
        sd.make_ticket(queue=queue, kind="in_progress", assignee=user, last_message_from="requester")
    sd.make_ticket(queue=queue, kind="closed")
    sd.make_ticket(queue=queue, kind="closed", assignee=user, last_message_from="requester")
    sd.make_ticket(queue=queue, kind="in_progress", assignee=user, last_message_from="staff")
    sd.make_ticket(queue=queue, kind="in_progress", assignee=other_user, last_message_from="requester")
    _unassigned_in(other_queue, 2)
    assert _svc("listing").badge(user) == 6
    response, root = _list(user, "?preset=all")
    badges = _menu_badges(root)
    assert len(badges) == 1 and badges[0].text() == "6"
    assert [b.text() for b in _menu_badges(tree(support.logged_in(user).get("/me/")))] == ["6"]


def test_badge_not_counted_when_menu_item_hidden():
    """FR-280: у того, кому пункт «Заявки» не виден (нет очередей, права «Все заявки» и своих заявок), пункта и
    счётчика в меню нет, а счёт открытых заявок (`COUNT` по таблице заявок) при загрузке страницы не выполняется
    (`badge` зовётся только у видимого пункта, 3.2)."""
    sd.make_ticket(queue=sd.make_queue())
    outsider = support.make_employee()
    permissions = importlib.import_module("apps.core.services.permissions")
    assert "/tickets/" not in [item["url"] for item in permissions.menu_for(outsider)]
    client = support.logged_in(outsider)
    client.get("/me/")   # прогрев
    with capture_sql() as ctx:
        response = client.get("/me/")
    assert response.status_code == 200
    root = tree(response)
    menu = q1(root, id="main-menu")
    assert not q(menu, "a", href="/tickets/") and not q(menu, "span", data_menu_badge=True)
    assert _count_queries(ctx) == 0


def test_badge_two_counts_once_per_request():
    """FR-280, 6.21: счётчик — два `COUNT` по таблице заявок за загрузку страницы (не больше и не по разу на
    каждый вывод меню); результат — число в `span[data-menu-badge]`."""
    user, queue = _member()
    _unassigned_in(queue, 2)
    sd.make_ticket(queue=queue, kind="in_progress", assignee=user, last_message_from="requester")
    client = support.logged_in(user)
    client.get("/me/")   # прогрев
    with capture_sql() as ctx:
        response = client.get("/me/")
    assert response.status_code == 200
    assert _count_queries(ctx) == 2
    assert [b.text() for b in _menu_badges(tree(response))] == ["3"]


def test_badge_updates_on_page_load_without_cache():
    """FR-280, 7.4: кэша счётчика нет — при следующей загрузке страницы число свежее: 0 (элемента нет) → 1 → 2 →
    снова меньше после закрытия; в Valkey ключей счётчика не заводится."""
    user, queue = _member()
    client = support.logged_in(user)

    def shown():
        response = client.get("/tickets/?preset=all")
        assert response.status_code == 200
        return [b.text() for b in _menu_badges(tree(response))]

    assert shown() == []
    first = sd.make_ticket(queue=queue)
    assert shown() == ["1"]
    sd.make_ticket(queue=queue)
    assert shown() == ["2"]
    first.kind = "closed"
    first.status = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    first.save(update_fields=["kind", "status"])
    assert shown() == ["1"]
    assert not list(support.valkey().scan_iter(match="*badge*"))


# --- ссылка из карточки сотрудника (FR-281) -------------------------------------------------------------

def _viewer(queue=None):
    """Смотрящий: участник очереди с правом `staff.view` (карточка сотрудника `/staff/<id>/`)."""
    queue = queue or sd.make_queue()
    viewer = support.make_with_permissions("staff.view")
    org.make_member(viewer, queue.unit)
    return viewer, queue


def test_employee_card_tickets_link_filters_by_assignee():
    """FR-281 (сценарий 8): в карточке сотрудника раздел `[data-section="tickets"]` со ссылкой «Заявки»
    `a[data-action="employee-tickets"][href="/tickets/?preset=all&assignee=<id>"]`; `listing.card_link` даёт тот же
    адрес; список по ссылке — только заявки этого ответственного."""
    viewer, queue = _viewer()
    employee = support.make_employee(full_name="Громов Глеб")
    mine = [sd.make_ticket(queue=queue, kind="in_progress", assignee=employee) for _ in range(2)]
    others = sd.make_ticket(queue=queue, kind="in_progress", assignee=support.make_employee())
    unassigned = sd.make_ticket(queue=queue)
    href = f"/tickets/?preset=all&assignee={employee.pk}"
    assert _svc("listing").card_link(viewer, employee.pk) == href
    client = support.logged_in(viewer)
    response = client.get(f"/staff/{employee.pk}/")
    assert response.status_code == 200
    section = q1(tree(response), data_section="tickets")
    link = q1(section, "a", data_action="employee-tickets")
    assert link.attrs["href"] == href and link.text() == "Заявки"
    listed = client.get(link.attrs["href"])
    assert listed.status_code == 200
    numbers = {int(r.attrs["data-ticket"]) for r in q(tree(listed), "tr", data_ticket=True)}
    assert numbers == {t.number for t in mine}
    assert others.number not in numbers and unassigned.number not in numbers


def test_employee_card_link_hidden_without_menu_item():
    """FR-281: у смотрящего, которому пункт «Заявки» не виден, раздела `[data-section="tickets"]` в карточке нет, а
    `listing.card_link` возвращает `None`; у видящего пункт и раздел есть."""
    employee = support.make_employee()
    blind = support.make_with_permissions("staff.view")
    assert _svc("listing").card_link(blind, employee.pk) is None
    response = support.logged_in(blind).get(f"/staff/{employee.pk}/")
    assert response.status_code == 200
    assert not q(tree(response), data_section="tickets")
    holder = support.make_with_permissions("staff.view", "servicedesk.all")
    assert _svc("listing").card_link(holder, employee.pk) is not None
    seen = support.logged_in(holder).get(f"/staff/{employee.pk}/")
    assert q1(tree(seen), data_section="tickets")


def test_linked_list_limited_by_viewer_visible_tickets():
    """FR-281, FR-234: список по ссылке из карточки строится по правам смотрящего: заявки ответственного из
    чужой для смотрящего очереди в нём не показаны (ни в сетке, ни в подсказках); держатель «Все заявки» видит все."""
    viewer, queue_a = _viewer()
    queue_b = sd.make_queue()
    employee = support.make_employee()
    visible = sd.make_ticket(queue=queue_a, kind="in_progress", assignee=employee)
    hidden = sd.make_ticket(queue=queue_b, kind="in_progress", assignee=employee,
                            subject="Скрытая-" + secrets.token_hex(4))
    link = _svc("listing").card_link(viewer, employee.pk)
    response = support.logged_in(viewer).get(link)
    assert response.status_code == 200
    root = tree(response)
    assert {int(r.attrs["data-ticket"]) for r in q(root, "tr", data_ticket=True)} == {visible.number}
    assert str(hidden.subject) not in response.content.decode("utf-8")
    holder = support.make_with_permissions("servicedesk.all")
    wide = support.logged_in(holder).get(link)
    assert {int(r.attrs["data-ticket"]) for r in q(tree(wide), "tr", data_ticket=True)} == {
        visible.number, hidden.number}
