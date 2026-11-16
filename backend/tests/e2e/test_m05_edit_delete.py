"""T-8135: приёмка сценария 5 — правка, удаление и ответ-цитата (FR-653, 654, 656, 657, 661).

Общее для файла (SPEC-008, «Сценарий 5»; PLAN-008, «Беседа и история порциями», «Отправка, правка, удаление, цитата»,
«Живые обновления и рассылка», «Проход в браузере»; CONTRACT-008 разделы 10.2, 11.3, 12.3, 13.3, 14.3; TASKS-008
T-8135; образец замеров — `test_f08_live.py` среза 007):
- люди — `helpers_messenger.messenger_cast` (фикстура `circle`, круг собирается один раз на браузер и дальше берётся
  по сохранённым сессиям `Account.storage_state`: заводить девять учёток с мастером активации на каждый тест — часы
  прохода); нужны двое: `writer` (автор) и `peer` (собеседник личного диалога);
- страницы — `open_messenger`, `start_dialog`, `open_chat`; отправка, правка, удаление и цитата — `write`,
  `edit_message`, `delete_message`, `quote` (14.3), зацепки — только `data-*` и `id` раздела 12;
- живой кадр (пп. 1–2) проверяется у открытой беседы собеседника в своём контексте, без перезагрузки; замер — как в
  `f08`: `time.monotonic()` от возврата ответа на действие автора до видимого результата, ожидание берётся больше
  нормы (`WAIT_MS`), проверка — по замеру (`FRAME_SECONDS`, сценарий 5 пп. 1–2);
- удаление у собеседника: кадр удаления — `hx-swap-oob="delete"` (11.3), то есть узел `#m<id>` исчезает, а серая
  запись «Сообщение удалено» появляется в ответе автора и при следующем открытии беседы; тест принимает и
  исчезновение узла, и серую запись на месте (спека: «запись меняется»), дальше проверяет её после перезагрузки;
- меню сообщения контракт зацепкой не называет (он называет только результат): пункты «Ответить», «Править»,
  «Удалить» ищутся по видимой подписи, сворачиваемое `<details>` раскрывается — тот же приём, что `_menu_action`
  помощников T-8130;
- отказы чужого действия — `helpers_org.direct_post` от имени страницы (сессия и CSRF её, без переходов по
  редиректам), поэтому 403 — отказ по праву (10.1, 10.2), а не по токену;
- предел задания: удаление вместе с файлами (строки `MessageAttachment`, `StoredFile`, диск) проверяется серверными
  тестами T-8109b и сценарием 7 (`test_m07_files.py`); здесь у серой записи утверждается только то, что называет
  12.3, — «текста и файлов нет»;
- секретов и ПДн нет: ФИО вымышленные, адреса ссылок — `example.test`.
"""
import re
import time
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_messenger, helpers_org

FRAME_SECONDS = 2.0            # «не позже 2 с» без перезагрузки (сценарий 5 пп. 1–2, FR-661)
WAIT_MS = 4_000                # ожидание чуть больше нормы: проверка идёт по замеру (образец f08)
DATE_TEXT = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")   # time[data-at], время по Москве (12.1)
DELETED = "Сообщение удалено"
EDITED = "изменено"
MOSCOW = timezone(timedelta(hours=3))
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
    return helpers_org.unique_name(prefix)


def _dialog(context, cast):
    """Личный диалог `writer` ↔ `peer`: страница писателя в беседе и номер чата (`start_dialog` шлёт первое
    сообщение). Повторный вызов на пару открывает ту же переписку (FR-645): тексты тестов уникальны."""
    page = helpers_messenger.open_messenger(context, cast.writer)
    return page, helpers_messenger.start_dialog(page, cast.peer)


def _message(page, message_id):
    """Сообщение `article#m<id>[data-message-id]` (12.3)."""
    return page.locator(f'article[data-message-id="{message_id}"]')


def _aware(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=MOSCOW)


def _reveal(node) -> None:
    """Раскрывает сворачиваемое меню сообщения (`<details>`), если оно закрыто: сценарий 5 п. 3 — «открывает меню»."""
    if node.locator("details").count() and not node.locator("details[open]").count():
        node.locator("summary").first.click()


def _labels(node) -> list:
    """Подписи интерактивных узлов сообщения (кнопки, ссылки, переключатели меню), в том числе скрытые в `<details>`:
    контракт зацепку меню не называет, поэтому «есть ли пункт» решается по видимой подписи."""
    return [text.strip() for text in node.locator("button, a, summary").all_inner_texts()]


