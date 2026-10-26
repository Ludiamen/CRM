"""T-6152: сценарий 13 — права: кто видит и правит, сотрудник без прав, стартовые права (FR-501, FR-505, FR-512,
FR-513, FR-514, FR-525, FR-527, FR-528, FR-540, FR-545).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md разделы 10, 11, 12, 15.4):
- управляющий — администратор круга `admin_page` («Администратор портала», `lists.manage`); читающие и правящие —
  `helpers_lists.make_list_reader` / `make_list_editor` (своя роль без прав в наборе своего списка); сотрудник без прав
  на списки — сотрудник с новой ролью без прав (`make_list_role`); где нужно открыть карточку коллеги, у роли читающего
  право «Просмотр сотрудников и структуры» (`staff.view`, срез 002) — `_role_with`;
- стартовые списки тест только читает; исключение — тест 5 (по его имени администратор выдаёт роли «Руководитель» чтение
  списка «Договоры» в интерфейсе): выдача снимается в `finally` и снятие проверяется; общих настроек файл больше не
  меняет; тест 15 меняет права только своей новой роли;
- каждый тест заводит свои списки, записи и людей с уникальными названиями; сброса стенда и `stand_shell` в файле нет;
  вне интерфейса — только `helpers_sd.deliver` (письмо заявки в тесте 14);
- пункт «после обновления портала» (п. 1) — серверный T-6105 (решение 19 задач), в приёмке его нет;
- 404 «как у несуществующего» сравнивается в пределах одного клиента (раздел 10.1, К-10): статус и текст области
  содержимого `main#content` без всплывающих сообщений `.alert`, каждый раз после нейтральной страницы `/me/` (15.5 п. 11).
"""
import io
import zipfile
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_lists, helpers_org, helpers_sd
from tests.e2e.helpers_lists import (
    access_subjects, add_field, attach_file, create_list, create_record, grant_role, grant_unit, link_ticket,
    list_names_on_home, make_list_editor, make_list_manager, make_list_reader, make_list_role, open_access,
    open_add_record, open_edit_record, open_field, open_record, pick, post_status, status_of, submit_record,
    unique_list_name, unique_word, wait_file_clean)

LISTS_MANAGE = "lists.manage"
MANAGE_TITLE = "Управление списками"        # подпись права в «Роли и права» (спека, сценарий 13, п. 1)
HEAD_ROLE = helpers.DEFAULT_ROLES[1]         # «Руководитель»
MISSING = 2_000_000_000                      # номера, которого на стенде нет
STARTER_NAMES = ("Оборудование", "Лицензии", "Картриджи и расходники", "Сертификаты ЭП", "Договоры",
                 "SIM-карты и телефоны")
HINT_LICENSE = "Ключи активации здесь не храните: секреты хранятся вне портала"
KIND_EQUIPMENT = ["Компьютер", "Ноутбук", "Монитор", "Принтер/МФУ", "Сетевое оборудование", "Телефон", "Прочее"]

# Стартовые списки (CONTRACT-006, 2.4; SPEC-006 FR-505): название → поля `(код, название, тип, свойства)`. Свойства:
# `unique`, `multiple`, `deadline` (пороги по убыванию), `choices`, `currency`, `target` (название списка), `hint`.
STARTERS = {
    "Оборудование": [
        ("kind", "Вид", "Список значений", {"choices": KIND_EQUIPMENT}),
        ("inventory_number", "Инвентарный номер", "Строка", {"unique": True}),
        ("serial_number", "Серийный номер", "Строка", {"unique": True}),
        ("model", "Модель", "Строка", {}),
        ("state", "Состояние", "Список значений", {"choices": ["В работе", "На складе", "В ремонте"]}),
        ("assignee", "За кем закреплено", "Сотрудник", {}),
        ("unit", "Подразделение", "Подразделение", {}),
        ("place", "Место", "Строка", {}),
        ("purchased", "Дата покупки", "Дата", {}),
        ("warranty", "Гарантия до", "Дата", {"deadline": ["30"]}),
        ("cost", "Стоимость", "Деньги", {"currency": "RUB"}),
        ("note", "Примечание", "Многострочный текст", {}),
        ("files", "Файлы", "Файл", {"multiple": True}),
    ],
    "Лицензии": [
        ("product", "Продукт", "Строка", {}),
        ("kind", "Вид", "Список значений", {"choices": ["Бессрочная", "Подписка"]}),
        ("seats", "Количество мест", "Число", {}),
        ("license_number", "Номер лицензии или договора", "Строка", {"hint": HINT_LICENSE}),
        ("valid_until", "Действует до", "Дата", {"deadline": ["30", "7"]}),
        ("installed_on", "Установлена на", "Запись другого списка", {"multiple": True, "target": "Оборудование"}),
        ("owner", "Ответственный", "Сотрудник", {}),
        ("cost", "Стоимость", "Деньги", {"currency": "RUB"}),
        ("files", "Файлы", "Файл", {"multiple": True}),
    ],
    "Картриджи и расходники": [
        ("kind", "Вид", "Список значений", {"choices": ["Картридж", "Тонер", "Барабан", "Прочее"]}),
        ("model", "Модель", "Строка", {}),
        ("printers", "Для принтера", "Запись другого списка", {"multiple": True, "target": "Оборудование"}),
        ("stock", "Количество на складе", "Число", {}),
        ("note", "Примечание", "Многострочный текст", {}),
    ],
    "Сертификаты ЭП": [
        ("holder", "Владелец", "Сотрудник", {}),
        ("issuer", "Удостоверяющий центр", "Строка", {}),
        ("serial_number", "Серийный номер", "Строка", {"unique": True}),
        ("medium", "Носитель", "Список значений", {"choices": ["Токен", "Реестр", "Облако"]}),
        ("valid_until", "Действует до", "Дата", {"deadline": ["30", "7"]}),
        ("files", "Файлы", "Файл", {"multiple": True}),
    ],
    "Договоры": [
        ("counterparty", "Контрагент", "Строка", {}),
        ("contract_number", "Номер договора", "Строка", {"unique": True}),
        ("subject", "Предмет", "Многострочный текст", {}),
        ("signed", "Дата заключения", "Дата", {}),
        ("valid_until", "Действует до", "Дата", {"deadline": ["30"]}),
        ("amount", "Сумма", "Деньги", {"currency": "RUB"}),
        ("owner", "Ответственный", "Сотрудник", {}),
        ("files", "Файлы", "Файл", {"multiple": True}),
    ],
    "SIM-карты и телефоны": [
        ("phone", "Номер телефона", "Строка", {"unique": True}),
        ("operator", "Оператор", "Список значений", {"choices": []}),
        ("tariff", "Тариф", "Строка", {}),
        ("assignee", "За кем закреплено", "Сотрудник", {}),
        ("device", "Устройство", "Запись другого списка", {"target": "Оборудование"}),
        ("iccid", "ICCID", "Строка", {}),
        ("note", "Примечание", "Многострочный текст", {}),
    ],
}


