"""T-6142: сценарий 3 — таблица записей: столбцы, фильтры, готовые отборы, сортировка, групповые действия, 360 px
(FR-509, FR-514, FR-518, FR-519, FR-520, FR-521, FR-523, FR-539, NFR-507).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md, разделы 10.3, 11.3, 15.3 К-15, 15.4):
- каждый тест заводит свои списки с уникальными названиями (`unique_list_name`), шесть стартовых не трогает (решение 56);
  общих настроек тесты файла не меняют; `shift()` и команд стенда нет (сроки задаются датами записей, «сегодня» — по Москве);
- управляющий — `admin_page`; читающий и правящий — `make_list_reader` / `make_list_editor`;
- массовая подготовка (51 запись для 50 строк страницы): прямые POST формы `/lists/<id>/add/` от имени управляющего,
  каждый ответ проверяется на 302 (`_direct_add_record`); остальные записи — формой;
- фильтры (п. 3) задаются параметрами адреса (раздел 10.3): внутреннее устройство `[data-lists-filter]` контракт не
  задаёт, тест проверяет наличие зацепки `[data-lists-filter="<код>"]` у поля;
- п. 1 сценария: отбор «Все» и порядок строк без сортировки; порядок, которого контракт не задаёт, не проверяется.
"""
import re
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers_lists, helpers_org
from tests.e2e.helpers_lists import (
    add_field, archive_record, create_list, create_record, make_list_editor, make_list_reader, open_add_record,
    open_settings, pick, post_status, set_choices, status_of, submit_record, fill_record,
    unique_list_name, unique_word, open_narrow, page_fits)

MOSCOW = ZoneInfo("Europe/Moscow")
ROWS = "#lists-grid tr[data-record-number]"


# --- Помощники файла -----------------------------------------------------------------------------------------

def _day(offset: int) -> str:
    """Дата «сегодня по Москве» плюс `offset` дней в виде ДД.ММ.ГГГГ (дата хоста не берётся)."""
    return (datetime.now(MOSCOW).date() + timedelta(days=offset)).strftime("%d.%m.%Y")


def _open_grid(page, list_id, query: str = "") -> None:
    page.goto(f"/lists/{list_id}/{query}")
    expect(page.locator('[data-lists-page="grid"]')).to_be_visible()
    expect(page.locator("#lists-grid")).to_be_visible()


def _titles(page) -> list:
    """Названия записей строк таблицы по порядку (`a[data-field="title"]`)."""
    return page.locator(f'{ROWS} a[data-field="title"]').evaluate_all("els => els.map(e => e.textContent.trim())")


def _numbers(page) -> list:
    """Номера записей строк таблицы по порядку (`data-record-number`)."""
    return page.locator(ROWS).evaluate_all("els => els.map(e => Number(e.dataset.recordNumber))")


def _cols(page) -> set:
    """Коды ячеек `td[data-col]` первой строки таблицы."""
    first = page.locator(ROWS).first
    expect(first).to_be_visible()
    return set(first.locator("td[data-col]").evaluate_all("els => els.map(e => e.dataset.col)"))


def _shows(page, titles) -> None:
    """В таблице ровно записи с этими названиями (порядок не проверяется: контракт его без сортировки не задаёт)."""
    expect(page.locator(ROWS)).to_have_count(len(titles))
    assert sorted(_titles(page)) == sorted(titles)


def _found(page, count: int) -> None:
    """`[data-lists-found]` показывает «Найдено: N» (число не как часть большего: «5» не равно «50»)."""
    expect(page.locator("[data-lists-found]")).to_contain_text(re.compile(rf"Найдено:\s*{count}(?!\d)"))


def _preset(page, name: str):
    return page.locator(f'[data-lists-presets] a[data-preset="{name}"]')


def _press_preset(page, name: str) -> None:
    link = _preset(page, name)
    expect(link).to_be_visible()
    link.click()
    expect(_preset(page, name)).to_have_attribute("aria-current", "page")


def _record(page, list_id, title: str, values: dict | None = None, picks: dict | None = None) -> int:
    """Запись формой: значения (`fill_record`), затем выбор людей `picks` (код → слово запроса)."""
    open_add_record(page, list_id)
    fill_record(page, {"title": title, **(values or {})})
    for code, query in (picks or {}).items():
        pick(page, code, query)
    number = submit_record(page)
    assert number, f"запись «{title}» не создана: {helpers_lists.refusal_codes(page)}"
    return number


