"""Помощники приёмки среза 008 «Мессенджер» (T-8130; ими пользуются T-8131…T-8143).

Что здесь есть (CONTRACT-008.md: разделы 1.4, 10, 12, 13.3, 14.1, 14.3; решения К17-К21; план, «Проход в браузере»):
- роли и учётки тринадцати сценариев: `MessengerCast`, `messenger_cast` (`writer`, `peer`, `third`, `creator`,
  `department_member`, `department_newcomer`, `outsider`, `admin`, `dismissed`; узлы «Отдел ИТ», «Группа сети»,
  «Бухгалтерия»);
- вход и страницы: `open_messenger(context, account, live=True)`, `open_chat(context, account, chat_id)`;
- начало личного диалога: `start_dialog(page, account)` — «Написать» в карточке сотрудника или `/messenger/people/`;
- отправка: `write`, `try_write`; правка и удаление своим меню: `edit_message`, `delete_message`; цитата: `quote`;
- подсказка «@»: `mention`, `chat_mention`;
- файлы (ClamAV стенда): `upload`, `wait_clean`, `eicar_file`;
- счётчики и живые кадры: `unread`, `wait_unread`, `badge`, `wait_badge`, `wait_message`, `wait_read_line`;
- команда стенда: `age(days)` над `e2e_messenger_age` (14.1);
- без WebSocket: `block_ws(context)`; ширина 360 px: `check_360(page)`.

Правила (шаблон `e2e/template.md`): код приложения (`apps.*`, `django`) и `tests.support*` не импортируются — тесты
идут с хоста против стенда; локаторы — только зацепки CONTRACT-008 раздела 12 (`data-*`, `id`); ждать — `expect`,
`expect_response`, `wait_for_url`; сна нет (готовность файла — опрос `wait_for_timeout`); отказы форм —
`[data-error="<поле>"][data-code]` и `[role=alert][data-code]` (10.1); данные круга общие, поэтому все названия
уникальны. Готовое из прежних срезов вызывается, не дублируется: `helpers` (`Account`, `make_employee`, `submit`,
`no_horizontal_scroll`), `helpers_org` (`open_structure`, `root_id`, `create_unit`, `add_members`, `unique_name`),
`helpers_sd._stand_command`, `helpers_notify.adopt_session`, `helpers_kb.eicar_bytes`.

Оговорки (вопросы Opus — в отчёте T-8130):
- меню сообщения контракт не зацепляет: он называет только результат (`[data-quote-id]`, `[data-messenger-edited]`,
  `[data-messenger-deleted]`), поэтому пункты «Ответить», «Править», «Удалить» ищутся по видимой подписи внутри
  `article[data-message-id]` (`_menu_action`); сворачиваемое меню-`<details>` раскрывается;
- форма ввода на странице `?to=` — тот же фрагмент `_form.html` с `#messenger-form` (12.3);
- «проверяется → чистый» ждёт только `wait_clean`: контракт не даёт имени для ожидания карантина (T-8137).
Файл правит только T-8130.
"""
import re
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_notify, helpers_org, helpers_sd

PAGE_TIMEOUT = 20_000          # готовность узла соединения беседы (12.4)
# Узел соединения беседы: у колокольчика тоже есть `data-ws`, поэтому ищем по адресу слоя мессенджера.
WS_CHAT = '[data-ws][ws-connect*="/ws/messenger/"]'
FRAME_TIMEOUT = 2_000          # живой кадр до получателя и числа (FR-660, NFR-701)
FILE_TIMEOUT = 60_000          # «проверяется → чистый» (FR-662, NFR-704)
AGE_MIN, AGE_MAX = 1, 4_000    # границы `--days` команды `e2e_messenger_age` (14.1, К21)
FIRST_TEXT = "Здравствуйте! Начнём диалог."   # первое сообщение `start_dialog`
QUOTE_TEXT = "Ответ на сообщение."            # текст ответа-цитаты `quote`

