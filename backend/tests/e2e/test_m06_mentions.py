"""T-8136: приёмка сценария 6 — упоминания «@» (FR-655, FR-664).

Приёмка SPEC-008, сценарий 6 «Упоминание и уведомление»:
1. групповой чат: сотрудник упоминает участника — у упомянутого появляется уведомление на портале, а в тексте
   сообщения имя — ссылка;
2. упоминание вне подсказки («@» и слово, которого нет среди участников) — упоминанием не считается, уведомления нет;
3. сообщение с упоминанием чата и участника — в тексте ссылка на беседу, уведомление получает только упомянутый
   человек, никто больше;
4. личный диалог: сотрудник набирает «@» — подсказка не открывается.

Источники: CONTRACT-008 § 5.2 (`mentions.suggest`/`extract`, маркеры `@[u<id>]`/`@[c<id>]`), § 7.1–7.2 (виды
`messenger.mention`/`messenger.message`, их тексты и `Draft.url`), § 10.2 (`GET /messenger/mentions/?chat=&q=`,
`POST …/messages/`), § 12.3 (`[data-messenger-mention-list]`, `[data-mention-value]`, `#messenger-form`), § 12.6
(`a[data-mention]`), § 14.3 (помощники `helpers_messenger`); CONTRACT-004 § 11, 14.2 (строки уведомлений
`li[data-notification]`, `[data-field="kind"]`, `[data-field="text"]`, `a[data-open]`, `/notifications/<id>/open/`);
план «Упоминания „@“», «Уведомления»; задачи T-8136, T-8210, T-8217.

Решения файла (зацепки, которых контракт не называет):
- подсказка проверяется в интерфейсе: в `textarea[name="text"]` формы `#messenger-form` набирается «@» и часть
  ФИО/названия, тест ждёт ответ `/messenger/mentions/` именно на полный `q` (разбор адреса) и смотрит строки
  `[data-messenger-mention-list] [data-mention-value]`; отрицательный случай — ответ без строк;
- «@» и слово без выбора из подсказки набираются прямо в поле (fill): так проверяется п. 2 — сервер доверяет
  только маркерам, а слово вне подсказки остаётся текстом;
- маркер на сервере читается из тела POST формы (`post_data_buffer`, urlencoded; как в `test_f06_mentions.py`
  среза 007): `@[u<id>]` у человека и `@[c<id>]` у чата; видимое в поле — `@ФИО`/`#название` (план);
- уведомления читаются на вкладке «Уведомления» `/messenger/notifications/` (`[data-messenger-page="notifications"]`,
  § 12.1): строки `ul[data-notifications] li[data-notification]` с видом `[data-field="kind"]` — «Упомянул вас
  в чате» и «Новое сообщение в чате», текст строки — `[data-field="text"]` (§ 7.1–7.2); адрес открытия
  проверяется запросом `/notifications/<id>/open/` без следования (302 на `Notification.url` —
  `/messenger/chats/<id>/#m<id>`);
- «уведомления нет» проверяется только после положительного контроля: сначала подтверждается, что вид вообще
  приходит в этом круге (упомянутому — упоминание, остальному участнику — сообщение), затем считаются строки
  у остальных; строки всегда сужаются названием чата этого теста — данные круга общие;
- `messenger_cast` собирается один раз на круг браузера, названия чатов и слова уникальны
  (`helpers_org.unique_name`, `_word`); списки открываются `live=False` — у соседних сценариев «Общий чат» может
  быть выключен; пропусков (`skip`/`xfail`) в файле нет; файл правит только T-8136.
"""
import re
import secrets
import time
from urllib.parse import parse_qs, unquote_plus, urlencode, urlsplit

import pytest
from playwright.sync_api import FormData, TimeoutError as PlaywrightTimeoutError, expect

from tests.e2e import helpers_messenger, helpers_org

