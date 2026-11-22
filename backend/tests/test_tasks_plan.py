"""Срез 009 «Задачи»: личные колонки «Моего плана» (T-9110; FR-682, FR-684).

Владелец создаёт, переименовывает, переставляет и удаляет свои колонки; удаление переносит задачи в первую;
чужой план руководитель и заместитель видят только для чтения; выбор колонки в карточке — только владельцу
плана (PLAN-009 «Мой план и категории»; CONTRACT-009, 4, 5.1, 6.2, 7). Код среза импортируется внутри тестов;
тексты отказов — литералы раздела 12.1.
"""
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_org
from tests import support_tasks as tasks

pytestmark = pytest.mark.django_db

TITLE_RANGE = "Название колонки — от 1 до 100 знаков"
TITLE_TAKEN = "Колонка с таким названием уже есть"
COLUMN_LAST = "Последнюю колонку удалить нельзя"
PLAN_FORBIDDEN = "Двигать карточки в чужом плане нельзя"

PLAN_TITLES = ["Сегодня", "На этой неделе", "Потом"]


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
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def _error(response, field, code, text) -> None:
    nodes = q(tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error={field}][data-code={code}] в ответе {response.status_code}"
    assert any(text in node.text() for node in nodes), f"нет текста «{text}» в отказе {code}"


def _plan_columns(scope) -> list:
    return q(scope, data_plan_column=True)


def _plan_title(column) -> str:
    titles = q(column, data_column_title=True)
    assert titles, "нет [data-column-title] в колонке плана"
    return titles[0].text()


def _card_ids(column) -> set:
    return {int(node.attrs["data-task-id"]) for node in q(column, data_task_id=True)}


def _fresh(task):
    return support.model("tasks.Task").objects.get(pk=task.pk)


# --- CRUD владельца ---------------------------------------------------------------------------------------------

def test_owner_adds_renames_and_reorders_columns():
    """FR-682: владелец добавляет колонку, переименовывает её и задаёт `position`; обычный POST отвечает 302,
    изменения видны в `columns_of`."""
    from apps.tasks.services import plan

    owner = tasks.staff_user()
    client = support.logged_in(owner)
    plan.ensure_defaults(owner)

    created = client.post("/tasks/plan/columns/", {"title": "Важное"})
    assert created.status_code == 302, created.status_code
    column = support.model("tasks.PlanColumn").objects.get(user=owner, title="Важное")

    renamed = client.post(f"/tasks/plan/columns/{column.pk}/", {"title": "Срочное", "position": "0"})
    assert renamed.status_code == 302, renamed.status_code
    column.refresh_from_db()
    assert column.title == "Срочное"
    assert plan.columns_of(owner)[0].pk == column.pk, "position=0 ставит колонку первой"


def test_first_open_creates_three_default_columns_once():
    """FR-682: первое открытие `/tasks/board/plan/` создаёт «Сегодня», «На этой неделе», «Потом»; повторное
    открытие не дублирует; задача без колонки показывается в первой."""
    owner = tasks.staff_user()
    client = support.logged_in(owner)
    PlanColumn = support.model("tasks.PlanColumn")
    task = tasks.make_task(title="Без колонки", author=owner, assignee=owner)
    assert PlanColumn.objects.filter(user=owner).count() == 0

    response = client.get("/tasks/board/plan/")

    assert response.status_code == 200, response.status_code
    columns = list(PlanColumn.objects.filter(user=owner).order_by("position", "pk"))
    assert [column.title for column in columns] == PLAN_TITLES
    root = tree(response)
    nodes = _plan_columns(root)
    assert [node.attrs["data-plan-column"] for node in nodes] == [str(column.pk) for column in columns]
    assert [_plan_title(node) for node in nodes] == PLAN_TITLES
    assert task.pk in _card_ids(nodes[0])

    assert client.get("/tasks/board/plan/").status_code == 200
    assert PlanColumn.objects.filter(user=owner).count() == 3


def test_deleting_column_moves_its_tasks_into_first_column():
    """FR-682: удаление колонки (второй шаг `confirm=1`) переносит её задачи в первую колонку; задача и первая
    колонка остаются."""
    from apps.tasks.services import plan

    owner = tasks.staff_user()
    client = support.logged_in(owner)
    first, second, _third = plan.ensure_defaults(owner)
    task = tasks.make_task(title="Вторая колонка", author=owner, assignee=owner, plan_column=second)

    response = client.post(f"/tasks/plan/columns/{second.pk}/delete/", {"confirm": "1"})

    assert response.status_code == 302, response.status_code
    assert not support.model("tasks.PlanColumn").objects.filter(pk=second.pk).exists()
    assert _fresh(task).plan_column_id == first.pk
    assert plan.columns_of(owner)[0].pk == first.pk


