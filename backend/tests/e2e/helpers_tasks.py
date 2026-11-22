"""Помощники приёмки среза 009 «Задачи» (T-9007; ими пользуются тесты `test_t09_*`).

Что здесь есть (CONTRACT-009: разделы 1.4, 6.2, 6.3, 13.3):
- роли и учётки сценариев: `TasksCast`, `tasks_cast` (`employee`, `peer`, `head`, `deputy`, `outsider`, `admin`,
  `dismissed`; узлы «Отдел ИТ», вложенный узел и «Бухгалтерия»);
- вход и страницы: `open_tasks(context, account, …)`, `open_card(context, account, task_id)`;
- создание: `create_task(page, title, …)`;
- доски: `move_card(page, task_id, board, column)`, `board_titles(page)`, `plan_columns(page)`;
- карточка: `comment(page, text)`, `upload_task_file(page, path)`;
- телефон: `check_360(page)`.

Правила (шаблон `e2e/template.md`): код приложения (`apps.*`, `django`) и `tests.support*` не импортируются —
тесты идут с хоста против стенда; локаторы — только зацепки CONTRACT-009 раздела 6.3; ждать — `expect`,
`wait_for_url`, `expect_response`; сна нет; данные круга общие, поэтому названия уникальны. Готовое из прежних
срезов вызывается, не дублируется: `helpers` (`Account`, `make_employee`, `no_horizontal_scroll`), `helpers_org`
(`open_structure`, `root_id`, `create_unit`, `add_members`, `set_marks`, `unique_name`).
Файл правит только T-9007.
"""
import re
from typing import NamedTuple

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org

PAGE_TIMEOUT = 20_000
MOVE_TIMEOUT = 5_000

TASK_URL = re.compile(r"/tasks/(\d+)/$")


# --- Люди и узлы сценариев (13.3, `TasksCast`) ---------------------------------------------------

class TasksCast(NamedTuple):
    """Участники сценариев задач. Учётки — `helpers.Account`; узлы — номера строкой."""
    employee: object          # рядовой сотрудник «Отдела ИТ»
    peer: object              # сотрудник вложенного узла (исполнитель задачи подчинённому)
    head: object              # руководитель «Отдела ИТ»
    deputy: object            # заместитель «Отдела ИТ»
    outsider: object          # сотрудник «Бухгалтерии»
    admin: object             # администратор портала
    dismissed: object         # уволенный сотрудник
    it_unit: str              # «Отдел ИТ», отдел
    nested_unit: str          # вложенный узел внутри «Отдела ИТ»
    other_unit: str           # «Бухгалтерия», отдел


