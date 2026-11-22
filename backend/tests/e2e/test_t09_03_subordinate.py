"""T-9301: сценарий 2 — руководитель ставит задачу подчинённому (FR-676, FR-677, FR-685, FR-686).

Общее для файла (CONTRACT-009, разделы 4, 6.1–6.3, 12.1, 13.3; SPEC-009, сценарий 2; шаблон `e2e/template.md`):
- учётки и узлы — `helpers_tasks.tasks_cast` один раз на круг браузера (фикстура `cast`): `head` — руководитель
  «Отдела ИТ», `deputy` — его заместитель, `employee` — сотрудник отдела, `peer` — сотрудник вложенного узла,
  `outsider` — «Бухгалтерия»;
- задача ставится формой `create_task` (`[data-task-field="assignee"]`); пресеты списка — зацепки
  `[data-tasks-preset]`, строки — `[data-task-id]` внутри `#tasks-list`;
- «на момент просмотра» (FR-686) в браузере проверяется тем, что обе стороны видят одну и ту же задачу сразу
  после её создания; перевод между узлами — серверный `test_tasks_list`;
- рядовой сотрудник не ставит задачу другому (п. 2): форма получает отказ у поля `assignee`
  (`[data-error="assignee"][data-code="assignee_forbidden"]`, текст 12.1) и остаётся на `/tasks/new/`.
"""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import create_task, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

FORBIDDEN = "Поставить задачу этому сотруднику нельзя"
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценария 2: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _row(page, task_id):
    """Строка списка по номеру задачи (только `#tasks-list`)."""
    return page.locator(f'#tasks-list [data-task-id="{task_id}"]')


def test_t09_03_head_task_to_employee_is_visible_to_both_in_mine_and_subordinate(cast, new_context):
    """Сценарий 2, п. 1 (FR-676, FR-677, FR-686): руководитель ставит задачу сотруднику своего узла — она видна
    исполнителю в «Моих», руководителю в «Задачах подчинённых» и в «Поставленных мной»."""
    head, employee = cast.head, cast.employee
    head_page = open_tasks(new_context(), head)
    title = helpers_org.unique_name("Подчинённому")
    task_id = create_task(head_page, title, assignee=employee)

    employee_page = open_tasks(new_context(), employee)
    expect(_row(employee_page, task_id)).to_be_visible()
    expect(_row(employee_page, task_id).locator("[data-task-title]")).to_have_text(title)

    subordinate = open_tasks(new_context(), head, preset="subordinate")
    expect(_row(subordinate, task_id)).to_be_visible()
    authored = open_tasks(new_context(), head, preset="authored")
    expect(_row(authored, task_id)).to_be_visible()


def test_t09_03_deputy_sets_task_to_nested_unit_member(cast, new_context):
    """Сценарий 2, п. 1 (FR-676, FR-686): заместитель узла ставит задачу сотруднику вложенного узла — исполнитель
    видит её в «Моих», заместитель — в «Задачах подчинённых»."""
    deputy, peer = cast.deputy, cast.peer
    page = open_tasks(new_context(), deputy)
    title = helpers_org.unique_name("Вложенному")
    task_id = create_task(page, title, assignee=peer)

    peer_page = open_tasks(new_context(), peer)
    expect(_row(peer_page, task_id)).to_be_visible()
    expect(_row(peer_page, task_id).locator("[data-task-title]")).to_have_text(title)

    subordinate = open_tasks(new_context(), deputy, preset="subordinate")
    expect(_row(subordinate, task_id)).to_be_visible()


def test_t09_03_plain_employee_cannot_assign_task_to_another_employee(cast, new_context):
    """Сценарий 2, п. 2 (FR-676): рядовой сотрудник выбирает исполнителем другого сотрудника — форма отклоняет
    выбор причиной у поля `assignee`, задача не создаётся, страница остаётся формой создания."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    page.goto("/tasks/new/")
    expect(page.locator('[data-tasks-page="new"]')).to_be_visible()
    form = page.locator('form[data-form="task-new"]')
    expect(form).to_be_visible()

    form.locator('[data-task-field="title"]').fill(helpers_org.unique_name("Чужому"))
    form.locator('[data-task-field="assignee"]').select_option(str(cast.peer.id))
    form.locator("button[type=submit]").first.click()

    expect(page.locator('[data-error="assignee"][data-code="assignee_forbidden"]')).to_contain_text(FORBIDDEN)
    expect(page).to_have_url(re.compile(r"/tasks/new/$"))