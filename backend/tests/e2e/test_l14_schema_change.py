"""T-6153: сценарий 14 — изменение схемы: скрыть поле с данными, обязательность и уникальность, удаление пустого
(FR-503, FR-508, FR-509, FR-510, FR-511, FR-515, FR-516, FR-522, FR-526, FR-542, FR-546, NFR-507).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md):
- управляющий — администратор круга `admin_page`; правящий (п. 7) — `helpers_lists.make_list_editor`;
- каждый тест заводит свои списки с уникальными названиями и шесть стартовых не трогает (решение 56); общих настроек
  тесты файла не меняют, сброса стенда и команд стенда в файле нет;
- «Скрыть», «Показать», «Вверх» — обычные POST с переходом на вкладку «Поля» (10.2): после нажатия ждём переход;
- решение владельца 2026-10-25 (сценарий 14, п. 2): после «Скрыть» значения поля в карточке не показываются, в истории
  изменения поля видны, после «Показать» значение снова в карточке (6.1 V4, 6.2 A7);
- «поиск» п. 2 — поиск внутри списка (`/lists/<id>/?q=`); пересчёт поиска после «Скрыть»/«Показать» идёт фоном (И2), пока
  он не закончен, страница показывает `[data-lists-notice="vectors-stale"]`, поэтому перед проверкой поиска ждём,
  когда сообщение исчезнет (до 60 с);
- тексты отказов — литералы раздела 12 контракта.
"""
import io
import re
import time
import zipfile

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_lists, helpers_org
from tests.e2e.helpers_lists import (
    add_field, archive_record, choice_titles, choose, confirm_dialog, create_list, create_record, delete_reason,
    field_codes, fill_field_form, fill_record, open_add_record, open_edit_record, open_field,
    open_new_field, open_record, open_settings, refusal_codes, status_of, submit_field_form, submit_record,
    try_add_field, try_create_record, unique_list_name, unique_word)

_SAVE = 'button[type=submit]:not([data-action])'  # главная кнопка формы (15.4, п. 1)


# --- Помощники файла -------------------------------------------------------------------------------------------

def _row(page, code):
    """Строка сетки полей `tr[data-field-code="<код>"]` (вкладка «Поля»)."""
    return page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')


def _marked(page, code, attr: str, value: str):
    """Пометка `[<attr>="<value>"]` строки поля — на ячейке названия `[data-field="name"]` (CONTRACT-006, 15.5 п. 7)."""
    return page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"] [data-field="name"][{attr}="{value}"]')


def _field_action(page, list_id, code, action: str) -> None:
    """Нажимает `button[data-action="<action>"]` строки поля на вкладке «Поля» (обычный POST) и ждёт переход."""
    open_settings(page, list_id, "fields")
    with page.expect_navigation():
        _row(page, code).locator(f'button[data-action="{action}"]').click()
    expect(page.locator('[data-lists-page="fields"]')).to_be_visible()


def _hide(page, list_id, code) -> None:
    _field_action(page, list_id, code, "field-hide")
    expect(_marked(page, code, "data-hidden", "true").first).to_be_attached()
    expect(_row(page, code).locator('button[data-action="field-show"]')).to_have_count(1)


def _show(page, list_id, code) -> None:
    _field_action(page, list_id, code, "field-show")
    expect(_marked(page, code, "data-hidden", "false").first).to_be_attached()
    expect(_row(page, code).locator('button[data-action="field-hide"]')).to_have_count(1)


def _has_code(body: str, code: str) -> bool:
    """В теле ответа есть отказ с `data-code="<код>"` (прямой POST отдаёт страницу целиком)."""
    return re.search(rf'data-code=["\']?{re.escape(code)}["\'\s>]', body) is not None


def _direct_body(page, path: str, data: dict) -> tuple:
    """Прямой POST (обход браузера, как в сценариях 1 и 6 прежних срезов): `(код ответа, текст тела)`."""
    response = helpers_org.direct_post(page, path, data)
    return response.status, response.text()


def _grid(page, list_id) -> None:
    page.goto(f"/lists/{list_id}/")
    expect(page.locator('[data-lists-page="grid"]')).to_be_visible()


def _wait_search_fresh(page, list_id) -> None:
    """Ждёт конца пересчёта поиска (И2): сообщение `vectors-stale` исчезло со страницы списка; до 60 с."""
    deadline = time.monotonic() + 60
    while True:
        _grid(page, list_id)
        if page.locator('[data-lists-notice="vectors-stale"]').count() == 0:
            return
        if time.monotonic() > deadline:
            raise AssertionError("пересчёт поиска списка не закончился за 60 с")
        page.wait_for_timeout(2000)


def _search(page, list_id, query: str) -> list:
    """Поиск внутри списка: страница `/lists/<id>/?q=<запрос>`; номера записей таблицы по порядку. Строка поиска
    `form[data-lists-search] input[name=q]` показывает запрос."""
    page.goto(f"/lists/{list_id}/?q={query}")
    expect(page.locator('[data-lists-page="grid"]')).to_be_visible()
    expect(page.locator('form[data-lists-search] input[name="q"]')).to_have_value(query)
    expect(page.locator("[data-lists-found]")).to_be_visible()
    return [int(tr.get_attribute("data-record-number")) for tr in page.locator("tr[data-record-number]").all()]


