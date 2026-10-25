"""T-6145: сценарий 6 — связи: «Закреплённое» в карточке сотрудника, подразделение, запись другого списка (FR-509,
FR-511, FR-514, FR-525, FR-526, FR-527).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md):
- управляющий — администратор круга `admin_page`: он читает все списки и заводит списки и записи; сотрудник для
  «Закреплённого» — активный сотрудник «Сотрудник ИТ» с уникальной частью ФИО (поле «сотрудник» не принимает
  приглашённых, заблокированных и уволенных, 12.3 `value_unavailable`); «Сотрудник ИТ» не читает списки, созданные
  тестом (стартовые списки он читает, но ни тест, ни «Закреплённое» их не касаются);
- читающий чужую карточку должен открывать `/staff/<id>/` (право `staff.view`), которого нет у роли без прав, поэтому
  в п. 3 читающий — «Сотрудник ИТ», которому список открыт через подразделение (набор «Читают», FR-513); в пп. 6–9
  читающие — `make_list_reader` / `make_list_editor`, им нужна только страница записи;
- каждый тест заводит свои списки, записи, подразделения с уникальными названиями; шесть стартовых списков и общие
  настройки тесты файла не трогают; сброса стенда, команд стенда и `stand_shell` в файле нет;
- строка «Закреплённого» — `li[data-pinned-record]` в `#lists-pinned[data-lists-pinned]` (11.8): «Название — Список
  — Поле»; ссылка на запись — `a` внутри строки; своя карточка — `/me/`, чужая — `/staff/<id>/`, раздел — на вкладке
  профиля (`[data-tab-panel="profile"]`, CONTRACT-002).
"""
import re
from types import SimpleNamespace

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_lists, helpers_org
from tests.e2e.helpers_lists import (
    add_field, archive_record, create_list, create_record, fill_record, grant_role, grant_unit, make_list_editor,
    make_list_reader, open_add_record, open_record, open_settings, pick, status_of, submit_record, unique_list_name,
    unique_word)

PINNED = "#lists-pinned[data-lists-pinned]"
ROW = f"{PINNED} li[data-pinned-record]"


# --- Помощники файла ------------------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _row_text(title: str, list_name: str, field_name: str) -> str:
    """Строка «Закреплённого» по 11.8: «Название — Список — Поле»."""
    return f"{title} — {list_name} — {field_name}"


def _open_colleague_card(page, user_id) -> None:
    page.goto(f"/staff/{user_id}/")
    expect(page.locator(f'[data-card][data-user-id="{user_id}"]')).to_be_visible()


def _open_own_card(page, user_id) -> None:
    page.goto("/me/")
    expect(page.locator(f'[data-card][data-user-id="{user_id}"]')).to_be_visible()


def _pinned_rows(page, count: int) -> list:
    """Ждёт `count` строк «Закреплённого» на открытой карточке и возвращает их тексты (по порядку страницы)."""
    expect(page.locator(ROW)).to_have_count(count)
    return [_norm(t) for t in page.locator(ROW).all_inner_texts()]


def _has_row(texts: list, expected: str) -> bool:
    return any(expected in text for text in texts)


def _make_person(employee, word: str):
    """Активный сотрудник с уникальной частью ФИО (она же запрос подсказки выбора)."""
    return employee(full_name=f"Закреплённый{word} Пётр Петрович")


def _add_record(page, list_id, title: str, *, values: dict | None = None, picks: dict | None = None) -> int:
    """Запись формой: `values` — `fill_record`; `picks` — код поля → `(запрос, номер выбранного | None)` через `pick`."""
    open_add_record(page, list_id)
    fill_record(page, {"title": title, **(values or {})})
    for code, (query, pick_id) in (picks or {}).items():
        pick(page, code, query, pick_id)
    number = submit_record(page)
    assert number, f"запись «{title}» не создана: {helpers_lists.refusal_codes(page)}"
    return number