def _direct_add_record(page, list_id, title: str, **values) -> None:
    """Массовая подготовка: прямой POST формы записи от имени управляющего; успех — 302 (10.2)."""
    status = post_status(page, f"/lists/{list_id}/add/", {"title": title, **values})
    assert status == 302, f"запись «{title}» не создана прямым POST: {status}"


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l03_reader_opens_list_with_all_preset_without_archive_default_columns_50_per_page_and_record_count_and_row_click_opens_card(
        admin_page, employee):
    """Сценарий 3, п. 1: читающий открывает список — отбор «Все» без архива, столбцы «Название» и поля с «показывать в
    таблице», 50 строк на странице, число записей, нажатие на название открывает карточку (FR-518)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Оборудование"))
    model = add_field(page, list_id, "Модель", "string", show_in_table=True)
    inv = add_field(page, list_id, "Инвентарный номер", "string", show_in_table=True)
    note = add_field(page, list_id, "Примечание", "string", show_in_table=False)
    archived_title = f"Архивный {unique_word()}"
    archived = create_record(page, list_id, archived_title, {model: "Модель-архив"})
    archive_record(page, list_id, archived)
    for i in range(1, 52):
        _direct_add_record(page, list_id, f"Монитор {i:02d}", **{model: f"Модель-{i:02d}", inv: f"INV-{i:02d}",
                                                                   note: f"Заметка-{i:02d}"})
    reader = make_list_reader(employee, admin_page, list_id)
    rp = reader.page
    # п. 1: отбор «Все» — текущий, число записей без архива
    _open_grid(rp, list_id)
    expect(_preset(rp, "all")).to_have_attribute("aria-current", "page")
    _found(rp, 51)
    # п. 1: 50 строк на странице, есть следующая; архивной записи среди них нет
    expect(rp.locator(ROWS)).to_have_count(50)
    expect(rp.locator('a[data-action="next-page"]')).to_be_visible()
    assert archived_title not in _titles(rp)
    # п. 1: столбцы по умолчанию — «Название» и поля с «показывать в таблице»; «Примечание» не показано
    cols = _cols(rp)
    assert {model, inv} <= cols, f"столбцы первой строки: {cols}"
    assert note not in cols, f"«Примечание» показано по умолчанию: {cols}"
    first = rp.locator(ROWS).first
    title = first.locator('a[data-field="title"]').inner_text().strip()
    suffix = title.split()[-1]
    expect(first.locator(f'td[data-col="{model}"]')).to_have_text(f"Модель-{suffix}")
    expect(first.locator(f'td[data-col="{inv}"]')).to_have_text(f"INV-{suffix}")
    # п. 1: вторая страница — одна оставшаяся запись (архивная в «Все» не входит)
    rp.locator('a[data-action="next-page"]').click()
    expect(rp.locator(ROWS)).to_have_count(1)
    assert archived_title not in _titles(rp)
    # п. 1: нажатие на название открывает карточку этой записи
    _open_grid(rp, list_id)
    link = rp.locator(ROWS).first.locator('a[data-field="title"]')
    name = link.inner_text().strip()
    number = rp.locator(ROWS).first.get_attribute("data-record-number")
    link.click()
    rp.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/$"))
    expect(rp.locator("[data-lists-record]")).to_contain_text(name)


def test_l03_chosen_columns_kept_for_employee_and_list_after_reopen_and_other_employee_has_own(admin_page, employee):
    """Сценарий 3, п. 2: сотрудник выбрал другие столбцы — после закрытия и повторного открытия выбор сохранён за ним
    для этого списка; у другого сотрудника столбцы свои, по умолчанию (FR-518)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Столбцы"))
    model = add_field(page, list_id, "Модель", "string", show_in_table=True)
    inv = add_field(page, list_id, "Инвентарный номер", "string", show_in_table=True)
    note = add_field(page, list_id, "Примечание", "string", show_in_table=False)
    for i in range(1, 4):
        _direct_add_record(page, list_id, f"Прибор {i}", **{model: f"М-{i}", inv: f"И-{i}", note: f"З-{i}"})
    first = make_list_reader(employee, admin_page, list_id)
    second = employee(role=first.list_role_name)
    fp = first.page
    # п. 2: по умолчанию «Модель» и «Инвентарный номер» есть, «Примечания» нет
    _open_grid(fp, list_id)
    cols = _cols(fp)
    assert {model, inv} <= cols and note not in cols, f"столбцы по умолчанию: {cols}"
    # п. 2: выбор других столбцов — «Примечание» вместо «Модели»
    fp.get_by_role("button", name="Выбрать столбцы").click()
    dialog = fp.locator("dialog[data-lists-columns]")
    expect(dialog).to_be_visible()
    expect(dialog.locator(f'input[name="columns"][data-lists-column-choice="{model}"]')).to_be_checked()
    expect(dialog.locator(f'input[name="columns"][data-lists-column-choice="{note}"]')).not_to_be_checked()
    dialog.locator(f'input[name="columns"][data-lists-column-choice="{model}"]').uncheck()
    dialog.locator(f'input[name="columns"][data-lists-column-choice="{note}"]').check()
    dialog.locator("button[type=submit]:not([data-action])").click()
    expect(fp.locator(f'{ROWS} td[data-col="{note}"]').first).to_be_visible()
    cols = _cols(fp)
    assert note in cols and model not in cols, f"столбцы после выбора: {cols}"
    # п. 2: закрыл список и открыл снова — выбор сохранён
    fp.goto("/lists/")
    _open_grid(fp, list_id)
    cols = _cols(fp)
    assert note in cols and model not in cols and inv in cols, f"столбцы после повторного открытия: {cols}"
    # п. 2: у другого сотрудника столбцы свои — по умолчанию
    _open_grid(second.page, list_id)
    cols = _cols(second.page)
    assert {model, inv} <= cols and note not in cols, f"столбцы другого сотрудника: {cols}"