def _xlsx_text(body: bytes) -> str:
    """Весь текст XML-частей книги XLSX (строки и ячейки; вид хранения строк не важен)."""
    with zipfile.ZipFile(io.BytesIO(body)) as book:
        return "\n".join(book.read(n).decode("utf-8", "replace") for n in book.namelist() if n.endswith(".xml"))


def _export_text(page, list_id) -> str:
    """Выгрузка в Excel по ссылке `a[data-action="export"]` таблицы (читающий): 200 и XLSX; возвращает его текст."""
    _grid(page, list_id)
    href = page.locator('a[data-action="export"]').get_attribute("href")
    response = page.request.get(href)
    assert response.status == 200, f"выгрузка: код {response.status}"
    body = response.body()
    assert body[:2] == b"PK", "выгрузка — не книга XLSX"
    return _xlsx_text(body)


def _label_value(page, list_id, number) -> str:
    """Значение этикетки записи `[data-lists-label] [data-field="value"]`."""
    page.goto(f"/lists/{list_id}/{number}/label/")
    expect(page.locator('[data-lists-page="label"]')).to_be_visible()
    value = page.locator('[data-lists-label] [data-field="value"]')
    expect(value).to_have_count(1)
    return value.inner_text().strip()


def _places(page, list_id, code, number, name: str, word: str) -> dict:
    """Где сейчас видно поле `code` (название `name`, значение `word` у записи `number`): форма новой записи, форма
    правки, ячейка таблицы, выбор столбцов, фильтры, выгрузка, этикетка, поиск внутри списка."""
    found = {}
    open_add_record(page, list_id)
    found["форма"] = page.locator(f'[data-lists-field="{code}"]').count() > 0
    open_edit_record(page, list_id, number)
    found["правка"] = page.locator(f'[data-lists-field="{code}"]').count() > 0
    _grid(page, list_id)
    expect(page.locator(f'tr[data-record-number="{number}"]')).to_be_visible()
    found["таблица"] = page.locator(f'td[data-col="{code}"]').count() > 0
    found["столбцы"] = page.locator(f'[data-lists-column-choice="{code}"]').count() > 0
    found["фильтры"] = page.locator(f'[data-lists-filter="{code}"]').count() > 0
    text = _export_text(page, list_id)
    found["выгрузка"] = name in text or word in text
    found["этикетка"] = _label_value(page, list_id, number) == word
    found["поиск"] = number in _search(page, list_id, word)
    return found


def _record_text_without_history(page) -> str:
    """Текст карточки записи без места истории `[data-lists-history]` (история показывает и скрытые поля)."""
    return page.locator("[data-lists-record]").evaluate(
        "el => { const c = el.cloneNode(true); "
        "c.querySelectorAll('[data-lists-history]').forEach(x => x.remove()); return c.textContent; }")


def _error_at(page, field: str, code: str):
    return page.locator(f'[data-error="{field}"][data-code="{code}"]')


def _checked(page, prop: str):
    """Флажок свойства `prop` открытой формы поля."""
    return page.locator(f'[data-prop="{prop}"] input[name="{prop}"]')


def _save_choices(page, code) -> None:
    """Сохраняет значения списка значений: форма с `[data-lists-choices]`, POST `…/<код>/choices/`."""
    form = page.locator("form[data-lists-choices], form:has([data-lists-choices])").first
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.split("?")[0].endswith(f"/{code}/choices/")):
        form.locator(_SAVE).click()
    page.wait_for_load_state()


def _remove_choice(page, title: str) -> None:
    """Убирает значение `title` из формы значений (`button[data-action="choice-remove"]` его строки)."""
    rows = page.locator("[data-lists-choices] li[data-choice-id]:not([data-archived])")
    index = choice_titles(page).index(title)
    before = rows.count()
    rows.nth(index).locator('button[data-action="choice-remove"]').click()
    expect(rows).to_have_count(before - 1)


