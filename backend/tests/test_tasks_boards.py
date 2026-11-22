"""Срез 009 «Задачи»: четыре доски (T-9108; FR-680…FR-684).

«Стадии» — четыре колонки-статуса с числами; «Сроки» — `overdue`/`today`/`week`/`none` без «Готово» и без срока
дальше семи дней; «Мой план» — личные колонки, три создаются лениво; «Категории» — по `position`, «Без категории»
(`key="none"`) последней (PLAN-009 «Доски и перетаскивание», «Мой план и категории»; CONTRACT-009, 5.1, 6.2, 7).
Код среза импортируется внутри тестов: сбор проходит до его появления, падения видны поимённо. Модели — через
`support.model`. Тексты — литералы раздела 12, даты — по Москве.
"""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_tasks as tasks

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc

STATUS_KEYS = ["new", "in_progress", "waiting", "done"]
STATUS_TITLES = ["Новая", "В работе", "Ждёт", "Готово"]
DEADLINE_KEYS = ["overdue", "today", "week", "none"]
DEADLINE_TITLES = ["Просрочены", "Сегодня", "На неделе", "Без срока"]
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
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`; `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def _columns(scope) -> list:
    return q(scope, data_column=True)


def _column_title(column) -> str:
    nodes = q(column, data_column_title=True)
    assert nodes, f"нет [data-column-title] в колонке {column.attrs.get('data-column')!r}"
    return nodes[0].text()


def _column_count(column) -> int:
    nodes = q(column, data_column_count=True)
    assert nodes, f"нет [data-column-count] в колонке {column.attrs.get('data-column')!r}"
    found = re.search(r"\d+", nodes[0].text())
    assert found, f"в [data-column-count] нет числа: {nodes[0].text()!r}"
    return int(found.group())


def _ids(column) -> set:
    return {int(node.attrs["data-task-id"]) for node in q(column, data_task_id=True)}


def _error(response, field, code, text) -> None:
    """Отказ у поля: 200, `[data-error="<поле>"][data-code="<код>"]` и текст раздела 12.1 внутри него."""
    nodes = q(tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error={field}][data-code={code}] в ответе {response.status_code}"
    assert any(text in node.text() for node in nodes), f"нет текста «{text}» в отказе {code}"


def _service():
    from apps.tasks.services import boards
    return boards


# --- «Стадии» --------------------------------------------------------------------------------------------------

def test_status_columns_service_has_four_statuses_counts_and_done_column():
    """FR-680: служба «Стадии» отдаёт ровно четыре колонки `new`, `in_progress`, `waiting`, `done` в порядке
    плана, с русскими названиями, числом задач и самими задачами; завершённые остаются в «Готово»."""
    owner = tasks.viewer()
    first = tasks.make_task(title="Первая", author=owner, assignee=owner)
    second = tasks.make_task(title="Вторая", author=owner, assignee=owner)
    running = tasks.make_task(title="В работе", author=owner, assignee=owner, status="in_progress")
    waiting = tasks.make_task(title="Ждёт", author=owner, assignee=owner, status="waiting")
    finished = tasks.make_task(title="Готово", author=owner, assignee=owner, status="done")

    columns = _service().status_columns(owner)

    assert [column["key"] for column in columns] == STATUS_KEYS
    assert [column["title"] for column in columns] == STATUS_TITLES
    assert [column["count"] for column in columns] == [2, 1, 1, 1]
    for column in columns:
        assert column["count"] == len(column["tasks"])
    by_key = {column["key"]: column for column in columns}
    assert {task.pk for task in by_key["new"]["tasks"]} == {first.pk, second.pk}
    assert {task.pk for task in by_key["in_progress"]["tasks"]} == {running.pk}
    assert {task.pk for task in by_key["waiting"]["tasks"]} == {waiting.pk}
    assert {task.pk for task in by_key["done"]["tasks"]} == {finished.pk}


