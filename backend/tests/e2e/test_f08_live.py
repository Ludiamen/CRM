"""T-7147: сценарий 8 — лента обновляется сама, непрочитанное (FR-602, FR-626, FR-627, FR-628, NFR-602).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 10–14; решения 8, 26, 54, 55, 57, 62 задач):
- люди и узлы — `helpers_feed.feed_cast` один раз на браузер (фикстура `circle`, сессии сохраняются в
  `Account.storage_state`: заводить девять человек с мастером активации на каждый из 21 теста — часы прохода);
  тесты, которым нужны точные числа у пункта «Лента» (0, 3, «99+», вход и выход сессии), берут свежего сотрудника
  фикстурой `employee`;
- ожидания — только `expect(...).to_have_attribute(..., timeout=…)` и помощники `wait_badge`, `wait_banner`; время
  замеряется `time.monotonic()` от возврата ответа на публикацию (комментарий, отметку, правку, удаление) до
  видимого результата, ожидание берётся чуть больше нормы (4 с), проверка — по замеру (2 с, NFR-602; 35 с у закрытия
  соединения: допуск 30 с, FR-627, плюс запас на сторону браузера), как образец e12;
- числа у пункта «Лента» у людей круга — дельтами от значения до действия (записи «Всем» соседних файлов круга общие);
  абсолютные 0, 3 и «99+» — у свежего сотрудника, чья лента перед опытом «осушена» (`_drain`: «Ещё записи» до конца);
- записи — адресные (узел «Бухгалтерия», человек), «Всем» — только там, где зрителем служит свежий сотрудник и нужен
  положительный контроль у Петрова; объёмные записи (3, 21, 50, 120) — `publish_request` одному адресату;
  записи, которым нужен номер вне списка (важные), публикуются формой (`publish`);
- «нет плашки, числа, фрагмента» утверждается после положительного сигнала у контрольного наблюдателя (без сна): порядок
  кадров по соединению сохраняется;
- без WebSocket — `block_ws(context)` до создания страниц, `open_feed(..., live=False)` (решение 55 задач);
- правка и удаление чужой для зрителя записи делаются запросом в обход страницы (`helpers_org.direct_post`): сама правка
  и удаление через интерфейс проверены в f07, здесь важен только кадр у зрителя;
- старые записи новичка — `age(31, posts=[…])` по номерам своих записей (решение 54 задач), не по всему стенду.
"""
import re
import time
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed, helpers_notify, helpers_org
from tests.e2e.helpers_feed import (
    add_comment, age, badge, block_ws, important_ids, like, like_comment, open_card, open_feed, post_ids, publish,
    publish_request, wait_badge, wait_banner)

FRAME_SECONDS = 2.0        # NFR-602
CLOSE_SECONDS = 35.0       # FR-627: допуск 30 с и запас
WAIT_MS = 4_000
_CIRCLES: dict = {}


class Circle(NamedTuple):
    cast: object      # `helpers_feed.FeedCast`
    names: dict       # номер узла → название (для подсказки «Кому»)


@pytest.fixture
def circle(browser, admin_page, mailpit, new_context) -> Circle:
    """Круг сценария: собирается при первом обращении в круге браузера; учётки переходят на сохранённые сессии."""
    key = browser.e2e_project
    if key not in _CIRCLES:
        cast = helpers_feed.feed_cast(admin_page, mailpit, new_context)
        names = {}
        for unit in (cast.it_unit, cast.net_unit, cast.accounting_unit):
            helpers_org.open_structure(admin_page, unit)
            names[unit] = helpers_org.unit_link(admin_page, unit).first.text_content().strip()
        for item in cast:
            if isinstance(item, helpers.Account) and item.page is not None:
                item.storage_state = item.page.context.storage_state()
                item.page = None
        _CIRCLES[key] = Circle(cast, names)
    return _CIRCLES[key]


# --- Общие приёмы -------------------------------------------------------------------------------------------------

def _word(prefix: str) -> str:
    return helpers_org.unique_name(prefix)


def _writer_page(new_context, cast):
    """Страница писателя (без соединения: он только публикует)."""
    return open_feed(new_context(), cast.writer, live=False)


