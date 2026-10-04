"""Помощники приёмки Playwright среза 002 (T-2140; ими пользуются T-2141…T-2150).

Что даёт модуль: дерево и карточка узла страницы «Структура», создание и правка узлов, диалог
удаления, меню «…» участника, добавление людей и отметки, роли узла, загрузка файла в форму,
ожидание проверки фото (опрос до минуты), путь к файлу календаря и прямые POST-запросы с токеном CSRF.

Правила (шаблон задания e2e/template.md):
- локаторы — только зацепки `data-*`, маршруты и поля форм из tests/CONTRACT-002.md (§ 8, § 9, дополнения);
- ожидание — `expect(...)` и `wait_for_url`; `sleep` только в опросе `wait_photo_checked`;
- код приложения (`apps.*`, `django`) не импортируется: тесты идут с хоста против стенда;
- дерево растёт за круг (другие тесты заводят свои узлы): узлы ищутся по номеру, а имена уникальны
  (`unique_name`); корень ищется по положению в дереве, а не по названию «ИТ-отдел» (его можно переименовать).
"""
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.conftest import PORTAL_URL

ROOT_NAME = "ИТ-отдел"  # название корня на новой установке (SPEC-002, сценарий 1, п. 7)
CALENDAR_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "calendar"


def unique_name(prefix: str) -> str:
    """Уникальное название узла или ФИО: `<prefix>-<6 hex>` (стенд между тестами круга не сбрасывается)."""
    return f"{prefix}-{secrets.token_hex(3)}"


# --- Дерево и карточка узла (§ 9.1) --------------------------------------------------------

def open_structure(page, unit_id=None) -> None:
    """Открывает `/structure/` (или `/structure/<id>/`) и ждёт дерево `[data-unit-tree]` и карточку `#unit-card`.
    С номером узла ещё ждёт, что его ссылка в дереве видна (предки выбранного узла раскрыты) и помечена
    `aria-current="true"`."""
    page.goto("/structure/" if unit_id is None else f"/structure/{unit_id}/")
    expect(page.locator("[data-unit-tree]")).to_be_visible()
    expect(page.locator("#unit-card")).to_be_visible()
    if unit_id is not None:
        expect(unit_link(page, unit_id)).to_be_visible()
        expect(unit_link(page, unit_id)).to_have_attribute("aria-current", "true")


def root_id(page) -> str:
    """Номер корня: единственный `li[data-unit-id]` верхнего уровня `[data-unit-tree]` (по положению, не по названию)."""
    top = page.locator("[data-unit-tree] > li[data-unit-id]")
    expect(top).to_have_count(1)
    return top.get_attribute("data-unit-id")


def unit_li(page, unit_id):
    """Узел дерева `li[data-unit-id="<id>"]` внутри `[data-unit-tree]` (в нём и атрибуты `data-kind`, `data-own`)."""
    return page.locator(f'[data-unit-tree] li[data-unit-id="{unit_id}"]')


def unit_link(page, unit_id):
    """Ссылка узла `a[data-unit-link][href="/structure/<id>/"]` (у выбранного — `aria-current="true"`)."""
    return page.locator(f'[data-unit-tree] a[data-unit-link][href="/structure/{unit_id}/"]')


def unit_id_by_name(page, name: str) -> str:
    """Номер узла по названию на открытой странице «Структура»: ссылка `a[data-unit-link]` с этим текстом
    (название должно быть уникальным, `unique_name`). Ссылка может лежать в свёрнутом `<details>`."""
    link = page.locator("[data-unit-tree] a[data-unit-link]", has_text=name)
    expect(link).to_have_count(1)
    return re.search(r"/structure/(\d+)/", link.get_attribute("href")).group(1)


def descendant_li(page, ancestor_id, unit_id):
    """Узел `unit_id`, лежащий в дереве внутри узла `ancestor_id` (на любой глубине): `li[ancestor] li[unit]`."""
    return page.locator(f'[data-unit-tree] li[data-unit-id="{ancestor_id}"] li[data-unit-id="{unit_id}"]')


def unit_card(page):
    """Карточка выбранного узла: `#unit-card [data-unit-card]` (в ней `data-unit-id`, `data-kind`)."""
    return page.locator("#unit-card [data-unit-card]")


