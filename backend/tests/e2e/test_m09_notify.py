"""T-8139: приёмка сценария 9 — колокольчик и уведомления (FR-663, 664, 665, 666, 667).

Ровно семь пунктов приёмки SPEC-008, «Сценарий 9» (по одному тесту на пункт):
1. новое уведомление — колокольчик открывает мессенджер на вкладке «Уведомления» с потоком (FR-667);
2. старая ссылка на страницу уведомлений открывает ту же вкладку, ссылки в уведомлениях работают (FR-667);
3. сотрудник отключил почту — письма нет, на портале уведомление есть (FR-663, FR-665);
4. сообщение не прочитано 15 минут — уходит письмо; в тихие часы письма нет, на портале уведомление есть, а
   накопленное уходит одной сводкой с началом рабочего дня (FR-663);
5. своё сообщение и упоминание себя уведомлений не дают, несколько сообщений подряд склеиваются в одно, пока не
   прочитаны (FR-666);
6. сообщение в открытой беседе не остаётся непрочитанным в потоке, в закрытой — уведомление есть (FR-666);
7. упоминание в чате при подключённом Telegram — во внешнем канале только событие и ссылка, без текста и имён
   (FR-664).

Общее для файла (CONTRACT-008: 3.3, 7.1–7.3, 10.2, 12, 13.3, 14.3; TASKS-008 T-8139; образцы —
`test_f09_notify.py`, `test_messenger_notify_2.py`/`_3.py`, `test_e10_page.py`):
- люди — `helpers_messenger.messenger_cast` один раз на круг браузера (фикстура `circle`): девять учёток через
  интерфейс на каждый тест — часы прохода; круг браузеров даёт `conftest.py`, своих параметров и пропусков нет;
- уведомления создаёт настоящая отправка сообщений мессенджера (`helpers_messenger.write`, `mention`); читаются
  они на вкладке `/messenger/notifications/` зацепками `notify/_row.html` (`ul[data-notifications]`,
  `li[data-notification][data-unread]`, `[data-field="text"|"kind"]`) и числом колокольчика
  `#notify-count[data-count]` (3.3, 12);
- перед каждым действием непрочитанные получателя гасятся «Прочитать все» (`POST /notifications/read-all/`, 3.3) —
  тогда ровно одна непрочитанная строка принадлежит проверяемому событию, а прежние сообщения круга не мешают;
  этим же закрываются прежние ожидающие письма (`still_relevant` — прочитанное, 7.3);
- письмо после срока — `helpers_notify.tick(shift=121)` (121 минута больше верхней границы срока письма 120,
  CONTRACT-004 6.5); «письма нет» проверяется только после положительного контроля другого получателя того же
  сообщения; тихие часы — «Свои часы» вне текущего московского времени, начало рабочего дня — смена режима на
  «Без тихих часов» (решения C1/E23, как в `test_e07_quiet_digest.py` и `test_f09_notify.py`);
- Telegram включает администратор на время теста (`channels_on`), привязка — `bind_channel`; для внешнего канала
  заводится свежий сотрудник (`employee`), чтобы привязка прежних тестов круга не мешала;
- данные круга общие: названия групп и тексты уникальны; ПДн и секретов нет — ФИО вымышленные, адреса
  `example.test`. Файл правит только T-8139.
"""
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import NamedTuple
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import FormData, expect

from tests.e2e import helpers, helpers_messenger, helpers_notify, helpers_org