# --- Помощники файла -------------------------------------------------------------------------------------------

def _role_page(page, role_name: str):
    """Страница роли `/roles/<id>/` (срез 001); возвращает `(номер роли, локатор формы роли)`."""
    role_id = helpers_org.role_id(page, role_name)
    page.goto(f"/roles/{role_id}/")
    form = page.locator(f'form[action="/roles/{role_id}/"]')
    expect(form).to_be_visible()
    return role_id, form


def _right(form, code: str):
    return form.locator(f'input[name=permissions][value="{code}"]')


def _role_with(admin_page, permissions) -> tuple:
    """Новая роль с правами `permissions` (коды) формой `/roles/new/`; возвращает `(номер, название)`."""
    name = helpers_org.unique_name("Роль списков")
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    for code in permissions:
        form.locator(f'input[name=permissions][value="{code}"]').check()
    with admin_page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    admin_page.wait_for_load_state()
    return helpers_org.role_id(admin_page, name), name


def _starter_ids(page) -> dict:
    """Номера шести стартовых списков по названию (главная управляющего); каждого из шести должно быть по одному."""
    by_name = {}
    for list_id, name in list_names_on_home(page).items():
        by_name.setdefault(name, []).append(list_id)
    ids = {}
    for name in STARTER_NAMES:
        assert len(by_name.get(name, [])) == 1, f"стартовых списков «{name}» на главной: {len(by_name.get(name, []))}"
        ids[name] = by_name[name][0]
    return ids


def _revoke_subject(page, list_id, level: str, subject: str) -> None:
    """Снимает строку `subject` (`role:<id>`) из набора `level` вкладки «Права» и сохраняет форму; проверяет после
    перезагрузки (управляющий)."""
    open_access(page, list_id)
    block = page.locator(f'[data-lists-access="{level}"]')
    row = block.locator(f'li[data-subject="{subject}"]')
    expect(row).to_have_count(1)
    row.locator('button[data-action="access-remove"]').click()
    expect(row).to_have_count(0)
    form = page.locator('form:has([data-lists-access="read"])').first
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(f"/lists/{list_id}/settings/access/")):
        form.locator("button[type=submit]:not([data-action])").click()
    page.wait_for_load_state()
    open_access(page, list_id)
    expect(page.locator(f'[data-lists-access="{level}"] li[data-subject="{subject}"]')).to_have_count(0)


_CONTENT_TEXT_JS = ("el => { const c = el.cloneNode(true); c.querySelectorAll('.alert').forEach(a => a.remove());"
                    " return c.textContent.replace(/\\s+/g, ' ').trim(); }")


def _content_text(page, path: str):
    """Открывает нейтральную страницу `/me/` (забирает ожидающие всплывающие сообщения), затем `path`; возвращает
    ответ и текст области содержимого `main#content` без `.alert` (CONTRACT-006, 15.5 п. 11)."""
    page.goto("/me/")
    response = page.goto(path)
    return response, page.locator("main#content").evaluate(_CONTENT_TEXT_JS)


def _same_404(page, real: str, missing: str) -> None:
    """Адрес `real` отвечает так же, как несуществующий `missing`: 404 и тот же текст области содержимого без
    всплывающих сообщений (один клиент, К-10; 15.5 п. 11 — меню и счётчики оболочки не сравниваются)."""
    got, real_text = _content_text(page, real)
    other, other_text = _content_text(page, missing)
    assert got.status == 404, f"{real}: ответ {got.status}, нужен 404"
    assert other.status == 404, f"{missing}: ответ {other.status}, нужен 404"
    assert other_text == real_text, f"{real} отвечает не так, как несуществующий {missing}"


def _record_with_picks(page, list_id, title: str, picks: dict | None = None) -> int:
    """Запись формой `/lists/<id>/add/`: «Название» и выбор в полях-подсказках (`picks`: код → слово запроса)."""
    open_add_record(page, list_id)
    helpers_lists.fill_record(page, {"title": title})
    for code, query in (picks or {}).items():
        pick(page, code, query)
    number = submit_record(page)
    assert number, f"запись «{title}» не создана: {helpers_lists.refusal_codes(page)}"
    return number


def _dismiss_employee(page, user_id: str) -> None:
    """Увольняет сотрудника из его карточки (срез 002); ждёт отметку «уволен»."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _selected(scope, name: str) -> str:
    """Выбранное значение поля `name` в `scope`: у `<select>` — значение пункта, у переключателей — отмеченного."""
    control = scope.locator(f'[name="{name}"]')
    if control.count() == 1 and control.evaluate("el => el.tagName") == "SELECT":
        return control.input_value()
    checked = scope.locator(f'[name="{name}"]:checked')
    return checked.first.get_attribute("value") if checked.count() else ""


def _ticket(admin_page) -> tuple:
    """Заявка корпоративного заявителя по письму (как в `test_k11`); возвращает `(номер, очередь по умолчанию)`."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    word = unique_word("tk")
    msg = MIMEText(f"Описание сбоя {word}", "plain", "utf-8")
    msg["From"] = helpers_sd.requester_email()
    msg["To"] = helpers_sd.MAILBOX
    msg["Subject"] = Header(f"Права списков {word}", "utf-8")
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain="client.test")
    helpers_sd.deliver(msg.as_bytes())
    return helpers_sd.ticket_number_by_subject(admin_page, word), queue_id


