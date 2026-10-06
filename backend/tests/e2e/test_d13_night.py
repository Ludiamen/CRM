"""T-3149: сценарий 13 — заявитель пишет ночью (FR-254).

Нерабочее время приёмка задаёт настройкой рабочей недели календаря среза 002 (подмены часов на стенде нет): из
рабочих дней убирается сегодняшний день недели по Москве; «рабочее время» — все семь дней, 00:00–23:59. Прежняя
неделя и часы возвращаются в `finally`. Тест, который начинается за пять минут до полуночи по Москве, ждёт новой
даты (иначе «сегодня» сменилось бы между настройкой и разбором письма).
"""
import re
import secrets
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

MOSCOW = ZoneInfo("Europe/Moscow")
SETTINGS = 'form[action="/calendar/settings/"]'
SUCCESS = "[role=status]:not([data-notice])"  # доп. 56 среза 002
ALL_DAYS = ["0", "1", "2", "3", "4", "5", "6"]
PHRASE = "Заявка поступила в нерабочее время, мы рассмотрим её"


def _word() -> str:
    """Уникальное слово темы по доп. 41 (в): буква и шесть шестнадцатеричных знаков, не из одних цифр."""
    return f"t{secrets.token_hex(3)}"


def _norm(text: str) -> str:
    """Текст письма с пробелами и переводами строк, сжатыми в один пробел."""
    return " ".join(text.split())


def _midnight_guard(page) -> None:
    """Не начинать за пять минут до полуночи по Москве: ждёт новой даты (предел ~6 минут) и ещё 15 секунд."""
    start = datetime.now(MOSCOW)
    if not (start.hour == 23 and start.minute >= 55):
        return
    deadline = time.monotonic() + 360
    while datetime.now(MOSCOW).date() == start.date() and time.monotonic() < deadline:
        page.wait_for_timeout(2000)
    page.wait_for_timeout(15_000)


def _calendar_form(page):
    page.goto("/calendar/")
    form = page.locator(SETTINGS)
    expect(form).to_be_visible()
    return form


def _week_state(page) -> tuple:
    """(отмеченные рабочие дни, начало, конец) формы недели и часов на `/calendar/`."""
    form = _calendar_form(page)
    # год календаря не загружен: ожидаемая дата считается только по дням недели (особых дней нет)
    expect(page.locator(f'[data-notice="calendar-year"][data-year="{datetime.now(MOSCOW).year}"]'),
           "на текущий год загружен календарь: ожидаемая дата «ближайшего рабочего времени» в тестах считается "
           "только по дням недели").to_be_visible()
    days = [v for v in ALL_DAYS if form.locator(f'input[type=checkbox][name=work_weekdays][value="{v}"]').is_checked()]
    return days, form.locator("input[name=day_start]").input_value(), form.locator("input[name=day_end]").input_value()


def _set_week(page, days: list, start: str, end: str) -> None:
    """Отмечает ровно `days`, пишет часы, отправляет форму и ждёт сообщения об успехе."""
    form = _calendar_form(page)
    for value in ALL_DAYS:
        box = form.locator(f'input[type=checkbox][name=work_weekdays][value="{value}"]')
        box.check() if value in days else box.uncheck()
    form.locator("input[name=day_start]").fill(start)
    form.locator("input[name=day_end]").fill(end)
    form.locator("button[type=submit]").click()
    expect(page.locator(SUCCESS).first).to_be_visible()
    expect(page.locator("[role=alert]")).to_have_count(0)


def _all_but_today(now: datetime) -> list:
    """Все семь дней недели, кроме сегодняшнего по Москве (`now` — московское время)."""
    return [d for d in ALL_DAYS if int(d) != now.weekday()]


def _next_start(now: datetime, days: list, start: str) -> str:
    """«ДД.ММ.ГГГГ ЧЧ:ММ» ближайшего начала рабочего дня после `now` (московское время) при рабочих днях `days`,
    когда сегодняшний день не рабочий (год календаря не загружен: действуют только дни недели)."""
    hours, minutes = (int(part) for part in start.split(":"))
    for shift in range(1, 15):
        day = now.date() + timedelta(days=shift)
        if str(day.weekday()) in days:
            return datetime.combine(day, dtime(hours, minutes), MOSCOW).strftime("%d.%m.%Y %H:%M")
    raise AssertionError("нет рабочих дней")


