"""T-9301: сценарий 6 — «Мой план», колонки и чужой план только для чтения (FR-682, FR-684, FR-678).

Общее для файла (CONTRACT-009, разделы 4, 6.2–6.3, 7, 12.1, 13.3; SPEC-009, сценарий 6; шаблон
`e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера; задачи — `create_task`; доска плана —
  `open_tasks(new_context(), account, preset="board:plan")`, чужой план — тот же вызов с `user=<номер>`;
- колонки — `[data-plan-column="<id>"]` с `[data-column-title]` (порядок — `helpers_tasks.plan_columns`),
  у чужого плана — `[data-plan-readonly]`; карточки — `[data-task-id]`, запасной путь — `plan_column` (FR-684);
- первый вход создаёт три колонки «Сегодня», «На этой неделе», «Потом» (FR-682); задача без колонки — в первой;
- перенос меняет только колонку: статус задачи после переноса остаётся прежним;
- чужой план: руководитель видит колонки и карточки, но перенос получает `plan_forbidden` (200 с причиной,
  раздел 6.2); сам перенос отправляется прямым POST от его сессии — тот же адрес `/move/`, что у перетаскивания;
- «добавить/переименовать/удалить колонку» (п. 2) зацепок 6.3 не имеет, кроме `[data-plan-column]`; эти действия
  остаются серверному `test_tasks_plan`.
"""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import create_task, move_card, open_card, open_tasks, plan_columns, tasks_cast

pytestmark = pytest.mark.e2e

DEFAULTS = ["Сегодня", "На этой неделе", "Потом"]
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 6: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _column_ids(page) -> list:
    """Номера колонок плана по порядку (`data-plan-column`)."""
    return page.locator("[data-plan-column]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-plan-column'))")


def _status(page, task_id):
    """Элемент со статусом задачи в карточке (6.3)."""
    return page.locator(f'[data-task-id="{task_id}"][data-task-status], '
                        f'[data-task-id="{task_id}"] [data-task-status]').first


def test_t09_06_first_open_creates_three_columns_and_task_without_column_is_in_first(cast, new_context):
    """Сценарий 6, п. 1 (FR-682): при первом открытии «Моего плана» видны три колонки «Сегодня», «На этой
    неделе», «Потом», задача без личной колонки стоит в первой."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("План")
    task_id = create_task(page, title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:plan")
    expect(board.locator('[data-board="plan"]')).to_be_visible()
    assert plan_columns(board) == DEFAULTS, f"колонки первого входа: {plan_columns(board)}"
    first = board.locator("[data-plan-column]").first
    expect(first.locator(f'[data-task-id="{task_id}"]')).to_be_visible()


def test_t09_06_move_between_columns_changes_only_plan_column_not_status(cast, new_context):
    """Сценарий 6, п. 2 (FR-682): перенос карточки во вторую колонку меняет только личную колонку; статус
    задачи остаётся «Новая», а выбор `plan_column` в карточке показывает новую колонку."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Переложить")
    task_id = create_task(page, title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:plan")
    ids = _column_ids(board)
    assert len(ids) >= 2, f"у плана меньше двух колонок: {ids}"
    target = ids[1]
    move_card(board, task_id, "plan", target)

    expect(board.locator(f'[data-plan-column="{target}"] [data-task-id="{task_id}"]')).to_be_visible()
    expect(board.locator(f'[data-plan-column="{ids[0]}"] [data-task-id="{task_id}"]')).to_have_count(0)

    card = open_card(new_context(), employee, task_id)
    expect(_status(card, task_id)).to_have_attribute("data-task-status", "new")
    expect(card.locator('form[data-task-field="plan_column"] [data-task-field="plan_column"]')
           ).to_have_value(target)


def test_t09_06_foreign_plan_is_readonly_for_head_and_move_is_refused(cast, new_context):
    """Сценарий 6, п. 3 (FR-682, FR-678): руководитель открывает план подчинённого — видит колонки и карточки,
    страница помечена `[data-plan-readonly]`, перенос отклоняется причиной `plan_forbidden`, карточка не
    двигается."""
    head, employee = cast.head, cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Чужой план")
    task_id = create_task(page, title, assignee=employee)

    board = open_tasks(new_context(), head, preset="board:plan", user=str(employee.id))
    expect(board.locator("[data-plan-readonly]").first).to_be_visible()
    expect(board.locator(f'[data-task-id="{task_id}"]')).to_be_visible()
    ids = _column_ids(board)
    assert len(ids) >= 2, f"у плана подчинённого меньше двух колонок: {ids}"

    response = helpers_org.direct_post(
        board, f"/tasks/{task_id}/move/", {"board": "plan", "value": ids[1]})
    assert response.status == 200, f"перенос в чужом плане ответил {response.status}"
    assert "plan_forbidden" in response.text(), "перенос в чужом плане не назвал причину plan_forbidden"

    again = open_tasks(new_context(), head, preset="board:plan", user=str(employee.id))
    expect(again.locator(f'[data-plan-column="{ids[0]}"] [data-task-id="{task_id}"]')).to_be_visible()