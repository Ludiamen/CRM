"""T-2147: сценарий 12 — администратор задаёт рабочую неделю и часы (FR-143, FR-150).

Неделя и часы общие на общество: тесты начинают с умолчания (пн–пт, 09:00–18:00) и возвращают его в `finally`
через `helpers.stand_shell` (сброс настроек, кэша отметок месяцев и рост номера версии календаря).
Пункт 5 сценария (внутренний запрос `is_working_time` / `next_working_start`) браузером не проверяется: это
служба без интерфейса, её закрывает серверный тест test_calendar (T-2112).
"""
import re
from datetime import date

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_org import audit_rows, audit_sides

SUCCESS = "[role=status]:not([data-notice])"  # доп. 56
SETTINGS = 'form[action="/calendar/settings/"]'
TEST_YEAR = 2028  # год, который никто не загружает: суббота в нём — без особого дня


def _stand_reset_settings() -> None:
    """Подготовка через stand_shell: неделя пн–пт, часы 09:00–18:00, год теста не загружен, кэш отметок сброшен и
    номер версии календаря поднят (в интерфейсе вернуть «как было» нельзя без новой записи в журнале)."""
    helpers.stand_shell(
        "import redis\n"
        "from datetime import time\n"
        "from django.apps import apps\n"
        "from django.conf import settings\n"
        f"apps.get_model('org.SpecialDay').objects.filter(date__year={TEST_YEAR}).delete()\n"
        f"apps.get_model('org.CalendarYear').objects.filter(year={TEST_YEAR}).delete()\n"
        "apps.get_model('org.WorkCalendar').objects.update(work_weekdays=[0, 1, 2, 3, 4], "
        "day_start=time(9, 0), day_end=time(18, 0))\n"
        "r = redis.Redis.from_url(settings.VALKEY_URL)\n"
        "for k in list(r.scan_iter('*calendar:marks:*')):\n"
        "    r.delete(k)\n"
        "for k in list(r.scan_iter('*calendar:version')):\n"
        "    r.incr(k)\n"
        "print('ok')\n")


def _form(page):
    """Форма недели и часов на `/calendar/` (открывает страницу заново)."""
    page.goto(f"/calendar/?year={TEST_YEAR}")
    form = page.locator(SETTINGS)
    expect(form).to_be_visible()
    return form


def _state(form) -> tuple:
    """(отмеченные дни недели, начало, конец) формы."""
    days = [v for v in map(str, range(7))
            if form.locator(f'input[type=checkbox][name=work_weekdays][value="{v}"]').is_checked()]
    return (days, form.locator("input[name=day_start]").input_value(), form.locator("input[name=day_end]").input_value())


def _save(page, *, days, start, end) -> None:
    """Заполняет форму недели и часов (отмечает ровно `days`, пишет время) и отправляет."""
    form = _form(page)
    for value in map(str, range(7)):
        box = form.locator(f'input[type=checkbox][name=work_weekdays][value="{value}"]')
        box.check() if value in days else box.uncheck()
    form.locator("input[name=day_start]").fill(start)
    form.locator("input[name=day_end]").fill(end)
    form.locator("button[type=submit]").click()


def _saturday() -> str:
    """Первая суббота марта года теста (дата ГГГГ-ММ-ДД)."""
    return next(d for d in (date(TEST_YEAR, 3, n) for n in range(1, 32)) if d.weekday() == 5).isoformat()


def test_o12_defaults_saturday_workday_and_validation(admin_page):
    """Сценарий 12, п. 1–3: на новой установке рабочие дни пн–пт, 09:00–18:00, неделя в календаре с понедельника;
    суббота, отмеченная рабочей, считается рабочим днём (в году без особых дней); конец дня раньше начала, пустой
    набор рабочих дней и день короче двух часов (план: «Неделя и часы») отклоняются, а сохранённое не меняется
    (FR-143)."""
    page = admin_page
    _stand_reset_settings()
    try:
        # п. 1: умолчания и неделя с понедельника
        form = _form(page)
        assert _state(form) == (["0", "1", "2", "3", "4"], "09:00", "18:00")
        expect(page.locator('[data-month="1"] thead th')).to_have_text(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
        saturday = _saturday()
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "off")

        # п. 2: суббота рабочая
        _save(page, days=["0", "1", "2", "3", "4", "5"], start="09:00", end="18:00")
        expect(page.locator(SUCCESS).first).not_to_have_text("")
        form = _form(page)
        assert _state(form) == (["0", "1", "2", "3", "4", "5"], "09:00", "18:00")
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "work")
        sunday = next(d for d in (date(TEST_YEAR, 3, n) for n in range(1, 32)) if d.weekday() == 6).isoformat()
        expect(page.locator(f'td[data-date="{sunday}"]')).to_have_attribute("data-day-kind", "off")
        saved = _state(form)

        # п. 3: отказы, сохранённое не меняется
        for days, start, end in ((["0", "1", "2", "3", "4", "5"], "12:00", "10:00"),  # конец раньше начала
                                 ([], "09:00", "18:00"),                                # нет рабочих дней
                                 (["0", "1", "2", "3", "4", "5"], "09:00", "10:00")):  # день короче двух часов
            _save(page, days=days, start=start, end=end)
            expect(page.locator("[role=alert]").first).to_be_visible()
            assert helpers.alert_text(page)
            assert _state(_form(page)) == saved, (days, start, end)
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "work")
    finally:
        _stand_reset_settings()


def test_o12_journal_before_after(admin_page):
    """Сценарий 12, п. 4: изменение недели и часов пишется в журнал записью «было / стало» на русском, без
    латинских названий полей; повторное сохранение тех же значений новой записи не даёт (FR-150)."""
    page = admin_page
    _stand_reset_settings()
    try:
        events = len(audit_rows(page, "calendar.settings_changed"))
        _save(page, days=["0", "1", "2", "3", "4", "5"], start="08:00", end="19:00")
        expect(page.locator(SUCCESS).first).not_to_have_text("")

        sides = audit_sides(page, "calendar.settings_changed")
        assert len(sides) == events + 1, sides
        before, after = sides[0]  # новое событие — сверху
        assert "09:00" in before and "18:00" in before, before
        assert "08:00" in after and "19:00" in after, after
        assert before != after
        assert "Сб" in after and "Сб" not in before, (before, after)
        for text in (before, after):
            assert not re.search(r"\b(work_weekdays|day_start|day_end|year|totals|file_name|kind|date)\b", text), text
            assert not re.search(r'[{}\[\]"]', text), text  # сырого JSON нет (доп. 29, 58)
            assert not re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", text), text  # время ЧЧ:ММ

        # то же значение ещё раз — изменения нет, записи нет
        _save(page, days=["0", "1", "2", "3", "4", "5"], start="08:00", end="19:00")
        expect(page.locator(SUCCESS).first).not_to_have_text("")
        assert len(audit_rows(page, "calendar.settings_changed")) == events + 1
    finally:
        _stand_reset_settings()
