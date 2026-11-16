"""T-8134: сценарий 4 — «Общий чат» портала (FR-651, FR-671).

Приёмка SPEC-008, сценарий 4: после установки «Общий чат» один, виден всем действующим сотрудникам и писать в него
может любой (п. 1); выключение настройкой портала убирает чат из списка и поиска, прямой адрес отвечает как
несуществующий, отправка отклоняется (п. 2); включение возвращает прежнюю историю, а в журнале остаются две записи —
выключение и включение, без текста переписки (п. 3).

Общее для файла (CONTRACT-008.md, разделы 1.4, 8.1, 9, 10.1–10.2, 12, 13.1, 14.3):
- люди круга — `helpers_messenger.messenger_cast` (один раз на круг браузера; сессии сохранены в
  `Account.storage_state`, контекст активации закрыт); настройку переключает администратор портала (`admin_page`);
- страницы и отправка — помощники `helpers_messenger` (`open_messenger`, `open_chat`, `write`); локаторы — только
  зацепки раздела 12 (`#messenger-list [data-chat-id]`, `[data-chat-kind="general"]`, `#messenger-form`,
  `[data-messenger-page="settings"]`, `section[data-search-group="messenger"]`);
- «Общий чат» ищется в списке по названию: раздел 12.2 не даёт строке списка отдельной зацепки вида чата; вид
  проверяется у заголовка беседы `[data-chat-kind="general"]` (12.2);
- настройка переключается галочкой `input[name="general_chat_enabled"]` страницы `/settings/messenger/` (10.2;
  обычный POST — 302 на ту же страницу); срок хранения не меняется, второй шаг `[data-messenger-confirm]` не нужен;
- журнал: код `messenger.general_changed` (8.1), записи читаются `helpers_org.audit_rows`/`audit_sides` с фильтром по
  коду; «две записи» считаются прибавкой к числу записей до опыта — стенд круга не сбрасывается между тестами, и
  прежние события не мешают;
- пока «Общий чат» выключен, у сотрудника без других чатов список пуст, поэтому страница списка открывается
  `live=False`: узла соединения беседы `[data-ws]` на ней нет (12.4);
- отказы — `data-code` (10.1): `chat_disabled` у поля `chat` или общий `[role=alert]` (13.1).
"""
import secrets
from urllib.parse import urlencode, urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_messenger, helpers_notify, helpers_org
from tests.e2e.conftest import PORTAL_URL

GENERAL_TITLE = "Общий чат"
SETTINGS_URL = "/settings/messenger/"
AUDIT_ACTION = "messenger.general_changed"
DISABLED_CODE = "chat_disabled"
DISABLED_TEXT = "Чат отключён"
MISSING_TEXT = "Не найдено"
MISSING = 987_654_321          # заведомо несуществующий чат: ответ сравнивается с прямым адресом

_CASTS: dict = {}


@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Круг людей сценариев (`messenger_cast`), один на круг браузера (образец — `test_f01_publish.cast`)."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        found = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
        _CASTS[stand_admin.email] = found
    return found


# --- Помощники файла -----------------------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово из латинских букв: цифры и русские окончания поиск разобрал бы иначе."""
    return "".join(secrets.choice("bcdfghklmnprstvz") for _ in range(10))


def _general_row(page):
    """Строка «Общего чата» в списке (`#messenger-list [data-chat-id]` с названием «Общий чат», 12.2)."""
    rows = page.locator("#messenger-list [data-chat-id]").filter(has_text=GENERAL_TITLE)
    expect(rows).to_have_count(1)
    return rows.first


def _general_id(page) -> int:
    return int(_general_row(page).get_attribute("data-chat-id"))


def _list_page(context, account, *, live: bool = True):
    return helpers_messenger.open_messenger(context, account, live=live)


def _chat_page(context, account, chat_id):
    return helpers_messenger.open_chat(context, account, chat_id)


