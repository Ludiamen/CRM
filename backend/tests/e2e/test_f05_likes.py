"""T-7144: сценарий 5 — «Мне нравится» под записью и комментарием (FR-625, FR-629, FR-630, FR-631, NFR-606).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 4.2, 7, 10.2, 12.3, 14.4; helpers_feed.py):
- каждый тест заводит своих сотрудников с уникальными ФИО: автор записи — сотрудник с ролью «Писать всем» (своя роль),
  остальные — «Сотрудник ИТ» без прав ленты; записи — «Всем»; сброса стенда и команд стенда (кроме `tick_mail` —
  «письма через 15 минут») в файле нет, общих настроек файл не меняет;
- страницы ленты — `helpers_feed.open_feed(new_context(), account)`: у каждого сотрудника свой контекст;
- уведомления читаются на `/notifications/` или в панели колокольчика самого сотрудника, строки отбираются по названию
  вида («Нравится», `[data-field=kind]`); «уведомления нет» и «одно уведомление» проверяются после положительного
  контроля (строка уже есть): уведомления создаются в запросе действия;
- письма: сначала запоминаются прежние письма (`helpers.mail_ids`), затем `tick_mail()` сдвигает сроки доставок на 15
  минут, и положительный контроль — письмо о новом комментарии автору записи (у него вид с почтой); у «Нравится»
  внешних каналов нет (4.2): в «Моих уведомлениях» ячейки почты и мессенджеров без флажка (`data-available="0"`);
- ПДн в данных нет; ждать — `expect`, `expect_response`, опрос списка.
"""
import re
import secrets
import time

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_feed import (
    POST_ALL, add_comment, check_360, feed_mail, like, like_comment, make_role, no_feed_mail, open_card, open_feed,
    publish, tick_mail)

KIND_LIKE = "Нравится"
LIKE_ROW = "feed.like"


# --- Помощники файла ---------------------------------------------------------------------------------------------

def _fio(surname: str) -> str:
    return f"{surname}{secrets.token_hex(3)} Иван Иванович"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _word() -> str:
    return "т" + secrets.token_hex(4)


def _writer(admin_page, employee, surname: str = "Писарев"):
    """Сотрудник с правом «Писать всем» (своя роль)."""
    return employee(role=make_role(admin_page, [POST_ALL]), full_name=_fio(surname))


def _staff(employee, surname: str):
    return employee(full_name=_fio(surname))


def _post_likers(page, post_id):
    """Часть записи со строкой отметивших (`#feed-post-<id>-likers`, 12.3)."""
    return page.locator(f"#feed-post-{post_id}-likers")


def _pressed(page, post_id) -> str:
    return page.locator(f"#feed-post-{post_id} button[data-feed-like]").first.get_attribute("aria-pressed")


def _kind_rows(page, title: str):
    """Строки «Мои уведомления» вида `title` (страница открывается заново)."""
    page.goto("/notifications/")
    page.wait_for_load_state()
    return page.locator("ul[data-notifications] li[data-notification]").filter(
        has=page.locator('[data-field="kind"]', has_text=re.compile(rf"^\s*{re.escape(title)}\s*$")))


def _wait_kind_rows(page, title: str, count: int, timeout: float = 20.0):
    end = time.monotonic() + timeout
    while True:
        rows = _kind_rows(page, title)
        if rows.count() == count:
            return rows
        if time.monotonic() >= end:
            raise AssertionError(f"строк «{title}»: {rows.count()}, ожидалось {count}")
        page.wait_for_timeout(500)


def _row_text(row) -> str:
    return _norm(row.locator('[data-field="text"]').inner_text())


