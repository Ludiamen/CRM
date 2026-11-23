"""Помощники приёмки среза 010 «Поручения» (T-10006; ими пользуются тесты `test_t10_*`).

Что здесь есть (CONTRACT-010: разделы 1.4, 6.3, 13.3):
- роли и учётки сценариев: `InstructionsCast`, `instructions_cast` (`assignee`, `peer`, `head`, `deputy`,
  `outsider`, `admin`, `dismissed`; узлы «Отдел ИТ», вложенный узел и «Бухгалтерия»);
- вход и страницы: `open_instructions(context, account, …)`, `open_card(context, account, instruction_id)`,
  `open_discipline(context, account, …)`;
- создание: `create_instruction(page, title, …)`;
- отчёты и решения: `submit_report`, `accept_report`, `return_report`;
- переносы: `request_transfer`, `decide_transfer`;
- снятие и Excel: `close_instruction`, `export_excel`;
- телефон: `check_360(page)`.

Правила (шаблон `e2e/template.md`): код приложения (`apps.*`, `django`) и `tests.support*` не импортируются —
тесты идут с хоста против стенда; локаторы — только зацепки CONTRACT-010 раздела 6.3; ждать — `expect`,
`wait_for_url`, `expect_response`; сна нет; данные круга общие, поэтому названия уникальны. Готовое из прежних
срезов вызывается, не дублируется: `helpers` (`Account`, `make_employee`, `no_horizontal_scroll`), `helpers_org`
(`open_structure`, `root_id`, `create_unit`, `add_members`, `set_marks`, `unique_name`).
Файл правит только T-10006.
"""
import re
from typing import NamedTuple

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org

PAGE_TIMEOUT = 20_000

INSTRUCTION_URL = re.compile(r"/instructions/(\d+)/$")


# --- Люди и узлы сценариев (13.3, `InstructionsCast`) --------------------------------------------

class InstructionsCast(NamedTuple):
    """Участники сценариев поручений. Учётки — `helpers.Account`; узлы — номера строкой."""
    assignee: object         # рядовой сотрудник «Отдела ИТ» (ответственный исполнитель)
    peer: object             # сотрудник вложенного узла (соисполнитель)
    head: object             # руководитель «Отдела ИТ» (постановщик и контролёр по умолчанию)
    deputy: object           # заместитель «Отдела ИТ»
    outsider: object         # сотрудник «Бухгалтерии»
    admin: object            # администратор портала
    dismissed: object        # уволенный сотрудник
    it_unit: str             # «Отдел ИТ», отдел
    nested_unit: str         # вложенный узел внутри «Отдела ИТ»
    other_unit: str          # «Бухгалтерия», отдел