def test_l03_equals_from_to_and_contains_filters_leave_only_matching_rows_and_show_found_count(admin_page):
    """Сценарий 3, п. 3: фильтры по «Состоянию» (равно), «Дате покупки» (от/до) и «Названию» (содержит) оставляют в
    таблице только подходящие записи; число найденного показано (FR-519)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Фильтры"))
    state = add_field(page, list_id, "Состояние", "choice", show_in_table=True)
    ids = set_choices(page, list_id, state, ["Работает", "Сломан", "Склад"])
    bought = add_field(page, list_id, "Дата покупки", "date", show_in_table=True)
    data = [("Принтер HP", "Работает", "10.01.2024"), ("Принтер Canon", "Сломан", "15.03.2024"),
            ("Монитор Dell", "Работает", "20.06.2024"), ("Монитор LG", "Склад", "25.09.2024"),
            ("Ноутбук Lenovo", "Сломан", "30.12.2024")]
    for title, label, date in data:
        _record(page, list_id, title, {state: label, bought: date})
    _open_grid(page, list_id)
    _found(page, 5)
    for code in (state, bought):
        expect(page.locator(f'[data-lists-filter="{code}"]')).to_have_count(1)
    broken, working = ids[1], ids[0]
    # п. 3: «равно» — Состояние = Сломан
    _open_grid(page, list_id, f"?f.{state}={broken}")
    _shows(page, ["Принтер Canon", "Ноутбук Lenovo"])
    _found(page, 2)
    # п. 3: «от/до» — дата покупки с 01.03.2024 по 30.09.2024
    _open_grid(page, list_id, f"?f.{bought}.from=01.03.2024&f.{bought}.to=30.09.2024")
    _shows(page, ["Принтер Canon", "Монитор Dell", "Монитор LG"])
    _found(page, 3)
    # п. 3: только «до» и только «от»
    _open_grid(page, list_id, f"?f.{bought}.to=14.03.2024")
    _shows(page, ["Принтер HP"])
    _found(page, 1)
    _open_grid(page, list_id, f"?f.{bought}.from=01.10.2024")
    _shows(page, ["Ноутбук Lenovo"])
    _found(page, 1)
    # п. 3: «содержит» — название без учёта регистра
    _open_grid(page, list_id, f"?f.title={quote('принтер')}")
    _shows(page, ["Принтер HP", "Принтер Canon"])
    _found(page, 2)
    # п. 3: фильтры сочетаются по «и» — работает и название содержит «монитор»
    _open_grid(page, list_id, f"?f.{state}={working}&f.title={quote('монитор')}")
    _shows(page, ["Монитор Dell"])
    _found(page, 1)


def test_l03_expiring_preset_shows_non_archived_records_with_deadline_within_largest_threshold_or_passed(admin_page):
    """Сценарий 3, п. 4: отбор «Истекает» — записи не в архиве со сроком в ближайшие N дней (N — наибольший порог
    поля-срока, без порогов — 30) или уже прошедшим (FR-520)."""
    page = admin_page
    # порог: наибольший из 3 и 10 — N = 10 (по Москве)
    list_id = create_list(page, unique_list_name("Сроки"))
    due = add_field(page, list_id, "Срок", "date", deadline=True, thresholds=[3, 10], show_in_table=True)
    _record(page, list_id, "Через девять дней", {due: _day(9)})
    _record(page, list_id, "Уже прошёл", {due: _day(-5)})
    _record(page, list_id, "Через двенадцать дней", {due: _day(12)})
    _record(page, list_id, "Без срока")
    archived = _record(page, list_id, "В архиве со сроком", {due: _day(2)})
    archive_record(page, list_id, archived)
    _open_grid(page, list_id)
    _found(page, 4)
    _press_preset(page, "expiring")
    _shows(page, ["Через девять дней", "Уже прошёл"])
    _found(page, 2)
    # без порогов N = 30
    default_id = create_list(page, unique_list_name("Сроки без порогов"))
    due = add_field(page, default_id, "Срок", "date", deadline=True, show_in_table=True)
    _record(page, default_id, "Через двадцать пять дней", {due: _day(25)})
    _record(page, default_id, "Через тридцать три дня", {due: _day(33)})
    _open_grid(page, default_id)
    _press_preset(page, "expiring")
    _shows(page, ["Через двадцать пять дней"])
    _found(page, 1)


def test_l03_assigned_to_me_preset_shows_non_archived_records_with_me_in_any_employee_field(admin_page, employee):
    """Сценарий 3, п. 5: отбор «Закреплено за мной» — записи не в архиве, где любое поле «сотрудник» содержит этого
    сотрудника (FR-520)."""
    page = admin_page
    me_word, other_word = unique_word("moi"), unique_word("chuzh")
    list_id = create_list(page, unique_list_name("Закреплено"))
    first = add_field(page, list_id, "Ответственный", "person", show_in_table=True)
    second = add_field(page, list_id, "Резервный", "person", show_in_table=True)
    me = make_list_reader(employee, admin_page, list_id, full_name=f"Закреплённый {me_word}")
    employee(full_name=f"Посторонний {other_word}")
    _record(page, list_id, "В первом поле", picks={first: me_word})
    _record(page, list_id, "Во втором поле", picks={second: me_word})
    _record(page, list_id, "У другого", picks={first: other_word})
    _record(page, list_id, "Без людей")
    archived = _record(page, list_id, "В архиве с мной", picks={first: me_word})
    archive_record(page, list_id, archived)
    mp = me.page
    _open_grid(mp, list_id)
    _found(mp, 4)
    _press_preset(mp, "mine")
    _shows(mp, ["В первом поле", "Во втором поле"])
    _found(mp, 2)


def test_l03_list_without_deadline_or_employee_field_has_no_expiring_or_assigned_to_me_preset(admin_page):
    """Сценарий 3, п. 4–5: в списке без поля-срока нет отбора «Истекает», в списке без поля «сотрудник» — отбора
    «Закреплено за мной»; «Все» и «Архив» есть всегда (FR-520)."""
    page = admin_page
    plain = create_list(page, unique_list_name("Без отборов"))
    add_field(page, plain, "Модель", "string")
    add_field(page, plain, "Куплено", "date")           # дата без признака «срок» — не поле-срок
    with_due = create_list(page, unique_list_name("Только срок"))
    add_field(page, with_due, "Срок", "date", deadline=True)
    with_person = create_list(page, unique_list_name("Только человек"))
    add_field(page, with_person, "Ответственный", "person")
    for list_id, expiring, mine in ((plain, 0, 0), (with_due, 1, 0), (with_person, 0, 1)):
        _open_grid(page, list_id)
        expect(_preset(page, "all")).to_have_count(1)
        expect(_preset(page, "archive")).to_have_count(1)
        expect(_preset(page, "expiring")).to_have_count(expiring)
        expect(_preset(page, "mine")).to_have_count(mine)
    # недоступный отбор по адресу — «Все» (раздел 10.3)
    _open_grid(page, plain, "?preset=expiring")
    expect(_preset(page, "all")).to_have_attribute("aria-current", "page")
    _open_grid(page, plain, "?preset=mine")
    expect(_preset(page, "all")).to_have_attribute("aria-current", "page")


def test_l03_archive_preset_shows_only_archived_records(admin_page):
    """Сценарий 3, п. 6: отбор «Архив» — только записи в архиве (FR-520)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Архив отбор"))
    add_field(page, list_id, "Модель", "string", show_in_table=True)
    numbers = {title: _record(page, list_id, title) for title in ("Живая 1", "Живая 2", "Старая 1", "Старая 2")}
    for title in ("Старая 1", "Старая 2"):
        archive_record(page, list_id, numbers[title])
    _open_grid(page, list_id)
    _shows(page, ["Живая 1", "Живая 2"])
    _press_preset(page, "archive")
    _shows(page, ["Старая 1", "Старая 2"])
    _found(page, 2)
    _open_grid(page, list_id, "?preset=archive")
    expect(_preset(page, "archive")).to_have_attribute("aria-current", "page")
    _shows(page, ["Старая 1", "Старая 2"])