def select_unit(page, unit_id, *, via_url: bool = False) -> None:
    """Выбирает узел в дереве: если ссылка `a[data-unit-link]` скрыта в свёрнутых `<details>`, щелчками по переключателю
    `summary [data-unit-toggle]` закрытых предков (доп. 53; снаружи внутрь) раскрывает их, затем щелчок по ссылке
    (HTMX, цель `#unit-card`, адрес в строке браузера меняется на `/structure/<id>/`). `via_url=True` — открыть страницу узла по адресу (для тестов, которым
    раскрытие дерева не важно). Ждёт карточку `[data-unit-card][data-unit-id]` этого узла."""
    link = unit_link(page, unit_id)
    expect(link).to_have_count(1)
    if via_url:
        page.goto(f"/structure/{unit_id}/")
    else:
        ancestors = link.locator("xpath=ancestor::li[@data-unit-id]").all()  # в порядке документа: снаружи внутрь
        for ancestor in ancestors:
            ancestor_id = ancestor.get_attribute("data-unit-id")
            if ancestor_id == str(unit_id):
                continue
            closed = page.locator(
                f'[data-unit-tree] li[data-unit-id="{ancestor_id}"] > details:not([open]) > summary [data-unit-toggle]')  # доп. 53
            if closed.count():
                closed.first.click()
        expect(link).to_be_visible()
        link.click()
    expect(page.locator(f'#unit-card [data-unit-card][data-unit-id="{unit_id}"]')).to_be_visible()
    page.wait_for_url(re.compile(rf"/structure/{unit_id}/$"))


def card_text(page, hook: str) -> str:
    """Текст поля карточки узла: `hook` — `name` (`[data-unit-name]`), `description` (`[data-unit-description]`),
    `parent` (`[data-unit-parent]`)."""
    selectors = {"name": "[data-unit-name]", "description": "[data-unit-description]",
                 "parent": "[data-unit-parent]"}
    return unit_card(page).locator(selectors[hook]).inner_text().strip()


def unit_role_names(page) -> list:
    """Названия ролей узла в карточке: тексты `[data-unit-role]`."""
    return [t.strip() for t in unit_card(page).locator("[data-unit-role]").all_inner_texts()]


# --- Формы узла (§ 8.3, § 9.8) -------------------------------------------------------------

def set_choice(form, name: str, value) -> None:
    """Выбирает значение поля формы, не зная вида элемента (контракт называет только имя поля): переключатель
    `input[type=radio][name][value]` — отмечает; `select[name]` — выбирает пункт; иное поле `[name]` — заполняет."""
    value = str(value)
    radio = form.locator(f'input[type=radio][name="{name}"][value="{value}"]')
    if radio.count():
        radio.check()
        return
    select = form.locator(f'select[name="{name}"]')
    if select.count():
        select.select_option(value)
        return
    form.locator(f'[name="{name}"]').fill(value)


def create_unit(page, name: str, *, kind: str = "department", parent_id=None, description: str = "") -> str:
    """Создаёт узел формой `form[data-form="unit-new"]` на `/structure/new/?parent=<id>` (обычный GET — страница
    целиком, § 9.8); поля `kind`, `name`, `description`, `parent`. Ждёт 302 на `/structure/<новый id>/`,
    возвращает номер нового узла. Без `parent_id` — «Подчиняется» берётся из формы как есть (корень)."""
    page.goto("/structure/new/" + (f"?parent={parent_id}" if parent_id is not None else ""))
    form = page.locator('form[data-form="unit-new"]')
    expect(form).to_be_visible()
    set_choice(form, "kind", kind)
    form.locator("[name=name]").fill(name)
    if description:
        form.locator("[name=description]").fill(description)
    if parent_id is not None:
        set_choice(form, "parent", parent_id)
    form.locator("button[type=submit]").click()
    page.wait_for_url(re.compile(r"/structure/(?!new)\d+/$"))
    new_id = re.search(r"/structure/(\d+)/", page.url).group(1)
    expect(unit_link(page, new_id)).to_be_visible()  # новый узел виден в дереве (предки раскрыты)
    return new_id