def _like_by(new_context, account, post_id) -> None:
    """Сотрудник открывает ленту и отмечает запись «Нравится»; ждёт, что отметка стоит."""
    page = open_feed(new_context(), account)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    assert like(page, post_id) is True


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_f05_like_click_sets_mark_with_own_name_and_second_click_removes_it(admin_page, employee, new_context):
    """П. 1 (FR-625): запись без отметок — нажатие «Нравится» ставит отметку, рядом «Нравится: <ФИО нажавшего>»;
    повторное нажатие снимает отметку (в том числе после перезагрузки)."""
    writer = _writer(admin_page, employee)
    liker = _staff(employee, "Лайков")
    post_id = publish(open_feed(new_context(), writer), f"Запись для отметок {_word()}")
    page = open_feed(new_context(), liker)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    expect(page.locator(f"#feed-post-{post_id} button[data-feed-like]").first).to_have_attribute("aria-pressed", "false")
    assert like(page, post_id) is True
    expect(page.locator(f"#feed-post-{post_id} button[data-feed-like]").first).to_have_attribute("aria-pressed", "true")
    expect(_post_likers(page, post_id)).to_contain_text(f"Нравится: {liker.full_name}")
    page = open_card(new_context(), liker, post_id)
    assert _pressed(page, post_id) == "true", "отметка пропала после перезагрузки"
    expect(_post_likers(page, post_id)).to_contain_text(f"Нравится: {liker.full_name}")
    assert like(page, post_id) is False
    expect(page.locator(f"#feed-post-{post_id} button[data-feed-like]").first).to_have_attribute("aria-pressed", "false")
    expect(_post_likers(page, post_id)).not_to_contain_text(liker.full_name)
    page = open_card(new_context(), liker, post_id)
    assert _pressed(page, post_id) == "false", "снятая отметка вернулась после перезагрузки"
    expect(_post_likers(page, post_id)).not_to_contain_text(liker.full_name)


def test_f05_five_likers_line_shows_two_latest_names_and_3_more_and_full_list_on_click(
        admin_page, employee, new_context):
    """П. 2 (FR-625): запись отметили пять человек — «Нравится: <ФИО последнего>, <ФИО предпоследнего> и ещё 3»; по
    нажатию на «и ещё 3» — полный список из пяти."""
    writer = _writer(admin_page, employee)
    likers = [_staff(employee, f"Лайков{i}") for i in range(1, 6)]
    page_w = open_feed(new_context(), writer)
    post_id = publish(page_w, f"Запись с пятью отметками {_word()}")
    for liker in likers:
        _like_by(new_context, liker, post_id)
    page = open_feed(new_context(), writer)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    line = _post_likers(page, post_id)
    expect(line).to_contain_text(f"Нравится: {likers[4].full_name}, {likers[3].full_name} и ещё 3")
    for older in likers[:3]:
        expect(line).not_to_contain_text(older.full_name)
    more = line.locator("a", has_text="и ещё 3")
    expect(more).to_have_count(1)
    with page.expect_response(lambda r: r.request.method == "GET" and f"/feed/{post_id}/likes/" in r.url):
        more.click()
    full = page.locator('ul[data-feed-list="likers"]')
    expect(full).to_be_visible()
    expect(full.locator("li")).to_have_count(5)
    for liker in likers:
        expect(full).to_contain_text(liker.full_name)


def test_f05_two_likes_of_petrov_comment_give_him_one_portal_notification_without_letter_or_messenger_message(
        admin_page, employee, new_context, mailpit):
    """П. 3 (FR-629, FR-631): комментарий Петрова отметили два сотрудника — у Петрова одно (склеенное) уведомление на
    портале; письма нет (после сдвига сроков на 15 минут), у вида «Нравится» нет ячеек почты и мессенджеров."""
    writer = _writer(admin_page, employee)
    petrov = _staff(employee, "Петров")
    first = _staff(employee, "Первов")
    second = _staff(employee, "Второв")
    post_id = publish(open_feed(new_context(), writer), f"Запись для комментария Петрова {_word()}")
    page_p = open_feed(new_context(), petrov)
    comment_id = add_comment(page_p, post_id, f"комментарий Петрова {_word()}")
    for liker in (first, second):
        page = open_feed(new_context(), liker)
        expect(page.locator(f"#c{comment_id}")).to_be_visible()
        assert like_comment(page, comment_id) is True
    rows = _wait_kind_rows(page_p, KIND_LIKE, 1)
    text = _row_text(rows.first)
    assert f"Нравится {second.full_name} (и ещё 1)" in text, text
    assert rows.count() == 1
    seen_petrov, seen_writer = helpers.mail_ids(mailpit, petrov.email), helpers.mail_ids(mailpit, writer.email)
    tick_mail()
    feed_mail(mailpit, writer.email, seen=seen_writer)  # положительный контроль: письмо «Новый комментарий» автору записи
    assert no_feed_mail(mailpit, petrov.email, seen=seen_petrov), "об отметке Петрову пришло письмо"
    page_p.goto("/me/notifications/")
    cells = page_p.locator(f'tr[data-notify-kind="{LIKE_ROW}"] td[data-channel]')
    expect(cells.first).to_be_attached()
    found = cells.evaluate_all(
        "els => els.map(e => [e.getAttribute('data-channel'), e.getAttribute('data-available'), "
        "e.querySelectorAll('input').length])")
    external = [item for item in found if item[0] != "portal"]
    assert {item[0] for item in external} >= {"email"}, found
    assert all(item[1] == "0" and item[2] == 0 for item in external), f"у «Нравится» есть внешний канал: {found}"


