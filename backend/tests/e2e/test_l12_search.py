"""T-6151: сценарий 12 — поиск: сквозной (группа «Списки») и внутри списка (FR-509, FR-514, FR-540, FR-541, FR-546,
NFR-507).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md §9, §10.2–10.3, §11.3, §12, §15.4, CONTRACT-005.md):
- каждый тест заводит свои списки (`unique_list_name`) и слова поиска только из латинских букв (`unique_word`; цифры
  внутри слова поиск разобрал бы иначе); шесть стартовых списков и общие настройки не трогаются, команд стенда и
  `stand_shell` в файле нет; ищет читающий список сотрудник (`make_list_reader`), настраивает администратор;
- страница результатов — `/search/?q=…` (`[data-search-page]`, группа `section[data-search-group="lists"]`, строки
  `li[data-search-row]` с `a[href]`, `[data-field="title"]`, `[data-field="subtitle"]`; разметка среза 005), строка
  выдачи читается «<название> — <список>» (§9): запись ищется по адресу карточки `/lists/<id>/<n>/`, не по числу строк;
- таблица внутри списка — `/lists/<id>/` (`#lists-grid`, `tr[data-record-number]`, `[data-lists-found]`), поиск —
  `form[data-lists-search] input[name="q"]`, подсказка — `[data-lists-search-hint]`; отбор по состоянию — параметр
  `f.<код>=<id значения>` (§10.3: вид виджета фильтра контрактом не задан);
- первый положительный поиск после создания записи — с повтором до 20 с (пересчёт вектора может идти после фиксации);
  отсутствие записи проверяется только после положительной проверки той же записи по соседнему запросу;
- скрытие текстового поля пересчитывает векторы фоном (И2): перед проверкой «не находится» ждём исчезновения
  `[data-lists-notice="vectors-stale"]` (до 60 с);
- пункты 7 (таблицы базы) и 9 («модуль выключен») приёмка не проходит (решение 19): журнал событий — здесь, остальное
  — серверный T-6122.
"""
import re
import secrets
import time
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org
from tests.e2e.helpers_lists import (
    add_field, archive_record, create_list, create_record, field_code_by_name, make_list_reader, open_settings,
    set_choices, unique_list_name, unique_word)

HINT_SHORT = "Введите не меньше 2 знаков"      # 12.1, query_short
NOTHING_FOUND = "Ничего не найдено"             # прежняя страница поиска, CONTRACT-005 §12.1
FIND_TIMEOUT = 20.0


# --- Свои помощники файла -----------------------------------------------------------------------------------

def _results(page, q: str) -> None:
    """Страница результатов `/search/?q=…`; ждёт её корень (он есть на любой запрос)."""
    page.goto("/search/?" + urlencode({"q": q}))
    expect(page.locator("[data-search-page]")).to_be_visible()


def _lists_section(page):
    return page.locator('[data-search-page] section[data-search-group="lists"]')


def _lists_hrefs(page, q: str) -> list:
    """Адреса строк группы «Списки» на странице результатов по `q` (пусто, если группы нет)."""
    _results(page, q)
    return _lists_section(page).locator("li[data-search-row]").evaluate_all(
        "els => els.map(li => li.querySelector('a[href]').getAttribute('href'))")


