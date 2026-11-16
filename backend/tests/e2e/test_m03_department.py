"""T-8133: приёмка сценария 3 — чат отдела (FR-649, FR-650, FR-671, FR-672).

Сценарий 3 SPEC-008 и пять пунктов его приёмки:
1. галочка «Создадим чат для всего отдела» в форме отдела — чат создан, в нём системные записи «Создал чат» и
   «К чату присоединились сотрудники отдела «…»», участники — сотрудники отдела и вложенных отделов на момент
   просмотра (FR-649, FR-650);
2. перевод сотрудника в другой отдел с созданным чатом — выбывает из прежнего и видит чат нового (FR-650);
3. принятый в отдел после создания чата сразу видит чат и прежнюю историю (FR-650);
4. удаление подразделения — чат и история удаляются, в журнал идёт `messenger.unit_chat_deleted` без текста
   (FR-650, FR-671);
5. администратор портала удаляет чат отдела с подтверждением — чат и история исчезают у всех, журнал
   `messenger.department_chat_deleted` без текста (FR-672, FR-671).

Как устроен файл (CONTRACT-008: 10.1–10.2 — маршруты и второй шаг подтверждения, 12.1–12.6 — зацепки, 13.3 —
тексты интерфейса, 14.3 — помощники; план, «Проход в браузере», «Системные записи чата отдела», «Журнал»):
- роли и учётки — `helpers_messenger.messenger_cast` один раз на круг браузера (восемь мастеров активации на
  каждый тест были бы часами прохода); узлы и чаты каждый тест заводит свои, чтобы тесты файла не зависели от
  порядка и не спорили за один чат (узлы круга «Отдел ИТ», «Группа сети», «Бухгалтерия» остаются запасными);
- галочка: на создании узла поля ещё нет (`render` получает `unit=None` — так решено в T-8127), поэтому
  «создание отдела с чатом» — это создание узла и сразу галочка в его форме (CONTRACT-008 12.6); после сохранения
  форма показывает «Чат отдела создан» без галочки;
- состав чата отдела не материализуется (FR-650): проверяется видимостью у участника вложенного узла и именами
  участников в шапке беседы, а не строками состава;
- удаление чата администратором идёт по маршруту `POST /messenger/chats/<id>/delete/` (кнопку удаления контракт не
  зацепляет): без `confirm` — 200 со вторым шагом `[data-messenger-confirm]` и текстом «Удалить чат вместе с
  историей?», с `confirm=1` — 302 на `/messenger/`;
- журнал читается страницей `/audit/` с фильтром `action` и `object_id` (`helpers_org.audit_sides`): в «стало» —
  название отдела и номер подразделения, текста переписки нет (FR-671);
- ожидания — только `expect(...)` и `wait_for_url`; сна нет; пропусков нет (стенд недоступен — тест падает);
- секретов и ПДн нет: почта и телефоны не печатаются, в отчётах — `***`.
"""
import re

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_messenger, helpers_org

LABEL = "Создадим чат для всего отдела"          # подпись галочки (CONTRACT-008 12.6)
CREATED = "Чат отдела создан"                    # правка отдела с чатом (12.6)
SYSTEM_CREATED = "Создал чат"                    # системная запись (13.3)
SYSTEM_JOINED = "К чату присоединились сотрудники отдела «{name}»"
DELETE_CONFIRM = "Удалить чат вместе с историей?"  # второй шаг удаления (13.1)
UNIT_CHAT_DELETED = "messenger.unit_chat_deleted"        # журнал удаления узла (8.1)
ADMIN_CHAT_DELETED = "messenger.department_chat_deleted"  # журнал удаления админом (8.1)

_CASTS: dict = {}   # браузер → `MessengerCast`


# --- Круг сценария ----------------------------------------------------------------------------------------------