KIND_MENTION = "Упомянул вас в чате"        # CONTRACT-008, 7.1: название вида `messenger.mention`
KIND_MESSAGE = "Новое сообщение в чате"     # CONTRACT-008, 7.1: название вида `messenger.message`
SUGGEST_TIMEOUT = 10_000                    # ответ подсказки «@» на набранный запрос
OBSERVE_MS = 1_500                          # окно наблюдения «подсказки нет» (п. 4)
CREATE = "/messenger/chats/"                # CONTRACT-008, 10.2
NOTIFICATIONS = "/messenger/notifications/"  # CONTRACT-008, 10.2
FORM = "#messenger-form"                    # CONTRACT-008, 12.3
_MENTIONS = re.compile(r"/messenger/mentions/")
_MESSAGE_ID = re.compile(r'data-message-id="(\d+)"')
_CHAT_LOCATION = re.compile(r"(?:https?://[^/]+)?/messenger/chats/(\d+)/")

_CASTS: dict = {}


@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Люди и узлы сценариев (`helpers_messenger.messenger_cast`), один раз на круг браузера."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        found = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
        _CASTS[stand_admin.email] = found
    return found


# --- Помощники файла -----------------------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово латиницей: не совпадает ни с ФИО, ни с названием чата круга."""
    return "zz" + secrets.token_hex(4)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _list_page(new_context, account):
    """Список чатов сотрудника: `open_messenger(..., live=False)` (у соседей «Общий чат» может быть выключен)."""
    return helpers_messenger.open_messenger(new_context(), account, live=False)


def _create(page, title: str, members):
    """`POST /messenger/chats/` с `kind=group`, названием и участниками (CONTRACT-008, 10.2).

    Возвращает `(ответ, номер чата или None)`: успех — 302 на адрес беседы, отказ — 200 с причиной у поля."""
    data = FormData()
    for member in members:
        data.append("members", str(member.id))
    data.set("kind", "group")
    data.set("title", title)
    response = helpers_org.direct_post(page, CREATE, data)
    if response.status != 302:
        return response, None
    location = response.headers.get("location", "")
    found = _CHAT_LOCATION.fullmatch(location)
    assert found, f"после создания чата адрес перехода {location!r}, ожидался /messenger/chats/<id>/"
    return response, int(found.group(1))


def _chat_page(new_context, account, chat_id):
    return helpers_messenger.open_chat(new_context(), account, chat_id)


def _box(page):
    """Поле ввода беседы `#messenger-form textarea[name="text"]` (CONTRACT-008, 12.3)."""
    return page.locator(f'{FORM} textarea[name="text"]').first


def _type_at(page, query: str) -> None:
    """Набирает «@» и `query` в поле ввода по символу (как человек): подсказка запрашивается с задержкой набора."""
    box = _box(page)
    box.fill("")
    box.focus()
    box.press_sequentially("@" + query, delay=30)


def _settle(page) -> None:
    """Два кадра перерисовки: ответ подсказки уже применён к списку."""
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _suggest(page, query: str) -> str:
    """Ждёт ответ `/messenger/mentions/` на полный `q=<query>` и возвращает текст фрагмента подсказки.

    `q` — запрос подсказки (план: пустой или один знак — пусто); клиент может прислать и часть текста после «@»,
    и всё поле целиком, поэтому ответ узнаётся по окончанию `q` на набранный запрос."""
    def matches(response):
        if response.request.method != "GET" or not _MENTIONS.search(response.url):
            return False
        value = (parse_qs(urlsplit(response.url).query).get("q") or [""])[0].rstrip()
        return value == query or value.endswith(query)

    with page.expect_response(matches, timeout=SUGGEST_TIMEOUT) as info:
        _type_at(page, query)
    html = info.value.text()
    _settle(page)
    return html


def _options(page, text: str = ""):
    """Строки подсказки «@»: `[data-messenger-mention-list] [data-mention-value]` (CONTRACT-008, 12.3)."""
    rows = page.locator("[data-messenger-mention-list] [data-mention-value]")
    return rows.filter(has_text=text) if text else rows


