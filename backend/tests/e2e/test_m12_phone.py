"""T-8142: приёмка сценария 12 — телефон 360 px (FR-673, NFR-702).

Ровно три пункта приёмки SPEC-008, «Сценарий 12» (по одному тесту на пункт):
1. ширина окна 360 px — при открытии мессенджера видна одна колонка без горизонтальной прокрутки (FR-673,
   NFR-702); то же для страницы беседы, которая по плану до 900 px показывает только беседу;
2. открыт список — нажатие на чат открывает беседу, а кнопка «Назад» ведёт обратно к списку (FR-673);
3. широкое окно — видны две колонки: список и беседа (FR-673).

Общее для файла (CONTRACT-008.md, разделы 10.2, 12, 13.3, 14.3; план, «360 px и две колонки», «Проход в
браузере»):
- люди — `helpers_messenger.messenger_cast` один раз на круг браузера (фикстура `circle`): девять учёток через
  интерфейс на каждый тест — часы прохода; круг браузеров (chromium, firefox, Edge, Яндекс Браузер) даёт
  `tests/e2e/conftest.py`, здесь своих параметров и пропусков нет;
- личный диалог пары `writer` ↔ `peer` — `helpers_messenger.start_dialog`; в него пишется сообщение с длинной
  ссылкой без пробелов (`LONG_TEXT`) — план требует переноса длинных ссылок и имён (`overflow-wrap: anywhere`),
  поэтому проверка прокрутки идёт на непустых списке, превью и истории, а не на пустых состояниях;
- ширина 360 px — `helpers_messenger.check_360` (`helpers.no_horizontal_scroll`): ставит окно 360 px, проверяет
  отсутствие горизонтальной прокрутки и что видимые панели списка и беседы не стоят рядом; «одна колонка»
  дополнительно проверяется по видимым панелям (`_panels`): на `/messenger/` виден только список, на
  `/messenger/chats/<id>/` — только беседа;
- зацепки — только CONTRACT-008, раздел 12: `[data-messenger-page="list"|"chat"]`, `#messenger-list`
  `[data-chat-id]`, `#messenger-messages`, `[data-messenger-back]`; подпись кнопки «Назад» — текст интерфейса
  13.3;
- переключение ширины — до первой загрузки страницы (`new_context(viewport=…)`), чтобы вёрстка сразу была
  узкой или широкой; окно не меняется посреди проверки;
- состояния «пусто», «ошибка» и живые кадры здесь не проверяются — это другие сценарии (T-8131…T-8141);
  секретов и ПДн нет: ФИО вымышленные. Файл правит только T-8142.
"""
import re
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_messenger

PHONE = {"width": 360, "height": 800}       # ширина сценария 12 (FR-673)
WIDE = {"width": 1440, "height": 900}       # «широкое окно»: две колонки от 900 px (план)
LIST_URL = re.compile(r"/messenger/(?:\?.*)?$")
BACK_TEXT = "Назад"                          # текст интерфейса 13.3
LONG_TEXT = "Длинная ссылка без пробелов: https://example.org/" + "a" * 160  # перенос длинных ссылок (план)
PANELS = (("#messenger-list", "список"), ("#messenger-messages", "беседа"))

_CIRCLES: dict = {}


class Circle(NamedTuple):
    """Круг сценария: учётки `helpers_messenger.MessengerCast`, собранные один раз на браузер."""
    cast: object


