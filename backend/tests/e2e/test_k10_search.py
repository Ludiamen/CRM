"""T-5149: сценарий 10 — сквозной поиск: строка в шапке, всплывающая выдача, страница результатов, права, номер
заявки, словоформы, пределы запроса, сотрудники и подразделения (FR-439, FR-440, FR-442, FR-443, FR-444, FR-446,
FR-447, NFR-406).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md, разделы 9, 10.6, 11.9, 12.1, 17):
- каждый тест заводит свои данные (слова поиска — только из латинских букв, `helpers_kb.unique_word`: цифры внутри
  слова поиск мог бы принять за номер заявки), общих настроек не меняет; единственное исключение — тест невидимой
  заявки временно ставит очередь по умолчанию на свою и возвращает прежнюю в `finally`;
- заявки заводятся письмом в ящик стенда (письмо собирается стандартной библиотекой, `tests.support*` не
  импортируется): несколько писем — один `poll_now()`;
- строка поиска в шапке — `[data-search-bar] input[name="q"]`: у списка заявок и «Сотрудников» есть своё поле `q`;
- «закрыто» у всплывающей выдачи — `li[data-search-row]` скрыт или убран (контракт не говорит, очищает ли `search.js`
  окно или прячет), поэтому проверяется `to_be_hidden` у первой строки;
- единственный выход за интерфейс — один вызов `helpers.stand_shell` в последнем тесте (перевод 22 приглашённых
  записей в состояние «активен»: 22 настоящих активации заняли бы минуты); он назван в отчёте.
"""
import re
import secrets
import statistics
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, make_msgid
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_kb, helpers_org, helpers_sd
from tests.e2e.helpers_kb import unique_word

HINT_SHORT = "Введите не меньше 2 знаков"      # 12.1 / раздел 17, п. 25
HINT_LONG = "Запрос не длиннее 200 знаков"      # 12.1
ALL_RESULTS = "Все результаты"                  # 12.1
NOTHING_FOUND = "Ничего не найдено"             # 12.1
GROUP_ORDER = ["tickets", "articles", "staff", "units"]   # 9.3
GROUP_TITLES = {"tickets": "Заявки", "articles": "Статьи", "staff": "Сотрудники", "units": "Подразделения"}


# --- Свои помощники файла -----------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def _mail_bytes(subject: str, text: str = "Текст заявки.") -> bytes:
    """Письмо заявителя корпоративного домена в ящик заявок (стандартная библиотека; заголовки как у обычного письма)."""
    msg = EmailMessage(policy=SMTP)
    msg["From"] = helpers_sd.requester_email()
    msg["To"] = helpers_sd.MAILBOX
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(domain="client.test")
    msg.set_content(text)
    return msg.as_bytes(policy=SMTP)


def _send_tickets(subjects: list) -> None:
    """Кладёт письма с этими темами в ящик и разбирает их одним опросом (заявки появляются в очереди по умолчанию)."""
    for subject in subjects:
        helpers_sd.append_mail(_mail_bytes(subject))
    helpers_sd.poll_now()


def _ticket(admin_page, extra: str = "") -> tuple:
    """Одна заявка с уникальным словом темы: `(номер, слово)`; номер — поиском списка администратора."""
    word = unique_word("t")
    helpers_sd.deliver(_mail_bytes(f"Заявка {extra} {word}".replace("  ", " ")))
    return helpers_sd.ticket_number_by_subject(admin_page, word), word


def _ticket_from_ten(admin_page, extra: str = "") -> tuple:
    """Заявка с номером не меньше 10 (запрос из одной цифры — подсказка, а не номер): на стенде номера уже ушли
    вперёд, но на пустом стенде заводятся лишние заявки, пока номер не дорастёт."""
    for _ in range(12):
        number, word = _ticket(admin_page, extra)
        if number >= 10:
            return number, word
    raise AssertionError("номер заявки не дорос до 10 за 12 заявок")


def _join_queue(admin_page, queue_id, account) -> None:
    """Сотрудник — участник очереди (узла `org`): у отдела режим «параллельно», у команды выбора режима нет."""
    admin_page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if admin_page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(admin_page, queue_id, [account.id], q=account.full_name.split()[0], mode=mode)
    assert "уже участник" not in note, note


def _rubric(admin_page) -> str:
    name = helpers_org.unique_name("Рубрика")
    helpers_kb.create_rubric(admin_page, name)
    return name


def _publish(page, rubric: str, title: str, text: str = "Текст статьи.") -> str:
    """Опубликованная статья: черновик через форму и кнопка «Опубликовать» на странице статьи; возвращает номер."""
    article_id = helpers_kb.create_draft(page, title=title, text=text, rubric=rubric)
    helpers_kb.publish_from_article_page(page, article_id)
    return article_id


