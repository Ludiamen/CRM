"""T-8131: сценарий 1 — личный диалог (FR-644, FR-645, FR-652, FR-658, FR-659, FR-660, FR-661).

Общее для файла (CONTRACT-008.md разделы 10–14; план, «Проход в браузере»; шаблон `e2e/template.md`):
- приёмка ровно шести пунктов сценария 1 спеки: один диалог на пару из карточки и из мессенджера; новое
  сообщение у открытой беседы не позже 2 с без перезагрузки; открытие беседы обнуляет счётчик, автор видит
  «Прочитали N из M»; порядок трёх чатов по последнему сообщению с превью и временем; история 60 сообщений
  порциями без потери места до первого; пустое, из пробелов и 4 001 знак отклонены с причиной;
- люди и узлы — `helpers_messenger.messenger_cast` один раз на круг браузера (фикстура `circle`: девять
  учёток и три узла через интерфейс заводить на каждый тест — часы прохода); круги браузеров (chromium,
  firefox, Edge, Яндекс Браузер) даёт `tests/e2e/conftest.py`, здесь своих параметров и пропусков нет;
- диалог пары — один на круг: пары разных тестов пересекаются (`peer`, `third`), поэтому точный счёт истории
  (60 сообщений) ведёт только своя пара `writer` ↔ `outsider`; остальным тестам накопленная переписка не мешает;
- ожидания — `expect(...)` и помощники `helpers_messenger` (`write`, `try_write`, `wait_unread`,
  `wait_read_line`); время — `time.monotonic()` от ответа на отправку до видимого результата, ожидание чуть
  больше нормы (4 с), проверка — по замеру (2 с, FR-661; образец `test_f08_live.py`); сна нет;
- отказы форм — пары `(поле, data-code)` из ответа (`try_write`) и `[data-error="<поле>"][data-code]` на
  странице (10.1, 13.1); тексты — подстрокой из раздела 13;
- сессия на карточку сотрудника переносится `helpers_notify.adopt_session` (страница `/staff/<id>/` — не
  адрес мессенджера); дальше вход и страницы дают `open_messenger` и `open_chat`;
- «без потери места» проверяется положением самого старого показанного сообщения на экране до и после
  подгрузки: прокручиваемый предок `#messenger-messages` ставится в начало, после `afterbegin` сообщение
  должно остаться на том же месте (допуск 2 px) — так проверяется обещанное планом
  `scrollTop += новый scrollHeight − старый`.
"""
import re
import time
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_messenger, helpers_notify

FRAME_SECONDS = 2.0        # FR-661: новое сообщение у открытой беседы
WAIT_MS = 4_000            # ожидание чуть больше нормы: проверка — по замеру
PAGE_TIMEOUT = 20_000      # готовность страницы беседы и порции истории
MORE = "Показать более ранние"  # текст интерфейса (13.3), отдельной зацепки контракт не даёт
EMPTY_TEXT = "Напишите текст"
LIMIT_4000 = "Предел: 4000 знаков"
TIME_TEXT = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")
FIFTY = 50                 # порция истории (FR-658)
_CIRCLES: dict = {}

_SCROLL = """() => {
  const box = document.querySelector('#messenger-messages');
  if (!box) throw new Error('нет #messenger-messages');
  let node = box;
  while (node && node !== document.body && node.scrollHeight <= node.clientHeight + 1) node = node.parentElement;
  const scroller = node && node !== document.body ? node : (document.scrollingElement || document.documentElement);
  window.__m01_scroller = scroller;
  return {top: scroller.scrollTop, height: scroller.scrollHeight};
}"""


class Circle(NamedTuple):
    """Круг сценария: учётки `helpers_messenger.MessengerCast`, собранные один раз на браузер."""
    cast: object


