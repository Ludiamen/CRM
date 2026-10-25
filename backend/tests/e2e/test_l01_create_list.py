"""T-6140: сценарий 1 — администратор создаёт список, поля разных типов и права (FR-502, FR-503, FR-504, FR-506,
FR-507, FR-508, FR-511, FR-512, FR-513, FR-514, FR-529, FR-542, NFR-507).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md):
- управляющий — администратор круга `admin_page` (роль «Администратор портала» с `lists.manage`); читающие и правящие —
  `helpers_lists.make_list_reader` / `make_list_editor` (своя роль без прав в наборе своего списка); сотрудник без прав
  на списки — сотрудник с новой ролью без прав (`make_list_role`);
- каждый тест заводит свои списки с уникальными названиями (`unique_list_name`) и шесть стартовых не трогает
  (решение 56); общих настроек тесты файла не меняют; сброса стенда и команд стенда в файле нет;
- п. 1 сценария («ни одного списка») приёмка не проходит: стенд всегда со стартовыми списками, его проверяет серверный
  T-6105 (решение 19); здесь кнопка «Создать список» — начало п. 2;
- тексты отказов — литералы раздела 12 контракта.
"""
import re

from playwright.sync_api import expect

from tests.e2e import helpers_lists, helpers_org
from tests.e2e.helpers_lists import (
    add_field, create_list, create_record, field_code_by_name, field_codes, field_form, open_field, open_new_field,
    open_settings, refusal_codes, status_of, try_add_field, try_create_list, unique_list_name, unique_word)

TABS = (("main", "Основное", "settings/"), ("fields", "Поля", "settings/fields/"), ("access", "Права", "settings/access/"))


def _error_at(page, field: str, code: str):
    """Отказ у поля (10.1): `[data-error="<поле>"][data-code="<код>"]`."""
    return page.locator(f'[data-error="{field}"][data-code="{code}"]')


def _alert(page, code: str):
    """Общий отказ (10.1): `[role=alert][data-code="<код>"]`."""
    return page.locator(f'[role=alert][data-code="{code}"]')


def _own_codes(page, list_id) -> list:
    """Коды полей списка без системного «Названия», по порядку сетки полей."""
    return [code for code in field_codes(page, list_id) if code != "title"]


def _row(page, code):
    return page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')


def _control_value(scope, name: str) -> str:
    """Выбранное значение поля `name` внутри `scope`: у `<select>` — значение выбранного пункта, у переключателей —
    отмеченного (пусто, если не отмечен ни один)."""
    control = scope.locator(f'[name="{name}"]')
    if control.count() == 1 and control.evaluate("el => el.tagName") == "SELECT":
        return control.input_value()
    checked = scope.locator(f'[name="{name}"]:checked')
    return checked.first.get_attribute("value") if checked.count() else ""


def _offered_values(scope, name: str) -> set:
    """Предложенные значения поля `name`: пункты `<select>` или значения переключателей (пустой пункт не считается)."""
    control = scope.locator(f'[name="{name}"]')
    if control.count() == 1 and control.evaluate("el => el.tagName") == "SELECT":
        values = control.evaluate("el => Array.from(el.options).map(o => o.value)")
    else:
        values = [box.get_attribute("value") for box in control.all()]
    return {v for v in values if v}