@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Учётки и узлы сценария — один раз на круг браузера (`helpers_messenger.messenger_cast`); сессии лежат в
    `Account.storage_state`, поэтому каждый тест берёт их без повторной активации."""
    key = browser.e2e_project
    if key not in _CASTS:
        _CASTS[key] = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
    return _CASTS[key]


# --- Общие приёмы файла ----------------------------------------------------------------------------------------

def _surname(account) -> str:
    """Фамилия с уникальной частью круга: в шапке беседы бывает и «Фамилия И. О.», и полное ФИО."""
    return account.full_name.split()[0]


def _query(account) -> str:
    """Строка поиска кандидатов: шестизначная часть ФИО круга (так ищет `messenger_cast`), иначе фамилия."""
    found = re.search(r"[0-9a-f]{6}$", _surname(account))
    return found.group(0) if found else _surname(account)


def _add(page, unit_id, account, *, mode=None) -> None:
    """Принимает сотрудника в узел через интерфейс «Добавить сотрудников» (своих участников тест не заводит)."""
    helpers_org.add_members(page, unit_id, [account.id], q=_query(account), mode=mode)


def _list(new_context, account):
    """Список чатов `#messenger-list` открытого мессенджера: строку беседы тест находит по названию отдела."""
    return helpers_messenger.open_messenger(new_context(), account, live=False)


def _unit_form(page, unit_id):
    """Форма правки узла `form[data-form="unit-edit"]` на `/structure/<id>/edit/`."""
    page.goto(f"/structure/{unit_id}/edit/")
    form = page.locator('form[data-form="unit-edit"]')
    expect(form).to_be_visible()
    return form


def _department_with_chat(page, name: str, parent_id) -> str:
    """Отдел с чатом: создание узла, затем галочка `input[name="messenger_chat"]` в форме узла и сохранение.

    Возвращает номер узла. После сохранения форма показывает «Чат отдела создан» и галочки больше нет
    (CONTRACT-008 12.6; FR-649 — чат по галочке при создании или изменении подразделения)."""
    unit_id = helpers_org.create_unit(page, name, kind="department", parent_id=parent_id)
    form = _unit_form(page, unit_id)
    expect(form.locator("[data-messenger-unit-field]")).to_have_count(1)
    expect(form).to_contain_text(LABEL)
    checkbox = form.locator('input[name="messenger_chat"][type="checkbox"]')
    expect(checkbox).to_have_count(1)
    checkbox.check()
    form.locator("button[type=submit]").first.click()
    page.wait_for_url(re.compile(rf"/structure/{unit_id}/$"))

    form = _unit_form(page, unit_id)
    expect(form.locator('input[name="messenger_chat"]')).to_have_count(0)
    expect(page.locator("body")).to_contain_text(CREATED)
    return unit_id


def _chat_id(page, name: str) -> int:
    """Номер чата из списка `#messenger-list` по названию отдела (строка `[data-chat-id]`, 12.2)."""
    rows = page.locator("#messenger-list [data-chat-id]", has_text=name)
    expect(rows).to_have_count(1)
    return int(rows.first.get_attribute("data-chat-id"))


def _chat_page(new_context, account, chat_id):
    """Беседа `chat_id` глазами участника: страница открыта, история и `[data-chat-kind]` на месте."""
    return helpers_messenger.open_chat(new_context(), account, chat_id)


def _page_text(page) -> str:
    """Текст содержимого страницы беседы (шапка с участниками, история, форма)."""
    return page.locator('[data-messenger-page="chat"]').inner_text()


def _journal(admin_page, action: str, chat_id) -> list:
    """Пары («было», «стало») журнала по действию и номеру чата (8.1: объект — `messenger.chat`)."""
    return helpers_org.audit_sides(admin_page, action, chat_id)


# --- Пункт 1: галочка, системные записи, состав с вложенным отделом (FR-649, FR-650) ---------------------------

def test_department_chat_by_checkbox_with_system_notes_and_nested_members(admin_page, new_context, cast):
    """П. 1: галочка в форме отдела создаёт чат с названием отдела и двумя системными записями; участники —
    сотрудники отдела и вложенного узла на момент просмотра; сотрудник чужого отдела чат не видит (FR-649,
    FR-650)."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name = helpers_org.unique_name("Отдел ИТ")
    unit_id = _department_with_chat(admin_page, name, root)
    team_id = helpers_org.create_unit(admin_page, helpers_org.unique_name("Группа сети"), kind="team",
                                      parent_id=unit_id)
    _add(admin_page, unit_id, cast.department_member, mode="concurrent")
    _add(admin_page, team_id, cast.writer)

    member_page = _list(new_context, cast.department_member)
    chat_id = _chat_id(member_page, name)

    chat = _chat_page(new_context, cast.department_member, chat_id)
    expect(chat.locator('[data-chat-kind="department"]')).to_have_count(1)
    text = _page_text(chat)
    assert name in text, f"в шапке беседы нет названия отдела {name!r}: {text[:400]!r}"
    history = chat.locator("#messenger-messages")
    expect(history).to_contain_text(SYSTEM_CREATED)
    expect(history).to_contain_text(SYSTEM_JOINED.format(name=name))
    assert _surname(cast.writer) in text, "в шапке беседы нет сотрудника вложенного узла"
    assert _surname(cast.outsider) not in text, "в шапке беседы сотрудник чужого отдела"

    nested_page = _list(new_context, cast.writer)   # участник вложенной команды
    expect(nested_page.locator("#messenger-list [data-chat-id]", has_text=name)).to_have_count(1)

    outside_page = _list(new_context, cast.outsider)  # сотрудник другого отдела
    expect(outside_page.locator("#messenger-list [data-chat-id]", has_text=name)).to_have_count(0)
    assert helpers_org.direct_get(outside_page, f"/messenger/chats/{chat_id}/").status == 404


