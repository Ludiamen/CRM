"""T-2148: сценарий 13 — сотрудник смотрит рабочий календарь, поле выбора даты выделяет выходные и праздники
(FR-146, FR-147, FR-148).

Опора на рабочую неделю по умолчанию (Пн–Пт): o11/o12 возвращают её в finally."""
import calendar as std_calendar
import datetime
import re
import secrets
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_org import calendar_fixture, upload_file

# Поля даты портала: дата рождения на «Мой профиль» и «с» / «по» в журнале событий (план: «Поле выбора даты»,
# test_date_field::test_every_portal_datefield_uses_portal_widget).
DATE_FIELDS = (("/me/", "birth_date"), ("/audit/", "date_from"), ("/audit/", "date_to"))

# Подписи и буквы видов дня (CONTRACT-002 § 9.5, решение Opus G1).
LABELS = {"off": "выходной", "holiday": "праздник", "day_off": "перенесённый выходной",
          "workday": "перенесённый рабочий день", "short": "сокращённый день"}
LETTERS = {"off": "В", "holiday": "П", "day_off": "Н", "workday": "Р", "short": "С"}

# Дни настоящего файла cal2024.csv (tests/fixtures/calendar/SOURCE.md; виды выведены из файла):
# апрель 2024 — 24-е среда (обычный), 27-е суббота вне списка (перенесённый рабочий), 28-е воскресенье (выходной),
# 29-е понедельник «+» (перенесённый выходной); январь — 1-е праздник; май — 1-е праздник, 8-е «*» (сокращённый).
APRIL_KINDS = {"2024-04-24": "work", "2024-04-27": "workday", "2024-04-28": "off", "2024-04-29": "day_off"}
MAY_KINDS = {"2024-05-01": "holiday", "2024-05-08": "short"}
YEAR_KINDS = {"2024-01-01": "holiday", **APRIL_KINDS, **MAY_KINDS}


def _load_year_2024(admin_page) -> None:
    """Администратор загружает календарь 2024 года через интерфейс: форма загрузки → предпросмотр → подтверждение.
    Повторная загрузка безвредна: тот же файл даёт те же дни."""
    admin_page.goto("/calendar/upload/")
    form = admin_page.locator('form[data-form="calendar-upload"]')
    form.locator("input[name=year]").fill("2024")
    upload_file(form, calendar_fixture("cal2024.csv"), submit=False)
    form.locator("button[type=submit]").click()
    admin_page.wait_for_url(re.compile(r"/calendar/upload/\d+/$"))
    expect(admin_page.locator("[data-calendar-preview]")).to_be_visible()
    confirm = admin_page.locator("form:has(input[name=confirm])")
    confirm.locator("button[type=submit]").click()
    admin_page.wait_for_url(re.compile(r"/calendar/\?year=2024$"))
    expect(admin_page.locator('[data-calendar-year][data-year="2024"][data-loaded="true"]')).to_be_visible()


def _moscow_today() -> datetime.date:
    """Сегодня по Москве, как считают портал и браузер стенда (NFR-107, доп. 63)."""
    return datetime.datetime.now(ZoneInfo("Europe/Moscow")).date()


def _wrapper(page, name: str):
    """Обёртка поля даты с полем ввода `name` (доп. 57)."""
    return page.locator(f'[data-datefield]:has(input[data-datefield-input][name="{name}"])')


def _open_grid(page, name: str, month: str):
    """Открывает сетку поля `name` кнопкой «Выбрать дату» и листает её на месяц `month` (`ГГГГ-ММ`) списками года и
    месяца сетки (§ 9.6). Возвращает корень сетки `[data-datefield-grid]`."""
    wrapper = _wrapper(page, name)
    expect(wrapper).to_have_count(1)
    wrapper.locator("button[data-datefield-open]").click()
    grid = wrapper.locator("[data-datefield-grid]")
    expect(grid).to_be_visible()
    year, number = month.split("-")
    if not re.fullmatch(rf"{year}-\d\d", grid.get_attribute("data-month") or ""):
        grid.locator("select[name=year]").select_option(year)
        expect(grid).to_have_attribute("data-month", re.compile(rf"^{year}-\d\d$"))
    if grid.get_attribute("data-month") != month:
        grid.locator("select[name=month]").select_option(str(int(number)))
        expect(grid).to_have_attribute("data-month", month)
    return grid


def _day(grid, iso: str):
    return grid.locator(f'button[data-date="{iso}"]')