def _xlsx_text(response) -> str:
    """Весь текст частей XLSX (`xl/…xml`) ответа выгрузки одной строкой."""
    with zipfile.ZipFile(io.BytesIO(response.body())) as book:
        return " ".join(book.read(name).decode("utf-8", "replace") for name in book.namelist()
                        if name.startswith("xl/") and name.endswith(".xml"))


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_l13_role_rights_page_after_install_shows_manage_lists_at_portal_admin_and_not_at_head(admin_page):
    """Сценарий 13, п. 1: на странице прав ролей право «Управление списками» отмечено у «Администратор портала» и не
    отмечено у «Сотрудник ИТ» и «Руководитель» (FR-512, FR-545)."""
    page = admin_page
    expected = {helpers.ADMIN_ROLE: True, helpers.STAFF_ROLE: False, HEAD_ROLE: False}
    for role_name, manages in expected.items():
        # п. 1: администратор открывает права роли
        _, form = _role_page(page, role_name)
        # право названо своей подписью, одно на странице роли
        expect(form.get_by_label(MANAGE_TITLE, exact=True)).to_have_count(1)
        expect(_right(form, LISTS_MANAGE)).to_have_count(1)
        # п. 1: отмечено только у администратора портала
        expect(_right(form, LISTS_MANAGE)).to_be_checked(checked=manages)


def test_l13_rights_tab_of_six_starter_lists_gives_read_and_edit_to_it_staff_and_none_to_head(admin_page):
    """Сценарий 13, п. 1–2: на вкладке «Права» каждого из шести стартовых списков роль «Сотрудник ИТ» стоит и в «Читают»,
    и в «Правят», а «Руководитель» — ни там, ни там (FR-513, FR-545)."""
    page = admin_page
    # п. 2: администратор открывает «Списки»; номера шести списков
    ids = _starter_ids(page)
    it_id = helpers_org.role_id(page, helpers.STAFF_ROLE)
    head_id = helpers_org.role_id(page, HEAD_ROLE)
    for name, list_id in ids.items():
        for level in ("read", "edit"):
            # п. 1–2: права чтения и правки списка
            subjects = access_subjects(page, list_id, level)
            assert f"role:{it_id}" in subjects, f"«{name}»: у «Сотрудник ИТ» нет прав набора {level}: {subjects}"
            assert f"role:{head_id}" not in subjects, f"«{name}»: «Руководитель» в наборе {level}: {subjects}"


def test_l13_lists_home_after_install_shows_six_starter_lists_by_name(admin_page, employee):
    """Сценарий 13, п. 2: после установки на главной «Списки» шесть списков с названиями из спеки; у сотрудника ИТ они
    тоже видны, но без кнопки «Создать список» (FR-505, FR-545)."""
    page = admin_page
    # п. 2: администратор открывает «Списки»
    names = list(list_names_on_home(page).values())
    for name in STARTER_NAMES:
        assert names.count(name) == 1, f"список «{name}» на главной: {names.count(name)} раз"
    for list_id, name in list_names_on_home(page).items():
        if name in STARTER_NAMES:
            link = page.locator(f'li[data-list-id="{list_id}"] a[data-field="name"]')
            expect(link).to_have_attribute("href", f"/lists/{list_id}/")
            expect(page.locator(f'li[data-list-id="{list_id}"] [data-field="count"]')).to_be_visible()
    expect(page.locator('a[data-action="lists-create"]').first).to_be_visible()
    # п. 1–2: сотрудник ИТ видит те же шесть списков (права роли из данных установки), создавать их не может
    staff = employee()
    seen = list(list_names_on_home(staff.page).values())
    for name in STARTER_NAMES:
        assert name in seen, f"«Сотрудник ИТ» не видит стартовый список «{name}»"
    expect(staff.page.locator('a[data-action="lists-create"]')).to_have_count(0)
    assert status_of(staff.page, "/lists/new/") == 403


def test_l13_starter_lists_fields_tabs_show_types_choices_unique_and_deadline_thresholds_of_install_table(admin_page):
    """Сценарий 13, п. 2: вкладки «Поля» шести стартовых списков показывают поля из таблицы установки — порядок, названия,
    типы, значения списков значений, уникальность, срок с порогами, валюту, целевой список и подсказку (FR-505)."""
    page = admin_page
    ids = _starter_ids(page)
    for list_name, fields in STARTERS.items():
        list_id = ids[list_name]
        # п. 2: вкладка «Поля» — коды по порядку, «Название» системное первым
        codes = helpers_lists.field_codes(page, list_id)
        assert codes == ["title"] + [code for code, _, _, _ in fields], f"«{list_name}»: поля {codes}"
        expect(page.locator('tr[data-field-code="title"][data-system]')).to_have_count(1)
        for code, name, type_label, _ in fields:
            row = page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')
            # содержание ячейки контракт не задаёт точно (рядом могут быть пометки; R-1-E3, находка 3)
            expect(row.locator('[data-field="name"]')).to_contain_text(name)
            expect(row.locator('[data-field="type"]')).to_contain_text(type_label)
        # п. 2: свойства — на странице каждого поля, у которого они есть
        for code, name, type_label, props in fields:
            if not props:
                continue
            form = open_field(page, list_id, code)
            where = f"«{list_name}» / «{name}»"
            if "unique" in props:
                expect(form.locator('[data-prop="unique"] input[name="unique"]')).to_be_checked()
            if "multiple" in props:
                expect(form.locator('[data-prop="multiple"] input[name="multiple"]')).to_be_checked()
            if "deadline" in props:
                expect(form.locator('[data-prop="deadline"] input[name="deadline"]')).to_be_checked()
                boxes = form.locator('[data-prop="thresholds"] input[name="thresholds"]')
                shown = [box.input_value().strip() for box in boxes.all() if box.input_value().strip()]
                assert shown == props["deadline"], f"{where}: пороги {shown}, нужны {props['deadline']}"
            if "choices" in props:
                assert helpers_lists.choice_titles(page) == props["choices"], f"{where}: значения списка"
            if "currency" in props:
                assert _selected(form.locator('[data-prop="currency"]'), "currency") == props["currency"], where
            if "target" in props:
                got = _selected(form.locator('[data-prop="target"]'), "target")
                assert got == ids[props["target"]], f"{where}: целевой список {got}, нужен «{props['target']}»"
            if "hint" in props:
                assert form.locator("[name=hint]").input_value() == props["hint"], f"{where}: подсказка"


