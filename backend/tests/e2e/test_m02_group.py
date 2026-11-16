"""T-8132: приёмка сценария 2 — групповой чат (FR-646, FR-647, FR-648, FR-671).

SPEC-008, сценарий 2 «Групповой чат для рабочего вопроса», пункты приёмки 1–5:
1. сотрудник создаёт групповой чат с названием и двумя участниками — чат виден всем троим, сообщения получают все
   участники; пустое название и название длиннее 200 знаков не принимаются с причиной (FR-646);
2. участник выходит — перестаёт видеть чат и получать сообщения, остальные продолжают беседу (FR-647);
3. выходит создатель — чат остаётся у остальных, состав больше не меняется: ни один участник не может добавить
   или удалить участника (FR-646);
4. создатель-участник удаляет чат и подтверждает в окне предупреждения — чат и вся история исчезают у всех
   участников, в журнале появляется запись без текста сообщений (FR-648, FR-671);
5. групповой чат с одним участником: он выходит и подтверждает — чат удаляется вместе с историей (FR-647).

Источники: CONTRACT-008 § 10–10.2 (адреса, поля форм, ответы, 403/404), § 12.2 (`#messenger-list`,
`[data-chat-kind]`), § 12.3 (`[data-messenger-page="chat"]`, `#messenger-messages`, `article#m<id>`),
§ 12.4 (`[data-ws]`), § 12.6 (`[data-messenger-confirm]`), § 13.1 (`title_range`, `delete_confirm`), § 8.1
(`messenger.chat_deleted` — без текста), § 14.3 (помощники `helpers_messenger`); план — «Виды чатов и создание»,
«Журнал»; задачи — T-8132, T-8204.

Решения файла (зацепок формы создания группы, кнопок выхода и удаления CONTRACT-008 § 12 не называет):
- создание чата и отказы названия — по адресу `POST /messenger/chats/` с полями `kind`, `title`, `members`
  (§ 10.2; имена маршрутов свободны, тесты ходят по путям — решение контракта К15), остальное проверяется в
  интерфейсе;
- формы выхода и удаления ищутся по адресу действия `/messenger/chats/<id>/leave/` и `…/delete/` (§ 10);
  второй шаг подтверждения — `[data-messenger-confirm]` (§ 12.6), кнопка `button[name="confirm"][value="1"]`;
- журнал читает администратор круга (`helpers_org.audit_rows`/`audit_sides`): код `messenger.chat_deleted`,
  название чата есть, текста сообщений нет (§ 8.1).

Списка чатов ждём без `[data-ws]` (`open_messenger(..., live=False)`): «Общий чат» мог быть выключен соседним
сценарием того же круга. Люди и узлы — `helpers_messenger.messenger_cast` (один раз на круг браузера). Данные
круга общие, поэтому названия и тексты уникальны (`helpers_org.unique_name`, `_word`). Пропусков (`skip`) нет;
файл — единственный, который правит T-8132.
"""
import re
import secrets

import pytest
from playwright.sync_api import FormData, expect

from tests.e2e import helpers_messenger, helpers_org

_CREATE = "/messenger/chats/"
_LIST_ROW = '#messenger-list [data-chat-id="{chat_id}"]'
_MISSING_CHAT = 2_000_000_000            # номер несуществующего чата (ответ — как у вышедшего)
TITLE_RANGE = "Название чата — от 1 до 200 знаков"   # CONTRACT-008, 13.1
DELETE_CONFIRM = "Удалить чат вместе с историей?"     # CONTRACT-008, 13.1
AUDIT_DELETED = "messenger.chat_deleted"              # CONTRACT-008, 8.1
DEFAULT_TIMEOUT = helpers_messenger.PAGE_TIMEOUT

_CASTS: dict = {}


# --- Люди круга и общие помощники файла ---------------------------------------------------------------------------

@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Люди и узлы сценариев (`helpers_messenger.messenger_cast`), один раз на круг браузера."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        found = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
        _CASTS[stand_admin.email] = found
    return found


def _word() -> str:
    """Уникальное слово из русских букв: тексты сообщений круга не совпадают."""
    return "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(10))


def _chat_url(chat_id) -> str:
    return f"/messenger/chats/{int(chat_id)}/"


def _fields(name: str, values) -> FormData:
    """Данные формы с повторяющимся полем (`members`, `add`, `remove` — CONTRACT-008, 10.2)."""
    data = FormData()
    for value in values:
        data.append(name, str(value))
    return data


