"""T-8140: приёмка сценария 10 — поиск (FR-668, FR-669).

Ровно три пункта приёмки SPEC-008, «Сценарий 10» (по одному тесту на пункт):
1. дано сообщение в чужом чате — сотрудник ищет слово, в выдаче и числе его нет (FR-668, FR-669);
2. дано сообщение в своём чате — группа «Мессенджер» показывает чат, автора, время по Москве и строку с
   найденным словом (FR-668);
3. дано открытая беседа — поиск по ней находит только сообщения этой беседы, доступные участнику, с подсветкой
   и переходом к `#m<id>` (FR-668).

Общее для файла (CONTRACT-008: 9, 10.2, 12.1, 12.3, 12.6, 14.3; TASKS-008 T-8140; образцы — `test_m04_general.py`,
`test_f11_search.py`, серверный `test_messenger_search.py`):
- люди — `helpers_messenger.messenger_cast` один раз на круг браузера (фикстура `cast`): `writer`, `peer`,
  `creator`, `third` (сотрудник вне чата), `admin` (администратор портала);
- сквозной поиск — страница `/search/?q=<слово>` (`[data-search-page]`, раздел 9); группа —
  `section[data-search-group="messenger"]` (12.6), строка — ссылка `/messenger/chats/<id>/#m<id>` (раздел 9),
  число группы — `span[data-search-count-value][data-count]` (как у прежних провайдеров, `test_f11_search.py`);
  пустая выдача — `[data-empty-state="search"]` «Ничего не найдено» (12.1);
- поиск по беседе — поле `[data-messenger-search]` беседы (12.3), GET `q` на `/messenger/chats/<id>/search/`
  (10.2): фрагмент только с сообщениями этой беседы, подсветка `ts_headline`, `time[data-at]` (12.1) и якорь
  `#m<id>` (раздел 9);
- слова поиска — уникальные латинские буквы (`_word`): цифры и русские окончания поиск разобрал бы иначе; данные
  круга общие, поэтому каждое слово встречается ровно в одном сообщении и выдача однозначна;
- «чужое не находится» проверяется только после положительного контроля: то же сообщение сначала находится у
  участника чата (`peer`), затем отсутствует у `third` и `admin` (приём «письма нет» из `test_m09_notify.py`);
- ПДн и секретов нет: ФИО вымышленные (их заводит `messenger_cast`), адреса — `example.test`; пропусков
  (`skip`/`xfail`) в файле нет.
"""
import re
import secrets
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers_messenger, helpers_notify

MOSCOW = ZoneInfo("Europe/Moscow")
MESSENGER = "Мессенджер"
GROUP = 'section[data-search-group="messenger"]'
EMPTY_TEXT = "Ничего не найдено"
COUNT_TIMEOUT = 15_000     # число группы подгружается отдельным запросом (образец test_f11_search)
DASH = " — "               # «<чат>, <ФИО>, <дата по Москве> — <отрывок 100>» (раздел 9)
NO_WORD_TEXT = "Начнём диалог"   # второе предложение первого сообщения `start_dialog` (не должно находиться)
_CASTS: dict = {}


@pytest.fixture
def cast(browser, admin_page, mailpit, new_context):
    """Круг людей сценария 10: `messenger_cast` один раз на круг браузера, дальше — сохранённые сессии."""
    key = browser.e2e_project
    if key not in _CASTS:
        _CASTS[key] = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
    return _CASTS[key]


# --- Помощники файла ----------------------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово из латинских букв: цифры и русские окончания поиск разобрал бы иначе."""
    return "".join(secrets.choice("bcdfghklmnprstvz") for _ in range(10))