def test_l13_head_granted_read_of_contracts_in_interface_sees_only_that_list_without_edit(admin_page, employee):
    """Сценарий 13, п. 3: администратор выдал роли «Руководитель» чтение списка «Договоры» в интерфейсе; руководитель
    открывает «Списки» и видит только этот список, без кнопок правки и настройки; после снятия выдачи раздела у него
    снова нет (FR-513)."""
    page = admin_page
    ids = _starter_ids(page)
    contracts = ids["Договоры"]
    head_id = helpers_org.role_id(page, HEAD_ROLE)
    head = employee(role=HEAD_ROLE)
    # до выдачи у руководителя раздела нет
    assert status_of(head.page, "/lists/") == 404
    try:
        # п. 3: администратор выдаёт чтение в интерфейсе («Читают» списка «Договоры»)
        grant_role(page, contracts, "read", head_id)
        # п. 3: руководитель открывает «Списки» — «Договоры» есть, других стартовых списков нет (точное равенство
        # набора хрупко к остаткам упавшего прогона в общей базе круга, решение 56; 15.5, строка 63)
        names = list_names_on_home(head.page)
        assert names.get(contracts) == "Договоры", f"у руководителя нет «Договоров»: {names}"
        others = {name for name, list_id in ids.items() if name != "Договоры" and list_id in names}
        assert not others, f"руководитель видит чужие стартовые списки: {others}"
        expect(head.page.locator('#main-menu a[href="/lists/"]')).to_have_count(1)
        # список читает: таблица открыта, выгрузка есть; правки и настройки нет
        response = head.page.goto(f"/lists/{contracts}/")
        assert response.status == 200
        expect(head.page.locator('[data-lists-page="grid"]')).to_be_visible()
        expect(head.page.locator('a[data-action="export"]').first).to_be_visible()
        for hook in ('a[data-action="record-add"]', 'a[data-action="import"]', 'a[data-action="list-settings"]',
                     'button[data-action="bulk-archive"]', 'a[data-action="lists-create"]'):
            expect(head.page.locator(hook)).to_have_count(0)
        assert status_of(head.page, f"/lists/{contracts}/add/") == 403
        assert status_of(head.page, f"/lists/{contracts}/settings/") == 403
        # остальные пять списков он не читает: ответ как у несуществующего
        for name, list_id in ids.items():
            if name != "Договоры":
                assert status_of(head.page, f"/lists/{list_id}/") == 404, f"руководитель открыл «{name}»"
    finally:
        if f"role:{head_id}" in access_subjects(page, contracts, "read"):
            _revoke_subject(page, contracts, "read", f"role:{head_id}")
    # выдача снята: на следующем запросе раздела и списка нет
    assert status_of(head.page, "/lists/") == 404
    assert status_of(head.page, f"/lists/{contracts}/") == 404
    # меню перечитывается с новой страницы: живого обновления меню контракт не обещает (R-1-E3, находка 1)
    head.page.goto("/me/")
    expect(head.page.locator("#main-menu")).to_be_visible()
    expect(head.page.locator('#main-menu a[href="/lists/"]')).to_have_count(0)


def test_l13_employee_without_lists_has_no_menu_item_and_lists_url_gives_not_found(admin_page, employee):
    """Сценарий 13, п. 4: сотрудник, который не читает ни одного списка и не управляет списками, в левом меню раздела
    «Списки» не видит; прямая ссылка отвечает как несуществующая страница (FR-501, FR-514)."""
    stranger = employee(role=make_list_role(admin_page)[1])
    page = stranger.page
    ids = _starter_ids(admin_page)
    # п. 4: смотрит левое меню — раздела нет (у управляющего он есть)
    page.goto("/me/")
    expect(page.locator("#main-menu")).to_be_visible()
    expect(page.locator('#main-menu a[href="/lists/"]')).to_have_count(0)
    admin_page.goto("/me/")
    expect(admin_page.locator('#main-menu a[href="/lists/"]')).to_have_count(1)
    # п. 4: прямая ссылка — как у несуществующей страницы
    _same_404(page, "/lists/", f"/{unique_word('nolist')}/")
    _same_404(page, f"/lists/{ids['Договоры']}/", f"/lists/{MISSING}/")
    _same_404(page, "/lists/new/", f"/lists/{MISSING}/new/")
    for path in ("/lists/people/", "/lists/units/"):
        assert status_of(page, path) == 404, path