@pytest.fixture
def circle(browser, admin_page, mailpit, new_context) -> Circle:
    """Круг сценария 12: собирается при первом обращении в круге браузера (образец — `test_m01_personal`)."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        _CIRCLES[key] = Circle(helpers_messenger.messenger_cast(admin_page, mailpit, new_context))
    return _CIRCLES[key]


# --- Общие приёмы -------------------------------------------------------------------------------------------------

def _panels(page) -> list:
    """Видимые панели страницы по порядку `PANELS`: «список» (`#messenger-list`) и «беседа»
    (`#messenger-messages`). Одна колонка — ровно одна панель (FR-673)."""
    visible = []
    for selector, name in PANELS:
        node = page.locator(selector)
        if node.count() and node.first.is_visible():
            visible.append(name)
    return visible


def _dialog(new_context, account, peer) -> int:
    """Новый (или существующий) личный диалог `account` ↔ `peer` с длинным сообщением: номер чата.

    Сначала открывается мессенджер на широком окне (`open_messenger` ждёт узел соединения беседы), затем
    `start_dialog` заводит пару и возвращает номер; длинное сообщение даёт непустые превью и историю."""
    page = helpers_messenger.open_messenger(new_context(), account)
    chat_id = helpers_messenger.start_dialog(page, peer)
    helpers_messenger.write(page, LONG_TEXT)
    return chat_id


def _row(page, chat_id):
    """Строка чата в списке: `#messenger-list [data-chat-id="<id>"]` (12.2)."""
    row = page.locator(f'#messenger-list [data-chat-id="{chat_id}"]')
    expect(row).to_be_visible()
    return row


# --- Тесты (по пунктам приёмки сценария 12) -----------------------------------------------------------------------

def test_m12_360px_list_and_chat_are_single_column_without_horizontal_scroll(circle, new_context):
    """П. 1 (FR-673, NFR-702): на ширине 360 px при открытии мессенджера видна одна колонка — только список чатов,
    без горизонтальной прокрутки; страница беседы на той же ширине — тоже одна колонка (беседа), без прокрутки."""
    c = circle.cast
    chat_id = _dialog(new_context, c.writer, c.peer)

    listing = helpers_messenger.open_messenger(new_context(viewport=PHONE), c.writer, live=False)
    expect(listing.locator('[data-messenger-page="list"]')).to_be_visible()
    _row(listing, chat_id)
    assert _panels(listing) == ["список"], f"на 360 px у списка видны панели {_panels(listing)}"
    assert helpers_messenger.check_360(listing), "список на 360 px"

    chat = helpers_messenger.open_chat(new_context(viewport=PHONE), c.writer, chat_id)
    expect(chat.locator('[data-messenger-page="chat"]')).to_be_visible()
    expect(chat.locator("#messenger-messages")).to_be_visible()
    expect(chat.locator("[data-messenger-back]")).to_be_visible()
    assert _panels(chat) == ["беседа"], f"на 360 px у беседы видны панели {_panels(chat)}"
    assert helpers_messenger.check_360(chat), "беседа на 360 px"


def test_m12_360px_chat_opens_from_list_and_back_returns_to_list(circle, new_context):
    """П. 2 (FR-673): на 360 px открыт список — нажатие на чат открывает беседу (`/messenger/chats/<id>/`,
    история на месте), а кнопка «Назад» `[data-messenger-back]` возвращает к списку с тем же чатом."""
    c = circle.cast
    chat_id = _dialog(new_context, c.writer, c.peer)

    page = helpers_messenger.open_messenger(new_context(viewport=PHONE), c.writer, live=False)
    assert helpers_messenger.check_360(page), "список перед переходом на 360 px"
    _row(page, chat_id).click()

    page.wait_for_url(re.compile(rf"/messenger/chats/{chat_id}/$"))
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="chat"]')).to_be_visible()
    expect(page.locator("#messenger-messages")).to_be_visible()
    expect(page.locator("#messenger-messages")).to_contain_text(LONG_TEXT)
    back = page.locator("[data-messenger-back]")
    expect(back).to_be_visible()
    expect(back).to_contain_text(BACK_TEXT)
    assert helpers_messenger.check_360(page), "беседа после перехода на 360 px"

    back.click()
    page.wait_for_url(LIST_URL)
    page.wait_for_load_state()
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    _row(page, chat_id)
    assert _panels(page) == ["список"], f"после «Назад» на 360 px видны панели {_panels(page)}"
    assert helpers_messenger.check_360(page), "список после «Назад» на 360 px"


def test_m12_wide_window_shows_list_and_chat_in_two_columns(circle, new_context):
    """П. 3 (FR-673): на широком окне при открытии мессенджера видны две колонки — список слева и беседа справа,
    рядом по горизонтали (не друг под другом)."""
    c = circle.cast
    chat_id = _dialog(new_context, c.writer, c.peer)

    page = helpers_messenger.open_messenger(new_context(viewport=WIDE), c.writer, live=True)
    expect(page.locator('[data-messenger-page="list"]')).to_be_visible()
    _row(page, chat_id)
    listing = page.locator("#messenger-list")
    messages = page.locator("#messenger-messages")
    expect(listing).to_be_visible()
    expect(messages).to_be_visible()

    left, right = listing.bounding_box(), messages.bounding_box()
    assert left and right, f"у колонок нет размеров: {left}, {right}"
    assert left["width"] > 0 and right["width"] > 0, f"колонки пусты: {left}, {right}"
    assert left["x"] + left["width"] <= right["x"] + 1, f"беседа не справа от списка: {left}, {right}"
    top = max(left["y"], right["y"])
    bottom = min(left["y"] + left["height"], right["y"] + right["height"])
    assert bottom > top, f"колонки стоят друг под другом, а не рядом: {left}, {right}"