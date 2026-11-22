"""T-9301: сценарий 4 — доска «Стадии», перетаскивание и запасной путь (FR-679, FR-680, FR-684, NFR-711).

Общее для файла (CONTRACT-009, разделы 6.3, 7, 13.3; SPEC-009, сценарий 4; шаблон `e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера; задачи — `create_task`, доска —
  `open_tasks(new_context(), account, preset="board:status")`;
- колонки — `[data-column="new|in_progress|waiting|done"]` в порядке раздела 7, названия `[data-column-title]`,
  числа `[data-column-count]`, карточки `[data-task-card][data-task-id]` с `[data-task-title]`;
- перетаскивание — `helpers_tasks.move_card` (мышью, ждёт ответ `/move/`); «без перезагрузки» проверяется
  меткой `window.__t09_alive` на странице до и после переноса (NFR-711);
- запасной путь (FR-684) — выбор `[data-task-field="status"]` в карточке; кнопок «Начать»/«Завершить»
  контракт зацепками не называет.
"""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import board_titles, create_task, move_card, open_card, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

STATUSES = ("new", "in_progress", "waiting", "done")
TITLES = ("Новая", "В работе", "Ждёт", "Готово")
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 4: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _status(page, task_id):
    """Элемент со статусом задачи в карточке или на карточке доски (6.3)."""
    return page.locator(f'[data-task-id="{task_id}"][data-task-status], '
                        f'[data-task-id="{task_id}"] [data-task-status]').first


def _set_status(page, task_id, value: str) -> None:
    """Меняет статус запасным путём карточки (FR-684)."""
    form = page.locator('form[data-task-field="status"]')
    expect(form).to_be_visible()
    form.locator('[data-task-field="status"]').select_option(value)
    form.locator("button[type=submit]").first.click()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", value)


def test_t09_04_board_has_four_status_columns_in_order_with_titles_and_counts(cast, new_context):
    """Сценарий 4, п. 1 (FR-680): доска «Стадии» показывает четыре колонки в порядке «Новая», «В работе»,
    «Ждёт», «Готово»; в шапке каждой — число задач, совпадающее с числом карточек."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Новая")
    task_id = create_task(page, title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:status")
    expect(board.locator('[data-board="status"]')).to_be_visible()
    keys = board.locator("[data-column]").evaluate_all("els => els.map(e => e.getAttribute('data-column'))")
    assert keys == list(STATUSES), f"колонки доски «Стадии»: {keys}"
    titles = [text.strip() for text in board.locator("[data-column-title]").all_inner_texts()]
    assert titles == list(TITLES), f"названия колонок: {titles}"

    fresh = board.locator('[data-column="new"]')
    expect(fresh.locator(f'[data-task-card][data-task-id="{task_id}"]')).to_be_visible()
    expect(fresh.locator("[data-column-title]")).to_have_text("Новая")
    for key in STATUSES:
        column = board.locator(f'[data-column="{key}"]')
        count_text = column.locator("[data-column-count]").inner_text()
        number = int(re.search(r"\d+", count_text).group(0))
        assert number == column.locator("[data-task-card][data-task-id]").count(), (
            f"число в шапке колонки {key} не совпало с карточками")


def test_t09_04_drag_from_new_to_done_changes_status_without_page_reload(cast, new_context):
    """Сценарий 4, п. 2 (FR-680, NFR-711): исполнитель перетаскивает свою карточку из «Новой» в «Готово» —
    статус меняется без перезагрузки, карточка остаётся в «Готово»."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Перетащить")
    task_id = create_task(page, title, assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:status")
    board.evaluate("() => { window.__t09_alive = true; }")
    move_card(board, task_id, "status", "done")

    assert board.evaluate("() => window.__t09_alive === true"), "доска перезагрузилась при переносе"
    expect(board.locator(f'[data-column="done"] [data-task-card][data-task-id="{task_id}"]')).to_be_visible()
    assert title in board_titles(board)["done"], f"карточки «{title}» нет в «Готово»"
    assert title not in board_titles(board)["new"], "карточка осталась в «Новой»"
    expect(_status(board, task_id)).to_have_attribute("data-task-status", "done")


def test_t09_04_fallback_status_select_in_card_changes_status(cast, new_context):
    """Сценарий 4, п. 4 (FR-684): без перетаскивания статус меняется выбором в карточке; выбранный статус
    сохраняется после перезагрузки."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Без мыши"), assignee=employee)

    _set_status(page, task_id, "waiting")
    page.reload()
    page.wait_for_load_state()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", "waiting")

    card = open_card(new_context(), employee, task_id)
    expect(card.locator('form[data-task-field="status"] [data-task-field="status"]')).to_have_value("waiting")