def try_create_unit(page, name: str, *, kind: str = "department", parent_id=None, description: str = "") -> str:
    """Та же форма `unit-new`, но ждёт отказа: возвращает текст `[role=alert]` (ответ 200, узел не создан)."""
    page.goto("/structure/new/" + (f"?parent={parent_id}" if parent_id is not None else ""))
    form = page.locator('form[data-form="unit-new"]')
    expect(form).to_be_visible()
    set_choice(form, "kind", kind)
    form.locator("[name=name]").fill(name)
    if description:
        form.locator("[name=description]").fill(description)
    if parent_id is not None:
        set_choice(form, "parent", parent_id)
    form.locator("button[type=submit]").click()
    expect(page.locator("[role=alert]").first).to_be_visible()
    return helpers.alert_text(page)


def edit_unit(page, unit_id, *, name=None, description=None, parent_id=None) -> None:
    """Правит узел формой `form[data-form="unit-edit"]` на `/structure/<id>/edit/`: поля `name`, `description`,
    `parent` (только заданные). Ждёт 302 на `/structure/<id>/`."""
    _fill_edit(page, unit_id, name=name, description=description, parent_id=parent_id)
    page.wait_for_url(re.compile(rf"/structure/{unit_id}/$"))


def try_edit_unit(page, unit_id, *, name=None, description=None, parent_id=None) -> str:
    """Та же форма `unit-edit`, но ждёт отказа: возвращает текст `[role=alert]` (ответ 200, ничего не изменено)."""
    _fill_edit(page, unit_id, name=name, description=description, parent_id=parent_id)
    expect(page.locator("[role=alert]").first).to_be_visible()
    return helpers.alert_text(page)


def _fill_edit(page, unit_id, *, name, description, parent_id) -> None:
    page.goto(f"/structure/{unit_id}/edit/")
    form = page.locator('form[data-form="unit-edit"]')
    expect(form).to_be_visible()
    if name is not None:
        form.locator("[name=name]").fill(name)
    if description is not None:
        form.locator("[name=description]").fill(description)
    if parent_id is not None:
        set_choice(form, "parent", parent_id)
    form.locator("button[type=submit]").click()


def open_delete_dialog(page, unit_id):
    """Выбирает узел и нажимает `[data-action="unit-delete"]` в карточке: диалог
    `#dialog-root [data-dialog="unit-delete"]` (роль `dialog`). Возвращает локатор диалога."""
    open_structure(page, unit_id)
    unit_card(page).locator('[data-action="unit-delete"]').click()
    dialog = page.locator('#dialog-root [data-dialog="unit-delete"]')
    expect(dialog).to_be_visible()
    return dialog


def confirm_delete(page, dialog) -> None:
    """Подтверждает диалог удаления: `form[data-form="unit-delete"]` (флажок `confirm`, если есть, отмечается),
    кнопка отправки. Результат не ждёт: успех — диалога больше нет (`/structure/`), отказ — `[role=alert]`."""
    helpers.submit(dialog.locator('form[data-form="unit-delete"]'))


# --- Участники: добавление, меню «…», отметки (§ 8.3, § 9.1, § 9.2, § 9.8) ---------------------

def member_row(page, user_id, section=None):
    """Строка участника `[data-member][data-user-id]` в карточке; `section` — `heads`, `deputies`, `members`
    (зацепка `[data-section]`), без него — в любом разделе карточки."""
    scope = unit_card(page)
    if section:
        scope = scope.locator(f'[data-section="{section}"]')
    return scope.locator(f'[data-member][data-user-id="{user_id}"]')


def member_menu(page, user_id):
    """Раскрывает меню «…» участника (`<details data-member-menu>`, кнопка `summary[data-member-menu-button]`)
    и возвращает его локатор; пункты — `[data-menu-item="transfer|remove|dismiss"]`."""
    menu = member_row(page, user_id).locator("[data-member-menu]").first
    expect(menu).to_be_visible()
    menu.locator("summary[data-member-menu-button]").click()
    return menu


def transfer_member(page, user_id, target_id) -> None:
    """Меню «…» → «Перевести»: `form[data-form="member-transfer"]`, `select[name=target]` = узел `target_id`,
    отправка. Результат не ждёт (302 на карточку исходного узла; отказ — `[role=alert]`)."""
    form = member_menu(page, user_id).locator('form[data-form="member-transfer"]')
    set_choice(form, "target", target_id)
    form.locator("button[type=submit]").click()


