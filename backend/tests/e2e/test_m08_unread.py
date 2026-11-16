"""T-8138: приёмка сценария 8 — непрочитанное и счётчики (FR-659, 660, 661, 666, NFR-701).

Общее для файла (SPEC-008, «Сценарий 8»; PLAN-008, «Прочтение и счётчики», «Живые обновления и рассылка»,
«Проход в браузере»; CONTRACT-008 разделы 11.1–11.3, 12.2–12.4, 13.3, 14.3; образец замеров — `test_f08_live.py`
среза 007):
- приёмка ровно трёх пунктов сценария 8: новое сообщение поднимает число своего чата и общее число у пункта
  «Мессенджер» без перезагрузки; открытие беседы обнуляет число этого чата и уменьшает общее ровно на столько же;
  у последнего своего сообщения автор видит «Прочитали 1 из 1», у остальных своих такой строки нет. Плюс
  FR-661/FR-666/NFR-701 из строки T-8138: сообщение в открытую беседу приходит не позже 2 с и не остаётся
  непрочитанным;
- люди — `helpers_messenger.messenger_cast` (фикстура `circle`, круг собирается один раз на браузер и дальше
  берётся по сохранённым сессиям `Account.storage_state`: заводить девять учёток с мастером активации на каждый
  тест — часы прохода); страницы — `open_messenger`, `open_chat`, диалог — `start_dialog`, отправка — `write`;
- две вкладки: у получателя открыт список (`/messenger/`, числа приходят живым кадром `notify.u.{id}`, 11.1),
  у автора — беседа (своё соединение `messenger.u.{id}`, 11.1); страницы в разных контекстах, `data-ws` и
  `#notify-bell[data-ws="open"]` ждутся до действия (`helpers_notify.wait_ws_open`) — иначе кадр можно пропустить;
- кадр прочтения адресован автору сообщения (11.2 «рассылает автору кадр»; FR-659), поэтому п. 2 и FR-666 не ждут
  живого кадра в другой вкладке самого читателя: они проверяют ответ на отметку (`#menu-badge-messenger` во
  вкладке беседы, 10.2) и состояние списка после его открытия — так требует спека («когда сообщения показаны,
  тогда счётчик обнуляется»);
- на широком экране страница списка сама открывает первый чат и читает его (FR-673; CONTRACT-008 10.2). Поэтому
  самый свежий чат получателя создаётся и читается заранее (`_decoy`) и стоит первым: числа чатов, которые
  проверяются, во время замера не сдвигаются;
- числа — дельтами от значения до действия (`base + 1`, `base_total − base_chat`): переписка круга общая, а
  абсолютные значения зависят от соседних тестов; ожидания — `expect(...)` и помощники `wait_unread`,
  `wait_badge`, `wait_message`; сна нет;
- замер — как в `f08` среза 007: `time.monotonic()` от возврата ответа на отправку до видимых чисел и сообщения,
  ожидание берётся больше нормы (`WAIT_MS`), проверка идёт по замеру (`FRAME_SECONDS` = 2 с, FR-661, FR-660,
  NFR-701);
- «число чата не осталось непрочитанным» утверждается после положительного сигнала того же кадра (превью
  обновилось) и подтверждается состоянием списка после его открытия (счётчик 0); строка «Прочитали 1 из 1» у
  последнего своего проверяется на серверном рендере беседы (п. 3, 12.3; живой кадр строки — сценарий 1);
- пропусков и своих параметров браузера в файле нет; круги браузеров (chromium, firefox, Edge, Яндекс Браузер)
  даёт `tests/e2e/conftest.py`; секретов и ПДн нет — ФИО вымышленные, адресов в текстах нет.
"""
import time
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_messenger, helpers_notify, helpers_org

FRAME_SECONDS = 2.0        # «не позже 2 с»: новое сообщение и числа (FR-661, FR-660, NFR-701)
WAIT_MS = 4_000            # ожидание чуть больше нормы: проверка идёт по замеру (образец f08)
PAGE_TIMEOUT = 20_000      # готовность страницы списка, её чата и соединений (12.4)
READ_LINE = "Прочитали 1 из 1"   # «Прочитали N из M» личного диалога (13.3): M — один собеседник
_CIRCLES: dict = {}