@pytest.fixture
def circle(browser, admin_page, mailpit, new_context) -> Circle:
    """Круг сценария 1: собирается при первом обращении в круге браузера; учётки — на сохранённых сессиях."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = Circle(helpers_messenger.messenger_cast(admin_page, mailpit, new_context))
    return _CIRCLES[key]


# --- Общие приёмы -------------------------------------------------------------------------------------------------

def _since(started: float, limit: float, what: str) -> None:
    elapsed = time.monotonic() - started
    assert elapsed <= limit, f"{what}: {elapsed:.2f} с при норме {limit:.0f} с"


def _message_ids(page) -> list:
    """Номера сообщений `#messenger-messages article[data-message-id]` сверху вниз (старые → новые)."""
    return [int(value) for value in page.locator(
        "#messenger-messages article[data-message-id]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-message-id'))")]


def _chat_ids(page) -> list:
    """Номера чатов `#messenger-list [data-chat-id]` сверху вниз."""
    return [int(value) for value in page.locator(
        "#messenger-list [data-chat-id]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-chat-id'))")]


def _more_control(page):
    """Кнопка или ссылка «Показать более ранние» (13.3): контракт зацепку не называет — ищем по видимой подписи."""
    for role in ("button", "link"):
        control = page.get_by_role(role, name=re.compile(re.escape(MORE)))
        if control.count():
            return control.first
    raise AssertionError(f"у истории нет кнопки «{MORE}»")


def _has_more(page) -> bool:
    return any(page.get_by_role(role, name=re.compile(re.escape(MORE))).count()
               for role in ("button", "link"))


def _scroll(page, top=None) -> dict:
    """Прокручиваемый предок `#messenger-messages` (или окно): при `top` — прокрутка в это положение.
    Возвращает `{"top": …, "height": …}` этого элемента."""
    page.evaluate(_SCROLL)
    if top is not None:
        page.evaluate("value => { window.__m01_scroller.scrollTop = value; }", top)
    return page.evaluate("() => ({top: window.__m01_scroller.scrollTop, height: window.__m01_scroller.scrollHeight})")


def _settle(page) -> None:
    """Два кадра перерисовки: разметка и восстановление прокрутки после свопа уже применены."""
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _card_page(context, account: helpers.Account, target: helpers.Account | None = None):
    """Страница карточки сотрудника `/staff/<id>/` с сессией `account` (`helpers_notify.adopt_session`);
    `target` — чья карточка открыта (по умолчанию своя)."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto(f"/staff/{(target or account).id}/")
    page.wait_for_load_state()
    return page


def _dialog(new_context, account, peer) -> int:
    """Новый (или существующий) личный диалог `account` ↔ `peer` из мессенджера: номер чата."""
    return helpers_messenger.start_dialog(helpers_messenger.open_messenger(new_context(), account), peer)


# --- Тесты (по пунктам приёмки сценария 1) -----------------------------------------------------------------------

def test_m01_dialog_is_one_for_pair_started_from_card_and_from_messenger(circle, new_context):
    """Сценарий 1, п. 1 (FR-645): первый сотрудник шлёт сообщение второму кнопкой «Написать» в карточке — открывается
    личный диалог; вторая отправка того же сотрудника из мессенджера попадает в него же, а не в новый чат."""
    c = circle.cast
    card = _card_page(new_context(), c.writer, c.peer)
    write_button = card.locator("[data-messenger-card-write]")
    expect(write_button).to_be_visible()  # кнопка «Написать» в карточке собеседника
    from_card = helpers_messenger.start_dialog(card, c.peer)
    expect(card.locator("[data-chat-kind]")).to_have_attribute("data-chat-kind", "personal")
    first = helpers_messenger.write(card, "Сообщение из карточки")

    messenger = helpers_messenger.open_messenger(new_context(), c.writer)
    from_messenger = helpers_messenger.start_dialog(messenger, c.peer)
    assert from_messenger == from_card, f"из мессенджера открылся новый чат {from_messenger} вместо {from_card}"
    greeting = _message_ids(messenger)[-1]  # «Здравствуйте!» второго start_dialog — та же история
    second = helpers_messenger.write(messenger, "Сообщение из мессенджера")

    expect(messenger.locator(f'article[data-message-id="{first}"]')).to_be_visible()
    expect(messenger.locator(f'article[data-message-id="{second}"]')).to_be_visible()
    expect(messenger.locator("[data-chat-kind]")).to_have_attribute("data-chat-kind", "personal")
    assert _message_ids(messenger)[-3:] == [first, greeting, second], "сообщения пары не в одной истории"


