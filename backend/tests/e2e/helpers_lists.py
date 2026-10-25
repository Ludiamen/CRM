"""Помощники приёмки среза 006 «Списки» (T-6140; ими пользуются T-6141…T-6153).

Что здесь есть (CONTRACT-006.md: разделы 10, 11, 12, 13.1, 13.3; решения 10, 19, 56 задач):
- имена и роли: `unique_word`, `unique_list_name`, `make_list_role`, `make_list_reader`, `make_list_editor`,
  `make_list_manager`;
- права списка через вкладку «Права»: `open_access`, `grant_role`, `grant_unit`, `access_subjects`;
- список через интерфейс: `open_list_new`, `create_list`, `try_create_list`, `list_id_from_url`, `open_settings`,
  `list_names_on_home`, `delete_reason`, `confirm_dialog`;
- поля через интерфейс: `field_form`, `open_new_field`, `choose_type`, `wait_type`, `fill_field_form`, `submit_field_form`,
  `add_field`, `try_add_field`, `field_codes`, `field_code_by_name`, `open_field`, `set_choices`, `choice_titles`,
  `direct_add_field` (только для массовой подготовки, например 50 полей);
- записи через интерфейс: `record_form`, `open_add_record`, `open_edit_record`, `fill_record`, `choose`, `pick`, `submit_record`,
  `create_record`, `try_create_record`, `open_record`, `record_number_from_url`, `archive_record`;
- файлы записи на ClamAV стенда: `files_block`, `record_file_row`, `scan_snapshot`, `try_attach_file`, `attach_file`,
  `wait_file_clean`, `eicar_bytes`;
- команда стенда `e2e_lists_shift` (13.1): `shift`, `parse_shift_line`;
- отказы и ответы: `refusal_codes`, `lift_limits`, `status_of`, `post_status`, `audit_rows`;
- письма Mailpit и Telegram через `fakebots`: `mail_ids`, `item_mail`, `no_item_mail`, `bots`, `bind_telegram`,
  `wait_telegram`;
- QR по решению 10: `qr_svg_variants`, `qr_image_bytes`, `qr_matches`;
- ширина 360 px: `narrow_context`, `open_narrow`, `page_fits`, `scrolls_inside`.

Как заводить людей (раздел 10.4 и К25 контракта: «читает» и «правит» — свойство пары «сотрудник, список»):
- читающий и правящий — `make_list_reader` / `make_list_editor`: новая роль без прав (`/roles/new/`), сотрудник с этой
  ролью и строка роли в наборе «Читают» или «Правят» своего списка через вкладку «Права»; встроенным ролям
  («Сотрудник ИТ», «Руководитель») права на списки не выдаются никогда: «Сотрудник ИТ» уже читает и правит шесть
  стартовых списков (данные установки), и чужая выдача протекла бы в соседние тесты круга;
- управляющий — `make_list_manager` (роль «Администратор портала», у неё право `lists.manage` после данных установки)
  или `admin_page` круга;
- сотрудник без прав на списки — `employee(role=make_list_role(admin_page)[1])`: раздела «Списки» у него нет (404).

Правила (шаблон e2e/template.md): код приложения (`apps.*`, `django`) и `tests.support*` не импортируются; локаторы —
только из контракта; ждать — `expect`, `wait_for_url`, `expect_response`; сна нет (опрос файла — `wait_for_timeout`);
данные круга общие: каждый тест заводит свои списки с уникальными названиями и не меняет шесть стартовых (решение 56);
`shift(days)` сдвигает сроки ВСЕХ записей стенда, поэтому тесты сроков смотрят только на свои записи. Готовое из прежних
срезов не дублируется, а вызывается: `helpers` (вход, `mail_ids`, `stand_shell`), `helpers_sd._stand_command`,
`helpers_sd.reset_stand_and_relogin` (сброс перед кругом), `helpers_org` (`direct_get`, `direct_post`, `audit_rows`,
`unique_name`, `role_id`, `create_unit`, `add_members`), `helpers_notify` (`wait_item_mail`, `no_item_mail`,
`channels_on`), `helpers_kb` (`eicar_bytes`, `bots`, `bind_telegram`, `wait_telegram`, `narrow_context`, `page_fits`,
`scrolls_inside`, `parse_kb_line`). Файл правит только T-6140.
"""
import base64
import re
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_notify, helpers_org, helpers_sd

MANAGER_ROLE = helpers.ADMIN_ROLE   # «Администратор портала»: `lists.manage` после данных установки (раздел 2.4)
NAME_LIMIT = 100                    # знаков названия списка (FR-502)
DESCRIPTION_LIMIT = 500             # знаков описания списка (FR-502)
FIELD_NAME_LIMIT = 100              # знаков названия поля (FR-506)
FIELDS_LIMIT = 50                   # полей в списке без «Названия» (FR-506)
TYPES = ("string", "text", "number", "money", "date", "datetime", "bool", "choice", "person", "unit", "record", "file")
TYPE_LABELS = {                     # подписи `Field.Type` (раздел 2.2)
    "string": "Строка", "text": "Многострочный текст", "number": "Число", "money": "Деньги", "date": "Дата",
    "datetime": "Дата и время", "bool": "Да/нет", "choice": "Список значений", "person": "Сотрудник",
    "unit": "Подразделение", "record": "Запись другого списка", "file": "Файл",
}
CURRENCIES = ("RUB", "USD", "EUR")  # поле `currency` (10.2)
# Свойства по FR-508, которые форма поля обязана показать у типа (`[data-prop]`, 11.2), и свойства, которых у типа нет.
# «Обязательное», «показывать в таблице», «пороги» и «значение по умолчанию» у списка значений здесь не ждутся:
# их показ зависит от состояния формы (новое поле, флажок «срок», значения ещё не заданы).
_PROPS_SHOWN = {
    "string": ("unique", "default"), "text": (), "number": ("unique", "default"), "money": ("currency", "default"),
    "date": ("deadline", "default"), "datetime": (), "bool": ("default",), "choice": ("multiple",),
    "person": ("multiple",), "unit": ("multiple",), "record": ("multiple", "target"), "file": ("multiple",),
}
_PROPS_ALLOWED = {
    "string": {"required", "unique", "default"}, "text": {"required"}, "number": {"required", "unique", "default"},
    "money": {"required", "default", "currency"}, "date": {"required", "default", "deadline"},
    "datetime": {"required"}, "bool": {"default"}, "choice": {"required", "multiple", "default"},
    "person": {"required", "multiple"}, "unit": {"required", "multiple"}, "record": {"required", "multiple", "target"},
    "file": {"multiple"},
}
_CHECKED_PROPS = ("required", "multiple", "unique", "default", "currency", "target", "deadline")
_SAVE = "button[type=submit]:not([data-action])"  # главная кнопка формы — единственная такая в форме (15.4, п. 1)
_REFUSAL = "[data-error][data-code], [role=alert][data-code]"  # отказы формы (10.1)
_LIST_URL = re.compile(r"/lists/(\d+)/")
_RECORD_URL = re.compile(r"/lists/(\d+)/(\d+)/$")
_SHIFT_KEYS = {"days", "shifted", "notified"}