def test_status_board_page_renders_columns_titles_counts_and_cards():
    """FR-680, FR-684: `/tasks/board/status/` — корень `[data-board="status"]`, четыре `[data-column]` в порядке
    статусов, у каждой `[data-column-title]`, число `[data-column-count]` и карточки `[data-task-card]` с
    номерами; на доске есть шаблон адреса переноса `[data-move-url]`."""
    owner = tasks.viewer()
    first = tasks.make_task(title="Первая", author=owner, assignee=owner)
    second = tasks.make_task(title="Вторая", author=owner, assignee=owner)
    running = tasks.make_task(title="В работе", author=owner, assignee=owner, status="in_progress")
    finished = tasks.make_task(title="Готово", author=owner, assignee=owner, status="done")
    client = support.logged_in(owner)

    response = client.get("/tasks/board/status/")

    assert response.status_code == 200, response.status_code
    root = tree(response)
    assert q(root, data_board="status"), "нет корня [data-board=status]"
    assert q(root, data_move_url=True), "нет [data-move-url]"

    columns = _columns(root)
    assert [column.attrs["data-column"] for column in columns] == STATUS_KEYS
    assert [_column_title(column) for column in columns] == STATUS_TITLES
    assert [_column_count(column) for column in columns] == [2, 1, 0, 1]
    by_key = {column.attrs["data-column"]: column for column in columns}
    assert _ids(by_key["new"]) == {first.pk, second.pk}
    assert _ids(by_key["in_progress"]) == {running.pk}
    assert _ids(by_key["done"]) == {finished.pk}

    rows = tasks.board_rows(response, "status")
    assert list(rows) == STATUS_KEYS
    assert set(rows["new"]) == {first.pk, second.pk}
    assert rows["in_progress"] == [running.pk]
    assert rows["done"] == [finished.pk]


# --- «Сроки» ---------------------------------------------------------------------------------------------------

def test_deadline_columns_service_groups_by_moscow_today_without_done_or_far_deadlines(clock):
    """FR-681, NFR-717: «Просрочены» — срок раньше сегодняшнего (по Москве) и статус не «Готово»; «Сегодня» —
    сегодня; «На неделе» — от завтра до сегодня + 7 включительно; «Без срока» — без даты. Задачи «Готово» и
    сроки дальше семи дней на доске не показываются; колонки идут `overdue`, `today`, `week`, `none`."""
    from apps.core.widgets import moscow_today

    clock.set(datetime(2026, 11, 18, 9, 0, tzinfo=UTC))
    today = moscow_today()
    owner = tasks.viewer()
    overdue = tasks.make_task(title="Просрочена", author=owner, assignee=owner, deadline=today - timedelta(days=1))
    overdue_done = tasks.make_task(title="Просрочена и готова", author=owner, assignee=owner,
                                   deadline=today - timedelta(days=1), status="done")
    due_today = tasks.make_task(title="Сегодня", author=owner, assignee=owner, deadline=today)
    tomorrow = tasks.make_task(title="Завтра", author=owner, assignee=owner, deadline=today + timedelta(days=1))
    week_end = tasks.make_task(title="Через семь", author=owner, assignee=owner, deadline=today + timedelta(days=7))
    far = tasks.make_task(title="Через восемь", author=owner, assignee=owner, deadline=today + timedelta(days=8))
    no_deadline = tasks.make_task(title="Без срока", author=owner, assignee=owner)
    done_without = tasks.make_task(title="Готова без срока", author=owner, assignee=owner, status="done")

    columns = _service().deadline_columns(owner)

    assert [column["key"] for column in columns] == DEADLINE_KEYS
    assert [column["title"] for column in columns] == DEADLINE_TITLES
    assert "done" not in [column["key"] for column in columns]
    by_key = {column["key"]: column for column in columns}
    assert {task.pk for task in by_key["overdue"]["tasks"]} == {overdue.pk}
    assert {task.pk for task in by_key["today"]["tasks"]} == {due_today.pk}
    assert {task.pk for task in by_key["week"]["tasks"]} == {tomorrow.pk, week_end.pk}
    assert {task.pk for task in by_key["none"]["tasks"]} == {no_deadline.pk}
    shown = {task.pk for column in columns for task in column["tasks"]}
    assert overdue_done.pk not in shown and far.pk not in shown and done_without.pk not in shown