def _search_page(context, account, word):
    """Страница результатов `/search/?q=<word>` (раздел 9) с сессией `account`; ждёт корень `[data-search-page]`."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto("/search/?" + urlencode({"q": word}))
    expect(page.locator("[data-search-page]")).to_be_visible()
    return page


def _messenger_group(page):
    """Группа «Мессенджер» страницы результатов (12.6)."""
    return page.locator(GROUP)


def _message_link(page, chat_id, message_id):
    """Строка выдачи — ссылка на сообщение `/messenger/chats/<id>/#m<id>` (раздел 9, 12.6)."""
    return _messenger_group(page).locator(f'a[href="/messenger/chats/{chat_id}/#m{message_id}"]').first


def _row_parts(text: str) -> tuple:
    """Части строки выдачи «<чат>, <автор>, <дата> — <отрывок>», прочитанные по «, » (в ФИО запятых нет)."""
    parts = text.split(", ", 2)
    assert len(parts) == 3, f"строка выдачи не вида «чат, автор, дата — отрывок»: {text!r}"
    return parts[0], parts[1], parts[2]


def _highlight(word: str):
    """Подсветка `ts_headline` вокруг слова: тег `b`/`strong`/`mark` (контракт называет функцию, не тег)."""
    return re.compile(r"(?is)<(b|strong|mark)\b[^>]*>[^<]*" + re.escape(word))


def _moscow_day(at: datetime) -> str:
    """Дата по Москве в виде строки выдачи (раздел 9); время стенда берётся из браузера (`Europe/Moscow`)."""
    return at.strftime("%d.%m.%Y")


# --- 1. Сообщение своего чата находится ---------------------------------------------------------------------------

def test_m10_word_in_own_chat_found_with_chat_author_time_and_snippet(new_context, cast):
    """П. 2 (FR-668): сообщение своего чата находится сквозным поиском; группа «Мессенджер» показывает название
    чата, ФИО автора, дату по Москве и отрывок с найденным словом; строка ведёт на
    `/messenger/chats/<id>/#m<id>`; число группы — 1."""
    word = _word()
    page = helpers_messenger.open_messenger(new_context(), cast.writer)
    chat_id = helpers_messenger.start_dialog(page, cast.peer)
    sent_at = datetime.now(MOSCOW)
    message_id = helpers_messenger.write(page, f"Отчёт {word} по проекту")

    found = _search_page(new_context(), cast.writer, word)
    group = _messenger_group(found)
    expect(group).to_have_count(1)
    expect(group).to_contain_text(MESSENGER)
    link = _message_link(found, chat_id, message_id)
    expect(link).to_be_visible()

    title, author, rest = _row_parts(link.inner_text())
    assert title == cast.peer.full_name, f"название личного чата: {title!r}"
    assert author == cast.writer.full_name, f"автор сообщения: {author!r}"
    date, dash, snippet = rest.partition(DASH)
    assert dash, f"нет разделителя «{DASH}» перед отрывком: {rest!r}"
    days = {_moscow_day(sent_at), _moscow_day(datetime.now(MOSCOW))}
    assert date in days, f"дата по Москве: {date!r}, ожидалась одна из {sorted(days)}"
    assert word in snippet.lower(), f"в отрывке нет слова {word!r}: {snippet!r}"
    expect(group.locator("span[data-search-count-value]")).to_have_attribute(
        "data-count", "1", timeout=COUNT_TIMEOUT)


# --- 2. Сообщение чужого чата не находится и не считается ---------------------------------------------------------

def test_m10_word_in_foreign_chat_absent_from_results_and_count(new_context, cast):
    """П. 1 (FR-668, FR-669): участник чата находит сообщение, а сотрудник вне чата и администратор портала не
    находят его ни в выдаче, ни в числе: группы «Мессенджер» нет, счёта нет, выдача пуста («Ничего не найдено»)."""
    word = _word()
    page = helpers_messenger.open_messenger(new_context(), cast.peer)
    chat_id = helpers_messenger.start_dialog(page, cast.creator)
    message_id = helpers_messenger.write(page, f"Закрытая тема {word}")

    control = _search_page(new_context(), cast.peer, word)
    expect(_message_link(control, chat_id, message_id)).to_be_visible()

    for account in (cast.third, cast.admin):
        hidden = _search_page(new_context(), account, word)
        expect(_messenger_group(hidden)).to_have_count(0)
        expect(hidden.locator("[data-search-count-value]")).to_have_count(0)
        expect(hidden.locator('[data-empty-state="search"]')).to_contain_text(EMPTY_TEXT)
        assert word not in hidden.locator("[data-search-page]").inner_text(), \
            f"{account.email}: слово чужого чата попало в выдачу"


# --- 3. Поиск по открытой беседе ----------------------------------------------------------------------------------

def test_m10_chat_search_returns_only_its_messages_available_to_member(new_context, cast):
    """П. 3 (FR-668): поиск по открытой беседе находит только сообщения этой беседы, доступные участнику; чужое
    сообщение другого чата и сообщение без искомого слова не попадают, найденное подсвечено, у него
    `time[data-at]` и якорь `#m<id>`."""
    word = _word()
    own_page = helpers_messenger.open_messenger(new_context(), cast.writer)
    chat_id = helpers_messenger.start_dialog(own_page, cast.peer)
    message_id = helpers_messenger.write(own_page, f"Слово {word} в этой беседе")

    foreign_page = helpers_messenger.open_messenger(new_context(), cast.peer)
    foreign_chat = helpers_messenger.start_dialog(foreign_page, cast.creator)
    foreign_message = helpers_messenger.write(foreign_page, f"Слово {word} в другой беседе")
    assert foreign_chat != chat_id, "чужой чат совпал с проверяемым"

    chat = helpers_messenger.open_chat(new_context(), cast.writer, chat_id)
    form = chat.locator("[data-messenger-search]").first
    expect(form).to_be_visible()
    box = chat.locator('[data-messenger-search] input[name="q"], input[data-messenger-search][name="q"]').first
    expect(box).to_be_visible()
    box.fill(word)
    with chat.expect_response(lambda response: response.request.method == "GET"
                              and response.url.split("?")[0].endswith(
                                  f"/messenger/chats/{chat_id}/search/")) as info:
        button = form.locator('button[type="submit"]')
        if button.count():
            button.first.click()
        else:
            box.press("Enter")
    fragment = info.value.text()

    assert re.search(rf"#m{message_id}\b", fragment), "во фрагменте нет якоря найденного сообщения"
    assert not re.search(rf"#m{foreign_message}\b", fragment), "во фрагмент попало сообщение другого чата"
    assert "в другой беседе" not in fragment, "во фрагмент попало сообщение другого чата"
    assert NO_WORD_TEXT not in fragment, "во фрагмент попало сообщение без искомого слова"
    assert _highlight(word).search(fragment), "нет подсветки ts_headline вокруг найденного слова"
    assert re.search(r"<time\b[^>]*\bdata-at\b", fragment), "у найденного сообщения нет time[data-at]"