_WS_URL = re.compile(r"/ws/(messenger|notify)/")
_MSG_ID = re.compile(r'data-message-id="(\d+)"')
_FILE_ID = re.compile(r'data-messenger-file="(\d+)"')
_CHAT_URL = re.compile(r"/messenger/chats/(\d+)/")
_MENTION_MARK = re.compile(r"[@#]")


# --- Люди и узлы сценариев (14.3, `MessengerCast`) ------------------------------------------------------------

class MessengerCast(NamedTuple):
    """Участники сценариев мессенджера. Учётки — `helpers.Account` (сессия — `Account.storage_state`); узлы —
    номера строкой. Уволенный сессии не имеет (он создан без активации)."""
    writer: object                # сотрудник, пишущий всем
    peer: object                  # собеседник личного диалога
    third: object                 # сотрудник вне чата
    creator: object               # создатель группы
    department_member: object     # сотрудник «Отдела ИТ»
    department_newcomer: object   # новичок: в узле ещё не состоит (сценарий 3)
    outsider: object              # сотрудник «Бухгалтерии»
    admin: object                 # администратор портала
    dismissed: object             # уволенный сотрудник
    it_unit: str                  # «Отдел ИТ», отдел
    net_unit: str                 # «Группа сети», команда внутри «Отдела ИТ»
    other_unit: str               # «Бухгалтерия», отдел


def _dismiss(page, user_id) -> None:
    """Увольняет сотрудника из карточки `/staff/<id>/` (прежние зацепки CONTRACT-002/003: `[data-action="dismiss"]`,
    диалог `#dialog-root [data-dialog="dismiss"]`, `form[data-form="dismiss"]`, `[data-dismissed-badge]`; образец —
    `test_o07_dismiss`). Нужен только для роли «уволенный»."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    expect(card).to_be_visible()
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def messenger_cast(admin_page, mailpit, new_context) -> MessengerCast:
    """Создаёт узлы и учётки через интерфейс (`helpers.make_employee`, `helpers_org.create_unit`,
    `helpers_org.add_members`). Названия узлов и ФИО уникальны на круг (`<имя>-<hex>`; у всех людей общая часть
    `<hex>`, чтобы один запрос `add_members(q=…)` находил их). Собственных ролей у среза нет (план, «Права среза»):
    все, кроме администратора, — «Сотрудник ИТ». `department_member` состоит в «Отделе ИТ»; «Группа сети» —
    команда внутри него и остаётся пустой (участника вложенного узла добавляет сценарий 3); `outsider` — в
    «Бухгалтерии»; `department_newcomer` — ни в одном узле; `dismissed` создан без активации и уволен.
    Сессии всех учёток переносятся в `Account.storage_state` (контексты освобождаются)."""
    token = helpers_org.unique_name("м")[2:]

    def person(surname: str, *, role: str = helpers.STAFF_ROLE, activate: bool = True):
        return helpers.make_employee(admin_page, mailpit, new_context, role=role, activate=activate,
                                     full_name=f"{surname}{token} Иван Иванович")

    writer = person("Писарев")
    peer = person("Собеседников")
    third = person("Третин")
    creator = person("Создателев")
    department_member = person("Отделов")
    department_newcomer = person("Новиков")
    outsider = person("Чужаков")
    admin = person("Админов", role=helpers.ADMIN_ROLE)
    dismissed = person("Уволенов", activate=False)

    helpers_org.open_structure(admin_page)
    root_id = helpers_org.root_id(admin_page)
    it_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Отдел ИТ"), kind="department",
                                      parent_id=root_id)
    net_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Группа сети"), kind="team",
                                       parent_id=it_unit)
    other_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Бухгалтерия"), kind="department",
                                         parent_id=root_id)
    helpers_org.add_members(admin_page, it_unit, [department_member.id], q=token)
    helpers_org.add_members(admin_page, other_unit, [outsider.id], q=token)
    _dismiss(admin_page, dismissed.id)

    for account in (writer, peer, third, creator, department_member, department_newcomer, outsider, admin):
        account.storage_state = account.page.context.storage_state()
        account.page = None
    return MessengerCast(writer, peer, third, creator, department_member, department_newcomer, outsider, admin,
                         dismissed, it_unit, net_unit, other_unit)


# --- Вход и страницы (14.3) ------------------------------------------------------------------------------------

def open_messenger(context, account, live: bool = True):
    """Сессия `account` переносится в `context` (`helpers_notify.adopt_session`), новая страница, `/messenger/`.
    `live=True` — ждёт узел соединения беседы `[data-ws]` (на широком экране первый чат открыт; «Общий чат» есть у
    всех после установки); `live=False` (после `block_ws`) — только страницу и корень `[data-messenger-page="list"]`.
    Возвращает страницу."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto("/messenger/")
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    if live:
        expect(page.locator(WS_CHAT)).to_be_attached(timeout=PAGE_TIMEOUT)
    return page