def _unit_post(page, circle, text: str, *, kind: str = "post", term=None) -> int:
    """Запись узлу «Бухгалтерия» формой писателя; возвращает номер."""
    return publish(page, text, kind=kind, term=term, to=[("unit", circle.names[circle.cast.accounting_unit])])


def _since(started: float, limit: float, what: str) -> None:
    elapsed = time.monotonic() - started
    assert elapsed <= limit, f"{what}: {elapsed:.2f} с при норме {limit:.0f} с"


def _drain(page) -> None:
    """Листает ленту «Ещё записи» до конца: все видимые записи показаны, число «Ленты» обнулено."""
    for _ in range(80):
        more = page.locator("a[data-feed-more]")
        if not more.count():
            return
        shown = len(post_ids(page))
        with page.expect_response(lambda r: "/feed/more/" in r.url):
            more.first.click()
        page.wait_for_function(
            "n => document.querySelectorAll('#feed-list [data-post-id]').length > n", arg=shown, timeout=15_000)
    raise AssertionError("лента не закончилась за 80 нажатий «Ещё записи»")


def _fresh_watcher(employee, new_context, name: str):
    """Свежий сотрудник с осушённой лентой: возвращает учётку и страницу ленты (число «Ленты» — 0)."""
    account = employee(full_name=f"{name}{helpers_org.unique_name('н')[2:]} Иван Иванович")
    page = open_feed(new_context(), account, live=False)
    _drain(page)
    assert badge(page) == 0, "после осушения ленты число у «Ленты» не ноль"
    return account, page


def _banner_link(page):
    return page.locator("#feed-new a").first


def _unit_posts(writer, unit_id, texts):
    return [publish_request(writer, kind="post", text=text, to=f"u{unit_id}") for text in texts]


def _end_by_logout_everywhere(new_context, account, admin_page) -> None:
    other = new_context().new_page()
    helpers.sign_in(other, account)
    other.goto("/me/security/")
    helpers.submit(other.locator('form[action="/me/security/logout-everywhere/"]'))
    other.goto("/me/security/")
    expect(other.locator("#top-bar")).to_be_visible()


def _end_by_block(new_context, account, admin_page) -> None:
    admin_page.goto(f"/staff/{account.id}/")
    helpers.open_security_tab(admin_page)
    form = admin_page.locator('form[action$="/block/"]')
    form.locator("[name=reason]").fill("проверка живой ленты")
    helpers.submit(form)
    admin_page.goto(f"/staff/?state=blocked&q={account.email}")
    expect(helpers.staff_row(admin_page, account.email)).to_have_count(1)