# --- Имена ----------------------------------------------------------------------------------------------------

def unique_word(prefix: str = "lst") -> str:
    """Уникальное слово из латинских строчных букв (`helpers_kb.unique_word`): годится для поиска."""
    return helpers_kb.unique_word(prefix)


def unique_list_name(prefix: str = "Список") -> str:
    """Уникальное название списка: `<prefix> <unique_word()>` (до 100 знаков при коротком `prefix`)."""
    return f"{prefix} {unique_word()}"


# --- Роли и люди (10.4, К25) ----------------------------------------------------------------------------------

def make_list_role(admin_page, name: str | None = None) -> tuple:
    """Новая роль без прав формой `/roles/new/` (срез 001: поле `name`, флажки `permissions` не отмечаются).
    Возвращает `(role_id, name)`; `name` по умолчанию — уникальное «Роль списка-<hex>»."""
    name = name or helpers_org.unique_name("Роль списка")
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    with admin_page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    admin_page.wait_for_load_state()
    return helpers_org.role_id(admin_page, name), name


def _make_list_actor(employee, admin_page, list_id, level: str, **kwargs):
    role_id, role_name = make_list_role(admin_page)
    grant_role(admin_page, list_id, level, role_id)
    account = employee(role=role_name, **kwargs)
    account.list_role_id = role_id
    account.list_role_name = role_name
    return account


def make_list_reader(employee, admin_page, list_id, **kwargs):
    """Читающий список `list_id`: новая роль без прав (`make_list_role`) в наборе «Читают» этого списка (вкладка
    «Права», `grant_role`), сотрудник с этой ролью (`employee` — фикстура круга; `kwargs` — её параметры, например
    `full_name`). Возвращает `Account` (сессия — `account.page`); номер и название роли — `account.list_role_id`,
    `account.list_role_name` (чтобы дать той же роли другой список: `grant_role`)."""
    return _make_list_actor(employee, admin_page, list_id, "read", **kwargs)


def make_list_editor(employee, admin_page, list_id, **kwargs):
    """Правящий список `list_id`: как `make_list_reader`, но роль — в наборе «Правят» («правят» читают тоже)."""
    return _make_list_actor(employee, admin_page, list_id, "edit", **kwargs)


def make_list_manager(employee, **kwargs):
    """Управляющий списками (`lists.manage`): сотрудник с ролью «Администратор портала». Если хватает
    администратора круга, берите `admin_page`."""
    return employee(role=MANAGER_ROLE, **kwargs)


# --- Права списка (11.2, 10.2) --------------------------------------------------------------------------------

def open_access(page, list_id) -> None:
    """Открывает вкладку «Права» `/lists/<id>/settings/access/` и ждёт `[data-lists-page="access"]`."""
    page.goto(f"/lists/{list_id}/settings/access/")
    expect(page.locator('[data-lists-page="access"]')).to_be_visible()


def _access_block(page, level: str):
    assert level in ("read", "edit"), f"набор прав — read или edit, а не {level!r}"
    return page.locator(f'[data-lists-access="{level}"]')


def _save_access(page, list_id) -> None:
    """Отправляет форму прав (одна форма с обоими наборами: POST несёт и `readers`, и `editors`, 10.2) и ждёт ответ."""
    form = page.locator('form:has([data-lists-access="read"])').first
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(f"/lists/{list_id}/settings/access/")):
        form.locator(_SAVE).click()
    page.wait_for_load_state()


def grant_role(page, list_id, level: str, role_id, *, save: bool = True) -> None:
    """Добавляет роль в набор `level` («read» — «Читают», «edit» — «Правят») на вкладке «Права» (управляющий):
    `select[data-lists-role-select]` (значение пункта — номер роли, 15.4 п. 5), `button[data-action="access-add"]`,
    ждёт `li[data-subject="role:<id>"]` в наборе; при `save` сохраняет форму и проверяет строку после перезагрузки."""
    open_access(page, list_id)
    block = _access_block(page, level)
    block.locator("select[data-lists-role-select]").select_option(value=str(role_id))
    block.locator('button[data-action="access-add"]').click()
    expect(block.locator(f'li[data-subject="role:{role_id}"]')).to_have_count(1)
    if save:
        _save_access(page, list_id)
        expect(_access_block(page, level).locator(f'li[data-subject="role:{role_id}"]')).to_have_count(1)