def open_chat(context, account, chat_id):
    """Сессия `account` в `context`, `/messenger/chats/<id>/`, ждёт `[data-messenger-page="chat"]` и
    `[data-ws="open"]` (12.4). Возвращает страницу."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto(f"/messenger/chats/{chat_id}/")
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="chat"]')).to_be_visible()
    expect(page.locator(WS_CHAT)).to_have_attribute(
        "data-ws", "open", timeout=PAGE_TIMEOUT)
    return page


# --- Начало личного диалога (10.2, 12.6) -----------------------------------------------------------------------

def start_dialog(page, account) -> int:
    """Первый личный диалог с `account`: «Написать» в уже открытой карточке сотрудника
    (`[data-messenger-card-write]`, 12.6) или в `/messenger/people/?q=<фамилия>` — строка `[data-person-id="<id>"]`
    со ссылкой `/messenger/?to=<id>`; затем первое сообщение `FIRST_TEXT` формой `#messenger-form`. Форма —
    обычный POST: по CONTRACT-008 10.2 ответ 302 на беседу, браузер идёт по нему сам. Возвращает номер чата."""
    card_button = page.locator("[data-messenger-card-write]")
    if card_button.count():
        card_button.first.click()
    else:
        page.goto("/messenger/people/?" + urlencode({"q": account.full_name.split()[0]}))
        row = page.locator(f'[data-person-id="{account.id}"]').first
        expect(row).to_be_visible()
        action = row.locator(f'a[href="/messenger/?to={account.id}"]')
        if not action.count():
            action = row.get_by_role("link", name="Написать", exact=True)
        expect(action.first).to_be_visible()
        action.first.click()
    expect(page.locator('[data-messenger-page="write"]')).to_be_visible()
    form = _form(page)
    expect(form).to_be_visible()
    form.locator('textarea[name="text"]').first.fill(FIRST_TEXT)
    form.locator('button[type="submit"]').first.click()
    page.wait_for_url(_CHAT_URL, timeout=PAGE_TIMEOUT)
    return int(_CHAT_URL.search(page.url).group(1))


# --- Отправка, правка, удаление, цитата, «@» (10.2, 12.3) -------------------------------------------------------

def _form(page):
    """Форма ввода беседы `#messenger-form` (12.3)."""
    return page.locator("#messenger-form")


def _message(page, message_id):
    """Сообщение `article#m<id>[data-message-id]` (12.3)."""
    return page.locator(f'article[data-message-id="{message_id}"]').first


def _codes_in(html: str) -> list:
    """Отказы в HTML ответа: пары `(поле или "", код)` по порядку (10.1)."""
    out = []
    for tag in re.findall(r"<[^>]*\bdata-code=\"[^\"]*\"[^>]*>", html):
        code = re.search(r'data-code="([^"]*)"', tag).group(1)
        field = re.search(r'data-error="([^"]*)"', tag)
        out.append((field.group(1) if field else "", code))
    return out


def _menu_action(node, label: str) -> None:
    """Пункт меню сообщения по видимой подписи `label` («Ответить», «Править», «Удалить»): кнопка или ссылка;
    сворачиваемое меню (`<details>`) раскрывается. Контракт зацепку меню не называет (см. шапку файла)."""
    item = node.get_by_role("button", name=label, exact=True)
    if not item.count():
        item = node.get_by_role("link", name=label, exact=True)
    if not item.count() and node.locator("summary").count():
        node.locator("summary").first.click()
        item = node.get_by_role("button", name=label, exact=True)
        if not item.count():
            item = node.get_by_role("link", name=label, exact=True)
    assert item.count(), f"у сообщения нет пункта «{label}»"
    expect(item.first).to_be_visible()
    item.first.click()


def _send(page, text: str) -> str:
    """Заполняет поле ввода и отправляет форму беседы; возвращает тело ответа на POST `…/messages/`.

    Обычный POST по CONTRACT-008 10.2 даёт 302 на беседу (тела у ответа нет) — тогда возвращается пустая строка,
    а номер сообщения берётся из истории страницы (`_sent_id`)."""
    form = _form(page)
    expect(form).to_be_visible()
    form.locator('textarea[name="text"]').first.fill(text)
    with page.expect_response(lambda r: r.request.method == "POST" and "/messenger/chats/" in r.url
                              and r.url.split("?")[0].endswith("/messages/")) as info:
        form.locator('button[type="submit"]').first.click()
    response = info.value
    if response.status in (301, 302, 303, 307, 308):
        page.wait_for_load_state()
        return ""
    return response.text()


def _sent_id(page, html: str) -> int:
    """Номер отправленного сообщения: из ответа (`data-message-id`) или, если ответ без фрагмента (302), —
    последнее сообщение истории."""
    ids = [int(value) for value in _MSG_ID.findall(html)]
    if ids:
        return ids[-1]
    article = page.locator("#messenger-messages article[data-message-id]").last
    expect(article).to_be_visible(timeout=FRAME_TIMEOUT)
    return int(article.get_attribute("data-message-id"))


def write(page, text: str) -> int:
    """Отправляет `text` формой `#messenger-form` беседы, ждёт сообщение `article[data-message-id]` и очищенное
    поле; возвращает номер сообщения. Отказ — `AssertionError` с парами `(поле, код)` (для проверки отказов —
    `try_write`)."""
    html = _send(page, text)
    codes = _codes_in(html)
    assert not codes, f"сообщение отклонено: {codes}"
    message_id = _sent_id(page, html)
    expect(_message(page, message_id)).to_be_visible(timeout=FRAME_TIMEOUT)
    expect(_form(page).locator('textarea[name="text"]')).to_have_value("")
    return message_id


def try_write(page, text: str) -> list:
    """То же, что `write`, но без ожидания сообщения: пары `(поле или "", data-code)` отказов из ответа (общий
    отказ `[role=alert]` — поле `""`). Пустой список — отправлено."""
    return _codes_in(_send(page, text))


def edit_message(page, message_id, text: str) -> None:
    """Правит своё сообщение своим меню («Править»), форма правки — в самом сообщении; ждёт ответ на
    `…/messages/<id>/edit/` и пометку `[data-messenger-edited]`. Отказ — `AssertionError` с парами `(поле, код)`."""
    node = _message(page, message_id)
    expect(node).to_be_visible()
    _menu_action(node, "Править")
    form = node.locator("form").first
    expect(form).to_be_visible()
    form.locator('textarea[name="text"]').first.fill(text)
    with page.expect_response(lambda r: r.request.method == "POST"
                              and f"/messenger/messages/{message_id}/edit/" in r.url) as info:
        form.locator('button[type="submit"]').first.click()
    codes = _codes_in(info.value.text())
    assert not codes, f"правка отклонена: {codes}"
    expect(_message(page, message_id).locator("[data-messenger-edited]")).to_be_visible(timeout=FRAME_TIMEOUT)


def delete_message(page, message_id) -> None:
    """Удаляет своё сообщение своим меню («Удалить»); ждёт ответ на `…/messages/<id>/delete/` и серую запись
    `[data-messenger-deleted]` на месте сообщения."""
    node = _message(page, message_id)
    expect(node).to_be_visible()
    with page.expect_response(lambda r: r.request.method == "POST"
                              and f"/messenger/messages/{message_id}/delete/" in r.url) as info:
        _menu_action(node, "Удалить")
    codes = _codes_in(info.value.text())
    assert not codes, f"удаление отклонено: {codes}"
    expect(_message(page, message_id).locator("[data-messenger-deleted]")).to_be_visible(timeout=FRAME_TIMEOUT)


def quote(page, message_id) -> int:
    """«Ответить» у сообщения: в поле ввода появляется цитата `[data-quote]`, уходит `QUOTE_TEXT`; у ответа ровно
    одна `[data-quote-id="<исходное>"]` и вложенной цитаты нет (FR-654). Возвращает номер ответа."""
    node = _message(page, message_id)
    expect(node).to_be_visible()
    _menu_action(node, "Ответить")
    expect(_form(page).locator("[data-quote]")).to_be_visible()
    html = _send(page, QUOTE_TEXT)
    codes = _codes_in(html)
    assert not codes, f"ответ отклонён: {codes}"
    reply_id = _sent_id(page, html)
    reply = _message(page, reply_id)
    expect(reply).to_be_visible(timeout=FRAME_TIMEOUT)
    expect(reply.locator(f'[data-quote-id="{message_id}"]')).to_have_count(1)
    assert reply.locator("[data-quote-id] [data-quote-id]").count() == 0, "у ответа второй уровень цитаты"
    return reply_id


def mention(page, name: str) -> None:
    """«@»: в поле ввода `#messenger-form` набирает `@<первое слово>` и выбирает строку подсказки
    `[data-messenger-mention-list] [data-mention-value]` с этим именем; ждёт в поле `@ФИО` (участник) или
    `#название` (чат). На сервер уходит маркер, а не текст (FR-655)."""
    form = _form(page)
    box = form.locator('textarea[name="text"]').first
    box.focus()
    at_boundary = box.evaluate(
        "el => { const p = el.value.slice(0, el.selectionStart); return p === '' || /[\\s(]$/.test(p); }"
    )
    if not at_boundary:
        box.press_sequentially(" ")
    box.press_sequentially("@" + name.split()[0], delay=30)
    rows = page.locator("[data-messenger-mention-list] [data-mention-value]")
    option = rows.filter(has_text=name).first
    inserted = name
    if not option.count():
        inserted = name.split()[0]
        option = rows.filter(has_text=inserted).first
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    expect(box).to_have_value(re.compile(r"[@#]" + re.escape(inserted)))
    value = box.input_value()
    assert _MENTION_MARK.search(value), f"в поле ввода нет маркера «@»/«#»: {value!r}"


def chat_mention(name: str) -> str:
    """Значение упоминания чата в поле ввода: `#<название>` (FR-655; `mention` выбирает строку подсказки)."""
    return f"#{name}"


# --- Файлы (12.5, 14.3) ----------------------------------------------------------------------------------------

def upload(page, path) -> int:
    """Кладёт файл в `input[type="file"][data-messenger-upload]` формы `#messenger-form` и ждёт ответ
    `/messenger/files/`; возвращает номер вложения (номер таблетки `[data-messenger-file]` — `MessageAttachment`).
    Отказ (размер, тип, 11-й файл, 31-й непривязанный) — `AssertionError` с парами `(поле, код)`."""
    form = _form(page)
    with page.expect_response(lambda r: r.request.method == "POST" and "/messenger/files/" in r.url) as info:
        form.locator('input[type="file"][data-messenger-upload]').set_input_files(str(path))
    html = info.value.text()
    codes = _codes_in(html)
    assert not codes, f"файл {Path(str(path)).name} отклонён: {codes}"
    ids = _FILE_ID.findall(html)
    assert ids, "в ответе на загрузку нет таблетки data-messenger-file"
    file_id = int(ids[-1])
    expect(form.locator(f'[data-messenger-file="{file_id}"]')).to_be_visible()
    return file_id


def wait_clean(page, file_id, timeout: int = FILE_TIMEOUT) -> None:
    """Ждёт «проверяется → чистый»: `[data-messenger-file="<id>"][data-file-state="clean"]` после обновления
    страницы (пауза 2 с; FR-662, NFR-704). Звать после отправки сообщения с файлом: у таблетки до отправки
    состояния нет. «Карантин» и истечение `timeout` мс — `AssertionError`."""
    deadline = time.monotonic() + timeout / 1000
    selector = f'[data-messenger-file="{file_id}"][data-file-state]'
    while True:
        node = page.locator(selector).first
        if node.count():
            state = node.get_attribute("data-file-state")
            assert state != "quarantine", f"файл {file_id}: ожидался чистый, а состояние «карантин»"
            if state == "clean":
                return
        if time.monotonic() > deadline:
            raise AssertionError(f"файл {file_id}: проверка не закончилась за {timeout // 1000} с")
        page.wait_for_timeout(2_000)
        page.reload()
        page.wait_for_load_state()


def eicar_file(tmp_path) -> Path:
    """Файл с тестовой строкой EICAR, собранной из частей (`helpers_kb.eicar_bytes`), в `tmp_path`; имя
    `eicar-test.txt` (не исполняемый тип: до ClamAV файл доходит)."""
    path = Path(tmp_path) / "eicar-test.txt"
    path.write_bytes(helpers_kb.eicar_bytes())
    return path


# --- Счётчики и живые кадры (12.2, 12.3, 14.3) -----------------------------------------------------------------

def unread(page, chat_id) -> int:
    """Число непрочитанных у чата `#chat-<id>-unread[data-count]`. Нет узла или атрибута — `AssertionError`."""
    node = page.locator(f"#chat-{chat_id}-unread")
    value = node.get_attribute("data-count") if node.count() else None
    if value is None:
        raise AssertionError(f"на странице {page.url} нет #chat-{chat_id}-unread[data-count]")
    return int(value)


def wait_unread(page, chat_id, value, timeout: int = FRAME_TIMEOUT) -> None:
    """Ждёт `#chat-<id>-unread[data-count="<value>"]` (по умолчанию 2 с: число приходит живым кадром)."""
    expect(page.locator(f"#chat-{chat_id}-unread")).to_have_attribute("data-count", str(int(value)),
                                                                     timeout=timeout)


def badge(page) -> int:
    """Число у пункта «Мессенджер»: `#menu-badge-messenger[data-count]`. Нет узла или атрибута — `AssertionError`."""
    node = page.locator("#menu-badge-messenger")
    value = node.get_attribute("data-count") if node.count() else None
    if value is None:
        raise AssertionError(f"на странице {page.url} нет #menu-badge-messenger[data-count]")
    return int(value)


def wait_badge(page, value, timeout: int = FRAME_TIMEOUT) -> None:
    """Ждёт `#menu-badge-messenger[data-count="<value>"]` (по умолчанию 2 с)."""
    expect(page.locator("#menu-badge-messenger")).to_have_attribute("data-count", str(int(value)), timeout=timeout)


def wait_message(page, message_id, timeout: int = FRAME_TIMEOUT) -> None:
    """Ждёт кадр по `article[data-message-id="<id>"]`: новое сообщение, правка или замена удалённого."""
    expect(page.locator(f'article[data-message-id="{message_id}"]')).to_be_visible(timeout=timeout)


def wait_read_line(page, text: str, timeout: int = FRAME_TIMEOUT) -> None:
    """Ждёт `#messenger-read` с текстом «Прочитали N из M» у последнего своего сообщения (FR-659)."""
    expect(page.locator("#messenger-read")).to_contain_text(text, timeout=timeout)


# --- Команда стенда (14.1) -------------------------------------------------------------------------------------

def _whole(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name}: нужно целое от {low} до {high}, получено {value!r}")
    return value


def _parse_age(line: str) -> dict:
    """Строка `messenger_age: aged=<N>` → `{"aged": N}`; другая форма или нечисло — `AssertionError`."""
    prefix = "messenger_age"
    assert line.startswith(prefix + ": "), f"ожидалась строка «{prefix}: …», получено: {line[:200]!r}"
    result = {}
    for part in line[len(prefix) + 2:].split():
        key, sep, value = part.partition("=")
        assert sep and re.fullmatch(r"\d+", value), f"в строке «{prefix}» часть {part[:80]!r} не вида ключ=число"
        result[key] = int(value)
    assert tuple(result) == ("aged",), f"строка «{prefix}»: ключи {tuple(result)}, ожидался «aged»"
    return result


def age(days) -> dict:
    """`e2e_messenger_age --days N` (14.1) через `helpers_sd._stand_command`: состаривает все сообщения стенда на N
    суток и печатает `messenger_age: aged=<N>`. N — целое 1…4000 (иначе `ValueError` до вызова).
    Возвращает `{"aged": …}`."""
    days = _whole(days, "days", AGE_MIN, AGE_MAX)
    return _parse_age(helpers_sd._stand_command("e2e_messenger_age", "--days", str(days)))


# --- Без WebSocket’а (12.4, образец `helpers_feed.block_ws`) ---------------------------------------------------

def _close_ws(ws) -> None:
    """Закрытие перехваченного соединения так, чтобы callback маршрута не запирал dispatcher Playwright (T-7261
    среза 007): callback только регистрирует обработчик, а закрывает `on_message` — его зовёт channel-event
    greenlet, где синхронный `close` не блокирует event loop. Маршрут без `connect_to_server` на сервер не ходит;
    `/ws/messenger/` шлёт `sync` сразу после открытия и закрывается, «молчащий» `/ws/notify/` остаётся без кадров."""
    ws.on_message(lambda _message: ws.close(reason="blocked by test"))


def block_ws(context) -> None:
    """Перехват `/ws/messenger/` и `/ws/notify/` в `context` (`BrowserContext.route_web_socket`, Playwright 1.63):
    серверных кадров не приходит, страница работает обычными запросами. Звать ДО создания страниц (маршрут
    действует на соединения, открытые после вызова); дальше — `open_messenger(context, account, live=False)`."""
    context.route_web_socket(_WS_URL, _close_ws)


# --- Узкий экран (14.3) ----------------------------------------------------------------------------------------

def check_360(page) -> bool:
    """Окно шириной 360 px (высота прежняя): одна колонка (видимые панели списка и беседы, если обе есть, стоят
    друг под другом, а не рядом) и нет горизонтальной прокрутки (`helpers.no_horizontal_scroll`). Нарушение —
    `AssertionError`; иначе `True` (годится и как `assert check_360(page)`)."""
    height = page.viewport_size["height"] if page.viewport_size else 800
    page.set_viewport_size({"width": 360, "height": height})
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")  # перерисовка
    panels = []
    for selector in ("#messenger-list", "#messenger-messages"):
        node = page.locator(selector)
        if node.count() and node.first.is_visible():
            panels.append(node.first.bounding_box())
    if len(panels) == 2:
        left, right = panels
        overlap = left["x"] < right["x"] + right["width"] and right["x"] < left["x"] + left["width"]
        assert overlap, f"на ширине 360 px у {page.url} список и беседа стоят в две колонки"
    assert helpers.no_horizontal_scroll(page), f"на ширине 360 px у {page.url} есть горизонтальная прокрутка"
    return True