def test_l13_non_reader_gets_not_found_for_list_record_history_file_export_and_label_urls(admin_page, employee):
    """Сценарий 13, п. 5: список с записью и файлом, сотрудник без права его читать (и без прав вообще, и читающий другой
    список) открывает адреса списка, записи, истории, файла, выгрузки и этикетки — везде 404, как у несуществующего;
    читающему те же адреса отвечают 200 (FR-514)."""
    page = admin_page
    title = f"Договор {unique_word()}"
    list_id = create_list(page, unique_list_name("Договоры"))
    file_code = add_field(page, list_id, "Файл договора", "file")
    number = create_record(page, list_id, title)
    file_id, _ = attach_file(page, list_id, number, file_code, b"plain text\n", "contract.txt", mime="text/plain")
    assert wait_file_clean(page, list_id, number, file_id) == "clean"
    reader = make_list_reader(employee, page, list_id)
    other_id = create_list(page, unique_list_name("Другой"))
    other_reader = make_list_reader(employee, page, other_id)
    no_rights = employee(role=make_list_role(page)[1])
    paths = [f"/lists/{list_id}/", f"/lists/{list_id}/{number}/", f"/lists/{list_id}/{number}/history/",
             f"/lists/{list_id}/{number}/files/{file_id}/", f"/lists/{list_id}/export/",
             f"/lists/{list_id}/{number}/label/", f"/lists/{list_id}/labels/?n={number}"]
    # положительный контроль: читающий получает все адреса
    for path in paths:
        assert status_of(reader.page, path) == 200, f"читающий: {path}"
    # п. 5: не читающий открывает те же адреса — 404 и ни одного данных объекта в теле
    for who, account in (("без прав", no_rights), ("читает другой список", other_reader)):
        for path in paths:
            response = helpers_org.direct_get(account.page, path)
            assert response.status == 404, f"{who}: {path} → {response.status}"
            body = response.text()
            assert title not in body and "contract.txt" not in body, f"{who}: в ответе 404 данные записи: {path}"
        # ответ — тот же, что у несуществующего объекта (один клиент)
        _same_404(account.page, paths[1], f"/lists/{MISSING}/{number}/")
        _same_404(account.page, paths[0], f"/lists/{MISSING}/")


def test_l13_editor_role_reads_list_and_saves_record(admin_page, employee):
    """Сценарий 13, п. 6: правящий (роль в наборе «Правят») открывает список, читает его и сохраняет запись — создаёт и
    правит; настройки списка ему закрыты (FR-513)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Правка"))
    code = add_field(page, list_id, "Номер", "string")
    editor = make_list_editor(employee, page, list_id)
    ep = editor.page
    title, changed = f"Запись {unique_word()}", f"Правка {unique_word()}"
    # п. 6: правящий открывает список — читает таблицу и видит кнопки правки
    assert ep.goto(f"/lists/{list_id}/").status == 200
    expect(ep.locator('[data-lists-page="grid"]')).to_be_visible()
    expect(ep.locator('a[data-action="record-add"]').first).to_be_visible()
    expect(ep.locator('a[data-action="import"]').first).to_be_visible()
    expect(ep.locator('a[data-action="list-settings"]')).to_have_count(0)
    # п. 6: сохраняет запись
    number = create_record(ep, list_id, title, {code: "A-1"})
    expect(ep.locator(f'[data-lists-value="{code}"]')).to_have_text("A-1")
    ep.goto(f"/lists/{list_id}/")
    expect(ep.locator(f'tr[data-record-number="{number}"] a[data-field="title"]')).to_have_text(title)
    # п. 6: правит ту же запись
    open_edit_record(ep, list_id, number)
    helpers_lists.fill_record(ep, {"title": changed})
    assert submit_record(ep) == number
    expect(ep.locator("[data-lists-record]")).to_contain_text(changed)
    # запись с правкой видна и управляющему
    open_record(page, list_id, number)
    expect(page.locator("[data-lists-record]")).to_contain_text(changed)
    # настройка списка правящему закрыта (403: раздел открыт, действие нет)
    assert status_of(ep, f"/lists/{list_id}/settings/") == 403


def test_l13_unit_grant_gives_read_to_subunit_member_and_transfer_to_other_unit_removes_access(admin_page, employee):
    """Сценарий 13, п. 7: право «Читают» выдано подразделению; сотрудник подчинённого подразделения открывает список и
    читает его; после перевода в другое подразделение (вне выданного) доступ пропадает (FR-513)."""
    page = admin_page
    word = unique_word("ed")
    unit, subunit, other = (helpers_org.unique_name(prefix) for prefix in ("Отдел", "Группа", "Прочий"))
    unit_id = helpers_org.create_unit(page, unit)
    subunit_id = helpers_org.create_unit(page, subunit, parent_id=unit_id)
    other_id = helpers_org.create_unit(page, other)
    list_id = create_list(page, unique_list_name("Подразделение"))
    member = employee(role=make_list_role(page)[1], full_name=f"Сидоров {word}")
    helpers_org.add_members(page, subunit_id, [member.id], q=word)
    helpers_org.open_structure(page, subunit_id)
    expect(helpers_org.member_row(page, member.id)).to_have_count(1)
    # до выдачи права сотрудник списка не видит
    assert status_of(member.page, f"/lists/{list_id}/") == 404
    # п. 7: право выдано подразделению (родитель подразделения сотрудника)
    grant_unit(page, list_id, "read", unit_id, unit)
    assert f"unit:{unit_id}" in access_subjects(page, list_id, "read")
    # п. 7: сотрудник подчинённого подразделения открывает список — читает
    assert member.page.goto(f"/lists/{list_id}/").status == 200
    expect(member.page.locator('[data-lists-page="grid"]')).to_be_visible()
    assert list(list_names_on_home(member.page)) == [list_id]
    assert status_of(member.page, f"/lists/{list_id}/add/") == 403
    # п. 7: переведён в другое подразделение — доступ теряет
    helpers_org.open_structure(page, subunit_id)
    helpers_org.transfer_member(page, member.id, other_id)
    page.goto(f"/structure/{other_id}/")
    expect(helpers_org.member_row(page, member.id)).to_have_count(1)
    assert status_of(member.page, f"/lists/{list_id}/") == 404
    assert status_of(member.page, "/lists/") == 404


def test_l13_lists_manager_sees_and_edits_any_list_without_list_rights(admin_page, employee):
    """Сценарий 13, п. 8: управляющий (роль с «Управлением списками») открывает любой список — видит его и правит
    независимо от прав списка: настройку, поля, записи (FR-512)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Чужой"))
    # в наборах прав списка нет ни одной строки, а тем более роли управляющего
    assert access_subjects(page, list_id, "read") == []
    assert access_subjects(page, list_id, "edit") == []
    manager = make_list_manager(employee)
    mp = manager.page
    # п. 8: открывает «Списки» — список виден, есть ссылка на настройку и «Создать список»
    assert list_id in list_names_on_home(mp)
    expect(mp.locator(f'li[data-list-id="{list_id}"] a[data-action="list-settings"]')).to_have_count(1)
    expect(mp.locator('a[data-action="lists-create"]').first).to_be_visible()
    # п. 8: открывает список и настройку, правит
    assert mp.goto(f"/lists/{list_id}/").status == 200
    expect(mp.locator('[data-lists-page="grid"]')).to_be_visible()
    code = add_field(mp, list_id, "Поле управляющего", "string")
    title = f"Запись {unique_word()}"
    number = create_record(mp, list_id, title, {code: "значение"})
    open_edit_record(mp, list_id, number)
    helpers_lists.fill_record(mp, {"title": title + " 2"})
    assert submit_record(mp) == number
    expect(mp.locator("[data-lists-record]")).to_contain_text(title + " 2")
    # права списка от этого не появились
    assert access_subjects(page, list_id, "read") == []
    assert access_subjects(page, list_id, "edit") == []