def _clear_choice(scope, name: str) -> None:
    """Оставляет поле выбора `name` пустым: у `<select>` — пункт с пустым значением (если его нет, он добавляется,
    как отправил бы форму обход браузера), у переключателей — снимает отметку со всех."""
    scope.locator(f'[name="{name}"]').first.evaluate(
        "el => { if (el.tagName === 'SELECT') { let o = Array.from(el.options).find(o => o.value === ''); "
        "if (!o) { o = document.createElement('option'); o.value = ''; el.add(o, 0); } el.value = ''; } "
        "else { el.form.querySelectorAll('[name=\"' + el.name + '\"]').forEach(r => { r.checked = false; }); } "
        "el.dispatchEvent(new Event('change', {bubbles: true})); }")


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l01_create_monitors_opens_settings_with_main_fields_rights_tabs_and_system_title_field(admin_page):
    """Сценарий 1, п. 2: «Создать список» на главной, название «Мониторы…» и описание, «Создать» — открыта «Настройка
    списка» с вкладками «Основное», «Поля», «Права»; у списка уже есть системное «Название» без кнопок; список виден
    на главной с описанием (FR-502, FR-503, FR-504)."""
    page = admin_page
    name = unique_list_name("Мониторы")
    description = "Мониторы рабочих мест отдела"
    # п. 2: кнопка «Создать список» на главной ведёт на /lists/new/
    page.goto("/lists/")
    expect(page.locator('[data-lists-page="home"]')).to_be_visible()
    create = page.locator('a[data-action="lists-create"]')
    expect(create).to_be_visible()
    expect(create).to_contain_text("Создать список")
    create.click()
    page.wait_for_url(re.compile(r"/lists/new/$"))
    form = page.locator('[data-lists-page="new"] form:has([name=name])').first
    form.locator("[name=name]").fill(name)
    form.locator("[name=description]").fill(description)
    form.locator("button[type=submit]:not([data-action])").click()
    # п. 2: список создан, открыта «Настройка списка» на вкладке «Основное»
    page.wait_for_url(re.compile(r"/lists/\d+/settings/$"))
    list_id = helpers_lists.list_id_from_url(page.url)
    expect(page.locator('[data-lists-page="settings"]')).to_be_visible()
    expect(page.locator('[data-lists-page="settings"] [name=name]')).to_have_value(name)
    tabs = page.locator("nav[data-lists-tabs]")
    for tab, label, path in TABS:
        link = tabs.locator(f'a[data-tab="{tab}"]')
        expect(link).to_have_count(1)
        expect(link).to_contain_text(label)
        expect(link).to_have_attribute("href", re.compile(rf"/lists/{list_id}/{re.escape(path)}$"))
    expect(tabs.locator('a[data-tab="main"]')).to_have_attribute("aria-current", "page")
    # п. 2: вкладка «Поля» — одно системное поле «Название» без кнопок (FR-504)
    tabs.locator('a[data-tab="fields"]').click()
    page.wait_for_url(re.compile(rf"/lists/{list_id}/settings/fields/$"))
    expect(page.locator('[data-lists-page="fields"]')).to_be_visible()
    expect(page.locator('nav[data-lists-tabs] a[data-tab="fields"]')).to_have_attribute("aria-current", "page")
    rows = page.locator("[data-lists-fields-grid] tr[data-field-code]")
    expect(rows).to_have_count(1)
    title = page.locator('[data-lists-fields-grid] tr[data-field-code="title"][data-system]')
    expect(title).to_have_count(1)
    expect(title.locator('[data-field="name"]')).to_have_text("Название")
    expect(title.locator("button, a[data-action]")).to_have_count(0)
    # п. 2: вкладка «Права» открывается; наборов у нового списка нет (FR-513)
    page.locator('nav[data-lists-tabs] a[data-tab="access"]').click()
    page.wait_for_url(re.compile(rf"/lists/{list_id}/settings/access/$"))
    expect(page.locator('[data-lists-access="read"] li[data-subject]')).to_have_count(0)
    expect(page.locator('[data-lists-access="edit"] li[data-subject]')).to_have_count(0)
    # п. 2: список на главной с названием, описанием и числом записей 0
    page.goto("/lists/")
    row = page.locator(f'li[data-list-id="{list_id}"]')
    expect(row.locator('a[data-field="name"]')).to_have_text(name)
    expect(row.locator('a[data-field="name"]')).to_have_attribute("href", re.compile(rf"/lists/{list_id}/$"))
    expect(row.locator('[data-field="description"]')).to_contain_text(description)
    expect(row.locator('[data-field="count"]')).to_have_text(re.compile(r"^\D*0\D*$"))