def _option_labels(page, code) -> list:
    """Подписи пунктов `select[name="<код>"]` формы записи."""
    return page.locator(f'[data-lists-field="{code}"] select[name="{code}"]').evaluate(
        "el => Array.from(el.options).map(o => o.textContent.trim())")


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l14_field_with_data_has_no_delete_and_type_change_but_has_hide(admin_page):
    """Сценарий 14, п. 1: у поля с данными в сетке полей нет «Удалить» и в форме поля нет выбора типа, есть «Скрыть»;
    у пустого поля — есть «Удалить» (FR-509)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Схема"))
    full = add_field(page, list_id, f"С данными {unique_word('f')}", "string", show_in_table=True)
    empty = add_field(page, list_id, f"Пустое {unique_word('f')}", "string")
    create_record(page, list_id, f"Запись {unique_word('t')}", {full: unique_word("v")})
    # п. 1: поле с данными
    open_settings(page, list_id, "fields")
    expect(_marked(page, full, "data-has-data", "true").first).to_be_attached()
    expect(_row(page, full).locator('button[data-action="field-hide"]')).to_have_count(1)
    expect(_row(page, full).locator('button[data-action="field-delete"]')).to_have_count(0)
    open_field(page, list_id, full)
    expect(page.locator("form[data-lists-field-form] [name=type]")).to_have_count(0)
    # п. 1: пустое поле — «Удалить» есть
    open_settings(page, list_id, "fields")
    expect(_marked(page, empty, "data-has-data", "false").first).to_be_attached()
    expect(_row(page, empty).locator('button[data-action="field-delete"]')).to_have_count(1)
    expect(_row(page, empty).locator('button[data-action="field-hide"]')).to_have_count(1)
    # п. 1: отказ и по прямому обращению (обход браузера): поле с данными не удаляется
    status, body = _direct_body(page, f"/lists/{list_id}/settings/fields/{full}/delete/", {})
    assert status == 200 and _has_code(body, "field_has_data"), f"удаление поля с данными: {status}"
    open_settings(page, list_id, "fields")
    expect(_row(page, full)).to_have_count(1)


def test_l14_hidden_field_is_absent_from_form_table_export_search_and_label(admin_page):
    """Сценарий 14, п. 2: после «Скрыть» поля нет в форме, таблице (столбец, выбор столбцов, фильтры), выгрузке, поиске
    внутри списка и этикетке; до «Скрыть» везде есть (FR-509)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Скрытие"))
    name = f"Инвентарный {unique_word('f')}"
    code = add_field(page, list_id, name, "string", unique=True, show_in_table=True)
    word = unique_word("inv")
    title_word = unique_word("ttl")
    number = create_record(page, list_id, f"Ноутбук {title_word}", {code: word})
    # до «Скрыть» поле видно везде (иначе проверка «нет» ничего не доказывает)
    _wait_search_fresh(page, list_id)
    before = _places(page, list_id, code, number, name, word)
    assert all(before.values()), f"до «Скрыть» поле видно не везде: {before}"
    # п. 2: «Скрыть»
    _hide(page, list_id, code)
    _wait_search_fresh(page, list_id)
    after = _places(page, list_id, code, number, name, word)
    assert not any(after.values()), f"после «Скрыть» поле осталось: {after}"
    # этикетка берёт следующее уникальное или «№ N»; значения скрытого поля в ней нет
    assert re.fullmatch(rf"№\s*{number}", _label_value(page, list_id, number)), "этикетка без значения скрытого поля"
    # поиск по названию записи работает (проверка не пуста из-за сбоя поиска)
    assert number in _search(page, list_id, title_word)


def test_l14_hidden_field_values_are_not_shown_in_record_card(admin_page):
    """Сценарий 14, п. 2 (решение владельца 2026-10-25): значения скрытого поля в карточке записи не показываются; до
    «Скрыть» значение в карточке есть (FR-509, FR-516)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Карточка"))
    name = f"Серийный {unique_word('f')}"
    code = add_field(page, list_id, name, "string")
    word = unique_word("val")
    number = create_record(page, list_id, f"Запись {unique_word('t')}", {code: word})
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_contain_text(word)
    _hide(page, list_id, code)
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_have_count(0)
    text = _record_text_without_history(page)
    assert word not in text, "значение скрытого поля показано в карточке"
    assert name not in text, "название скрытого поля показано в карточке"


def test_l14_hidden_field_changes_stay_visible_in_record_history(admin_page):
    """Сценарий 14, п. 2: изменения скрытого поля остаются видны в истории записи, а в карточке значения нет
    (FR-509, FR-522)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("История"))
    code = add_field(page, list_id, f"Место {unique_word('f')}", "string")
    old, new = unique_word("old"), unique_word("new")
    number = create_record(page, list_id, f"Запись {unique_word('t')}", {code: old})
    open_edit_record(page, list_id, number)
    fill_record(page, {code: new})
    assert submit_record(page) == number
    change = f'[data-lists-history] li[data-change-kind="changed"] [data-change-field="{code}"]'
    expect(page.locator(change).first).to_be_visible()
    _hide(page, list_id, code)
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_have_count(0)
    # п. 2: в истории строка изменения скрытого поля с прежним и новым значением
    field = page.locator(change)
    expect(field).to_have_count(1)
    expect(field.locator('[data-field="before"]')).to_contain_text(old)
    expect(field.locator('[data-field="after"]')).to_contain_text(new)
    assert new not in _record_text_without_history(page)