def test_l13_colleague_card_pinned_section_hides_rows_of_list_reader_lost_access_to(admin_page, employee):
    """Сценарий 13, п. 9: коллега указан в записях двух списков; сотрудник, потерявший право читать один из них, открывает
    карточку коллеги — в «Закреплённом» строки этого списка ему не показаны, строки второго остаются (FR-525)."""
    page = admin_page
    word = unique_word("pc")
    colleague = employee(full_name=f"Петров {word}")
    names, titles, codes, lists = {}, {}, {}, {}
    for which in ("first", "second"):
        names[which] = unique_list_name("Закреплённое")
        titles[which] = f"Запись {unique_word()}"
        lists[which] = create_list(page, names[which])
        codes[which] = add_field(page, lists[which], "Ответственный", "person")
        _record_with_picks(page, lists[which], titles[which], {codes[which]: word})
    # смотрящий: читает оба списка и может открывать карточки коллег (`staff.view`)
    role_id, role_name = _role_with(page, ["staff.view"])
    for which in ("first", "second"):
        grant_role(page, lists[which], "read", role_id)
    viewer = employee(role=role_name)
    pinned = viewer.page.locator("#lists-pinned li[data-pinned-record]")
    viewer.page.goto(f"/staff/{colleague.id}/")
    # до потери права видны обе строки: «Название — Список — Поле», со ссылками
    expect(pinned).to_have_count(2)
    for which in ("first", "second"):
        row = pinned.filter(has_text=titles[which])
        expect(row).to_have_count(1)
        expect(row).to_contain_text(names[which])
        expect(row.locator("a")).to_have_count(1)
    # п. 9: смотрящий потерял право читать первый список
    _revoke_subject(page, lists["first"], "read", f"role:{role_id}")
    assert status_of(viewer.page, f"/lists/{lists['first']}/") == 404
    # п. 9: открывает карточку коллеги — строк первого списка нет, второго — есть
    viewer.page.goto(f"/staff/{colleague.id}/")
    expect(pinned).to_have_count(1)
    expect(pinned.first).to_contain_text(titles["second"])
    expect(pinned.first).to_contain_text(names["second"])
    body = viewer.page.locator("body").inner_text()
    assert titles["first"] not in body and names["first"] not in body, "строка потерянного списка осталась в карточке"


def test_l13_direct_post_of_record_save_archive_import_and_settings_without_right_is_refused(admin_page, employee):
    """Сценарий 13, п. 10: прямые POST без кнопки — сохранение записи, архив, групповой архив, загрузка, настройка,
    поля, права, удаление списка, «Создать список» — проверяются на сервере: читающему 403, не читающему 404, правящему
    настройка 403; данные не изменились; положительный контроль — правящему прямой POST «В архив» проходит (FR-514)."""
    page = admin_page
    name = unique_list_name("Охрана")
    title = f"Запись {unique_word()}"
    list_id = create_list(page, name)
    number = create_record(page, list_id, title)
    reader = make_list_reader(employee, page, list_id)
    editor = make_list_editor(employee, page, list_id)
    other_id = create_list(page, unique_list_name("Соседний"))
    outsider = make_list_reader(employee, page, other_id)
    no_rights = employee(role=make_list_role(page)[1])
    hostile = unique_list_name("Нарушитель")
    record_posts = [
        (f"/lists/{list_id}/add/", {"title": hostile}),
        (f"/lists/{list_id}/{number}/edit/", {"title": hostile, "base_version": "1"}),
        (f"/lists/{list_id}/{number}/archive/", {}),
        (f"/lists/{list_id}/bulk-archive/", {"n": str(number)}),
        (f"/lists/{list_id}/import/", {}),
    ]
    settings_posts = [
        (f"/lists/{list_id}/settings/", {"name": hostile, "description": ""}),
        (f"/lists/{list_id}/settings/fields/new/", {"name": hostile, "type": "string"}),
        (f"/lists/{list_id}/settings/access/", {"readers": f"role:{reader.list_role_id}"}),
        (f"/lists/{list_id}/delete/", {}),
    ]
    # п. 10: читающий — отказ по праву (403) на каждом действии
    for path, data in record_posts + settings_posts:
        assert post_status(reader.page, path, data) == 403, f"читающий: POST {path}"
    # п. 10: правящий — запись правит, а настройка ему закрыта
    for path, data in settings_posts:
        assert post_status(editor.page, path, data) == 403, f"правящий: POST {path}"
    # п. 10: не читающий этот список — как у несуществующего (404); без прав вовсе — тоже
    for who in (outsider, no_rights):
        for path, data in record_posts + settings_posts:
            assert post_status(who.page, path, data) == 404, f"не читающий: POST {path}"
    # «Создать список»: читающему 403, без прав 404
    assert post_status(reader.page, "/lists/new/", {"name": hostile}) == 403
    assert post_status(no_rights.page, "/lists/new/", {"name": hostile}) == 404
    # ничего не изменилось
    assert list_id in list_names_on_home(page) and list_names_on_home(page)[list_id] == name
    assert hostile not in list_names_on_home(page).values()
    page.goto(f"/lists/{list_id}/")
    expect(page.locator("tr[data-record-number]")).to_have_count(1)
    open_record(page, list_id, number)
    expect(page.locator("[data-lists-record]")).to_contain_text(title)
    expect(page.locator('button[data-action="record-archive"]')).to_have_count(1)
    assert hostile not in page.locator("body").inner_text()
    assert helpers_lists.field_codes(page, list_id) == ["title"]
    assert access_subjects(page, list_id, "read") == [f"role:{reader.list_role_id}"]
    # положительный контроль того же пути (R-1-E3, находка 9; CONTRACT-006 10.4): правящему прямой POST «В архив»
    # той же записи проходит — отказы выше не означают, что служба отвечает 403 всем
    assert post_status(editor.page, f"/lists/{list_id}/{number}/archive/", {}) in (200, 302)
    open_record(page, list_id, number)
    expect(page.locator('[data-lists-page="record"] [data-lists-archived]').first).to_be_visible()