def test_l01_name_in_other_case_empty_name_over_100_or_description_over_500_is_refused_with_reason_at_field(
        admin_page):
    """Сценарий 1, п. 3: название другим регистром, пустое, длиннее 100 знаков или описание длиннее 500 — сохранения
    нет, причина у поля; то же при переименовании на вкладке «Основное» (FR-502)."""
    page = admin_page
    name = unique_list_name("Мониторы")
    existing = create_list(page, name, "Описание")
    long_name = "Д" * 101
    # п. 3: название того же списка другим регистром — «Список с таким названием уже есть» у поля name
    assert try_create_list(page, name.lower()) == ""
    expect(_error_at(page, "name", "name_taken")).to_contain_text("Список с таким названием уже есть")
    # п. 3: пустое название — «Обязательное поле» у поля name
    assert try_create_list(page, "") == ""
    expect(_error_at(page, "name", "required")).to_contain_text("Обязательное поле")
    # п. 3: название длиннее 100 знаков — «Предел: 100 знаков» у поля name
    assert try_create_list(page, long_name) == ""
    expect(_error_at(page, "name", "too_long")).to_contain_text("Предел: 100 знаков")
    # п. 3: описание длиннее 500 знаков — «Предел: 500 знаков» у поля description
    over_description = unique_list_name("Мониторы")
    assert try_create_list(page, over_description, "о" * 501) == ""
    expect(_error_at(page, "description", "too_long")).to_contain_text("Предел: 500 знаков")
    # п. 3: сохранения не было — на главной ни одного из отклонённых названий, исходный список один
    names = list(helpers_lists.list_names_on_home(page).values())
    assert long_name not in names and over_description not in names
    assert names.count(name) == 1 and name.lower() not in names
    # п. 3: переименование на «Основном» в название другого списка другим регистром — отказ у поля, имя прежнее
    other = create_list(page, unique_list_name("Мониторы"))
    open_settings(page, other)
    form = page.locator('[data-lists-page="settings"] form:has([name=name])').first
    helpers_lists.lift_limits(form)
    form.locator("[name=name]").fill(name.upper())
    form.locator("button[type=submit]:not([data-action])").click()
    expect(_error_at(page, "name", "name_taken")).to_contain_text("Список с таким названием уже есть")
    names = helpers_lists.list_names_on_home(page)
    assert names[existing] == name and names[other] != name.upper()


def test_l01_six_fields_of_different_types_appear_in_order_added(admin_page):
    """Сценарий 1, п. 4: поля «Диагональ» (число), «Состояние» (список значений, три значения), «Ответственный»
    (сотрудник, несколько), «Гарантия до» (дата, срок 30 и 7 дней), «Стоимость» (деньги, рубль), «Файлы» (файл)
    появляются в порядке добавления с типами и свойствами (FR-506, FR-507, FR-508, FR-529)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Мониторы"))
    plan = (("Диагональ", "number", {}), ("Состояние", "choice", {}), ("Ответственный", "person", {"multiple": True}),
            ("Гарантия до", "date", {"deadline": True, "thresholds": [30, 7]}),
            ("Стоимость", "money", {"currency": "RUB"}), ("Файлы", "file", {}))
    codes = []
    for name, type_code, props in plan:
        # п. 4: поле добавляется формой «Добавить поле»
        codes.append(add_field(page, list_id, name, type_code, **props))
    states = ("Исправен", "В ремонте", "Списан")
    helpers_lists.set_choices(page, list_id, codes[1], states)
    # п. 4: поля в порядке добавления после системного «Названия», с подписью типа
    assert field_codes(page, list_id) == ["title", *codes]
    for (name, type_code, _), code in zip(plan, codes):
        row = _row(page, code)
        expect(row.locator('[data-field="name"]')).to_have_text(name)
        expect(row.locator('[data-field="type"]')).to_contain_text(helpers_lists.TYPE_LABELS[type_code])
    # п. 4: у «Состояния» три значения в заданном порядке (FR-510)
    open_field(page, list_id, codes[1])
    assert helpers_lists.choice_titles(page) == list(states)
    # п. 4: «Ответственный» — несколько значений (FR-508)
    form = open_field(page, list_id, codes[2])
    expect(form.locator('[data-prop="multiple"] input[name="multiple"]')).to_be_checked()
    # п. 4: «Гарантия до» — срок с порогами 30 и 7 дней (FR-529)
    form = open_field(page, list_id, codes[3])
    expect(form.locator('[data-prop="deadline"] input[name="deadline"]')).to_be_checked()
    saved = [box.input_value() for box in form.locator('[data-prop="thresholds"] input[name="thresholds"]').all()]
    assert sorted(int(v) for v in saved if v.strip()) == [7, 30], f"пороги срока: {saved}"
    # п. 4: «Стоимость» — валюта рубль (FR-507)
    form = open_field(page, list_id, codes[4])
    assert _control_value(form.locator('[data-prop="currency"]'), "currency") == "RUB"
    # п. 4: «Файлы» — без «Обязательного» (FR-508)
    form = open_field(page, list_id, codes[5])
    expect(form.locator('[data-prop="required"]')).to_have_count(0)


def test_l01_field_order_changes_by_drag_and_by_arrows(admin_page):
    """Сценарий 1, п. 4: порядок полей меняется перетаскиванием ручки строки (POST `…/fields/order/`) и стрелками
    «вверх» / «вниз»; новый порядок виден после перезагрузки (FR-506)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Мониторы"))
    first, second, third = (add_field(page, list_id, name, "string") for name in ("Модель", "Серийный номер", "Место"))
    assert _own_codes(page, list_id) == [first, second, third]
    # п. 4: перетаскивание последней строки на первую — уходит POST нового порядка
    handle = _row(page, third).locator("[data-lists-drag]")
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(f"/lists/{list_id}/settings/fields/order/")):
        handle.drag_to(_row(page, first))
    dragged = _own_codes(page, list_id)
    assert sorted(dragged) == sorted([first, second, third]) and dragged.index(third) < 2, \
        f"после перетаскивания порядок {dragged}"
    # п. 4: стрелка «вверх» у последней строки меняет её местами с предыдущей
    last = dragged[2]
    with page.expect_navigation():
        _row(page, last).locator('button[data-action="field-up"]').click()
    expected = [dragged[0], dragged[2], dragged[1]]
    assert _own_codes(page, list_id) == expected
    # п. 4: стрелка «вниз» у первой строки меняет её местами со следующей
    with page.expect_navigation():
        _row(page, expected[0]).locator('button[data-action="field-down"]').click()
    assert _own_codes(page, list_id) == [expected[1], expected[0], expected[2]]