def test_l03_header_click_sorts_by_column_second_click_reverses_and_equal_values_keep_stable_order(admin_page):
    """Сценарий 3, п. 7: нажатие на заголовок столбца сортирует записи, повторное меняет направление; записи с равным
    значением идут в устойчивом порядке — по номеру по возрастанию (К-15) (FR-518)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Сортировка"))
    model = add_field(page, list_id, "Модель", "string", show_in_table=True)
    qty = add_field(page, list_id, "Количество", "number", show_in_table=True)
    rows = [("B", "10"), ("A", "9"), ("B", "100"), ("A", "10"), ("C", "9")]
    n = [_record(page, list_id, f"Запись {i + 1}", {model: m, qty: q}) for i, (m, q) in enumerate(rows)]
    _open_grid(page, list_id)

    def header(code):
        return page.locator(f'th[data-sort="{code}"]')

    # п. 7: по строке — по возрастанию, затем по убыванию; равные значения — по номеру по возрастанию
    page.locator(f'th[data-sort="{model}"] a').click()
    expect(header(model)).to_have_attribute("data-dir", "asc")
    assert _numbers(page) == [n[1], n[3], n[0], n[2], n[4]]
    page.locator(f'th[data-sort="{model}"] a').click()
    expect(header(model)).to_have_attribute("data-dir", "desc")
    assert _numbers(page) == [n[4], n[0], n[2], n[1], n[3]]
    # п. 7: по числу — числовой порядок (9, 10, 100), а не по строке
    page.locator(f'th[data-sort="{qty}"] a').click()
    expect(header(qty)).to_have_attribute("data-dir", "asc")
    assert _numbers(page) == [n[1], n[4], n[0], n[3], n[2]]
    page.locator(f'th[data-sort="{qty}"] a').click()
    expect(header(qty)).to_have_attribute("data-dir", "desc")
    assert _numbers(page) == [n[2], n[0], n[3], n[1], n[4]]


def test_l03_hidden_field_absent_from_column_and_filter_choice(admin_page, employee):
    """Сценарий 3, п. 8: скрытое поле не показано ни столбцом, ни в выборе столбцов, ни в фильтрах (FR-509)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Скрытое"))
    model = add_field(page, list_id, "Модель", "string", show_in_table=True)
    store = add_field(page, list_id, "Склад", "string", show_in_table=True)
    _record(page, list_id, "Принтер", {model: "HP-1", store: "Склад-7"})
    reader = make_list_reader(employee, admin_page, list_id)
    rp = reader.page

    def probe(who, present: bool):
        _open_grid(who, list_id)
        cols = _cols(who)
        assert (store in cols) == present, f"столбцы: {cols}"
        assert model in cols
        count = 1 if present else 0
        expect(who.locator(f'[data-lists-column-choice="{store}"]')).to_have_count(count)
        expect(who.locator(f'[data-lists-filter="{store}"]')).to_have_count(count)
        expect(who.locator(f'th[data-sort="{store}"]')).to_have_count(count)
        expect(who.locator(f'[data-lists-column-choice="{model}"]')).to_have_count(1)
        expect(who.locator(f'[data-lists-filter="{model}"]')).to_have_count(1)

    probe(rp, True)
    # поле скрыто управляющим на вкладке «Поля»
    open_settings(page, list_id, "fields")
    page.locator(f'[data-lists-fields-grid] tr[data-field-code="{store}"] button[data-action="field-hide"]').click()
    expect(page.locator(f'[data-lists-fields-grid] tr[data-field-code="{store}"][data-hidden="true"]')).to_be_visible()
    probe(rp, False)
    probe(page, False)