# --- Пункты 2–3: перевод сотрудника и приём новичка (FR-650) ---------------------------------------------------

def test_transfer_and_newcomer_see_department_chat_with_history(admin_page, new_context, cast):
    """П. 2, 3: принятый в отдел позже видит чат и прежнюю историю; переведённый в другой отдел с чатом выбывает из
    прежнего чата и видит чат нового отдела; прямой адрес прежней беседы отвечает как несуществующий (FR-650)."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    old_name = helpers_org.unique_name("Отдел приёма")
    old_id = _department_with_chat(admin_page, old_name, root)
    new_name = helpers_org.unique_name("Отдел перевода")
    new_id = _department_with_chat(admin_page, new_name, root)
    _add(admin_page, old_id, cast.department_member, mode="concurrent")

    marker = helpers_org.unique_name("Переписка отдела")
    old_chat_id = _chat_id(_list(new_context, cast.department_member), old_name)
    old_chat = _chat_page(new_context, cast.department_member, old_chat_id)
    helpers_messenger.write(old_chat, marker)

    _add(admin_page, old_id, cast.department_newcomer, mode="concurrent")

    member_chat = _chat_page(new_context, cast.department_member,
                            _chat_id(_list(new_context, cast.department_member), old_name))
    assert _surname(cast.department_newcomer) in _page_text(member_chat), \
        "новичок не появился в участниках чата на момент просмотра"

    newcomer_page = _list(new_context, cast.department_newcomer)
    expect(newcomer_page.locator("#messenger-list [data-chat-id]", has_text=old_name)).to_have_count(1)
    newcomer_chat = _chat_page(new_context, cast.department_newcomer,
                               _chat_id(newcomer_page, old_name))
    expect(newcomer_chat.locator("#messenger-messages")).to_contain_text(marker)
    expect(newcomer_chat.locator("#messenger-messages")).to_contain_text(SYSTEM_CREATED)

    helpers_org.open_structure(admin_page, old_id)
    helpers_org.transfer_member(admin_page, cast.department_member.id, new_id)
    expect(helpers_org.member_row(admin_page, cast.department_member.id)).to_have_count(0)

    moved_page = _list(new_context, cast.department_member)
    expect(moved_page.locator("#messenger-list [data-chat-id]", has_text=new_name)).to_have_count(1)
    expect(moved_page.locator("#messenger-list [data-chat-id]", has_text=old_name)).to_have_count(0)
    assert helpers_org.direct_get(moved_page, f"/messenger/chats/{old_chat_id}/").status == 404

    moved_chat = _chat_page(new_context, cast.department_member, _chat_id(moved_page, new_name))
    expect(moved_chat.locator('[data-chat-kind="department"]')).to_have_count(1)
    expect(moved_chat.locator("#messenger-messages")).to_contain_text(SYSTEM_CREATED)
    assert old_name not in _page_text(moved_chat), "в беседе нового отдела чужое название"


# --- Пункт 4: удаление подразделения (FR-650, FR-671) -----------------------------------------------------------

def test_deleted_unit_removes_department_chat_and_writes_journal_without_text(admin_page, new_context, cast):
    """П. 4: после удаления подразделения его чат и история удалены — беседа отвечает 404, в журнале одна запись
    `messenger.unit_chat_deleted` с названием отдела и номером узла без текста переписки (FR-650, FR-671).

    Узел удаляется только пустым, поэтому сотрудник переводится в другой отдел до удаления (план, «Состав чата
    отдела»)."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name = helpers_org.unique_name("Отдел на удаление")
    unit_id = _department_with_chat(admin_page, name, root)
    target_id = helpers_org.create_unit(admin_page, helpers_org.unique_name("Отдел назначения"),
                                        kind="department", parent_id=root)
    _add(admin_page, unit_id, cast.writer, mode="concurrent")

    marker = helpers_org.unique_name("Текст переписки")
    chat_id = _chat_id(_list(new_context, cast.writer), name)
    chat = _chat_page(new_context, cast.writer, chat_id)
    helpers_messenger.write(chat, marker)
    expect(chat.locator("#messenger-messages")).to_contain_text(marker)

    helpers_org.open_structure(admin_page, unit_id)
    helpers_org.transfer_member(admin_page, cast.writer.id, target_id)
    expect(helpers_org.member_row(admin_page, cast.writer.id)).to_have_count(0)

    dialog = helpers_org.open_delete_dialog(admin_page, unit_id)
    helpers_org.confirm_delete(admin_page, dialog)
    expect(admin_page.locator('[data-dialog="unit-delete"]')).to_have_count(0)
    helpers_org.open_structure(admin_page)
    expect(helpers_org.unit_li(admin_page, unit_id)).to_have_count(0)

    moved_page = _list(new_context, cast.writer)
    expect(moved_page.locator("#messenger-list [data-chat-id]", has_text=name)).to_have_count(0)
    assert helpers_org.direct_get(moved_page, f"/messenger/chats/{chat_id}/").status == 404

    sides = _journal(admin_page, UNIT_CHAT_DELETED, chat_id)
    assert len(sides) == 1, f"записей {UNIT_CHAT_DELETED}: {len(sides)}"
    was, became = sides[0]
    assert "название чата" in became.lower() and name in became, f"в журнале нет названия отдела: {became!r}"
    assert "номер подразделения" in became.lower() and str(unit_id) in became, became
    assert marker not in was + became, "в журнале удаления узла есть текст переписки"