def remove_member(page, user_id) -> None:
    """Меню «…» → «Удалить из отдела/команды»: `form[data-form="member-remove"]`, отправка."""
    form = member_menu(page, user_id).locator('form[data-form="member-remove"]')
    form.locator("button[type=submit]").click()


def add_members(page, unit_id, user_ids, *, q: str = "", mode=None) -> str:
    """«Добавить сотрудников»: открывает `/structure/<id>/`, раскрывает `<details data-action="members-add">`,
    ищет кандидатов полем `input[name=q]` (запрос `…/candidates/`, ждёт ответ), отмечает
    `label[data-candidate][data-user-id] input[name=users]` для каждого из `user_ids`, у отдела выбирает
    `select[name=mode]` (`transfer`/`concurrent`), отправляет `form[data-form="members-add"]`. Один запрос `q`
    должен находить всех добавляемых (выбор между запросами не сохраняется): заводи людей с общей уникальной частью ФИО.
    Возвращает текст `[role=status]` или `[role=alert]` страницы после ответа (например «уже участник»)."""
    page.goto(f"/structure/{unit_id}/")
    details = page.locator('#unit-card details[data-action="members-add"]')
    expect(details).to_have_count(1)
    details.locator("summary").first.click()
    form = details.locator('form[data-form="members-add"]')
    if q:
        with page.expect_response(lambda r: "/candidates/" in r.url and r.status == 200):
            form.locator("input[name=q]").fill(q)
    for user_id in user_ids:
        box = form.locator(f'label[data-candidate][data-user-id="{user_id}"] input[name=users]')
        box.check()
    if mode is not None:
        set_choice(form, "mode", mode)
    with page.expect_navigation():  # ждём сам ответ POST (доп. 51), а не появление сообщения
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    return (helpers.status_text(page) + " " + helpers.alert_text(page)).strip()


def set_marks(page, unit_id, part: str, user_ids) -> str:
    """Отметки: `<details data-action="marks-<part>">` (`part` — `heads` или `deputies`), в форме
    `form[data-form="marks-<part>"]` отмечены ровно `user_ids` среди `input[name=users]`, остальные сняты;
    отправка. Возвращает текст `[role=status]`/`[role=alert]` после ответа."""
    page.goto(f"/structure/{unit_id}/")
    details = page.locator(f'#unit-card details[data-action="marks-{part}"]')
    expect(details).to_have_count(1)
    details.locator("summary").first.click()
    form = details.locator(f'form[data-form="marks-{part}"]')
    wanted = {str(u) for u in user_ids}
    boxes = form.locator("input[name=users]")
    for box in boxes.all():
        box.set_checked(box.get_attribute("value") in wanted)
    with page.expect_navigation():  # ждём сам ответ POST (доп. 51), а не появление сообщения
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    return (helpers.status_text(page) + " " + helpers.alert_text(page)).strip()


def role_id(page, role_name: str) -> str:
    """Номер роли по названию на `/roles/` (`[data-role-id][data-role-name]`, срез 001)."""
    page.goto("/roles/")
    row = page.locator(f'[data-role-id][data-role-name="{role_name}"]')
    expect(row).to_have_count(1)
    return row.get_attribute("data-role-id")


def set_unit_roles(page, unit_id, role_ids) -> str:
    """Роли узла (нужно `roles.manage`): `<details data-action="unit-roles">`, `form[data-form="unit-roles"]`,
    флажки `input[name=roles]` — отмечены ровно `role_ids`; отправка. Возвращает текст статуса или отказа."""
    page.goto(f"/structure/{unit_id}/")
    details = page.locator('#unit-card details[data-action="unit-roles"]')
    expect(details).to_have_count(1)
    details.locator("summary").first.click()
    form = details.locator('form[data-form="unit-roles"]')
    wanted = {str(r) for r in role_ids}
    for box in form.locator("input[name=roles]").all():
        box.set_checked(box.get_attribute("value") in wanted)
    with page.expect_navigation():  # ждём сам ответ POST (доп. 51), а не появление сообщения
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    return (helpers.status_text(page) + " " + helpers.alert_text(page)).strip()


# --- Прямые запросы (FR-103, FR-123) ---------------------------------------------------------