def test_l14_show_returns_field_with_values_to_card_form_and_table(admin_page):
    """Сценарий 14, п. 2: «Показать» возвращает поле со значениями в карточку, форму и таблицу (FR-509, FR-516)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Показать"))
    code = add_field(page, list_id, f"Метка {unique_word('f')}", "string", show_in_table=True)
    word = unique_word("val")
    number = create_record(page, list_id, f"Запись {unique_word('t')}", {code: word})
    _hide(page, list_id, code)
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_have_count(0)
    _show(page, list_id, code)
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_contain_text(word)
    open_edit_record(page, list_id, number)
    expect(page.locator(f'[data-lists-field="{code}"] [name="{code}"]')).to_have_value(word)
    _grid(page, list_id)
    expect(page.locator(f'tr[data-record-number="{number}"] td[data-col="{code}"]')).to_contain_text(word)


def test_l14_empty_field_is_deleted_after_confirm_dialog_with_journal_entry(admin_page):
    """Сценарий 14, п. 3: пустое поле удаляется после подтверждения в диалоге («Отмена» ничего не меняет); в журнале
    запись об удалении (FR-509, FR-542)."""
    page = admin_page
    list_name = unique_list_name("Удаление")
    list_id = create_list(page, list_name)
    name = f"Лишнее {unique_word('f')}"
    code = add_field(page, list_id, name, "string")
    create_record(page, list_id, f"Запись {unique_word('t')}")  # записи есть, значения поля ни у одной нет
    open_settings(page, list_id, "fields")
    expect(_marked(page, code, "data-has-data", "false").first).to_be_attached()
    # «Отмена» диалога: поле на месте
    _row(page, code).locator('button[data-action="field-delete"]').click()
    dialog = page.locator("dialog[data-lists-confirm][open]")
    expect(dialog).to_be_visible()
    dialog.locator('button[data-action="cancel"]').click()
    expect(dialog).not_to_be_visible()
    expect(_row(page, code)).to_have_count(1)
    # подтверждение: поле удалено
    _row(page, code).locator('button[data-action="field-delete"]').click()
    with page.expect_navigation():
        confirm_dialog(page)
    expect(page.locator('[data-lists-page="fields"]')).to_be_visible()
    expect(_row(page, code)).to_have_count(0)
    assert code not in field_codes(page, list_id, navigate=False)
    assert status_of(page, f"/lists/{list_id}/settings/fields/{code}/") == 404
    # журнал: удаление поля с названием поля и списка
    rows = [r for r in helpers_lists.audit_rows(page, "lists.field_deleted") if name in r and list_name in r]
    assert len(rows) == 1, rows


def test_l14_empty_field_type_can_be_changed(admin_page):
    """Сценарий 14, п. 3: у пустого поля тип меняется; в журнале «было / стало» (FR-509)."""
    page = admin_page
    list_name = unique_list_name("Тип")
    list_id = create_list(page, list_name)
    name = f"Значение {unique_word('f')}"
    code = add_field(page, list_id, name, "string")
    create_record(page, list_id, f"Запись {unique_word('t')}")
    open_field(page, list_id, code)
    expect(page.locator("form[data-lists-field-form] [name=type]").first).to_be_attached()
    helpers_lists.choose_type(page, "number")
    assert submit_field_form(page, list_id), f"тип пустого поля не изменён: {refusal_codes(page)}"
    open_settings(page, list_id, "fields")
    expect(_row(page, code).locator('[data-field="type"]')).to_have_text(helpers_lists.TYPE_LABELS["number"])
    sides = helpers_org.audit_sides(page, "lists.field_changed")
    assert any(list_name in b + a and "Строка" in b and "Число" in a for b, a in sides), sides


def test_l14_field_with_value_only_in_archived_record_or_in_history_cannot_be_deleted(admin_page):
    """Сценарий 14, п. 3: значение только в записи архива или только в истории записи — поле «с данными»: «Удалить»
    нет, прямое удаление отклонено; пустое поле удаляется (FR-509)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Данные"))
    in_archive = add_field(page, list_id, f"Архивное {unique_word('f')}", "string")
    in_history = add_field(page, list_id, f"Историческое {unique_word('f')}", "string")
    empty = add_field(page, list_id, f"Пустое {unique_word('f')}", "string")
    first = create_record(page, list_id, f"Запись {unique_word('t')}", {in_archive: unique_word("arc")})
    archive_record(page, list_id, first)
    second = create_record(page, list_id, f"Запись {unique_word('t')}", {in_history: unique_word("his")})
    open_edit_record(page, list_id, second)
    fill_record(page, {in_history: ""})
    assert submit_record(page) == second
    open_settings(page, list_id, "fields")
    for code in (in_archive, in_history):
        expect(_marked(page, code, "data-has-data", "true").first).to_be_attached()
        expect(_row(page, code).locator('button[data-action="field-delete"]')).to_have_count(0)
        expect(_row(page, code).locator('button[data-action="field-hide"]')).to_have_count(1)
    expect(_marked(page, empty, "data-has-data", "false").first).to_be_attached()
    expect(_row(page, empty).locator('button[data-action="field-delete"]')).to_have_count(1)
    # прямое удаление: отказ «Нельзя удалить: в поле есть данные», поля на месте
    for code in (in_archive, in_history):
        status, body = _direct_body(page, f"/lists/{list_id}/settings/fields/{code}/delete/", {})
        assert status == 200 and _has_code(body, "field_has_data"), f"{code}: ответ {status}"
        assert "Нельзя удалить: в поле есть данные" in body
    open_settings(page, list_id, "fields")
    for code in (in_archive, in_history):
        expect(_row(page, code)).to_have_count(1)


