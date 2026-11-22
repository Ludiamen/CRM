"""T-9301: сценарий 1 — личная задача от создания до «Готово» (FR-674…FR-679, FR-684).

Общее для файла (CONTRACT-009, разделы 6.1–6.3, 12.1, 13.3; SPEC-009, сценарий 1; шаблон `e2e/template.md`):
- учётки и узлы — `helpers_tasks.tasks_cast` один раз на круг браузера (фикстура `cast`);
- создание — `helpers_tasks.create_task` (форма `[data-form="task-new"]`, поля `[data-task-field]`); карточка —
  `open_card`, список — `open_tasks`; сроки — «сегодня по Москве» плюс дни, формат ДД.ММ.ГГГГ;
- статус меняется запасным путём карточки (FR-684): `form[data-task-field="status"]` с выбором статуса — это
  зацепка 6.3; отдельных зацепок у кнопок «Начать»/«Завершить» контракт не даёт, поэтому сценарий проверяется
  тем же полем, каким пользуется помощник `move_card` при недоступном перетаскивании;
- отказ формы — `[data-error="title"][data-code="title_range"]` с текстом 12.1; `sleep` нет, ожидание — `expect`.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import create_task, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

MOSCOW = timezone(timedelta(hours=3))
TASK_URL = re.compile(r"/tasks/(\d+)/$")
TITLE_TEXT = "Название задачи — от 1 до 300 знаков"
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 1: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _day(offset: int = 0) -> str:
    """Дата «сегодня по Москве» плюс `offset` дней в виде ДД.ММ.ГГГГ."""
    return (datetime.now(MOSCOW).date() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _status(page, task_id):
    """Элемент со статусом задачи — на строке списка или в карточке (6.3)."""
    return page.locator(f'[data-task-id="{task_id}"][data-task-status], '
                        f'[data-task-id="{task_id}"] [data-task-status]').first


def _set_status(page, task_id, value: str) -> None:
    """Меняет статус запасным путём карточки (FR-684) и ждёт новый статус в разметке."""
    form = page.locator('form[data-task-field="status"]')
    expect(form).to_be_visible()
    form.locator('[data-task-field="status"]').select_option(value)
    form.locator("button[type=submit]").first.click()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", value)


def test_t09_02_created_task_is_in_my_preset_with_number_author_assignee_deadline_and_status(cast, new_context):
    """Сценарий 1, п. 1 (FR-674, FR-675, FR-685): сотрудник создаёт задачу с описанием и сроком, назначает
    исполнителем себя — задача появляется в «Моих» со статусом «Новая», а в карточке видны номер, постановщик,
    исполнитель, срок и статус."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Личная")
    task_id = create_task(page, title, description="Описание личной задачи", deadline=_day(2),
                          assignee=employee)

    expect(page.locator('[data-tasks-page="card"]')).to_be_visible()
    assert TASK_URL.search(page.url).group(1) == str(task_id)
    card = page.locator('[data-tasks-page="card"]')
    expect(card).to_contain_text(f"#{task_id}")
    expect(card).to_contain_text(employee.full_name)
    expect(card).to_contain_text(_day(2))
    expect(_status(page, task_id)).to_have_attribute("data-task-status", "new")

    page.goto("/tasks/?preset=mine")
    row = page.locator(f'#tasks-list [data-task-id="{task_id}"]')
    expect(row).to_be_visible()
    expect(row.locator("[data-task-title]")).to_have_text(title)
    expect(_status(page, task_id)).to_have_attribute("data-task-status", "new")


def test_t09_02_executor_moves_task_to_work_and_done_and_it_stays_in_done(cast, new_context):
    """Сценарий 1, п. 2 (FR-679, FR-684): исполнитель переводит свою задачу в «В работе», затем в «Готово»;
    статус сохраняется после перезагрузки карточки, и завершённая задача остаётся в «Моих» со статусом «Готово»."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Довести"), deadline=_day(1), assignee=employee)

    _set_status(page, task_id, "in_progress")
    _set_status(page, task_id, "done")

    page.reload()
    page.wait_for_load_state()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", "done")

    page.goto("/tasks/?preset=mine")
    row = page.locator(f'#tasks-list [data-task-id="{task_id}"]')
    expect(row).to_be_visible()
    expect(_status(page, task_id)).to_have_attribute("data-task-status", "done")


def test_t09_02_empty_and_301_character_titles_are_refused_at_the_field(cast, new_context):
    """Сценарий 1, п. 3 (FR-674): пустое название и название длиннее 300 знаков не создают задачу — причина
    показана у поля `title` (12.1), страница остаётся формой создания."""
    page = open_tasks(new_context(), cast.employee)
    page.goto("/tasks/new/")
    expect(page.locator('[data-tasks-page="new"]')).to_be_visible()
    form = page.locator('form[data-form="task-new"]')
    expect(form).to_be_visible()

    form.locator('[data-task-field="title"]').fill("")
    form.locator("button[type=submit]").first.click()
    expect(page.locator('[data-error="title"][data-code="title_range"]')).to_contain_text(TITLE_TEXT)
    expect(page).to_have_url(re.compile(r"/tasks/new/$"))

    form.locator('[data-task-field="title"]').fill("я" * 301)
    form.locator("button[type=submit]").first.click()
    expect(page.locator('[data-error="title"][data-code="title_range"]')).to_contain_text(TITLE_TEXT)
    expect(page).to_have_url(re.compile(r"/tasks/new/$"))