MESSAGE_KIND = "messenger.message"
MENTION_KIND = "messenger.mention"
MESSAGE_TITLE = "Новое сообщение в чате"   # CONTRACT-008, 7.1
MENTION_TITLE = "Упомянул вас в чате"      # CONTRACT-008, 7.1
EXTERNAL_MENTION = "Вас упомянули в чате"  # внешний текст вида (7.1)
NOTES = "/messenger/notifications/"
OLD_NOTES = "/notifications/"
CREATE_CHAT = "/messenger/chats/"
READ_ALL = "/notifications/read-all/"
SAVED = "Настройки уведомлений сохранены."  # CONTRACT-004, 15.4
PAST_TERM = 121                              # минут: больше верхней границы срока письма (120)
MAIL_WAIT = 90.0
FRAME_SECONDS = 2.0
WAIT_MS = 4_000                              # ожидание чуть больше нормы: проверка идёт по замеру
PAGE_TIMEOUT = helpers_messenger.PAGE_TIMEOUT
MOSCOW = ZoneInfo("Europe/Moscow")
ALL_DAYS = range(7)
_MSG_ID = re.compile(r'data-message-id="(\d+)"')
_CHAT_LOCATION = re.compile(r"(?:https?://[^/]+)?/messenger/chats/(\d+)/")
_CIRCLES: dict = {}


class Circle(NamedTuple):
    """Круг сценария: учётки и узлы `helpers_messenger.MessengerCast`, собранные один раз на браузер."""
    cast: object


@pytest.fixture
def circle(browser, admin_page, mailpit, new_context) -> Circle:
    """Круг сценария 9: собирается при первом обращении в круге браузера, дальше — сохранённые сессии."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = Circle(helpers_messenger.messenger_cast(admin_page, mailpit, new_context))
    return _CIRCLES[key]


# --- Общие приёмы -------------------------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово текста сообщения (буквы, чтобы поиск не принял его за число)."""
    return "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(8))


def _codes(html: str) -> list:
    """Пары `(поле или "", data-code)` отказов в HTML ответа (CONTRACT-008, 10.1)."""
    found = []
    for tag in re.findall(r"<[^>]*\bdata-code=\"[^\"]*\"[^>]*>", html):
        code = re.search(r'data-code="([^"]*)"', tag).group(1)
        field = re.search(r'data-error="([^"]*)"', tag)
        found.append((field.group(1) if field else "", code))
    return found