def test_l14_turning_on_unique_with_repeated_values_is_refused_with_first_record_numbers_and_values(admin_page):
    """Сценарий 14, п. 4: «Уникальное» при повторах значений (в том числе с записью в архиве) — отказ «Значения
    повторяются: №N — значение»; после исправления повторов включается (FR-509, FR-546)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Повторы"))
    code = add_field(page, list_id, f"Номер {unique_word('f')}", "string")
    word, other, third = unique_word("dup"), unique_word("one"), unique_word("two")
    first = create_record(page, list_id, f"Запись {unique_word('t')}", {code: word})
    second = create_record(page, list_id, f"Запись {unique_word('t')}", {code: word})
    create_record(page, list_id, f"Запись {unique_word('t')}", {code: other})
    archive_record(page, list_id, second)  # повтор через запись в архиве тоже считается
    open_field(page, list_id, code)
    fill_field_form(page, unique=True)
    assert not submit_field_form(page, list_id), "«Уникальное» включено при повторах"
    error = _error_at(page, "unique", "unique_repeats")
    expect(error).to_be_visible()
    text = error.inner_text()
    assert "Значения повторяются:" in text, text
    pairs = re.findall(r"№(\d+)\s+—\s+(\S+)", text)
    assert pairs and {n for n, _ in pairs} <= {str(first), str(second)}, text
    assert all(v.lower() == word.lower() for _, v in pairs), text
    # отказ ничего не включил
    open_field(page, list_id, code)
    expect(_checked(page, "unique")).not_to_be_checked()
    # повторы убраны — «Уникальное» включается
    open_edit_record(page, list_id, first)
    fill_record(page, {code: third})
    assert submit_record(page) == first
    open_field(page, list_id, code)
    fill_field_form(page, unique=True)
    assert submit_field_form(page, list_id), f"«Уникальное» не включено: {refusal_codes(page)}"
    open_field(page, list_id, code)
    expect(_checked(page, "unique")).to_be_checked()


def test_l14_turning_on_required_with_empty_values_is_refused_with_first_records_without_value(admin_page):
    """Сценарий 14, п. 5: «Обязательное» при пустых значениях (и в записи архива) — отказ «Не заполнено у записей:
    №N, …» (FR-509, FR-546)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Пустые"))
    code = add_field(page, list_id, f"Модель {unique_word('f')}", "string")
    filled = create_record(page, list_id, f"Запись {unique_word('t')}", {code: unique_word("val")})
    empty_a = create_record(page, list_id, f"Запись {unique_word('t')}")
    empty_b = create_record(page, list_id, f"Запись {unique_word('t')}")
    archive_record(page, list_id, empty_b)  # запись архива тоже проверяется
    open_field(page, list_id, code)
    fill_field_form(page, required=True)
    assert not submit_field_form(page, list_id), "«Обязательное» включено при пустых значениях"
    error = _error_at(page, "required", "required_missing")
    expect(error).to_be_visible()
    text = error.inner_text()
    assert "Не заполнено у записей:" in text, text
    numbers = set(re.findall(r"№(\d+)", text))
    assert numbers == {str(empty_a), str(empty_b)}, f"{text} (заполнена №{filled})"
    # отказ ничего не включил: запись без значения сохраняется
    open_field(page, list_id, code)
    expect(_checked(page, "required")).not_to_be_checked()
    assert create_record(page, list_id, f"Запись {unique_word('t')}")


def test_l14_new_field_in_list_with_records_cannot_be_required_at_once(admin_page):
    """Сценарий 14, п. 6: в списке с записями новое поле сразу «Обязательное» — отказ «Сначала заполните поле у всех
    записей»; в пустом списке то же поле создаётся (FR-509, FR-546)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Новое"))
    create_record(page, list_id, f"Запись {unique_word('t')}")
    name = f"Паспорт {unique_word('f')}"
    assert try_add_field(page, list_id, name, "string", required=True) == ""
    error = _error_at(page, "required", "required_new_with_records")
    expect(error).to_be_visible()
    assert "Сначала заполните поле у всех записей" in error.inner_text()
    open_settings(page, list_id, "fields")
    names = [tr.locator('[data-field="name"]').inner_text().strip()
             for tr in page.locator("[data-lists-fields-grid] tr[data-field-code]").all()
             if tr.get_attribute("data-field-code") != "title"]
    assert name not in names, "поле создано несмотря на отказ"
    # без «Обязательного» то же поле добавляется
    assert add_field(page, list_id, name, "string")
    # в пустом списке «Обязательное» при создании допустимо
    empty_id = create_list(page, unique_list_name("Пустой"))
    code = add_field(page, empty_id, f"Паспорт {unique_word('f')}", "string", required=True)
    open_field(page, empty_id, code)
    expect(_checked(page, "required")).to_be_checked()


def test_l14_hidden_required_field_is_not_checked_on_record_save(admin_page, employee):
    """Сценарий 14, п. 7: у скрытого обязательного поля сотрудник сохраняет запись без значения; до «Скрыть» то же
    сохранение отказано (FR-509, FR-515)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Обязательное"))
    code = add_field(page, list_id, f"Договор {unique_word('f')}", "string", required=True)
    admin_number = create_record(page, list_id, f"Запись {unique_word('t')}", {code: unique_word("val")})
    editor = helpers_lists.make_list_editor(employee, page, list_id)
    # до «Скрыть»: без значения — отказ «Обязательное поле» у поля
    assert try_create_record(editor.page, list_id, f"Запись {unique_word('t')}") == 0
    expect(_error_at(editor.page, code, "required")).to_be_visible()
    _hide(page, list_id, code)
    # после «Скрыть»: поля в форме нет, запись сохраняется без проверки обязательности
    open_add_record(editor.page, list_id)
    expect(editor.page.locator(f'[data-lists-field="{code}"]')).to_have_count(0)
    number = create_record(editor.page, list_id, f"Запись {unique_word('t')}")
    assert number != admin_number
    # правка прежней записи без скрытого поля тоже сохраняется
    open_edit_record(editor.page, list_id, admin_number)
    fill_record(editor.page, {"title": f"Новое {unique_word('t')}"})
    assert submit_record(editor.page) == admin_number