def _dismiss(page, user_id) -> None:
    """Увольняет сотрудника из карточки `/staff/<id>/` (прежние зацепки CONTRACT-002/003)."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator("#staff-card")
    expect(card).to_be_visible()
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    with page.expect_navigation():
        dialog.locator('form[data-form="dismiss"] button[type=submit]').click()
    expect(page.locator("[data-dismissed-badge]")).to_be_visible()


def tasks_cast(admin_page, mailpit, new_context) -> TasksCast:
    """Создаёт узлы и учётки через интерфейс (`helpers.make_employee`, `helpers_org.create_unit`,
    `helpers_org.add_members`, `helpers_org.set_marks`). Имена узлов и ФИО уникальны на круг; у людей общая
    часть `<hex>`, чтобы один запрос `add_members(q=…)` находил всех. Сессии переносятся в
    `Account.storage_state` (контексты освобождаются); уволенный создан без активации."""
    token = helpers_org.unique_name("з")[2:]

    def person(surname: str, *, role: str = helpers.STAFF_ROLE, activate: bool = True):
        return helpers.make_employee(admin_page, mailpit, new_context, role=role, activate=activate,
                                     full_name=f"{surname}{token} Иван Иванович")

    employee = person("Задачев")
    peer = person("Подчинённов")
    head = person("Руководев")
    deputy = person("Заместителев")
    outsider = person("Чужаков")
    admin = person("Админов", role=helpers.ADMIN_ROLE)
    dismissed = person("Уволенов", activate=False)

    helpers_org.open_structure(admin_page)
    root_id = helpers_org.root_id(admin_page)
    it_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Отдел ИТ"), kind="department",
                                      parent_id=root_id)
    nested_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Группа задач"), kind="team",
                                          parent_id=it_unit)
    other_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Бухгалтерия"), kind="department",
                                         parent_id=root_id)
    helpers_org.add_members(admin_page, it_unit, [employee.id, head.id, deputy.id], q=token)
    helpers_org.add_members(admin_page, nested_unit, [peer.id], q=token)
    helpers_org.add_members(admin_page, other_unit, [outsider.id], q=token)
    helpers_org.set_marks(admin_page, it_unit, "heads", [head.id])
    helpers_org.set_marks(admin_page, it_unit, "deputies", [deputy.id])
    _dismiss(admin_page, dismissed.id)

    for account in (employee, peer, head, deputy, outsider, admin):
        account.storage_state = account.page.context.storage_state()
        account.page = None
    return TasksCast(employee, peer, head, deputy, outsider, admin, dismissed,
                     it_unit, nested_unit, other_unit)


# --- Вход и страницы (13.3) ----------------------------------------------------------------------

def open_tasks(context, account, preset="mine", **params):
    """Сессия `account` переносится в `context` (`helpers_notify.adopt_session`), новая страница, `/tasks/`
    (или доска, если `preset` начинается с `board:`); параметры — строками запроса. Возвращает страницу."""
    from tests.e2e import helpers_notify

    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    path = "/tasks/"
    if preset and preset.startswith("board:"):
        path = f"/tasks/board/{preset.split(':', 1)[1]}/"
    query = "&".join(f"{key}={value}" for key, value in params.items() if value not in (None, ""))
    page.goto(path + (f"?{query}" if query else ""))
    page.wait_for_load_state()
    expect(page.locator("[data-tasks-page]")).to_be_visible()
    return page


def open_card(context, account, task_id):
    """Вход и карточка `/tasks/<id>/`; ждёт `[data-tasks-page="card"]`."""
    from tests.e2e import helpers_notify

    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto(f"/tasks/{task_id}/")
    page.wait_for_load_state()
    expect(page.locator('[data-tasks-page="card"]')).to_be_visible()
    return page


# --- Создание и поля (13.3) ----------------------------------------------------------------------

def create_task(page, title, *, deadline=None, assignee=None, description="", category=None):
    """Форма «Новая задача»: `[data-task-field="title|description|deadline|assignee|category"]`;
    ждёт карточку и возвращает номер задачи."""
    page.goto("/tasks/new/")
    expect(page.locator('[data-tasks-page="new"]')).to_be_visible()
    form = page.locator('form[data-form="task-new"]')
    expect(form).to_be_visible()
    form.locator('[data-task-field="title"]').fill(title)
    if description:
        form.locator('[data-task-field="description"]').fill(description)
    if deadline:
        form.locator('[data-task-field="deadline"]').fill(str(deadline))
    if assignee is not None:
        person_id = getattr(assignee, "id", assignee)
        form.locator('[data-task-field="assignee"]').select_option(str(person_id))
    if category is not None:
        form.locator('[data-task-field="category"]').select_option(str(getattr(category, "pk", category)))
    form.locator("button[type=submit]").first.click()
    page.wait_for_url(TASK_URL)
    return int(TASK_URL.search(page.url).group(1))


# --- Доски и перенос (13.3) ----------------------------------------------------------------------

def _card(page, task_id):
    return page.locator(f'[data-task-card][data-task-id="{task_id}"]')


def move_card(page, task_id, board, column):
    """Перетаскивает карточку в колонку `[data-column="<column>"]` (мышью, SortableJS). Ждёт ответ переноса;
    если перетаскивание недоступно, пользуется выбором в карточке (запасной путь FR-684)."""
    card, target = _card(page).first, page.locator(f'[data-column="{column}"]').first
    expect(card).to_be_visible()
    expect(target).to_be_visible()
    source_box, target_box = card.bounding_box(), target.bounding_box()
    if source_box and target_box:
        x1 = source_box["x"] + source_box["width"] / 2
        y1 = source_box["y"] + source_box["height"] / 2
        x2 = target_box["x"] + target_box["width"] / 2
        y2 = target_box["y"] + min(target_box["height"] / 4, 120)
        with page.expect_response(lambda response: "/move/" in response.url, timeout=MOVE_TIMEOUT):
            page.mouse.move(x1, y1)
            page.mouse.down()
            page.mouse.move(x1 + 10, y1 + 10, steps=5)
            page.mouse.move(x2, y2, steps=15)
            page.mouse.up()
        page.wait_for_load_state()
        return
    _move_by_card_form(page, task_id, board, column)


def _move_by_card_form(page, task_id, board, column):
    """Запасной путь без перетаскивания: выбор поля в карточке (FR-684)."""
    field = {"plan": "plan_column"}.get(board, board if board != "status" else "status")
    page.goto(f"/tasks/{task_id}/")
    form = page.locator(f'form[data-task-field="{field}"]')
    expect(form).to_be_visible()
    form.locator(f'[data-task-field="{field}"]').select_option(str(column))
    with page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()


def board_titles(page):
    """Заголовки карточек по колонкам: `{ключ колонки: [название, …]}`."""
    result = {}
    for column in page.locator("[data-column]").all():
        key = column.get_attribute("data-column")
        result[key] = [title.strip() for title in column.locator("[data-task-title]").all_inner_texts()]
    return result


def plan_columns(page):
    """Названия колонок личного плана по порядку (`[data-plan-column]`)."""
    return [title.strip() for title in page.locator("[data-plan-column] [data-column-title]").all_inner_texts()]


# --- Карточка: комментарий и файл (13.3) ---------------------------------------------------------

def comment(page, text):
    """Пишет комментарий формой карточки; ждёт новую запись ленты."""
    counter = page.locator("[data-comment-id]")
    before = counter.count()
    form = page.locator('form[data-form="task-comment"]')
    expect(form).to_be_visible()
    form.locator('[data-task-field="text"]').fill(text)
    form.locator("button[type=submit]").first.click()
    expect(counter).to_have_count(before + 1, timeout=PAGE_TIMEOUT)


def upload_task_file(page, path):
    """Прикладывает файл к комментарию; возвращает `uuid` из `[data-task-file]`."""
    page.locator('input[type=file][name=file]').set_input_files(str(path))
    tile = page.locator("[data-task-file]").last
    expect(tile).to_be_visible(timeout=PAGE_TIMEOUT)
    return tile.get_attribute("data-task-file")


# --- Телефон (13.3) ------------------------------------------------------------------------------

def check_360(page):
    """Ширина 360 px: страница задач без горизонтальной прокрутки; на доске прокручивается только `[data-board]`."""
    page.set_viewport_size({"width": 360, "height": 800})
    expect(page.locator("[data-tasks-page]")).to_be_visible()
    page.wait_for_load_state()
    assert helpers.no_horizontal_scroll(page), "на 360 px горизонтальная прокрутка страницы"
    board = page.locator("[data-board]")
    if board.count():
        assert board.first.evaluate("node => node.scrollWidth >= node.clientWidth")