def test_l01_duplicate_field_name_or_field_over_50_is_refused_with_reason(admin_page):
    """Сценарий 1, п. 5: название поля, которое уже есть в списке (другим регистром), — отказ у поля; 51-е поле при
    пятидесяти — общий отказ «Не больше 50 полей», поле не добавлено (FR-506)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Мониторы"))
    add_field(page, list_id, "Инвентарный номер", "string")
    # п. 5: то же название другим регистром — «Поле с таким названием уже есть» у поля name
    assert try_add_field(page, list_id, "инвентарный НОМЕР", "string") == ""
    expect(_error_at(page, "name", "field_name_taken")).to_contain_text("Поле с таким названием уже есть")
    assert len(_own_codes(page, list_id)) == 1
    # подготовка: добор до 50 полей прямыми POST формы поля от имени управляющего
    for i in range(2, helpers_lists.FIELDS_LIMIT + 1):
        status = helpers_lists.direct_add_field(page, list_id, f"Поле {i:02d}", "string")
        assert status == 302, f"поле {i} не добавлено: ответ {status}"
    assert len(_own_codes(page, list_id)) == helpers_lists.FIELDS_LIMIT
    # п. 5: 51-е поле формой — общий отказ «Не больше 50 полей»
    assert try_add_field(page, list_id, "Пятьдесят первое", "string") == ""
    expect(_alert(page, "fields_limit")).to_contain_text("Не больше 50 полей")
    assert len(_own_codes(page, list_id)) == helpers_lists.FIELDS_LIMIT


def test_l01_readers_unit_and_editors_role_let_unit_and_subunit_members_and_editing_role_read_list(
        admin_page, employee):
    """Сценарий 1, п. 6: «Читают» — подразделение, «Правят» — роль: список читают сотрудник подразделения, сотрудник
    подчинённого подразделения и сотрудник правящей роли; сотрудник вне наборов списка не видит (FR-513)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Мониторы"))
    unit_name = helpers_org.unique_name("Отдел ИТ")
    unit_id = helpers_org.create_unit(page, unit_name)
    sub_id = helpers_org.create_unit(page, helpers_org.unique_name("Группа поддержки"), parent_id=unit_id)
    _, plain_role = helpers_lists.make_list_role(page)
    editor_role_id, editor_role = helpers_lists.make_list_role(page)
    tag = helpers_org.unique_name("Читатель")
    in_unit = employee(role=plain_role, full_name=f"{tag} Отдел Иванович")
    in_sub = employee(role=plain_role, full_name=f"{tag} Группа Иванович")
    editor = employee(role=editor_role, full_name=helpers_org.unique_name("Правящий"))
    outsider = employee(role=plain_role, full_name=helpers_org.unique_name("Посторонний"))
    for node, account in ((unit_id, in_unit), (sub_id, in_sub)):
        helpers_org.add_members(page, node, [account.id], q=tag)
        helpers_org.open_structure(page, node)
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)  # подготовка удалась: сотрудник в узле
    # п. 6: «Читают» — подразделение подсказкой, «Правят» — роль; наборы сохранены
    helpers_lists.grant_unit(page, list_id, "read", unit_id, unit_name)
    helpers_lists.grant_role(page, list_id, "edit", editor_role_id)
    assert helpers_lists.access_subjects(page, list_id, "read") == [f"unit:{unit_id}"]
    assert helpers_lists.access_subjects(page, list_id, "edit") == [f"role:{editor_role_id}"]
    # п. 6: сотрудник подразделения, сотрудник подчинённого подразделения и правящая роль видят список и открывают его
    for account in (in_unit, in_sub, editor):
        reader_page = account.page
        reader_page.goto("/lists/")
        expect(reader_page.locator(f'li[data-list-id="{list_id}"]')).to_have_count(1)
        reader_page.goto(f"/lists/{list_id}/")
        expect(reader_page.locator('[data-lists-page="grid"]')).to_be_visible()
    # п. 6: читающим через подразделение правка не дана, правящей роли — дана (11.3: «Добавить запись» правящим)
    for account in (in_unit, in_sub):
        expect(account.page.locator('a[data-action="record-add"]')).to_have_count(0)
    expect(editor.page.locator('a[data-action="record-add"]')).to_have_count(1)
    # п. 6: сотрудник вне подразделения и без правящей роли списка не читает — ответ как у несуществующего (FR-514)
    assert status_of(outsider.page, f"/lists/{list_id}/") == 404