def _no_suggestions(page, observe_ms: int = OBSERVE_MS) -> None:
    """Подсказка не открылась: за `observe_ms` мс строк `[data-mention-value]` в документе не появилось.

    Ожидание — `wait_for_function` по условию «строка есть» и его таймаут (без `time.sleep`), как
    `helpers_notify.no_notifications`; строка появилась — `AssertionError`."""
    script = ("() => document.querySelectorAll("
              "'[data-messenger-mention-list] [data-mention-value]').length > 0")
    try:
        page.wait_for_function(script, timeout=observe_ms)
    except PlaywrightTimeoutError:
        return
    raise AssertionError("в личном диалоге подсказка «@» открылась")


def _is_message_post(response) -> bool:
    """POST формы беседы `…/messenger/chats/<id>/messages/` (CONTRACT-008, 10.2)."""
    return (response.request.method == "POST" and "/messenger/chats/" in response.url
            and response.url.split("?")[0].endswith("/messages/"))


def _send(page):
    """Отправляет форму беседы. Возвращает `(ответ, тело запроса, номер сообщения)`.

    Тело запроса — urlencoded (как в `test_f06_mentions.py`): по нему проверяется, что на сервер ушёл маркер.
    Номер сообщения — из ответа (`data-message-id`) или, если ответ без фрагмента (обычный POST — 302), —
    последнее сообщение истории (образец — `helpers_messenger._sent_id`)."""
    form = page.locator(FORM)
    expect(form).to_be_visible()
    with page.expect_response(_is_message_post) as info:
        form.locator('button[type="submit"]').first.click()
    response = info.value
    body = unquote_plus((response.request.post_data_buffer or b"").decode("utf-8", "replace"))
    ids = _MESSAGE_ID.findall(response.text())
    if ids:
        message_id = int(ids[-1])
    else:
        article = page.locator("#messenger-messages article[data-message-id]").last
        expect(article).to_be_visible(timeout=helpers_messenger.FRAME_TIMEOUT)
        message_id = int(article.get_attribute("data-message-id"))
    return response, body, message_id


def _notifications(new_context, account):
    """Вкладка «Уведомления» сотрудника `/messenger/notifications/` (CONTRACT-008, 10.2, 12.1)."""
    page = _list_page(new_context, account)
    page.goto(NOTIFICATIONS)
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="notifications"]')).to_be_visible()
    return page


def _kind_rows(page, kind: str):
    """Строки уведомлений вида `kind`: `li[data-notification]` с `[data-field="kind"]` (CONTRACT-004, 14.2)."""
    return page.locator("ul[data-notifications] li[data-notification]").filter(
        has=page.locator('[data-field="kind"]', has_text=re.compile(rf"^\s*{re.escape(kind)}\s*$")))


def _chat_rows(page, kind: str, title: str):
    """Строки вида про чат `title`: текст уведомления содержит название (`Draft.text`, CONTRACT-008, 7.2)."""
    return _kind_rows(page, kind).filter(has=page.locator('[data-field="text"]', has_text=title))