def test_l14_used_choice_goes_to_choice_archive_not_offered_but_shown_in_old_records_and_unused_is_deleted(admin_page):
    """Сценарий 14, п. 8: используемое значение «списка значений» при удалении уходит в архив значений (не
    предлагается при выборе, у старой записи показано); неиспользованное удаляется (FR-510)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Значения"))
    code = add_field(page, list_id, f"Статус {unique_word('f')}", "choice")
    used, kept, unused = (f"{p} {unique_word('c')}" for p in ("Занято", "Остаётся", "Лишнее"))
    ids = helpers_lists.set_choices(page, list_id, code, [used, kept, unused])
    used_id, kept_id, unused_id = ids[-3:]
    open_add_record(page, list_id)
    fill_record(page, {"title": f"Запись {unique_word('t')}"})
    choose(page, code, used)
    number = submit_record(page)
    assert number, f"запись со значением не создана: {refusal_codes(page)}"
    # удаление: используемое и неиспользованное значения
    open_field(page, list_id, code)
    _remove_choice(page, used)
    _remove_choice(page, unused)
    _save_choices(page, code)
    open_field(page, list_id, code)
    archived = page.locator(f'[data-lists-choices] li[data-choice-id="{used_id}"][data-archived]')
    expect(archived).to_have_count(1)
    expect(archived.locator('button[data-action="choice-restore"]')).to_have_count(1)
    expect(page.locator(f'[data-lists-choices] li[data-choice-id="{unused_id}"]')).to_have_count(0)
    expect(page.locator(f'[data-lists-choices] li[data-choice-id="{kept_id}"]:not([data-archived])')).to_have_count(1)
    assert choice_titles(page) == [kept]
    # не предлагается при выборе
    open_add_record(page, list_id)
    offered = _option_labels(page, code)
    assert kept in offered and used not in offered and unused not in offered, offered
    # у старой записи показано
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_contain_text(used)


def test_l14_target_list_of_link_field_with_data_cannot_be_changed_and_referenced_list_cannot_be_deleted(admin_page):
    """Сценарий 14, п. 9: у поля «запись другого списка» с данными целевой список не меняется (отказ), список, на
    который ссылается поле, не удаляется с причиной (FR-503, FR-511, FR-546)."""
    page = admin_page
    target_name, source_name = unique_list_name("Цель"), unique_list_name("Источник")
    target_id, source_id = create_list(page, target_name), create_list(page, source_name)
    other_id = create_list(page, unique_list_name("Другая"))
    target_word = unique_word("tgt")
    create_record(page, target_id, f"Цель {target_word}")
    link_name = f"Ссылка {unique_word('f')}"
    link = add_field(page, source_id, link_name, "record", target=target_id)
    open_add_record(page, source_id)
    fill_record(page, {"title": f"Источник {unique_word('t')}"})
    helpers_lists.pick(page, link, target_word)
    assert submit_record(page), f"запись со ссылкой не создана: {refusal_codes(page)}"
    open_settings(page, source_id, "fields")
    expect(_marked(page, link, "data-has-data", "true").first).to_be_attached()
    # п. 9: смена целевого списка — отказ
    status, body = _direct_body(page, f"/lists/{source_id}/settings/fields/{link}/",
                                {"name": link_name, "target": other_id})
    assert status == 200 and _has_code(body, "field_locked"), f"смена целевого списка: ответ {status}"
    assert re.search(r'data-error=["\']?target["\'\s>]', body), "отказ не у поля «целевой список»"
    # цель не изменилась: «Другая» не названа целью поля, её можно удалить
    open_settings(page, other_id)
    expect(page.locator('button[data-action="list-delete"]')).to_be_enabled()
    page.locator('button[data-action="list-delete"]').click()
    with page.expect_navigation():
        confirm_dialog(page)
    page.wait_for_url(re.compile(r"/lists/$"))
    assert str(other_id) not in helpers_lists.list_names_on_home(page)
    # список с записями не удаляется (причина названа)
    assert "Нельзя удалить:" in delete_reason(page, target_id)
    # п. 9: пустой список, на который ссылается поле, не удаляется; причина называет поле и список
    empty_target_name = unique_list_name("Пустая цель")
    empty_target = create_list(page, empty_target_name)
    second_name = f"Вторая ссылка {unique_word('f')}"
    add_field(page, source_id, second_name, "record", target=empty_target)
    reason = delete_reason(page, empty_target)
    assert f"Нельзя удалить: на список ссылается поле {second_name} списка {source_name}" in reason, reason


def test_l14_file_field_has_no_required_property(admin_page):
    """Сценарий 14, п. 10: у поля «файл» свойства «Обязательное» нет ни в новой форме, ни в форме поля; служба его
    отклоняет (FR-508)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Файлы"))
    open_new_field(page, list_id, "string")
    expect(page.locator('form[data-lists-field-form] [data-prop="required"]')).to_have_count(1)  # у строки оно есть
    form = open_new_field(page, list_id, "file")
    expect(form.locator('[data-prop="required"]')).to_have_count(0)
    expect(form.locator('[name="required"]')).to_have_count(0)
    name = f"Скан {unique_word('f')}"
    code = add_field(page, list_id, name, "file")
    form = open_field(page, list_id, code)
    expect(form.locator('[data-prop="required"]')).to_have_count(0)
    expect(form.locator('[name="required"]')).to_have_count(0)
    # прямой запрос с «Обязательное»: отказ у свойства, поле не стало обязательным
    status, body = _direct_body(page, f"/lists/{list_id}/settings/fields/{code}/", {"name": name, "required": "on"})
    assert status == 200 and _has_code(body, "property_not_allowed"), f"ответ {status}"
    assert re.search(r'data-error=["\']?required["\'\s>]', body), "отказ не у свойства «Обязательное»"
    form = open_field(page, list_id, code)
    expect(form.locator('[name="required"]')).to_have_count(0)