def _codes(html: str) -> list:
    """Пары `(поле или "", код)` отказов в HTML ответа (CONTRACT-008, 10.1)."""
    found = []
    for tag in re.findall(r"<[^>]*\bdata-code=\"[^\"]*\"[^>]*>", html):
        code = re.search(r'data-code="([^"]*)"', tag).group(1)
        field = re.search(r'data-error="([^"]*)"', tag)
        found.append((field.group(1) if field else "", code))
    return found


def _create(page, title: str, members) -> tuple:
    """`POST /messenger/chats/` с `kind=group`, названием и участниками (CONTRACT-008, 10.2).

    Возвращает `(ответ, номер чата или None)`: успех — 302 на адрес беседы, отказ — 200 с причиной у поля.
    Создание идёт адресом, потому что § 12 зацепки формы создания группы не называет."""
    data = _fields("members", [account.id for account in members])
    data.set("kind", "group")
    data.set("title", title)
    response = helpers_org.direct_post(page, _CREATE, data)
    if response.status != 302:
        return response, None
    location = response.headers.get("location", "")
    found = re.fullmatch(r"(?:https?://[^/]+)?/messenger/chats/(\d+)/", location)
    assert found, f"после создания чата адрес перехода {location!r}, ожидался /messenger/chats/<id>/"
    return response, int(found.group(1))


def _member_opens(context, account, chat_id, title):
    """Список чатов сотрудника: строка `[data-chat-id="<id>"]` с названием; затем беседа по адресу с
    `[data-ws="open"]` (CONTRACT-008, 12.2, 12.4). Возвращает страницу беседы."""
    page = helpers_messenger.open_messenger(context, account, live=False)
    row = page.locator(_LIST_ROW.format(chat_id=chat_id))
    expect(row).to_be_visible()
    expect(row).to_contain_text(title)
    page.goto(_chat_url(chat_id))
    expect(page.locator('[data-messenger-page="chat"]')).to_be_visible()
    expect(page.locator("[data-ws]")).to_have_attribute("data-ws", "open", timeout=DEFAULT_TIMEOUT)
    return page


def _absent_from_list(page, chat_id) -> None:
    """Чата нет в списке: есть `#messenger-list`, но нет строки `[data-chat-id]` и узла числа (12.2)."""
    page.goto("/messenger/")
    page.wait_for_load_state()
    expect(page.locator("#messenger-list")).to_be_visible()
    expect(page.locator(_LIST_ROW.format(chat_id=chat_id))).to_have_count(0)
    expect(page.locator(f"#chat-{chat_id}-unread")).to_have_count(0)


def _like_missing(page, chat_id) -> None:
    """Чат вышедшему и после удаления отвечает как несуществующий: 404 и «Не найдено» (10.1)."""
    gone = helpers_org.direct_get(page, _chat_url(chat_id))
    missing = helpers_org.direct_get(page, _chat_url(_MISSING_CHAT))
    assert gone.status == missing.status == 404, (gone.status, missing.status)
    assert "Не найдено" in gone.text() and "Не найдено" in missing.text(), chat_id


def _action_form(page, chat_id, action: str):
    """Форма действия беседы по адресу `/messenger/chats/<id>/<action>/` (§ 10; зацепки § 12 нет)."""
    form = page.locator(f'form[action$="/chats/{chat_id}/{action}/"]')
    assert form.count(), f"на странице {page.url} нет формы {action}"
    return form.first


def _post_to(chat_id, action: str):
    """Условие ответа на POST действия беседы."""
    suffix = f"/messenger/chats/{chat_id}/{action}/"
    return lambda response: response.request.method == "POST" and response.url.split("?")[0].endswith(suffix)


def _submit(form) -> None:
    """Отправляет форму: видимая кнопка или `requestSubmit` (кнопка может быть в свёрнутом меню)."""
    button = form.locator('button[type="submit"]').first
    if button.count() and button.is_visible():
        button.click()
    else:
        form.evaluate("node => node.requestSubmit()")


def _leave(page, chat_id):
    """Выход участника формой `…/leave/`; возвращает ответ на POST (302 или второй шаг)."""
    form = _action_form(page, chat_id, "leave")
    with page.expect_response(_post_to(chat_id, "leave")) as info:
        _submit(form)
    return info.value


def _delete(page, chat_id):
    """Первый шаг удаления создателем формой `…/delete/`; возвращает ответ на POST (второй шаг)."""
    form = _action_form(page, chat_id, "delete")
    with page.expect_response(_post_to(chat_id, "delete")) as info:
        _submit(form)
    return info.value


