"""T-9301: сценарий 8–9 — напоминания и уведомление на портале (FR-688, FR-691, FR-692).

Общее для файла (CONTRACT-009, разделы 6.2–6.3, 8, 9.1, 12.1, 13.3; CONTRACT-008, 3.3, 12; SPEC-009,
сценарии 8 и 9; шаблон `e2e/template.md`):
- учётки — `helpers_tasks.tasks_cast` один раз на круг браузера; задачи — `create_task`, карточка — `open_card`;
- ручное напоминание — форма карточки по адресу 6.2 `/tasks/<id>/remind/` с полем `days` (или `on`): отдельной
  зацепки `data-task-field` для напоминания раздел 6.3 не даёт, поэтому форма ищется по полю `days` (имя поля —
  6.2); строки — `[data-reminder]` с моментом в `data-reminder-at`; «Отложить» — форма строки (адрес
  `/tasks/reminders/<id>/postpone/`, 6.2; «Отложить» проверяет серверный `test_tasks_reminders` — в браузере
  напоминание ещё не сработало, а ждать пятиминутное задание приёмка не может;
- отказ «за N рабочих дней» без срока — `[data-error="reminder"][data-code="reminder_deadline_required"]`
  с текстом 12.1;
- уведомление «Назначена задача» — поток `/messenger/notifications/` (CONTRACT-008, 3.3: `ul[data-notifications]`,
  `li[data-notification]`, `[data-field="text"|"kind"]`); ссылка строки ведёт в карточку задачи;
- автоматические сроки («скоро», «наступил», «просрочена») в браузере не проверяются: для них нужен сдвиг
  времени, а у задач команды сдвига нет — они остаются серверному `test_tasks_reminders` и `test_tasks_notify`;
- `sleep` нет, ожидание — `expect` и `wait_for_url`.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_tasks import create_task, open_card, open_tasks, tasks_cast

pytestmark = pytest.mark.e2e

MOSCOW = timezone(timedelta(hours=3))
DEADLINE_REQUIRED = "Для «за N рабочих дней» нужен срок задачи"
_CIRCLES: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг сценариев 8–9: учётки и узлы собираются при первом обращении в круге браузера."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = tasks_cast(admin_page, mailpit, new_context)
    return _CIRCLES[key]


def _day(offset: int = 0) -> str:
    return (datetime.now(MOSCOW).date() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _remind_form(page):
    """Форма ручного напоминания: поля `days` или `on` (6.2)."""
    return page.locator('form:has([name="days"], [name="on"])').first


def test_t09_08_manual_reminder_is_listed_with_moment(cast, new_context):
    """Сценарий 8, п. 3 (FR-688): сотрудник ставит себе напоминание «за 2 рабочих дня» к задаче со сроком —
    строка `[data-reminder]` появляется с моментом `data-reminder-at`; «Отложить» проверяет серверный тест."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Напомнить"), deadline=_day(5), assignee=employee)
    card = open_card(new_context(), employee, task_id)

    form = _remind_form(card)
    expect(form).to_be_visible()
    rows = card.locator("[data-reminder]")
    before = rows.count()
    form.locator('[name="days"]').fill("2")
    form.locator("button[type=submit]").first.click()

    expect(rows).to_have_count(before + 1)
    row = rows.filter(has=card.locator("form")).first
    expect(row).to_be_visible()
    moment = row.get_attribute("data-reminder-at")
    assert moment, "у строки напоминания нет момента data-reminder-at"


def test_t09_08_reminder_by_days_without_deadline_is_refused(cast, new_context):
    """Сценарий 8, п. 3 (FR-688): у задачи без срока «за N рабочих дней» не ставится — причина у поля
    `reminder` (`reminder_deadline_required`, текст 12.1)."""
    employee = cast.employee
    page = open_tasks(new_context(), employee)
    task_id = create_task(page, helpers_org.unique_name("Без срока"), assignee=employee)
    card = open_card(new_context(), employee, task_id)

    form = _remind_form(card)
    expect(form).to_be_visible()
    form.locator('[name="days"]').fill("1")
    form.locator("button[type=submit]").first.click()

    expect(card.locator('[data-error="reminder"][data-code="reminder_deadline_required"]')
           ).to_contain_text(DEADLINE_REQUIRED)
    expect(card.locator("[data-reminder]")).to_have_count(0)


def test_t09_08_assigned_task_sends_portal_notification_to_executor(cast, new_context):
    """Сценарий 9, п. 1 (FR-691, FR-692): руководитель ставит задачу сотруднику — у исполнителя на портале
    появляется уведомление «Назначена задача», ссылка ведёт в карточку этой задачи."""
    head, employee = cast.head, cast.employee
    head_page = open_tasks(new_context(), head)
    task_id = create_task(head_page, helpers_org.unique_name("Назначение"), assignee=employee)

    page = open_tasks(new_context(), employee)
    page.goto("/messenger/notifications/")
    expect(page.locator("ul[data-notifications]")).to_be_visible()
    row = page.locator("li[data-notification]").filter(has_text="Назначена задача").first
    expect(row).to_be_visible(timeout=20_000)
    row.locator("a").first.click()
    page.wait_for_url(re.compile(rf"/tasks/{task_id}/$"))