def _wait_chat_rows(page, kind: str, title: str, count: int = 1, timeout: float = 20.0):
    """Ждёт не меньше `count` строк вида о чате `title`; не пришло за `timeout` с — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        rows = _chat_rows(page, kind, title)
        if rows.count() >= count:
            return rows
        if time.monotonic() >= deadline:
            raise AssertionError(f"уведомлений «{kind}» о чате «{title}»: {rows.count()}, "
                                 f"ожидалось не меньше {count}")
        page.wait_for_timeout(500)
        page.reload()
        page.wait_for_load_state()
        expect(page.locator('[data-messenger-page="notifications"]')).to_be_visible()


def _row_text(row) -> str:
    return _norm(row.locator('[data-field="text"]').inner_text())


def _notification_id(row) -> str:
    value = row.get_attribute("data-notification")
    assert value, "у строки уведомления нет data-notification"
    return value


def _open_target(page, notification_id) -> str:
    """Адрес перехода `/notifications/<id>/open/`: 302 на `Notification.url` (CONTRACT-004, 11, 14.2)."""
    response = page.request.get(f"/notifications/{notification_id}/open/", max_redirects=0)
    assert response.status == 302, f"открытие уведомления {notification_id}: ответ {response.status}"
    location = response.headers.get("location", "")
    assert location, f"у уведомления {notification_id} нет адреса перехода"
    return location


# --- Сценарий 6, подсказка «@» (FR-655) ----------------------------------------------------------------------------

def test_m06_at_suggestion_lists_chat_members_and_own_chats_and_hides_strangers(new_context, cast):
    """П. 1, 4 (FR-655): в групповом чате «@» и часть ФИО участника показывают строку подсказки с этим участником;
    сотрудник вне чата в подсказке не появляется; свои чаты (где сотрудник участник) видны, чужой чат — нет."""
    title = helpers_org.unique_name("Групповой чат")
    own_title = helpers_org.unique_name("Свой чат")
    foreign_title = helpers_org.unique_name("Чужой чат")
    page = _list_page(new_context, cast.writer)
    response, chat_id = _create(page, title, [cast.peer, cast.department_member])
    assert response.status == 302 and chat_id is not None, f"создание чата: ответ {response.status}"
    other = _list_page(new_context, cast.creator)
    assert _create(other, own_title, [cast.writer])[0].status == 302, "не создан свой второй чат"
    assert _create(other, foreign_title, [cast.third])[0].status == 302, "не создан чужой чат"

    chat = _chat_page(new_context, cast.writer, chat_id)
    expect(chat.locator(FORM)).to_be_visible()

    member_query = cast.peer.full_name.split()[0]
    html = _suggest(chat, member_query)
    option = _options(chat, cast.peer.full_name)
    expect(option).to_have_count(1)
    expect(option.first).to_be_visible()
    assert cast.peer.full_name in html, "подсказка «@» не содержит участника чата"

    stranger_query = cast.third.full_name.split()[0]
    html = _suggest(chat, stranger_query)
    expect(_options(chat, cast.third.full_name)).to_have_count(0)
    assert "data-mention-value" not in html, "подсказка «@» показала сотрудника вне чата"

    own_query = own_title.split()[0]
    html = _suggest(chat, own_query)
    expect(_options(chat, own_title)).to_have_count(1)
    assert own_title in html, "подсказка «@» не содержит своего чата"

    foreign_query = foreign_title.split()[0]
    html = _suggest(chat, foreign_query)
    expect(_options(chat, foreign_title)).to_have_count(0)
    assert "data-mention-value" not in html, "подсказка «@» показала чужой чат"


# --- Сценарий 6, п. 1: выбранный участник, маркер, ссылка и уведомление (FR-655, FR-664) ---------------------------

def test_m06_selected_member_shown_as_at_full_name_marker_sent_and_notification_arrives(new_context, cast):
    """П. 1 (FR-655, FR-664): выбранный из подсказки участник виден в поле как `@ФИО`; на сервер уходит маркер
    `@[u<id>]`, а не ФИО; в сообщении имя — ссылка на карточку; упомянутому приходит уведомление на портале."""
    title = helpers_org.unique_name("Групповой чат")
    page = _list_page(new_context, cast.writer)
    response, chat_id = _create(page, title, [cast.peer])
    assert response.status == 302 and chat_id is not None, f"создание чата: ответ {response.status}"

    chat = _chat_page(new_context, cast.writer, chat_id)
    _box(chat).fill("Привет, коллеги " + _word() + " ")
    helpers_messenger.mention(chat, cast.peer.full_name)
    expect(_box(chat)).to_have_value(re.compile(re.escape("@" + cast.peer.full_name)))

    _, body, message_id = _send(chat)
    assert f"@[u{cast.peer.id}]" in body, "на сервер не ушёл маркер упоминания человека"
    assert cast.peer.full_name not in body, "на сервер ушло выбранное ФИО вместо маркера"

    message = chat.locator(f'article[data-message-id="{message_id}"]')
    expect(message).to_be_visible(timeout=helpers_messenger.FRAME_TIMEOUT)
    link = message.locator(f'a[data-mention="{cast.peer.id}"][href="/staff/{cast.peer.id}/"]')
    expect(link).to_have_count(1)
    expect(link).to_contain_text(cast.peer.full_name)
    assert f"@[u{cast.peer.id}]" not in message.inner_text(), "маркер упоминания показан текстом"

    peer = _notifications(new_context, cast.peer)
    rows = _wait_chat_rows(peer, KIND_MENTION, title)
    text = _row_text(rows.first)
    assert "упомянул" in text, f"текст уведомления: {text!r}"
    assert cast.writer.full_name in text, f"в уведомлении нет ФИО автора: {text!r}"
    assert title in text, f"в уведомлении нет названия чата: {text!r}"
    notification_id = _notification_id(rows.first)
    expect(rows.first.locator('[data-field="text"] a[data-open]')).to_have_attribute(
        "href", f"/notifications/{notification_id}/open/")


# --- Сценарий 6, п. 4: личный диалог (FR-655) ----------------------------------------------------------------------

def test_m06_personal_dialog_opens_no_at_suggestion(new_context, cast):
    """П. 4 (FR-655): в личном диалоге «@» и часть ФИО собеседника не открывают подсказку; сервер на запрос
    подсказки этого чата отвечает пустым списком (план, «Упоминания „@“»)."""
    page = _list_page(new_context, cast.writer)
    chat_id = helpers_messenger.start_dialog(page, cast.peer)
    expect(page.locator("[data-chat-kind]")).to_have_attribute("data-chat-kind", "personal")
    expect(page.locator(FORM)).to_be_visible()

    query = cast.peer.full_name.split()[0]
    _type_at(page, query)
    _no_suggestions(page)
    expect(_options(page)).to_have_count(0)

    fragment = helpers_org.direct_get(page, "/messenger/mentions/?" + urlencode({"chat": chat_id, "q": query}))
    assert fragment.status == 200, f"подсказка личного диалога: ответ {fragment.status}"
    assert "data-mention-value" not in fragment.text(), "в личном диалоге сервер вернул строки подсказки"


# --- Сценарий 6, п. 2: «@» и слово вне подсказки (FR-655) ----------------------------------------------------------

def test_m06_mention_outside_suggestion_is_text_and_sends_no_notification(new_context, cast):
    """П. 2 (FR-655): «@» и слово, которого нет среди участников, — не упоминание: остаётся текстом, маркера нет,
    уведомления нет; положительный контроль — настоящее упоминание даёт ровно одно уведомление, и оно ведёт на
    сообщение с упоминанием, а не на слово вне подсказки."""
    title = helpers_org.unique_name("Групповой чат")
    page = _list_page(new_context, cast.writer)
    response, chat_id = _create(page, title, [cast.peer])
    assert response.status == 302 and chat_id is not None, f"создание чата: ответ {response.status}"

    chat = _chat_page(new_context, cast.writer, chat_id)
    word = "@" + _word()
    _box(chat).fill(f"Просто {word} и больше ничего")
    _, body, plain_id = _send(chat)
    assert "@[u" not in body and "@[c" not in body, "на сервер ушёл маркер несуществующего упоминания"
    plain = chat.locator(f'article[data-message-id="{plain_id}"]')
    expect(plain).to_contain_text(word)
    expect(plain.locator("[data-mention]")).to_have_count(0)

    helpers_messenger.mention(chat, cast.peer.full_name)
    _, body, mentioned_id = _send(chat)
    assert f"@[u{cast.peer.id}]" in body, "на сервер не ушёл маркер настоящего упоминания"

    peer = _notifications(new_context, cast.peer)
    rows = _wait_chat_rows(peer, KIND_MENTION, title)
    assert rows.count() == 1, f"уведомлений об упоминании: {rows.count()}, ожидалось одно"
    target = _open_target(peer, _notification_id(rows.first))
    assert urlsplit(target).path == f"/messenger/chats/{chat_id}/", f"уведомление ведёт на {target!r}"
    assert urlsplit(target).fragment == f"m{mentioned_id}", f"уведомление ведёт на {target!r}"


# --- Сценарий 6, п. 3: упоминание чата и «только упомянутый» (FR-655, FR-664) ---------------------------------------

def test_m06_chat_mention_inserts_link_and_notifies_only_mentioned_member(new_context, cast):
    """П. 3 (FR-655, FR-664): в сообщении с упоминанием чата и участника — ссылка на беседу и ссылка на карточку,
    на сервер уходят оба маркера; уведомление об упоминании получает только упомянутый — автору, второму участнику
    (у него есть только «Новое сообщение в чате») и сотруднику вне чата упоминания не приходит."""
    title = helpers_org.unique_name("Групповой чат")
    page = _list_page(new_context, cast.writer)
    response, chat_id = _create(page, title, [cast.peer, cast.department_member])
    assert response.status == 302 and chat_id is not None, f"создание чата: ответ {response.status}"

    chat = _chat_page(new_context, cast.writer, chat_id)
    _box(chat).fill("Обсудим в ")
    helpers_messenger.mention(chat, title)
    expect(_box(chat)).to_have_value(re.compile(re.escape(helpers_messenger.chat_mention(title))))
    helpers_messenger.mention(chat, cast.peer.full_name)
    expect(_box(chat)).to_have_value(re.compile(re.escape("@" + cast.peer.full_name)))

    _, body, message_id = _send(chat)
    assert f"@[c{chat_id}]" in body, "на сервер не ушёл маркер упоминания чата"
    assert f"@[u{cast.peer.id}]" in body, "на сервер не ушёл маркер упоминания участника"
    assert title not in body, "на сервер ушло название чата вместо маркера"

    message = chat.locator(f'article[data-message-id="{message_id}"]')
    expect(message).to_be_visible(timeout=helpers_messenger.FRAME_TIMEOUT)
    chat_link = message.locator(f'a[data-mention="c{chat_id}"][href="/messenger/chats/{chat_id}/"]')
    expect(chat_link).to_have_count(1)
    expect(chat_link).to_contain_text(title)
    person_link = message.locator(f'a[data-mention="{cast.peer.id}"][href="/staff/{cast.peer.id}/"]')
    expect(person_link).to_have_count(1)
    expect(person_link).to_contain_text(cast.peer.full_name)
    text = message.inner_text()
    assert f"@[c{chat_id}]" not in text and f"@[u{cast.peer.id}]" not in text, "маркеры показаны текстом"

    peer = _notifications(new_context, cast.peer)
    peer_rows = _wait_chat_rows(peer, KIND_MENTION, title)
    assert peer_rows.count() == 1, f"у упомянутого уведомлений об упоминании: {peer_rows.count()}"
    assert title in _row_text(peer_rows.first), "в уведомлении нет названия чата"
    assert cast.writer.full_name in _row_text(peer_rows.first), "в уведомлении нет ФИО автора"

    member = _notifications(new_context, cast.department_member)
    expect(_chat_rows(member, KIND_MENTION, title)).to_have_count(0)
    _wait_chat_rows(member, KIND_MESSAGE, title)  # положительный контроль: вид вообще доходит

    author = _notifications(new_context, cast.writer)
    expect(_chat_rows(author, KIND_MENTION, title)).to_have_count(0)

    outsider = _notifications(new_context, cast.third)
    expect(_chat_rows(outsider, KIND_MENTION, title)).to_have_count(0)
    expect(_chat_rows(outsider, KIND_MESSAGE, title)).to_have_count(0)