def _confirm_step(page, response, timeout: int = DEFAULT_TIMEOUT):
    """Второй шаг подтверждения: 200 с `[data-messenger-confirm]`, текст «Удалить чат вместе с историей?» и
    `button[name="confirm"][value="1"]` (CONTRACT-008, 10.2, 12.6). Возвращает кнопку подтверждения."""
    assert response.status == 200, f"без confirm ожидался второй шаг, а ответ {response.status}"
    assert "data-messenger-confirm" in response.text(), "в ответе нет [data-messenger-confirm]"
    step = page.locator("[data-messenger-confirm]")
    expect(step).to_be_visible(timeout=timeout)
    expect(step).to_contain_text(DELETE_CONFIRM)
    button = step.locator('button[name="confirm"][value="1"]')
    expect(button).to_have_count(1)
    return button.first


def _confirm(page, button, chat_id, action: str = "delete") -> None:
    """Подтверждение вторым шагом: 302 на `/messenger/` (10.2)."""
    with page.expect_response(_post_to(chat_id, action)) as info:
        button.click()
    assert info.value.status == 302, f"после подтверждения ожидался 302, а ответ {info.value.status}"
    page.wait_for_url(re.compile(r"/messenger/$"))


# --- Сценарий 2, п. 1: создание и отказы названия (FR-646) -------------------------------------------------------

