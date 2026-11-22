"""T-9301: сценарий 3 — список задач, пресеты, фильтры и страницы (FR-685, FR-686).

Общее для файла (CONTRACT-009, разделы 6.1–6.3, 13.3; SPEC-009, сценарий 3; план, «Проход в браузере»;
шаблон `e2e/template.md`):
- люди и узлы — `helpers_tasks.tasks_cast` один раз на круг браузера (фикстура `cast`); сессии учёток
  переносятся помощниками `open_tasks`/`open_card`, свои контексты закрывает `conftest.py`;
- локаторы — только зацепки 6.3: `[data-tasks-page]`, `[data-task-id]`, `[data-task-title]`,
  `[data-task-status]`, `[data-tasks-preset]`, `[data-error][data-code]`; строки списка — внутри `#tasks-list`
  (адрес фрагмента назван в 6.2), чтобы карточка рядом на широком экране не смешивалась со строками;
- «сегодня» — по Москве (NFR-717; Москва без перехода на летнее время, как `test_l08_deadlines.py`);
- названия задач уникальны на круг (`helpers_org.unique_name`): стенд между тестами не сбрасывается;
- массовая подготовка страниц (21 задача) — прямыми POST формы `/tasks/` от имени сотрудника
  (`helpers_org.direct_post`, успех — 302 раздела 6.2), как в `test_l03_table.py`; остальное — `create_task`;
- «Просрочены» (сценарий 3, п. 2) в браузере не проверяется: срок раньше сегодняшнего форма не принимает
  (`deadline_past`, 12.1), а сдвига времени у задач нет — правило группы остаётся серверному `test_tasks_list`;
- «без перезагрузки страницы» (п. 4) отдельной зацепкой не названо: проверяется выдача страниц 20/50, а не
  способ подгрузки.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import create_task, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

MOSCOW = timezone(timedelta(hours=3))
PRESETS = ("mine", "authored", "subordinate", "work", "overdue")
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 3: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _day(offset: int = 0) -> str:
    """Дата «сегодня по Москве» плюс `offset` дней в виде ДД.ММ.ГГГГ (дата хоста не берётся)."""
    return (datetime.now(MOSCOW).date() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _row(page, task_id):
    """Строка списка по номеру задачи: только внутри `#tasks-list`."""
    return page.locator(f'#tasks-list [data-task-id="{task_id}"]')


def _titles(page) -> list:
    """Названия строк текущей страницы списка сверху вниз."""
    return page.locator("#tasks-list [data-task-title]").all_inner_texts()


def test_t09_01_presets_and_row_fields_show_number_title_assignee_deadline_and_status(cast, new_context):
    """Сценарий 3, п. 1 (FR-685): у сотрудника видны все пять пресетов; в «Моих» строка несёт номер, название,
    исполнителя, срок и статус «Новая», выбранный пресет отмечен `aria-pressed`."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    title = helpers_org.unique_name("Список")
    task_id = create_task(page, title, deadline=_day(3), assignee=employee)

    page.goto("/tasks/?preset=mine")
    expect(page.locator('[data-tasks-page="list"]')).to_be_visible()
    expect(page.locator('[data-tasks-preset="mine"]')).to_have_attribute("aria-pressed", "true")

    row = _row(page, task_id)
    expect(row).to_be_visible()
    expect(row.locator("[data-task-title]")).to_have_text(title)
    expect(row).to_contain_text(f"#{task_id}")
    expect(row).to_contain_text(employee.full_name)
    expect(row).to_contain_text(_day(3))
    status = page.locator(f'[data-task-id="{task_id}"][data-task-status], '
                          f'[data-task-id="{task_id}"] [data-task-status]').first
    expect(status).to_have_attribute("data-task-status", "new")

    # «Задачи подчинённых» — пресет руководителя (и заместителя): у главы узла видны все пять
    head_page = open_tasks(new_context(), cast.head)
    for name in PRESETS:
        expect(head_page.locator(f'[data-tasks-preset="{name}"]')).to_be_visible()


def test_t09_01_assignee_filter_narrows_list_and_preset_click_returns_to_preset(cast, new_context):
    """Сценарий 3, п. 3 (FR-685, FR-686): фильтр по исполнителю оставляет только задачи выбранного человека,
    а нажатие пресета «Поставленные мной» возвращает полный список пресета без фильтра."""
    head, employee = cast.head, cast.employee
    page = open_tasks(new_context(), head)
    own = create_task(page, helpers_org.unique_name("Себе"), assignee=head)
    subordinate = create_task(page, helpers_org.unique_name("Подчинённому"), assignee=employee)

    page.goto("/tasks/?preset=authored")
    expect(_row(page, own)).to_be_visible()
    expect(_row(page, subordinate)).to_be_visible()

    page.goto(f"/tasks/?preset=authored&assignee={employee.id}")
    expect(_row(page, subordinate)).to_be_visible()
    expect(_row(page, own)).to_have_count(0)

    page.locator('[data-tasks-preset="authored"]').click()
    expect(_row(page, own)).to_be_visible()
    expect(_row(page, subordinate)).to_be_visible()
    expect(page).to_have_url(re.compile(r"/tasks/\?preset=authored$"))


def test_t09_01_pages_of_20_and_50_show_the_rest_without_repetition(cast, new_context):
    """Сценарий 3, п. 4 (FR-685): при 21 задаче страница `per_page=20` показывает ровно 20 строк, вторая
    страница — остальные без повторов, а `per_page=50` отдаёт все 21; порядок страниц не пересекается."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    prefix = helpers_org.unique_name("Страницы")
    created = []
    for index in range(21):
        title = f"{prefix} {index:02d}"
        response = helpers_org.direct_post(
            page, "/tasks/", {"title": title, "assignee": str(employee.id)})
        assert response.status == 302, f"задача «{title}» не создана прямым POST: {response.status}"
        created.append(title)

    first = open_tasks(new_context(), employee, preset="mine", per_page="20", page="1")
    expect(first.locator("#tasks-list [data-task-id]")).to_have_count(20)
    second = open_tasks(new_context(), employee, preset="mine", per_page="20", page="2")
    second_ids = second.locator("#tasks-list [data-task-id]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-task-id'))")
    first_ids = first.locator("#tasks-list [data-task-id]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-task-id'))")
    assert second_ids, "вторая страница пуста: 21-я задача не показана"
    assert not set(first_ids) & set(second_ids), "страницы повторили строки"

    wide = open_tasks(new_context(), employee, preset="mine", per_page="50", page="1")
    expect(wide.locator("#tasks-list [data-task-id]").first).to_be_visible()
    count = wide.locator("#tasks-list [data-task-id]").count()
    assert len(created) <= count <= 50, f"страница per_page=50 показала {count} строк"
    assert set(created) <= set(_titles(wide)), "на странице 50 не все созданные задачи"