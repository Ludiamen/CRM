"""T-2147: сценарий 11 — администратор загружает производственный календарь и правит день (FR-123, FR-144, FR-145,
FR-146, FR-150).

Календарь общий на общество, поэтому каждый тест сам приводит нужные годы в исходное состояние и возвращает его
в `finally` (подготовка через `helpers.stand_shell`: снять особые дни и отметку «загружен», сбросить кэш отметок и
поднять номер версии календаря; в интерфейсе года выгрузить нельзя). Годы теста — 2026, 2027 и текущий.
"""
import csv
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_org import (audit_rows, audit_sides, calendar_fixture, direct_get, direct_post, has_alert,
                                   upload_file)

SUCCESS = "[role=status]:not([data-notice])"  # доп. 56: напоминание календаря тоже role=status
KINDS = ("holiday", "day_off", "workday", "short")


def _stand_reset_years(*years: int) -> None:
    """Подготовка через stand_shell: убрать у годов особые дни, отметку «загружен» и предпросмотры, неделю и часы
    вернуть к умолчанию (пн–пт, 09:00–18:00), сбросить кэш отметок месяцев и поднять номер версии календаря."""
    helpers.stand_shell(
        "import redis\n"
        "from datetime import time\n"
        "from django.apps import apps\n"
        "from django.conf import settings\n"
        f"years = {list(years)!r}\n"
        "apps.get_model('org.SpecialDay').objects.filter(date__year__in=years).delete()\n"
        "apps.get_model('org.CalendarYear').objects.filter(year__in=years).delete()\n"
        "apps.get_model('org.CalendarUpload').objects.filter(year__in=years).delete()\n"
        "apps.get_model('org.WorkCalendar').objects.update(work_weekdays=[0, 1, 2, 3, 4], "
        "day_start=time(9, 0), day_end=time(18, 0))\n"
        "r = redis.Redis.from_url(settings.VALKEY_URL)\n"
        "for k in list(r.scan_iter('*calendar:marks:*')):\n"
        "    r.delete(k)\n"
        "for k in list(r.scan_iter('*calendar:version')):\n"
        "    r.incr(k)\n"
        "print('ok')\n")


def _assert_russian(text: str) -> None:
    """FR-150, доп. 29 и 58: в «было / стало» нет латинских ключей событий календаря (§ 6), сырого JSON и
    секунд во времени."""
    assert not re.search(r"\b(year|totals|file_name|kind|date|work_weekdays|day_start|day_end|holidays_on_weekdays|"
                         r"moved_days_off|moved_workdays|short_days|work_days|holidays|day_offs|workdays|shorts)\b",
                         text), text
    assert not re.search(r'[{}\[\]"]', text), text
    assert not re.search(r"\b\d{1,2}:\d{2}:\d{2}\b", text), text


def _moscow_today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _open_year(page, year: int) -> None:
    """Открывает `/calendar/?year=<год>` и ждёт контейнер года."""
    page.goto(f"/calendar/?year={year}")
    expect(page.locator(f'[data-calendar-year][data-year="{year}"]')).to_be_visible()


def _loaded(page, year: int) -> str:
    """Значение `data-loaded` года на странице календаря."""
    _open_year(page, year)
    return page.locator("[data-calendar-year]").get_attribute("data-loaded")


def _kinds(page) -> dict:
    """Вид каждого дня открытого года: дата -> `data-day-kind` (ячейки `td[data-date]`)."""
    return page.eval_on_selector_all(
        "td[data-date]", "els => Object.fromEntries(els.map(e => [e.dataset.date, e.dataset.dayKind]))")


def _count_kind(page, year: int, kind: str) -> int:
    return page.locator(f'td[data-date^="{year}-"][data-day-kind="{kind}"]').count()