def test_l13_dismissed_or_blocked_employee_in_read_set_has_no_access(admin_page, employee, new_context):
    """Сценарий 13, п. 11: сотрудник, чья роль стоит в «Читают», после увольнения или блокировки доступа к списку не
    имеет; после разблокировки (роль в наборе прежняя) доступ возвращается (FR-513; SPEC-002 FR-127)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Состояние"))
    dismissed = make_list_reader(employee, page, list_id)
    blocked = make_list_reader(employee, page, list_id)
    active = make_list_reader(employee, page, list_id)
    for account in (dismissed, blocked, active):
        assert account.page.goto(f"/lists/{list_id}/").status == 200
    # п. 11: один уволен, другой заблокирован
    _dismiss_employee(page, dismissed.id)
    page.goto(f"/staff/{blocked.id}/")
    helpers.open_security_tab(page)
    form = page.locator('form[action$="/block/"]')
    form.locator("[name=reason]").fill("проверка прав списков")
    helpers.submit(form)
    # п. 11: доступа к списку нет — сессии закрыты, список ведёт на вход
    for account in (dismissed, blocked):
        account.page.goto(f"/lists/{list_id}/")
        assert "/login/" in account.page.url, "уволенный или заблокированный открыл список"
        expect(account.page.locator("#top-bar")).to_have_count(0)
        expect(account.page.locator('[data-lists-page="grid"]')).to_have_count(0)
    # роль в наборе «Читают» осталась — дело в состоянии сотрудника; читающий той же роли-набора не затронут
    assert access_subjects(page, list_id, "read").count(f"role:{dismissed.list_role_id}") == 1
    assert active.page.goto(f"/lists/{list_id}/").status == 200
    # п. 11: после разблокировки доступ возвращается, у уволенного — нет
    page.goto(f"/staff/{blocked.id}/")
    helpers.open_security_tab(page)
    helpers.submit(page.locator('form[action$="/unblock/"]'))
    again = new_context().new_page()
    helpers.sign_in(again, blocked)
    assert again.goto(f"/lists/{list_id}/").status == 200
    expect(again.locator('[data-lists-page="grid"]')).to_be_visible()
    dismissed.page.goto(f"/lists/{list_id}/")
    assert "/login/" in dismissed.page.url


def test_l13_no_unreadable_records_in_menu_table_search_export_label_links_history_and_ticket_card(
        admin_page, employee):
    """Сценарий 13, п. 3–5 и общее правило: сотрудник читает список A и не читает список B; записей B нет в меню и на
    главной, в таблице и карточке A (значение-ссылка — «запись недоступного списка»), в истории, в выгрузке, в поиске,
    в «Закреплённом» коллеги и в разделе «Записи списков» карточки заявки; адреса B — 404 (FR-514, FR-525, FR-527, FR-528,
    FR-540)."""
    page = admin_page
    word_a, word_b, word_c, word_r = (unique_word(prefix) for prefix in ("aa", "bb", "cc", "rr"))
    colleague = employee(full_name=f"Зайцев {word_c}")
    # список B (закрытый) с записью, где указан коллега
    name_b = unique_list_name("Закрытый")
    b_id = create_list(page, name_b)
    b_person = add_field(page, b_id, "Ответственный", "person")
    title_b = f"Секрет {word_b}"
    b_number = _record_with_picks(page, b_id, title_b, {b_person: word_c})
    # список A (читаемый): поле-ссылка на B в таблице, коллега
    name_a = unique_list_name("Открытый")
    a_id = create_list(page, name_a)
    a_link = add_field(page, a_id, "Связь", "record", target=b_id, show_in_table=True)
    a_person = add_field(page, a_id, "Ответственный", "person")
    title_a = f"Открытая {word_a}"
    a_number = _record_with_picks(page, a_id, title_a, {a_person: word_c})
    open_edit_record(page, a_id, a_number)
    pick(page, a_link, word_b)
    assert submit_record(page) == a_number
    # смотрящий: читает только A, участник очереди заявок, может открывать карточки коллег
    role_id, role_name = _role_with(page, ["staff.view"])
    grant_role(page, a_id, "read", role_id)
    viewer = employee(role=role_name, full_name=f"Орлов {word_r}")
    vp = viewer.page
    number, queue_id = _ticket(page)
    helpers_sd.add_queue_member(page, queue_id, [viewer.id], q=word_r)
    # привязка — общим помощником обвязки (CONTRACT-006, 15.5 п. 12; R-1-E3, находка 7)
    link_ticket(page, number, word_a, title_a)
    link_ticket(page, number, word_b, title_b)
    expect(page.locator('[data-card-part="lists-records"] li[data-ticket-link-id]')).to_have_count(2)

    # меню и главная: B нет, A есть
    home = list_names_on_home(vp)
    assert home == {a_id: name_a}, f"главная читающего: {home}"
    assert name_b not in vp.locator("body").inner_text()
    # адреса B — 404
    for path in (f"/lists/{b_id}/", f"/lists/{b_id}/{b_number}/", f"/lists/{b_id}/{b_number}/history/",
                 f"/lists/{b_id}/export/", f"/lists/{b_id}/{b_number}/label/", f"/lists/{b_id}/labels/?n={b_number}"):
        assert status_of(vp, path) == 404, f"читающий A открыл {path}"
    # таблица A: значение-ссылка на запись B — «запись недоступного списка», без названия и ссылки на B
    vp.goto(f"/lists/{a_id}/")
    cell = vp.locator(f'tr[data-record-number="{a_number}"] td[data-col="{a_link}"]')
    expect(cell.locator("[data-lists-unavailable]")).to_have_count(1)
    expect(cell.locator("a")).to_have_count(0)
    assert word_b not in vp.locator("body").inner_text() and title_b not in vp.locator("body").inner_text()
    # карточка A и история: то же, ссылок на B нет
    open_record(vp, a_id, a_number)
    expect(vp.locator(f'[data-lists-value="{a_link}"] [data-lists-unavailable]')).to_have_count(1)
    expect(vp.locator(f'a[href^="/lists/{b_id}/"]')).to_have_count(0)
    expect(vp.locator('[data-lists-history] li[data-change-kind="changed"]')).to_have_count(1)
    assert word_b not in vp.locator("body").inner_text(), "в карточке и истории A есть название записи B"
    # выгрузка A: управляющему название записи B видно, читающему — нет
    admin_export = _xlsx_text(helpers_org.direct_get(page, f"/lists/{a_id}/export/"))
    assert word_b in admin_export, "выгрузка управляющего не содержит значения-ссылки (контроль)"
    viewer_response = helpers_org.direct_get(vp, f"/lists/{a_id}/export/")
    assert viewer_response.status == 200
    viewer_export = _xlsx_text(viewer_response)
    assert word_b not in viewer_export and word_a in viewer_export
    # поиск: управляющий находит запись B и A, читающий — только A
    page.goto(f"/search/?q={word_b}")
    expect(page.locator('[data-search-page] section[data-search-group="lists"]')).to_have_count(1)
    vp.goto(f"/search/?q={word_b}")
    expect(vp.locator("[data-search-page]")).to_be_visible()
    expect(vp.locator('section[data-search-group="lists"]')).to_have_count(0)
    vp.goto(f"/search/?q={word_a}")
    group = vp.locator('[data-search-page] section[data-search-group="lists"]')
    expect(group).to_have_count(1)
    expect(group.locator(f'a[href="/lists/{a_id}/{a_number}/"]').first).to_be_visible()
    # «Закреплённое» коллеги: строка списка A есть, строки B нет
    vp.goto(f"/staff/{colleague.id}/")
    pinned = vp.locator("#lists-pinned li[data-pinned-record]")
    expect(pinned).to_have_count(1)
    expect(pinned.first).to_contain_text(title_a)
    assert title_b not in vp.locator("body").inner_text()
    # карточка заявки: связана с двумя записями, читающему видна только запись A
    helpers_sd.open_ticket(page, number)
    expect(page.locator('[data-card-part="lists-records"] li[data-ticket-link-id]')).to_have_count(2)
    helpers_sd.open_ticket(vp, number)
    links = vp.locator('[data-card-part="lists-records"] li[data-ticket-link-id]')
    expect(links).to_have_count(1)
    expect(links.locator(f'a[href="/lists/{a_id}/{a_number}/"]')).to_have_count(1)
    assert word_b not in vp.locator('[data-card-part="lists-records"]').inner_text()
    # подбор записи для привязки: запись B не предлагается, запись A предлагается
    hidden = helpers_org.direct_get(vp, f"/lists/ticket-pick/?ticket={number}&q={word_b}")
    assert hidden.status == 200 and "data-pick-id" not in hidden.text() and word_b not in hidden.text()
    offered = helpers_org.direct_get(vp, f"/lists/ticket-pick/?ticket={number}&q={word_a}")
    assert offered.status == 200 and "data-pick-id" in offered.text()


def test_l13_manage_lists_right_given_to_role_in_interface_makes_its_employee_manager(admin_page, employee):
    """Сценарий 13, п. 8: администратор отметил роли «Управление списками» на странице прав ролей — сотрудник этой роли
    становится управляющим: видит все списки, «Создать список» и настройку; до выдачи раздела у него нет (FR-512)."""
    page = admin_page
    role_name = make_list_role(page)[1]
    worker = employee(role=role_name)
    wp = worker.page
    ids = _starter_ids(page)
    # до выдачи: раздела нет (меню проверяется на «Профиле», где оно точно есть; R-1-E3, находка 2)
    assert status_of(wp, "/lists/") == 404
    wp.goto("/me/")
    expect(wp.locator("#main-menu")).to_be_visible()
    expect(wp.locator('#main-menu a[href="/lists/"]')).to_have_count(0)
    # администратор выдаёт право в интерфейсе «Роли и права»
    _, form = _role_page(page, role_name)
    _right(form, LISTS_MANAGE).check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    _, form = _role_page(page, role_name)
    expect(_right(form, LISTS_MANAGE)).to_be_checked()
    # следующий запрос: сотрудник — управляющий
    assert wp.goto("/lists/").status == 200
    expect(wp.locator('#main-menu a[href="/lists/"]')).to_have_count(1)
    expect(wp.locator('a[data-action="lists-create"]').first).to_be_visible()
    seen = list(list_names_on_home(wp).values())
    for name in STARTER_NAMES:
        assert name in seen, f"управляющий не видит «{name}»"
    assert status_of(wp, f"/lists/{ids['Договоры']}/settings/") == 200
    assert status_of(wp, "/lists/new/") == 200
    created = create_list(wp, unique_list_name("Новый"))
    assert created
    # право снято — раздела снова нет
    _, form = _role_page(page, role_name)
    _right(form, LISTS_MANAGE).uncheck()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    assert status_of(wp, "/lists/") == 404