def grant_unit(page, list_id, level: str, unit_id, query: str, *, save: bool = True) -> None:
    """Добавляет подразделение в набор `level` подсказкой `input[data-lists-picker="units"]` (запрос `/lists/units/`):
    вводит `query` по знаку, нажимает `li[data-pick-id="<unit_id>"]` подсказки внутри набора, ждёт
    `li[data-subject="unit:<id>"]`; при `save` сохраняет и проверяет строку после перезагрузки."""
    open_access(page, list_id)
    block = _access_block(page, level)
    field = block.locator('input[data-lists-picker="units"]')
    field.fill("")
    field.press_sequentially(query, delay=30)
    option = block.locator(f'ul[data-lists-pick] li[data-pick-id="{unit_id}"]')
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    expect(block.locator(f'li[data-subject="unit:{unit_id}"]')).to_have_count(1)
    if save:
        _save_access(page, list_id)
        expect(_access_block(page, level).locator(f'li[data-subject="unit:{unit_id}"]')).to_have_count(1)


def access_subjects(page, list_id, level: str) -> list:
    """Значения `data-subject` строк набора `level` вкладки «Права» по порядку (`role:<id>`, `unit:<id>`)."""
    open_access(page, list_id)
    return [li.get_attribute("data-subject") for li in _access_block(page, level).locator("li[data-subject]").all()]


# --- Отказы, ответы, журнал -----------------------------------------------------------------------------------

def refusal_codes(page) -> list:
    """Отказы формы на странице (10.1): пары `(поле, код)` — у поля `[data-error="<поле>"][data-code]`, общий
    отказ — `("alert", код)` у `[role=alert][data-code]`."""
    out = []
    for el in page.locator(_REFUSAL).all():
        field = el.get_attribute("data-error")
        out.append((field if field is not None else "alert", el.get_attribute("data-code")))
    return out


def lift_limits(scope) -> None:
    """Снимает с полей внутри `scope` (локатор формы) `maxlength`, `minlength`, `required` и `pattern`: проверку
    пределов и обязательности делает сервер, а браузер иначе обрезал бы ввод или не отправил форму (так её отправил
    бы обход браузера). Образец — `test_k01._lift_limits`."""
    scope.evaluate("el => el.querySelectorAll('input, textarea, select').forEach(f => "
                   "['maxlength', 'minlength', 'required', 'pattern'].forEach(a => f.removeAttribute(a)))")


def status_of(page, path: str) -> int:
    """Код ответа прямого GET от имени страницы без перехода по редиректам (`helpers_org.direct_get`)."""
    return helpers_org.direct_get(page, path).status


def post_status(page, path: str, data: dict | None = None) -> int:
    """Код ответа прямого POST от имени страницы с CSRF без перехода по редиректам (`helpers_org.direct_post`)."""
    return helpers_org.direct_post(page, path, data).status


def audit_rows(admin_page, action: str, object_id=None) -> list:
    """Тексты строк журнала `/audit/` с кодом `action` (например `lists.list_deleted`) и номером объекта
    (`helpers_org.audit_rows`); новые сверху."""
    return helpers_org.audit_rows(admin_page, action, object_id)


# --- Список (10.2, 11.1, 11.2) --------------------------------------------------------------------------------

def list_id_from_url(url: str) -> str:
    """Номер списка из адреса `/lists/<id>/…`; другой адрес — `AssertionError`."""
    found = _LIST_URL.search(url)
    assert found, f"в адресе нет номера списка: {url}"
    return found.group(1)


def open_list_new(page):
    """Открывает `/lists/new/`, ждёт `[data-lists-page="new"]`; возвращает локатор формы (поля `name`, `description`)."""
    page.goto("/lists/new/")
    root = page.locator('[data-lists-page="new"]')
    expect(root).to_be_visible()
    form = root.locator("form:has([name=name])").first
    expect(form).to_be_visible()
    return form


def try_create_list(page, name: str, description: str = "") -> str:
    """«Создать список» формой `/lists/new/` (пределы браузера сняты `lift_limits`): ждёт переход на
    `/lists/<id>/settings/` или отказ формы. Возвращает номер списка или пустую строку при отказе (страница
    остаётся с отказом — его читает тест)."""
    form = open_list_new(page)
    lift_limits(form)
    form.locator("[name=name]").fill(name)
    form.locator("[name=description]").fill(description)
    form.locator(_SAVE).click()
    expect(page.locator(f'[data-lists-page="settings"], {_REFUSAL}').first).to_be_visible()
    if re.search(r"/lists/\d+/settings/$", page.url):
        return list_id_from_url(page.url)
    return ""


def create_list(page, name: str, description: str = "") -> str:
    """Новый список через интерфейс (управляющий); возвращает номер. Отказ — `AssertionError` с кодами."""
    list_id = try_create_list(page, name, description)
    assert list_id, f"список «{name}» не создан: {refusal_codes(page)}"
    expect(page.locator('[data-lists-page="settings"]')).to_be_visible()
    return list_id


def open_settings(page, list_id, tab: str = "main") -> None:
    """Открывает вкладку настройки: `main` — `/lists/<id>/settings/` (`[data-lists-page="settings"]`), `fields` —
    `…/settings/fields/` (`fields`), `access` — `…/settings/access/` (`access`)."""
    path, root = {"main": ("", "settings"), "fields": ("fields/", "fields"), "access": ("access/", "access")}[tab]
    page.goto(f"/lists/{list_id}/settings/{path}")
    expect(page.locator(f'[data-lists-page="{root}"]')).to_be_visible()


def confirm_dialog(page) -> None:
    """Подтверждает открытый диалог `dialog[data-lists-confirm]` кнопкой `button[type=submit][data-action="confirm"]`
    (15.4, п. 2); результат не ждёт."""
    dialog = page.locator("dialog[data-lists-confirm]")
    expect(dialog).to_be_visible()
    dialog.locator('button[type=submit][data-action="confirm"]').click()