def test_m01_new_message_appears_in_open_peer_chat_within_2s_without_reload(circle, new_context):
    """Сценарий 1, п. 2 (FR-661, FR-660): у собеседника открыта беседа — новое сообщение встаёт в неё не позже чем
    через 2 с, страница не перезагружается, сообщение помечено как чужое."""
    c = circle.cast
    chat = _dialog(new_context, c.writer, c.third)
    peer = helpers_messenger.open_chat(new_context(), c.third, chat)
    writer = helpers_messenger.open_chat(new_context(), c.writer, chat)
    peer.evaluate("() => { window.__m01_alive = true; }")

    text = "Живое сообщение диалога"
    message_id = helpers_messenger.write(writer, text)
    started = time.monotonic()
    expect(peer.locator(f'article[data-message-id="{message_id}"]')).to_be_visible(timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "новое сообщение в открытой беседе собеседника")

    node = peer.locator(f'article[data-message-id="{message_id}"]')
    expect(node).to_contain_text(text)
    expect(node).to_have_attribute("data-own", "0")
    assert peer.evaluate("() => window.__m01_alive === true"), "страница собеседника перезагружена"


def test_m01_opening_chat_clears_unread_and_author_sees_read_line(circle, new_context):
    """Сценарий 1, п. 3 (FR-659, FR-660): у собеседника в списке есть непрочитанное — он открывает беседу, счётчик
    у чата обнуляется, а автор у последнего своего сообщения видит «Прочитали 1 из 1»."""
    c = circle.cast
    chat = _dialog(new_context, c.writer, c.department_member)
    writer = helpers_messenger.open_chat(new_context(), c.writer, chat)
    helpers_messenger.write(writer, "Непрочитанное сообщение")
    # Второй, более свежий чат получателя: список на широком экране сам открывает первый чат, и целью он быть не должен
    newer = _dialog(new_context, c.creator, c.department_member)
    assert newer != chat

    peer_list = helpers_messenger.open_messenger(new_context(), c.department_member)
    rows = _chat_ids(peer_list)
    assert rows.index(newer) < rows.index(chat), (
        f"свежий чат {newer} не выше цели {chat}: список сам откроет цель и прочитает её")
    before = helpers_messenger.unread(peer_list, chat)
    assert before >= 1, f"у получателя нет непрочитанных в чате {chat}: {before}"

    helpers_messenger.open_chat(new_context(), c.department_member, chat)
    helpers_messenger.wait_read_line(writer, "Прочитали 1 из 1")

    peer_list.goto("/messenger/")
    peer_list.wait_for_load_state()
    expect(peer_list.locator('[data-messenger-page="list"]')).to_be_visible()
    helpers_messenger.wait_unread(peer_list, chat, 0, timeout=PAGE_TIMEOUT)


def test_m01_list_orders_three_chats_by_last_message_with_preview_and_time(circle, new_context):
    """Сценарий 1, п. 4 (FR-644): у трёх чатов разное время последнего сообщения — в списке они стоят по последнему
    сообщению (свежий выше), у каждого видны превью этого сообщения и время; новое сообщение поднимает чат выше."""
    c = circle.cast
    page = helpers_messenger.open_messenger(new_context(), c.writer)
    chats = {
        "peer": helpers_messenger.start_dialog(page, c.peer),
        "third": helpers_messenger.start_dialog(page, c.third),
        "creator": helpers_messenger.start_dialog(page, c.creator),
    }
    assert len(set(chats.values())) == 3, f"три пары дали не три чата: {chats}"
    texts = {"peer": "Порядок первый", "third": "Порядок второй", "creator": "Порядок третий"}
    for name in ("peer", "third", "creator"):  # последнее сообщение — у «creator»
        helpers_messenger.write(
            helpers_messenger.open_chat(new_context(), c.writer, chats[name]), texts[name])

    page.goto("/messenger/")
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    order = _chat_ids(page)
    for name in chats:
        assert chats[name] in order, f"чата {name} ({chats[name]}) нет в списке"
    positions = {name: order.index(chats[name]) for name in chats}
    assert positions["creator"] < positions["third"] < positions["peer"], (
        f"порядок не по последнему сообщению: {positions}")
    for name, chat_id in chats.items():
        row = page.locator(f'#messenger-list [data-chat-id="{chat_id}"]')
        expect(row.locator(f"#chat-{chat_id}-preview")).to_contain_text(texts[name])
        stamp = row.locator("time[data-at]")
        expect(stamp).to_be_visible()
        assert TIME_TEXT.fullmatch(stamp.inner_text().strip()), f"время чата {chat_id}: {stamp.inner_text()!r}"

    fresh = "Порядок новее всех"
    helpers_messenger.write(helpers_messenger.open_chat(new_context(), c.writer, chats["peer"]), fresh)
    page.goto("/messenger/")
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    order = _chat_ids(page)
    positions = {name: order.index(chats[name]) for name in chats}
    assert positions["peer"] < positions["creator"] < positions["third"], (
        f"новое сообщение не подняло чат наверх: {positions}")
    expect(page.locator(f'#chat-{chats["peer"]}-preview')).to_contain_text(fresh)