def csrf_token(page) -> str:
    """Токен CSRF из куки `csrftoken` контекста страницы (кука HttpOnly, но Playwright её видит); если её ещё
    нет, открывает `/me/` (там форма) и читает снова."""
    for attempt in range(2):
        for cookie in page.context.cookies():
            if cookie["name"] == "csrftoken":
                return cookie["value"]
        if attempt == 0:
            page.goto("/me/")
    raise AssertionError("у страницы нет куки csrftoken")


def direct_post(page, path: str, data: dict | None = None):
    """Прямой POST от имени страницы (сессия и кука — её): с `X-CSRFToken`, `Referer` и `Origin` портала,
    без перехода по редиректам (`max_redirects=0`), поэтому 302 остаётся 302, а ответ 200 — именно 200.
    Так ответ 403 означает отказ по праву, а не по CSRF. Возвращает ответ Playwright."""
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(PORTAL_URL))
    return page.request.post(path, form=data or {}, max_redirects=0, headers={
        "X-CSRFToken": csrf_token(page), "Referer": origin + "/", "Origin": origin})


def direct_get(page, path: str):
    """Прямой GET от имени страницы, без перехода по редиректам: статус виден как есть."""
    return page.request.get(path, max_redirects=0)


def has_alert(response) -> bool:
    """В теле ответа есть `role="alert"` (отказ службы — 200 с `[role=alert]`, § 8)."""
    return re.search(r'role=["\']?alert', response.text()) is not None


# --- Журнал ------------------------------------------------------------------------------------

def audit_rows(admin_page, action: str, object_id=None) -> list:
    """Тексты строк журнала `tr[data-event-id][data-action="<код>"]` (первая страница, фильтр `action`, при
    необходимости `object_id`); новые события сверху. Фильтр `object_id` — точное равенство (срез 001,
    audit_search.py:115; CONTRACT-002, доп. 52), поэтому по номеру узла событие одно."""
    query = f"action={action}" + (f"&object_id={object_id}" if object_id is not None else "")
    admin_page.goto(f"/audit/?{query}")
    return [r.inner_text() for r in admin_page.locator(f'tr[data-event-id][data-action="{action}"]').all()]


# --- Файлы и фото ----------------------------------------------------------------------------------

def upload_file(form, file, *, field: str = "file", name: str = "upload.bin", mime: str = "application/octet-stream",
                submit: bool = True) -> None:
    """Кладёт файл в `input[type=file][name=<field>]` формы (локатор `form`) и отправляет её.
    `file` — путь (`Path`/`str`) или `bytes` (тогда `name` и `mime` задают имя и тип). Поля: `file` (календарь,
    сотрудники), `photo` (`/me/photo/`)."""
    chooser = form.locator(f'input[type=file][name="{field}"]')
    if isinstance(file, (bytes, bytearray)):
        chooser.set_input_files({"name": name, "mimeType": mime, "buffer": bytes(file)})
    else:
        chooser.set_input_files(str(file))
    if submit:
        form.locator("button[type=submit]").click()


def wait_photo_checked(page, url: str = "/me/", *, timeout: float = 60.0) -> str:
    """Опрос страницы `url` до `timeout` секунд (пауза 2 с, перезагрузка страницы): ждёт, пока в `[data-card]`
    исчезнет `[data-photo-status="pending"]`. Возвращает `"clean"` (есть `img[data-photo-img]`, статусов нет)
    или `"failed"` (`[data-photo-status="failed"]`); по истечении срока — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        page.goto(url)
        card = page.locator("[data-card]").first
        expect(card).to_be_visible()
        if card.locator('[data-photo-status="failed"]').count():
            return "failed"
        if not card.locator('[data-photo-status="pending"]').count() and card.locator("img[data-photo-img]").count():
            return "clean"
        if time.monotonic() > deadline:
            raise AssertionError(f"проверка фото не закончилась за {timeout:.0f} с")
        page.wait_for_timeout(2000)


def calendar_fixture(name: str) -> Path:
    """Путь файла `tests/fixtures/calendar/<name>` (`cal2026.csv`, `years_2024_2027.csv`, `bad_totals_2026.csv` и др.,
    CONTRACT-002 § 1). Отличие от `support_org.calendar_fixture`: возвращает путь, а не байты (для `upload_file`)."""
    path = CALENDAR_FIXTURES / name
    if not path.is_file():
        raise FileNotFoundError(f"нет файла календаря {name}")
    return path