def _mail_ticket(page, mailpit):
    """Письмо заявителя → заявка → подтверждение; возвращает (номер, текст подтверждения без переносов строк)."""
    word, sender = _word(), helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Ночная заявка {word}",
                                  text=f"Не работает почта {word}", message_id=f"<{secrets.token_hex(8)}@client.test>"))
    number = helpers_sd.ticket_number_by_subject(page, word)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    return number, _norm(letter["Text"])


def _form_ticket(page, mailpit, new_context):
    """Заявка гостя с открытой формы `/request/` в категории «Другое» (как `_guest_ticket` в test_d09_settings.py);
    возвращает (номер, текст подтверждения без переносов строк)."""
    word, sender = _word(), helpers_sd.requester_email()
    guest = new_context().new_page()
    guest.goto("/request/")
    form = guest.locator('form[data-form="request"]')
    expect(form).to_be_visible()
    form.locator("input[name=email]").fill(sender)
    form.locator("input[name=name]").fill("Тест Заявитель")
    form.locator("select[name=category]").select_option(label="Другое")
    form.locator("input[name=subject]").fill(f"Ночная форма {word}")
    form.locator("textarea[name=text]").fill(f"Описание {word}")
    form.locator("input[name=consent]").check()
    form.locator("button[type=submit]").click()
    guest.wait_for_url(re.compile(r"/request/done/"))
    number = helpers_sd.ticket_number_by_subject(page, word)
    letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=sender)
    return number, _norm(letter["Text"])


def test_d13_after_hours_mail_or_form_confirmation_has_phrase_with_next_working_time(admin_page, mailpit,
                                                                                    new_context):
    """Сценарий 13, п. 1: заявка из письма и заявка гостя с открытой формы в нерабочее время — в подтверждении
    фраза «Заявка поступила в нерабочее время, мы рассмотрим её с <дата и время начала ближайшего рабочего
    времени>» (FR-254)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    _midnight_guard(page)
    original = _week_state(page)
    now = datetime.now(MOSCOW)
    days = _all_but_today(now)
    try:
        # дано: момент вне рабочего времени — сегодняшний день недели не рабочий
        _set_week(page, days, "09:00", "18:00")
        # когда: создаётся заявка из письма
        number, text = _mail_ticket(page, mailpit)
        # и заявка гостя с открытой формы (категория «Другое»; порог формы 10 в час, хватает одной отправки)
        form_number, form_text = _form_ticket(page, mailpit, new_context)
    finally:
        _set_week(page, *original)
    # п. 1: фраза с началом ближайшего рабочего времени (завтра 09:00 по Москве) — и у письма, и у формы
    expected = _next_start(now, days, "09:00")
    assert f"{PHRASE} с {expected}." in text, text
    assert f"Ваша заявка принята под номером {number}." in text
    assert f"{PHRASE} с {expected}." in form_text, form_text
    assert f"Ваша заявка принята под номером {form_number}." in form_text


def test_d13_working_hours_confirmation_has_no_phrase(admin_page, mailpit):
    """Сценарий 13, п. 2: в рабочее время (все семь дней, 00:00–23:59) в подтверждении фразы о нерабочем времени
    нет (FR-254)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    _midnight_guard(page)
    original = _week_state(page)
    try:
        # дано: рабочее время в любой день и час
        _set_week(page, ALL_DAYS, "00:00", "23:59")
        number, text = _mail_ticket(page, mailpit)
    finally:
        _set_week(page, *original)
    # п. 2: подтверждение есть, фразы нет
    assert f"Ваша заявка принята под номером {number}." in text
    assert "нерабочее время" not in text.lower(), text
    assert "ближайшего рабочего" not in text.lower()


def test_d13_year_not_loaded_saturday_has_phrase_by_weekdays_only(browser, browser_context_args, stand_admin,
                                                                  admin_page, mailpit):
    """Сценарий 13, п. 3: год календаря не загружен — при заявке в выходной (по дням недели) фраза есть, действуют
    только рабочие дни недели (FR-254; SPEC-002 FR-146)."""
    # сброс `org` стирает загруженные годы календаря и возвращает неделю по умолчанию (пн–пт, 09:00–18:00)
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    page = admin_page
    helpers_sd.ensure_ready(page)
    _midnight_guard(page)
    now = datetime.now(MOSCOW)
    # дано: на текущий год календарь не загружен (напоминание у обладателя права «Календарь»)
    page.goto("/calendar/")
    expect(page.locator(f'[data-notice="calendar-year"][data-year="{now.year}"]')).to_be_visible()
    original = _week_state(page)
    assert original == (["0", "1", "2", "3", "4"], "09:00", "18:00")
    # в субботу и воскресенье умолчание уже даёт выходной; в будни убираем сегодняшний день недели
    days = original[0] if now.weekday() >= 5 else _all_but_today(now)
    try:
        if days != original[0]:
            _set_week(page, days, "09:00", "18:00")
        number, text = _mail_ticket(page, mailpit)
    finally:
        if days != original[0]:
            _set_week(page, *original)
    # п. 3: фраза есть; ближайшее рабочее время считается только по дням недели
    expected = _next_start(now, days, "09:00")
    assert f"{PHRASE} с {expected}." in text, text
    assert f"Ваша заявка принята под номером {number}." in text