def _dismiss(page, user_id) -> None:
    """Увольняет сотрудника из карточки `/staff/<id>/` (зацепки CONTRACT-002/003; образец — `helpers_tasks`)."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    expect(card).to_be_visible()
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def instructions_cast(admin_page, mailpit, new_context) -> InstructionsCast:
    """Создаёт узлы и учётки через интерфейс; имена уникальны на круг, общая часть `<hex>` — для одного запроса
    `add_members(q=…)`. Сессии переносятся в `Account.storage_state`; уволенный создан без активации."""
    token = helpers_org.unique_name("п")[2:]

    def person(surname: str, *, role: str = helpers.STAFF_ROLE, activate: bool = True):
        return helpers.make_employee(admin_page, mailpit, new_context, role=role, activate=activate,
                                     full_name=f"{surname}{token} Иван Иванович")

    assignee = person("Порученцев")
    peer = person("Соисполнителев")
    head = person("Постановщиков")
    deputy = person("Заместителев")
    outsider = person("Чужаков")
    admin = person("Админов", role=helpers.ADMIN_ROLE)
    dismissed = person("Уволенов", activate=False)

    helpers_org.open_structure(admin_page)
    root_id = helpers_org.root_id(admin_page)
    it_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Отдел ИТ"), kind="department",
                                      parent_id=root_id)
    nested_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Группа поручений"), kind="team",
                                          parent_id=it_unit)
    other_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Бухгалтерия"), kind="department",
                                         parent_id=root_id)
    helpers_org.add_members(admin_page, it_unit, [assignee.id, head.id, deputy.id], q=token)
    helpers_org.add_members(admin_page, nested_unit, [peer.id], q=token)
    helpers_org.add_members(admin_page, other_unit, [outsider.id], q=token)
    helpers_org.set_marks(admin_page, it_unit, "heads", [head.id])
    helpers_org.set_marks(admin_page, it_unit, "deputies", [deputy.id])
    _dismiss(admin_page, dismissed.id)

    for account in (assignee, peer, head, deputy, outsider, admin):
        account.storage_state = account.page.context.storage_state()
        account.page = None
    return InstructionsCast(assignee, peer, head, deputy, outsider, admin, dismissed,
                            it_unit, nested_unit, other_unit)


# --- Вход и страницы (13.3) ----------------------------------------------------------------------

def _session(context, account):
    from tests.e2e import helpers_notify

    context.clear_cookies()
    helpers_notify.adopt_session(context, account)
    return context.new_page()


def open_instructions(context, account, preset="mine", **params):
    """Вход и `/instructions/` с параметрами строкой запроса; ждёт `[data-instructions-page="registry"]`."""
    page = _session(context, account)
    if preset:
        params["preset"] = preset
    query = "&".join(f"{key}={value}" for key, value in params.items() if value not in (None, ""))
    page.goto("/instructions/" + (f"?{query}" if query else ""))
    page.wait_for_load_state()
    expect(page.locator('[data-instructions-page="registry"]')).to_be_visible()
    return page


def open_card(context, account, instruction_id):
    """Вход и карточка `/instructions/<id>/`; ждёт `[data-instructions-page="card"]`."""
    page = _session(context, account)
    page.goto(f"/instructions/{instruction_id}/")
    page.wait_for_load_state()
    expect(page.locator('[data-instructions-page="card"]')).to_be_visible()
    return page


def open_discipline(context, account, **params):
    """Вход и `/instructions/discipline/` (`from`, `to`, `unit`); ждёт `[data-discipline-table]`."""
    page = _session(context, account)
    query = "&".join(f"{key}={value}" for key, value in params.items() if value not in (None, ""))
    page.goto("/instructions/discipline/" + (f"?{query}" if query else ""))
    page.wait_for_load_state()
    expect(page.locator("[data-discipline-table]")).to_be_visible()
    return page


# --- Создание и поля (13.3) ----------------------------------------------------------------------

def create_instruction(page, title, *, basis=None, basis_number="12", basis_date=None, assignee=None,
                       deadline=None, periodicity=None, dates=()):
    """Форма «Новое поручение»: `form[data-form="instruction-new"]`, поля `[data-instruction-field]`;
    ждёт карточку и возвращает номер поручения."""
    page.goto("/instructions/new/")
    expect(page.locator('[data-instructions-page="new"]')).to_be_visible()
    form = page.locator('form[data-form="instruction-new"]')
    expect(form).to_be_visible()
    form.locator('[data-instruction-field="title"]').fill(title)
    if basis is not None:
        form.locator('[data-instruction-field="basis_kind"]').select_option(label=str(basis))
    form.locator('[data-instruction-field="basis_number"]').fill(str(basis_number))
    if basis_date is not None:
        form.locator('[data-instruction-field="basis_date"]').fill(str(basis_date))
    if assignee is not None:
        form.locator('[data-instruction-field="assignee"]').select_option(str(getattr(assignee, "id", assignee)))
    if deadline is not None:
        form.locator('[data-instruction-field="deadline"]').fill(str(deadline))
    if periodicity is not None:
        form.locator('[data-instruction-field="periodicity"]').select_option(str(periodicity))
    if dates:
        form.locator('[data-instruction-field="dates"]').fill(", ".join(str(day) for day in dates))
    form.locator("button[type=submit]").first.click()
    page.wait_for_url(INSTRUCTION_URL)
    return int(INSTRUCTION_URL.search(page.url).group(1))


# --- Отчёты и решения (13.3) ---------------------------------------------------------------------

def submit_report(page, text, *, files=()):
    """Отправляет сводный отчёт первой доступной формой; ждёт, что дата перестала быть «Ждёт отчёта»."""
    form = page.locator('form[data-form="instruction-report"]').first
    expect(form).to_be_visible()
    form.locator('[data-instruction-field="text"]').fill(text)
    for path in files:
        form.locator('input[type=file]').set_input_files(str(path))
    form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()


def accept_report(page, report_id):
    """Принимает отчёт отчётной даты (кнопка `[data-decide="accept"]` внутри `[data-report-date]`)."""
    block = page.locator(f'[data-report-date="{report_id}"]')
    expect(block).to_be_visible()
    block.locator('[data-decide="accept"]').click()
    page.wait_for_load_state()
    expect(block.locator('[data-report-state]')).to_have_text(re.compile("Принято"))


def return_report(page, report_id, comment):
    """Возвращает отчёт с комментарием (кнопка `[data-decide="return"]`)."""
    block = page.locator(f'[data-report-date="{report_id}"]')
    expect(block).to_be_visible()
    block.locator('[data-instruction-field="comment"]').fill(comment)
    block.locator('[data-decide="return"]').click()
    page.wait_for_load_state()
    expect(block.locator('[data-report-state]')).to_have_text(re.compile("Возвращено"))


# --- Переносы (13.3) -----------------------------------------------------------------------------

def request_transfer(page, new_deadline, reason):
    """Запрос переноса формой карточки; ждёт строку `[data-transfer][data-transfer-state="pending"]`."""
    form = page.locator('form[data-form="instruction-transfer"]').first
    expect(form).to_be_visible()
    form.locator('[data-instruction-field="new_deadline"]').fill(str(new_deadline))
    form.locator('[data-instruction-field="reason"]').fill(reason)
    form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()
    expect(page.locator('[data-transfer][data-transfer-state="pending"]').first).to_be_visible()


def decide_transfer(page, transfer_id, approve=True, comment=""):
    """Решение по переносу: `[data-decide="approve"]` или `[data-decide="reject"]` в строке переноса."""
    row = page.locator(f'[data-transfer="{transfer_id}"]')
    expect(row).to_be_visible()
    if comment:
        row.locator('[data-instruction-field="comment"]').fill(comment)
    row.locator(f'[data-decide="{"approve" if approve else "reject"}"]').click()
    page.wait_for_load_state()


# --- Снятие с контроля и Excel (13.3) ------------------------------------------------------------

def close_instruction(page):
    """Снимает поручение с контроля; при втором шаге подтверждает его. Ждёт `[data-instruction-state="done"]`."""
    form = page.locator('form[data-form="instruction-close"]').first
    expect(form).to_be_visible()
    form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()
    confirm = page.locator("[data-instructions-confirm]")
    if confirm.count():
        confirm.locator("button[type=submit]").first.click()
        page.wait_for_load_state()
    expect(page.locator('[data-instruction-state="done"]').first).to_be_visible()


def export_excel(page):
    """Скачивает `instructions/discipline.xlsx`; возвращает путь временного файла."""
    with page.expect_download() as download:
        page.locator('a[href*="discipline.xlsx"]').first.click()
    return download.value.path()


# --- Телефон (13.3) ------------------------------------------------------------------------------

def check_360(page):
    """Ширина 360 px: страница поручений без горизонтальной прокрутки; таблица дисциплины прокручивается внутри."""
    page.set_viewport_size({"width": 360, "height": 800})
    expect(page.locator("[data-instructions-page]")).to_be_visible()
    page.wait_for_load_state()
    assert helpers.no_horizontal_scroll(page), "на 360 px горизонтальная прокрутка страницы"
    table = page.locator("[data-discipline-table]")
    if table.count():
        assert table.first.evaluate("node => node.scrollWidth >= node.clientWidth")