def _action(node, label: str) -> None:
    """Пункт меню сообщения по подписи `label`: кнопка или ссылка; сворачиваемое меню раскрывается. Контракт зацепку
    меню не называет — приём тот же, что `_menu_action` помощников T-8130."""
    item = node.get_by_role("button", name=label, exact=True)
    if not item.count():
        item = node.get_by_role("link", name=label, exact=True)
    if not item.count():
        _reveal(node)
        item = node.get_by_role("button", name=label, exact=True)
        if not item.count():
            item = node.get_by_role("link", name=label, exact=True)
    assert item.count(), f"у сообщения нет пункта «{label}»"
    expect(item.first).to_be_visible()
    item.first.click()


def _wait_changed(page, message_id, what: str) -> float:
    """Ждёт изменения записи у собеседника: узел `#m<id>` исчез (кадр удаления, 11.3) или на его месте серая запись.
    Возвращает замер от вызова; по истечении `FRAME_SECONDS` — `AssertionError` (норма сценария 5 п. 2)."""
    started = time.monotonic()
    deadline = started + FRAME_SECONDS
    while True:
        node = _message(page, message_id)
        if node.count() == 0 or node.locator("[data-messenger-deleted]").count():
            return time.monotonic() - started
        if time.monotonic() > deadline:
            raise AssertionError(f"{what}: за {FRAME_SECONDS:.0f} с запись #{message_id} не изменилась")
        page.wait_for_timeout(100)


def _assert_links_and_escaping(node, page, allowed, forbidden, token) -> None:
    """Проверка вывода текста (FR-653): разрешённые адреса — ссылки `target=_blank` с `rel`, запрещённые и разметка —
    экранированный текст, скрипт не исполняется."""
    links = node.locator("a[href]")
    hrefs = links.evaluate_all("els => els.map(el => el.getAttribute('href'))")
    for address in allowed:
        assert hrefs.count(address) == 1, f"адрес {address!r} не стал ссылкой ровно один раз: {hrefs}"
        link = next(item for item in links.all() if item.get_attribute("href") == address)
        assert link.get_attribute("target") == "_blank", f"{address!r}: ссылка без target=_blank"
        assert set((link.get_attribute("rel") or "").split()) == {"noopener", "noreferrer"}, (
            f"{address!r}: rel={link.get_attribute('rel')!r}")
        assert link.inner_text() == address, f"{address!r}: подпись ссылки {link.inner_text()!r}"
    for address in forbidden:
        assert address not in hrefs, f"запрещённый адрес стал ссылкой: {address!r}"
    shown = node.inner_text()
    for address in forbidden:
        assert address in shown, f"адрес {address!r} пропал из текста сообщения: {shown!r}"
    assert f"<b>{token}</b>" in shown, f"разметка не показана текстом: {shown!r}"
    assert node.locator("b", has_text=token).count() == 0, "разметка <b> выполнилась"
    assert node.locator("script", has_text="__m05").count() == 0, "разметка <script> попала в беседу"
    assert not page.evaluate("() => Boolean(window.__m05)"), "скрипт из сообщения выполнился"


# --- Тесты --------------------------------------------------------------------------------------------------------

def test_m05_author_edit_shows_new_text_and_edited_mark_for_author_and_peer_in_two_seconds(circle, new_context):
    """Сценарий 5, п. 1 (FR-656, FR-661): автор правит своё сообщение — в беседе новый текст и пометка «изменено»,
    прежнего текста нет; у открытой беседы собеседника правка видна не позже 2 с без перезагрузки."""
    c = circle.cast
    old, new = _word("Первый текст"), _word("Второй текст")
    author, chat_id = _dialog(new_context(), c)
    message_id = helpers_messenger.write(author, old)
    peer = helpers_messenger.open_chat(new_context(), c.peer, chat_id)
    peer_message = _message(peer, message_id)
    expect(peer_message).to_contain_text(old)
    # контроль: до правки пометки нет ни у автора, ни у собеседника
    expect(_message(author, message_id).locator("[data-messenger-edited]")).to_have_count(0)
    expect(peer_message.locator("[data-messenger-edited]")).to_have_count(0)

    helpers_messenger.edit_message(author, message_id, new)

    own = _message(author, message_id)
    expect(own).to_contain_text(new)
    expect(own).not_to_contain_text(old)
    expect(own.locator("[data-messenger-edited]").first).to_contain_text(EDITED)
    assert old not in author.locator("#messenger-messages").inner_text(), "прежний текст остался в беседе автора"

    started = time.monotonic()          # замер — от возврата ответа на правку (образец f08)
    expect(peer_message).to_contain_text(new, timeout=WAIT_MS)
    expect(peer_message.locator("[data-messenger-edited]").first).to_contain_text(EDITED, timeout=WAIT_MS)
    elapsed = time.monotonic() - started
    assert elapsed <= FRAME_SECONDS, f"правка дошла до собеседника за {elapsed:.2f} с при норме 2 с"
    assert old not in peer.locator("#messenger-messages").inner_text(), "у собеседника остался прежний текст"

    peer.reload()
    peer.wait_for_load_state()
    expect(_message(peer, message_id)).to_contain_text(new)
    expect(_message(peer, message_id).locator("[data-messenger-edited]").first).to_contain_text(EDITED)
    assert old not in peer.locator("#messenger-messages").inner_text(), (
        "после перезагрузки у собеседника остался прежний текст")