def test_l03_archive_and_labels_actions_apply_to_checked_rows_only(admin_page, employee):
    """Сценарий 3, п. 9: «В архив» и «Этикетки» применяются только к отмеченным записям (FR-521, FR-523, FR-539)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Групповые"))
    add_field(page, list_id, "Модель", "string", show_in_table=True)
    numbers = {t: _record(page, list_id, t) for t in ("Первая", "Вторая", "Третья", "Четвёртая")}
    editor = make_list_editor(employee, admin_page, list_id)
    ep = editor.page
    _open_grid(ep, list_id)
    expect(ep.locator(ROWS)).to_have_count(4)
    # п. 9: отмечены две записи, «В архив» — только они ушли в архив
    for title in ("Первая", "Вторая"):
        ep.locator(f'input[type="checkbox"][name="n"][data-lists-row-check][value="{numbers[title]}"]').check()
    ep.locator('button[data-action="bulk-archive"]').click()
    expect(ep.locator('[data-lists-notice="bulk-result"]')).to_contain_text(re.compile(r"В архив:\s*2,\s*пропущено:\s*0"))
    _open_grid(ep, list_id)
    _shows(ep, ["Третья", "Четвёртая"])
    _open_grid(ep, list_id, "?preset=archive")
    _shows(ep, ["Первая", "Вторая"])
    # п. 9: «Этикетки» — одна отмеченная запись из двух, этикетка только её
    _open_grid(ep, list_id)
    expect(ep.locator(ROWS)).to_have_count(2)
    ep.locator(f'input[type="checkbox"][name="n"][data-lists-row-check][value="{numbers["Третья"]}"]').check()
    ep.locator('button[data-action="bulk-labels"]').click()
    ep.wait_for_url(re.compile(rf"/lists/{list_id}/labels/\?.*n={numbers['Третья']}"))
    expect(ep.locator('[data-lists-page="labels"]')).to_be_visible()
    expect(ep.locator("[data-lists-label]")).to_have_count(1)
    expect(ep.locator('[data-lists-label] [data-field="title"]')).to_have_text("Третья")


def test_l03_reader_without_edit_right_has_no_archive_action_for_checked_rows(admin_page, employee):
    """Сценарий 3, п. 9: у читающего без права правки «В архива» нет, «Этикетки» есть; прямой запрос — 403, записи на
    месте (FR-521, FR-523)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Только чтение"))
    add_field(page, list_id, "Модель", "string", show_in_table=True)
    numbers = [_record(page, list_id, f"Запись {i}") for i in (1, 2, 3)]
    reader = make_list_reader(employee, admin_page, list_id)
    rp = reader.page
    _open_grid(rp, list_id)
    rp.locator(f'input[type="checkbox"][name="n"][data-lists-row-check][value="{numbers[0]}"]').check()
    expect(rp.locator('button[data-action="bulk-archive"]')).to_have_count(0)
    expect(rp.locator('button[data-action="bulk-labels"]')).to_be_visible()
    assert post_status(rp, f"/lists/{list_id}/bulk-archive/", {"n": str(numbers[0])}) == 403
    _open_grid(rp, list_id)
    _found(rp, 3)
    expect(rp.locator(ROWS)).to_have_count(3)