def _end_by_dismiss(new_context, account, admin_page) -> None:
    admin_page.goto(f"/staff/{account.id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{account.id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _connection_closes_and_no_more_fragments(employee, circle, new_context, admin_page, end_session) -> None:
    """Общий ход трёх проверок закрытия соединения: открытая лента свежего сотрудника, сессия закончена (`end_session`),
    писатель публикует «Всем» — не позже 35 с вкладка получает `data-ws="closed"`; следующая запись доходит до
    контрольного Петрова (положительный сигнал), а закрытая вкладка нового не получает: плашка, записи и число прежние."""
    c = circle.cast
    account = employee(full_name=f"Закрываемый{helpers_org.unique_name('н')[2:]} Иван Иванович")
    tab = open_feed(new_context(), account)
    control = open_feed(new_context(), c.petrov)
    writer = _writer_page(new_context, c)
    end_session(new_context, account, admin_page)
    started = time.monotonic()
    publish_request(writer, kind="post", text=_word("Запись после конца сессии"), to="all")
    expect(tab.locator("#feed-live")).to_have_attribute("data-ws", "closed", timeout=int(CLOSE_SECONDS * 1000))
    _since(started, CLOSE_SECONDS, "закрытие соединения открытой вкладки")
    banner_after_close = tab.locator("#feed-new").get_attribute("data-count")
    ids_after_close = post_ids(tab)
    badge_after_close = badge(tab)
    second = publish_request(writer, kind="post", text=_word("Вторая запись"), to="all")
    wait_banner(control, 2)  # положительный контроль: рассылка идёт и дошла до того, кто видит
    assert tab.locator("#feed-new").get_attribute("data-count") == banner_after_close, "закрытая вкладка получила плашку"
    assert post_ids(tab) == ids_after_close and second not in post_ids(tab)
    expect(tab.locator(f"#feed-post-{second}")).to_have_count(0)
    assert badge(tab) == badge_after_close, "закрытая вкладка получила число"


# --- Тесты --------------------------------------------------------------------------------------------------------

def test_f08_colleague_post_gives_new_posts_1_banner_and_feed_badge_plus_1_within_2s_without_inserting_post(
        circle, new_context):
    """Сценарий 8, п. 1 (FR-626, FR-627, NFR-602): у сотрудника открыта лента, коллега публикует запись, которую он
    видит — не позже чем через 2 с сверху плашка «Новых записей: 1», число у «Ленты» выросло на 1; саму запись в ленту
    не вставляют."""
    c = circle.cast
    watcher = open_feed(new_context(), c.accountant)
    base, before = badge(watcher), post_ids(watcher)
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Новая запись"))
    started = time.monotonic()
    wait_banner(watcher, 1, timeout=WAIT_MS)
    wait_badge(watcher, base + 1, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "плашка и число после публикации")
    assert post_ids(watcher) == before and pid not in post_ids(watcher), "запись вставлена в ленту сама"
    expect(watcher.locator(f"#feed-post-{pid}")).to_have_count(0)


def test_f08_new_posts_2_banner_click_puts_two_posts_on_top_and_hides_banner(circle, new_context):
    """Сценарий 8, п. 2 (FR-627): плашка «Новых записей: 2» — по нажатию две записи наверху ленты (новая выше),
    плашка исчезает."""
    c = circle.cast
    watcher = open_feed(new_context(), c.accountant)
    writer = _writer_page(new_context, c)
    first = _unit_post(writer, circle, _word("Первая из двух"))
    second = _unit_post(writer, circle, _word("Вторая из двух"))
    wait_banner(watcher, 2, timeout=WAIT_MS)
    _banner_link(watcher).click()
    expect(watcher.locator("#feed-new")).to_be_hidden()
    rows = watcher.locator("#feed-list [data-post-id]")
    expect(rows.nth(0)).to_have_attribute("data-post-id", str(second))
    expect(rows.nth(1)).to_have_attribute("data-post-id", str(first))


def test_f08_comment_on_shown_post_appears_in_place_within_2s(circle, new_context):
    """Сценарий 8, п. 3, комментарий (FR-627, NFR-602): к показанной записи коллега пишет комментарий — не позже
    чем через 2 с он на месте, страница не перезагружена."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись для комментария"))
    watcher = open_feed(new_context(), c.accountant)
    expect(watcher.locator(f"#feed-post-{pid}")).to_be_visible()
    watcher.evaluate("() => { window.__f08_alive = true; }")
    colleague = open_card(new_context(), c.petrov, pid)
    text = _word("Живой комментарий")
    add_comment(colleague, pid, text)
    started = time.monotonic()
    expect(watcher.locator(f"#feed-post-{pid}-comments")).to_contain_text(text, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "комментарий на месте")
    assert watcher.evaluate("() => window.__f08_alive === true"), "страница перезагружена"


def test_f08_like_on_shown_post_appears_in_place_within_2s(circle, new_context):
    """Сценарий 8, п. 3, «Нравится» (FR-627, NFR-602): отметка коллеги на показанной записи видна на месте не позже
    чем через 2 с."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись для отметки"))
    watcher = open_feed(new_context(), c.accountant)
    expect(watcher.locator(f"#feed-post-{pid}")).to_be_visible()
    colleague = open_card(new_context(), c.petrov, pid)
    assert like(colleague, pid) is True
    started = time.monotonic()
    expect(watcher.locator(f"#feed-post-{pid}-likers")).to_contain_text(c.petrov.full_name.split()[0], timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "отметка «Нравится» на месте")