def _expect_day_kind(day, kind: str) -> None:
    """Кнопка дня в сетке: вид, класс `date-day-<вид>` и скрытая подпись для чтения с экрана (§ 9.6, 9.5);
    у обычного дня подписи нет; кнопка не отключена — выбрать можно любой день."""
    expect(day).to_have_count(1)
    expect(day).to_have_attribute("data-day-kind", kind)
    expect(day).to_be_enabled()
    if kind == "work":
        expect(day.locator(".visually-hidden")).to_have_count(0)
    else:
        expect(day).to_have_class(re.compile(rf"\bdate-day-{kind}\b"))
        expect(day.locator(".visually-hidden")).to_have_text(LABELS[kind])


def test_o13_calendar_page_12_months_marked_not_only_by_color(admin_page, employee):
    """Сценарий 13, п. 1 и 4: у загруженного года сотрудник видит 12 месяцев, выходные, праздники, перенесённые и
    сокращённые дни отличаются от обычных буквой и подписью (не только цветом), есть легенда и выбор года; при
    ширине окна 360 px горизонтальной прокрутки нет (FR-147)."""
    _load_year_2024(admin_page)
    viewer = employee(full_name=f"Календарь{secrets.token_hex(3)} Смотрящий")
    page = viewer.page

    # п. 1: сотрудник открывает «Календарь» загруженного года
    page.goto("/calendar/?year=2024")
    container = page.locator('[data-calendar-year][data-year="2024"]')
    expect(container).to_have_attribute("data-loaded", "true")
    for number in range(1, 13):
        month = container.locator(f'[data-month="{number}"]')
        expect(month).to_have_count(1)
        expect(month.locator("thead th")).to_have_text(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"])
        expect(month.locator("tbody tr[data-week]").first).to_be_visible()
    # п. 1: в 2024 году 366 дней, у каждого дня ячейка с видом; ячейки вне месяца пустые, без data-date (доп. 60)
    expect(container.locator("td[data-date][data-day-kind]")).to_have_count(366)

    # п. 1: выходные, праздники, перенесённые и сокращённые дни отличаются от обычных и подписаны не только цветом
    for iso, kind in YEAR_KINDS.items():
        cell = container.locator(f'td[data-date="{iso}"]')
        expect(cell).to_have_count(1)
        expect(cell).to_have_attribute("data-day-kind", kind)
        if kind == "work":
            expect(cell.locator(".cal-letter")).to_have_count(0)
            expect(cell.locator(".visually-hidden")).to_have_count(0)
        else:
            expect(cell.locator(".cal-letter")).to_have_text(LETTERS[kind])
            expect(cell.locator(".visually-hidden")).to_have_text(LABELS[kind])
    # п. 1: легенда с теми же буквами и подписями
    for kind in LABELS:
        item = page.locator(f'[data-legend] [data-legend-item="{kind}"]')
        expect(item).to_have_count(1)
        expect(item).to_contain_text(LETTERS[kind])
        expect(item).to_contain_text(LABELS[kind])
    # п. 1: выбор года — среди значений есть загруженный
    expect(page.locator('select[name=year] option[value="2024"]')).to_have_count(1)

    # п. 4: ширина окна 360 px — горизонтальной прокрутки нет
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto("/calendar/?year=2024")
    expect(page.locator('[data-calendar-year][data-year="2024"]')).to_be_visible()
    assert helpers.no_horizontal_scroll(page), "на /calendar/ при ширине 360 px есть горизонтальная прокрутка"


def test_o13_every_date_field_marks_weekends_and_holidays(admin_page):
    """Сценарий 13, п. 2: в каждом поле выбора даты портала (дата рождения на «Мой профиль», «с» и «по» в журнале)
    открытая сетка выделяет выходные, праздники, перенесённые и сокращённые дни, а выбрать праздник всё равно можно
    (FR-148)."""
    _load_year_2024(admin_page)
    page = admin_page
    for path, name in DATE_FIELDS:
        # п. 2: поле даты открыто — в сетке апреля выделены выходной и перенесённые дни
        page.goto(path)
        grid = _open_grid(page, name, "2024-04")
        for iso, kind in APRIL_KINDS.items():
            _expect_day_kind(_day(grid, iso), kind)
        # п. 2: в сетке мая — праздник и сокращённый день
        grid.locator("[data-datefield-next]").click()
        expect(grid).to_have_attribute("data-month", "2024-05")
        for iso, kind in MAY_KINDS.items():
            _expect_day_kind(_day(grid, iso), kind)
        # п. 2: выбрать такую дату всё равно можно — праздник переносится в поле ввода
        _day(grid, "2024-05-01").click()
        expect(_wrapper(page, name).locator("input[data-datefield-input]")).to_have_value("01.05.2024")
        # щелчок по дню — как Enter: сетка закрывается, контейнер снова hidden (доп. 59)
        expect(_wrapper(page, name).locator("[data-datefield-picker]")).to_be_hidden()


def test_o13_date_field_keyboard_arrows_pages_home_end_enter_esc(admin_page):
    """Сценарий 13, п. 2 (клавиатура, решение C9): в поле даты стрелки двигают фокус на день и неделю (в том числе
    через край месяца), PageUp и PageDown — на месяц, Home и End — на понедельник и воскресенье, Enter пишет дату
    ДД.ММ.ГГГГ и закрывает сетку, Esc закрывает сетку и возвращает фокус на «Выбрать дату» (FR-148)."""
    _load_year_2024(admin_page)
    page = admin_page
    page.goto("/me/")
    name = "birth_date"
    wrapper = _wrapper(page, name)
    field = wrapper.locator("input[data-datefield-input]")
    # при открытии (поле пусто) фокус на сегодняшнем дне показанного месяца (доп. 59)
    today = _moscow_today()
    wrapper.locator("button[data-datefield-open]").click()
    opened = wrapper.locator("[data-datefield-grid]")
    expect(opened).to_be_visible()
    expect(opened).to_have_attribute("data-month", today.strftime("%Y-%m"))
    expect(_day(opened, today.isoformat())).to_be_focused()
    page.keyboard.press("Escape")
    expect(wrapper.locator("[data-datefield-picker]")).to_be_hidden()
    grid = _open_grid(page, name, "2024-04")

    def focus_day(iso: str) -> None:
        _day(grid, iso).focus()
        expect(_day(grid, iso)).to_be_focused()

    def press(key: str, iso: str, month: str) -> None:
        """Нажимает клавишу и ждёт фокус на дне `iso` сетки месяца `month` (соседний месяц загружается по HTMX)."""
        page.keyboard.press(key)
        expect(grid).to_have_attribute("data-month", month)
        expect(_day(grid, iso)).to_be_focused()

    # стрелки: ±1 день, ±7 дней (15 апреля 2024 — понедельник)
    focus_day("2024-04-15")
    press("ArrowRight", "2024-04-16", "2024-04")
    press("ArrowLeft", "2024-04-15", "2024-04")
    press("ArrowDown", "2024-04-22", "2024-04")
    press("ArrowUp", "2024-04-15", "2024-04")
    # переход через край месяца: влево с 1 апреля — 31 марта, вправо — обратно; вверх с 1 апреля — 25 марта
    focus_day("2024-04-01")
    press("ArrowLeft", "2024-03-31", "2024-03")
    press("ArrowRight", "2024-04-01", "2024-04")
    press("ArrowUp", "2024-03-25", "2024-03")
    # вниз с 25 марта — 1 апреля (через край вперёд)
    press("ArrowDown", "2024-04-01", "2024-04")
    # PageDown и PageUp: тот же день соседнего месяца
    focus_day("2024-04-15")
    press("PageDown", "2024-05-15", "2024-05")
    press("PageUp", "2024-04-15", "2024-04")
    # PageDown с 31 марта — последний день апреля (30-е); с 31 января — 29 февраля високосного года
    press("PageUp", "2024-03-15", "2024-03")
    focus_day("2024-03-31")
    press("PageDown", "2024-04-30", "2024-04")
    grid.locator("select[name=month]").select_option("1")
    expect(grid).to_have_attribute("data-month", "2024-01")
    focus_day("2024-01-31")
    press("PageDown", "2024-02-29", "2024-02")
    # Home и End: понедельник и воскресенье той же недели (17 апреля 2024 — среда)
    grid.locator("select[name=month]").select_option("4")
    expect(grid).to_have_attribute("data-month", "2024-04")
    focus_day("2024-04-17")
    press("Home", "2024-04-15", "2024-04")
    press("End", "2024-04-21", "2024-04")
    # Home и End через край месяца: 1 мая 2024 — среда; понедельник 29 апреля, воскресенье 5 мая (§ 9.6)
    focus_day("2024-04-30")
    press("ArrowRight", "2024-05-01", "2024-05")
    press("Home", "2024-04-29", "2024-04")
    press("ArrowRight", "2024-04-30", "2024-04")
    press("ArrowRight", "2024-05-01", "2024-05")
    press("End", "2024-05-05", "2024-05")
    grid.locator("select[name=month]").select_option("4")
    expect(grid).to_have_attribute("data-month", "2024-04")

    # Esc: сетка закрывается, фокус на кнопке «Выбрать дату», поле осталось пустым
    focus_day("2024-04-17")
    page.keyboard.press("Escape")
    expect(wrapper.locator("[data-datefield-picker]")).to_be_hidden()
    expect(wrapper.locator("button[data-datefield-open]")).to_be_focused()
    expect(field).to_have_value("")

    # Enter на празднике (1 мая 2024): дата пишется в поле как ДД.ММ.ГГГГ, сетка закрывается
    grid = _open_grid(page, name, "2024-05")
    focus_day("2024-05-01")
    page.keyboard.press("Enter")
    expect(field).to_have_value("01.05.2024")
    expect(wrapper.locator("[data-datefield-picker]")).to_be_hidden()
    # повторное открытие (доп. 63): месяц в адрес не попадает, сетка открывается на текущем месяце по Москве, фокус на
    # сегодняшнем дне (выбранный 01.05.2024 не в показанном месяце)
    today = _moscow_today()
    wrapper.locator("button[data-datefield-open]").click()
    reopened = wrapper.locator("[data-datefield-grid]")
    expect(reopened).to_be_visible()
    expect(reopened).to_have_attribute("data-month", today.strftime("%Y-%m"))
    expect(_day(reopened, today.isoformat())).to_be_focused()
    # листание списками года и месяца на 2024-05: выбранный день помечен aria-pressed="true"
    reopened.locator("select[name=year]").select_option("2024")
    expect(reopened).to_have_attribute("data-month", re.compile(r"^2024-\d\d$"))
    reopened.locator("select[name=month]").select_option("5")
    expect(reopened).to_have_attribute("data-month", "2024-05")
    expect(_day(reopened, "2024-05-01")).to_have_attribute("aria-pressed", "true")


def test_o13_unloaded_year_only_weekends(employee):
    """Сценарий 13, п. 3: в незагруженном году (текущий +4, его не грузит никто) календарь и сетка поля даты выделяют
    только выходные дни недели — ни праздников, ни перенесённых, ни сокращённых дней (FR-146)."""
    year = _moscow_today().year + 4
    viewer = employee(full_name=f"Пустой{secrets.token_hex(3)} Год")
    page = viewer.page

    days = [datetime.date(year, 1, 1) + datetime.timedelta(days=n)
            for n in range(366 if std_calendar.isleap(year) else 365)]
    weekends = [d for d in days if d.weekday() >= 5]

    # п. 3: сотрудник открывает календарь года, который не загружен
    page.goto(f"/calendar/?year={year}")
    container = page.locator(f'[data-calendar-year][data-year="{year}"]')
    expect(container).to_have_attribute("data-loaded", "false")
    for number in range(1, 13):
        expect(container.locator(f'[data-month="{number}"]')).to_have_count(1)
    expect(container.locator("td[data-date][data-day-kind]")).to_have_count(len(days))
    expect(container.locator('td[data-day-kind="off"]')).to_have_count(len(weekends))
    expect(container.locator('td[data-day-kind="work"]')).to_have_count(len(days) - len(weekends))
    for kind in ("holiday", "day_off", "workday", "short"):
        expect(container.locator(f'td[data-day-kind="{kind}"]')).to_have_count(0)
    # 1 января незагруженного года — не праздник
    first = container.locator(f'td[data-date="{year}-01-01"]')
    expect(first).to_have_attribute("data-day-kind", "off" if days[0].weekday() >= 5 else "work")

    # п. 3: в поле даты тот же год — выделены только суббота и воскресенье
    page.goto("/me/")
    grid = _open_grid(page, "birth_date", f"{year}-01")
    january = [d for d in days if d.month == 1]
    january_weekends = [d for d in january if d.weekday() >= 5]
    expect(grid.locator("button[data-date]")).to_have_count(len(january))
    expect(grid.locator('button[data-day-kind="off"]')).to_have_count(len(january_weekends))
    expect(grid.locator('button[data-day-kind="work"]')).to_have_count(len(january) - len(january_weekends))
    for kind in ("holiday", "day_off", "workday", "short"):
        expect(grid.locator(f'button[data-day-kind="{kind}"]')).to_have_count(0)
    for d in january_weekends[:2]:
        _expect_day_kind(_day(grid, d.isoformat()), "off")