def test_f05_author_liking_own_post_gets_no_notification(admin_page, employee, new_context):
    """П. 4 (FR-630): автор отмечает свою запись — уведомления ему нет; отметка другого сотрудника (контроль) даёт
    ровно одно уведомление с именем другого, без «и ещё»."""
    writer = _writer(admin_page, employee)
    other = _staff(employee, "Другов")
    page_w = open_feed(new_context(), writer)
    post_id = publish(page_w, f"Запись, которую отметит сам автор {_word()}")
    assert like(page_w, post_id) is True
    expect(_post_likers(page_w, post_id)).to_contain_text(f"Нравится: {writer.full_name}")
    _like_by(new_context, other, post_id)
    rows = _wait_kind_rows(page_w, KIND_LIKE, 1)
    text = _row_text(rows.first)
    assert f"Нравится {other.full_name}" in text, text
    assert "и ещё" not in text, f"отметка автора попала в уведомление: {text}"
    assert writer.full_name not in text


def test_f05_three_likes_give_one_like_notification_with_last_liker_kozlov_and_2_more_linking_to_post(
        admin_page, employee, new_context):
    """П. 5 (FR-629, FR-631): запись Петрова отметили Иванов, Сидоров и Козлов, уведомление не прочитано — в колокольчике
    у Петрова одно «Нравится» с последним отметившим, Козловым, и «и ещё 2»; ссылка ведёт к записи."""
    petrov = _writer(admin_page, employee, "Петров")
    ivanov = _staff(employee, "Иванов")
    sidorov = _staff(employee, "Сидоров")
    kozlov = _staff(employee, "Козлов")
    page = open_feed(new_context(), petrov)
    post_id = publish(page, f"Запись Петрова {_word()}")
    for liker in (ivanov, sidorov, kozlov):
        _like_by(new_context, liker, post_id)
    page = open_feed(new_context(), petrov)
    page.locator("button[data-bell-toggle]").click()
    panel = page.locator("[data-bell-panel] [data-bell-list]")
    expect(panel).to_be_visible()
    rows = panel.locator("li[data-notification]").filter(has_text=re.compile(r"^\s*Нравится "))
    expect(rows).to_have_count(1)
    text = _norm(rows.first.inner_text())
    assert f"Нравится {kozlov.full_name} (и ещё 2)" in text, text
    assert ivanov.full_name not in text and sidorov.full_name not in text
    rows.first.locator("a[data-open]").click()
    expect(page).to_have_url(re.compile(rf"/feed/{post_id}/(#.*)?$"))
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()


def test_f05_likers_list_has_no_horizontal_scroll_at_360px(admin_page, employee, new_context):
    """NFR-606: строка отметивших и полный список (длинные ФИО) на ширине 360 px — без горизонтальной прокрутки, в
    ленте и в карточке."""
    writer = _writer(admin_page, employee)
    likers = [employee(full_name=f"Очень{'длиннофамильный' * 2}{secrets.token_hex(2)}{i} Иван Иванович")
              for i in range(1, 5)]
    page_w = open_feed(new_context(), writer)
    post_id = publish(page_w, f"Запись для узкого экрана {_word()}")
    for liker in likers:
        _like_by(new_context, liker, post_id)
    page = open_feed(new_context(), writer)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    more = _post_likers(page, post_id).locator("a", has_text="и ещё 2")
    expect(more).to_have_count(1)
    more.click()
    expect(page.locator('ul[data-feed-list="likers"] li')).to_have_count(4)
    assert check_360(page)
    card = open_card(new_context(), writer, post_id)
    _post_likers(card, post_id).locator("a", has_text="и ещё 2").click()
    expect(card.locator('ul[data-feed-list="likers"] li')).to_have_count(4)
    assert check_360(card)