def _search_page(context, account, word):
    """Страница результатов `/search/?q=<word>` (раздел 9: `[data-search-page]`, группа «Мессенджер»)."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto("/search/?" + urlencode({"q": word}))
    expect(page.locator("[data-search-page]")).to_be_visible()
    return page


def _set_general(admin_page, enabled: bool) -> None:
    """Включает или выключает «Общий чат» галочкой страницы `/settings/messenger/` (10.2) и проверяет, что значение
    сохранилось после 302. Уже нужное значение не отправляется заново (лишней записи журнала не будет)."""
    admin_page.goto(SETTINGS_URL)
    root = admin_page.locator('[data-messenger-page="settings"]')
    expect(root).to_be_visible()
    box = root.locator('input[name="general_chat_enabled"]')
    expect(box).to_have_count(1)
    if box.is_checked() == enabled:
        return
    box.set_checked(enabled)
    form = box.locator("xpath=ancestor::form[1]")
    expect(form).to_have_count(1)
    with admin_page.expect_navigation():
        form.locator('button[type="submit"]').first.click()
    admin_page.wait_for_load_state()
    expect(admin_page.locator('[data-messenger-page="settings"]')).to_be_visible()
    expect(admin_page.locator('input[name="general_chat_enabled"]')).to_be_checked(checked=enabled)


def _messages_post(page, chat_id, text: str, *, htmx: bool = False):
    """`POST /messenger/chats/<id>/messages/` от имени страницы (10.2): обычный запрос — 404 у выключенного чата,
    HTMX (`HX-Request: true`) — 200 с причиной `chat_disabled`; CSRF и Origin — как у `helpers_org.direct_post`."""
    path = f"/messenger/chats/{chat_id}/messages/"
    if not htmx:
        return helpers_org.direct_post(page, path, {"text": text})
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(PORTAL_URL))
    return page.request.post(path, form={"text": text}, max_redirects=0, headers={
        "X-CSRFToken": helpers_org.csrf_token(page), "Referer": origin + "/", "Origin": origin,
        "HX-Request": "true"})


# --- Тесты ---------------------------------------------------------------------------------------------------------

def test_m04_general_chat_present_after_install_and_any_employee_writes(new_context, cast):
    """П. 1 (FR-651): «Общий чат» есть сразу, без подготовки, у сотрудника в списке и открывается беседой вида
    `general` с названием «Общий чат»; писать в него может любой действующий сотрудник, сообщение видно другому
    сотруднику, а «Общий чат» у обоих один и тот же."""
    page = _list_page(new_context(), cast.writer)
    chat_id = _general_id(page)
    expect(_general_row(page)).to_be_visible()

    chat = _chat_page(new_context(), cast.writer, chat_id)
    expect(chat.locator('[data-chat-kind="general"]')).to_have_count(1)
    expect(chat.locator('[data-messenger-page="chat"]')).to_contain_text(GENERAL_TITLE)

    text = f"Первое сообщение общего чата {_word()}"
    message_id = helpers_messenger.write(chat, text)
    expect(chat.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(text)

    other = _list_page(new_context(), cast.peer)
    expect(_general_row(other)).to_have_attribute("data-chat-id", str(chat_id))
    peer_chat = _chat_page(new_context(), cast.peer, chat_id)
    expect(peer_chat.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(text)

    peer_text = f"Ответ второго сотрудника {_word()}"
    peer_message_id = helpers_messenger.write(peer_chat, peer_text)
    expect(peer_chat.locator(f'article[data-message-id="{peer_message_id}"]')).to_contain_text(peer_text)


def test_m04_disabled_general_chat_absent_from_list_and_search_and_direct_address_404(admin_page, new_context, cast):
    """П. 2 (FR-651): администратор снимает галочку «Общий чат» — чат исчезает из списка и из сквозного поиска,
    прямой адрес беседы отвечает как несуществующий, обычная отправка — 404, HTMX — 200 с причиной `chat_disabled`
    («Чат отключён»); отклонённые сообщения не записываются. В конце чат включается обратно."""
    word = _word()
    chat_id = _general_id(_list_page(new_context(), cast.writer))
    chat = _chat_page(new_context(), cast.writer, chat_id)
    kept_text = f"Слово до выключения {word}"
    message_id = helpers_messenger.write(chat, kept_text)

    found = _search_page(new_context(), cast.writer, word)
    expect(found.locator(
        f'section[data-search-group="messenger"] a[href="/messenger/chats/{chat_id}/#m{message_id}"]')).to_be_visible()

    refused = (f"Обычная отправка в выключенный чат {word}", f"HTMX-отправка в выключенный чат {word}")
    try:
        _set_general(admin_page, False)

        hidden = _list_page(new_context(), cast.writer, live=False)
        expect(hidden.locator(f'#messenger-list [data-chat-id="{chat_id}"]')).to_have_count(0)
        assert GENERAL_TITLE not in hidden.locator("#messenger-list").inner_text(), "выключенный чат остался в списке"

        results = _search_page(new_context(), cast.writer, word)
        group = results.locator('section[data-search-group="messenger"]')
        expect(group.locator(f'a[href*="/messenger/chats/{chat_id}/"]')).to_have_count(0)
        if group.count():
            assert word not in group.inner_text(), "выключенный чат найден поиском"

        response = hidden.goto(f"/messenger/chats/{chat_id}/")
        assert response is not None and response.status == 404, "прямой адрес выключенного чата не 404"
        expect(hidden.locator("body")).to_contain_text(MISSING_TEXT)
        absent = hidden.request.get(f"/messenger/chats/{MISSING}/", max_redirects=0)
        assert absent.status == response.status == 404, "прямой адрес отвечает не как несуществующий чат"

        plain = _messages_post(hidden, chat_id, refused[0])
        missing = _messages_post(hidden, MISSING, refused[0])
        assert plain.status == missing.status == 404, "обычная отправка в выключенный чат не отклонена как 404"
        htmx = _messages_post(hidden, chat_id, refused[1], htmx=True)
        assert htmx.status == 200, f"HTMX-отправка: {htmx.status}"
        body = htmx.text()
        assert f'data-code="{DISABLED_CODE}"' in body, "у отказа нет причины chat_disabled"
        assert DISABLED_TEXT in body, "у отказа нет текста «Чат отключён»"
    finally:
        _set_general(admin_page, True)

    back = _chat_page(new_context(), cast.writer, chat_id)
    expect(back.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(kept_text)
    for message in refused:
        expect(back.locator("#messenger-messages")).not_to_contain_text(message)


def test_m04_enable_again_restores_history_and_writes_two_journal_records(admin_page, new_context, cast):
    """П. 3 (FR-651, FR-671): выключение и включение «Общего чата» страницей настроек пишут ровно две новые записи
    журнала `messenger.general_changed` — «было / стало» с «включён»/«выключен» и без текста переписки; после
    включения чат снова в списке, прежние сообщения на месте с теми же номерами, отправка снова работает."""
    chat_id = _general_id(_list_page(new_context(), cast.writer))
    first, second = f"История до выключения {_word()}", f"Второе сообщение истории {_word()}"
    chat = _chat_page(new_context(), cast.writer, chat_id)
    message_ids = [helpers_messenger.write(chat, first), helpers_messenger.write(chat, second)]

    before_rows = helpers_org.audit_rows(admin_page, AUDIT_ACTION)
    try:
        _set_general(admin_page, False)
        hidden = _list_page(new_context(), cast.writer, live=False)
        expect(hidden.locator(f'#messenger-list [data-chat-id="{chat_id}"]')).to_have_count(0)
        assert hidden.goto(f"/messenger/chats/{chat_id}/").status == 404, "выключенный чат открылся по адресу"
    finally:
        _set_general(admin_page, True)

    rows = helpers_org.audit_rows(admin_page, AUDIT_ACTION)
    new_rows = len(rows) - len(before_rows)
    assert new_rows == 2, f"выключение и включение дали {new_rows} записей журнала, а не две"
    sides = helpers_org.audit_sides(admin_page, AUDIT_ACTION)
    assert len(sides) == len(rows), "«было / стало» прочитаны не у всех строк журнала"
    enable_was, enable_became = sides[0]
    disable_was, disable_became = sides[1]
    assert "выключен" in disable_became and "включён" in disable_was, (
        f"запись выключения: было {disable_was!r}, стало {disable_became!r}")
    assert "включён" in enable_became and "выключен" in enable_was, (
        f"запись включения: было {enable_was!r}, стало {enable_became!r}")
    for row in rows[:2]:
        for text in (first, second):
            assert text not in row, "в журнале оказался текст переписки"

    restored = _chat_page(new_context(), cast.writer, chat_id)
    for message_id, text in zip(message_ids, (first, second)):
        expect(restored.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(text)
    expect(_general_row(_list_page(new_context(), cast.writer))).to_have_attribute("data-chat-id", str(chat_id))

    third = f"Сообщение после включения {_word()}"
    new_id = helpers_messenger.write(restored, third)
    expect(restored.locator(f'article[data-message-id="{new_id}"]')).to_contain_text(third)