def test_l03_table_shows_cards_without_horizontal_scroll_at_360px(admin_page, employee, browser, browser_context_args):
    """Сценарий 3, п. 10: на экране 360 px записи показаны карточками, горизонтальной прокрутки страницы нет
    (FR-521, NFR-507)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Узкий экран"))
    codes = [add_field(page, list_id, name, "string", show_in_table=True)
             for name in ("Модель", "Инвентарный номер", "Расположение", "Ответственный отдел")]
    for i in range(1, 4):
        _direct_add_record(page, list_id, f"Рабочая станция бухгалтерии {i}",
                           **{c: f"Значение поля {c} для записи {i} со словами" for c in codes})
    reader = make_list_reader(employee, admin_page, list_id)
    context, narrow = open_narrow(browser, browser_context_args, reader.page, f"/lists/{list_id}/", "grid")
    try:
        grid = narrow.locator("#lists-grid")
        expect(grid).to_have_attribute("data-narrow", "cards")
        expect(narrow.locator(ROWS)).to_have_count(3)
        expect(narrow.locator(ROWS).first.locator('a[data-field="title"]')).to_be_visible()
        # строки — карточки, а не строки таблицы
        assert narrow.locator(ROWS).first.evaluate("el => getComputedStyle(el).display") != "table-row"
        assert page_fits(narrow), "у страницы таблицы есть горизонтальная прокрутка при 360 px"
    finally:
        context.close()


def test_l03_empty_list_shows_explanation_and_add_and_import_buttons_to_editor_only(admin_page, employee):
    """Сценарий 3, п. 11: в списке без записей — пояснение; правящему «Добавить запись» и «Загрузить из таблицы» на
    виду, читающему их нет (FR-518; UX-13)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Пустой"))
    add_field(page, list_id, "Модель", "string", show_in_table=True)
    editor = make_list_editor(employee, admin_page, list_id)
    reader = make_list_reader(employee, admin_page, list_id)
    ep, rp = editor.page, reader.page
    _open_grid(ep, list_id)
    expect(ep.locator('[data-empty-state="lists-grid"]')).to_contain_text("В списке пока нет записей")
    expect(ep.locator(ROWS)).to_have_count(0)
    add = ep.locator('a[data-action="record-add"]')
    expect(add).to_be_visible()
    expect(add).to_contain_text("Добавить запись")
    expect(ep.locator('a[data-action="import"]')).to_be_visible()
    expect(ep.locator('a[data-action="import"]')).to_contain_text("Загрузить из таблицы")
    add.click()
    ep.wait_for_url(re.compile(rf"/lists/{list_id}/add/$"))
    _open_grid(rp, list_id)
    expect(rp.locator('[data-empty-state="lists-grid"]')).to_contain_text("В списке пока нет записей")
    expect(rp.locator('a[data-action="record-add"]')).to_have_count(0)
    expect(rp.locator('a[data-action="import"]')).to_have_count(0)