def test_f08_edit_of_shown_post_appears_in_place_within_2s(circle, new_context):
    """Сценарий 8, п. 3, правка (FR-627, NFR-602): правка показанной записи автором видна на месте не позже чем
    через 2 с."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись до правки"))
    watcher = open_feed(new_context(), c.accountant)
    expect(watcher.locator(f"#feed-post-{pid}")).to_be_visible()
    new = _word("Запись после правки")
    response = helpers_org.direct_post(writer, f"/feed/{pid}/edit/", {"text": new, "to": f"u{c.accounting_unit}"})
    assert response.status == 302, f"правка запросом: ожидался 302, получен {response.status}"
    started = time.monotonic()
    expect(watcher.locator(f"#feed-post-{pid}-body")).to_contain_text(new, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "правка записи на месте")


def test_f08_delete_of_shown_post_removes_it_from_page_within_2s(circle, new_context):
    """Сценарий 8, п. 3, удаление (FR-627, NFR-602): удаление показанной записи автором — запись пропала со страницы
    не позже чем через 2 с."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись под удаление"))
    watcher = open_feed(new_context(), c.accountant)
    expect(watcher.locator(f"#feed-post-{pid}")).to_be_visible()
    response = helpers_org.direct_post(writer, f"/feed/{pid}/delete/")
    assert response.status == 302, f"удаление запросом: ожидался 302, получен {response.status}"
    started = time.monotonic()
    expect(watcher.locator(f"#feed-post-{pid}")).to_have_count(0, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "удаление записи на месте")


def test_f08_open_post_card_gets_new_comment_in_place_within_2s_and_no_banner(circle, new_context):
    """Сценарий 8, п. 3 для карточки (FR-627, NFR-602): в открытой карточке записи новый комментарий появляется на
    месте не позже чем через 2 с; плашки о новых записях в карточке нет."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись в карточке"))
    card = open_card(new_context(), c.accountant, pid)
    colleague = open_card(new_context(), c.petrov, pid)
    text = _word("Комментарий в карточку")
    add_comment(colleague, pid, text)
    started = time.monotonic()
    expect(card.locator(f"#feed-post-{pid}-comments")).to_contain_text(text, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "комментарий в открытой карточке")
    _unit_post(writer, circle, _word("Другая запись при открытой карточке"))
    expect(card.locator("#feed-new")).to_have_count(0)


def test_f08_feed_badge_changes_live_on_other_portal_page(circle, new_context):
    """Сценарий 8, п. 1 и FR-627 («число у пункта «Лента» — сразу на любой странице портала»): на странице «Мой
    профиль» число у «Ленты» растёт без перезагрузки, когда коллега публикует запись."""
    c = circle.cast
    context = new_context()
    helpers_notify.adopt_session(context, c.accountant)
    page = context.new_page()
    page.goto("/me/")
    page.wait_for_load_state()
    helpers_notify.wait_ws_open(page)
    base = badge(page)
    page.evaluate("() => { window.__f08_alive = true; }")
    writer = _writer_page(new_context, c)
    _unit_post(writer, circle, _word("Запись для другой страницы"))
    started = time.monotonic()
    wait_badge(page, base + 1, timeout=WAIT_MS)
    _since(started, FRAME_SECONDS, "число «Ленты» на другой странице")
    assert page.evaluate("() => window.__f08_alive === true"), "страница перезагружена"


def test_f08_like_button_of_comment_inserted_by_frame_sends_request_and_sets_like(circle, new_context):
    """FR-627 (кадр вставляет комментарий): у комментария, вставленного кадром, кнопка «Нравится» работает — нажатие
    отправляет запрос и ставит отметку (токен CSRF добавляет скрипт)."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись для кадра"))
    watcher = open_feed(new_context(), c.accountant)
    expect(watcher.locator(f"#feed-post-{pid}")).to_be_visible()
    colleague = open_card(new_context(), c.petrov, pid)
    cid = add_comment(colleague, pid, _word("Комментарий кадром"))
    expect(watcher.locator(f"#c{cid}")).to_be_visible(timeout=WAIT_MS)
    assert like_comment(watcher, cid) is True
    likers = helpers_org.direct_get(watcher, f"/feed/comments/{cid}/likes/").text()
    assert c.accountant.full_name.split()[0] in likers, "отметка не записана на сервере"