def test_m01_history_of_60_messages_loads_in_portions_to_first_without_losing_place(circle, new_context):
    """Сценарий 1, п. 5 (FR-658): в беседе 60 сообщений — открывается последними 50, «Показать более ранние»
    догружает оставшиеся 10 без перезагрузки и без потери места, история доходит до первого сообщения."""
    c = circle.cast
    writer = helpers_messenger.open_messenger(new_context(), c.writer)
    chat = helpers_messenger.start_dialog(writer, c.outsider)
    for number in range(FIFTY + 10 - 1):  # первое сообщение отправил `start_dialog`; всего 60
        helpers_messenger.write(writer, f"История {number + 2:02d}")

    peer = helpers_messenger.open_chat(new_context(), c.outsider, chat)
    messages = peer.locator("#messenger-messages article[data-message-id]")
    expect(messages).to_have_count(FIFTY, timeout=PAGE_TIMEOUT)
    first_page = _message_ids(peer)
    assert len(first_page) == FIFTY and len(set(first_page)) == FIFTY

    control = _more_control(peer)
    expect(control).to_be_visible()
    peer.evaluate("() => { window.__m01_alive = true; }")
    before_scroll = _scroll(peer, 0)
    anchor_id = first_page[0]                # самое старое показанное сообщение — якорь места
    anchor = peer.locator(f'article[data-message-id="{anchor_id}"]')
    expect(anchor).to_be_visible()
    anchor_y = anchor.bounding_box()["y"]

    with peer.expect_response(lambda r: "/messenger/chats/" in r.url and "/messages/" in r.url,
                              timeout=PAGE_TIMEOUT):
        control.evaluate("el => el.click()")
    expect(messages).to_have_count(FIFTY + 10, timeout=PAGE_TIMEOUT)
    _settle(peer)

    after_scroll = _scroll(peer)
    moved = anchor.bounding_box()["y"]
    assert abs(moved - anchor_y) <= 2, (
        f"после подгрузки старых сообщение {anchor_id} съехало с {anchor_y:.1f} px на {moved:.1f} px")
    assert after_scroll["height"] > before_scroll["height"], "история не выросла после подгрузки"
    assert peer.evaluate("() => window.__m01_alive === true"), "страница перезагружена при подгрузке истории"

    all_ids = _message_ids(peer)
    assert len(all_ids) == FIFTY + 10, f"в истории сообщений: {len(all_ids)}"
    assert len(set(all_ids)) == FIFTY + 10, "история повторила сообщение"
    assert all_ids == sorted(all_ids), "история идёт не по порядку"
    assert first_page == all_ids[-FIFTY:], "первая порция — не последние 50 сообщений"
    assert all_ids[0] < first_page[0], "старые сообщения не добавлены выше показанных"
    assert not _has_more(peer), f"кнопка «{MORE}» осталась у первого сообщения"


def test_m01_empty_spaces_and_4001_chars_are_refused_with_reason_and_not_sent(circle, new_context):
    """Сценарий 1, п. 6 (FR-652): пустое поле, одни пробелы и 4 001 знак не отправляются; причина — у поля `text`
    («Напишите текст», «Предел: 4000 знаков»), в истории новых сообщений нет."""
    c = circle.cast
    chat = _dialog(new_context, c.writer, c.department_newcomer)
    page = helpers_messenger.open_chat(new_context(), c.writer, chat)
    messages = page.locator("#messenger-messages article[data-message-id]")
    before = messages.count()

    assert helpers_messenger.try_write(page, "") == [("text", "empty_text")]
    expect(page.locator('[data-error="text"][data-code="empty_text"]')).to_contain_text(EMPTY_TEXT)
    assert helpers_messenger.try_write(page, "   \n\t ") == [("text", "empty_text")]
    expect(page.locator('[data-error="text"][data-code="empty_text"]')).to_contain_text(EMPTY_TEXT)

    assert helpers_messenger.try_write(page, "я" * 4001) == [("text", "too_long")]
    reason = page.locator('[data-error="text"][data-code="too_long"]')
    expect(reason).to_contain_text(LIMIT_4000)

    assert messages.count() == before, "отклонённый текст попал в историю"