def test_d13_executor_ticket_confirmation_has_no_phrase_at_any_time(admin_page, mailpit):
    """Сценарий 13, п. 4: заявка исполнителя, созданная в нерабочее время, — в подтверждении фразы о нерабочем времени
    нет, хотя заявка из письма в тот же момент её получает (FR-254)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    _midnight_guard(page)
    original = _week_state(page)
    now = datetime.now(MOSCOW)
    requester, word = helpers_sd.requester_email("phone"), _word()
    try:
        # дано: нерабочее время; контроль — заявка из письма получает фразу
        _set_week(page, _all_but_today(now), "09:00", "18:00")
        _control_number, control_text = _mail_ticket(page, mailpit)
        assert PHRASE in control_text, control_text
        # когда: исполнитель заводит заявку по звонку
        page.goto("/tickets/new/")
        form = page.locator('form[data-form="ticket-new"]')
        expect(form).to_be_visible()
        old_requester = form.locator("input[name=name]").element_handle()
        with page.expect_response(lambda r: "/tickets/new/requester/" in r.url):
            form.locator("input[name=email]").fill(requester)
            form.locator("input[name=email]").press("Tab")
        page.wait_for_function("el => !el.isConnected", arg=old_requester)  # обёртка заменена целиком (доп. 42 (д))
        old_queue = form.locator("select[name=queue]").element_handle()
        with page.expect_response(lambda r: "/tickets/new/queue/" in r.url):
            form.locator("select[name=category]").select_option(label="Другое")
        page.wait_for_function("el => !el.isConnected", arg=old_queue)
        form.locator("select[name=source] option[value]:not([value=''])").first.wait_for(state="attached")
        source = form.locator("select[name=source] option[value]:not([value=''])").first.get_attribute("value")
        form.locator("select[name=source]").select_option(value=source)
        form.locator("input[name=subject]").fill(f"Звонок ночью {word}")
        form.locator("textarea[name=text]").fill(f"Заявка по звонку {word}")
        helpers.submit(form)
        page.wait_for_url(lambda url: "/tickets/new/" not in url)
        number = helpers_sd.ticket_number_by_subject(page, word)
        letter = helpers_sd.wait_letter(mailpit, number, "ticket.confirmation", to=requester)
    finally:
        _set_week(page, *original)
    # п. 4: подтверждение исполнителя без фразы
    text = _norm(letter["Text"])
    assert f"Ваша заявка принята под номером {number}." in text
    assert "нерабочее время" not in text.lower(), text
    assert "ближайшего рабочего" not in text.lower()


def test_d13_changed_calendar_settings_apply_to_next_ticket(admin_page, mailpit):
    """Сценарий 13, п. 5: настройки календаря изменены — следующая заявка получает подтверждение по новым: сначала
    рабочее время (фразы нет), затем нерабочее с другим началом дня (фраза с новым временем) (FR-254)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    _midnight_guard(page)
    original = _week_state(page)
    now = datetime.now(MOSCOW)
    days = _all_but_today(now)
    try:
        # прежние настройки: рабочее время всегда — фразы нет
        _set_week(page, ALL_DAYS, "00:00", "23:59")
        _first_number, first_text = _mail_ticket(page, mailpit)
        # настройки изменены: сегодня не рабочий день, день начинается в 08:30
        _set_week(page, days, "08:30", "17:30")
        _second_number, second_text = _mail_ticket(page, mailpit)
    finally:
        _set_week(page, *original)
    # п. 5: первая заявка — без фразы, следующая — с фразой по новым настройкам
    assert "нерабочее время" not in first_text.lower(), first_text
    expected = _next_start(now, days, "08:30")
    assert f"{PHRASE} с {expected}." in second_text, second_text