def test_l14_currency_of_money_field_with_data_cannot_be_changed_but_name_hint_order_and_thresholds_can(admin_page):
    """Сценарий 14, п. 11: у поля «деньги» с данными валюта не меняется (отказ); название, подсказку, порядок и
    пороги «срока» менять можно (FR-509)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Деньги"))
    money_name = f"Цена {unique_word('f')}"
    money = add_field(page, list_id, money_name, "money", show_in_table=True)
    date = add_field(page, list_id, f"Гарантия {unique_word('f')}", "date", deadline=True, thresholds=[30, 7])
    number = create_record(page, list_id, f"Запись {unique_word('t')}", {money: "1234,50", date: "01.01.2030"})
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{money}"]')).to_contain_text("₽")
    # валюта — отказ у поля «валюта»
    status, body = _direct_body(page, f"/lists/{list_id}/settings/fields/{money}/",
                                {"name": money_name, "currency": "USD"})
    assert status == 200 and _has_code(body, "field_locked"), f"смена валюты: ответ {status}"
    assert re.search(r'data-error=["\']?currency["\'\s>]', body), "отказ не у поля «валюта»"
    open_record(page, list_id, number)
    value = page.locator(f'[data-lists-value="{money}"]')
    expect(value).to_contain_text("₽")
    assert "$" not in value.inner_text()
    # название и подсказка
    new_name, hint = f"Стоимость {unique_word('f')}", f"Подсказка {unique_word('h')}"
    open_field(page, list_id, money)
    fill_field_form(page, name=new_name, hint=hint)
    assert submit_field_form(page, list_id), f"название и подсказка не сохранены: {refusal_codes(page)}"
    open_settings(page, list_id, "fields")
    expect(_row(page, money).locator('[data-field="name"]')).to_have_text(new_name)
    expect(open_field(page, list_id, money).locator('[name="hint"]')).to_have_value(hint)
    # порядок: «вверх» у второго поля
    _field_action(page, list_id, date, "field-up")
    assert field_codes(page, list_id, navigate=False) == ["title", date, money]
    # пороги «срока»
    open_field(page, list_id, date)
    fill_field_form(page, thresholds=[14, 3])
    assert submit_field_form(page, list_id), f"пороги не сохранены: {refusal_codes(page)}"
    open_field(page, list_id, date)
    boxes = page.locator('[data-prop="thresholds"] input[name="thresholds"]')
    assert {b.input_value() for b in boxes.all() if b.input_value()} == {"14", "3"}


def test_l14_multiple_values_turns_off_only_when_no_record_has_two_values(admin_page):
    """Сценарий 14, п. 11: «Несколько значений» выключается, только если ни у одной записи (и в архиве) нет двух
    значений (FR-509)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Несколько"))
    code = add_field(page, list_id, f"Теги {unique_word('f')}", "choice", multiple=True)
    first, second = f"Один {unique_word('c')}", f"Два {unique_word('c')}"
    helpers_lists.set_choices(page, list_id, code, [first, second])
    two = _make_record(page, list_id, code, [first, second])
    _make_record(page, list_id, code, [first])
    archive_record(page, list_id, two)
    # у записи в архиве два значения — выключить нельзя
    open_field(page, list_id, code)
    fill_field_form(page, multiple=False)
    assert not submit_field_form(page, list_id), "«Несколько значений» выключено при записи с двумя значениями"
    error = _error_at(page, "multiple", "multiple_in_use")
    expect(error).to_be_visible()
    assert "Нельзя выключить: есть записи с несколькими значениями" in error.inner_text()
    open_field(page, list_id, code)
    expect(_checked(page, "multiple")).to_be_checked()
    # запись возвращена и сведена к одному значению — выключается
    open_record(page, list_id, two)
    with page.expect_navigation():
        page.locator('button[data-action="record-restore"]').click()
    expect(page.locator('button[data-action="record-archive"]')).to_be_visible()
    open_edit_record(page, list_id, two)
    page.locator(f'[data-lists-field="{code}"]').get_by_label(second, exact=True).uncheck()
    assert submit_record(page) == two
    open_field(page, list_id, code)
    fill_field_form(page, multiple=False)
    assert submit_field_form(page, list_id), f"«Несколько значений» не выключено: {refusal_codes(page)}"
    open_field(page, list_id, code)
    expect(_checked(page, "multiple")).not_to_be_checked()


def _make_record(page, list_id, code, titles) -> int:
    """Запись со значениями `titles` поля «список значений» (флажки)."""
    open_add_record(page, list_id)
    fill_record(page, {"title": f"Запись {unique_word('t')}"})
    for title in titles:
        choose(page, code, title)
    number = submit_record(page)
    assert number, f"запись не создана: {refusal_codes(page)}"
    return number