def _pinned_setup(admin_page, person, word: str, *, archived_extra: bool = True) -> SimpleNamespace:
    """Два списка с полем «сотрудник» (названия полей разные) и по записи на `person`; у первого списка — ещё
    «Инвентарный номер» (значение другого поля записи, которого «Закреплённое» показывать не должно) и, если
    `archived_extra`, вторая запись на `person`, перенесённая в архив."""
    person_query = f"Закреплённый{word}"  # запрос подсказки — целая фамилия (по началу слова и по подстроке)
    a = SimpleNamespace(name=unique_list_name("Оборудование"), field="Ответственный", title=f"Ноутбук {word}",
                        serial=f"SN-{word}-17")
    b = SimpleNamespace(name=unique_list_name("Лицензии"), field="Хранитель", title=f"Лицензия {word}")
    a.id = create_list(admin_page, a.name)
    a.serial_code = add_field(admin_page, a.id, "Инвентарный номер", "string")
    a.code = add_field(admin_page, a.id, a.field, "person")
    b.id = create_list(admin_page, b.name)
    b.code = add_field(admin_page, b.id, b.field, "person")
    a.number = _add_record(admin_page, a.id, a.title, values={a.serial_code: a.serial},
                           picks={a.code: (person_query, person.id)})
    b.number = _add_record(admin_page, b.id, b.title, picks={b.code: (person_query, person.id)})
    a.archived_title = ""
    if archived_extra:
        a.archived_title = f"Старый ноутбук {word}"
        archived_number = _add_record(admin_page, a.id, a.archived_title, picks={a.code: (person_query, person.id)})
        archive_record(admin_page, a.id, archived_number)
    return SimpleNamespace(a=a, b=b, person=person, word=word,
                           expected=[_row_text(a.title, a.name, a.field), _row_text(b.title, b.name, b.field)])