class Circle(NamedTuple):
    cast: object      # `helpers_messenger.MessengerCast`


@pytest.fixture
def circle(browser, admin_page, mailpit, new_context) -> Circle:
    """Круг сценария: учётки и узлы `messenger_cast` один раз на круг браузера, сессии — сохранённые."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = Circle(helpers_messenger.messenger_cast(admin_page, mailpit, new_context))
    return _CIRCLES[key]


# --- Общие приёмы -------------------------------------------------------------------------------------------------

def _word(prefix: str) -> str:
    """Уникальный текст сообщения на круг: данные стенда между тестами не сбрасываются."""
    return helpers_org.unique_name(prefix)


def _since(started: float, limit: float, what: str) -> None:
    """Замер от `started` до видимого результата: больше `limit` — `AssertionError` (норма сценария 8)."""
    elapsed = time.monotonic() - started
    assert elapsed <= limit, f"{what}: {elapsed:.2f} с при норме {limit:.0f} с"


def _chat_ids(page) -> list:
    """Номера чатов `#messenger-list [data-chat-id]` сверху вниз (12.2)."""
    return [int(value) for value in page.locator("#messenger-list [data-chat-id]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-chat-id'))")]


def _dialog(context, author, other):
    """Личный диалог `author` ↔ `other`: страница `author` в беседе и номер чата. `start_dialog` шлёт первое
    сообщение, поэтому у `other` в этом чате одно непрочитанное."""
    page = helpers_messenger.open_messenger(context, author)
    return page, helpers_messenger.start_dialog(page, other)


def _decoy(new_context, sender, receiver) -> int:
    """Самый свежий чат получателя `receiver` (с `sender`), уже прочитанный им: на широком экране страница списка
    сама открывает первый чат и читает его (FR-673), поэтому свежий чат создаётся и читается заранее — числа,
    которые проверяет тест, во время замера не сдвигаются (FR-660)."""
    chat = _dialog(new_context(), sender, receiver)[1]
    helpers_messenger.open_chat(new_context(), receiver, chat)      # отметка прочтения свежего чата
    return chat


def _list_page(new_context, account, decoy):
    """Страница списка `account`: `[data-messenger-page="list"]`, открытое соединение колокольчика и прочитанный
    свежий чат `decoy` первым. Числа строк приходят кадром `notify.u.{id}` (11.1, 11.3), поэтому `/ws/notify/`
    ждётся до действия (`helpers_notify.wait_ws_open`). Возвращает страницу с меткой «не перезагружена»."""
    page = helpers_messenger.open_messenger(new_context(), account)
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    helpers_notify.wait_ws_open(page)
    helpers_messenger.wait_unread(page, decoy, 0, timeout=PAGE_TIMEOUT)
    order = _chat_ids(page)
    assert order and order[0] == decoy, (
        f"свежий чат {decoy} не первый в списке {order}: страница сама откроет и прочитает проверяемый чат")
    page.evaluate("() => { window.__m08_alive = true; }")
    return page


def _assert_read_line_only_under_last(page, message_ids) -> None:
    """FR-659, сценарий 8 п. 3: ровно один `#messenger-read` — у последнего своего сообщения, текст «Прочитали
    1 из 1»; у остальных своих сообщений строки нет (12.3)."""
    expect(page.locator("#messenger-read")).to_have_count(1)
    expect(page.locator(f'article[data-message-id="{message_ids[-1]}"] #messenger-read')).to_contain_text(READ_LINE)
    for message_id in message_ids[:-1]:
        expect(page.locator(f'article[data-message-id="{message_id}"] #messenger-read')).to_have_count(0)


# --- Тесты (по пунктам приёмки сценария 8) -----------------------------------------------------------------------

def test_m08_new_message_raises_chat_count_preview_and_menu_total_live(circle, new_context):
    """Сценарий 8, п. 1 (FR-660, NFR-701): у получателя два чата с непрочитанными, открыт список; новое сообщение в
    один из них — без перезагрузки число этого чата и общее число у пункта «Мессенджер» растут на 1, превью
    показывает текст; числа и превью — не позже 2 с; второй чат своё число сохраняет."""
    c = circle.cast
    writer_chat = _dialog(new_context(), c.writer, c.peer)[1]
    other_chat = _dialog(new_context(), c.creator, c.peer)[1]
    decoy = _decoy(new_context, c.third, c.peer)
    assert len({writer_chat, other_chat, decoy}) == 3, "три автора дали не три чата"

    page = _list_page(new_context, c.peer, decoy)
    base_chat = helpers_messenger.unread(page, writer_chat)
    base_other = helpers_messenger.unread(page, other_chat)
    base_total = helpers_messenger.badge(page)
    assert base_chat >= 1 and base_other >= 1, (
        f"у получателя не два чата с непрочитанными: {base_chat} и {base_other}")
    assert base_total >= base_chat + base_other, (
        f"общее число {base_total} меньше суммы чисел чатов {base_chat} + {base_other}")

    sender = helpers_messenger.open_chat(new_context(), c.writer, writer_chat)
    text = _word("Непрочитанное сообщение")
    helpers_messenger.write(sender, text)
    started = time.monotonic()
    helpers_messenger.wait_unread(page, writer_chat, base_chat + 1, timeout=WAIT_MS)
    expect(page.locator(f"#chat-{writer_chat}-preview")).to_contain_text(text, timeout=WAIT_MS)
    helpers_messenger.wait_badge(page, base_total + 1, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "число чата, превью и общее число после нового сообщения")

    assert helpers_messenger.unread(page, other_chat) == base_other, (
        "новое сообщение в другом чате изменило число второго чата")
    assert page.evaluate("() => window.__m08_alive === true"), "страница получателя перезагружена"


def test_m08_opening_chat_zeroes_its_count_and_lowers_menu_total_by_same_amount(circle, new_context):
    """Сценарий 8, п. 2 (FR-660): у сотрудника в одном окне список с непрочитанными, в другом он открывает беседу —
    сообщения показаны, общее число у пункта «Мессенджер» уменьшается ровно на число этого чата (ответ на отметку
    прочтения, 10.2), а в списке число этого чата становится 0."""
    c = circle.cast
    _, chat = _dialog(new_context(), c.writer, c.department_member)
    sender = helpers_messenger.open_chat(new_context(), c.writer, chat)
    texts = [_word(f"Непрочитанное {number}") for number in range(2)]
    for text in texts:
        helpers_messenger.write(sender, text)
    decoy = _decoy(new_context, c.creator, c.department_member)

    page = _list_page(new_context, c.department_member, decoy)
    base_chat = helpers_messenger.unread(page, chat)
    base_total = helpers_messenger.badge(page)
    assert base_chat >= 3, f"у чата {chat} ожидалось не меньше трёх непрочитанных, число {base_chat}"
    assert base_total >= base_chat, f"общее число {base_total} меньше числа чата {base_chat}"

    chat_tab = helpers_messenger.open_chat(new_context(), c.department_member, chat)
    expect(chat_tab.locator("#messenger-messages")).to_contain_text(texts[-1])   # «сообщения показаны»
    helpers_messenger.wait_badge(chat_tab, base_total - base_chat, timeout=WAIT_MS)

    page.reload()                       # список после прочтения: число чата 0, общее меньше на столько же
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    helpers_messenger.wait_unread(page, chat, 0, timeout=PAGE_TIMEOUT)
    helpers_messenger.wait_badge(page, base_total - base_chat, timeout=PAGE_TIMEOUT)
    assert helpers_messenger.unread(page, chat) == 0, "число прочитанного чата не стало нулём"
    assert helpers_messenger.badge(page) == base_total - base_chat, (
        f"общее число {helpers_messenger.badge(page)} вместо {base_total - base_chat}")


def test_m08_message_in_open_chat_appears_within_2s_and_is_not_unread(circle, new_context):
    """FR-661, FR-666, NFR-701 (строка T-8138): у получателя беседа открыта, в другом окне — список; новое сообщение
    появляется в беседе не позже 2 с без перезагрузки, превью в списке обновляется живым кадром, а пришедшее в
    открытую беседу прочитано: открытый заново список показывает у чата 0, а общее число — прежнее."""
    c = circle.cast
    chat = _dialog(new_context(), c.writer, c.outsider)[1]
    reader = helpers_messenger.open_chat(new_context(), c.outsider, chat)
    reader.evaluate("() => { window.__m08_alive = true; }")
    decoy = _decoy(new_context, c.creator, c.outsider)
    page = _list_page(new_context, c.outsider, decoy)
    assert helpers_messenger.unread(page, chat) == 0, "открытая беседа уже была с непрочитанным"
    base_total = helpers_messenger.badge(page)

    sender = helpers_messenger.open_chat(new_context(), c.writer, chat)
    text = _word("Сообщение в открытую беседу")
    message_id = helpers_messenger.write(sender, text)
    started = time.monotonic()
    helpers_messenger.wait_message(reader, message_id, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "сообщение в открытой беседе получателя")
    expect(reader.locator(f'article[data-message-id="{message_id}"]')).to_contain_text(text)

    expect(page.locator(f"#chat-{chat}-preview")).to_contain_text(text, timeout=WAIT_MS)   # кадр чисел дошёл

    assert reader.evaluate("() => window.__m08_alive === true"), "страница получателя перезагружена"
    assert page.evaluate("() => window.__m08_alive === true"), "страница списка перезагружена"

    # сообщение открытой беседы не осталось непрочитанным: счётчик на сервере 0 (свежий чат `_decoy` держит
    # первое место, поэтому обновлённый список не открывает проверяемый чат сам и не читает его за тест)
    _decoy(new_context, c.creator, c.outsider)
    page.reload()
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    assert _chat_ids(page)[0] == decoy, "обновлённый список сам открыл проверяемый чат"
    helpers_messenger.wait_unread(page, chat, 0, timeout=PAGE_TIMEOUT)
    helpers_messenger.wait_badge(page, base_total, timeout=PAGE_TIMEOUT)
    assert helpers_messenger.unread(page, chat) == 0, "сообщение открытой беседы осталось непрочитанным"
    assert helpers_messenger.badge(page) == base_total, (
        f"общее число {helpers_messenger.badge(page)} вместо прежнего {base_total}")


def test_m08_read_line_only_under_last_own_message_after_peer_reads(circle, new_context):
    """Сценарий 8, п. 3 (FR-659): автор отправил несколько сообщений, собеседник их прочитал — когда автор открывает
    беседу, у последнего своего сообщения он видит «Прочитали 1 из 1», у остальных своих такой строки нет."""
    c = circle.cast
    page, chat = _dialog(new_context(), c.writer, c.department_newcomer)
    texts = [_word(f"Своё сообщение {number}") for number in range(1, 4)]
    own = [int(page.locator("#messenger-messages article[data-message-id]").last.get_attribute("data-message-id"))]
    own += [helpers_messenger.write(page, text) for text in texts]
    assert len(set(own)) == 4 and own == sorted(own), f"свои сообщения: {own}"
    expect(page.locator("#messenger-read", has_text=READ_LINE)).to_have_count(0)   # непрочитано — строки нет

    reader = helpers_messenger.open_chat(new_context(), c.department_newcomer, chat)   # собеседник читает
    expect(reader.locator("#messenger-messages")).to_contain_text(texts[-1])

    opened = helpers_messenger.open_chat(new_context(), c.writer, chat)   # «автор открывает беседу»
    expect(opened.locator("#messenger-messages")).to_contain_text(texts[-1])
    _assert_read_line_only_under_last(opened, own)