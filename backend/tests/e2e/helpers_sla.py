"""Помощники приёмки среза 011 «Сроки и отчёты заявок» (T-11005).

Локаторы здесь используют только зацепки CONTRACT-011: страницы SLA, отчёта,
шаблонов ответа, фильтров срока и блока SLA в карточке. Данные создаются
через интерфейс стенда, а не через ORM; ожидания выполняются средствами
Playwright без сна.
"""
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify


def _session(context, account):
    """Создаёт страницу с сессией переданной учётной записи."""
    context.clear_cookies()
    helpers_notify.adopt_session(context, account)
    return context.new_page()


def open_sla(context, account, *, archived=False):
    """Входит и открывает `/servicedesk/sla/`; ждёт `[data-sla-page="list"]`."""
    page = _session(context, account)
    query = "?archived=1" if archived else ""
    page.goto(f"/servicedesk/sla/{query}")
    page.wait_for_load_state()
    expect(page.locator('[data-sla-page="list"]')).to_be_visible()
    return page


def create_level(page, title, *, priority=0, reaction_minutes=60, solution_minutes=240, workdays=(),
                 all_day=False, category=None, severity=None, assignee=None):
    """Создаёт уровень SLA и возвращает его целочисленный идентификатор из `[data-sla-id]`."""
    page.goto("/servicedesk/sla/new/")
    expect(page.locator('[data-sla-page="new"]')).to_be_visible()
    form = page.locator('[data-sla-page="new"]')
    fields = {
        "title": title,
        "priority": priority,
        "reaction_minutes": reaction_minutes,
        "solution_minutes": solution_minutes,
    }
    for name, value in fields.items():
        form.locator(f'[data-sla-field="{name}"]').fill(str(value))
    if workdays:
        form.locator('[data-sla-field="workdays"]').select_option([str(day) for day in workdays])
    if all_day:
        form.locator('[data-sla-field="all_day"]').check()
    for name, value in (("category", category), ("priority", severity), ("assignee", assignee)):
        if value is not None:
            control = form.locator(f'[data-sla-field="{name}"]')
            control.select_option(str(getattr(value, "id", value)))
    form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    row = page.locator('[data-sla-id]').filter(has_text=title).first
    expect(row).to_be_visible()
    return int(row.get_attribute("data-sla-id"))


def open_report(context, account, *, period="month", **params):
    """Входит и открывает отчёт с периодом и непустыми параметрами запроса."""
    page = _session(context, account)
    query = {"period": period, **{key: value for key, value in params.items() if value not in (None, "")}}
    page.goto(f"/servicedesk/reports/?{urlencode(query)}")
    page.wait_for_load_state()
    expect(page.locator("[data-report-page]")).to_be_visible()
    expect(page.locator(f'[data-report-period="{period}"]')).to_be_visible()
    return page


def export_xlsx(page):
    """Скачивает XLSX отчёта и возвращает путь временного файла, не удаляя его."""
    with page.expect_download() as download:
        page.locator('a[href*="/servicedesk/reports/export/"]').click()
    return download.value.path()


def insert_answer(page, title, *, ticket_number=None):
    """Вставляет шаблон ответа по названию и возвращает текст textarea после подстановки."""
    button = page.locator("[data-answer-insert]").filter(has_text=title).first
    expect(button).to_be_visible()
    if ticket_number is not None:
        href = button.get_attribute("href") or ""
        if "ticket=" not in href:
            button = page.locator(f'[data-answer-insert][data-ticket="{ticket_number}"]').filter(
                has_text=title
            ).first
    button.click()
    text = page.locator("textarea").first
    expect(text).not_to_have_value("")
    return text.input_value()


def check_360(page):
    """Проверяет страницу и блок SLA на ширине 360 px без горизонтальной прокрутки."""
    page.set_viewport_size({"width": 360, "height": 800})
    expect(page.locator("[data-sla-page], [data-report-page], [data-sla], [data-answer-page]").first).to_be_visible()
    assert helpers.no_horizontal_scroll(page), "на 360 px горизонтальная прокрутка страницы"
    return True


def prepare_sla_stand(account):
    """Стенд: наполнение среза и права отчёта для вошедшего администратора.

    Круг e2e создаёт администратора уже после сброса стенда, поэтому `e2e_sla_seed` вызывается здесь, а затем
    администратор становится руководителем первой очереди (иначе отчёт честно даёт 403: область — управляемые
    узлы, FR-749). Наполнение идемпотентно.
    """
    code = (
        "from django.core.management import call_command; "
        "call_command('e2e_sla_seed'); "
        "from django.contrib.auth import get_user_model; "
        "from apps.org.services import membership; "
        "from apps.servicedesk.models import Queue; "
        f"user = get_user_model().objects.get(email={account.email!r}); "
        "queue = Queue.objects.select_related('unit').first(); "
        "membership.set_marks(queue.unit, heads=[user], actor=user); print('ok')"
    )
    return helpers.stand_shell(code)
