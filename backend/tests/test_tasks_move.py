"""Срез 009 «Задачи»: перенос `POST /tasks/<id>/move/` (T-9109; FR-681, FR-684, FR-690).

Доска и значение приходят полями `board` и `value`; права — по полю (статус, срок, категория, личный план),
«Сегодня» — сегодняшняя дата по Москве, «На неделе» — ближайшая пятница строго после сегодня, «Без срока» снимает
дату; из «Просрочены» переносить нельзя. Смена срока пересчитывает напоминания (PLAN-009 «Доски и перетаскивание»,
CONTRACT-009, 4, 6.2, 7). Код среза импортируется внутри тестов; тексты отказов — литералы раздела 12.1.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_org
from tests import support_tasks as tasks

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc

MOVE_FORBIDDEN = "Нет права менять это поле задачи"
PLAN_FORBIDDEN = "Двигать карточки в чужом плане нельзя"
OVERDUE_MOVE = "Из «Просрочены» переносить нельзя"
BOARD_UNKNOWN = "Неизвестная доска"
VALUE_INVALID = "Неизвестное значение переноса"


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
    """Отказ переноса: 200, `[data-error="<поле>"][data-code="<код>"]`, текст раздела 12.1 внутри."""
    nodes = q(tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error={field}][data-code={code}] в ответе {response.status_code}"
    assert any(text in node.text() for node in nodes), f"нет текста «{text}» в отказе {code}"


def _fresh(task):
    return support.model("tasks.Task").objects.get(pk=task.pk)


# --- статус ----------------------------------------------------------------------------------------------------

def test_move_status_changes_status_and_sets_and_clears_completed_at():
    """FR-679, FR-680: перенос на «Стадиях» меняет статус; «Готово» ставит `completed_at`, возврат в работу его
    снимает; ответ HTMX — 200 без ошибки."""
    owner = tasks.staff_user()
    client = support.logged_in(owner)
    task = tasks.make_task(title="Задача", author=owner, assignee=owner)

    response = tasks.move(client, task, "status", "in_progress")
    assert response.status_code == 200, response.status_code
    assert _fresh(task).status == "in_progress"
    assert _fresh(task).completed_at is None

    response = tasks.move(client, task, "status", "done")
    assert response.status_code == 200
    finished = _fresh(task)
    assert finished.status == "done" and finished.completed_at is not None

    response = tasks.move(client, task, "status", "new")
    assert response.status_code == 200
    returned = _fresh(task)
    assert returned.status == "new" and returned.completed_at is None


def test_move_status_allowed_for_coexecutor_but_forbidden_for_observer():
    """FR-678, FR-679: статус меняют исполнитель и соисполнитель; наблюдатель видит задачу, но перенос статуса
    отклоняется — 200 с `board`/`move_forbidden`, статус не меняется."""
    owner = tasks.staff_user()
    coexecutor = tasks.staff_user()
    observer = tasks.staff_user()
    task = tasks.make_task(title="Задача", author=owner, assignee=owner)
    tasks.add_member(task, coexecutor, role="coexecutor")
    tasks.add_member(task, observer, role="observer")

    allowed = tasks.move(support.logged_in(coexecutor), task, "status", "waiting")
    assert allowed.status_code == 200
    assert _fresh(task).status == "waiting"

    denied = tasks.move(support.logged_in(observer), task, "status", "in_progress")
    assert denied.status_code == 200
    _error(denied, "board", "move_forbidden", MOVE_FORBIDDEN)
    assert _fresh(task).status == "waiting"


# --- срок ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("moment,expected", [
    (datetime(2026, 11, 18, 0, 30, tzinfo=UTC), date(2026, 11, 18)),
    (datetime(2026, 11, 18, 21, 30, tzinfo=UTC), date(2026, 11, 19)),
])
def test_move_deadline_today_uses_moscow_date(clock, moment, expected):
    """FR-681, NFR-717: «Сегодня» ставит сегодняшнюю дату по Москве — после полуночи UTC (21:00–23:59 UTC) это
    уже следующий день."""
    clock.set(moment)
    owner = tasks.staff_user()
    task = tasks.make_task(title="Задача", author=owner, assignee=owner)

    response = tasks.move(support.logged_in(owner), task, "deadline", "today")

    assert response.status_code == 200
    assert _fresh(task).deadline == expected


@pytest.mark.parametrize("today,expected", [
    (date(2026, 11, 18), date(2026, 11, 20)),  # среда -> пятница этой недели
    (date(2026, 11, 20), date(2026, 11, 27)),  # пятница -> следующая
    (date(2026, 11, 21), date(2026, 11, 27)),  # суббота -> ближайшая пятница после
    (date(2026, 11, 22), date(2026, 11, 27)),  # воскресенье
    (date(2026, 11, 23), date(2026, 11, 27)),  # понедельник
])
def test_move_deadline_week_sets_nearest_friday_strictly_after_today(clock, today, expected):
    """FR-681: «На неделе» ставит ближайшую пятницу строго после сегодня; в саму пятницу — следующую, а не
    сегодняшнюю."""
    clock.set(datetime(today.year, today.month, today.day, 12, 0, tzinfo=UTC))
    owner = tasks.staff_user()
    task = tasks.make_task(title="Задача", author=owner, assignee=owner)

    response = tasks.move(support.logged_in(owner), task, "deadline", "week")

    assert response.status_code == 200
    assert _fresh(task).deadline == expected


def test_move_deadline_none_clears_deadline_and_replans_reminders(clock):
    """FR-681, FR-690: «На неделе» пересчитывает автоматические напоминания по новому сроку, а «Без срока»
    снимает дату и не оставляет ожидающих напоминаний."""
    from apps.tasks.services import reminders

    clock.set(datetime(2026, 11, 18, 9, 0, tzinfo=UTC))
    owner = tasks.staff_user()
    task = tasks.make_task(title="Задача", author=owner, assignee=owner, deadline=date(2026, 12, 10))
    reminders.plan(task)
    before = tasks.reminders_of(task)
    assert before, "планировщик должен поставить автоматические напоминания"

    response = tasks.move(support.logged_in(owner), task, "deadline", "week")
    assert response.status_code == 200
    after = tasks.reminders_of(task)
    assert after, "напоминания должны пересчитаться, а не исчезнуть"
    assert {(row.kind, row.moment) for row in after} != {(row.kind, row.moment) for row in before}
    assert _fresh(task).deadline == date(2026, 11, 20)

    response = tasks.move(support.logged_in(owner), task, "deadline", "none")
    assert response.status_code == 200
    assert _fresh(task).deadline is None
    assert not [row for row in tasks.reminders_of(task) if row.state == "pending"], (
        "при снятии срока ожидающих напоминаний остаться не должно")


def test_move_to_overdue_column_is_refused(clock):
    """FR-681: из «Просрочены» переносить нельзя — 200 с `board`/`overdue_move`, срок не меняется."""
    from apps.core.widgets import moscow_today

    clock.set(datetime(2026, 11, 18, 9, 0, tzinfo=UTC))
    owner = tasks.staff_user()
    deadline = moscow_today() + timedelta(days=3)
    task = tasks.make_task(title="Задача", author=owner, assignee=owner, deadline=deadline)

    response = tasks.move(support.logged_in(owner), task, "deadline", "overdue")

    assert response.status_code == 200
    _error(response, "board", "overdue_move", OVERDUE_MOVE)
    assert _fresh(task).deadline == deadline


# --- личный план -----------------------------------------------------------------------------------------------

def test_move_plan_changes_only_column_for_plan_owner():
    """FR-682, FR-684: владелец плана переносит задачу в свою колонку — меняется только `plan_column`, статус
    остаётся прежним."""
    owner = tasks.staff_user()
    first = tasks.make_column(owner, title="Сегодня", position=0)
    later = tasks.make_column(owner, title="Потом", position=1)
    task = tasks.make_task(title="Задача", author=owner, assignee=owner, status="waiting")

    response = tasks.move(support.logged_in(owner), task, "plan", str(later.pk))

    assert response.status_code == 200
    fresh = _fresh(task)
    assert fresh.plan_column_id == later.pk
    assert fresh.status == "waiting"
    assert fresh.plan_column_id != first.pk


def test_move_plan_of_subordinate_is_forbidden_for_head():
    """FR-682, FR-678: руководитель видит задачу и план подчинённого, но двигать карточки в чужом плане нельзя —
    200 с `board`/`plan_forbidden`, колонка не меняется."""
    tree = support_org.make_tree({"Отдел": {}})
    employee = tasks.staff_user()
    support_org.make_member(employee, tree["Отдел"])
    head = tasks.head_of(tree["Отдел"])
    column = tasks.make_column(employee, title="Сегодня", position=0)
    task = tasks.make_task(title="Задача", author=employee, assignee=employee)

    response = tasks.move(support.logged_in(head), task, "plan", str(column.pk))

    assert response.status_code == 200
    _error(response, "board", "plan_forbidden", PLAN_FORBIDDEN)
    assert _fresh(task).plan_column_id is None


# --- категории -------------------------------------------------------------------------------------------------

def test_move_category_sets_category_and_none_clears_it():
    """FR-683: перенос в категорию ставит её задаче, перенос в «Без категории» (`value="none"`) снимает
    категорию, задача остаётся."""
    owner = tasks.staff_user()
    client = support.logged_in(owner)
    category = tasks.make_category(title="Работа", position=0)
    task = tasks.make_task(title="Задача", author=owner, assignee=owner)

    response = tasks.move(client, task, "category", str(category.pk))
    assert response.status_code == 200
    assert _fresh(task).category_id == category.pk

    response = tasks.move(client, task, "category", "none")
    assert response.status_code == 200
    assert _fresh(task).category_id is None
    assert support.model("tasks.Task").objects.filter(pk=task.pk).exists()


def test_move_deadline_and_category_need_field_edit_rights():
    """FR-678, FR-681, FR-683: срок и категорию меняет постановщик (права полей), а соисполнитель, который видит
    задачу и меняет статус, получает `board`/`move_forbidden`; значения не меняются."""
    author = tasks.staff_user()
    coexecutor = tasks.staff_user()
    category = tasks.make_category(title="Работа", position=0)
    task = tasks.make_task(title="Задача", author=author, assignee=author)
    tasks.add_member(task, coexecutor, role="coexecutor")
    client = support.logged_in(coexecutor)

    for board, value in (("deadline", "today"), ("category", str(category.pk))):
        response = tasks.move(client, task, board, value)
        assert response.status_code == 200
        _error(response, "board", "move_forbidden", MOVE_FORBIDDEN)
    fresh = _fresh(task)
    assert fresh.deadline is None and fresh.category_id is None


# --- неизвестные доска и значение -------------------------------------------------------------------------------

def test_move_unknown_board_and_value_are_rejected_without_changes():
    """FR-684: неизвестная доска — `board`/`board_unknown`, неизвестное значение — `board`/`value_invalid`;
    задача не меняется (CONTRACT-009, 6.2)."""
    owner = tasks.staff_user()
    client = support.logged_in(owner)
    task = tasks.make_task(title="Задача", author=owner, assignee=owner)

    unknown = tasks.move(client, task, "nope", "x")
    assert unknown.status_code == 200
    _error(unknown, "board", "board_unknown", BOARD_UNKNOWN)

    invalid = tasks.move(client, task, "status", "nope")
    assert invalid.status_code == 200
    _error(invalid, "board", "value_invalid", VALUE_INVALID)

    fresh = _fresh(task)
    assert (fresh.status, fresh.deadline, fresh.plan_column_id, fresh.category_id) == ("new", None, None, None)


# --- ответы: HTMX и обычный --------------------------------------------------------------------------------------

def test_move_htmx_returns_updated_columns_and_plain_post_redirects_to_board():
    """FR-680, FR-684, NFR-711: обычный POST — 302 на доску; HTMX — 200 фрагментом без `<html>` с обновлёнными
    колонками (`hx-swap-oob` на `[data-column]`), карточка уже в новой колонке."""
    owner = tasks.staff_user()
    client = support.logged_in(owner)
    first = tasks.make_task(title="Первая", author=owner, assignee=owner)
    second = tasks.make_task(title="Вторая", author=owner, assignee=owner)

    plain = client.post(f"/tasks/{first.pk}/move/", {"board": "status", "value": "in_progress"})
    assert plain.status_code == 302
    assert plain["Location"] == "/tasks/board/status/"
    assert _fresh(first).status == "in_progress"

    response = tasks.move(client, second, "status", "done")

    assert response.status_code == 200
    assert b"<html" not in response.content
    columns = q(tree(response), data_column=True)
    assert columns, "ответ HTMX должен содержать колонки"
    assert all("hx-swap-oob" in column.attrs for column in columns), "колонки меняются вне основного блока"
    rows = tasks.board_rows(response, "status")
    assert second.pk in rows["done"]
    assert second.pk not in rows["new"]