def _page(context, account, url):
    """Новая страница в контексте с сессией `account` (`helpers_notify.adopt_session`) на адресе `url`."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto(url)
    page.wait_for_load_state()
    return page


def _expect_flow(page) -> None:
    """Вкладка «Уведомления» страницы мессенджера (12.1, 12.2, 3.3): корень, выбранная вкладка, поток."""
    expect(page.locator('[data-messenger-page="notifications"]')).to_be_visible()
    expect(page.locator('[data-messenger-tab="notifications"]')).to_have_attribute("aria-selected", "true")
    expect(page.locator('[data-messenger-tab="chats"]')).to_have_count(1)
    expect(page.locator("[data-notify-list]")).to_be_visible()


def _flow(context, account, query: str = ""):
    """Страница `/messenger/notifications/` (при `query` — с фильтром) сотрудника `account`."""
    page = _page(context, account, NOTES + query)
    _expect_flow(page)
    return page


def _rows(page):
    """Все строки потока уведомлений (`notify/_row.html`, 3.3)."""
    return page.locator("ul[data-notifications] li[data-notification]")


def _unread(page):
    """Непрочитанные строки потока: `data-unread="1"`."""
    return page.locator('ul[data-notifications] li[data-notification][data-unread="1"]')


def _row_for(page, text: str):
    """Строка потока, в тексте которой есть `text` (0 или 1 после гашения прежних)."""
    return _rows(page).filter(has_text=text).first


def _read_all(context, account) -> None:
    """Гасит все непрочитанные уведомления сотрудника: «Прочитать все» (3.3), затем проверяет число колокольчика."""
    page = _flow(context, account)
    response = helpers_org.direct_post(page, READ_ALL)
    assert response.status == 302, f"«Прочитать все»: ответ {response.status}"
    page.goto(NOTES)
    page.wait_for_load_state()
    _expect_flow(page)
    assert helpers_notify.bell_count(page) == 0, f"после «Прочитать все» на колокольчике {account.email}"
    page.close()


def _wait_row(context, account, text: str, unread: str, timeout: int = PAGE_TIMEOUT):
    """Ждёт строку потока с `data-unread=<unread>` и текстом `text` (перезагрузки до предела). Возвращает страницу
    и строку; не появилась — `AssertionError`."""
    page = _flow(context, account)
    deadline = time.monotonic() + timeout / 1000
    while True:
        row = _row_for(page, text)
        if row.count() and row.get_attribute("data-unread") == unread:
            return page, row
        if time.monotonic() >= deadline:
            raise AssertionError(f"строка «{text}» с data-unread={unread} не появилась за {timeout / 1000:.0f} с")
        page.wait_for_timeout(500)
        page.goto(NOTES)
        page.wait_for_load_state()


def _cell(page, kind: str, channel: str):
    """Флажок ячейки таблицы «Мои уведомления» (`/me/notifications/`, CONTRACT-004 14.3)."""
    return page.locator(f'table[data-notify-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _prefs(context, account, *, cells=None, quiet=None, start=None, end=None) -> None:
    """«Мои уведомления»: ячейки `{(вид, канал): состояние}`, режим тихих часов (`none` или `own` — все дни,
    начало и конец), сохранение; успех — «Настройки уведомлений сохранены.» без отказов (CONTRACT-004 15.4)."""
    page = _page(context, account, "/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for (kind, channel), state in (cells or {}).items():
        _cell(page, kind, channel).set_checked(state)
    if quiet is not None:
        form.locator(f'fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="{quiet}"]').check()
    if quiet == "own":
        for day in ALL_DAYS:
            form.locator(f'fieldset[data-quiet] input[type=checkbox][name="own_days"][value="{day}"]'
                         ).set_checked(True)
        form.locator('fieldset[data-quiet] input[type=time][name="own_start"]').fill(start)
        form.locator('fieldset[data-quiet] input[type=time][name="own_end"]').fill(end)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()
    page.close()


def _hours(start_offset: int, end_offset: int) -> tuple:
    """Часы «ЧЧ:ММ» (Москва) на `start_offset` и `end_offset` часов от текущего момента (переход через полночь
    допустим)."""
    now = datetime.now(MOSCOW)
    return ((now + timedelta(hours=start_offset)).strftime("%H:%M"),
            (now + timedelta(hours=end_offset)).strftime("%H:%M"))


def _dialog(context, author, peer):
    """Личный диалог `author` ↔ `peer`: страница автора в беседе и номер чата (`start_dialog` шлёт первое
    сообщение); повторный вызов на пару открывает ту же переписку (FR-645)."""
    page = helpers_messenger.open_messenger(context, author)
    return page, helpers_messenger.start_dialog(page, peer)


def _create_group(context, author, title: str, members) -> int:
    """Групповой чат `title` с участниками `members` от `author`: `POST /messenger/chats/` (`kind=group`, 10.2);
    зацепки формы создания группа контракт не даёт — приём `test_m02_group.py`. Возвращает номер чата."""
    page = helpers_messenger.open_messenger(context, author, live=False)
    data = FormData()
    for account in members:
        data.append("members", str(account.id))
    data.set("kind", "group")
    data.set("title", title)
    response = helpers_org.direct_post(page, CREATE_CHAT, data)
    assert response.status == 302, f"создание группы {title!r}: ответ {response.status}"
    found = _CHAT_LOCATION.fullmatch(response.headers.get("location", ""))
    assert found, f"после создания чата адрес {response.headers.get('location')!r}"
    page.close()
    return int(found.group(1))


def _send_mention(page, tail: str) -> int:
    """Отправляет уже набранное в поле ввода (подсказка «@» из `mention`) вместе с `tail`; возвращает номер
    сообщения. `write` не годится: он заменяет поле текстом и стёр бы упоминание."""
    form = page.locator("#messenger-form")
    box = form.locator('textarea[name="text"]').first
    box.press_sequentially(" " + tail, delay=10)
    with page.expect_response(lambda r: r.request.method == "POST" and "/messenger/chats/" in r.url
                              and r.url.split("?")[0].endswith("/messages/")) as info:
        form.locator('button[type="submit"]').first.click()
    html = "" if info.value.status in (301, 302, 303, 307, 308) else info.value.text()
    codes = _codes(html)
    assert not codes, f"сообщение с упоминанием отклонено: {codes}"
    ids = [int(value) for value in _MSG_ID.findall(html)]
    if ids:
        return ids[-1]
    article = page.locator("#messenger-messages article[data-message-id]").last
    expect(article).to_be_visible(timeout=helpers_messenger.FRAME_TIMEOUT)
    return int(article.get_attribute("data-message-id"))


def _button_url(message: dict) -> str:
    """Адрес кнопки сообщения Telegram: `reply_markup.inline_keyboard[0][0].url` (CONTRACT-004 15.2)."""
    markup = message["reply_markup"]
    markup = json.loads(markup) if isinstance(markup, str) else markup
    return markup["inline_keyboard"][0][0]["url"]


# --- Тесты (по пунктам приёмки сценария 9) ------------------------------------------------------------------------

def test_m09_bell_opens_messenger_notifications_tab_with_new_notification_flow(circle, new_context):
    """Сценарий 9, п. 1 (FR-667, FR-663): сотрудник получает новое сообщение — колокольчик оболочки ведёт на
    `/messenger/notifications/`, открывается вкладка «Уведомления» с потоком: ровно одна непрочитанная строка
    «<автор>: новое сообщение в чате …» вида «Новое сообщение в чате»."""
    c = circle.cast
    writer, _chat_id = _dialog(new_context(), c.writer, c.peer)
    peer_context = new_context()
    _read_all(peer_context, c.peer)
    watcher = helpers_notify.open_watcher(None, c.peer, spy=False, context=peer_context)

    helpers_messenger.write(writer, "Новое сообщение " + _word())

    helpers_notify.wait_bell_count(watcher, 1, timeout_ms=PAGE_TIMEOUT)   # портал — сразу (FR-663)
    bell = watcher.locator("a[data-bell-link]")
    expect(bell).to_have_attribute("href", NOTES)                        # 3.3: колокольчик — ссылка
    with watcher.expect_navigation():
        bell.click()
    assert urlsplit(watcher.url).path == NOTES, f"колокольчик привёл на {watcher.url}"
    _expect_flow(watcher)

    rows = _unread(watcher)
    expect(rows).to_have_count(1)
    row = rows.first
    expect(row.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)
    expect(row.locator('[data-field="text"]')).to_contain_text(c.writer.full_name)
    expect(row.locator('[data-field="text"] a[data-open]')).to_have_count(1)


def test_m09_old_notifications_address_opens_same_tab_and_notification_link_works(circle, new_context):
    """Сценарий 9, п. 2 (FR-667): старая ссылка `/notifications/?f=unread` отвечает 302 на
    `/messenger/notifications/?f=unread`, открывается та же вкладка с потоком; ссылка уведомления
    (`a[data-open]`) ведёт в беседу к сообщению, текст сообщения на месте."""
    c = circle.cast
    writer, chat_id = _dialog(new_context(), c.writer, c.third)
    third_context = new_context()
    _read_all(third_context, c.third)
    text = "Сообщение по старой ссылке " + _word()
    message_id = helpers_messenger.write(writer, text)

    page = _page(third_context, c.third, "/")
    redirect = helpers_org.direct_get(page, "/notifications/?f=unread")
    assert redirect.status == 302, f"старый адрес: ответ {redirect.status}"
    assert redirect.headers.get("location") == f"{NOTES}?f=unread", redirect.headers.get("location")

    page.goto(OLD_NOTES + "?f=unread")
    page.wait_for_load_state()
    assert urlsplit(page.url).path == NOTES, f"старый адрес открыл {page.url}"
    assert "f=unread" in page.url, page.url
    _expect_flow(page)
    rows = _unread(page)
    expect(rows).to_have_count(1)
    row = rows.first
    expect(row.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)
    link = row.locator('[data-field="text"] a[data-open]')
    expect(link).to_have_count(1)
    with page.expect_navigation():
        link.click()
    assert urlsplit(page.url).path == f"/messenger/chats/{chat_id}/", page.url
    assert page.url.endswith(f"#m{message_id}"), page.url
    message = page.locator(f'article[data-message-id="{message_id}"]')
    expect(message).to_be_visible()
    expect(message).to_contain_text(text)


def test_m09_email_switched_off_sends_no_letter_and_keeps_portal_notification(circle, new_context, mailpit):
    """Сценарий 9, п. 3 (FR-663, FR-665): сотрудник отключил почту у видов мессенджера — после срока письма письма
    нет, уведомление на портале есть; контроль того же сообщения — второй участник с включённой почтой получает
    письмо (срок 15 минут прошёл, `tick(shift=121)`)."""
    c = circle.cast
    title = helpers_org.unique_name("Беседа без почты")
    chat_id = _create_group(new_context(), c.writer, title, [c.creator, c.department_member])
    off_context = new_context()
    _read_all(off_context, c.creator)
    _prefs(off_context, c.creator, cells={(MESSAGE_KIND, "email"): False, (MENTION_KIND, "email"): False},
           quiet="none")
    control_context = new_context()
    _read_all(control_context, c.department_member)
    _prefs(control_context, c.department_member, cells={(MESSAGE_KIND, "email"): True}, quiet="none")

    writer = helpers_messenger.open_chat(new_context(), c.writer, chat_id)
    helpers_messenger.write(writer, "Сообщение без письма " + _word())

    portal = _flow(off_context, c.creator)
    expect(_unread(portal)).to_have_count(1)                      # портал приходит всегда (FR-665)
    expect(_unread(portal).first.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)

    assert helpers_notify.tick(shift=PAST_TERM)["shifted"] >= 1, "срок письма не наступил ни у кого"
    helpers_notify.wait_item_mail(mailpit, c.department_member.email, timeout=MAIL_WAIT)  # контроль
    assert helpers_notify.no_item_mail(mailpit, c.creator.email, wait=10), "письмо при отключённой почте"

    portal.goto(NOTES)
    portal.wait_for_load_state()
    _expect_flow(portal)
    expect(_unread(portal)).to_have_count(1)


def test_m09_unread_message_after_term_sends_mail_quiet_hours_hold_it_and_digest_comes_at_work_start(
        circle, new_context, mailpit):
    """Сценарий 9, п. 4 (FR-663): сообщение не прочитано — после срока уходит письмо (контроль с «Без тихих
    часов»); у сотрудника в тихих часах письма нет, на портале уведомление есть, а накопленное уходит одной
    сводкой с началом рабочего дня (режим «Без тихих часов», `tick()`, письмо `notify.digest`)."""
    c = circle.cast
    title = helpers_org.unique_name("Вечерняя беседа")
    chat_id = _create_group(new_context(), c.writer, title, [c.outsider, c.department_newcomer])
    quiet_context = new_context()
    _read_all(quiet_context, c.outsider)
    start, end = _hours(3, 4)                     # окно вне текущего московского времени
    _prefs(quiet_context, c.outsider, cells={(MESSAGE_KIND, "email"): True}, quiet="own", start=start, end=end)
    control_context = new_context()
    _read_all(control_context, c.department_newcomer)
    _prefs(control_context, c.department_newcomer, cells={(MESSAGE_KIND, "email"): True}, quiet="none")

    writer = helpers_messenger.open_chat(new_context(), c.writer, chat_id)
    helpers_messenger.write(writer, "Сообщение на вечер " + _word())

    portal = _flow(quiet_context, c.outsider)
    expect(_unread(portal)).to_have_count(1)                      # на портале — сразу
    expect(_unread(portal).first.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)

    assert helpers_notify.tick(shift=PAST_TERM)["shifted"] >= 1, "срок письма не наступил ни у кого"
    helpers_notify.wait_item_mail(mailpit, c.department_newcomer.email, timeout=MAIL_WAIT)  # письмо через 15 минут
    assert helpers_notify.no_item_mail(mailpit, c.outsider.email, wait=10), "письмо в тихие часы"
    assert helpers_notify.no_digest_mail(mailpit, c.outsider.email, wait=2), "сводка до начала рабочего дня"

    _prefs(quiet_context, c.outsider, cells={(MESSAGE_KIND, "email"): True}, quiet="none")  # начало рабочего дня
    helpers_notify.tick()
    mail = helpers_notify.wait_digest_mail(mailpit, c.outsider.email, timeout=MAIL_WAIT)
    assert mail["Subject"] == "За нерабочее время: 1 уведомление", mail["Subject"]
    assert helpers_notify.no_item_mail(mailpit, c.outsider.email, wait=4), "вместе со сводкой ушло отдельное письмо"

    portal.goto(NOTES)
    portal.wait_for_load_state()
    _expect_flow(portal)
    expect(_unread(portal)).to_have_count(1)                      # уведомление остаётся на портале непрочитанным


def test_m09_own_message_and_self_mention_give_no_notification_and_three_messages_coalesce(
        circle, new_context):
    """Сценарий 9, п. 5 (FR-666): три сообщения подряд одному получателю до прочтения дают одно уведомление
    «Новых сообщений: 3 в чате «…»»; своё сообщение и упоминание себя уведомлений автору не дают, а участнику
    группы уходит обычное «Новое сообщение в чате» (контроль)."""
    c = circle.cast
    writer, _chat_id = _dialog(new_context(), c.writer, c.peer)
    peer_context = new_context()
    _read_all(peer_context, c.peer)
    for number in range(1, 4):
        helpers_messenger.write(writer, f"Склейка {number} {_word()}")

    peer_flow = _flow(peer_context, c.peer)
    expect(_unread(peer_flow)).to_have_count(1)                   # три сообщения — одно уведомление
    coalesced = _unread(peer_flow).first
    expect(coalesced.locator('[data-field="text"]')).to_have_text(
        f"Новых сообщений: 3 в чате «{c.writer.full_name}»")
    expect(coalesced.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)

    own_context = new_context()
    _read_all(own_context, c.writer)
    own = _flow(own_context, c.writer)
    helpers_messenger.write(writer, "Своё сообщение " + _word())
    own.goto(NOTES)
    own.wait_for_load_state()
    _expect_flow(own)
    expect(_unread(own)).to_have_count(0)
    assert helpers_notify.bell_count(own) == 0, "своё сообщение дало уведомление автору"

    title = helpers_org.unique_name("Беседа с собой")
    group_id = _create_group(new_context(), c.writer, title, [c.department_member])
    member_context = new_context()
    _read_all(member_context, c.department_member)
    chat = helpers_messenger.open_chat(new_context(), c.writer, group_id)
    helpers_messenger.mention(chat, c.writer.full_name)           # упоминание самого себя
    _send_mention(chat, "Заметка себе " + _word())

    own.goto(NOTES)
    own.wait_for_load_state()
    _expect_flow(own)
    expect(_unread(own)).to_have_count(0)
    assert title not in " ".join(_rows(own).all_inner_texts()), "упоминание себя дало уведомление автору"

    member = _flow(member_context, c.department_member)
    expect(_unread(member)).to_have_count(1)                      # контроль: участнику — обычное уведомление
    expect(_unread(member).first.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)
    expect(_unread(member).first.locator('[data-field="text"]')).to_contain_text(c.writer.full_name)


def test_m09_message_in_open_chat_is_not_unread_in_flow_and_closed_chat_keeps_notification(
        circle, new_context):
    """Сценарий 9, п. 6 (FR-666): беседа получателя открыта — пришедшее сообщение видно в ней, но в потоке
    уведомлений не остаётся непрочитанным (в фильтре «непрочитанные» строки нет); у второго участника с закрытой
    беседой уведомление непрочитано и число колокольчика больше нуля."""
    c = circle.cast
    title = helpers_org.unique_name("Открытая беседа")
    chat_id = _create_group(new_context(), c.writer, title, [c.third, c.peer])
    open_context = new_context()
    _read_all(open_context, c.third)
    opened = helpers_messenger.open_chat(open_context, c.third, chat_id)
    closed_context = new_context()
    _read_all(closed_context, c.peer)

    writer = helpers_messenger.open_chat(new_context(), c.writer, chat_id)
    text = "Сообщение в открытую беседу " + _word()
    started = time.monotonic()
    message_id = helpers_messenger.write(writer, text)
    expect(opened.locator(f'article[data-message-id="{message_id}"]')).to_be_visible(timeout=WAIT_MS)
    elapsed = time.monotonic() - started
    assert elapsed <= FRAME_SECONDS, f"сообщение в открытой беседе появилось за {elapsed:.2f} с при норме 2 с"

    page, row = _wait_row(open_context, c.third, title, "0")
    note_id = row.get_attribute("data-notification")
    page.goto(NOTES + "?f=unread")
    page.wait_for_load_state()
    _expect_flow(page)
    expect(page.locator(f'li[data-notification="{note_id}"]')).to_have_count(0)  # в непрочитанных его нет
    assert helpers_notify.bell_count(page) == 0, "у открытой беседы осталось непрочитанное уведомление"

    closed, closed_row = _wait_row(closed_context, c.peer, title, "1")
    expect(closed_row.locator('[data-field="kind"]')).to_have_text(MESSAGE_TITLE)
    expect(closed_row.locator('[data-field="text"]')).to_contain_text(c.writer.full_name)
    assert helpers_notify.bell_count(closed) == 1, "у закрытой беседы нет непрочитанного уведомления"


def test_m09_mention_in_chat_sends_only_event_and_link_without_text_or_names(circle, new_context, admin_page,
                                                                             employee):
    """Сценарий 9, п. 7 (FR-664, NFR-705): упоминание в чате при подключённом Telegram — во внешнем канале только
    постоянный текст «Вас упомянули в чате» и кнопка на страницу уведомлений портала; ФИО, названия чата и текста
    сообщения нет ни в тексте, ни в кнопке. На портале упомянутому — отдельное «Упомянул вас в чате»."""
    c = circle.cast
    token = secrets.token_hex(3)
    mentioned = employee(full_name=f"Упомянутая{token} Иван Иванович")
    bots, chat = helpers_notify.fakebots(), secrets.randbelow(900_000_000) + 100_000_000
    title = helpers_org.unique_name("Беседа упоминания")
    body = "секретное поручение " + _word()

    with helpers_notify.channels_on(admin_page, "telegram"):
        helpers_notify.bind_channel(mentioned.page, bots, "telegram", chat)
        _read_all(mentioned.page.context, mentioned)
        _prefs(mentioned.page.context, mentioned, cells={(MENTION_KIND, "telegram"): True}, quiet="none")
        group_id = _create_group(new_context(), c.writer, title, [mentioned])
        chat_page = helpers_messenger.open_chat(new_context(), c.writer, group_id)
        helpers_messenger.mention(chat_page, mentioned.full_name)
        _send_mention(chat_page, body)

        found = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_MENTION)

    assert len(found) == 1, f"сообщений «{EXTERNAL_MENTION}» в свой чат: {len(found)}"
    message = found[0]
    assert message["text"] == EXTERNAL_MENTION
    dump = json.dumps(message, ensure_ascii=False)
    for forbidden in (c.writer.full_name, mentioned.full_name, title, body, c.writer.email, mentioned.email):
        assert forbidden not in dump, "во внешнем сообщении есть текст или имя"
    assert urlsplit(_button_url(message)).path == OLD_NOTES   # кнопка — страница уведомлений портала

    portal = _flow(mentioned.page.context, mentioned)
    expect(_unread(portal)).to_have_count(1)
    expect(_unread(portal).first.locator('[data-field="kind"]')).to_have_text(MENTION_TITLE)
    expect(_unread(portal).first.locator('[data-field="text"]')).to_contain_text(c.writer.full_name)