def test_l14_role_or_unit_in_list_rights_cannot_be_deleted_and_refusal_names_the_lists(admin_page):
    """Сценарий 14, п. 12: роль или подразделение из набора прав списков не удаляются; отказ называет списки
    (FR-526, FR-546)."""
    page = admin_page
    first = unique_list_name("Альфа")
    second = unique_list_name("Бета")
    first_id, second_id = create_list(page, first), create_list(page, second)
    names = f"{first}, {second}"
    # роль: «Читают» первого списка и «Правят» второго
    role_id, _ = helpers_lists.make_list_role(page)
    helpers_lists.grant_role(page, first_id, "read", role_id)
    helpers_lists.grant_role(page, second_id, "edit", role_id)
    page.goto(f"/roles/{role_id}/")
    helpers.submit(page.locator('form[action$="/delete/"]'))
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert f"Нельзя удалить: указано в правах списков: {names}." in helpers.alert_text(page), helpers.alert_text(page)
    assert status_of(page, f"/roles/{role_id}/") == 200, "роль из прав списков удалена"
    # подразделение: те же два списка
    unit_name = helpers_org.unique_name("Узел")
    unit_id = helpers_org.create_unit(page, unit_name)
    helpers_lists.grant_unit(page, first_id, "read", unit_id, unit_name)
    helpers_lists.grant_unit(page, second_id, "edit", unit_id, unit_name)
    dialog = helpers_org.open_delete_dialog(page, unit_id)
    helpers_org.confirm_delete(page, dialog)
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert f"Узел нельзя удалить: указано в правах списков: {names}." in helpers.alert_text(page), helpers.alert_text(page)
    assert status_of(page, f"/structure/{unit_id}/") == 200, "узел из прав списков удалён"


def test_l14_settings_and_rights_changes_appear_in_journal_as_before_after_without_record_values(admin_page):
    """Сценарий 14, п. 13: изменения настроек, прав и полей списка записаны в журнал «было / стало», значений полей
    записей в журнале нет (FR-542)."""
    page = admin_page
    old_name, new_name = unique_list_name("Журнал"), unique_list_name("Переименован")
    list_id = create_list(page, old_name, "Первое описание")
    rows = helpers_lists.audit_rows(page, "lists.list_created", list_id)
    assert len(rows) == 1 and old_name in rows[0], rows
    field_name = f"Заметка {unique_word('f')}"
    code = add_field(page, list_id, field_name, "string")
    marker = unique_word("marker")
    number = create_record(page, list_id, f"Запись {unique_word('t')}", {code: marker})
    # настройки списка: было / стало
    open_settings(page, list_id)
    form = page.locator('[data-lists-page="settings"] form:has([name=name])').first
    form.locator("[name=name]").fill(new_name)
    form.locator("[name=description]").fill("Второе описание")
    with page.expect_navigation():
        form.locator(_SAVE).click()
    sides = helpers_org.audit_sides(page, "lists.list_changed", list_id)
    assert sides and old_name in sides[0][0] and new_name in sides[0][1], sides
    # права: «стало» называет роль
    role_id, role_name = helpers_lists.make_list_role(page)
    helpers_lists.grant_role(page, list_id, "read", role_id)
    sides = helpers_org.audit_sides(page, "lists.access_changed", list_id)
    assert sides and role_name in sides[0][1] and role_name not in sides[0][0], sides
    # поле: подсказка, «Скрыть», «Показать»; запись — «В архив»
    hint = f"Подсказка {unique_word('h')}"
    open_field(page, list_id, code)
    fill_field_form(page, hint=hint)
    assert submit_field_form(page, list_id)
    sides = helpers_org.audit_sides(page, "lists.field_changed")
    assert any(new_name in b + a and hint in a for b, a in sides), sides
    _hide(page, list_id, code)
    _show(page, list_id, code)
    archive_record(page, list_id, number)
    actions = ("lists.list_created", "lists.list_changed", "lists.access_changed", "lists.field_created",
               "lists.field_changed", "lists.field_hidden", "lists.field_shown", "lists.record_archived")
    for action in actions:
        mine = [r for r in helpers_lists.audit_rows(page, action) if new_name in r or old_name in r]
        assert mine, f"в журнале нет записи {action} по списку"
        assert not any(marker in r for r in mine), f"в журнале {action} значение поля записи"
    assert any(field_name in r and new_name in r for r in helpers_lists.audit_rows(page, "lists.field_hidden"))


def test_l14_settings_page_with_wide_fields_table_does_not_widen_page_at_360px(admin_page, browser,
                                                                                browser_context_args):
    """Сценарий 14, NFR-507: при 360 px страница настройки с широкой таблицей полей не шире экрана, таблица
    прокручивается внутри своего блока (NFR-507)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Узкий"))
    add_field(page, list_id, "Серийный" + "номер" * 18, "string")
    add_field(page, list_id, "Гарантия до", "date", deadline=True, thresholds=[30, 7])
    context, narrow = helpers_lists.open_narrow(browser, browser_context_args, page,
                                                f"/lists/{list_id}/settings/fields/", "fields")
    try:
        assert helpers_lists.page_fits(narrow), "горизонтальная прокрутка страницы настройки"
        block = narrow.locator(".lists-scroll:has([data-lists-fields-grid]), .lists-scroll[data-lists-fields-grid]")
        expect(block).to_have_count(1)
        assert helpers_lists.scrolls_inside(block), "таблица полей не прокручивается внутри блока"
        assert helpers_lists.page_fits(narrow)
    finally:
        context.close()
