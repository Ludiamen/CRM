"""Помощники браузерной приёмки среза 012.

CONTRACT-012 ещё дополняется. До его появления используются стабильные
маршруты из PLAN-012 и зацепки ``data-*`` из T-12001/T-12011; при публикации
контракта селекторы ниже сверяются с ним, а не с декоративным HTML.
"""
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers_notify


def _session(context, account):
    context.clear_cookies()
    helpers_notify.adopt_session(context, account)
    return context.new_page()


def open_queue(context, account, queue_id=None):
    """Открывает список очередей или карточку очереди."""
    page = _session(context, account)
    path = "/servicedesk/queues/" if queue_id is None else f"/servicedesk/queues/{int(queue_id)}/"
    page.goto(path)
    expect(page.locator("[data-queues-page], [data-queue-page]").first).to_be_visible()
    return page


def open_rule(page, queue_id):
    """Открывает форму правила очереди."""
    page.goto(f"/servicedesk/queues/{int(queue_id)}/rule/")
    expect(page.locator('[data-queue-rule-page], [data-queue-rule]').first).to_be_visible()
    return page


def set_rule(page, mode):
    """Выбирает режим в `[data-queue-field="mode"]` и отправляет форму."""
    form = page.locator('form[data-form="queue-rule"], [data-queue-rule]').first
    expect(form).to_be_visible()
    form.locator('[data-queue-rule-field="mode"], select[name="mode"]').first.select_option(mode)
    form.locator("button[type=submit]").first.click()
    expect(page.locator('[role="status"], [data-queue-rule]').first).to_be_visible()
    return page


def open_observers(page, queue_id):
    """Открывает список наблюдателей очереди."""
    page.goto(f"/servicedesk/queues/{int(queue_id)}/observers/")
    expect(page.locator("[data-observers-page], [data-observer-list]").first).to_be_visible()
    return page


def add_observer(page, user_id):
    """Добавляет сотрудника через форму наблюдателей."""
    form = page.locator('form[data-form="observer-add"], form[data-form="queue-observer"]').first
    expect(form).to_be_visible()
    form.locator('[data-observer-field="user"], select[name="user"], input[name="user"]').first.select_option(
        str(user_id))
    form.locator("button[type=submit]").first.click()
    return page


def open_rating(context, ticket_number, account=None):
    """Открывает карточку заявки для сотрудника или публичную форму оценки."""
    page = _session(context, account) if account is not None else context.new_page()
    query = urlencode({"ticket": int(ticket_number)})
    page.goto(f"/rate/?{query}")
    expect(page.locator("[data-rating-page], [data-rating-form]").first).to_be_visible()
    return page


def rate(page, code, score):
    """Отправляет код и балл POST-формой оценки."""
    form = page.locator('form[data-form="rating"], [data-rating-form]').first
    expect(form).to_be_visible()
    form.locator('[data-rating-field="code"], input[name="code"]').fill(code)
    field = form.locator('[data-rating-field="score"], select[name="score"]').first
    if field.evaluate("el => el.tagName.toLowerCase()") in ("select",):
        field.select_option(str(score))
    else:
        form.locator(f'input[name="score"][value="{int(score)}"]').check()
    form.locator("button[type=submit]").first.click()
    return page


def open_task_from_ticket(page, ticket_number):
    """Открывает форму задачи из заявки через параметр `ticket`."""
    page.goto(f"/tasks/new/?{urlencode({'ticket': int(ticket_number)})}")
    expect(page.locator('[data-tasks-page="new"], [data-task-form]').first).to_be_visible()
    return page


def open_task(context, account, task_id):
    """Открывает карточку задачи."""
    page = _session(context, account)
    page.goto(f"/tasks/{int(task_id)}/")
    expect(page.locator('[data-tasks-page="card"], [data-task-card]').first).to_be_visible()
    return page


def check_360(page):
    """Проверяет экран среза 012 на ширине 360 px."""
    page.set_viewport_size({"width": 360, "height": 800})
    expect(page.locator(
        "[data-queues-page], [data-queue-rule-page], [data-ticket-card], "
        "[data-rating-page], [data-tasks-page]"
    ).first).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "на 360 px горизонтальная прокрутка страницы"
    )
    return True