def test_m05_author_delete_leaves_grey_record_with_time_and_peer_sees_change_in_two_seconds(circle, new_context):
    """Сценарий 5, п. 2 (FR-657, FR-661): автор удаляет своё сообщение — на месте остаётся «Сообщение удалено» со
    временем, текста и файлов нет; у открытой беседы собеседника запись меняется не позже 2 с, после перезагрузки он
    видит ту же серую запись со временем."""
    c = circle.cast
    text = _word("Текст под удаление")
    author, chat_id = _dialog(new_context(), c)
    message_id = helpers_messenger.write(author, text)
    peer = helpers_messenger.open_chat(new_context(), c.peer, chat_id)
    expect(_message(peer, message_id)).to_contain_text(text)

    helpers_messenger.delete_message(author, message_id)

    grey = _message(author, message_id)
    expect(grey.locator("[data-messenger-deleted]")).to_be_visible()
    expect(grey).to_contain_text(DELETED)
    expect(grey).not_to_contain_text(text)
    expect(grey.locator("[data-messenger-file]")).to_have_count(0)     # 12.3: текста и файлов нет
    stamp = grey.locator("time[data-at]").first
    expect(stamp).to_have_text(DATE_TEXT)
    moment = _aware(stamp.get_attribute("datetime"))
    assert abs((datetime.now(timezone.utc) - moment).total_seconds()) < 600, (
        f"время серой записи {moment} далеко от текущего")
    assert text not in author.locator("#messenger-messages").inner_text(), "текст удалённого остался в беседе"

    elapsed = _wait_changed(peer, message_id, "удаление у собеседника")
    assert elapsed <= FRAME_SECONDS, f"запись у собеседника изменилась за {elapsed:.2f} с при норме 2 с"

    peer.reload()
    peer.wait_for_load_state()
    peer_grey = _message(peer, message_id)
    expect(peer_grey.locator("[data-messenger-deleted]")).to_be_visible()
    expect(peer_grey).to_contain_text(DELETED)
    expect(peer_grey).not_to_contain_text(text)
    expect(peer_grey.locator("[data-messenger-file]")).to_have_count(0)
    expect(peer_grey.locator("time[data-at]").first).to_have_text(DATE_TEXT)


def test_m05_foreign_message_has_no_edit_or_delete_and_direct_requests_refused(circle, new_context):
    """Сценарий 5, п. 3 (FR-656, FR-657): у чужого сообщения меню правки и удаления нет (ответить можно), прямой
    запрос правки и удаления от участника чата — 403 (10.1, 10.2), сообщение цело."""
    c = circle.cast
    text = _word("Чужое сообщение")
    author, chat_id = _dialog(new_context(), c)
    message_id = helpers_messenger.write(author, text)
    reader = helpers_messenger.open_chat(new_context(), c.peer, chat_id)
    node = _message(reader, message_id)
    expect(node).to_contain_text(text)

    _reveal(node)
    labels = _labels(node)
    assert "Ответить" in labels, f"у чужого сообщения нет пункта «Ответить»: {labels}"
    assert "Править" not in labels, f"у чужого сообщения есть пункт «Править»: {labels}"
    assert "Удалить" not in labels, f"у чужого сообщения есть пункт «Удалить»: {labels}"

    edit = helpers_org.direct_post(reader, f"/messenger/messages/{message_id}/edit/", {"text": _word("Подмена")})
    assert edit.status == 403, f"правка чужого сообщения: ожидался 403, получен {edit.status}"
    delete = helpers_org.direct_post(reader, f"/messenger/messages/{message_id}/delete/")
    assert delete.status == 403, f"удаление чужого сообщения: ожидался 403, получен {delete.status}"

    author.reload()
    author.wait_for_load_state()
    own = _message(author, message_id)
    expect(own).to_contain_text(text)
    expect(own.locator("[data-messenger-edited]")).to_have_count(0)
    expect(own.locator("[data-messenger-deleted]")).to_have_count(0)