def test_last_column_cannot_be_deleted():
    """FR-682: последнюю колонку удалить нельзя — 200 с `column`/`column_last`, колонка остаётся."""
    owner = tasks.staff_user()
    column = tasks.make_column(owner, title="Единственная", position=0)

    response = support.logged_in(owner).post(f"/tasks/plan/columns/{column.pk}/delete/", {"confirm": "1"})

    assert response.status_code == 200
    _error(response, "column", "column_last", COLUMN_LAST)
    assert support.model("tasks.PlanColumn").objects.filter(pk=column.pk).exists()


# --- чужой план -------------------------------------------------------------------------------------------------

def test_foreign_plan_is_readonly_for_head_and_deputy():
    """FR-682: руководитель и заместитель открывают план подчинённого (`?user=<id>`) и видят колонки и карточки,
    но страница помечена `[data-plan-readonly]`."""
    tree_ = support_org.make_tree({"Отдел": {}})
    employee = tasks.staff_user()
    support_org.make_member(employee, tree_["Отдел"])
    head = tasks.head_of(tree_["Отдел"])
    deputy = tasks.deputy_of(tree_["Отдел"])
    for position, title in enumerate(PLAN_TITLES):
        tasks.make_column(employee, title=title, position=position)
    task = tasks.make_task(title="Задача подчинённого", author=employee, assignee=employee)

    for viewer in (head, deputy):
        response = support.logged_in(viewer).get(f"/tasks/board/plan/?user={employee.pk}")
        assert response.status_code == 200, f"{viewer.pk}: {response.status_code}"
        root = tree(response)
        nodes = _plan_columns(root)
        assert [_plan_title(node) for node in nodes] == PLAN_TITLES
        assert task.pk in _card_ids(nodes[0])
        assert q(root, data_plan_readonly=True), "чужой план должен быть только для чтения"


def test_deputy_cannot_move_cards_or_edit_columns_in_subordinate_plan():
    """FR-682, FR-678: заместитель не двигает карточки в плане подчинённого — 200 с `board`/`plan_forbidden`;
    переименование и удаление чужой колонки — 403."""
    tree_ = support_org.make_tree({"Отдел": {}})
    employee = tasks.staff_user()
    support_org.make_member(employee, tree_["Отдел"])
    deputy = tasks.deputy_of(tree_["Отдел"])
    column = tasks.make_column(employee, title="Сегодня", position=0)
    task = tasks.make_task(title="Задача", author=employee, assignee=employee)
    client = support.logged_in(deputy)

    moved = tasks.move(client, task, "plan", str(column.pk))
    assert moved.status_code == 200
    _error(moved, "board", "plan_forbidden", PLAN_FORBIDDEN)
    assert _fresh(task).plan_column_id is None

    assert client.post(f"/tasks/plan/columns/{column.pk}/", {"title": "Чужое", "position": "0"}).status_code == 403
    assert client.post(f"/tasks/plan/columns/{column.pk}/delete/", {"confirm": "1"}).status_code == 403
    column.refresh_from_db()
    assert column.title == "Сегодня"


# --- названия колонок -------------------------------------------------------------------------------------------

def test_column_title_limits_and_uniqueness():
    """FR-682: название колонки — от 1 до 100 знаков и уникально у сотрудника: пустое и 101 знак —
    `title`/`column_title_range`, повтор — `title`/`column_title_taken`; 100 знаков принимается."""
    owner = tasks.staff_user()
    client = support.logged_in(owner)
    url = "/tasks/plan/columns/"

    empty = client.post(url, {"title": ""})
    assert empty.status_code == 200
    _error(empty, "title", "column_title_range", TITLE_RANGE)

    too_long = client.post(url, {"title": "к" * 101})
    assert too_long.status_code == 200
    _error(too_long, "title", "column_title_range", TITLE_RANGE)

    longest = "к" * 100
    assert client.post(url, {"title": longest}).status_code == 302
    assert support.model("tasks.PlanColumn").objects.filter(user=owner, title=longest).exists()

    duplicate = client.post(url, {"title": longest})
    assert duplicate.status_code == 200
    _error(duplicate, "title", "column_title_taken", TITLE_TAKEN)


# --- выбор колонки в карточке -----------------------------------------------------------------------------------

def test_plan_column_choice_in_card_is_visible_only_to_plan_owner():
    """FR-684, FR-682: выбор личной колонки `[data-task-field="plan_column"]` есть в карточке у владельца плана
    и отсутствует у руководителя, который видит ту же задачу."""
    from apps.tasks.services import plan

    tree_ = support_org.make_tree({"Отдел": {}})
    employee = tasks.staff_user()
    support_org.make_member(employee, tree_["Отдел"])
    head = tasks.head_of(tree_["Отдел"])
    plan.ensure_defaults(employee)
    task = tasks.make_task(title="Задача", author=employee, assignee=employee)

    own = support.logged_in(employee).get(f"/tasks/{task.pk}/")
    assert own.status_code == 200
    assert q(tree(own), data_task_field="plan_column"), "владелец плана выбирает колонку в карточке"

    foreign = support.logged_in(head).get(f"/tasks/{task.pk}/")
    assert foreign.status_code == 200
    assert not q(tree(foreign), data_task_field="plan_column"), "руководитель не двигает чужой план"