def test_l01_delete_empty_list_after_confirm_removes_it_with_journal_entry(admin_page):
    """Сценарий 1, п. 7: у списка без записей «Удалить список» и подтверждение в диалоге — список удалён (нет на
    главной, адрес — 404), в журнале «lists.list_deleted» с названием (FR-503, FR-542)."""
    page = admin_page
    name = unique_list_name("Мониторы")
    list_id = create_list(page, name)
    # п. 7: кнопка доступна у пустого списка, нажатие открывает диалог подтверждения
    open_settings(page, list_id)
    button = page.locator('button[data-action="list-delete"]')
    expect(button).to_be_enabled()
    expect(page.locator("[data-lists-delete-reason]")).to_be_hidden()
    button.click()
    expect(page.locator("dialog[data-lists-confirm]")).to_be_visible()
    # п. 7: подтверждение кнопкой `[data-action="confirm"]` — переход на главную, списка нет
    helpers_lists.confirm_dialog(page)
    page.wait_for_url(re.compile(r"/lists/$"))
    expect(page.locator(f'li[data-list-id="{list_id}"]')).to_have_count(0)
    assert status_of(page, f"/lists/{list_id}/") == 404
    # п. 7: в журнале запись об удалении с названием списка (FR-542)
    rows = helpers_lists.audit_rows(page, "lists.list_deleted", list_id)
    assert len(rows) == 1 and name in rows[0], f"строки журнала: {rows}"