def list_names_on_home(page) -> dict:
    """Главная `/lists/`: словарь «номер списка → название» по строкам `li[data-list-id]` (`a[data-field="name"]`)."""
    page.goto("/lists/")
    expect(page.locator('[data-lists-page="home"]')).to_be_visible()
    return {li.get_attribute("data-list-id"): li.locator('a[data-field="name"]').inner_text().strip()
            for li in page.locator("li[data-list-id]").all()}


def delete_reason(page, list_id) -> str:
    """Вкладка «Основное» (там кнопка «Удалить список», 15.4 п. 8): текст пояснения `[data-lists-delete-reason]` у недоступной кнопки
    `button[data-action="list-delete"]` (проверяет атрибут `disabled`)."""
    open_settings(page, list_id)
    expect(page.locator('button[data-action="list-delete"]')).to_be_disabled()
    reason = page.locator("[data-lists-delete-reason]")
    expect(reason).to_be_visible()
    return reason.inner_text().strip()


# --- Поля (10.2, 11.2) ----------------------------------------------------------------------------------------

def field_form(page):
    """Форма поля `form[data-lists-field-form]` (новое поле и правка)."""
    return page.locator("form[data-lists-field-form]")


def open_new_field(page, list_id, type_code: str | None = None):
    """Открывает `/lists/<id>/settings/fields/new/` (с `type_code` — `…/new/?type=<тип>`: форма сразу со свойствами
    этого типа, 10.2, К-15) и ждёт форму поля; с `type_code` ещё и свойства типа (`wait_type`). Возвращает локатор
    формы."""
    page.goto(f"/lists/{list_id}/settings/fields/new/" + (f"?type={type_code}" if type_code else ""))
    expect(field_form(page)).to_be_visible()
    if type_code:
        wait_type(page, type_code)
    return field_form(page)


def open_field(page, list_id, code):
    """Открывает `/lists/<id>/settings/fields/<код>/` и ждёт форму поля; возвращает её локатор."""
    page.goto(f"/lists/{list_id}/settings/fields/{code}/")
    expect(field_form(page)).to_be_visible()
    return field_form(page)


def _hx_on_change(locator) -> bool:
    """True, если смена значения элемента уходит запросом HTMX (у него `hx-get`/`hx-post` или предок с
    `hx-trigger` на `change`)."""
    return bool(locator.first.evaluate(
        "el => !!(el.getAttribute('hx-get') || el.getAttribute('hx-post') || el.closest('[hx-trigger*=\"change\"]'))"))


def _set_choice(scope, name: str, value) -> None:
    """Ставит значение поля `name` внутри `scope`: `<select>` — пункт со значением `value`, переключатели — тот,
    у которого `value`."""
    control = scope.locator(f'[name="{name}"]')
    if control.count() == 1 and control.evaluate("el => el.tagName") == "SELECT":
        control.select_option(value=str(value))
    else:
        scope.locator(f'[name="{name}"][value="{value}"]').check()


def choose_type(page, type_code: str) -> None:
    """Выбирает тип поля в открытой форме (`type`: выпадающий список или переключатели, значения — раздел 2.2); выбор
    перезапрашивает форму (`hx-get` на `…/new/?type=`, 10.2) — помощник ждёт ответ (до 10 с), затем `wait_type`."""
    assert type_code in TYPES, f"неизвестный тип {type_code!r}"
    form = field_form(page)
    control = form.locator("[name=type]")
    expect(control.first).to_be_visible()
    if _hx_on_change(control):
        try:
            with page.expect_response(lambda r: "/lists/" in r.url, timeout=10_000):
                _set_choice(form, "type", type_code)
        except PlaywrightTimeoutError:
            pass
    else:
        _set_choice(form, "type", type_code)
    wait_type(page, type_code)


def wait_type(page, type_code: str) -> None:
    """Ждёт, пока форма поля покажет тип `type_code` (значение `type`) и его свойства по FR-508 (`[data-prop]`, 11.2):
    обязательные типу — видны, недоступные — отсутствуют."""
    assert type_code in TYPES, f"неизвестный тип {type_code!r}"
    form = field_form(page)
    control = form.locator("[name=type]")
    if control.count() == 1 and control.evaluate("el => el.tagName") == "SELECT":
        expect(control).to_have_value(type_code)
    else:
        expect(form.locator(f'[name=type][value="{type_code}"]')).to_be_checked()
    for prop in _CHECKED_PROPS:
        hook = form.locator(f'[data-prop="{prop}"]')
        if prop in _PROPS_SHOWN[type_code]:
            expect(hook.first).to_be_visible()
        elif prop not in _PROPS_ALLOWED[type_code]:
            expect(hook).to_have_count(0)


def _set_flag(form, prop: str, value: bool) -> None:
    box = form.locator(f'[data-prop="{prop}"] input[name="{prop}"]')
    expect(box).to_have_count(1)
    box.set_checked(bool(value))