def _dismiss(page, user_id) -> None:
    """Увольняет из карточки (срез 002): диалог `[data-dialog="dismiss"]` → подтверждение; ждёт отметку `уволен`."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _set_field_hidden(page, list_id, code, hide: bool) -> None:
    """«Скрыть» / «Показать» поле на вкладке «Поля»; ждёт, что в строке стала другая кнопка (11.2)."""
    open_settings(page, list_id, "fields")
    row = page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')
    row.locator(f'button[data-action="{"field-hide" if hide else "field-show"}"]').click()
    expect(row.locator(f'button[data-action="{"field-show" if hide else "field-hide"}"]')).to_be_visible()


def _value_cell(page, code):
    return page.locator(f'[data-lists-record] [data-lists-value="{code}"]')


# --- Тесты ----------------------------------------------------------------------------------------------------

def test_l06_pinned_section_shows_non_archived_records_of_two_lists_with_title_list_and_field(admin_page, employee):
    """Сценарий 6, п. 1: на сотрудника указывает поле «сотрудник» у записей двух списков (и ещё у записи в архиве);
    в карточке сотрудника в «Закреплённом» — записи не в архиве из этих списков, у каждой «название — список — поле»
    (FR-525)."""
    word = unique_word()
    setup = _pinned_setup(admin_page, _make_person(employee, word), word)
    # п. 1: открыта карточка сотрудника
    _open_colleague_card(admin_page, setup.person.id)
    expect(admin_page.locator(f'[data-tab-panel="profile"] {PINNED}')).to_have_count(1)
    texts = _pinned_rows(admin_page, 2)
    for expected in setup.expected:
        assert _has_row(texts, expected), (expected, texts)
    # запись в архиве в «Закреплённом» не показана
    assert not any(setup.a.archived_title in text for text in texts), texts
    expect(admin_page.locator(PINNED)).not_to_contain_text(setup.a.archived_title)


def test_l06_employee_not_reading_lists_sees_same_rows_on_own_card_without_link_or_other_fields(admin_page, employee):
    """Сценарий 6, п. 2: сотрудник, не читающий эти списки, открывает свою карточку: те же строки, но без перехода
    в запись и без других полей записи (FR-525)."""
    word = unique_word()
    setup = _pinned_setup(admin_page, _make_person(employee, word), word)
    page = setup.person.page
    # п. 2: своя карточка — те же две строки
    _open_own_card(page, setup.person.id)
    expect(page.locator(f'[data-tab-panel="profile"] {PINNED}')).to_have_count(1)
    texts = _pinned_rows(page, 2)
    for expected in setup.expected:
        assert _has_row(texts, expected), (expected, texts)
    # без перехода в запись
    expect(page.locator(f'{ROW} a[href*="/lists/"]')).to_have_count(0)
    # без других полей записи
    expect(page.locator(PINNED)).not_to_contain_text(setup.a.serial)
    # переход по адресу записи ему закрыт, как у несуществующей
    assert status_of(page, f"/lists/{setup.a.id}/{setup.a.number}/") == 404
    assert status_of(page, f"/lists/{setup.b.id}/{setup.b.number}/") == 404


def test_l06_reader_sees_linked_rows_of_read_list_on_colleague_card_and_no_rows_of_unread_lists(admin_page, employee):
    """Сценарий 6, п. 3: сотрудник, читающий один из двух списков, открывает карточку коллеги: строка этого списка
    ведёт в запись, строки списка, которого он не читает, не показаны (FR-525)."""
    word = unique_word()
    setup = _pinned_setup(admin_page, _make_person(employee, word), word, archived_extra=False)
    reader = employee(full_name=f"Читающий{word} Иван Иванович")
    # подготовка: читающий — участник подразделения, которому открыт список «Оборудование» (набор «Читают», FR-513)
    helpers_org.open_structure(admin_page)
    unit_name = helpers_org.unique_name("Читатели")
    unit_id = helpers_org.create_unit(admin_page, unit_name, kind="department", parent_id=helpers_org.root_id(admin_page))
    helpers_org.add_members(admin_page, unit_id, [reader.id], q=f"Читающий{word}")
    grant_unit(admin_page, setup.a.id, "read", unit_id, unit_name)
    # п. 3: карточка коллеги глазами читающего
    _open_colleague_card(reader.page, setup.person.id)
    texts = _pinned_rows(reader.page, 1)
    assert _has_row(texts, setup.expected[0]), (setup.expected[0], texts)
    link = reader.page.locator(f'{ROW} a[href="/lists/{setup.a.id}/{setup.a.number}/"]')
    expect(link).to_have_count(1)
    # строки нечитаемого списка нет ни названием записи, ни названием списка, ни названием поля
    for hidden in (setup.b.title, setup.b.name, setup.b.field):
        expect(reader.page.locator(PINNED)).not_to_contain_text(hidden)
    # ссылка ведёт в запись
    link.click()
    reader.page.wait_for_url(re.compile(rf"/lists/{setup.a.id}/{setup.a.number}/$"))
    expect(reader.page.locator("[data-lists-record]")).to_be_visible()
    assert status_of(reader.page, f"/lists/{setup.b.id}/{setup.b.number}/") == 404


def test_l06_dismissed_employee_card_shows_pinned_section_with_what_remains(admin_page, employee):
    """Сценарий 6, п. 4: сотрудник уволен; в его карточке раздел «Закреплённое» виден и показывает, что осталось за
    ним (FR-525; SPEC-002 FR-127)."""
    word = unique_word()
    setup = _pinned_setup(admin_page, _make_person(employee, word), word)
    # п. 4: уволен
    _dismiss(admin_page, setup.person.id)
    _open_colleague_card(admin_page, setup.person.id)
    expect(admin_page.locator(f'[data-card][data-user-id="{setup.person.id}"] [data-dismissed-badge]')).to_be_visible()
    texts = _pinned_rows(admin_page, 2)
    for expected in setup.expected:
        assert _has_row(texts, expected), (expected, texts)
    assert not any(setup.a.archived_title in text for text in texts), texts


def test_l06_employee_before_dismissal_sees_on_own_card_pinned_section_with_items_to_return(admin_page, employee):
    """Сценарий 6, п. 4 (до увольнения): сотрудник на своей карточке видит «Закреплённое» с тем, что за ним числится
    и что вернуть; после увольнения у управляющего те же строки (FR-525; SPEC-002 FR-127)."""
    word = unique_word()
    setup = _pinned_setup(admin_page, _make_person(employee, word), word)
    page = setup.person.page
    # до увольнения: своя карточка, раздел на вкладке профиля, обе строки
    _open_own_card(page, setup.person.id)
    expect(page.locator(f'[data-tab-panel="profile"] {PINNED}')).to_be_visible()
    before = _pinned_rows(page, 2)
    for expected in setup.expected:
        assert _has_row(before, expected), (expected, before)
    expect(page.locator(f'[data-card][data-user-id="{setup.person.id}"] [data-dismissed-badge]')).to_have_count(0)
    # после увольнения управляющий видит те же строки
    _dismiss(admin_page, setup.person.id)
    _open_colleague_card(admin_page, setup.person.id)
    after = _pinned_rows(admin_page, 2)
    for expected in setup.expected:
        assert _has_row(after, expected), (expected, after)


def test_l06_deleting_unit_referenced_by_record_including_archived_is_refused_with_record_count_and_no_record_list(
        admin_page):
    """Сценарий 6, п. 5: на подразделение указывает поле «подразделение» у записей, в том числе в архиве;
    управляющий структурой пытается его удалить — отказ с числом записей и без перечня записей (FR-526; SPEC-002
    FR-107)."""
    word = unique_word()
    list_name = unique_list_name("Размещение")
    list_id = create_list(admin_page, list_name)
    code = add_field(admin_page, list_id, "Отдел", "unit")
    helpers_org.open_structure(admin_page)
    unit_name = helpers_org.unique_name("Бухгалтерия")
    unit_id = helpers_org.create_unit(admin_page, unit_name, kind="department", parent_id=helpers_org.root_id(admin_page))
    titles = (f"Стол {word}", f"Шкаф {word}")
    numbers = [_add_record(admin_page, list_id, title, picks={code: (unit_name, unit_id)}) for title in titles]
    archive_record(admin_page, list_id, numbers[1])

    def refused() -> str:
        dialog = helpers_org.open_delete_dialog(admin_page, unit_id)
        helpers_org.confirm_delete(admin_page, dialog)
        expect(admin_page.locator("[role=alert]").first).to_be_visible()
        return _norm(helpers.alert_text(admin_page))

    # п. 5: одна запись в архиве, другая нет — отказ с числом записей и без перечня
    message = refused()
    assert "Узел нельзя удалить" in message and "подразделение указано в 2 записях списков" in message, message
    for title in titles:
        assert title not in message, message
    helpers_org.open_structure(admin_page, unit_id)
    expect(helpers_org.unit_li(admin_page, unit_id)).to_have_count(1)
    # обе записи в архиве — отказ тот же
    archive_record(admin_page, list_id, numbers[0])
    message = refused()
    assert "подразделение указано в 2 записях списков" in message, message
    for title in titles:
        assert title not in message, message
    helpers_org.open_structure(admin_page, unit_id)
    expect(helpers_org.unit_li(admin_page, unit_id)).to_have_count(1)


def test_l06_printer_card_lists_two_referring_cartridges_archived_one_marked_and_hides_unread_lists(
        admin_page, employee):
    """Сценарий 6, п. 6: на запись «Принтер» ссылаются две записи «Картридж», одна в архиве; в карточке принтера в
    «Ссылаются на эту запись» — обе, архивная с пометкой «в архиве»; записи списка, которого сотрудник не читает, не
    показаны (FR-527)."""
    word = unique_word()
    printers = SimpleNamespace(name=unique_list_name("Принтеры"), title=f"Принтер {word}")
    cartridges = SimpleNamespace(name=unique_list_name("Картриджи"), titles=(f"Картридж чёрный {word}",
                                                                              f"Картридж цветной {word}"))
    licences = SimpleNamespace(name=unique_list_name("Лицензии на драйверы"), title=f"Лицензия драйвера {word}")
    printers.id = create_list(admin_page, printers.name)
    printers.number = create_record(admin_page, printers.id, printers.title)
    for source in (cartridges, licences):
        source.id = create_list(admin_page, source.name)
        source.code = add_field(admin_page, source.id, "Принтер", "record", target=printers.id)
    numbers = [_add_record(admin_page, cartridges.id, title, picks={cartridges.code: (printers.title, None)})
               for title in cartridges.titles]
    licence_number = _add_record(admin_page, licences.id, licences.title,
                                 picks={licences.code: (printers.title, None)})
    archive_record(admin_page, cartridges.id, numbers[1])
    # читающий «Принтеры» и «Картриджи», но не «Лицензии на драйверы»
    reader = make_list_reader(employee, admin_page, printers.id, full_name=f"Читающий{word} Иван Иванович")
    grant_role(admin_page, cartridges.id, "read", reader.list_role_id)
    # п. 6: карточка принтера глазами читающего
    open_record(reader.page, printers.id, printers.number)
    block = reader.page.locator("[data-lists-referrers]")
    expect(block.locator("li[data-record-ref]")).to_have_count(2)
    live = block.locator(f'li[data-record-ref="{cartridges.id}:{numbers[0]}"]')
    old = block.locator(f'li[data-record-ref="{cartridges.id}:{numbers[1]}"]')
    expect(live).to_have_count(1)
    expect(old).to_have_count(1)
    expect(live).to_contain_text(cartridges.titles[0])
    expect(old).to_contain_text(cartridges.titles[1])
    expect(old.locator("[data-lists-archived]")).to_contain_text("в архиве")
    expect(live.locator("[data-lists-archived]")).to_have_count(0)
    # запись нечитаемого списка не показана ни строкой, ни названием
    expect(block.locator(f'li[data-record-ref="{licences.id}:{licence_number}"]')).to_have_count(0)
    expect(block).not_to_contain_text(licences.title)
    # управляющий, читающий всё, видит и её
    open_record(admin_page, printers.id, printers.number)
    expect(admin_page.locator("[data-lists-referrers] li[data-record-ref]")).to_have_count(3)
    expect(admin_page.locator(f'[data-lists-referrers] li[data-record-ref="{licences.id}:{licence_number}"]')
           ).to_have_count(1)


def test_l06_record_field_picker_finds_non_archived_records_of_readable_list_by_title_or_number_with_number_shown(
        admin_page, employee):
    """Сценарий 6, п. 7: при выборе значения «запись другого списка» сотрудник ищет по названию или номеру среди
    записей не в архиве списка, который читает; рядом с названием — номер записи (FR-511, FR-527)."""
    word_live, word_old = unique_word(), unique_word()
    target = SimpleNamespace(name=unique_list_name("Оборудование"), live=f"Монитор {word_live}",
                             old=f"Монитор {word_old}")
    source = SimpleNamespace(name=unique_list_name("Рабочие места"))
    target.id = create_list(admin_page, target.name)
    target.live_number = create_record(admin_page, target.id, target.live)
    old_number = create_record(admin_page, target.id, target.old)
    archive_record(admin_page, target.id, old_number)
    source.id = create_list(admin_page, source.name)
    source.code = add_field(admin_page, source.id, "Монитор рабочего места", "record", target=target.id)
    # правящий источник, читающий целевой список
    editor = make_list_editor(employee, admin_page, source.id, full_name=f"Правящий{word_live} Иван Иванович")
    grant_role(admin_page, target.id, "read", editor.list_role_id)
    page = editor.page
    open_add_record(page, source.id)
    box = page.locator(f'form[data-lists-record-form] [data-lists-field="{source.code}"]')
    field = box.locator("input[data-lists-picker]")
    options = box.locator("ul[data-lists-pick] li[data-pick-id]")

    def search(query: str) -> None:
        field.fill("")
        with page.expect_response(lambda r: "/pick/" in r.url):
            field.press_sequentially(query, delay=30)

    # п. 7: по названию — запись не в архиве, рядом с названием её номер
    search(word_live)
    expect(options.filter(has_text=target.live)).to_have_count(1)
    expect(options.filter(has_text=f"№{target.live_number}")).to_have_count(1)
    # запись в архиве по названию не предлагается
    search(word_old)
    expect(options.filter(has_text=target.old)).to_have_count(0)
    # по номеру записи; архивную по её номеру тоже не предлагают
    search(str(target.live_number))
    expect(options.filter(has_text=target.live).filter(has_text=f"№{target.live_number}")).to_have_count(1)
    search(str(old_number))
    expect(options.filter(has_text=target.old)).to_have_count(0)
    # выбор записи сохраняется в значении
    chosen = pick(page, source.code, word_live)
    assert chosen
    expect(page.locator(f'[data-lists-selected="{source.code}"] li[data-selected-id="{chosen}"]')).to_contain_text(
        target.live)
    fill_record(page, {"title": f"Место {word_live}"})
    assert submit_record(page)
    expect(_value_cell(page, source.code)).to_contain_text(target.live)


def test_l06_value_from_unread_list_shown_as_unavailable_list_record_without_title_or_link(admin_page, employee):
    """Сценарий 6, п. 8: поле «запись другого списка» указывает на список, которого сотрудник не читает; в открытой
    записи значение — «запись недоступного списка», без названия и без перехода (FR-514, FR-527)."""
    word = unique_word()
    target = SimpleNamespace(name=unique_list_name("Договоры"), title=f"Договор {word}")
    source = SimpleNamespace(name=unique_list_name("Лицензии"), title=f"Лицензия {word}")
    target.id = create_list(admin_page, target.name)
    target.number = create_record(admin_page, target.id, target.title)
    source.id = create_list(admin_page, source.name)
    source.code = add_field(admin_page, source.id, "Договор", "record", target=target.id)
    source.number = _add_record(admin_page, source.id, source.title, picks={source.code: (target.title, None)})
    reader = make_list_reader(employee, admin_page, source.id, full_name=f"Читающий{word} Иван Иванович")
    # п. 8: читающий только «Лицензии» открывает запись
    open_record(reader.page, source.id, source.number)
    cell = _value_cell(reader.page, source.code)
    expect(cell.locator("[data-lists-unavailable]")).to_have_count(1)
    expect(cell).to_contain_text("запись недоступного списка")
    expect(cell.locator("a")).to_have_count(0)
    expect(cell).not_to_contain_text(target.title)
    expect(reader.page.locator("[data-lists-record]")).not_to_contain_text(target.title)
    # управляющий видит название и переход
    open_record(admin_page, source.id, source.number)
    admin_cell = _value_cell(admin_page, source.code)
    expect(admin_cell).to_contain_text(target.title)
    expect(admin_cell.locator("a")).to_have_count(1)
    expect(admin_cell.locator("[data-lists-unavailable]")).to_have_count(0)


def test_l06_value_pointing_to_archived_record_shown_with_archived_mark(admin_page):
    """Сценарий 6, п. 9: запись в архиве, на которую ссылается поле; в ссылающейся записи ссылка показана с пометкой
    «в архиве» (FR-527)."""
    word = unique_word()
    target = SimpleNamespace(name=unique_list_name("Принтеры"), title=f"Принтер {word}")
    source = SimpleNamespace(name=unique_list_name("Картриджи"), title=f"Картридж {word}")
    target.id = create_list(admin_page, target.name)
    target.number = create_record(admin_page, target.id, target.title)
    source.id = create_list(admin_page, source.name)
    source.code = add_field(admin_page, source.id, "Принтер", "record", target=target.id)
    source.number = _add_record(admin_page, source.id, source.title, picks={source.code: (target.title, None)})
    # пока цель не в архиве, пометки нет
    open_record(admin_page, source.id, source.number)
    expect(_value_cell(admin_page, source.code)).to_contain_text(target.title)
    expect(_value_cell(admin_page, source.code).locator("[data-lists-archived]")).to_have_count(0)
    # п. 9: цель перенесена в архив
    archive_record(admin_page, target.id, target.number)
    open_record(admin_page, source.id, source.number)
    cell = _value_cell(admin_page, source.code)
    expect(cell).to_contain_text(target.title)
    expect(cell.locator("[data-lists-archived]")).to_contain_text("в архиве")
    expect(cell.locator("a")).to_have_count(1)


def test_l06_hidden_employee_field_gives_no_rows_in_pinned_section(admin_page, employee):
    """Сценарий 6, п. 10: поле «сотрудник» скрыто; в карточке сотрудника строки по этому полю в «Закреплённом» нет
    (FR-509, FR-525)."""
    word = unique_word()
    person = _make_person(employee, word)
    list_name = unique_list_name("Оборудование")
    list_id = create_list(admin_page, list_name)
    code = add_field(admin_page, list_id, "Ответственный", "person")
    title = f"Ноутбук {word}"
    _add_record(admin_page, list_id, title, picks={code: (f"Закреплённый{word}", person.id)})
    expected = _row_text(title, list_name, "Ответственный")
    _open_colleague_card(admin_page, person.id)
    assert _has_row(_pinned_rows(admin_page, 1), expected)
    # п. 10: поле скрыто — строки нет ни у управляющего, ни у самого сотрудника
    _set_field_hidden(admin_page, list_id, code, True)
    _open_colleague_card(admin_page, person.id)
    expect(admin_page.locator(ROW)).to_have_count(0)
    expect(admin_page.locator(PINNED)).not_to_contain_text(title)
    _open_own_card(person.page, person.id)
    expect(person.page.locator(ROW)).to_have_count(0)
    # поле возвращено — строка вернулась
    _set_field_hidden(admin_page, list_id, code, False)
    _open_colleague_card(admin_page, person.id)
    assert _has_row(_pinned_rows(admin_page, 1), expected)