def test_deadline_board_page_keeps_groups_order_and_hides_done_and_far(clock):
    """FR-681: `/tasks/board/deadline/` показывает те же четыре группы в порядке плана, карточки лежат в своих
    колонках; задачи «Готово» и со сроком дальше семи дней отсутствуют на странице."""
    from apps.core.widgets import moscow_today

    clock.set(datetime(2026, 11, 18, 9, 0, tzinfo=UTC))
    today = moscow_today()
    owner = tasks.viewer()
    overdue = tasks.make_task(title="Просрочена", author=owner, assignee=owner, deadline=today - timedelta(days=1))
    due_today = tasks.make_task(title="Сегодня", author=owner, assignee=owner, deadline=today)
    tomorrow = tasks.make_task(title="Завтра", author=owner, assignee=owner, deadline=today + timedelta(days=1))
    week_end = tasks.make_task(title="Через семь", author=owner, assignee=owner, deadline=today + timedelta(days=7))
    far = tasks.make_task(title="Через восемь", author=owner, assignee=owner, deadline=today + timedelta(days=8))
    done = tasks.make_task(title="Готова", author=owner, assignee=owner, deadline=today, status="done")
    no_deadline = tasks.make_task(title="Без срока", author=owner, assignee=owner)

    response = support.logged_in(owner).get("/tasks/board/deadline/")

    assert response.status_code == 200, response.status_code
    root = tree(response)
    assert q(root, data_board="deadline")
    columns = _columns(root)
    assert [column.attrs["data-column"] for column in columns] == DEADLINE_KEYS
    assert [_column_title(column) for column in columns] == DEADLINE_TITLES
    rows = tasks.board_rows(response, "deadline")
    assert list(rows) == DEADLINE_KEYS
    assert set(rows["overdue"]) == {overdue.pk}
    assert rows["today"] == [due_today.pk]
    assert set(rows["week"]) == {tomorrow.pk, week_end.pk}
    assert set(rows["none"]) == {no_deadline.pk}
    shown = {pk for ids in rows.values() for pk in ids}
    assert far.pk not in shown and done.pk not in shown


# --- «Мой план» ------------------------------------------------------------------------------------------------

def test_plan_columns_create_three_defaults_lazily_and_group_unassigned_in_first():
    """FR-682: колонки «Сегодня», «На этой неделе», «Потом» создаются лениво один раз; служба плана отдаёт их в
    порядке `position`, задача без колонки показывается в первой."""
    from apps.tasks.services import plan

    owner = tasks.viewer()
    PlanColumn = support.model("tasks.PlanColumn")
    task = tasks.make_task(title="Без колонки", author=owner, assignee=owner)
    assert PlanColumn.objects.filter(user=owner).count() == 0

    created = plan.ensure_defaults(owner)
    assert [column.title for column in created] == PLAN_TITLES
    assert PlanColumn.objects.filter(user=owner).count() == 3
    again = plan.ensure_defaults(owner)
    assert [column.pk for column in again] == [column.pk for column in created], "повторный вызов не должен дублировать"
    assert PlanColumn.objects.filter(user=owner).count() == 3

    columns = _service().plan_columns(owner, owner)

    assert [column["title"] for column in columns] == PLAN_TITLES
    assert len({column["key"] for column in columns}) == 3
    assert {task.pk for task in columns[0]["tasks"]} == {task.pk}
    assert columns[0]["count"] == 1