def fill_field_form(page, *, name: str | None = None, hint: str | None = None, required: bool | None = None,
                    multiple: bool | None = None, unique: bool | None = None, show_in_table: bool | None = None,
                    deadline: bool | None = None, thresholds=None, default=None, currency: str | None = None,
                    target=None) -> None:
    """Заполняет форму поля (10.2): только переданные значения. Флажки — `[data-prop="<свойство>"] input[name=…]`;
    `thresholds` — до трёх целых в `input[name=thresholds]` (лишние поля очищаются); `default` — строка в поле
    `default` (у да/нет — `True`/`False` флажком, у выпадающего списка — значение пункта); `currency` — `RUB`,
    `USD`, `EUR`; `target` — номер списка. `name` и `hint` вводятся последними, после возможной перерисовки формы.
    Пределы браузера снимаются (`lift_limits`)."""
    form = field_form(page)
    for prop, value in (("required", required), ("multiple", multiple), ("unique", unique),
                        ("show_in_table", show_in_table), ("deadline", deadline)):
        if value is not None:
            _set_flag(form, prop, value)
    if thresholds is not None:
        boxes = form.locator('[data-prop="thresholds"] input[name="thresholds"]')
        expect(boxes.first).to_be_visible()
        values = [str(v) for v in thresholds]
        assert boxes.count() >= len(values), f"полей порогов {boxes.count()}, нужно {len(values)}"
        for i, box in enumerate(boxes.all()):
            box.fill(values[i] if i < len(values) else "")
    if default is not None:
        control = form.locator('[data-prop="default"] [name="default"]')
        expect(control.first).to_be_visible()
        kind = control.first.evaluate("el => el.tagName === 'SELECT' ? 'select' : (el.type || '')")
        if kind == "checkbox":
            control.first.set_checked(bool(default))
        elif kind == "select":
            control.first.select_option(value=str(default))
        else:
            control.first.fill(str(default))
    if currency is not None:
        _set_choice(form.locator('[data-prop="currency"]'), "currency", currency)
    if target is not None:
        _set_choice(form.locator('[data-prop="target"]'), "target", target)
    lift_limits(form)
    if name is not None:
        form.locator("[name=name]").fill(name)
        expect(form.locator("[name=name]")).to_have_value(name)
    if hint is not None:
        form.locator("[name=hint]").fill(hint)


def submit_field_form(page, list_id) -> bool:
    """Отправляет форму поля и ждёт итог: переход на вкладку «Поля» `/lists/<id>/settings/fields/` (успех, True) или
    отказ формы (False; страница остаётся — отказ читает тест или `refusal_codes`)."""
    field_form(page).locator(_SAVE).click()
    expect(page.locator(f'[data-lists-page="fields"], {_REFUSAL}').first).to_be_visible()
    return bool(re.search(rf"/lists/{list_id}/settings/fields/$", page.url))


def try_add_field(page, list_id, name: str, type_code: str, **props) -> str:
    """Новое поле через интерфейс: `open_new_field(page, list_id, type_code)` (форма по `?type=`),
    `fill_field_form(name=…, **props)`, `submit_field_form`. Возвращает код нового поля (`f<n>`) или пустую строку при
    отказе (страница с отказом). Смену типа выбором в форме проверяет `choose_type`."""
    open_new_field(page, list_id, type_code)
    fill_field_form(page, name=name, **props)
    if not submit_field_form(page, list_id):
        return ""
    return field_code_by_name(page, list_id, name, navigate=False)


def add_field(page, list_id, name: str, type_code: str, **props) -> str:
    """Поле без отказа (`try_add_field`); возвращает код поля. Отказ — `AssertionError` с кодами отказа."""
    code = try_add_field(page, list_id, name, type_code, **props)
    assert code, f"поле «{name}» не добавлено: {refusal_codes(page)}"
    return code


def direct_add_field(page, list_id, name: str, type_code: str = "string", **data) -> int:
    """Массовая подготовка (например, добор до 50 полей): прямой POST формы `/lists/<id>/settings/fields/new/` от
    имени страницы управляющего (поля 10.2: `name`, `type` и `data`). Возвращает код ответа (успех — 302)."""
    return post_status(page, f"/lists/{list_id}/settings/fields/new/", {"name": name, "type": type_code, **data})


def field_codes(page, list_id, *, navigate: bool = True) -> list:
    """Коды строк сетки полей `[data-lists-fields-grid] tr[data-field-code]` по порядку, первым — `title`."""
    if navigate:
        open_settings(page, list_id, "fields")
    return [tr.get_attribute("data-field-code")
            for tr in page.locator("[data-lists-fields-grid] tr[data-field-code]").all()]


def field_code_by_name(page, list_id, name: str, *, navigate: bool = True) -> str:
    """Код поля по точному названию (`[data-field="name"]` строки `tr[data-field-code]`); не одно — `AssertionError`."""
    if navigate:
        open_settings(page, list_id, "fields")
    found = [tr.get_attribute("data-field-code")
             for tr in page.locator("[data-lists-fields-grid] tr[data-field-code]").all()
             if tr.locator('[data-field="name"]').inner_text().strip() == name]
    assert len(found) == 1, f"полей с названием «{name}»: {len(found)}"
    return found[0]


def set_choices(page, list_id, code, titles) -> list:
    """Добавляет значения поля «список значений» на его странице: `input[data-lists-choice-title]` и
    `button[data-action="choice-add"]` на каждое название (ждёт новую строку с `input[name="title"]`), затем отправка
    формы с `[data-lists-choices]` (POST `…/<код>/choices/`); после перезагрузки сверяет, что значения стоят в конце по
    порядку. Возвращает номера значений не в архиве по порядку (`li[data-choice-id]`)."""
    open_field(page, list_id, code)
    block = page.locator("[data-lists-choices]")
    expect(block).to_be_visible()
    for title in titles:
        before = block.locator('input[name="title"]').count()
        block.locator("input[data-lists-choice-title]").fill(title)
        block.locator('button[data-action="choice-add"]').click()
        expect(block.locator('input[name="title"]')).to_have_count(before + 1)
    form = page.locator("form[data-lists-choices], form:has([data-lists-choices])").first
    with page.expect_response(lambda r: r.request.method == "POST"
                              and r.url.split("?")[0].endswith(f"/settings/fields/{code}/choices/")):
        form.locator(_SAVE).click()
    page.wait_for_load_state()
    open_field(page, list_id, code)
    shown = choice_titles(page)
    assert shown[len(shown) - len(titles):] == list(titles), f"значения после сохранения: {shown}"
    rows = page.locator("[data-lists-choices] li[data-choice-id]:not([data-archived])")
    return [li.get_attribute("data-choice-id") for li in rows.all()]


