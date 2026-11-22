"""T-9301: сценарий 7 — категории администратора и доска категорий (FR-683, FR-684, FR-678).

Общее для файла (CONTRACT-009, разделы 4, 6.2–6.3, 7, 12.1, 13.3; SPEC-009, сценарий 7; шаблон
`e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера: справочник ведёт `admin`, задачи ставят
  `employee` и `head`;
- справочник — `/settings/tasks/categories/` (`[data-tasks-page="settings"]`, поле `title`, успех — 302 на ту же
  страницу). Форма создания ищется по адресу 6.2: отдельной зацепки `data-form` контракт для неё не даёт;
- доска — `open_tasks(..., preset="board:category")`: `[data-board="category"]`, колонки `[data-column]` по
  `position`, «Без категории» (ключ `none`) последней (решение К19); карточки — `[data-task-id]`;
- перенос меняет категорию, перенос в `none` её снимает; у сотрудника без права правки полей (исполнитель
  чужой задачи) перенос отклоняется причиной `move_forbidden` (200 с причиной, 6.2) — отправляется прямым POST
  от его сессии по тому же адресу `/move/`;
- удаление категории (п. 1) отдельной зацепки не имеет и остаётся серверному `test_tasks_categories`.
"""
import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import create_task, move_card, open_card, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

NONE_TITLE = "Без категории"
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 7: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _create_category(page, title: str) -> None:
    """Создаёт категорию формой справочника; ждёт её название на странице (успех — 302 назад)."""
    page.goto("/settings/tasks/categories/")
    expect(page.locator('[data-tasks-page="settings"]')).to_be_visible()
    form = page.locator('form[action="/settings/tasks/categories/"]')
    expect(form).to_be_visible()
    form.locator('[name="title"]').fill(title)
    form.locator("button[type=submit]").first.click()
    expect(page.locator('[data-tasks-page="settings"]')).to_contain_text(title)


def _column_key(page, title: str) -> str:
    """Ключ колонки доски по названию `[data-column-title]`."""
    for column in page.locator("[data-column]").all():
        if column.locator("[data-column-title]").inner_text().strip() == title:
            return column.get_attribute("data-column")
    raise AssertionError(f"на доске нет колонки «{title}»")


def _column(page, key: str):
    return page.locator(f'[data-column="{key}"]')


def test_t09_07_admin_category_is_available_in_task_form_and_task_keeps_it(cast, new_context):
    """Сценарий 7, п. 1 (FR-683): администратор добавляет категорию — она появляется в выборе категории формы
    задачи; созданная с ней задача хранит эту категорию в карточке."""
    title = helpers_org.unique_name("Категория")
    admin = open_tasks(new_context(), cast.admin)
    _create_category(admin, title)

    employee = cast.employee
    page = open_tasks(new_context(), employee)
    page.goto("/tasks/new/")
    select = page.locator('[data-task-field="category"]')
    expect(select).to_be_visible()
    option = select.locator("option").filter(has_text=title)
    expect(option).to_have_count(1)
    value = option.get_attribute("value")
    assert value, "у категории нет значения в выборе категории"

    task_id = create_task(page, helpers_org.unique_name("С категорией"), category=value)
    card = open_card(new_context(), employee, task_id)
    expect(card.locator('form[data-task-field="category"] [data-task-field="category"]')).to_have_value(value)


def test_t09_07_category_board_places_uncategorized_last_and_move_changes_category(cast, new_context):
    """Сценарий 7, п. 2 (FR-683): на доске «Категории» колонки идут по порядку справочника, «Без категории»
    последняя; перенос карточки в категорию ставит её, перенос в «Без категории» снимает."""
    title = helpers_org.unique_name("Доска")
    admin = open_tasks(new_context(), cast.admin)
    _create_category(admin, title)

    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_title = helpers_org.unique_name("Без категории")
    task_id = create_task(page, task_title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:category")
    expect(board.locator('[data-board="category"]')).to_be_visible()
    keys = board.locator("[data-column]").evaluate_all("els => els.map(e => e.getAttribute('data-column'))")
    assert keys[-1] == "none", f"«Без категории» не последняя: {keys}"
    expect(_column(board, "none").locator("[data-column-title]")).to_have_text(NONE_TITLE)
    category = _column_key(board, title)
    expect(_column(board, "none").locator(f'[data-task-id="{task_id}"]')).to_be_visible()

    move_card(board, task_id, "category", category)
    expect(_column(board, category).locator(f'[data-task-id="{task_id}"]')).to_be_visible()
    card = open_card(new_context(), employee, task_id)
    expect(card.locator('form[data-task-field="category"] [data-task-field="category"]')
           ).to_have_value(category)

    board = open_tasks(new_context(), employee, preset="board:category")
    move_card(board, task_id, "category", "none")
    expect(_column(board, "none").locator(f'[data-task-id="{task_id}"]')).to_be_visible()
    card = open_card(new_context(), employee, task_id)
    expect(card.locator('form[data-task-field="category"] [data-task-field="category"]')).to_have_value("")


def test_t09_07_executor_without_field_right_cannot_move_card_between_categories(cast, new_context):
    """Сценарий 7, п. 3 (FR-683, FR-678): исполнитель чужой задачи (поля правит постановщик) пробует перенести
    карточку в категорию — переноса нет, причина `move_forbidden`, карточка остаётся в «Без категории»."""
    title = helpers_org.unique_name("Запрет")
    admin = open_tasks(new_context(), cast.admin)
    _create_category(admin, title)

    head, employee = cast.head, cast.employee
    head_page = open_tasks(new_context(), head)
    task_title = helpers_org.unique_name("Чужая")
    task_id = create_task(head_page, task_title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:category")
    category = _column_key(board, title)
    assert task_title in [
        text.strip() for text in _column(board, "none").locator("[data-task-title]").all_inner_texts()], (
        "задача исполнителя не в «Без категории»")

    response = helpers_org.direct_post(
        board, f"/tasks/{task_id}/move/", {"board": "category", "value": category})
    assert response.status == 200, f"перенос без права ответил {response.status}"
    assert "move_forbidden" in response.text(), "перенос без права не назвал причину move_forbidden"

    again = open_tasks(new_context(), employee, preset="board:category")
    expect(_column(again, "none").locator(f'[data-task-id="{task_id}"]')).to_be_visible()
    expect(_column(again, category).locator(f'[data-task-id="{task_id}"]')).to_have_count(0)