def test_f08_post_only_for_petrov_gives_other_open_feeds_no_banner_badge_or_fragment_on_publish_and_comment(
        circle, new_context):
    """Сценарий 8, п. 4 (FR-628): запись адресована только Петрову — у других сотрудников с открытой лентой нет ни
    плашки, ни числа, ни фрагмента записи и её комментария; у Петрова (контроль) всё приходит."""
    c = circle.cast
    others = [open_feed(new_context(), account) for account in (c.accountant, c.sidorov)]
    bases = [badge(page) for page in others]
    control = open_feed(new_context(), c.petrov)
    author = open_feed(new_context(), c.writer)
    text, comment_text = _word("Только для Петрова"), _word("Комментарий для Петрова")
    pid = publish(author, text, to=[("person", c.petrov.full_name)])
    wait_banner(control, 1, timeout=WAIT_MS)  # положительный сигнал: кадр у видящего дошёл
    _banner_link(control).click()
    expect(control.locator(f"#feed-post-{pid}")).to_be_visible()
    add_comment(control, pid, comment_text)
    expect(author.locator(f"#feed-post-{pid}-comments")).to_contain_text(comment_text, timeout=WAIT_MS)
    for page, base in zip(others, bases):
        expect(page.locator("#feed-new")).to_be_hidden()
        expect(page.locator(f"#feed-post-{pid}")).to_have_count(0)
        expect(page.locator("body")).not_to_contain_text(comment_text)
        assert badge(page) == base, "число «Ленты» изменилось у не видящего запись"


def test_f08_opening_feed_with_3_unread_posts_drops_feed_badge_to_zero_and_own_post_never_unread(
        circle, employee, new_context):
    """Сценарий 8, п. 5 (FR-626): три непрочитанные записи — сотрудник открывает ленту, они показаны, число у
    «Ленты» становится 0; своя запись непрочитанной не бывает."""
    c = circle.cast
    account, page = _fresh_watcher(employee, new_context, "Читатель")
    writer = _writer_page(new_context, c)
    for n in range(3):
        publish_request(writer, kind="post", text=_word(f"Непрочитанная {n}"), to=f"p{account.id}")
    page.goto("/me/")
    assert badge(page) == 3, f"до открытия ленты ожидалось 3, число {badge(page)}"
    page.goto("/")
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()
    wait_badge(page, 0, timeout=WAIT_MS)
    page.goto("/me/")
    assert badge(page) == 0
    own = publish(open_feed(new_context(), account, live=False), _word("Своя запись"),
                  to=[("person", c.petrov.full_name)])
    page.goto("/me/")
    assert badge(page) == 0, f"своя запись {own} сделала число «Ленты» ненулевым"


def test_f08_120_unread_posts_show_99_plus_at_feed_item(circle, employee, new_context):
    """Сценарий 8, п. 6 (FR-626): непрочитанных записей 120 — у пункта «Лента» «99+»."""
    c = circle.cast
    account, page = _fresh_watcher(employee, new_context, "Заваленный")
    writer = _writer_page(new_context, c)
    for n in range(120):
        publish_request(writer, kind="post", text=_word(f"Поток {n}"), to=f"p{account.id}")
    page.goto("/me/")
    expect(page.locator("#menu-badge-feed")).to_contain_text(re.compile(r"99\+"))
    assert "100" not in page.locator("#menu-badge-feed").inner_text()


def test_f08_without_websocket_publish_comment_like_and_more_posts_work_by_plain_requests_and_new_seen_after_reload(
        circle, new_context):
    """Сценарий 8, п. 7 (FR-628): соединение WebSocket недоступно (`block_ws`) — публикация, комментарий, «Нравится»
    и «Ещё записи» работают обычными запросами; новая запись коллеги видна только после обновления страницы."""
    c = circle.cast
    helper_writer = _writer_page(new_context, c)
    for n in range(21):  # у Петрова больше 20 записей: есть «Ещё записи»
        publish_request(helper_writer, kind="post", text=_word(f"Для листания {n}"), to=f"p{c.petrov.id}")
    context = new_context()
    block_ws(context)
    page = open_feed(context, c.petrov, live=False)
    expect(page.locator('#feed-live[data-ws="open"]')).to_have_count(0)
    text, comment_text = _word("Запись без соединения"), _word("Комментарий без соединения")
    own = publish(page, text, to=[("person", c.sidorov.full_name)])
    add_comment(page, own, comment_text)
    assert like(page, own) is True
    shown = len(post_ids(page))
    assert shown >= 20 and page.locator("a[data-feed-more]").count() == 1
    with page.expect_response(lambda r: "/feed/more/" in r.url):
        page.locator("a[data-feed-more]").first.click()
    page.wait_for_function(
        "n => document.querySelectorAll('#feed-list [data-post-id]').length > n", arg=shown, timeout=15_000)
    reader = open_card(new_context(), c.sidorov, own)  # сервер всё принял
    expect(reader.locator(f"#feed-post-{own}-comments")).to_contain_text(comment_text)
    fresh = publish_request(helper_writer, kind="post", text=_word("Новая для Петрова"), to=f"p{c.petrov.id}")
    expect(page.locator("#feed-new")).to_be_hidden()
    assert fresh not in post_ids(page), "запись появилась без соединения и без обновления"
    page.reload()
    page.wait_for_load_state()
    assert post_ids(page)[0] == fresh, "после обновления новая запись не сверху"