def choice_titles(page) -> list:
    """Названия значений не в архиве на открытой странице поля по порядку (`input[name="title"]` строк
    `li[data-choice-id]` без `data-archived`)."""
    rows = page.locator("[data-lists-choices] li[data-choice-id]:not([data-archived])")
    return [li.locator('input[name="title"]').input_value() for li in rows.all()]


# --- Записи (10.2, 11.4, 11.5) --------------------------------------------------------------------------------

def record_form(page):
    """Форма записи `form[data-lists-record-form]` (новая и правка)."""
    return page.locator("form[data-lists-record-form]")


def open_add_record(page, list_id):
    """Открывает `/lists/<id>/add/`, ждёт `[data-lists-page="add"]` и форму записи; возвращает её локатор."""
    page.goto(f"/lists/{list_id}/add/")
    expect(page.locator('[data-lists-page="add"]')).to_be_visible()
    expect(record_form(page)).to_be_visible()
    return record_form(page)


def _field_box(page, code):
    return record_form(page).locator(f'[data-lists-field="{code}"]')


def fill_record(page, values: dict) -> None:
    """Заполняет форму записи по кодам полей (`title` — «Название»): строка значения — в `[name="<код>"]`
    контейнера `[data-lists-field="<код>"]` (у выпадающего списка — пункт с такой подписью); `True`/`False` —
    флажок да/нет. Выбор значений списка — `choose`, людей, узлов и записей — `pick`. Пределы браузера снимаются."""
    lift_limits(record_form(page))
    for code, value in values.items():
        control = _field_box(page, code).locator(f'[name="{code}"]').first
        expect(control).to_be_attached()
        if isinstance(value, bool):
            control.set_checked(value)
        elif control.evaluate("el => el.tagName") == "SELECT":
            control.select_option(label=str(value))
        else:
            control.fill(str(value))


def choose(page, code, title: str) -> None:
    """Поле «список значений»: `select[name="<код>"]` — пункт с подписью `title`; флажки (при «несколько») —
    флажок с подписью `title` (связь `<label>`)."""
    box = _field_box(page, code)
    select = box.locator(f'select[name="{code}"]')
    if select.count():
        select.select_option(label=title)
    else:
        box.get_by_label(title, exact=True).check()


def pick(page, code, query: str, pick_id=None) -> str:
    """Подсказка выбора поля «сотрудник», «подразделение» или «запись» (11.4): вводит `query` по знаку в
    `input[data-lists-picker]` контейнера поля, ждёт `ul[data-lists-pick]` и нажимает `li[data-pick-id="<pick_id>"]`
    (без `pick_id` — единственную строку с текстом `query`); ждёт `[data-lists-selected="<код>"]
    li[data-selected-id]`. Возвращает выбранный номер."""
    box = _field_box(page, code)
    field = box.locator("input[data-lists-picker]")
    field.fill("")
    field.press_sequentially(query, delay=30)
    options = box.locator("ul[data-lists-pick] li[data-pick-id]")
    option = (box.locator(f'ul[data-lists-pick] li[data-pick-id="{pick_id}"]') if pick_id is not None
              else options.filter(has_text=query))
    expect(option).to_have_count(1, timeout=10_000)
    chosen = option.get_attribute("data-pick-id")
    option.click()
    expect(page.locator(f'[data-lists-selected="{code}"] li[data-selected-id="{chosen}"]')).to_have_count(1)
    return chosen


def open_edit_record(page, list_id, number):
    """Открывает правку `/lists/<id>/<n>/edit/`, ждёт `[data-lists-page="edit"]` и форму записи; возвращает её локатор
    (дальше — `fill_record`, `choose`, `pick`, `submit_record`). У записи в архиве страница другая
    (`[data-lists-page="archived-edit"]` без формы) — её тест открывает сам."""
    page.goto(f"/lists/{list_id}/{number}/edit/")
    expect(page.locator('[data-lists-page="edit"]')).to_be_visible()
    expect(record_form(page)).to_be_visible()
    return record_form(page)


def record_number_from_url(url: str) -> int:
    """Номер записи из адреса карточки `/lists/<id>/<n>/`; другой адрес — `AssertionError`."""
    found = _RECORD_URL.search(url)
    assert found, f"адрес не карточки записи: {url}"
    return int(found.group(2))


def submit_record(page) -> int:
    """Отправляет форму записи и ждёт итог: карточка `[data-lists-record]` (возвращает номер записи) или отказ
    формы (возвращает 0; страница остаётся с отказом)."""
    record_form(page).locator(_SAVE).click()
    expect(page.locator(f"[data-lists-record], {_REFUSAL}").first).to_be_visible()
    if _RECORD_URL.search(page.url) and page.locator("[data-lists-record]").count():
        return record_number_from_url(page.url)
    return 0


def try_create_record(page, list_id, title: str, values: dict | None = None) -> int:
    """Новая запись формой `/lists/<id>/add/`: «Название» и `values` (`fill_record`). Номер записи или 0 при отказе."""
    open_add_record(page, list_id)
    fill_record(page, {"title": title, **(values or {})})
    return submit_record(page)


def create_record(page, list_id, title: str, values: dict | None = None) -> int:
    """Запись без отказа (`try_create_record`); возвращает номер. Отказ — `AssertionError` с кодами."""
    number = try_create_record(page, list_id, title, values)
    assert number, f"запись «{title}» не создана: {refusal_codes(page)}"
    return number


def open_record(page, list_id, number) -> None:
    """Открывает карточку `/lists/<id>/<n>/` и ждёт `[data-lists-record]`."""
    page.goto(f"/lists/{list_id}/{number}/")
    expect(page.locator("[data-lists-record]")).to_be_visible()


