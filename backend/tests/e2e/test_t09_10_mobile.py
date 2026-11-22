"""T-9301: сценарии 14 и 12 — телефон 360 px, права и чужая задача (FR-677, FR-699, NFR-716).

Общее для файла (CONTRACT-009, разделы 4, 6.1–6.3, 13.3; SPEC-009, сценарии 12 и 14; шаблон `e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера: `employee` (исполнитель), `head` (руководитель
  его узла), `admin` (администратор портала), `outsider` («Бухгалтерия»);
- телефон — `helpers_tasks.check_360`: ширина 360 px, горизонтальной прокрутки страницы нет; у доски прокрутка
  только внутри `[data-board]` (FR-699, NFR-716);
- возврат из карточки в список — ссылка карточки на `/tasks/` (адрес 6.2); «Назад» отдельной зацепки 6.3 не
  имеет;
- запасной путь статуса на 360 px — `[data-task-field="status"]` в карточке (FR-684);
- чужая задача: администратор и сотрудник другого узла получают 404 «Не найдено» (6.1, FR-677) — проверяется
  ответом `direct_get` и отсутствием названия в теле; положительный контроль — автор и руководитель узла
  исполнителя карточку видят. Перевод сотрудника между узлами (п. 3 сценария 12) — серверный `test_tasks_list`.
"""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import check_360, create_task, open_card, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

TASK_URL = re.compile(r"/tasks/(\d+)/$")
BACK_LINKS = ('[data-tasks-page="card"] a[href="/tasks/"], '
              '[data-tasks-page="card"] a[href^="/tasks/?"]')
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценариев 12 и 14: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _status(page, task_id):
    """Элемент со статусом задачи в карточке (6.3)."""
    return page.locator(f'[data-task-id="{task_id}"][data-task-status], '
                        f'[data-task-id="{task_id}"] [data-task-status]').first


def _set_status(page, task_id, value: str) -> None:
    """Меняет статус запасным путём карточки (FR-684)."""
    form = page.locator('form[data-task-field="status"]')
    expect(form).to_be_visible()
    form.locator('[data-task-field="status"]').select_option(value)
    form.locator("button[type=submit]").first.click()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", value)


def test_t09_10_list_at_360_has_no_page_scroll_and_card_returns_to_list(cast, new_context):
    """Сценарий 14, пп. 1–2 (FR-699, NFR-716): на 360 px список и карточка без горизонтальной прокрутки
    страницы, нажатие на задачу открывает карточку, ссылка карточки возвращает к списку."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Телефон")
    task_id = create_task(page, title, assignee=employee)

    page.goto("/tasks/")
    check_360(page)
    row = page.locator(f'#tasks-list [data-task-id="{task_id}"]')
    expect(row).to_be_visible()
    row.locator("[data-task-title]").click()
    page.wait_for_url(TASK_URL)
    expect(page.locator('[data-tasks-page="card"]')).to_be_visible()
    check_360(page)

    page.locator(BACK_LINKS).first.click()
    expect(page.locator('[data-tasks-page="list"]')).to_be_visible()
    page.wait_for_url(re.compile(r"/tasks/(\?|$)"))
    assert not page.url.endswith(f"/tasks/{task_id}/"), "«Назад» осталась на карточке"


def test_t09_10_board_at_360_scrolls_inside_and_status_fallback_works(cast, new_context):
    """Сценарий 14, п. 3 и сценарий 4, п. 4 (FR-699, FR-684): доска на 360 px прокручивается внутри
    `[data-board]`, страница — нет; статус меняется выбором в карточке."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Доска 360"), assignee=employee)

    board = open_tasks(new_context(), employee, preset="board:status")
    check_360(board)
    expect(board.locator('[data-board="status"]')).to_be_visible()

    card = open_card(new_context(), employee, task_id)
    check_360(card)
    _set_status(card, task_id, "in_progress")
    expect(_status(card, task_id)).to_have_attribute("data-task-status", "in_progress")


def test_t09_10_admin_and_outsider_get_404_for_foreign_task_while_head_sees_it(cast, new_context):
    """Сценарий 12, пп. 1–2 (FR-677): администратор портала и сотрудник другого узла по прямому адресу получают
    404 «Не найдено» без названия задачи; автор и руководитель узла исполнителя карточку видят."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Приватная")
    task_id = create_task(page, title, assignee=employee)

    author = open_card(new_context(), employee, task_id)
    expect(author.locator('[data-tasks-page="card"]')).to_contain_text(title)
    head = open_card(new_context(), cast.head, task_id)
    expect(head.locator('[data-tasks-page="card"]')).to_contain_text(title)

    for account in (cast.admin, cast.outsider):
        viewer = open_tasks(new_context(), account)
        response = helpers_org.direct_get(viewer, f"/tasks/{task_id}/")
        assert response.status == 404, f"чужая задача открылась ({response.status})"
        assert title not in response.text(), "404 раскрывает название чужой задачи"