def _wait_found(page, q: str, href: str, timeout: float = FIND_TIMEOUT) -> list:
    """Повторяет поиск, пока в группе «Списки» не появится строка с адресом `href` (вектор записи мог ещё
    считаться); возвращает адреса группы. По истечении срока — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        hrefs = _lists_hrefs(page, q)
        if href in hrefs:
            return hrefs
        if time.monotonic() > deadline:
            raise AssertionError(f"запрос «{q}»: записи {href} нет в группе «Списки» за {timeout:.0f} с: {hrefs}")
        page.wait_for_timeout(1000)


def _groups(root) -> list:
    """Ключи групп выдачи внутри `root` по порядку разметки."""
    return root.locator("section[data-search-group]").evaluate_all("els => els.map(e => e.dataset.searchGroup)")


def _card(list_id, number) -> str:
    return f"/lists/{list_id}/{number}/"


def _make_list(admin_page, prefix: str = "Оборудование") -> tuple:
    """Новый список с уникальным названием: `(номер, название)`."""
    name = unique_list_name(prefix)
    return create_list(admin_page, name), name


def _serial() -> str:
    """Серийный номер вида «ИН-NNNNNN»: шесть цифр после дефиса (лексема вектора «-NNNNNN», план, «Поиск»)."""
    return "ИН-" + "".join(secrets.choice("0123456789") for _ in range(6))


def _grid(page, list_id, params: dict | None = None) -> None:
    """Таблица записей списка `/lists/<id>/?…` и ожидание её корня и числа найденного."""
    query = ("?" + urlencode(params)) if params else ""
    page.goto(f"/lists/{list_id}/{query}")
    expect(page.locator('[data-lists-page="grid"]')).to_be_visible()
    expect(page.locator("[data-lists-found]")).to_be_visible()


def _rows(page):
    return page.locator("#lists-grid tr[data-record-number]")


def _numbers(page) -> list:
    """Номера записей строк таблицы по возрастанию."""
    return sorted(int(n) for n in _rows(page).evaluate_all("els => els.map(e => e.dataset.recordNumber)"))


def _search_in_list(page, q: str) -> None:
    """Вводит `q` в строку поиска списка (`form[data-lists-search]`) и отправляет Enter; результат ждёт вызывающий
    (`expect` по числу строк)."""
    field = page.locator('form[data-lists-search] input[name="q"]')
    expect(field).to_be_visible()
    field.fill(q)
    field.press("Enter")


def _found(page):
    return page.locator("[data-lists-found]")


def _hint(page):
    return page.locator("[data-lists-search-hint]")


def _wait_vectors_fresh(page, list_id, timeout: float = 60.0) -> None:
    """Ждёт конца фонового пересчёта поиска списка (И2): на странице списка нет `[data-lists-notice="vectors-stale"]`."""
    deadline = time.monotonic() + timeout
    while True:
        _grid(page, list_id)
        if page.locator('[data-lists-notice="vectors-stale"]').count() == 0:
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"пересчёт поиска списка {list_id} не закончился за {timeout:.0f} с")
        page.wait_for_timeout(2000)


def _toggle_field(page, list_id, code: str, action: str, hidden: bool) -> None:
    """«Скрыть» (`field-hide`) или «Показать» (`field-show`) поле на вкладке «Поля»; ждёт его новую пометку."""
    open_settings(page, list_id, "fields")
    row = page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')
    row.locator(f'button[data-action="{action}"]').click()
    expect(row.locator(f'[data-hidden="{"true" if hidden else "false"}"]')).to_be_visible()


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l12_dell_in_top_search_shows_lists_group_row_title_dash_list_opening_card(admin_page, employee):
    """Сценарий 12, п. 1: запись «Ноутбук <слово>» в списке «Оборудование …», который читает сотрудник; слово в
    верхней строке поиска — в выдаче группа «Списки» (после прочих групп), строка «Ноутбук <слово> — Оборудование …»,
    нажатие открывает карточку записи (FR-540)."""
    list_id, name = _make_list(admin_page)
    word = unique_word("dell")
    title = f"Ноутбук {word}"
    number = create_record(admin_page, list_id, title)
    page = make_list_reader(employee, admin_page, list_id).page
    href = _card(list_id, number)
    # п. 1: страница результатов — группа «Списки», строка «название — список»
    _wait_found(page, word, href)
    section = _lists_section(page)
    expect(section).to_have_count(1)
    expect(section).to_contain_text("Списки")
    row = section.locator("li[data-search-row]").filter(has=page.locator(f'a[href="{href}"]'))
    expect(row).to_have_count(1)
    expect(row.locator('[data-field="title"]')).to_have_text(title)
    expect(row.locator('[data-field="subtitle"]')).to_have_text(name)
    groups = _groups(page.locator("[data-search-page]"))
    assert groups[-1] == "lists", f"группа «Списки» не последняя: {groups}"
    # п. 1: тот же запрос в строке поиска шапки — всплывающая выдача; нажатие на строку открывает карточку
    page.goto("/")
    bar = page.locator('[data-search-bar] input[name="q"]')
    expect(bar).to_be_visible()
    bar.fill("")
    bar.press_sequentially(word, delay=30)
    popup_row = page.locator(
        f'[data-search-popup] section[data-search-group="lists"] li[data-search-row]:has(a[href="{href}"])')
    expect(popup_row).to_be_visible()
    expect(popup_row.locator('[data-field="title"]')).to_have_text(title)
    expect(popup_row.locator('[data-field="subtitle"]')).to_have_text(name)
    popup_row.locator("a[href]").first.click()
    page.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/$"))
    expect(page.locator("[data-lists-record]")).to_contain_text(title)


def test_l12_whole_serial_number_in_other_case_with_spaces_finds_record_by_exact_match(admin_page, employee):
    """Сценарий 12, п. 2 (первая часть): серийный номер «ИН-NNNNNN» в уникальном поле; запрос «  ин-nnnnnn  » (другой
    регистр, пробелы по краям) целиком находит запись: слова запроса «ин» и «NNNNNN» вектору не подходят (лексемы
    «ин» и «-NNNNNN»), так что находит именно сравнение запроса целиком с уникальным полем (FR-540)."""
    list_id, _ = _make_list(admin_page)
    add_field(admin_page, list_id, "Серийный номер", "string", unique=True)
    code = field_code_by_name(admin_page, list_id, "Серийный номер")
    serial = _serial()
    number = create_record(admin_page, list_id, f"Сервер {unique_word('srv')}", {code: serial})
    page = make_list_reader(employee, admin_page, list_id).page
    href = _card(list_id, number)
    # п. 2: другой регистр и пробелы по краям
    hrefs = _wait_found(page, f"  {serial.lower()}  ", href)
    assert hrefs.count(href) == 1, f"запись выдана не один раз: {hrefs}"
    # тот же номер в исходном регистре
    assert href in _lists_hrefs(page, serial)
    # номер, которого нет ни у одной записи, ничего не находит (запрос не «находит всё»)
    assert href not in _lists_hrefs(page, _serial().lower())


def test_l12_part_of_serial_number_after_hyphen_does_not_find_record(admin_page, employee):
    """Сценарий 12, п. 2 (вторая часть): по части номера после дефиса («NNNNNN» из «ИН-NNNNNN») запись не находится,
    потому что часть не совпадает со словом названия или текстового поля; целиком номер находит (контроль) (FR-540)."""
    list_id, _ = _make_list(admin_page)
    add_field(admin_page, list_id, "Серийный номер", "string", unique=True)
    code = field_code_by_name(admin_page, list_id, "Серийный номер")
    serial = _serial()
    number = create_record(admin_page, list_id, f"Сервер {unique_word('srv')}", {code: serial})
    page = make_list_reader(employee, admin_page, list_id).page
    href = _card(list_id, number)
    _wait_found(page, serial, href)               # контроль: запись есть в выдаче по номеру целиком
    part = serial.split("-", 1)[1]
    assert href not in _lists_hrefs(page, part), "запись найдена по части номера после дефиса"
    assert href not in _lists_hrefs(page, part[:4]), "запись найдена по середине номера"


def test_l12_other_word_form_and_word_start_in_string_or_multiline_text_find_record(admin_page, employee):
    """Сценарий 12, п. 3: слово в другой словоформе и по началу слова находит запись, если слово стоит в поле «строка»
    или во второй строке многострочного текста; запрос с несовпавшим словом записи не находит (контроль) (FR-540)."""
    list_id, _ = _make_list(admin_page)
    add_field(admin_page, list_id, "Модель", "string")
    add_field(admin_page, list_id, "Заметка", "text")
    model = field_code_by_name(admin_page, list_id, "Модель")
    note = field_code_by_name(admin_page, list_id, "Заметка")
    marker = unique_word("mk")
    number = create_record(admin_page, list_id, f"Стенд {marker}",
                           {model: "холодильник", note: "Первая строка\nсканеры переговорная"})
    page = make_list_reader(employee, admin_page, list_id).page
    href = _card(list_id, number)
    # п. 3: словоформа слова из поля «строка»
    _wait_found(page, f"{marker} холодильники", href)
    # п. 3: начало слова из поля «строка»
    assert href in _lists_hrefs(page, f"{marker} холод")
    # п. 3: словоформа слова из многострочного текста
    assert href in _lists_hrefs(page, f"{marker} сканеров")
    # п. 3: начало слова из второй строки многострочного текста
    assert href in _lists_hrefs(page, f"{marker} переговор")
    # контроль: слово, которого в записи нет, вместе с найденным маркером записи не находит
    assert href not in _lists_hrefs(page, f"{marker} нептун")


def test_l12_archived_record_and_record_of_unread_list_are_absent_without_hint(admin_page, employee):
    """Сценарий 12, п. 4: запись в архиве читаемого списка и запись списка, который сотрудник не читает, в выдаче
    отсутствуют, и страница ничем не намекает, что они есть; тот, кто читает второй список, свою запись находит
    (контроль) (FR-514, FR-540)."""
    list_a, _ = _make_list(admin_page, "Склад")
    list_b, name_b = _make_list(admin_page, "Закрытый")
    word = unique_word("ar")
    live = create_record(admin_page, list_a, f"Монитор {word}")
    archived = create_record(admin_page, list_a, f"Принтер {word}")
    archive_record(admin_page, list_a, archived)
    hidden_title = f"Сервер {word}"
    closed = create_record(admin_page, list_b, hidden_title)
    reader = make_list_reader(employee, admin_page, list_a)
    other = make_list_reader(employee, admin_page, list_b)
    page = reader.page
    # контроль: у читающего первый список находится живая запись
    hrefs = _wait_found(page, word, _card(list_a, live))
    # п. 4: нет записи в архиве и записи нечитаемого списка
    assert _card(list_a, archived) not in hrefs, "запись в архиве попала в выдачу"
    assert _card(list_b, closed) not in hrefs, "запись нечитаемого списка попала в выдачу"
    text = page.locator("[data-search-page]").inner_text()
    assert hidden_title not in text and name_b not in text, "в выдаче есть намёк на запись"
    expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
    # п. 4: запрос, которому отвечает только нечитаемая запись, — пустая выдача без группы «Списки» и без подсказки
    only = unique_word("cl")
    closed_two = create_record(admin_page, list_b, f"Секрет {only}")
    _wait_found(other.page, only, _card(list_b, closed_two))    # контроль: читающему второй список запись видна
    _results(page, only)
    expect(page.locator('[data-search-page] [data-empty-state="search"]')).to_contain_text(NOTHING_FOUND)
    expect(_lists_section(page)).to_have_count(0)
    expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
    text = page.locator("[data-search-page]").inner_text()
    assert name_b not in text and "Секрет" not in text


def test_l12_word_only_in_hidden_field_does_not_find_record(admin_page, employee):
    """Сценарий 12, п. 5: слово лежит только в поле «строка» (и номер — в уникальном поле); пока поля показаны,
    запись по ним находится; после «Скрыть» (и конца фонового пересчёта) по слову и по номеру запись не находится,
    а по названию находится; после «Показать» снова находится (FR-509, FR-540)."""
    list_id, _ = _make_list(admin_page)
    add_field(admin_page, list_id, "Заметка", "string")
    add_field(admin_page, list_id, "Серийный номер", "string", unique=True)
    note = field_code_by_name(admin_page, list_id, "Заметка")
    serial_code = field_code_by_name(admin_page, list_id, "Серийный номер")
    title_word = unique_word("ti")
    marker = unique_word("hd")
    serial = _serial()
    number = create_record(admin_page, list_id, f"Прибор {title_word}", {note: f"Склад {marker}", serial_code: serial})
    page = make_list_reader(employee, admin_page, list_id).page
    href = _card(list_id, number)
    # контроль: поля показаны — запись находится и по слову, и по номеру
    _wait_found(page, marker, href)
    assert href in _lists_hrefs(page, serial)
    # п. 5: скрываем оба поля
    _toggle_field(admin_page, list_id, note, "field-hide", True)
    _toggle_field(admin_page, list_id, serial_code, "field-hide", True)
    _wait_vectors_fresh(admin_page, list_id)
    assert href in _lists_hrefs(page, title_word), "контроль: запись пропала из поиска целиком"
    assert href not in _lists_hrefs(page, marker), "запись найдена по слову из скрытого поля"
    assert href not in _lists_hrefs(page, serial), "запись найдена по номеру из скрытого уникального поля"
    # «Показать» возвращает поиск по полям
    _toggle_field(admin_page, list_id, note, "field-show", False)
    _toggle_field(admin_page, list_id, serial_code, "field-show", False)
    _wait_vectors_fresh(admin_page, list_id)
    _wait_found(page, marker, href)
    assert href in _lists_hrefs(page, serial)


def test_l12_search_inside_list_with_state_filter_shows_records_matching_both(admin_page, employee):
    """Сценарий 12, п. 6: внутри списка отбор «Состояние = В ремонте» и слово в строке поиска списка показывают
    только записи, подходящие обоим условиям; поиск без отбора находит обе записи со словом (FR-541)."""
    list_id, _ = _make_list(admin_page)
    add_field(admin_page, list_id, "Состояние", "choice")
    state = field_code_by_name(admin_page, list_id, "Состояние")
    ids = set_choices(admin_page, list_id, state, ["В ремонте", "На складе"])
    word = unique_word("rp")
    other_word = unique_word("ot")
    repair_word = create_record(admin_page, list_id, f"Принтер {word}", {state: "В ремонте"})
    stock_word = create_record(admin_page, list_id, f"Монитор {word}", {state: "На складе"})
    repair_other = create_record(admin_page, list_id, f"Сервер {other_word}", {state: "В ремонте"})
    stock_other = create_record(admin_page, list_id, f"Ноутбук {other_word}", {state: "На складе"})
    page = make_list_reader(employee, admin_page, list_id).page
    repair_id = ids[0]
    # контроль: отбор без слова — две записи «В ремонте»
    _grid(page, list_id, {f"f.{state}": repair_id})
    assert _numbers(page) == sorted([repair_word, repair_other])
    # п. 6: отбор и слово в адресе — одна запись, подходящая обоим условиям
    _grid(page, list_id, {f"f.{state}": repair_id, "q": word})
    assert _numbers(page) == [repair_word]
    expect(_found(page)).to_contain_text(re.compile(r"Найдено:\s*1\b"))
    # п. 6: строка поиска списка без отбора находит обе записи со словом
    _grid(page, list_id)
    assert _numbers(page) == sorted([repair_word, stock_word, repair_other, stock_other])
    _search_in_list(page, word)
    expect(_rows(page)).to_have_count(2)
    assert _numbers(page) == sorted([repair_word, stock_word])
    expect(_found(page)).to_contain_text(re.compile(r"Найдено:\s*2\b"))
    # п. 6: слово, введённое в строку поиска при действующем отборе, сужает таблицу до записи, подходящей обоим
    _grid(page, list_id, {f"f.{state}": repair_id})
    expect(_rows(page)).to_have_count(2)
    _search_in_list(page, word)
    expect(_rows(page)).to_have_count(1)
    assert _numbers(page) == [repair_word]


def test_l12_results_page_does_not_widen_page_at_360px(admin_page, employee, browser, browser_context_args):
    """Сценарий 12, п. 8: на 360 px страница результатов с группой «Списки» (длинное слово в названии записи и в
    названии списка), с подсказкой и с пустой выдачей не получает горизонтальной прокрутки (NFR-507)."""
    list_name = unique_word("lst") + "q" * 80
    list_id = create_list(admin_page, list_name)
    marker = unique_word("nw")
    title = f"Ноутбук {marker} {marker}{'q' * 80}"
    number = create_record(admin_page, list_id, title)
    reader = make_list_reader(employee, admin_page, list_id)
    href = _card(list_id, number)
    _wait_found(reader.page, marker, href)        # контроль: запись находится и на обычной ширине
    context = helpers_kb.narrow_context(browser, browser_context_args, reader.page)
    try:
        page = context.new_page()
        for query in (marker, "5", unique_word("zz")):
            _results(page, query)
            if query == marker:
                expect(_lists_section(page).locator(f'li[data-search-row] a[href="{href}"]')).to_have_count(1)
            assert helpers_kb.page_fits(page), f"запрос {query[:14]}: страница шире 360 px"
    finally:
        context.close()


def test_l12_one_char_query_inside_list_gives_min_two_chars_hint(admin_page, employee):
    """Сценарий 12, п. 10 (первая часть): запрос из одного знака в строке поиска списка даёт «Введите не меньше 2
    знаков», условие поиска не применяется (остаются все записи); на правильном запросе подсказки нет (FR-541,
    FR-546)."""
    list_id, _ = _make_list(admin_page)
    word = unique_word("sh")
    first = create_record(admin_page, list_id, f"Принтер {word}")
    second = create_record(admin_page, list_id, f"Монитор {unique_word('sh')}")
    page = make_list_reader(employee, admin_page, list_id).page
    # контроль: слово из двух и более знаков подсказки не даёт и сужает таблицу
    _grid(page, list_id, {"q": word})
    expect(_hint(page)).to_have_count(0)
    assert _numbers(page) == [first]
    # п. 10: один знак через строку поиска списка
    _grid(page, list_id)
    assert _numbers(page) == sorted([first, second])
    _search_in_list(page, "5")
    expect(_hint(page)).to_contain_text(HINT_SHORT)
    assert _numbers(page) == sorted([first, second]), "запрос из одного знака отобрал записи"
    expect(_found(page)).to_contain_text(re.compile(r"Найдено:\s*2\b"))
    # то же по адресу (сервер проверяет порог сам)
    _grid(page, list_id, {"q": "д"})
    expect(_hint(page)).to_contain_text(HINT_SHORT)
    assert _numbers(page) == sorted([first, second])


def test_l12_nine_word_query_inside_list_uses_first_eight_words(admin_page, employee):
    """Сценарий 12, п. 10 (вторая часть): из девяти слов в строке поиска списка учитываются первые восемь: запись с
    восемью словами находится запросом из этих восьми слов и девятым лишним, но не находится, если восьмое слово
    запроса чужое (FR-541)."""
    list_id, _ = _make_list(admin_page)
    words = [unique_word("") for _ in range(8)]
    target = create_record(admin_page, list_id, " ".join(words))
    decoy = create_record(admin_page, list_id, f"Прочее {unique_word('dc')}")
    page = make_list_reader(employee, admin_page, list_id).page
    ninth = unique_word("")
    # п. 10: девять слов через строку поиска списка — девятое отброшено, запись находится
    _grid(page, list_id)
    assert _numbers(page) == sorted([target, decoy])
    _search_in_list(page, " ".join(words + [ninth]))
    expect(_rows(page)).to_have_count(1)
    assert _numbers(page) == [target]
    # контроль: ровно восемь слов находят запись
    _grid(page, list_id, {"q": " ".join(words)})
    assert _numbers(page) == [target]
    # восьмое слово запроса учитывается: чужое восьмое слово записи не находит
    foreign = unique_word("")
    _grid(page, list_id, {"q": " ".join(words[:7] + [foreign, ninth])})
    assert _numbers(page) == [], "восьмое слово запроса не учтено"
    expect(_found(page)).to_contain_text(re.compile(r"Найдено:\s*0\b"))


def test_l12_search_query_text_is_absent_from_portal_event_journal(admin_page, employee):
    """Сценарий 12, п. 7 (журнал событий в интерфейсе): после сквозного поиска (страница, окно, счётчик группы, «ещё») и
    поиска внутри списка текста запроса нет в журнале событий `/audit/`, событий поиска там нет (FR-540)."""
    list_id, _ = _make_list(admin_page)
    marker = unique_word("mk")
    number = create_record(admin_page, list_id, f"Прибор {marker}")
    page = make_list_reader(employee, admin_page, list_id).page
    href = _card(list_id, number)
    _wait_found(page, marker, href)               # контроль: запрос что-то находит
    page.goto("/")
    bar = page.locator('[data-search-bar] input[name="q"]')
    bar.fill("")
    bar.press_sequentially(marker, delay=30)
    expect(page.locator(f'[data-search-popup] section[data-search-group="lists"] a[href="{href}"]')).to_be_visible()
    for path in ("/search/count/?" + urlencode({"q": marker, "group": "lists"}),
                 "/search/more/?" + urlencode({"q": marker, "group": "lists", "offset": 20}),
                 "/search/popup/?" + urlencode({"q": marker})):
        assert helpers_org.direct_get(page, path).status == 200
    _grid(page, list_id)
    _search_in_list(page, marker)
    expect(_rows(page)).to_have_count(1)
    text = helpers.audit_text(admin_page)
    expect(admin_page.locator("tr[data-event-id]").first).to_be_visible()
    assert marker not in text, "текст запроса попал в журнал событий"
    assert not any("search" in (action or "") for action in helpers.audit_actions(admin_page)), \
        "в журнале есть событие поиска"