def archive_record(page, list_id, number) -> None:
    """«В архив» на карточке (`button[data-action="record-archive"]`, правящий); ждёт кнопку
    `button[data-action="record-restore"]` и пометку `[data-lists-archived]` на карточке."""
    open_record(page, list_id, number)
    page.locator('button[data-action="record-archive"]').click()
    expect(page.locator('button[data-action="record-restore"]')).to_be_visible()
    expect(page.locator('[data-lists-page="record"] [data-lists-archived]').first).to_be_visible()


# --- Файлы записи (11.7; решение 19) --------------------------------------------------------------------------

eicar_bytes = helpers_kb.eicar_bytes  # строка EICAR из частей (решение 12 задач): ClamAV стенда — карантин


def files_block(page, code):
    """Блок файлов поля `[data-lists-files="<код поля>"]` на карточке записи."""
    return page.locator(f'[data-lists-files="{code}"]')


def record_file_row(page, file_id):
    """Строка файла `li[data-file-id="<id>"]` (атрибут `data-scan`: `pending`, `clean`, `quarantine`)."""
    return page.locator(f'li[data-file-id="{file_id}"]')


_SNAPSHOT_JS = """el => ({state: el.getAttribute("data-scan"), text: el.textContent,
                          links: el.querySelectorAll('a[data-action="file-download"]').length})"""


def _check_snapshot(seen: dict) -> dict:
    """Согласованность строки файла по 11.7 и 12.4: «чистый» — со ссылкой скачивания, «проверяется» и «в карантине» —
    с пометкой и без ссылки."""
    assert seen["state"] in ("pending", "clean", "quarantine"), f"состояние файла {seen['state']!r}"
    if seen["state"] == "pending":
        assert "проверяется" in seen["text"], f"у файла «pending» подпись {seen['text']!r}"
        assert seen["links"] == 0, "у файла «проверяется» есть ссылка скачивания"
    elif seen["state"] == "quarantine":
        assert "в карантине" in seen["text"], f"у файла «quarantine» подпись {seen['text']!r}"
        assert seen["links"] == 0, "у файла «в карантине» есть ссылка скачивания"
    else:
        assert seen["links"] >= 1, "у «чистого» файла нет ссылки скачивания"
    return seen


def scan_snapshot(page, file_id) -> dict:
    """Состояние строки файла одним обращением к DOM: `{"state", "text", "links"}` (`links` — число
    `a[data-action="file-download"]`), с проверкой согласованности (`_check_snapshot`)."""
    return _check_snapshot(record_file_row(page, file_id).evaluate(_SNAPSHOT_JS))


def _attach(page, list_id, number, code, data: bytes, name: str, mime: str) -> tuple:
    """Загрузка файла в поле `code` карточки: своя форма поля `form[data-action="file-attach"]` внутри
    `[data-lists-files="<код>"]` (`input[type=file][name=file]`, скрытое `field`), отправка кнопкой
    `button[type=submit]` с ожиданием ответа POST (15.4, п. 7; автоотправки нет). Затем до 30 с ждёт новую строку
    `li[data-file-id]` в блоке поля (снимок состояния — сразу, одним обращением к DOM) или отказ формы.
    Возвращает `(код отказа или "", номер файла или "", снимок или None)`."""
    open_record(page, list_id, number)
    block = files_block(page, code)
    before = {li.get_attribute("data-file-id") for li in block.locator("li[data-file-id]").all()}
    form = block.locator('form[data-action="file-attach"]')
    expect(form).to_have_count(1)

    def is_post(r):
        return r.request.method == "POST" and r.url.split("?")[0].endswith(f"/lists/{list_id}/{number}/files/")

    form.locator('input[type=file][name="file"]').set_input_files(
        {"name": name, "mimeType": mime, "buffer": bytes(data)})
    with page.expect_response(is_post, timeout=30_000):
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    rows = files_block(page, code).locator("li[data-file-id]")
    refusal = page.locator(_REFUSAL)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for li in rows.all():
            file_id = li.get_attribute("data-file-id")
            if file_id not in before:
                return "", file_id, _check_snapshot(li.evaluate(_SNAPSHOT_JS))
        if refusal.count():
            return refusal.first.get_attribute("data-code"), "", None
        page.wait_for_timeout(100)
    raise AssertionError("ответ на загрузку файла не пришёл за 30 с")


def try_attach_file(page, list_id, number, code, data: bytes, name: str, *,
                    mime: str = "application/octet-stream") -> str:
    """Загружает файл в поле `code` записи (`_attach`); возвращает код отказа (`files_limit`, `file_too_big`,
    `file_type_refused`, `field_has_file`, `record_archived`, `bad_file_field`, …) или пустую строку при успехе."""
    return _attach(page, list_id, number, code, data, name, mime)[0]


def attach_file(page, list_id, number, code, data: bytes, name: str, *,
                mime: str = "application/octet-stream") -> tuple:
    """Файл без отказа; возвращает `(file_id, снимок)`: снимок `{"state", "text", "links"}` прочитан одним обращением к
    DOM сразу после появления строки — `pending` («проверяется», без ссылки) или уже `clean` (у EICAR — `pending` или
    уже `quarantine`). Отказ — `AssertionError` с кодом. Дальше — `wait_file_clean` (предел 1 минута, NFR-505)."""
    refused, file_id, seen = _attach(page, list_id, number, code, data, name, mime)
    assert not refused, f"файл «{name}» отклонён: {refused}"
    return file_id, seen