def test_m05_reply_shows_quote_with_source_author_in_input_and_builds_no_second_level(circle, new_context):
    """Сценарий 5, п. 4 (FR-654): «Ответить» — в поле ввода цитата с автором исходного (крестик убирает её), ответ
    несёт ровно одну цитату; ответ на ответ цитирует только своё исходное и второго уровня не строит."""
    c = circle.cast
    text = _word("Исходное для цитаты")
    author, chat_id = _dialog(new_context(), c)
    peer = helpers_messenger.open_chat(new_context(), c.peer, chat_id)
    source_id = helpers_messenger.write(peer, text)
    author.reload()                      # беседа автора уже открыта; цитату строим по загруженной истории
    author.wait_for_load_state()
    source = _message(author, source_id)
    expect(source).to_contain_text(text)

    _action(source, "Ответить")
    form = author.locator("#messenger-form")
    quote = form.locator("[data-quote]")
    expect(quote).to_be_visible()
    expect(quote).to_contain_text(c.peer.full_name)                       # цитата с автором исходного
    expect(form.locator('input[name="quote"]')).to_have_value(str(source_id))
    expect(quote.locator('button[data-action="quote-remove"]')).to_be_visible()
    quote.locator('button[data-action="quote-remove"]').click()
    expect(quote).to_be_hidden()
    hidden = form.locator('input[name="quote"]')
    assert hidden.count() == 0 or hidden.input_value() == "", (
        f"после крестика в скрытом поле цитаты осталось {hidden.input_value()!r}")

    reply_id = helpers_messenger.quote(author, source_id)
    reply = _message(author, reply_id)
    expect(reply).to_contain_text(helpers_messenger.QUOTE_TEXT)
    expect(reply.locator(f'[data-quote-id="{source_id}"]')).to_have_count(1)
    expect(reply.locator(f'[data-quote-id="{source_id}"]')).to_contain_text(text)
    expect(reply.locator("[data-quote-id] [data-quote-id]")).to_have_count(0)

    second_id = helpers_messenger.quote(author, reply_id)
    second = _message(author, second_id)
    expect(second.locator(f'[data-quote-id="{reply_id}"]')).to_have_count(1)
    expect(second.locator("[data-quote-id] [data-quote-id]")).to_have_count(0)
    cited = second.locator(f'[data-quote-id="{reply_id}"]')
    expect(cited).to_contain_text(helpers_messenger.QUOTE_TEXT)
    assert text not in cited.inner_text(), "в цитате оказался текст более раннего сообщения — построен второй уровень"


def test_m05_http_https_mailto_become_links_and_other_markup_stays_escaped_text(circle, new_context):
    """Сценарий 5, п. 5 (FR-653): адреса `http`, `https`, `mailto` — ссылки в новой вкладке с `rel`; прочие схемы,
    голые домены и разметка — экранированный текст, скрипт не исполняется (и после перезагрузки)."""
    c = circle.cast
    token = helpers_org.unique_name("m05")      # только латиница: адреса раздела FR-653
    allowed = [f"https://example.test/{token}?a=1&b=2", f"http://example.test/{token}",
               f"mailto:box.{token}@example.test"]
    forbidden = ["ftp://example.test/file", "javascript:alert(1)", "data:text/html,привет", "www.example.test"]
    text = ("Адреса: " + " ".join(allowed) + ". Не ссылки: " + " ".join(forbidden)
            + f". Разметка: <b>{token}</b> и <script>window.__m05 = 1</script>")
    author, _ = _dialog(new_context(), c)
    message_id = helpers_messenger.write(author, text)

    _assert_links_and_escaping(_message(author, message_id), author, allowed, forbidden, token)

    author.reload()
    author.wait_for_load_state()
    _assert_links_and_escaping(_message(author, message_id), author, allowed, forbidden, token)