def test_group_with_title_and_two_members_is_visible_to_all_three_and_messages_reach_both(new_context, cast):
    """П. 1 (FR-646): чат с названием и двумя участниками создан; строка с названием есть в списке у всех троих,
    беседа открывается с видом `group`; сообщение автора видят оба участника живым кадром."""
    title = helpers_org.unique_name("Групповой чат")
    page = helpers_messenger.open_messenger(new_context(), cast.creator, live=False)
    response, chat_id = _create(page, title, [cast.writer, cast.peer])
    assert response.status == 302, f"создание чата: ответ {response.status}"
    assert chat_id is not None

    creator_page = helpers_messenger.open_chat(new_context(), cast.creator, chat_id)
    expect(creator_page.locator('[data-messenger-page="chat"]')).to_be_visible()
    expect(creator_page.locator("[data-chat-kind]")).to_have_attribute("data-chat-kind", "group")
    expect(creator_page.locator('[data-messenger-page="chat"]')).to_contain_text(title)

    writer_page = _member_opens(new_context(), cast.writer, chat_id, title)
    peer_page = _member_opens(new_context(), cast.peer, chat_id, title)
    expect(writer_page.locator('[data-messenger-page="chat"]')).to_contain_text(title)
    expect(peer_page.locator('[data-messenger-page="chat"]')).to_contain_text(title)

    text = "Первое сообщение группы " + _word()
    message_id = helpers_messenger.write(creator_page, text)
    for member_page in (writer_page, peer_page):
        helpers_messenger.wait_message(member_page, message_id)
        expect(member_page.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(text)


def test_empty_blank_and_201_char_title_refused_with_reason_and_200_accepted(new_context, cast):
    """П. 1 (FR-646): пустое название, из одних пробелов и длиной 201 знак не принимаются с причиной
    `title_range` у поля `title`; название ровно из 200 знаков принимается и видно в беседе."""
    page = helpers_messenger.open_messenger(new_context(), cast.creator, live=False)
    for title in ("", "   ", "Ж" * 201):
        response, chat_id = _create(page, title, [cast.peer])
        assert chat_id is None, f"название {len(title)} знаков создало чат"
        assert response.status == 200, f"название {len(title)}: ожидался отказ формы, ответ {response.status}"
        codes = _codes(response.text())
        assert ("title", "title_range") in codes, (len(title), codes)
        assert all(code == "title_range" for _, code in codes), (len(title), codes)
        assert TITLE_RANGE in response.text()

    long_title = "Ж" * 200
    response, chat_id = _create(page, long_title, [cast.peer])
    assert response.status == 302, f"название 200 знаков: ответ {response.status}"
    conversation = helpers_messenger.open_chat(new_context(), cast.creator, chat_id)
    expect(conversation.locator('[data-messenger-page="chat"]')).to_contain_text(long_title)


# --- Сценарий 2, п. 2: выход участника (FR-647) ------------------------------------------------------------------

def test_member_leaves_and_stops_seeing_chat_and_messages_while_others_continue(new_context, cast):
    """П. 2 (FR-647): участник выходит без второго шага; чата нет в его списке, беседа и отправка отвечают как у
    несуществующего чата; создатель и второй участник продолжают беседу, новое сообщение доходит живым кадром."""
    title = helpers_org.unique_name("Групповой чат")
    page = helpers_messenger.open_messenger(new_context(), cast.creator, live=False)
    response, chat_id = _create(page, title, [cast.writer, cast.peer])
    assert response.status == 302, f"создание чата: ответ {response.status}"

    creator_page = helpers_messenger.open_chat(new_context(), cast.creator, chat_id)
    before_text = "Сообщение до выхода " + _word()
    helpers_messenger.write(creator_page, before_text)
    writer_page = _member_opens(new_context(), cast.writer, chat_id, title)
    peer_page = _member_opens(new_context(), cast.peer, chat_id, title)
    expect(writer_page.locator("#messenger-messages")).to_contain_text(before_text)

    left = _leave(writer_page, chat_id)
    assert left.status == 302, f"выход участника: ответ {left.status}"
    assert "data-messenger-confirm" not in left.text(), "выход не последнего участника потребовал подтверждения"
    writer_page.wait_for_url(re.compile(r"/messenger/$"))

    _absent_from_list(writer_page, chat_id)
    _like_missing(writer_page, chat_id)
    refused = helpers_org.direct_post(writer_page, f"{_chat_url(chat_id)}messages/",
                                      {"text": "После выхода " + _word()})
    assert refused.status == 404, f"отправка вышедшего участника: ответ {refused.status}"

    after_text = "Сообщение после выхода " + _word()
    message_id = helpers_messenger.write(peer_page, after_text)
    expect(peer_page.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(after_text)
    helpers_messenger.wait_message(creator_page, message_id)
    expect(creator_page.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(after_text)


# --- Сценарий 2, п. 3: выход создателя и заморозка состава (FR-646) ----------------------------------------------

def test_creator_leaves_chat_stays_with_others_and_composition_frozen(new_context, cast):
    """П. 3 (FR-646): создатель выходит; чат остаётся у обоих участников, они продолжают беседу; состав больше не
    меняется — добавление и удаление от любого участника и от вышедшего создателя отвечают 403, формы
    состава в беседе нет."""
    title = helpers_org.unique_name("Групповой чат")
    page = helpers_messenger.open_messenger(new_context(), cast.creator, live=False)
    response, chat_id = _create(page, title, [cast.writer, cast.peer])
    assert response.status == 302, f"создание чата: ответ {response.status}"

    creator_page = helpers_messenger.open_chat(new_context(), cast.creator, chat_id)
    first_text = "Переписка после выхода создателя " + _word()
    helpers_messenger.write(creator_page, first_text)
    assert _leave(creator_page, chat_id).status == 302, "создатель не вышел из чата"
    creator_page.wait_for_url(re.compile(r"/messenger/$"))
    _absent_from_list(creator_page, chat_id)
    _like_missing(creator_page, chat_id)

    writer_page = _member_opens(new_context(), cast.writer, chat_id, title)
    peer_page = _member_opens(new_context(), cast.peer, chat_id, title)
    expect(writer_page.locator("#messenger-messages")).to_contain_text(first_text)

    members_url = f"{_chat_url(chat_id)}members/"
    added = helpers_org.direct_post(writer_page, members_url, _fields("add", [cast.third.id]))
    assert added.status == 403, f"участник добавил сотрудника после выхода создателя: ответ {added.status}"
    removed = helpers_org.direct_post(peer_page, members_url, _fields("remove", [cast.writer.id]))
    assert removed.status == 403, f"участник удалил сотрудника после выхода создателя: ответ {removed.status}"
    gone = helpers_org.direct_post(creator_page, members_url, _fields("add", [cast.third.id]))
    assert gone.status == 403, f"вышедший создатель меняет состав: ответ {gone.status}"
    expect(writer_page.locator(f'form[action$="/chats/{chat_id}/members/"]')).to_have_count(0)
    expect(peer_page.locator(f'form[action$="/chats/{chat_id}/members/"]')).to_have_count(0)

    third_list = helpers_messenger.open_messenger(new_context(), cast.third, live=False)
    _like_missing(third_list, chat_id)

    after_text = "Беседа после выхода создателя " + _word()
    message_id = helpers_messenger.write(peer_page, after_text)
    helpers_messenger.wait_message(writer_page, message_id)
    expect(writer_page.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(after_text)


# --- Сценарий 2, п. 4: удаление создателем, подтверждение и журнал (FR-648, FR-671) ------------------------------

def test_creator_deletes_chat_after_confirm_and_journal_has_no_message_text(new_context, cast, admin_page):
    """П. 4 (FR-648, FR-671): без подтверждения — второй шаг с предупреждением, чат и история целы; после
    подтверждения чат и история исчезают у обоих участников, в журнале одна запись `messenger.chat_deleted`
    с названием и без текста сообщений."""
    title = helpers_org.unique_name("Групповой чат")
    page = helpers_messenger.open_messenger(new_context(), cast.creator, live=False)
    response, chat_id = _create(page, title, [cast.writer])
    assert response.status == 302, f"создание чата: ответ {response.status}"

    creator_page = helpers_messenger.open_chat(new_context(), cast.creator, chat_id)
    first_text = "Первый секрет переписки " + _word()
    helpers_messenger.write(creator_page, first_text)
    writer_page = _member_opens(new_context(), cast.writer, chat_id, title)
    second_text = "Второй секрет переписки " + _word()
    helpers_messenger.write(writer_page, second_text)

    creator_page.goto(_chat_url(chat_id))
    step_response = _delete(creator_page, chat_id)
    button = _confirm_step(creator_page, step_response)
    assert helpers_org.direct_get(creator_page, _chat_url(chat_id)).status == 200, "чат удалён до подтверждения"
    writer_page.reload()
    expect(writer_page.locator("#messenger-messages")).to_contain_text(first_text)

    _confirm(creator_page, button, chat_id)
    _absent_from_list(creator_page, chat_id)
    _like_missing(writer_page, chat_id)

    rows = helpers_org.audit_rows(admin_page, AUDIT_DELETED, chat_id)
    assert len(rows) == 1, f"записей журнала {AUDIT_DELETED}: {len(rows)}"
    assert title in rows[0], f"в журнале нет названия чата: {rows[0]!r}"
    assert first_text not in rows[0] and second_text not in rows[0], "в журнале текст сообщений"
    sides = helpers_org.audit_sides(admin_page, AUDIT_DELETED, chat_id)
    assert len(sides) == 1, sides
    before, after = sides[0]
    assert title in before, f"в «было» нет названия чата: {before!r}"
    assert first_text not in before and second_text not in before, "в «было» текст сообщений"
    assert first_text not in after and second_text not in after, "в «стало» текст сообщений"


# --- Сценарий 2, п. 5: выход последнего участника (FR-647) -------------------------------------------------------

def test_last_member_leaves_with_confirm_and_chat_deleted_with_history(new_context, cast):
    """П. 5 (FR-647): второй участник выходит без подтверждения, чат остаётся у последнего; выход последнего
    требует второго шага, без него чат и история целы, после подтверждения чат и история удалены."""
    title = helpers_org.unique_name("Групповой чат")
    page = helpers_messenger.open_messenger(new_context(), cast.creator, live=False)
    response, chat_id = _create(page, title, [cast.peer])
    assert response.status == 302, f"создание чата: ответ {response.status}"

    creator_page = helpers_messenger.open_chat(new_context(), cast.creator, chat_id)
    text = "История до выхода последнего " + _word()
    helpers_messenger.write(creator_page, text)
    peer_page = _member_opens(new_context(), cast.peer, chat_id, title)

    left = _leave(peer_page, chat_id)
    assert left.status == 302, f"выход не последнего участника: ответ {left.status}"
    assert "data-messenger-confirm" not in left.text(), "не последний участник получил подтверждение"
    peer_page.wait_for_url(re.compile(r"/messenger/$"))
    assert helpers_org.direct_get(creator_page, _chat_url(chat_id)).status == 200, "чат исчез до выхода последнего"

    creator_page.goto(_chat_url(chat_id))
    expect(creator_page.locator('[data-messenger-page="chat"]')).to_contain_text(text)
    step_response = _leave(creator_page, chat_id)
    button = _confirm_step(creator_page, step_response)
    assert helpers_org.direct_get(creator_page, _chat_url(chat_id)).status == 200, "чат удалён до подтверждения"

    _confirm(creator_page, button, chat_id, action="leave")
    _absent_from_list(creator_page, chat_id)
    _like_missing(peer_page, chat_id)
    history = helpers_org.direct_get(creator_page, f"{_chat_url(chat_id)}messages/")
    assert history.status == 404, f"история удалённого чата: ответ {history.status}"