def wait_file_clean(page, list_id, number, file_id, *, timeout: float = 60.0) -> str:
    """Опрос карточки до `timeout` с (пауза 2 с, перезагрузка): ждёт, пока `data-scan` строки файла перестанет быть
    `pending`. Возвращает `"clean"` или `"quarantine"`; по истечении срока — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        open_record(page, list_id, number)
        row = record_file_row(page, file_id)
        expect(row).to_have_count(1)
        state = scan_snapshot(page, file_id)["state"]
        if state in ("clean", "quarantine"):
            return state
        if time.monotonic() > deadline:
            raise AssertionError(f"проверка файла не закончилась за {timeout:.0f} с")
        page.wait_for_timeout(2000)


# --- Команда стенда e2e_lists_shift (13.1) --------------------------------------------------------------------

def parse_shift_line(line: str) -> dict:
    """Разбирает строку `lists_shift: days=<N> shifted=<n> notified=<n>` в `{"days": N, "shifted": n,
    "notified": n}` (числа — `int`); иной вид строки — `AssertionError`."""
    assert line.startswith("lists_shift: "), f"строка вывода не команды e2e_lists_shift: {line!r}"
    out = helpers_kb.parse_kb_line(line)
    assert set(out) == _SHIFT_KEYS and all(isinstance(v, int) for v in out.values()), f"строка вывода {line!r}"
    return out


def shift(days: int) -> dict:
    """`e2e_lists_shift --days N` (13.1) через `helpers_sd._stand_command` (служба `standtools`, `E2E_STAND=1`):
    сдвигает значения полей-сроков ВСЕХ записей стенда и `ReminderSent.due_date` на N дней назад, затем обходит
    сроки. N — целое 1…3650 (иначе `ValueError` до вызова). Возвращает `{"days", "shifted", "notified"}`."""
    days = int(days)
    if not 1 <= days <= 3650:
        raise ValueError("days должно быть целым от 1 до 3650")
    return parse_shift_line(helpers_sd._stand_command("e2e_lists_shift", "--days", days))


# --- Письма (Mailpit) и Telegram (fakebots): готовое из прежних срезов ----------------------------------------

def mail_ids(mailpit, to: str) -> set:
    """Номера писем Mailpit на адрес `to` (`helpers.mail_ids`): передайте их в `seen`, чтобы ждать только новые."""
    return helpers.mail_ids(mailpit, to)


def item_mail(mailpit, to: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое письмо об одном уведомлении (`notify.item`, вид `lists.deadline` идёт тем же шаблоном) на `to`: полный
    текст Mailpit (`helpers_notify.wait_item_mail`); не пришло — `AssertionError`."""
    return helpers_notify.wait_item_mail(mailpit, to, seen=seen, timeout=timeout)


def no_item_mail(mailpit, to: str, *, seen=(), wait: float = 4.0) -> bool:
    """True, если за `wait` с нового письма `notify.item` на `to` нет (`helpers_notify.no_item_mail`)."""
    return helpers_notify.no_item_mail(mailpit, to, seen=seen, wait=wait)


bots = helpers_kb.bots                    # клиент `fakebots` без сброса; свои сообщения — по своему `chat_id`
bind_telegram = helpers_kb.bind_telegram  # привязка Telegram кодом (канал включает `helpers_notify.channels_on`)
wait_telegram = helpers_kb.wait_telegram  # ждать сообщения бота в чат `chat_id`, подстрока `text_has`


# --- QR этикетки (решение 10 задач; 11.9) ---------------------------------------------------------------------

_QR_PREFIX = "data:image/svg+xml;base64,"


def qr_svg_variants(url: str) -> tuple:
    """Байты SVG той же генерации, что в продукте (`qrcode.make(url, image_factory=SvgPathImage, box_size=10,
    border=4)`; `qrcode` 8.2 хостового окружения): `(save в поток, to_string)` — продукт кладёт в `src` один из этих
    двух видов «байтов SVG» (раздел 5.7 контракта не уточняет вид)."""
    import io

    import qrcode
    from qrcode.image.svg import SvgPathImage

    image = qrcode.make(url, image_factory=SvgPathImage, box_size=10, border=4)
    stream = io.BytesIO()
    image.save(stream)
    return stream.getvalue(), image.to_string()


def qr_image_bytes(img) -> bytes:
    """Байты SVG из `src` картинки `img[data-lists-qr]` (`data:image/svg+xml;base64,…`); иной `src` — `AssertionError`."""
    src = img.get_attribute("src") or ""
    assert src.startswith(_QR_PREFIX), f"src QR не data-URI SVG: {src[:40]!r}"
    return base64.b64decode(src[len(_QR_PREFIX):])


def qr_matches(img) -> bool:
    """True, если SVG картинки `img[data-lists-qr]` побайтно совпадает с генерацией для адреса из её же атрибута
    `data-qr-url` (адрес берётся дословно: при другом виде адреса байты разойдутся — факт T-6006)."""
    url = img.get_attribute("data-qr-url")
    assert url, "у картинки QR нет data-qr-url"
    return qr_image_bytes(img) in qr_svg_variants(url)


# --- Ширина 360 px (NFR-507) ----------------------------------------------------------------------------------

narrow_context = helpers_kb.narrow_context  # (browser, browser_context_args, source_page, *, height=740)
page_fits = helpers_kb.page_fits            # scrollWidth <= innerWidth у документа
scrolls_inside = helpers_kb.scrolls_inside  # блок шире себя и overflow-x auto/scroll


def open_narrow(browser, browser_context_args, source_page, path: str, page_hook: str):
    """Контекст 360 px с сессией `source_page` и страница `path`; ждёт `[data-lists-page="<page_hook>"]`.
    Возвращает `(context, page)`; контекст закрывает вызывающий (`finally: context.close()`)."""
    context = narrow_context(browser, browser_context_args, source_page)
    page = context.new_page()
    page.goto(path)
    expect(page.locator(f'[data-lists-page="{page_hook}"]')).to_be_visible()
    return context, page