def test_l01_delete_button_unavailable_with_explanation_for_list_with_records_including_archived(admin_page):
    """Сценарий 1, п. 7: у списка с записью и у списка, где единственная запись в архиве, кнопка «Удалить список»
    недоступна с пояснением «Нельзя удалить: есть записи»; прямой POST удаления список не удаляет (FR-503)."""
    page = admin_page
    with_record = create_list(page, unique_list_name("Мониторы"))
    create_record(page, with_record, f"Монитор {unique_word()}")
    with_archived = create_list(page, unique_list_name("Мониторы"))
    number = create_record(page, with_archived, f"Монитор {unique_word()}")
    helpers_lists.archive_record(page, with_archived, number)
    for list_id in (with_record, with_archived):
        # п. 7: кнопка недоступна с пояснением
        assert "Нельзя удалить: есть записи" in helpers_lists.delete_reason(page, list_id)
        # п. 7: обход кнопки прямым POST — отказ, список на месте
        assert helpers_lists.post_status(page, f"/lists/{list_id}/delete/") != 302
        assert status_of(page, f"/lists/{list_id}/") == 200


def test_l01_employee_without_manage_right_sees_no_create_or_settings_buttons_and_direct_links_are_denied(
        admin_page, employee):
    """Сценарий 1, п. 8: сотрудник без «Управления списками» не видит «Создать список» и ссылки на настройку;
    «Создать список» и «Настройка списка» по прямой ссылке — отказ по таблице 10.4 (FR-512, FR-514)."""
    page = admin_page
    name = unique_list_name("Мониторы")
    list_id = create_list(page, name)
    staff = employee()                                            # «Сотрудник ИТ»: читает стартовые списки
    reader = helpers_lists.make_list_reader(employee, page, list_id)  # читает только этот список
    # п. 8: управляющему кнопка «Создать список» и ссылки на настройку показаны (контроль для отказа ниже, 15.4 п. 3)
    page.goto("/lists/")
    expect(page.locator('a[data-action="lists-create"]')).to_be_visible()
    expect(page.locator(f'li[data-list-id="{list_id}"] a[data-action="list-settings"]')).to_have_count(1)
    page.goto(f"/lists/{list_id}/")
    expect(page.locator('[data-lists-page="grid"]')).to_be_visible()
    expect(page.locator('a[data-action="list-settings"]')).to_have_count(1)
    strays = []
    for account in (staff, reader):
        own = account.page
        # п. 8: кнопок «Создать список» и настройки нет
        own.goto("/lists/")
        expect(own.locator('[data-lists-page="home"]')).to_be_visible()
        expect(own.locator('a[data-action="lists-create"]')).to_have_count(0)
        expect(own.locator('a[data-action="list-settings"]')).to_have_count(0)
        # п. 8: «Создать список» по прямой ссылке — 403 (раздел открыт, действие нет), POST ничего не создаёт
        assert status_of(own, "/lists/new/") == 403
        strays.append(unique_list_name("Мониторы"))
        assert helpers_lists.post_status(own, "/lists/new/", {"name": strays[-1], "description": ""}) == 403
    # п. 8: читающий список не видит ссылки на его настройку; прямые ссылки на вкладки и POST — 403
    reader.page.goto(f"/lists/{list_id}/")
    expect(reader.page.locator('[data-lists-page="grid"]')).to_be_visible()
    expect(reader.page.locator('a[data-action="list-settings"]')).to_have_count(0)
    for path in ("settings/", "settings/fields/", "settings/access/", "settings/fields/new/"):
        assert status_of(reader.page, f"/lists/{list_id}/{path}") == 403, path
    assert helpers_lists.post_status(reader.page, f"/lists/{list_id}/settings/", {"name": "Чужое", "description": ""}) == 403
    assert helpers_lists.post_status(reader.page, f"/lists/{list_id}/delete/") == 403
    # п. 8: сотрудник ИТ, который этот список не читает, получает по прямой ссылке ответ как у несуществующего
    assert status_of(staff.page, f"/lists/{list_id}/settings/") == 404
    # п. 8: ничего не изменилось — список с прежним названием, отклонённых списков нет
    names = helpers_lists.list_names_on_home(page)
    assert names.get(list_id) == name
    assert not set(strays) & set(names.values()), "список создан сотрудником без права управления"