def test_f08_logout_from_all_devices_closes_open_tab_connection_within_35s_and_no_more_fragments(
        circle, employee, new_context, admin_page):
    """Сценарий 8, п. 8 (FR-627): сессия завершена («Выйти со всех устройств»), коллега публикует — не позже чем
    через 35 с соединение открытой вкладки закрыто, фрагментов она больше не получает."""
    _connection_closes_and_no_more_fragments(employee, circle, new_context, admin_page, _end_by_logout_everywhere)


def test_f08_blocking_employee_closes_open_tab_connection_within_35s_and_no_more_fragments(
        circle, employee, new_context, admin_page):
    """Сценарий 8, п. 8 (FR-627): сотрудника заблокировали — не позже чем через 35 с соединение открытой вкладки
    закрыто, фрагментов она больше не получает."""
    _connection_closes_and_no_more_fragments(employee, circle, new_context, admin_page, _end_by_block)


def test_f08_dismissing_employee_closes_open_tab_connection_within_35s_and_no_more_fragments(
        circle, employee, new_context, admin_page):
    """Сценарий 8, п. 8 (FR-627): сотрудника уволили — не позже чем через 35 с соединение открытой вкладки закрыто,
    фрагментов она больше не получает."""
    _connection_closes_and_no_more_fragments(employee, circle, new_context, admin_page, _end_by_dismiss)


def test_f08_newcomer_of_unit_with_50_old_and_3_recent_posts_has_feed_badge_3_and_old_posts_in_feed(
        circle, employee, new_context, admin_page):
    """Сценарий 8, п. 9 (FR-626): новичка принимают в отдел, где 50 записей отделу — 47 старше 30 дней (`age`) и 3
    новее; у пункта «Лента» — 3, а старые записи есть в его ленте."""
    c = circle.cast
    token = helpers_org.unique_name("н")[2:]
    account = employee(full_name=f"Новичков{token} Иван Иванович")
    page = open_feed(new_context(), account, live=False)
    _drain(page)  # записи круга, адресованные «Всем», к опыту не относятся
    assert badge(page) == 0
    helpers_org.open_structure(admin_page)
    unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Отдел новичка"), kind="department",
                                   parent_id=helpers_org.root_id(admin_page))
    writer = _writer_page(new_context, c)
    numbers = _unit_posts(writer, unit, [_word(f"Запись отделу {n}") for n in range(50)])
    old, recent = numbers[:47], numbers[47:]
    assert age(31, posts=old)["aged"] == 47
    helpers_org.add_members(admin_page, unit, [account.id], q=token, mode="concurrent")
    page.goto("/me/")
    assert badge(page) == 3, f"у новичка ожидалось 3, число {badge(page)}"
    page.goto("/")
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()
    shown = post_ids(page)
    assert set(recent) <= set(shown), "новые записи отдела не показаны новичку"
    assert set(old) & set(shown), "старых записей отдела нет в ленте новичка"