def test_l03_employee_without_list_right_gets_same_answer_as_missing_list_for_table_and_filter_values(
        admin_page, employee):
    """Сценарий 3, п. 12: сотрудник без права на список получает на адрес таблицы и на подбор значений фильтра тот же
    ответ, что на несуществующий список — 404 без данных списка (FR-514)."""
    page = admin_page
    closed_name = unique_list_name("Закрытый")
    closed = create_list(page, closed_name)
    state = add_field(page, closed, "Состояние", "choice")
    set_choices(page, closed, state, ["Работает", "Сломан"])
    record_title = f"Запись {unique_word()}"
    _record(page, closed, record_title, {state: "Сломан"})
    own = create_list(page, unique_list_name("Свой"))
    stranger = make_list_reader(employee, admin_page, own)
    sp = stranger.page
    missing = 999999999
    table, values = f"/lists/{closed}/", f"/lists/{closed}/filter-values/{state}/?q="
    # контроль: управляющему подбор отвечает значениями, свой список читающему открыт
    answer = helpers_org.direct_get(page, values)
    assert answer.status == 200 and "Сломан" in answer.text()
    assert status_of(sp, f"/lists/{own}/") == 200
    # п. 12: адрес таблицы и подбор значений — как у несуществующего списка
    for path, absent in ((table, f"/lists/{missing}/"), (values, f"/lists/{missing}/filter-values/{state}/?q=")):
        got, gone = helpers_org.direct_get(sp, path), helpers_org.direct_get(sp, absent)
        assert got.status == gone.status == 404, f"{path}: {got.status}, у несуществующего {gone.status}"
        body = got.text()
        for leak in (closed_name, record_title, "Сломан", "Работает", 'data-lists-page="grid"'):
            assert leak not in body, f"ответ на {path} выдаёт «{leak}»"
    # то же глазами: страница таблицы закрытого списка не открывается
    sp.goto(table)
    expect(sp.locator('[data-lists-page="grid"]')).to_have_count(0)
    expect(sp.locator("body")).not_to_contain_text(closed_name)