def test_l01_money_field_offers_rouble_by_default_dollar_and_euro(admin_page):
    """Сценарий 1, п. 9: у поля «деньги» валюта — рубль по умолчанию, доллар и евро; выбранная валюта сохраняется
    (FR-507)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Мониторы"))
    # п. 9: в форме нового поля «деньги» предложены RUB, USD, EUR, выбран RUB
    open_new_field(page, list_id)
    helpers_lists.choose_type(page, "money")
    currency = field_form(page).locator('[data-prop="currency"]')
    assert _offered_values(currency, "currency") == set(helpers_lists.CURRENCIES)
    assert _control_value(currency, "currency") == "RUB"
    # п. 9: поле без выбора валюты сохраняется с рублём, выбранные доллар и евро — с ними
    plain = add_field(page, list_id, "Стоимость", "money")
    dollar = add_field(page, list_id, "Стоимость в долларах", "money", currency="USD")
    euro = add_field(page, list_id, "Стоимость в евро", "money", currency="EUR")
    for code, expected in ((plain, "RUB"), (dollar, "USD"), (euro, "EUR")):
        form = open_field(page, list_id, code)
        assert _control_value(form.locator('[data-prop="currency"]'), "currency") == expected, code


def test_l01_record_field_requires_choosing_target_list(admin_page):
    """Сценарий 1, п. 9: поле «запись другого списка» без выбранного списка не сохраняется — «Выберите список» у
    поля target; с выбранным списком сохраняется и помнит его (FR-511)."""
    page = admin_page
    target_id = create_list(page, unique_list_name("Рабочие места"))
    list_id = create_list(page, unique_list_name("Мониторы"))
    # п. 9: выбор списка предлагает свой список-цель
    open_new_field(page, list_id)
    helpers_lists.choose_type(page, "record")
    target = field_form(page).locator('[data-prop="target"]')
    assert target_id in _offered_values(target, "target")
    # п. 9: без выбранного списка — отказ у поля target, поле не создано
    _clear_choice(target, "target")
    helpers_lists.fill_field_form(page, name="Рабочее место")
    assert helpers_lists.submit_field_form(page, list_id) is False
    expect(_error_at(page, "target", "target_required")).to_contain_text("Выберите список")
    assert ("target", "target_required") in refusal_codes(page)
    assert _own_codes(page, list_id) == []
    # п. 9: с выбранным списком поле сохраняется и помнит цель
    code = add_field(page, list_id, "Рабочее место", "record", target=target_id)
    assert field_code_by_name(page, list_id, "Рабочее место") == code
    form = open_field(page, list_id, code)
    assert _control_value(form.locator('[data-prop="target"]'), "target") == target_id


def test_l01_home_and_settings_have_no_horizontal_scroll_at_360px_and_fields_table_scrolls_inside_block(
        browser, browser_context_args, admin_page):
    """Сценарий 1, п. 10: на 360 px у главной и вкладок «Настройки списка» нет горизонтальной прокрутки страницы, а
    широкая таблица полей прокручивается внутри своего блока `.lists-scroll` (NFR-507)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Мониторы"), "Мониторы рабочих мест отдела")
    # подготовка: поле с длинным названием одним словом, чтобы таблица полей была шире 360 px
    add_field(page, list_id, "Серийный" + "номер" * 18, "string")
    add_field(page, list_id, "Гарантия до", "date", deadline=True, thresholds=[30, 7])
    context = helpers_lists.narrow_context(browser, browser_context_args, page)
    try:
        narrow = context.new_page()
        # п. 10: главная и вкладки настройки — без горизонтальной прокрутки
        for path, hook in (("/lists/", "home"), (f"/lists/{list_id}/settings/", "settings"),
                           (f"/lists/{list_id}/settings/fields/", "fields"),
                           (f"/lists/{list_id}/settings/access/", "access")):
            narrow.goto(path)
            expect(narrow.locator(f'[data-lists-page="{hook}"]')).to_be_visible()
            assert helpers_lists.page_fits(narrow), f"горизонтальная прокрутка на {path}"
        # п. 10: таблица полей прокручивается внутри блока
        narrow.goto(f"/lists/{list_id}/settings/fields/")
        block = narrow.locator(".lists-scroll:has([data-lists-fields-grid]), .lists-scroll[data-lists-fields-grid]")
        expect(block).to_have_count(1)
        assert helpers_lists.scrolls_inside(block), "таблица полей не прокручивается внутри блока"
        assert helpers_lists.page_fits(narrow)
    finally:
        context.close()