def test_f08_ordinary_and_important_posts_give_new_posts_2_and_click_puts_important_in_block_and_ordinary_on_top(
        circle, new_context):
    """Сценарий 8, п. 10 (FR-602, FR-627): публикуют обычную и важную записи, которые сотрудник видит — плашка
    «Новых записей: 2»; по нажатию важная встаёт в блок важных, обычная — наверх ленты (блок важных к этому моменту
    показан: до открытия ленты в ней уже есть важная запись)."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    earlier = _unit_post(writer, circle, _word("Важное, которое уже висит"), kind="important", term="week")
    watcher = open_feed(new_context(), c.accountant)
    assert earlier in important_ids(watcher), "блок важных не показан до опыта"
    ordinary = _unit_post(writer, circle, _word("Обычная запись"))
    important = _unit_post(writer, circle, _word("Новая важная запись"), kind="important", term="week")
    wait_banner(watcher, 2, timeout=WAIT_MS)
    _banner_link(watcher).click()
    expect(watcher.locator(f'#feed-important [data-post-id="{important}"]')).to_be_visible()
    expect(watcher.locator("#feed-list [data-post-id]").first).to_have_attribute("data-post-id", str(ordinary))
    expect(watcher.locator("#feed-new")).to_be_hidden()


def test_f08_edit_and_comment_of_shown_post_do_not_make_it_unread_or_raise_feed_badge(circle, new_context):
    """Сценарий 8, п. 11 (FR-626): запись уже показана — её правят и комментируют; непрочитанной она снова не
    становится, число у «Ленты» не растёт (ни сразу, ни после обновления страницы)."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Показанная запись"))
    watcher = open_feed(new_context(), c.accountant)
    expect(watcher.locator(f"#feed-post-{pid}")).to_be_visible()
    base = badge(watcher)
    new, comment_text = _word("Правка показанной"), _word("Комментарий к показанной")
    response = helpers_org.direct_post(writer, f"/feed/{pid}/edit/", {"text": new, "to": f"u{c.accounting_unit}"})
    assert response.status == 302
    colleague = open_card(new_context(), c.petrov, pid)
    add_comment(colleague, pid, comment_text)
    expect(watcher.locator(f"#feed-post-{pid}-body")).to_contain_text(new, timeout=WAIT_MS)  # кадры дошли
    expect(watcher.locator(f"#feed-post-{pid}-comments")).to_contain_text(comment_text, timeout=WAIT_MS)
    assert badge(watcher) == base, "число «Ленты» выросло от правки или комментария"
    expect(watcher.locator("#feed-new")).to_be_hidden()
    watcher.reload()
    watcher.wait_for_load_state()
    assert badge(watcher) == base, "после обновления страницы показанная запись снова непрочитанная"


def test_f08_new_posts_2_banner_click_lowers_feed_badge_by_2(circle, new_context):
    """Сценарий 8, п. 12 (FR-626, FR-627): плашка «Новых записей: 2» — по нажатию число у «Ленты» уменьшается на 2
    (сначала выросло на 2, затем вернулось к прежнему)."""
    c = circle.cast
    watcher = open_feed(new_context(), c.accountant)
    base = badge(watcher)
    writer = _writer_page(new_context, c)
    _unit_post(writer, circle, _word("Первая для числа"))
    _unit_post(writer, circle, _word("Вторая для числа"))
    wait_banner(watcher, 2, timeout=WAIT_MS)
    wait_badge(watcher, base + 2, timeout=WAIT_MS)
    _banner_link(watcher).click()
    wait_badge(watcher, base, timeout=WAIT_MS)


def test_f08_own_comment_in_same_tab_is_shown_once_after_frame_arrives(circle, new_context):
    """FR-627, решение 62 задач: свой комментарий в той же вкладке показан один раз и после того, как кадр о нём
    дошёл (повторная вставка кадром отменяется). Дошёл ли кадр до вкладки автора, видно по следующему кадру: кадры
    идут по соединению по порядку, поэтому после второго комментария коллеги первый уже обработан."""
    c = circle.cast
    writer = _writer_page(new_context, c)
    pid = _unit_post(writer, circle, _word("Запись для своего комментария"))
    author = open_feed(new_context(), c.accountant)
    expect(author.locator(f"#feed-post-{pid}")).to_be_visible()
    colleague = open_card(new_context(), c.petrov, pid)
    own = add_comment(author, pid, _word("Мой комментарий"))
    expect(colleague.locator(f"#c{own}")).to_be_visible(timeout=WAIT_MS)  # кадр о комментарии разослан
    later = add_comment(colleague, pid, _word("Ответ коллеги"))
    expect(author.locator(f"#c{later}")).to_be_visible(timeout=WAIT_MS)   # кадры дошли по порядку
    expect(author.locator(f"#c{own}")).to_have_count(1)