def test_plan_board_page_creates_defaults_on_first_open_and_places_unassigned_first():
    """FR-682: первое открытие `/tasks/board/plan/` создаёт три колонки; на странице они идут
    `[data-plan-column]` в порядке плана, задача без колонки — в первой; свой план не помечен
    `[data-plan-readonly]`."""
    owner = tasks.viewer()
    PlanColumn = support.model("tasks.PlanColumn")
    task = tasks.make_task(title="Без колонки", author=owner, assignee=owner)
    client = support.logged_in(owner)
    assert PlanColumn.objects.filter(user=owner).count() == 0

    response = client.get("/tasks/board/plan/")

    assert response.status_code == 200, response.status_code
    columns = list(PlanColumn.objects.filter(user=owner).order_by("position", "pk"))
    assert [column.title for column in columns] == PLAN_TITLES
    root = tree(response)
    assert q(root, data_board="plan")
    nodes = q(root, data_plan_column=True)
    assert [node.attrs["data-plan-column"] for node in nodes] == [str(column.pk) for column in columns]
    assert [_column_title(node) for node in nodes] == PLAN_TITLES
    assert task.pk in _ids(nodes[0])
    assert not q(root, data_plan_readonly=True), "свой план доступен для правки"
    assert PlanColumn.objects.filter(user=owner).count() == 3


# --- «Категории» -----------------------------------------------------------------------------------------------

def test_category_columns_follow_position_and_put_none_last():
    """FR-683, K19: служба «Категории» раскладывает задачи по категориям в порядке `position` и добавляет
    последней «Без категории» с ключом `none`."""
    owner = tasks.viewer()
    high = tasks.make_category(title="Позже", position=20)
    low = tasks.make_category(title="Раньше", position=10)
    in_high = tasks.make_task(title="В поздней", author=owner, assignee=owner, category=high)
    in_low = tasks.make_task(title="В ранней", author=owner, assignee=owner, category=low)
    uncategorized = tasks.make_task(title="Без категории", author=owner, assignee=owner)

    columns = _service().category_columns(owner)

    assert [column["title"] for column in columns] == ["Раньше", "Позже", "Без категории"]
    assert columns[-1]["key"] == "none"
    by_title = {column["title"]: column for column in columns}
    assert {task.pk for task in by_title["Раньше"]["tasks"]} == {in_low.pk}
    assert {task.pk for task in by_title["Позже"]["tasks"]} == {in_high.pk}
    assert {task.pk for task in by_title["Без категории"]["tasks"]} == {uncategorized.pk}


def test_category_board_page_orders_columns_and_keeps_none_last():
    """FR-683, K19: `/tasks/board/category/` показывает категории по `position` и «Без категории» последней с
    ключом `none`; карточки задач лежат в своих колонках."""
    owner = tasks.viewer()
    high = tasks.make_category(title="Позже", position=20)
    low = tasks.make_category(title="Раньше", position=10)
    in_high = tasks.make_task(title="В поздней", author=owner, assignee=owner, category=high)
    in_low = tasks.make_task(title="В ранней", author=owner, assignee=owner, category=low)
    uncategorized = tasks.make_task(title="Без категории", author=owner, assignee=owner)

    response = support.logged_in(owner).get("/tasks/board/category/")

    assert response.status_code == 200, response.status_code
    root = tree(response)
    assert q(root, data_board="category")
    columns = _columns(root)
    assert [_column_title(column) for column in columns] == ["Раньше", "Позже", "Без категории"]
    assert columns[-1].attrs["data-column"] == "none"
    by_title = {_column_title(column): column for column in columns}
    assert _ids(by_title["Раньше"]) == {in_low.pk}
    assert _ids(by_title["Позже"]) == {in_high.pk}
    rows = tasks.board_rows(response, "category")
    assert rows["none"] == [uncategorized.pk]
    assert list(rows)[-1] == "none"