def _world(admin_page, employee, *, tickets: int = 0, articles: int = 0, units: int = 0) -> SimpleNamespace:
    """Слово поиска `word`; сотрудник `viewer` («Сотрудник ИТ», право «Просмотр сотрудников и структуры») с фамилией
    из этого слова, участник очереди по умолчанию; `tickets` заявок, `articles` опубликованных статей и `units`
    подразделений со словом в теме, заголовке и названии."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    word = unique_word("k")
    viewer = employee(full_name=f"{word.capitalize()} Тест Тестович")
    _join_queue(admin_page, queue_id, viewer)
    if tickets:
        _send_tickets([f"Заявка {word} вариант{i}" for i in range(tickets)])
    rubric = ""
    if articles:
        rubric = _rubric(admin_page)
        for i in range(articles):
            _publish(admin_page, rubric, f"Статья {word} вариант{i}")
    for i in range(units):
        helpers_org.create_unit(admin_page, f"{word} Отдел{i:02d}")
    return SimpleNamespace(word=word, viewer=viewer, rubric=rubric, queue_id=queue_id)


def _field(page):
    return page.locator('[data-search-bar] input[name="q"]')


def _popup(page):
    return page.locator("[data-search-popup]")


def _popup_rows(page):
    return _popup(page).locator("li[data-search-row]")


def _type(page, text: str) -> None:
    """Вводит запрос в строку поиска шапки по знаку (короткие паузы между знаками)."""
    field = _field(page)
    field.fill("")
    field.press_sequentially(text, delay=30)


def _open_popup(page, text: str, path: str = "/") -> None:
    """Страница `path`, запрос в строке поиска и ожидание первой строки всплывающей выдачи."""
    page.goto(path)
    expect(_field(page)).to_be_visible()
    _type(page, text)
    expect(_popup_rows(page).first).to_be_visible()


def _groups(root) -> list:
    """Ключи групп выдачи внутри `root` по порядку разметки."""
    return root.locator("section[data-search-group]").evaluate_all("els => els.map(e => e.dataset.searchGroup)")


def _hrefs(scope) -> list:
    """Адреса строк выдачи внутри `scope` (первая ссылка каждой строки)."""
    return scope.locator("li[data-search-row]").evaluate_all(
        "els => els.map(li => li.querySelector('a[href]').getAttribute('href'))")


def _results(page, q: str) -> None:
    """Страница результатов `/search/?q=…`; ждёт её корень (он есть на любой запрос, 10.6)."""
    page.goto("/search/?" + urlencode({"q": q}))
    expect(page.locator("[data-search-page]")).to_be_visible()


def _section(page, key: str):
    return page.locator(f'[data-search-page] section[data-search-group="{key}"]')


def _group_hrefs(page, q: str, key: str) -> list:
    """Адреса строк группы `key` на странице результатов по `q` (первая порция)."""
    _results(page, q)
    return _hrefs(_section(page, key))


def _all_hrefs(page, q: str) -> list:
    _results(page, q)
    return _hrefs(page.locator("[data-search-page]"))


def _get_text(page, path: str) -> tuple:
    """Прямой GET от имени страницы: `(статус, тело)`."""
    response = helpers_org.direct_get(page, path)
    return response.status, response.text()


def _make_role_without_staff_view(admin_page) -> str:
    """Роль только с правом журнала (как в test_o04): без «Просмотра сотрудников и структуры» и без прав базы знаний."""
    role_name = f"БезПоиска-{secrets.token_hex(3)}"
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(role_name)
    form.locator('input[name=permissions][value="audit.view"]').check()
    form.locator("button[type=submit]").click()
    assert helpers_org.role_id(admin_page, role_name)
    return role_name


def _card(page, user_id):
    return page.locator(f'[data-card][data-user-id="{user_id}"]')


def _dismiss(admin_page, user_id) -> None:
    """Увольняет из карточки: диалог, подтверждение, отметка «уволен» у ФИО."""
    admin_page.goto(f"/staff/{user_id}/")
    _card(admin_page, user_id).locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(_card(admin_page, user_id).locator("[data-dismissed-badge]")).to_be_visible()


def _block(admin_page, account) -> None:
    """Блокирует учётную запись из вкладки «Безопасность»; ждёт её в списке заблокированных."""
    admin_page.goto(f"/staff/{account.id}/")
    helpers.open_security_tab(admin_page)
    form = admin_page.locator('form[action$="/block/"]')
    form.locator("[name=reason]").fill("проверка поиска")
    helpers.submit(form)
    admin_page.goto("/staff/?state=blocked")
    expect(helpers.staff_row(admin_page, account.email)).to_have_count(1)


# --- Тесты --------------------------------------------------------------------------------------------------

def test_k10_header_has_search_field_on_any_page(admin_page, employee, new_context):
    """Сценарий 10, п. 1: на любой странице вошедшего (редактор, читатель без прав базы знаний, администратор) в
    верхней панели есть строка поиска с адресом окна выдачи, вне колокольчика; у анонима её нет (FR-439)."""
    editor = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    plan = (
        (editor.page, ["/", "/kb/", "/me/", "/staff/", "/structure/", "/search/?q=zz"]),
        (reader.page, ["/", "/kb/", "/me/"]),
        (admin_page, ["/", "/tickets/", "/audit/"]),
    )
    for page, paths in plan:
        for path in paths:
            page.goto(path)
            bar = page.locator("#top-bar [data-search-bar]")
            expect(bar).to_have_count(1)
            field = bar.locator('input[type=search][name="q"]')
            expect(field).to_be_visible()
            expect(field).to_have_attribute("maxlength", "200")
            expect(field).to_have_attribute("aria-label", "Поиск")          # раздел 17, п. 67 (FR-439)
            expect(field).to_have_attribute("placeholder", "Поиск")
            expect(field).to_have_attribute("hx-get", "/search/popup/")
            expect(bar.locator("[data-search-popup]")).to_have_count(1)
            expect(page.locator("#notify-bell [data-search-bar]")).to_have_count(0)
            expect(page.locator("#top-bar input[name=q]")).to_have_count(1)
    anonymous = new_context().new_page()
    anonymous.goto("/login/")
    expect(anonymous.locator("[data-search-bar]")).to_have_count(0)


def test_k10_one_char_query_gives_no_popup_and_enter_opens_results_with_min_two_chars_hint(admin_page, employee):
    """Сценарий 10, п. 2: после «vpn»-подобного запроса окно открыто; один знак «5» убирает выдачу и не даёт подсказки
    в окне; Enter ведёт на `/search/?q=5` с подсказкой «Введите не меньше 2 знаков»; сервер отвечает так же и без
    браузера (FR-440, FR-442, FR-443)."""
    word = unique_word("k")
    _publish(admin_page, _rubric(admin_page), f"Статья {word}")
    page = helpers_kb.make_editor(employee).page
    _open_popup(page, word)                      # контроль: окно открывается на настоящем запросе
    field = _field(page)
    try:
        with page.expect_response(lambda r: "/search/popup/" in r.url and "q=5" in r.url, timeout=2_500):
            _type(page, "5")
    except PlaywrightTimeout:
        pass                                      # запрос мог не уходить совсем (допустимо): проверяем итог
    expect(_popup_rows(page).first).to_be_hidden()
    expect(_popup(page).locator("section[data-search-group]")).to_have_count(0)
    expect(_popup(page).locator("[data-search-hint]")).to_have_count(0)
    _type(page, "а б")                            # одни отброшенные слова — тоже без окна и подсказки в нём
    expect(_popup_rows(page).first).to_be_hidden()
    expect(_popup(page).locator("section[data-search-group]")).to_have_count(0)
    expect(_popup(page).locator("[data-search-hint]")).to_have_count(0)
    _type(page, "5")
    field.press("Enter")
    page.wait_for_url(re.compile(r"/search/\?(?:.*&)?q=5(?:&|$)"))
    expect(page.locator('[data-search-page] [data-search-hint="short"]')).to_contain_text(HINT_SHORT)
    expect(page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
    # сервер проверяет порог сам, независимо от браузера
    status, body = _get_text(page, "/search/?q=5")
    assert status == 200 and HINT_SHORT in body and "data-search-group" not in body
    status, body = _get_text(page, "/search/popup/?q=5")
    assert status == 200 and "data-search-group" not in body and "data-search-hint" not in body
    status, body = _get_text(page, "/search/count/?q=5&group=articles")
    assert status == 200 and not body.strip()


def test_k10_popup_request_goes_between_200_and_400ms_after_last_input_with_four_groups_max_five_rows_empty_group_hidden_and_all_results_link(
        admin_page, employee):
    """Сценарий 10, п. 3 и 5: запрос «слово» уходит через 300 мс (200–400) после последнего знака; под строкой четыре
    группы по порядку, в заявках, статьях и подразделениях по 5 строк при шести совпадениях, без чисел; группа без
    совпадений не показана; внизу «Все результаты» ведёт на страницу результатов (FR-440, FR-442)."""
    world = _world(admin_page, employee, tickets=6, articles=6, units=6)
    word, page = world.word, world.viewer.page
    # п. 3: пауза ввода — медиана трёх замеров от последнего знака до запроса окна
    samples = []
    for _ in range(3):
        page.goto("/")
        expect(_field(page)).to_be_visible()
        samples.append(helpers_kb.search_pause_ms(page, word))
    pause = statistics.median(samples)
    assert 200 <= pause <= 400, f"пауза ввода {pause:.0f} мс вне 300 ± 100: замеры {samples}"
    expect(_popup_rows(page).first).to_be_visible()
    popup = _popup(page)
    assert _groups(popup) == GROUP_ORDER
    for key in GROUP_ORDER:
        section = popup.locator(f'section[data-search-group="{key}"]')
        expect(section).to_contain_text(GROUP_TITLES[key])
        rows = section.locator("li[data-search-row]")
        if key == "staff":
            assert 1 <= rows.count() <= 5
        else:
            assert rows.count() == 5, f"{key}: в окне {rows.count()} строк при шести совпадениях"
    expect(popup.locator("[data-search-count], [data-search-count-value]")).to_have_count(0)
    # группа без совпадений не показывается: слово есть только в одной статье
    only = unique_word("o")
    _publish(admin_page, world.rubric, f"Единственная {only}")
    page.goto("/")
    _type(page, only)
    expect(_popup_rows(page).first).to_be_visible()
    assert _groups(_popup(page)) == ["articles"]
    expect(_popup_rows(page)).to_have_count(1)
    # «Все результаты» — внизу окна и ведёт на страницу результатов с теми же группами
    page.goto("/")
    _type(page, word)
    expect(_popup_rows(page).first).to_be_visible()
    link = _popup(page).locator('a[data-action="search-all"]')
    expect(link).to_have_text(re.compile(ALL_RESULTS))
    expect(link).to_have_attribute("href", re.compile(rf"^/search/\?q={word}$"))
    link.click()
    page.wait_for_url(re.compile(rf"/search/\?(?:.*&)?q={word}(?:&|$)"))
    expect(page.locator("[data-search-page]")).to_be_visible()
    expect(_section(page, "tickets")).to_have_count(1)
    assert _groups(page.locator("[data-search-page]")) == GROUP_ORDER


def test_k10_arrows_enter_and_esc_move_open_row_or_results_page_and_close_popup(admin_page, employee):
    """Сценарий 10, п. 4: стрелки вниз и вверх переставляют выбранную строку (`data-selected`), Esc закрывает окно,
    Enter без выбора ведёт на страницу результатов, Enter на выбранной строке открывает её адрес (FR-440)."""
    world = _world(admin_page, employee, tickets=3)
    word, page = world.word, world.viewer.page
    # стрелки и Esc
    _open_popup(page, word)
    rows = _popup_rows(page)
    selected = _popup(page).locator('li[data-search-row][data-selected="true"]')
    field = _field(page)
    field.press("ArrowDown")
    expect(selected).to_have_count(1)
    expect(rows.nth(0)).to_have_attribute("data-selected", "true")
    field.press("ArrowDown")
    expect(rows.nth(1)).to_have_attribute("data-selected", "true")
    expect(selected).to_have_count(1)
    field.press("ArrowUp")
    expect(rows.nth(0)).to_have_attribute("data-selected", "true")
    expect(selected).to_have_count(1)
    field.press("Escape")
    expect(rows.first).to_be_hidden()
    # Enter без выбранной строки — страница результатов
    _open_popup(page, word)
    _field(page).press("Enter")
    page.wait_for_url(re.compile(rf"/search/\?(?:.*&)?q={word}(?:&|$)"))
    expect(page.locator("[data-search-page]")).to_be_visible()
    # Enter на выбранной строке — адрес строки
    _open_popup(page, word)
    _field(page).press("ArrowDown")
    _field(page).press("ArrowDown")
    target = _popup_rows(page).nth(1).locator("a[href]").first.get_attribute("href")
    expect(_popup_rows(page).nth(1)).to_have_attribute("data-selected", "true")
    _field(page).press("Enter")
    page.wait_for_url(lambda url: urlsplit(url).path == target)


def test_k10_esc_in_search_field_closes_popup_without_closing_open_ticket_card(admin_page, employee):
    """Сценарий 10, п. 4 (решение контракта 11.9): Esc в строке поиска закрывает окно выдачи, а слайдер открытой
    карточки заявки остаётся на месте (FR-440)."""
    world = _world(admin_page, employee, tickets=1)
    word, page = world.word, world.viewer.page
    number = helpers_sd.ticket_number_by_subject(admin_page, word)
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/tickets/?" + urlencode({"preset": "all", "q": word}))
    link = page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="number"] a')
    link.click()
    card = page.locator("#slider-root .slider-panel [data-ticket-card]")
    expect(card).to_have_attribute("data-number", str(number))
    expect(card).to_have_attribute("data-layout", "slider")
    _type(page, word)
    expect(_popup_rows(page).first).to_be_visible()
    _field(page).press("Escape")
    expect(_popup_rows(page).first).to_be_hidden()
    expect(card).to_be_visible()
    expect(page.locator("#slider-root [data-slider-close]")).to_be_visible()
    assert urlsplit(page.url).path == f"/tickets/{number}/"


def test_k10_results_page_shows_groups_with_counts_20_rows_and_show_more_adds_next_20(admin_page, employee):
    """Сценарий 10, п. 5: страница `/search/?q=…` (из «Все результаты» и по Enter) показывает те же группы с числом
    найденного; в группе из 21 заявки — 20 строк и «Показать ещё», добавляющая остальное; у групп без избытка
    кнопки нет (FR-442; раздел 17, п. 49)."""
    world = _world(admin_page, employee, tickets=21, articles=1, units=1)
    word, page = world.word, world.viewer.page
    # путь из окна: Enter в строке
    page.goto("/")
    _type(page, word)
    expect(_popup_rows(page).first).to_be_visible()
    _field(page).press("Enter")
    page.wait_for_url(re.compile(rf"/search/\?(?:.*&)?q={word}(?:&|$)"))
    expect(page.locator("[data-search-page]")).to_be_visible()
    assert _groups(page.locator("[data-search-page]")) == GROUP_ORDER
    expected = {"tickets": "21", "articles": "1", "staff": "1", "units": "1"}
    for key, number in expected.items():
        section = _section(page, key)
        expect(section).to_contain_text(GROUP_TITLES[key])
        value = section.locator("span[data-search-count-value]")
        expect(value).to_be_visible()
        expect(value).to_have_attribute("data-count", number)
        expect(value).to_have_attribute("data-capped", "false")
        expect(value).to_have_text(number)
    tickets = _section(page, "tickets")
    expect(tickets.locator("li[data-search-row]")).to_have_count(20)
    for key in ("articles", "staff", "units"):
        expect(_section(page, key).locator('button[data-action="more"]')).to_have_count(0)
    more = tickets.locator('button[data-action="more"]')
    expect(more).to_have_count(1)
    expect(more).to_have_attribute("data-next-offset", "20")
    expect(more).to_contain_text("Показать ещё")
    first_twenty = _hrefs(tickets)
    more.click()
    expect(tickets.locator("li[data-search-row]")).to_have_count(21)
    after = _hrefs(tickets)
    assert after[:20] == first_twenty and len(set(after)) == 21, "«Показать ещё» повторила или потеряла строки"
    expect(tickets.locator('button[data-action="more"]')).to_have_count(0)
    # путь из окна: «Все результаты»
    page.goto("/")
    _type(page, word)
    expect(_popup_rows(page).first).to_be_visible()
    _popup(page).locator('a[data-action="search-all"]').click()
    page.wait_for_url(re.compile(rf"/search/\?(?:.*&)?q={word}(?:&|$)"))
    expect(_section(page, "tickets").locator("li[data-search-row]")).to_have_count(20)
    # граница (раздел 17, п. 49): ровно 20 заявок — 20 строк и кнопки «Показать ещё» нет
    word20 = unique_word("k")
    _send_tickets([f"Заявка {word20} вариант{i}" for i in range(20)])
    _results(page, word20)
    exact = _section(page, "tickets")
    expect(exact).to_have_count(1)
    value = exact.locator("span[data-search-count-value]")
    expect(value).to_have_attribute("data-count", "20")
    expect(value).to_have_attribute("data-capped", "false")
    expect(exact.locator("li[data-search-row]")).to_have_count(20)
    expect(exact.locator('button[data-action="more"]')).to_have_count(0)


def test_k10_results_page_without_matches_says_nothing_found(admin_page, employee):
    """Сценарий 10, п. 6: запрос без совпадений ни в одной группе — «Ничего не найдено», групп и подсказок нет
    (FR-442)."""
    page = helpers_kb.make_editor(employee).page
    _results(page, unique_word("zz"))
    empty = page.locator('[data-search-page] [data-empty-state="search"]')
    expect(empty).to_have_count(1)
    expect(empty).to_contain_text(NOTHING_FOUND)
    expect(page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
    expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)


def test_k10_ticket_number_query_with_or_without_hash_puts_visible_ticket_first_in_tickets_group(admin_page, employee):
    """Сценарий 10, п. 7: видимая сотруднику заявка №N стоит первой в группе «Заявки» и по «#N», и по «N», хотя
    более новая заявка содержит число в теме; строка заявки одна (FR-443)."""
    world = _world(admin_page, employee)
    page = world.viewer.page
    number, _ = _ticket_from_ten(admin_page)
    other_word = unique_word("d")
    helpers_sd.deliver(_mail_bytes(f"Дубль {number} {other_word}"))
    other = helpers_sd.ticket_number_by_subject(admin_page, other_word)
    assert other > number
    target = f"/tickets/{number}/"
    for query in (f"#{number}", str(number)):
        hrefs = _group_hrefs(page, query, "tickets")
        assert hrefs, f"запрос {query}: группы «Заявки» нет"
        assert hrefs[0] == target, f"запрос {query}: первой стоит {hrefs[0]}, а не {target}"
        assert hrefs.count(target) == 1, f"запрос {query}: заявка показана {hrefs.count(target)} раз"
        if f"/tickets/{other}/" in hrefs:
            assert hrefs.index(target) < hrefs.index(f"/tickets/{other}/")
        expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)


def test_k10_invisible_ticket_is_absent_by_subject_or_number_without_any_hint(admin_page, employee):
    """Сценарий 10, п. 8: заявка чужой очереди не находится ни по теме, ни по номеру, и страница не отличается от
    страницы по несуществующему слову; видимая заявка с общим словом находится; администратор невидимую находит
    (FR-444)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    shared, hidden_word, visible_word = unique_word("s"), unique_word("h"), unique_word("v")
    viewer = employee(full_name=f"{unique_word('v').capitalize()} Тест Тестович")
    _join_queue(admin_page, queue_id, viewer)
    # чужая очередь: на время доставки письма очередью по умолчанию становится не та, где участник
    other_queue = helpers_org.create_unit(admin_page, helpers_org.unique_name("Чужая очередь"))
    helpers_sd.mark_queue(admin_page, other_queue)
    helpers_sd.set_default_queue(admin_page, other_queue)
    try:
        helpers_sd.deliver(_mail_bytes(f"Закрытая {shared} {hidden_word}"))
    finally:
        helpers_sd.set_default_queue(admin_page, queue_id)
    helpers_sd.deliver(_mail_bytes(f"Видимая {shared} {visible_word}"))
    hidden = helpers_sd.ticket_number_by_subject(admin_page, hidden_word)
    visible = helpers_sd.ticket_number_by_subject(admin_page, visible_word)
    page = viewer.page
    # контроль: администратор находит обе заявки
    admin_hrefs = helpers_kb.search_hrefs(admin_page, hidden_word)
    assert f"/tickets/{hidden}/" in admin_hrefs
    # участник: по общему слову видит только свою
    hrefs = _group_hrefs(page, shared, "tickets")
    assert f"/tickets/{visible}/" in hrefs and f"/tickets/{hidden}/" not in hrefs
    # по теме скрытой заявки и по её однозначному номеру — ничего, подсказки нет; «#N» от 10 — ещё и слово «N»
    # (CONTRACT-005 9.1: «#42» → number=42, words=["42"]), его проверяет ветка ниже, как номер без «#»
    queries = [hidden_word] + ([f"#{hidden}"] if hidden < 10 else [])
    nothing = unique_word("zz")
    _results(page, nothing)
    reference = _norm(page.locator('[data-search-page] [data-empty-state="search"]').inner_text())
    reference = _norm(reference.replace(nothing, ""))
    for query in queries:
        _results(page, query)
        assert f"/tickets/{hidden}/" not in _hrefs(page.locator("[data-search-page]"))
        expect(page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
        expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
        empty = page.locator('[data-search-page] [data-empty-state="search"]')
        expect(empty).to_have_count(1)
        expect(empty).to_contain_text(NOTHING_FOUND)
        text = _norm(_norm(empty.inner_text()).replace(query, ""))
        assert text == reference, f"запрос {query}: страница отличается от пустой выдачи"
    if hidden >= 10:
        # номер (с «#» и без) — ещё и слово поиска: чужие совпадения по началу (почта, телефон сотрудника) допустимы,
        # заявки и подсказки быть не должно
        for query in (str(hidden), f"#{hidden}"):
            _results(page, query)
            assert f"/tickets/{hidden}/" not in _hrefs(page.locator("[data-search-page]")), query
            expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
    status, body = _get_text(page, "/search/popup/?" + urlencode({"q": hidden_word}))
    assert status == 200 and f"/tickets/{hidden}/" not in body and "data-search-group" not in body


def test_k10_draft_and_trashed_article_are_absent_even_for_author_and_manager(admin_page, employee):
    """Сценарий 10, п. 9: черновик и статья в корзине не находятся ни автором, ни управляющим; опубликованная — да;
    публикация и возврат из корзины возвращают статью в поиск (FR-444, FR-447)."""
    editor = helpers_kb.make_editor(employee)
    rubric = _rubric(admin_page)
    draft_word, trash_word, live_word = unique_word("d"), unique_word("t"), unique_word("l")
    draft_id = helpers_kb.create_draft(editor.page, title=f"Черновик {draft_word}", text="Текст.", rubric=rubric)
    trash_id = _publish(editor.page, rubric, f"Корзина {trash_word}")
    live_id = _publish(editor.page, rubric, f"Живая {live_word}")
    both = (("автор", editor.page), ("управляющий", admin_page))
    for who, page in both:
        assert f"/kb/{live_id}/" in helpers_kb.search_hrefs(page, live_word), f"{who}: опубликованная не найдена"
        assert f"/kb/{trash_id}/" in helpers_kb.search_hrefs(page, trash_word), f"{who}: статья до корзины не найдена"
    # управляющий убирает статью в корзину
    admin_page.goto(f"/kb/{trash_id}/")
    admin_page.once("dialog", lambda dialog: dialog.accept())
    helpers.submit(admin_page.locator('form[data-form="kb-trash"]'))
    expect(admin_page.locator(f'article[data-article-id="{trash_id}"][data-article-state="trash"]')).to_be_visible()
    for who, page in both:
        hrefs = helpers_kb.search_hrefs(page, draft_word)
        assert f"/kb/{draft_id}/" not in hrefs, f"{who}: нашёлся черновик"
        expect(page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
        hrefs = helpers_kb.search_hrefs(page, trash_word)
        assert f"/kb/{trash_id}/" not in hrefs, f"{who}: нашлась статья из корзины"
        expect(page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
        assert f"/kb/{live_id}/" in helpers_kb.search_hrefs(page, live_word)
    # возврат из корзины — статья снова находится
    admin_page.goto(f"/kb/{trash_id}/")
    admin_page.once("dialog", lambda dialog: dialog.accept())
    helpers.submit(admin_page.locator('form[data-form="kb-restore"]'))
    expect(admin_page.locator(f'article[data-article-id="{trash_id}"][data-article-state="published"]')).to_be_visible()
    for who, page in both:
        assert f"/kb/{trash_id}/" in helpers_kb.search_hrefs(page, trash_word), f"{who}: статья после возврата не найдена"
    # публикация черновика — статья находится
    helpers_kb.publish_from_article_page(editor.page, draft_id)
    for who, page in both:
        assert f"/kb/{draft_id}/" in helpers_kb.search_hrefs(page, draft_word), f"{who}: опубликованный черновик не найден"


def test_k10_other_word_form_finds_article_and_title_match_ranks_above_text_match(admin_page, employee):
    """Сценарий 10, п. 10: слово «настройка» находит статью, где в тексте «настройки»; статья с совпадением в
    заголовке стоит выше, хотя другая новее (FR-443)."""
    reader = helpers_kb.make_reader(employee).page
    rubric = _rubric(admin_page)
    word = unique_word("m")
    in_title = _publish(admin_page, rubric, f"Настройка {word}", text="Краткое описание.")
    in_text = _publish(admin_page, rubric, f"Заметка {word}", text="Здесь описаны настройки подключения к сети.")
    hrefs = _group_hrefs(reader, f"{word} настройка", "articles")
    assert f"/kb/{in_text}/" in hrefs, "словоформа «настройки» в тексте не найдена по «настройка»"
    assert f"/kb/{in_title}/" in hrefs
    assert hrefs.index(f"/kb/{in_title}/") < hrefs.index(f"/kb/{in_text}/"), \
        "совпадение в тексте стоит выше совпадения в заголовке"


def test_k10_nine_word_query_uses_first_eight_and_query_over_200_chars_is_not_accepted(admin_page):
    """Сценарий 10, п. 11: из девяти слов учитываются первые восемь (статья по восьми словам находится, а с
    несовпавшим восьмым — нет); запрос длиннее 200 знаков не принимается (подсказка, ни одной строки), ровно 200
    принимается (FR-443)."""
    rubric = _rubric(admin_page)
    words = [unique_word("w") for _ in range(8)]
    article_id = _publish(admin_page, rubric, " ".join(words))
    ninth = unique_word("x")
    assert helpers_kb.search_finds(admin_page, " ".join(words + [ninth]), article_id), \
        "девятое слово не отброшено"
    assert helpers_kb.search_finds(admin_page, " ".join(words), article_id), "контроль: восемь слов не находят статью"
    assert not helpers_kb.search_finds(admin_page, " ".join(words[:7] + [ninth]), article_id), \
        "восьмое слово не учтено (запрос из восьми слов с чужим восьмым нашёл статью)"
    # длиннее 200 знаков
    field = _field(admin_page)
    assert field.get_attribute("maxlength") == "200"
    too_long = words[0] + " " + "x" * (201 - len(words[0]) - 1)
    assert len(too_long) == 201
    _results(admin_page, too_long)
    expect(admin_page.locator('[data-search-page] [data-search-hint="long"]')).to_contain_text(HINT_LONG)
    expect(admin_page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
    status, body = _get_text(admin_page, "/search/popup/?" + urlencode({"q": too_long}))
    assert status == 200 and "data-search-group" not in body
    # ровно 200 знаков — запрос принят: подсказки нет, слово "xxx…" ничего не находит
    exact = words[0] + " " + "x" * (200 - len(words[0]) - 1)
    assert len(exact) == 200
    _results(admin_page, exact)
    expect(admin_page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
    expect(admin_page.locator('[data-search-page] [data-empty-state="search"]')).to_contain_text(NOTHING_FOUND)


def test_k10_employee_without_view_staff_right_has_no_employees_and_departments_groups(admin_page, employee):
    """Сценарий 10, п. 12: у сотрудника без права «Просмотр сотрудников и структуры» в выдаче нет групп «Сотрудники»
    и «Подразделения» (страница, окно, счёт и «ещё»); у сотрудника с правом они есть (FR-444)."""
    word = unique_word("k")
    target = employee(full_name=f"{word.capitalize()} Тест Тестович")
    unit_id = helpers_org.create_unit(admin_page, f"{word} Отдел")
    _publish(admin_page, _rubric(admin_page), f"Статья {word}")
    allowed = employee().page
    restricted = employee(role=_make_role_without_staff_view(admin_page)).page
    # контроль: с правом обе группы есть и в них найденное
    assert f"/staff/{target.id}/" in _group_hrefs(allowed, word, "staff")
    assert f"/structure/{unit_id}/" in _group_hrefs(allowed, word, "units")
    status, body = _get_text(allowed, "/search/count/?" + urlencode({"q": word, "group": "staff"}))
    assert status == 200 and "data-count" in body
    # без права: статьи есть, сотрудников и подразделений нет
    _results(restricted, word)
    assert _groups(restricted.locator("[data-search-page]")) == ["articles"]
    expect(_section(restricted, "staff")).to_have_count(0)
    expect(_section(restricted, "units")).to_have_count(0)
    assert f"/staff/{target.id}/" not in _hrefs(restricted.locator("[data-search-page]"))
    _open_popup(restricted, word)
    assert _groups(_popup(restricted)) == ["articles"]
    for group in ("staff", "units"):
        status, body = _get_text(restricted, "/search/count/?" + urlencode({"q": word, "group": group}))
        assert status == 200 and not body.strip(), f"счёт группы {group} без права: {body[:80]}"
        status, body = _get_text(restricted, "/search/more/?" + urlencode({"q": word, "group": group, "offset": 0}))
        assert status == 200 and not body.strip(), f"«ещё» группы {group} без права: {body[:80]}"


def test_k10_invited_blocked_or_dismissed_employee_is_not_in_employees_group(admin_page, employee):
    """Сценарий 10, п. 13: в группе «Сотрудники» только действующие записи — после блокировки и увольнения
    сотрудник из выдачи пропадает, приглашённый (не активированный) в ней не появляется (FR-444)."""
    word = unique_word("k")
    surname = word.capitalize()
    active = employee(full_name=f"{surname} Активный Иванович")
    blocked = employee(full_name=f"{surname} Заблокированный Иванович")
    dismissed = employee(full_name=f"{surname} Уволенный Иванович")
    invited = employee(activate=False, full_name=f"{surname} Приглашённый Иванович")
    page = active.page
    hrefs = _group_hrefs(page, word, "staff")
    for account in (active, blocked, dismissed):
        assert f"/staff/{account.id}/" in hrefs, "контроль: действующий сотрудник не найден до блокировки"
    assert f"/staff/{invited.id}/" not in hrefs, "приглашённый попал в выдачу"
    _block(admin_page, blocked)
    _dismiss(admin_page, dismissed.id)
    hrefs = _group_hrefs(page, word, "staff")
    assert f"/staff/{active.id}/" in hrefs
    for who, account in (("заблокированный", blocked), ("уволенный", dismissed), ("приглашённый", invited)):
        assert f"/staff/{account.id}/" not in hrefs, f"{who} остался в выдаче"
    _open_popup(page, word)
    popup_hrefs = _hrefs(_popup(page).locator('section[data-search-group="staff"]'))
    assert f"/staff/{active.id}/" in popup_hrefs
    assert not {f"/staff/{a.id}/" for a in (blocked, dismissed, invited)} & set(popup_hrefs)


def test_k10_results_page_at_360px_does_not_widen_page(admin_page, employee, browser, browser_context_args):
    """Сценарий 10, п. 14: на 360 px страница результатов (с длинными словами в заголовках, подсказкой и пустой выдачей)
    не получает горизонтальной прокрутки страницы (NFR-406)."""
    world = _world(admin_page, employee)
    word = world.word
    long_word = word + "q" * 140
    _send_tickets([f"Заявка {long_word}"])
    _publish(admin_page, _rubric(admin_page), long_word)
    helpers_org.create_unit(admin_page, word + "u" * 40)
    context = helpers_kb.narrow_context(browser, browser_context_args, world.viewer.page)
    try:
        page = context.new_page()
        for query in (word, "5", unique_word("zz")):
            _results(page, query)
            if query == word:
                assert _groups(page.locator("[data-search-page]")) == GROUP_ORDER
                for section in page.locator("[data-search-page] section[data-search-group]").all():
                    expect(section.locator("span[data-search-count-value]")).to_be_visible()
            assert helpers_kb.page_fits(page), f"запрос {query[:14]}: страница шире 360 px"
            assert helpers.no_horizontal_scroll(page)
    finally:
        context.close()


def test_k10_search_query_text_is_absent_from_portal_event_journal_after_search(admin_page, employee):
    """Сценарий 10, п. 15: после поиска (окно, страница, счёт, «ещё») текста запроса нет в журнале событий портала
    (журнал приложения и таблицы базы проверяют серверные тесты T-5128; FR-446)."""
    marker = unique_word("mk")
    article_id = _publish(admin_page, _rubric(admin_page), f"Статья {unique_word('t')}",
                          text=f"Описание {marker} подключения.")
    page = helpers_kb.make_reader(employee).page
    assert f"/kb/{article_id}/" in _group_hrefs(page, marker, "articles"), "контроль: запрос ничего не нашёл"
    _open_popup(page, marker)
    for path in ("/search/count/?" + urlencode({"q": marker, "group": "articles"}),
                 "/search/more/?" + urlencode({"q": marker, "group": "articles", "offset": 20}),
                 "/search/popup/?" + urlencode({"q": marker})):
        status, _ = _get_text(page, path)
        assert status == 200
    text = helpers.audit_text(admin_page)
    expect(admin_page.locator("tr[data-event-id]").first).to_be_visible()
    assert marker not in text, "текст запроса попал в журнал событий"
    assert not any("search" in (action or "") for action in helpers.audit_actions(admin_page)), \
        "в журнале есть событие поиска"


def test_k10_tickets_5_and_15_found_by_hash_or_digits_first_and_single_digit_or_short_words_give_hint(admin_page, employee):
    """Сценарий 10, п. 17: заявка находится по «#N» и «N» (N не меньше 10) и стоит первой; «5» без «#» и «а б» дают
    подсказку; «#5», «#15» и «15» — подсказки нет, заявка по номеру первая, если она есть на стенде (FR-443)."""
    world = _world(admin_page, employee)
    page = world.viewer.page
    first, _ = _ticket_from_ten(admin_page)
    second, _ = _ticket(admin_page)
    for number in (first, second):
        queries = [f"#{number}"] + ([str(number)] if number >= 10 else [])
        for query in queries:
            hrefs = _group_hrefs(page, query, "tickets")
            assert hrefs and hrefs[0] == f"/tickets/{number}/", f"{query}: первой стоит {hrefs[:1]}"
            expect(page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
    for query in ("5", "а б", " 7 "):
        _results(page, query)
        expect(page.locator('[data-search-page] [data-search-hint="short"]')).to_contain_text(HINT_SHORT)
        expect(page.locator("[data-search-page] section[data-search-group]")).to_have_count(0)
    # «#5», «#15», «15»: на стенде такие заявки могут быть или нет (номера идут дальше); администратор видит все
    for number, queries in ((5, ["#5"]), (15, ["#15", "15"])):
        exists = helpers_org.direct_get(admin_page, f"/tickets/{number}/").status
        assert exists in (200, 404), f"/tickets/{number}/: ответ {exists}"
        for query in queries:
            hrefs = _group_hrefs(admin_page, query, "tickets")
            expect(admin_page.locator("[data-search-page] [data-search-hint]")).to_have_count(0)
            if exists == 200:
                assert hrefs and hrefs[0] == f"/tickets/{number}/", f"{query}: первой стоит {hrefs[:1]}"
            else:
                assert f"/tickets/{number}/" not in hrefs


def test_k10_employee_found_by_email_whole_or_part_phone_position_department_or_workplace(
        admin_page, mailpit, new_context):
    """Сценарий 10, п. 18: сотрудник находится по ФИО, по адресу почты целиком и по части, по телефону (цифры, с «8»
    вместо «7», с «+», по началу номера), по должности, по подразделению и по месту работы (FR-443; раздел 17,
    п. 47)."""
    surname_word, local, position_word = unique_word("fam"), unique_word("petrov"), unique_word("dolzh")
    workplace_word, unit_word = unique_word("kab"), unique_word("otdel")
    email = local + "@" + "example.test"
    digits = "9" + "".join(str(secrets.randbelow(10)) for _ in range(9))
    phone = f"+7 {digits[:3]} {digits[3:6]}-{digits[6:8]}-{digits[8:]}"
    entry_phrase = factories.new_password()
    user_id = helpers.create_employee(admin_page, email, full_name=f"{surname_word.capitalize()} Пётр Сергеевич",
                                      position=f"Инженер {position_word}", phone=phone)
    mail = helpers.wait_mail(mailpit, email, "invitation")
    page = new_context().new_page()
    helpers.walk_activation(page, helpers.link_in(mail, "/activate/"), entry_phrase, phone=phone)
    unit_id = helpers_org.create_unit(admin_page, f"{unit_word} Отдел")
    helpers_org.add_members(admin_page, unit_id, [user_id], q=surname_word.capitalize(), mode="concurrent")
    page.goto("/me/")
    form = page.locator('form:has(input[name="internal_phone"])')
    form.locator("[name=workplace]").fill(f"Кабинет {workplace_word}")
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    expect(page.locator("[role=status]").first).to_be_visible()
    queries = {
        "ФИО (фамилия)": surname_word,
        "почта целиком": email,
        "часть почты": local,
        "начало почты": local[:8],
        "должность": position_word,
        "подразделение": unit_word,
        "место работы": workplace_word,
        "телефон цифрами": "7" + digits,
        "телефон с 8": "8" + digits,
        "телефон с плюсом": "+7" + digits,
        "начало телефона": ("7" + digits)[:8],
    }
    for label, query in queries.items():
        hrefs = _group_hrefs(admin_page, query, "staff")
        assert f"/staff/{user_id}/" in hrefs, f"сотрудник не найден по запросу «{label}»"


def test_k10_employees_over_20_sorted_by_full_name_departments_by_title_and_show_more_adds_next_20(admin_page):
    """Сценарий 10, п. 19: в группах «Сотрудники» и «Подразделения» по 22 строки: на странице 20 по ФИО (по
    названию), число группы 22, «Показать ещё» добавляет следующие (FR-442, FR-443)."""
    word = unique_word("k")
    surname = word.capitalize()
    total = 22
    names = []
    for i in range(total):
        email = f"{word}-{i:02d}@" + "example.com"
        name = f"{surname} Сотрудник{i:02d} Иванович"
        helpers.create_employee(admin_page, email, full_name=name)
        names.append(name)
    # подготовка вне интерфейса (единственная stand_shell файла): записи приглашены, а в группе — только действующие
    changed = helpers.stand_shell(
        "from django.apps import apps; "
        f"print(apps.get_model('core.User').objects.filter(email__startswith='{word}-', state='invited')"
        ".update(state='active'))")
    assert changed.splitlines()[-1].strip() == str(total), f"активировано записей: {changed[-40:]}"
    unit_names = []
    for i in range(total):
        unit_names.append(f"{word} Отдел{i:02d}")
        helpers_org.create_unit(admin_page, unit_names[-1])
    _results(admin_page, word)
    for key, expected in (("staff", names), ("units", unit_names)):
        section = _section(admin_page, key)
        value = section.locator("span[data-search-count-value]")
        expect(value).to_be_visible()
        expect(value).to_have_attribute("data-count", str(total))
        rows = section.locator("li[data-search-row]")
        expect(rows).to_have_count(20)
        more = section.locator('button[data-action="more"]')
        expect(more).to_have_count(1)
        expect(more).to_have_attribute("data-next-offset", "20")
        more.click()
        expect(rows).to_have_count(total)
        titles = [_norm(t) for t in rows.locator('[data-field="title"]').all_inner_texts()]
        assert len(titles) == total
        for title, wanted in zip(titles, expected):
            assert wanted in title, f"{key}: порядок строк нарушен: {title!r} вместо {wanted!r}"
        expect(section.locator('button[data-action="more"]')).to_have_count(0)