# --- Пункт 5: удаление чата отдела администратором портала (FR-672, FR-671) ------------------------------------

def test_portal_admin_deletes_department_chat_with_confirm_and_journal(admin_page, new_context, cast):
    """П. 5: администратор портала удаляет чат отдела с подтверждением — без `confirm` второй шаг «Удалить чат
    вместе с историей?» и чат цел; с `confirm=1` чат и история исчезают у всех участников, в журнале одна запись
    `messenger.department_chat_deleted` с названием отдела и номером узла без текста (FR-672, FR-671)."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name = helpers_org.unique_name("Отдел администратора")
    unit_id = _department_with_chat(admin_page, name, root)
    _add(admin_page, unit_id, cast.department_member, mode="concurrent")
    _add(admin_page, unit_id, cast.writer, mode="concurrent")

    marker = helpers_org.unique_name("Переписка администратора")
    chat_id = _chat_id(_list(new_context, cast.department_member), name)
    chat = _chat_page(new_context, cast.department_member, chat_id)
    helpers_messenger.write(chat, marker)
    expect(chat.locator("#messenger-messages")).to_contain_text(marker)

    expect(_list(new_context, cast.writer)
           .locator("#messenger-list [data-chat-id]", has_text=name)).to_have_count(1)

    first = helpers_org.direct_post(admin_page, f"/messenger/chats/{chat_id}/delete/", {})
    assert first.status == 200, f"первый шаг удаления чата отдела: {first.status}"
    markup = first.text()
    assert "data-messenger-confirm" in markup, "нет второго шага [data-messenger-confirm]"
    assert DELETE_CONFIRM in markup, "нет текста «Удалить чат вместе с историей?»"
    assert re.search(r'name=["\']confirm["\']', markup) and re.search(r'value=["\']1["\']', markup), \
        "нет кнопки подтверждения (12.6)"
    expect(_list(new_context, cast.department_member)
           .locator("#messenger-list [data-chat-id]", has_text=name)).to_have_count(1)

    confirmed = helpers_org.direct_post(admin_page, f"/messenger/chats/{chat_id}/delete/", {"confirm": "1"})
    assert confirmed.status == 302, f"подтверждённое удаление: {confirmed.status}"
    assert confirmed.headers.get("location") == "/messenger/", confirmed.headers.get("location")

    for account in (cast.department_member, cast.writer):
        page = _list(new_context, account)
        expect(page.locator("#messenger-list [data-chat-id]", has_text=name)).to_have_count(0)
        assert helpers_org.direct_get(page, f"/messenger/chats/{chat_id}/").status == 404

    sides = _journal(admin_page, ADMIN_CHAT_DELETED, chat_id)
    assert len(sides) == 1, f"записей {ADMIN_CHAT_DELETED}: {len(sides)}"
    was, became = sides[0]
    assert "название чата" in became.lower() and name in became, f"в журнале нет названия отдела: {became!r}"
    assert "номер подразделения" in became.lower() and str(unit_id) in became, became
    assert marker not in was + became, "в журнале удаления чата есть текст переписки"