def _expected_totals(path, year: int) -> dict:
    """Ожидаемые числа предпросмотра, посчитанные по правилам плана («Перевод в особые дни») прямо из файла:
    число без пометки на будний день — праздник; «+» — перенесённый выходной; «*» — сокращённый; суббота или
    воскресенье вне списка месяца — перенесённый рабочий день; рабочих дней — из итоговой колонки файла."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    row = next(r for r in rows[1:] if r and r[0].strip() == str(year))
    total = {"holidays": 0, "day-offs": 0, "workdays": 0, "shorts": 0, "work-days": int(float(row[13]))}
    for month in range(1, 13):
        listed = set()
        for token in filter(None, (t.strip() for t in row[month].split(","))):
            number = int(token.rstrip("*+"))
            listed.add(number)
            weekday = date(year, month, number).weekday()
            if token.endswith("*"):
                total["shorts"] += 1
            elif token.endswith("+"):
                total["day-offs"] += 1
            elif weekday < 5:
                total["holidays"] += 1
        first = date(year, month, 1)
        for number in range(1, 32):
            try:
                day = first.replace(day=number)
            except ValueError:
                break
            if day.weekday() >= 5 and number not in listed:
                total["workdays"] += 1
    return total


def _file_for(year: int):
    """Файл года: настоящий из `tests/fixtures/calendar/` (2024–2027)."""
    return calendar_fixture(f"cal{year}.csv")


def _upload_year(page, year: int, file, **kw) -> None:
    """Форма `calendar-upload` на `/calendar/upload/`: год и файл, отправка."""
    page.goto("/calendar/upload/")
    form = page.locator('form[data-form="calendar-upload"]')
    expect(form).to_be_visible()
    form.locator("input[name=year]").fill(str(year))
    upload_file(form, file, **kw)


def _load_year(page, year: int, file=None) -> None:
    """Загрузка и подтверждение года интерфейсом; ждёт переход на `/calendar/?year=<год>` и сообщение об успехе."""
    _upload_year(page, year, file or _file_for(year))
    page.wait_for_url(re.compile(r"/calendar/upload/\d+/"))
    preview = page.locator("[data-calendar-preview]")
    expect(preview).to_be_visible()
    helpers.submit(preview.locator("form").filter(has=page.locator('input[name=confirm][value="1"]')))
    page.wait_for_url(re.compile(rf"/calendar/\?year={year}$"))
    expect(page.locator(SUCCESS).first).not_to_have_text("")


def test_o11_upload_year_preview_apply_and_other_years_kept(admin_page):
    """Сценарий 11, п. 1, 2, 7 (загрузка): файл 2027 года даёт предпросмотр с числами праздников, переносов и
    сокращённых дней; до подтверждения календарь 2027 не меняется и события в журнале нет; после подтверждения
    особые дни 2027 заменены загруженными, а уже загруженный 2026 год не тронут; журнал хранит «было / стало»
    (FR-145, FR-150)."""
    page = admin_page
    _stand_reset_years(2026, 2027)
    try:
        # исходное состояние: загружен только 2026 (второй год нужен, чтобы проверить «другие годы не тронуты»)
        # (журнал не очищается между тестами: считаем приращение числа событий)
        loaded_2027_before = len(audit_rows(page, "calendar.year_loaded", "2027"))
        _load_year(page, 2026, calendar_fixture("years_2024_2027.csv"))
        assert _loaded(page, 2026) == "true"
        snapshot_2026 = _kinds(page)
        assert any(kind in KINDS for kind in snapshot_2026.values()), "в 2026 году нет особых дней после загрузки"
        assert _loaded(page, 2027) == "false"

        # п. 1: предпросмотр называет четыре числа и рабочие дни — по файлу
        path = _file_for(2027)
        expected = _expected_totals(path, 2027)
        _upload_year(page, 2027, path)
        page.wait_for_url(re.compile(r"/calendar/upload/\d+/"))
        preview_url = page.url
        preview = page.locator("[data-calendar-preview]")
        expect(preview).to_be_visible()
        for name, value in expected.items():
            expect(preview).to_have_attribute(f"data-{name}", str(value))
        expect(preview.locator('input[name=confirm][value="1"]')).to_have_count(1)
        expect(page.locator("[data-manual-warning]")).to_have_count(0)  # год не загружен — ручных правок нет

        # п. 1: до подтверждения календарь и журнал не меняются
        assert _loaded(page, 2027) == "false"
        assert _kinds(page).get("2027-01-01") == "work", "до подтверждения 2027-01-01 уже не обычный день"
        assert not any(_count_kind(page, 2027, kind) for kind in KINDS), "до подтверждения появились особые дни"
        assert len(audit_rows(page, "calendar.year_loaded", "2027")) == loaded_2027_before

        # п. 2: подтверждение — особые дни 2027 заменены загруженными
        page.goto(preview_url)
        confirm = page.locator("[data-calendar-preview] form").filter(
            has=page.locator('input[name=confirm][value="1"]'))
        helpers.submit(confirm)
        page.wait_for_url(re.compile(r"/calendar/\?year=2027$"))
        expect(page.locator(SUCCESS).first).not_to_have_text("")
        expect(page.locator('[data-calendar-year][data-year="2027"]')).to_have_attribute("data-loaded", "true")
        for name, kind in (("holidays", "holiday"), ("day-offs", "day_off"), ("workdays", "workday"),
                           ("shorts", "short")):
            assert _count_kind(page, 2027, kind) == expected[name], f"дней вида {kind} не столько, сколько в файле"
        new_year_day = page.locator('td[data-date="2027-01-01"]')
        expect(new_year_day).to_have_attribute("data-day-kind", "holiday")
        expect(new_year_day.locator("span.cal-letter")).to_have_text("П")
        expect(new_year_day).to_contain_text("праздник")

        # п. 2: дни других лет не тронуты
        _open_year(page, 2026)
        assert _kinds(page) == snapshot_2026, "загрузка 2027 года изменила дни 2026 года"
        assert _loaded(page, 2026) == "true"

        # п. 7: журнал — одна запись «было / стало»; латинских ключей итогов в тексте нет (доп. 29)
        sides = audit_sides(page, "calendar.year_loaded", "2027")
        assert len(sides) == loaded_2027_before + 1, sides
        before, after = sides[0]  # новое событие — сверху
        # в «было» журнал выводит только изменившиеся поля, год не меняется (T-2260, разрешение владельца)
        assert "2027" in after
        assert "cal2027.csv" in after
        assert before != after
        for text in (before, after):
            _assert_russian(text)
        # 2027: перенесённых рабочих дней 0, поэтому сверка «workdays» выше для этого года тривиальна; переносы
        # (2024) проверяет загрузка того года в сценарии 13 (o13 грузит 2024 сам), новых загрузок года здесь нет.
    finally:
        _stand_reset_years(2026, 2027)


def test_o11_wrong_file_refused_day_edit_and_reupload_warning(admin_page):
    """Сценарий 11, п. 3, 4, 7 (правка дня): файл неверного формата или не того года отклоняется с причиной, календарь
    не меняется; в загруженном году день правится (перенесённый рабочий день и праздник), правка видна в календаре и
    в журнале «было / стало»; в незагруженном году правка отклонена; повторная загрузка файла предупреждает о ручных
    правках и заменяет их (FR-144, FR-145, FR-150)."""
    page = admin_page
    _stand_reset_years(2026, 2027, 2028)
    try:
        # п. 3: отказы; календарь не меняется (журнал не очищается между тестами: считаем приращение событий)
        loaded_2026_before = len(audit_rows(page, "calendar.year_loaded", "2026"))
        loaded_2027_before = len(audit_rows(page, "calendar.year_loaded", "2027"))
        assert _loaded(page, 2026) == "false"
        cases = (
            ("bad_totals_2026.csv", 2026, None),            # итоги не сходятся
            ("cp1251_2026.csv", 2026, None),                # не UTF-8
            ("extra_column_2026.csv", 2026, None),          # лишняя колонка
            ("missing_column_2026.csv", 2026, None),        # нет колонки
            ("cal2027.csv", 2026, "в файле нет 2026 года"),  # в файле нет строки этого года
        )
        for name, year, reason in cases:
            _upload_year(page, year, calendar_fixture(name))
            alert = page.locator("[role=alert]")
            expect(alert.first).to_be_visible()
            expect(page).not_to_have_url(re.compile(r"/calendar/upload/\d+/"))
            assert helpers.alert_text(page), f"отказ по {name} без причины"
            if reason:
                assert reason in helpers.alert_text(page), helpers.alert_text(page)
        _upload_year(page, 2026, b"", name="empty.csv", mime="text/csv")  # пустой файл (доп. 26)
        expect(page.locator("[role=alert]").first).to_be_visible()
        assert _loaded(page, 2026) == "false"
        assert not any(_count_kind(page, 2026, kind) for kind in KINDS)
        assert len(audit_rows(page, "calendar.year_loaded", "2026")) == loaded_2026_before

        # загружаем 2027 (настоящий файл) для правки дня
        _load_year(page, 2027)
        first_holiday = page.locator('td[data-date^="2027-"][data-day-kind="holiday"]').first
        holiday_date = first_holiday.get_attribute("data-date")
        saturday = next(d for d in (date(2027, 3, n) for n in range(1, 32)) if d.weekday() == 5).isoformat()
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "off")

        day_events_before = {d: len(audit_rows(page, "calendar.day_changed", d)) for d in (holiday_date, saturday)}
        refused_before = len(audit_rows(page, "calendar.day_changed", "2028-01-12"))

        # п. 4: правка дня — делаем рабочим праздник и обычную субботу
        for day, kind in ((holiday_date, "workday"), (saturday, "workday")):
            _open_year(page, 2027)
            page.locator(f'td[data-date="{day}"] a[data-day-edit][href="/calendar/days/{day}/"]').click()
            page.wait_for_url(re.compile(rf"/calendar/days/{day}/$"))
            form = page.locator('form[data-form="calendar-day"]')
            expect(form).to_be_visible()
            form.locator("select[name=kind]").select_option(kind)
            form.locator("button[type=submit]").click()
            page.wait_for_url(re.compile(r"/calendar/\?year=2027$"))
            expect(page.locator(SUCCESS).first).not_to_have_text("")
            expect(page.locator(f'td[data-date="{day}"]')).to_have_attribute("data-day-kind", kind)
        _open_year(page, 2027)  # изменение сохранилось
        expect(page.locator(f'td[data-date="{holiday_date}"]')).to_have_attribute("data-day-kind", "workday")
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "workday")

        # п. 7: журнал по дню — «было / стало»
        sides = audit_sides(page, "calendar.day_changed", saturday)
        assert len(sides) == day_events_before[saturday] + 1, sides
        assert sides[0][0] != sides[0][1] and sides[0][1]
        _assert_russian(sides[0][0])
        _assert_russian(sides[0][1])
        assert len(audit_sides(page, "calendar.day_changed", holiday_date)) == day_events_before[holiday_date] + 1

        # правка дня в незагруженном году — отказ, ссылок правки нет
        _open_year(page, 2028)
        expect(page.locator("a[data-day-edit]")).to_have_count(0)
        refused = direct_post(page, "/calendar/days/2028-01-12/", {"kind": "holiday"})
        assert refused.status == 200 and has_alert(refused), refused.status
        assert len(audit_rows(page, "calendar.day_changed", "2028-01-12")) == refused_before

        # п. 4: повторная загрузка предупреждает о двух ручных правках и заменяет их
        _upload_year(page, 2027, _file_for(2027))
        page.wait_for_url(re.compile(r"/calendar/upload/\d+/"))
        warning = page.locator("[data-manual-warning]")
        expect(warning).to_be_visible()
        expect(warning).to_have_attribute("data-manual-days", "2")
        _open_year(page, 2027)  # предпросмотр ничего не заменил
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "workday")
        _load_year(page, 2027)
        expect(page.locator(f'td[data-date="{holiday_date}"]')).to_have_attribute("data-day-kind", "holiday")
        expect(page.locator(f'td[data-date="{saturday}"]')).to_have_attribute("data-day-kind", "off")
        assert len(audit_sides(page, "calendar.year_loaded", "2027")) == loaded_2027_before + 2
    finally:
        _stand_reset_years(2026, 2027, 2028)


def test_o11_reminder_and_no_right_refused(admin_page, employee):
    """Сценарий 11, п. 5, 6: год не загружен — действуют только рабочие дни недели, а обладатель права «Рабочий
    календарь» видит напоминание на главной и в календаре; после загрузки напоминание о годе исчезает; сотрудник без
    права не видит напоминаний и форм изменения, а прямые запросы загрузки, настроек и правки дня получают 403 и
    ничего не меняют (FR-146, FR-123)."""
    page = admin_page
    today = _moscow_today()
    year = today.year
    _stand_reset_years(year, year + 1)
    try:
        # п. 5: год не загружен — только рабочие дни недели, правки дня нет
        page.goto("/calendar/")
        container = page.locator("[data-calendar-year]")
        expect(container).to_have_attribute("data-year", str(year))
        expect(container).to_have_attribute("data-loaded", "false")
        kinds = _kinds(page)
        assert set(kinds.values()) <= {"work", "off"}, set(kinds.values())
        for day, kind in kinds.items():
            assert kind == ("off" if date.fromisoformat(day).weekday() >= 5 else "work"), (day, kind)
        expect(page.locator("a[data-day-edit]")).to_have_count(0)

        # п. 5: напоминание на странице календаря и на главной, с текстом и ссылкой на загрузку
        notice = page.locator(f'[data-notice="calendar-year"][data-year="{year}"]')
        expect(notice).to_have_count(1)
        expect(notice).to_have_attribute("role", "status")
        expect(notice).to_contain_text(f"Не загружен производственный календарь на {year} год.")
        expect(notice.get_by_role("link", name="Загрузить файл")).to_have_attribute("href", "/calendar/upload/")
        page.goto("/")
        home = page.locator(f'[data-home-notices] [data-notice="calendar-year"][data-year="{year}"]')
        expect(home).to_have_count(1)
        expect(home).to_contain_text(f"Не загружен производственный календарь на {year} год.")
        home.get_by_role("link", name="Загрузить файл").click()
        page.wait_for_url(re.compile(r"/calendar/upload/$"))
        if today.month == 12:  # с 1 декабря — отдельное напоминание на следующий год, пока он не загружен
            page.goto("/")
            expect(page.locator(f'[data-notice="calendar-year"][data-year="{year + 1}"]')).to_have_count(1)

        # загружаем текущий год: напоминание о нём исчезает
        _load_year(page, year, _year_file_or_synthetic(year))
        expect(page.locator(f'[data-notice="calendar-year"][data-year="{year}"]')).to_have_count(0)
        page.goto("/")
        expect(page.locator(f'[data-home-notices] [data-notice="calendar-year"][data-year="{year}"]')).to_have_count(0)
        if today.month != 12:  # до декабря следующий год напоминания не требует
            expect(page.locator(f'[data-notice="calendar-year"][data-year="{year + 1}"]')).to_have_count(0)

        # п. 6: сотрудник без права «Рабочий календарь»
        acc = employee()
        emp = acc.page
        day_edit = next(d for d, k in _kinds_of_year(page, year).items() if k == "work")
        emp.goto("/")
        expect(emp.locator('[data-notice="calendar-year"]')).to_have_count(0)
        response = emp.goto(f"/calendar/?year={year}")
        assert response.status == 200, "сотрудник с правом просмотра не видит календарь"
        expect(emp.locator(f'[data-calendar-year][data-year="{year}"]')).to_be_visible()
        expect(emp.locator('a[data-action="calendar-upload"]')).to_have_count(0)
        expect(emp.locator('form[action="/calendar/settings/"]')).to_have_count(0)
        expect(emp.locator("a[data-day-edit]")).to_have_count(0)
        expect(emp.locator('[data-notice="calendar-year"]')).to_have_count(0)
        before = _kinds(emp)
        settings_events = len(audit_rows(page, "calendar.settings_changed"))
        assert emp.goto("/calendar/upload/").status == 403
        assert emp.goto(f"/calendar/days/{day_edit}/").status == 403
        assert direct_get(emp, "/calendar/upload/").status == 403
        assert direct_post(emp, "/calendar/settings/",
                           {"work_weekdays": ["0", "1", "2", "3", "4", "5"], "day_start": "09:00",
                            "day_end": "18:00"}).status == 403
        assert direct_post(emp, "/calendar/days/" + day_edit + "/", {"kind": "holiday"}).status == 403
        assert direct_post(emp, "/calendar/upload/", {"year": str(year + 1)}).status == 403
        assert audit_rows(page, "calendar.day_changed", day_edit) == []
        assert len(audit_rows(page, "calendar.settings_changed")) == settings_events
        emp.goto(f"/calendar/?year={year}")
        assert _kinds(emp) == before
        expect(emp.locator('form[action="/calendar/settings/"]')).to_have_count(0)
    finally:
        _stand_reset_years(year, year + 1)


def _year_file_or_synthetic(year: int):
    """Файл текущего года: настоящий из `tests/fixtures/calendar/` (2024–2027); для других лет — свой файл формата
    открытых данных, собранный `support_org.calendar_csv` (импорт внутри: модуль тянет только стандартную библиотеку
    и pytest-помощников приёмки)."""
    try:
        return _file_for(year)
    except FileNotFoundError:
        from tests.support_org import calendar_csv
        return calendar_csv(year, {1: "1,2,3,4,5,6,7,8", 5: "1,9"})


def _kinds_of_year(page, year: int) -> dict:
    _open_year(page, year)
    return _kinds(page)
