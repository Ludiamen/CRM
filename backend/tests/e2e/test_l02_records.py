"""T-6141: сценарий 2 — сотрудник ведёт записи: добавление, правка, обязательные и уникальные поля, одновременная правка
(FR-504, FR-507, FR-508, FR-513, FR-514, FR-515, FR-516, FR-517, FR-522, NFR-507).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md):
- список и поля заводит администратор круга `admin_page` через интерфейс (`_make_list`); записи ведёт правящий —
  `helpers_lists.make_list_editor` (своя роль без прав в наборе «Правят» своего списка), читающий — `make_list_reader`;
- каждый тест заводит свой список с уникальным названием; шесть стартовых списков и общие настройки не меняются, команд
  стенда и `stand_shell` в файле нет;
- два «контекста» сценария (пп. 6–7) — две сессии: две учётные записи правящих или второй контекст той же учётной записи
  (`new_context(storage_state=…)`); удаление записи навсегда делает администратор круга (право управляющего);
- тексты отказов — литералы раздела 12 контракта; отказы формы — `[data-error="<поле>"][data-code="<код>"]` и
  `[role=alert][data-code="<код>"]` (10.1); время в отказе одновременной правки сверяется с Москвой.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_lists import (
    add_field, archive_record, choose, confirm_dialog, create_list, create_record, make_list_editor,
    make_list_reader, open_add_record, open_edit_record, open_narrow, open_record, page_fits, pick, post_status,
    record_form, refusal_codes, set_choices, status_of, submit_record, unique_list_name,
    unique_word, fill_record)

MOSCOW = ZoneInfo("Europe/Moscow")


def _make_list(admin_page, specs, prefix="Оборудование"):
    """Список и поля через интерфейс администратора. `specs` — кортежи `(ключ, название, тип, свойства)`; возвращает
    номер списка и словарь «ключ → код поля»."""
    list_id = create_list(admin_page, unique_list_name(prefix), "Записи для проверки сценария 2")
    codes = {}
    for ref, name, type_code, props in specs:
        codes[ref] = add_field(admin_page, list_id, name, type_code, **props)
    return list_id, codes


def _error_at(page, field: str, code: str):
    """Отказ у поля (10.1): `[data-error="<поле>"][data-code="<код>"]`."""
    return page.locator(f'[data-error="{field}"][data-code="{code}"]')


def _alert(page, code: str):
    """Общий отказ (10.1): `[role=alert][data-code="<код>"]`."""
    return page.locator(f'[role=alert][data-code="{code}"]')


def _control(page, code: str):
    """Элемент ввода поля `code` в форме записи (контейнер `[data-lists-field]`, 11.4)."""
    return record_form(page).locator(f'[data-lists-field="{code}"] [name="{code}"]')


def _value(page, code: str):
    """Значение поля в карточке записи (`[data-lists-value]`, 11.5)."""
    return page.locator(f'[data-lists-record] [data-lists-value="{code}"]')


def _history_rows(page):
    """Строки истории в карточке (`[data-lists-history] li[data-change-kind]`, 11.5–11.6)."""
    return page.locator("[data-lists-history] li[data-change-kind]")


def _dismiss(admin_page, user_id) -> None:
    """Увольняет сотрудника из его карточки (образец `test_o07`: `[data-action="dismiss"]`, диалог, подтверждение)."""
    admin_page.goto(f"/staff/{user_id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l02_add_record_form_shows_fields_in_settings_order_with_required_marks_and_defaults_filled(
        admin_page, employee):
    """Сценарий 2, п. 1: «Добавить запись» открывает форму: поля по порядку настройки, обязательные отмечены, у полей
    со значением по умолчанию оно подставлено (FR-515, FR-508)."""
    specs = [
        ("model", "Модель", "string", {"required": True}),
        ("inv", "Инвентарный номер", "string", {"unique": True}),
        ("state", "Состояние", "string", {"default": "Новый"}),
        ("qty", "Количество", "number", {"default": "1"}),
        ("price", "Цена", "money", {}),
        ("bought", "Приобретено", "date", {"default": "15.03.2026"}),
        ("note", "Заметка", "text", {}),
        ("warranty", "Гарантия", "bool", {"default": True}),
    ]
    list_id, codes = _make_list(admin_page, specs)
    editor = make_list_editor(employee, admin_page, list_id)
    page = editor.page
    # п. 1: со страницы таблицы кнопка «Добавить запись» ведёт на форму
    page.goto(f"/lists/{list_id}/")
    add = page.locator('a[data-action="record-add"]')
    expect(add).to_have_count(1)
    expect(add).to_contain_text("Добавить запись")
    add.click()
    page.wait_for_url(re.compile(rf"/lists/{list_id}/add/$"))
    expect(page.locator('[data-lists-page="add"]')).to_be_visible()
    form = record_form(page)
    expect(form).to_be_visible()
    # п. 1: поля — «Название», затем по порядку настройки (порядок создания)
    expected = ["title"] + [codes[ref] for ref, *_ in specs]
    shown = [el.get_attribute("data-lists-field") for el in form.locator("[data-lists-field]").all()]
    assert shown == expected, f"порядок полей в форме {shown}, ожидался {expected}"
    # п. 1: обязательные отмечены `[data-required]`, остальные — нет (у «Названия» отметку контракт не задаёт)
    for ref, _name, _type, props in specs:
        marked = form.locator(f'[data-lists-field="{codes[ref]}"][data-required]')
        expect(marked).to_have_count(1 if props.get("required") else 0)
    # п. 1: значения по умолчанию подставлены, у остальных полей пусто
    expect(_control(page, codes["state"])).to_have_value("Новый")
    expect(_control(page, codes["qty"])).to_have_value("1")
    expect(_control(page, codes["bought"])).to_have_value("15.03.2026")
    expect(form.locator(f'[data-lists-field="{codes["warranty"]}"] input[type=checkbox][name="{codes["warranty"]}"]')
           ).to_be_checked()
    for ref in ("model", "inv", "price", "note"):
        expect(_control(page, codes[ref])).to_have_value("")
    expect(_control(page, "title")).to_have_value("")


def test_l02_empty_required_field_or_empty_title_is_refused_with_reason_and_other_input_kept(admin_page, employee):
    """Сценарий 2, п. 2: пустое обязательное поле и пустое «Название» — сохранения нет, у поля причина «Обязательное
    поле», остальное введённое осталось в форме (FR-515)."""
    specs = [
        ("model", "Модель", "string", {"required": True}),
        ("inv", "Инвентарный номер", "string", {}),
        ("qty", "Количество", "number", {}),
    ]
    list_id, codes = _make_list(admin_page, specs)
    page = make_list_editor(employee, admin_page, list_id).page
    open_add_record(page, list_id)
    # п. 2: «Название» и обязательная «Модель» пусты, остальные поля заполнены
    fill_record(page, {"title": "", codes["model"]: "", codes["inv"]: "ИН-7", codes["qty"]: "7"})
    assert submit_record(page) == 0, "запись с пустыми обязательными полями сохранена"
    # п. 2: у каждого пустого обязательного поля — причина
    for field in ("title", codes["model"]):
        error = _error_at(page, field, "required")
        expect(error).to_have_count(1)
        expect(error).to_contain_text("Обязательное поле")
    assert sorted(refusal_codes(page)) == sorted([("title", "required"), (codes["model"], "required")])
    # п. 2: введённое в остальных полях осталось
    expect(record_form(page)).to_be_visible()
    expect(_control(page, codes["inv"])).to_have_value("ИН-7")
    expect(_control(page, codes["qty"])).to_have_value("7")
    # п. 2: записи не появилось
    page.goto(f"/lists/{list_id}/")
    expect(page.locator('[data-empty-state="lists-grid"]')).to_be_visible()
    # после заполнения обязательных полей та же форма сохраняется
    assert create_record(page, list_id, "Принтер", {codes["model"]: "LaserJet", codes["inv"]: "ИН-7"}) > 0


def test_l02_unique_value_with_other_case_and_spaces_is_refused_with_link_to_existing_record(admin_page, employee):
    """Сценарий 2, п. 3: в списке есть «ИН-100» в уникальном поле; « ин-100 » в новой записи — сохранения нет, сказано
    «Такое значение уже есть в списке» и есть ссылка на ту запись (FR-508, FR-515)."""
    list_id, codes = _make_list(admin_page, [("inv", "Инвентарный номер", "string", {"unique": True})])
    page = make_list_editor(employee, admin_page, list_id).page
    owner = create_record(page, list_id, "Ноутбук", {codes["inv"]: "ИН-100"})
    # п. 3: новая запись с тем же значением в другом регистре и с пробелами по краям
    open_add_record(page, list_id)
    fill_record(page, {"title": "Второй ноутбук", codes["inv"]: " ин-100 "})
    assert submit_record(page) == 0, "запись с повтором уникального значения сохранена"
    error = _error_at(page, codes["inv"], "unique_taken")
    expect(error).to_have_count(1)
    expect(error).to_contain_text("Такое значение уже есть в списке")
    # п. 3: ссылка на запись-владельца
    link = record_form(page).locator(f'a[href="/lists/{list_id}/{owner}/"]')
    expect(link).to_have_count(1)
    expect(_control(page, "title")).to_have_value("Второй ноутбук")
    # п. 3: второй записи нет
    page.goto(f"/lists/{list_id}/")
    expect(page.locator("tr[data-record-number]")).to_have_count(1)
    # другое значение сохраняется
    assert create_record(page, list_id, "Второй ноутбук", {codes["inv"]: "ИН-101"}) > owner


def test_l02_unique_value_of_archived_record_also_refuses_save(admin_page, employee):
    """Сценарий 2, п. 3: запись в архиве тоже считается — повтор её уникального значения отклонён со ссылкой на неё
    (FR-508, FR-515)."""
    list_id, codes = _make_list(admin_page, [("inv", "Инвентарный номер", "string", {"unique": True})])
    page = make_list_editor(employee, admin_page, list_id).page
    owner = create_record(page, list_id, "Старый монитор", {codes["inv"]: "ИН-200"})
    archive_record(page, list_id, owner)
    # п. 3: значение записи в архиве занято
    open_add_record(page, list_id)
    fill_record(page, {"title": "Новый монитор", codes["inv"]: " ин-200"})
    assert submit_record(page) == 0, "повтор значения записи из архива сохранён"
    error = _error_at(page, codes["inv"], "unique_taken")
    expect(error).to_have_count(1)
    expect(error).to_contain_text("Такое значение уже есть в списке")
    expect(record_form(page).locator(f'a[href="/lists/{list_id}/{owner}/"]')).to_have_count(1)


def test_l02_letters_in_number_wrong_date_format_three_decimals_in_money_and_over_limit_value_are_refused_at_field(
        admin_page, employee):
    """Сценарий 2, п. 4: число с буквами, дата не ДД.ММ.ГГГГ, деньги с тремя знаками после запятой и строка длиннее 500
    знаков — сохранения нет, у каждого поля своя причина (FR-507, FR-515)."""
    specs = [
        ("qty", "Количество", "number", {}),
        ("bought", "Приобретено", "date", {}),
        ("price", "Цена", "money", {"currency": "RUB"}),
        ("label", "Метка", "string", {}),
    ]
    list_id, codes = _make_list(admin_page, specs)
    page = make_list_editor(employee, admin_page, list_id).page
    open_add_record(page, list_id)
    long_label = "а" * 501
    fill_record(page, {"title": "Сервер", codes["qty"]: "12abc", codes["bought"]: "31/12/2026",
                       codes["price"]: "12,345", codes["label"]: long_label})
    assert submit_record(page) == 0, "запись с неверными значениями сохранена"
    # п. 4: у каждого поля — своя причина
    expect(_error_at(page, codes["qty"], "bad_number")).to_contain_text("Введите число")
    expect(_error_at(page, codes["bought"], "bad_date")).to_contain_text("Введите дату ДД.ММ.ГГГГ")
    expect(_error_at(page, codes["price"], "money_digits")).to_contain_text("Не больше 13 цифр до запятой и двух после")
    expect(_error_at(page, codes["label"], "too_long")).to_contain_text("Предел: 500 знаков")
    assert sorted(refusal_codes(page)) == sorted([
        (codes["qty"], "bad_number"), (codes["bought"], "bad_date"), (codes["price"], "money_digits"),
        (codes["label"], "too_long")])
    # п. 4: введённое осталось в форме
    expect(_control(page, codes["qty"])).to_have_value("12abc")
    expect(_control(page, codes["bought"])).to_have_value("31/12/2026")
    expect(_control(page, codes["price"])).to_have_value("12,345")
    assert len(_control(page, codes["label"]).input_value()) == 501
    # исправленные значения сохраняются; число и деньги показаны по контракту (12.4)
    fill_record(page, {codes["qty"]: "12,5", codes["bought"]: "15.03.2026", codes["price"]: "1234,5",
                       codes["label"]: "короткая метка"})
    number = submit_record(page)
    assert number > 0, f"исправленная запись не сохранена: {refusal_codes(page)}"
    expect(_value(page, codes["qty"])).to_have_text("12,5")
    expect(_value(page, codes["price"])).to_contain_text("1 234,50 ₽")


def test_l02_saved_record_card_opens_at_number_url_that_stays_after_rename(admin_page, employee):
    """Сценарий 2, п. 5: сохранённая запись открывается карточкой по адресу с её номером; адрес не меняется при
    переименовании (FR-504, FR-516)."""
    list_id, _codes = _make_list(admin_page, [("model", "Модель", "string", {})])
    page = make_list_editor(employee, admin_page, list_id).page
    first_title = f"Ноутбук {unique_word()}"
    number = create_record(page, list_id, first_title)
    # п. 5: адрес карточки — /lists/<список>/<номер>/
    page.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/$"))
    page.goto(f"/lists/{list_id}/{number}/")
    expect(page.locator('[data-lists-page="record"] [data-lists-record]')).to_contain_text(first_title)
    # п. 5: переименование не меняет адрес
    new_title = f"Планшет {unique_word()}"
    open_edit_record(page, list_id, number)
    fill_record(page, {"title": new_title})
    assert submit_record(page) == number
    assert re.search(rf"/lists/{list_id}/{number}/$", page.url)
    # п. 5: старый адрес показывает ту же запись под новым названием; следующая запись получает следующий номер
    page.goto(f"/lists/{list_id}/{number}/")
    expect(page.locator("[data-lists-record]")).to_contain_text(new_title)
    expect(page.locator("[data-lists-record]")).not_to_contain_text(first_title)
    assert create_record(page, list_id, f"Монитор {unique_word()}") == number + 1


def test_l02_second_editor_save_after_first_in_other_context_is_rejected_with_who_and_when_input_kept_first_change_intact(
        admin_page, employee):
    """Сценарий 2, п. 6: двое открыли запись на правке, первый сохранил; второй при «Сохранить» получает «Запись уже
    изменил <имя> в <время>», введённое осталось, чужая правка не затёрта (FR-517)."""
    specs = [("model", "Модель", "string", {}), ("note", "Заметка", "string", {})]
    list_id, codes = _make_list(admin_page, specs)
    first = make_list_editor(employee, admin_page, list_id, full_name="Сидоров Пётр Иванович")
    second = make_list_editor(employee, admin_page, list_id, full_name="Орлов Павел Сергеевич")
    number = create_record(first.page, list_id, "Ноутбук", {codes["model"]: "Исходная модель"})
    # п. 6: оба открыли одну и ту же правку
    open_edit_record(first.page, list_id, number)
    open_edit_record(second.page, list_id, number)
    # п. 6: первый сохранил свою правку
    fill_record(first.page, {codes["model"]: "Модель первого"})
    assert submit_record(first.page) == number
    # п. 6: второй правит другое поле и сохраняет
    fill_record(second.page, {codes["note"]: "Заметка второго"})
    assert submit_record(second.page) == 0, "сохранение по устаревшей версии принято"
    alert = _alert(second.page, "version_conflict")
    expect(alert).to_have_count(1)
    expect(alert).to_contain_text(f"Запись уже изменил {first.full_name} в ")
    found = re.search(r"Запись уже изменил (.+) в (\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})", alert.inner_text())
    assert found, f"нет времени в отказе: {alert.inner_text()!r}"
    assert found.group(1) == first.full_name
    day, month, year, hour, minute = (int(found.group(i)) for i in range(2, 7))
    saved_at = datetime(year, month, day, hour, minute, tzinfo=MOSCOW)
    assert abs(datetime.now(MOSCOW) - saved_at) <= timedelta(minutes=10), f"время по Москве {saved_at}"
    # п. 6: введённое вторым осталось в форме
    expect(record_form(second.page)).to_be_visible()
    expect(_control(second.page, codes["note"])).to_have_value("Заметка второго")
    # п. 6: правка первого не затёрта, правка второго не сохранена
    open_record(first.page, list_id, number)
    expect(_value(first.page, codes["model"])).to_have_text("Модель первого")
    expect(first.page.locator("[data-lists-record]")).not_to_contain_text("Заметка второго")


def test_l02_save_after_record_archived_in_other_context_shows_record_archived_and_keeps_input(
        admin_page, employee, new_context):
    """Сценарий 2, п. 7: пока форма открыта, запись отправили в архив; «Сохранить» — сохранения нет, «Запись в архиве»,
    введённое осталось (FR-517)."""
    list_id, codes = _make_list(admin_page, [("model", "Модель", "string", {}), ("note", "Заметка", "string", {})])
    editor = make_list_editor(employee, admin_page, list_id)
    page = editor.page
    number = create_record(page, list_id, "Ноутбук")
    open_edit_record(page, list_id, number)
    # п. 7: во втором контексте той же учётной записи запись уходит в архив
    other = new_context(storage_state=page.context.storage_state()).new_page()
    archive_record(other, list_id, number)
    # п. 7: «Сохранить» в первом контексте
    fill_record(page, {codes["note"]: "Введено до архива"})
    assert submit_record(page) == 0, "запись в архиве сохранена"
    alert = _alert(page, "record_archived")
    expect(alert).to_have_count(1)
    expect(alert).to_contain_text("Запись в архиве")
    expect(record_form(page)).to_be_visible()
    expect(_control(page, codes["note"])).to_have_value("Введено до архива")
    # п. 7: введённое не попало в запись
    open_record(other, list_id, number)
    expect(other.locator("[data-lists-record]")).not_to_contain_text("Введено до архива")


def test_l02_save_after_record_purged_in_other_context_shows_record_deleted_and_keeps_input(
        admin_page, employee, new_context):
    """Сценарий 2, п. 7: пока форма открыта, запись удалили навсегда; «Сохранить» — сохранения нет, «Запись удалена»,
    введённое осталось (FR-517)."""
    list_id, codes = _make_list(admin_page, [("model", "Модель", "string", {}), ("note", "Заметка", "string", {})])
    editor = make_list_editor(employee, admin_page, list_id)
    page = editor.page
    number = create_record(page, list_id, "Ноутбук")
    open_edit_record(page, list_id, number)
    # п. 7: запись в архив (второй контекст правящего), затем навсегда — администратор (право управляющего)
    other = new_context(storage_state=page.context.storage_state()).new_page()
    archive_record(other, list_id, number)
    open_record(admin_page, list_id, number)
    admin_page.locator('button[data-action="record-purge"]').click()
    confirm_dialog(admin_page)
    admin_page.wait_for_url(re.compile(rf"/lists/{list_id}/\?preset=archive"))
    assert status_of(page, f"/lists/{list_id}/{number}/") == 404
    # п. 7: «Сохранить» в первом контексте
    fill_record(page, {codes["note"]: "Введено до удаления"})
    assert submit_record(page) == 0, "удалённая запись сохранена"
    alert = _alert(page, "record_gone")
    expect(alert).to_have_count(1)
    expect(alert).to_contain_text("Запись удалена")
    expect(record_form(page)).to_be_visible()
    expect(_control(page, codes["note"])).to_have_value("Введено до удаления")


def test_l02_save_without_changes_adds_no_history_entry(admin_page, employee):
    """Сценарий 2, п. 8: сохранение формы без изменений не добавляет запись в историю (FR-522)."""
    specs = [("model", "Модель", "string", {}), ("qty", "Количество", "number", {}), ("price", "Цена", "money", {})]
    list_id, codes = _make_list(admin_page, specs)
    page = make_list_editor(employee, admin_page, list_id).page
    number = create_record(page, list_id, "Ноутбук", {codes["model"]: "Модель", codes["qty"]: "12,5",
                                                      codes["price"]: "1234,5"})
    open_record(page, list_id, number)
    expect(_history_rows(page)).to_have_count(1)
    expect(page.locator('[data-lists-history] li[data-change-kind="created"]')).to_have_count(1)
    # п. 8: «Сохранить» без правок
    open_edit_record(page, list_id, number)
    assert submit_record(page) == number
    open_record(page, list_id, number)
    expect(_history_rows(page)).to_have_count(1)
    expect(page.locator('[data-lists-history] li[data-change-kind="changed"]')).to_have_count(0)
    # контроль: настоящая правка запись в истории добавляет
    open_edit_record(page, list_id, number)
    fill_record(page, {codes["model"]: "Другая модель"})
    assert submit_record(page) == number
    open_record(page, list_id, number)
    expect(_history_rows(page)).to_have_count(2)
    expect(page.locator('[data-lists-history] li[data-change-kind="changed"]')).to_have_count(1)


def test_l02_reader_sees_no_add_or_edit_buttons_and_direct_add_and_edit_are_denied(admin_page, employee):
    """Сценарий 2, п. 9: читающий не видит «Добавить запись» и «Править»; прямое обращение — отказ 403 (FR-513,
    FR-514)."""
    list_id, codes = _make_list(admin_page, [("model", "Модель", "string", {})])
    editor = make_list_editor(employee, admin_page, list_id)
    reader = make_list_reader(employee, admin_page, list_id)
    number = create_record(editor.page, list_id, "Ноутбук", {codes["model"]: "Исходная"})
    # контроль: у правящего кнопки есть
    editor.page.goto(f"/lists/{list_id}/")
    expect(editor.page.locator('a[data-action="record-add"]')).to_have_count(1)
    open_record(editor.page, list_id, number)
    expect(editor.page.locator('a[data-action="record-edit"]')).to_have_count(1)
    # п. 9: у читающего таблица и карточка есть, кнопок нет
    page = reader.page
    page.goto(f"/lists/{list_id}/")
    expect(page.locator('tr[data-record-number]')).to_have_count(1)
    expect(page.locator('a[data-action="record-add"]')).to_have_count(0)
    open_record(page, list_id, number)
    expect(page.locator('a[data-action="record-edit"]')).to_have_count(0)
    expect(page.locator('button[data-action="record-archive"]')).to_have_count(0)
    # п. 9: прямое обращение — отказ
    assert status_of(page, f"/lists/{list_id}/add/") == 403
    assert status_of(page, f"/lists/{list_id}/{number}/edit/") == 403
    assert post_status(page, f"/lists/{list_id}/add/", {"title": "Чужая запись"}) == 403
    assert post_status(page, f"/lists/{list_id}/{number}/edit/",
                       {"title": "Чужая правка", "base_version": "1"}) == 403
    # п. 9: ничего не создано и не изменено
    page.goto(f"/lists/{list_id}/")
    expect(page.locator("tr[data-record-number]")).to_have_count(1)
    open_record(page, list_id, number)
    expect(page.locator("[data-lists-record]")).to_contain_text("Ноутбук")
    expect(page.locator("[data-lists-record]")).not_to_contain_text("Чужая правка")


def test_l02_dismissed_employee_in_record_shown_with_dismissed_mark_and_absent_from_choice_when_editing(
        admin_page, employee):
    """Сценарий 2, п. 10: уволенный сотрудник, уже указанный в записи, показан с ФИО и пометкой «уволен»; при правке в
    выборе уволенных нет (FR-507)."""
    list_id, codes = _make_list(admin_page, [("owner", "Ответственный", "person", {})])
    code = codes["owner"]
    word = unique_word("pk")
    gone = employee(full_name=f"Выбывший {word}")
    stays = employee(full_name=f"Действующий {word}")
    page = make_list_editor(employee, admin_page, list_id).page
    open_add_record(page, list_id)
    fill_record(page, {"title": "Ноутбук"})
    pick(page, code, word, pick_id=gone.id)
    number = submit_record(page)
    assert number > 0, f"запись не сохранена: {refusal_codes(page)}"
    # п. 10: сотрудник уволен
    _dismiss(admin_page, gone.id)
    # п. 10: в карточке — ФИО с пометкой «уволен»
    open_record(page, list_id, number)
    mark = _value(page, code).locator('span[data-dismissed="true"]')
    expect(mark).to_have_count(1)
    expect(mark).to_contain_text(gone.full_name)
    expect(mark).to_contain_text("(уволен)")
    # п. 10: при правке уволенного в подсказке выбора нет, действующий предложен
    open_edit_record(page, list_id, number)
    box = page.locator(f'[data-lists-field="{code}"]')
    expect(page.locator(f'[data-lists-selected="{code}"] li[data-selected-id="{gone.id}"]')).to_have_count(1)
    field = box.locator("input[data-lists-picker]")
    field.fill("")
    field.press_sequentially(word, delay=30)
    expect(box.locator(f'ul[data-lists-pick] li[data-pick-id="{stays.id}"]')).to_have_count(1, timeout=10_000)
    expect(box.locator(f'ul[data-lists-pick] li[data-pick-id="{gone.id}"]')).to_have_count(0)
    # п. 10: старое значение остаётся — запись сохраняется, пометка в карточке прежняя
    assert submit_record(page) == number
    expect(_value(page, code).locator('span[data-dismissed="true"]')).to_have_count(1)


def test_l02_choosing_and_removing_several_employees_and_choice_values_saves_set_without_repeats(
        admin_page, employee):
    """Сценарий 2, п. 11: у записи несколько сотрудников и несколько значений списка значений; выбор и снятие
    сохраняют набор без повторов (FR-508)."""
    specs = [("tags", "Метки", "choice", {"multiple": True}), ("team", "Ответственные", "person", {"multiple": True})]
    list_id, codes = _make_list(admin_page, specs)
    tags, team = codes["tags"], codes["team"]
    set_choices(admin_page, list_id, tags, ["Синий", "Красный", "Зелёный"])
    word = unique_word("pk")
    first = employee(full_name=f"Первый {word}")
    second = employee(full_name=f"Второй {word}")
    page = make_list_editor(employee, admin_page, list_id).page
    selected = page.locator(f'[data-lists-selected="{team}"] li[data-selected-id]')

    def tag_box(title):
        return record_form(page).locator(f'[data-lists-field="{tags}"]').get_by_label(title, exact=True)

    open_add_record(page, list_id)
    fill_record(page, {"title": "Ноутбук"})
    # п. 11: выбраны три значения, одно снято
    for title in ("Синий", "Красный", "Зелёный"):
        choose(page, tags, title)
    tag_box("Красный").uncheck()
    # п. 11: выбраны двое, второй снят и выбран снова, первый предложен повторно
    pick(page, team, word, pick_id=first.id)
    pick(page, team, word, pick_id=second.id)
    page.locator(f'[data-lists-selected="{team}"] li[data-selected-id="{second.id}"] [data-action="pick-remove"]').click()
    expect(selected).to_have_count(1)
    pick(page, team, word, pick_id=second.id)
    field = record_form(page).locator(f'[data-lists-field="{team}"] input[data-lists-picker]')
    field.fill("")
    with page.expect_response(lambda r: "/lists/people/" in r.url):
        field.press_sequentially(word, delay=30)
    again = record_form(page).locator(f'[data-lists-field="{team}"] ul[data-lists-pick] li[data-pick-id="{first.id}"]')
    if again.count():
        again.click()
    expect(selected).to_have_count(2)
    assert sorted(el.get_attribute("data-selected-id") for el in selected.all()) == sorted([first.id, second.id])
    expect(record_form(page).locator(f'input[type=hidden][name="{team}"]')).to_have_count(2)
    number = submit_record(page)
    assert number > 0, f"запись не сохранена: {refusal_codes(page)}"
    # п. 11: в карточке набор без повторов
    for title, shown in (("Синий", True), ("Красный", False), ("Зелёный", True)):
        text = _value(page, tags).inner_text()
        assert (title in text) == shown, f"«{title}» в карточке: {text!r}"
    people = _value(page, team).inner_text()
    assert people.count(first.full_name) == 1 and people.count(second.full_name) == 1, people
    # п. 11: правка — снят «Синий», выбран «Красный», снят первый сотрудник
    open_edit_record(page, list_id, number)
    expect(tag_box("Синий")).to_be_checked()
    expect(tag_box("Красный")).not_to_be_checked()
    expect(tag_box("Зелёный")).to_be_checked()
    expect(selected).to_have_count(2)
    tag_box("Синий").uncheck()
    tag_box("Красный").check()
    page.locator(f'[data-lists-selected="{team}"] li[data-selected-id="{first.id}"] [data-action="pick-remove"]').click()
    expect(selected).to_have_count(1)
    assert submit_record(page) == number
    text = _value(page, tags).inner_text()
    assert "Красный" in text and "Зелёный" in text and "Синий" not in text, text
    people = _value(page, team).inner_text()
    assert second.full_name in people and first.full_name not in people, people


def test_l02_record_form_and_card_have_no_horizontal_scroll_at_360px(
        admin_page, employee, browser, browser_context_args):
    """Сценарий 2 (экран 360 px): форма записи и карточка записи — без горизонтальной прокрутки страницы (NFR-507)."""
    specs = [("model", "Модель", "string", {}), ("price", "Цена", "money", {}), ("note", "Заметка", "text", {}),
             ("bought", "Приобретено", "date", {})]
    list_id, codes = _make_list(admin_page, specs)
    editor = make_list_editor(employee, admin_page, list_id)
    sentence = "Рабочая станция бухгалтерии с большим монитором, клавиатурой и мышью, выдана сотруднику под роспись"
    number = create_record(editor.page, list_id, f"Ноутбук {sentence}", {
        codes["model"]: sentence, codes["price"]: "123456,78", codes["note"]: sentence * 3,
        codes["bought"]: "15.03.2026"})
    for path, hook in ((f"/lists/{list_id}/add/", "add"), (f"/lists/{list_id}/{number}/edit/", "edit"),
                       (f"/lists/{list_id}/{number}/", "record")):
        context, narrow = open_narrow(browser, browser_context_args, editor.page, path, hook)
        try:
            if hook != "record":
                expect(record_form(narrow)).to_be_visible()
            assert page_fits(narrow), f"горизонтальная прокрутка на 360 px: {path}"
        finally:
            context.close()
