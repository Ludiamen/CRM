"""T-7143: сценарий 4 — комментарии под записью ленты (FR-611, FR-623, FR-624, FR-629, FR-630, FR-631, FR-633, FR-642,
NFR-606).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 10, 12, 13, 14.4; helpers_feed.py):
- каждый тест заводит своих сотрудников с уникальными ФИО: автор записей — сотрудник с ролью «Писать всем»
  (`helpers_feed.make_role` + `employee`), остальные — «Сотрудник ИТ» без прав ленты; записи — «Всем», поэтому их видит
  каждый; сброса стенда и команд стенда в файле нет, общих настроек файл не меняет;
- страницы ленты — `helpers_feed.open_feed(new_context(), account)`: у каждого сотрудника свой контекст;
- уведомления читаются на `/notifications/` самого сотрудника, строки отбираются по названию вида (`[data-field=kind]`):
  у нового сотрудника бывают и другие уведомления; «уведомления нет» проверяется после положительного контроля;
- отказы формы комментария смотрятся по `[data-error="<поле>"][data-code="<код>"]` рядом с полем (10.1); у поля сняты
  `required`/`maxlength` и у формы включён `novalidate`, иначе браузер не отправил бы запрос, а предел — дело сервера;
- комментарии статей базы знаний — прежняя форма `form[data-form="kb-comment"]` (срез 005);
- ПДн в данных нет; ждать — `expect`, `expect_response`.
"""
import re
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org
from tests.e2e.helpers_feed import (
    POST_ALL, add_comment, check_360, make_role, open_card, open_feed, publish, try_upload, upload)

MOSCOW = ZoneInfo("Europe/Moscow")
TIME_SHOWN = re.compile(r"\d\d\.\d\d\.\d{4} \d\d:\d\d")
KIND_COMMENT = "Новый комментарий"
LIMIT = 4000
EMPTY_TEXT = "Напишите текст"
TOO_LONG_TEXT = "Предел: 4000 знаков"
FILES_LIMIT_TEXT = "У комментария уже 3 файла"


# --- Помощники файла ---------------------------------------------------------------------------------------------

def _fio(surname: str) -> str:
    return f"{surname}{secrets.token_hex(3)} Иван Иванович"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _writer(admin_page, employee):
    """Сотрудник с правом «Писать всем» (своя роль)."""
    return employee(role=make_role(admin_page, [POST_ALL]), full_name=_fio("Писарев"))


def _staff(employee, surname: str):
    return employee(full_name=_fio(surname))


def _word() -> str:
    return "т" + secrets.token_hex(4)


def _comments(page, post_id):
    return page.locator(f"#feed-post-{post_id}-comments [data-comment-id]")


def _ids(locator) -> list:
    return [int(v) for v in locator.evaluate_all("els => els.map(e => e.getAttribute('data-comment-id'))")]


def _raw_comment(page, post_id, text: str) -> None:
    """Отправляет текст формой комментария записи, не давая браузеру остановить отправку (см. шапку); ждёт ответ."""
    form = page.locator(f"#feed-post-{post_id} form[data-feed-comment-form]").first
    expect(form).to_be_visible()
    area = form.locator('textarea[name="text"]')
    area.evaluate("el => { el.removeAttribute('maxlength'); el.removeAttribute('required'); }")
    form.evaluate("el => el.setAttribute('novalidate', '')")
    area.fill(text)
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/comments/" in r.url):
        form.locator("button[type=submit]").first.click()


def _refusal(page, post_id, field: str, code: str, text: str) -> None:
    node = page.locator(f'#feed-post-{post_id} [data-error="{field}"][data-code="{code}"]').first
    expect(node).to_be_visible(timeout=10_000)
    expect(node).to_contain_text(text)


def _kind_rows(page, title: str):
    """Строки «Мои уведомления» вида `title` (страница открывается заново)."""
    page.goto("/notifications/")
    page.wait_for_load_state()
    return page.locator("ul[data-notifications] li[data-notification]").filter(
        has=page.locator('[data-field="kind"]', has_text=re.compile(rf"^\s*{re.escape(title)}\s*$")))


def _wait_kind_rows(page, title: str, count: int, timeout: float = 20.0):
    """Опрос списка: ждёт, пока строк вида `title` станет ровно `count`; возвращает локатор строк."""
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


def _files(tmp_path, count: int) -> list:
    paths = []
    for i in range(count):
        path = tmp_path / f"doc-{i}-{secrets.token_hex(2)}.txt"
        path.write_text(f"Файл {i} для комментария\n", encoding="utf-8")
        paths.append(path)
    return paths


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_f04_sent_comment_appears_at_bottom_of_list_with_author_name_and_time(
        admin_page, employee, new_context):
    """П. 1 (FR-623): сотрудник пишет комментарий и отправляет — комментарий внизу списка комментариев записи с его
    ФИО и временем по Москве; второй комментарий встаёт под первым; поле очищено."""
    writer = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    post_id = publish(open_feed(new_context(), writer), f"Запись про комментарии {_word()}")
    page = open_feed(new_context(), commenter)
    text = f"не сработало на Windows 11 {_word()}"
    first = add_comment(page, post_id, text)
    expect(page.locator(f'#feed-post-{post_id} form[data-feed-comment-form] textarea[name="text"]').first
           ).to_have_value("")
    second = add_comment(page, post_id, f"второй комментарий {_word()}")
    for reloaded in (False, True):
        if reloaded:
            page = open_card(new_context(), commenter, post_id)
        assert _ids(_comments(page, post_id)) == [first, second]
        row = page.locator(f"#c{first}")
        expect(row).to_contain_text(commenter.full_name)
        expect(row).to_contain_text(text)
        stamp = row.locator("time[data-at]").first
        shown = stamp.inner_text().strip()
        assert TIME_SHOWN.fullmatch(shown), f"вид времени: {shown!r}"
        now = datetime.now(MOSCOW)
        moment = datetime.strptime(shown, "%d.%m.%Y %H:%M").replace(tzinfo=MOSCOW)
        assert abs(now - moment) < timedelta(minutes=10), f"время комментария {shown} далеко от московского"
        stamped = datetime.fromisoformat(stamp.get_attribute("datetime"))
        assert stamped.utcoffset() == timedelta(hours=3), "время не по Москве"


def test_f04_feed_shows_last_three_of_8_comments_and_show_all_8_opens_all_by_time_flat_without_reload(
        admin_page, employee, new_context):
    """П. 2 (FR-623): у записи 8 комментариев — лента показывает последние три и ссылку «Показать все 8»; по нажатию
    все восемь по времени плоским списком, без перезагрузки страницы."""
    writer = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    reader = _staff(employee, "Читатель")
    post_id = publish(open_feed(new_context(), writer), f"Запись с восемью комментариями {_word()}")
    page_c = open_feed(new_context(), commenter)
    ids = [add_comment(page_c, post_id, f"комментарий {i} {_word()}") for i in range(1, 9)]
    page = open_feed(new_context(), reader)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    assert _ids(_comments(page, post_id)) == ids[-3:]
    link = page.locator(f"#feed-post-{post_id} a[data-feed-comments-all]")
    expect(link).to_have_count(1)
    expect(link).to_contain_text("Показать все 8")
    expect(page.locator(f"#feed-post-{post_id}-ccount")).to_contain_text("8")
    page.evaluate("() => { window.__f04_marker = 'same-page'; }")
    with page.expect_response(lambda r: r.request.method == "GET" and f"/feed/{post_id}/comments/" in r.url):
        link.click()
    expect(_comments(page, post_id)).to_have_count(8)
    assert _ids(_comments(page, post_id)) == ids, "все комментарии должны идти по времени"
    assert page.evaluate("() => window.__f04_marker") == "same-page", "страница перезагрузилась"
    expect(page.locator(f"#feed-post-{post_id}-comments [data-comment-id] [data-comment-id]")).to_have_count(0)


def test_f04_post_card_shows_all_comments(admin_page, employee, new_context):
    """П. 2 по карточке (FR-623, FR-604): в карточке записи видны все комментарии, ссылки «Показать все» нет."""
    writer = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    post_id = publish(open_feed(new_context(), writer), f"Запись для карточки {_word()}")
    page_c = open_feed(new_context(), commenter)
    ids = [add_comment(page_c, post_id, f"комментарий {i} {_word()}") for i in range(1, 6)]
    card = open_card(new_context(), writer, post_id)
    assert _ids(_comments(card, post_id)) == ids
    expect(card.locator("a[data-feed-comments-all]")).to_have_count(0)


def test_f04_reply_inserts_author_mention_into_comment_field_and_sent_comment_shows_author_name(
        admin_page, employee, new_context):
    """П. 3 (FR-611, FR-623): у комментария Петрова «Ответить» вставляет в поле комментария упоминание Петрова
    (`@ФИО`); отправленный ответ показан с ФИО отвечающего и именем Петрова упоминанием."""
    writer = _writer(admin_page, employee)
    petrov = _staff(employee, "Петров")
    replier = _staff(employee, "Отвечаев")
    post_id = publish(open_feed(new_context(), writer), f"Запись для ответа {_word()}")
    page_p = open_feed(new_context(), petrov)
    petrov_comment = add_comment(page_p, post_id, f"вопрос Петрова {_word()}")
    page = open_feed(new_context(), replier)
    reply = page.locator(f'#c{petrov_comment} button[data-action="reply"]')
    expect(reply).to_have_count(1)
    expect(reply).to_have_attribute("data-reply-id", str(petrov.id))
    expect(reply).to_have_attribute("data-reply-name", petrov.full_name)
    reply.click()
    area = page.locator(f'#feed-post-{post_id} form[data-feed-comment-form] textarea[name="text"]').first
    expect(area).to_have_value(re.compile(re.escape("@" + petrov.full_name)))
    area.press("End")
    area.press_sequentially(f" ответ {_word()}", delay=10)
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/comments/" in r.url) as info:
        page.locator(f"#feed-post-{post_id} form[data-feed-comment-form] button[type=submit]").first.click()
    assert 'data-code=' not in info.value.text(), "ответ отклонён"
    sent = _ids(_comments(page, post_id))[-1]
    row = page.locator(f"#c{sent}")
    expect(row).to_be_visible()
    expect(row).to_contain_text(replier.full_name)
    mention = row.locator(f'[data-mention="{petrov.id}"]')
    expect(mention).to_have_count(1)
    expect(mention).to_contain_text(petrov.full_name)


def test_f04_empty_or_over_4000_comment_refused_with_reason(admin_page, employee, new_context):
    """П. 4 (FR-623, FR-642): пустой комментарий и комментарий длиннее 4 000 знаков не сохраняются, у поля — причина
    «Напишите текст» и «Предел: 4000 знаков»; введённое остаётся; комментарий ровно в 4 000 знаков принимается."""
    writer = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    post_id = publish(open_feed(new_context(), writer), f"Запись для отказов {_word()}")
    page = open_feed(new_context(), commenter)
    expect(_comments(page, post_id)).to_have_count(0)
    for blank in ("", "   "):
        _raw_comment(page, post_id, blank)
        _refusal(page, post_id, "text", "empty_text", EMPTY_TEXT)
        expect(_comments(page, post_id)).to_have_count(0)
    _raw_comment(page, post_id, "а" * (LIMIT + 1))
    _refusal(page, post_id, "text", "too_long", TOO_LONG_TEXT)
    expect(_comments(page, post_id)).to_have_count(0)
    kept = page.locator(f'#feed-post-{post_id} form[data-feed-comment-form] textarea[name="text"]').first
    assert kept.evaluate("el => el.value.length") == LIMIT + 1, "введённый текст пропал после отказа"
    page = open_card(new_context(), commenter, post_id)
    expect(_comments(page, post_id)).to_have_count(0)
    _raw_comment(page, post_id, "а" * LIMIT)
    expect(_comments(page, post_id)).to_have_count(1, timeout=10_000)


def test_f04_four_files_on_comment_refused_with_reason(admin_page, employee, new_context, tmp_path):
    """П. 4 (FR-633, FR-642): к комментарию можно три файла; четвёртый отклонён с причиной «У комментария уже 3
    файла», три прежних остаются и уходят с комментарием."""
    writer = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    post_id = publish(open_feed(new_context(), writer), f"Запись для файлов {_word()}")
    page = open_feed(new_context(), commenter)
    paths = _files(tmp_path, 4)
    form = page.locator(f"#feed-post-{post_id} form[data-feed-comment-form]").first
    for path in paths[:3]:
        upload(page, path, scope="comment", post_id=post_id)
    expect(form.locator("[data-feed-file]")).to_have_count(3)
    codes = try_upload(page, paths[3], scope="comment", post_id=post_id)
    assert [code for _field, code in codes] == ["comment_files_limit"], codes
    node = page.locator(f'#feed-post-{post_id} [data-code="comment_files_limit"]').first
    expect(node).to_be_visible()
    expect(node).to_contain_text(FILES_LIMIT_TEXT)
    expect(form.locator("[data-feed-file]")).to_have_count(3)
    cid = add_comment(page, post_id, f"комментарий с тремя файлами {_word()}")
    expect(page.locator(f"#c{cid} [data-feed-file]")).to_have_count(3)


def test_f04_post_author_and_earlier_commenter_get_new_comment_when_third_employee_comments(
        admin_page, employee, new_context):
    """П. 5 (FR-629, FR-630): автор записи и сотрудник, ранее комментировавший её, получают «Новый комментарий», когда
    третий сотрудник оставляет комментарий; самому третьему уведомления нет."""
    author = _writer(admin_page, employee)
    second = _staff(employee, "Второв")
    third = _staff(employee, "Третьев")
    post_id = publish(open_feed(new_context(), author), f"Запись автора {_word()}")
    page_2 = open_feed(new_context(), second)
    add_comment(page_2, post_id, f"первый комментарий {_word()}")
    page_3 = open_feed(new_context(), third)
    add_comment(page_3, post_id, f"комментарий третьего {_word()}")
    rows_2 = _wait_kind_rows(page_2, KIND_COMMENT, 1)
    assert third.full_name in _row_text(rows_2.first), "второму пришёл не комментарий третьего"
    rows_author = _wait_kind_rows(open_card(new_context(), author, post_id), KIND_COMMENT, 1)
    assert "Новых комментариев: 2" in _row_text(rows_author.first), "у автора два комментария одной записью"
    assert _kind_rows(page_3, KIND_COMMENT).count() == 0, "автору комментария уведомление не приходит"


def test_f04_three_comments_in_row_give_one_new_comment_notification_per_post(
        admin_page, employee, new_context):
    """П. 5 (FR-629, FR-630): три комментария подряд к одной записи дают автору одно уведомление «Новый комментарий»
    на запись (склеено, число комментариев — 3)."""
    author = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    post_id = publish(open_feed(new_context(), author), f"Запись для склейки {_word()}")
    page_c = open_feed(new_context(), commenter)
    for i in range(3):
        add_comment(page_c, post_id, f"комментарий {i} {_word()}")
    rows = _wait_kind_rows(open_card(new_context(), author, post_id), KIND_COMMENT, 1)
    assert "Новых комментариев: 3" in _row_text(rows.first)
    assert rows.count() == 1


def test_f04_my_notifications_show_one_new_comment_notification_with_3_new_and_link_to_first_unread_comment(
        admin_page, employee, new_context):
    """П. 7 (FR-629, FR-630, FR-631): к записи пришли три комментария, пока уведомление не прочитано — в «Моих
    уведомлениях» одно «Новый комментарий» с числом новых 3; ссылка ведёт к первому из них."""
    author = _writer(admin_page, employee)
    commenter_b = _staff(employee, "Бетов")
    commenter_c = _staff(employee, "Цетов")
    post_id = publish(open_feed(new_context(), author), f"Запись Иванова {_word()}")
    page_b = open_feed(new_context(), commenter_b)
    page_c = open_feed(new_context(), commenter_c)
    first = add_comment(page_b, post_id, f"первый новый {_word()}")
    add_comment(page_c, post_id, f"второй новый {_word()}")
    add_comment(page_b, post_id, f"третий новый {_word()}")
    page = open_feed(new_context(), author)
    rows = _wait_kind_rows(page, KIND_COMMENT, 1)
    row = rows.first
    expect(row).to_have_attribute("data-unread", "1")
    assert "Новых комментариев: 3" in _row_text(row), _row_text(row)
    row.locator("a[data-open]").click()
    expect(page).to_have_url(re.compile(rf"/feed/{post_id}/#c{first}$"))
    expect(page.locator(f"#c{first}")).to_be_visible()


def test_f04_knowledge_article_comments_still_have_no_edit_mention_like_or_files(
        admin_page, employee, new_context):
    """П. 6 (FR-624): комментарии статей базы знаний прежние — без правки, упоминаний, отметок и файлов; адреса ленты
    такой комментарий не принимают (404)."""
    editor = helpers_kb.make_editor(employee, full_name=_fio("Редакторов"))
    reader = helpers_kb.make_reader(employee, full_name=_fio("Читаев"))
    rubric = helpers_org.unique_name("Рубрика")
    helpers_kb.create_rubric(admin_page, rubric)
    article_id = helpers_kb.create_draft(editor.page, title=helpers_kb.unique_title(), text="Текст статьи.",
                                         rubric=rubric)
    helpers_kb.publish_from_article_page(editor.page, article_id)
    page = reader.page
    marker = f"@[{editor.id}] комментарий статьи {_word()}"
    comment_id = helpers_kb.add_comment(page, article_id, marker)
    section = page.locator("section#comments[data-kb-comments]")
    row = section.locator(f'li[data-comment-id="{comment_id}"]')
    expect(row).to_have_count(1)
    for hook in ('button[data-action="comment-edit"]', "button[data-feed-like]", "[data-feed-likers]",
                 "[data-mention]", 'button[data-action="reply"]'):
        expect(section.locator(hook)).to_have_count(0)
    expect(section.locator('input[type="file"]')).to_have_count(0)
    area = section.locator('form[data-form="kb-comment"] textarea[name="text"]')
    expect(area).not_to_have_attribute("data-feed-picker", re.compile(r".*"))
    assert "@[" in row.inner_text(), "маркер упоминания в статье должен остаться обычным текстом"
    area.click()
    area.press_sequentially("@Ред", delay=30)
    page.wait_for_timeout(1_000)
    expect(page.locator("[data-feed-pick-list] [data-pick-value]")).to_have_count(0)
    for method, path, data in (("post", f"/feed/comments/{comment_id}/edit/", {"text": "правка"}),
                               ("post", f"/feed/comments/{comment_id}/like/", {}),
                               ("get", f"/feed/comments/{comment_id}/edit/", None),
                               ("get", f"/feed/comments/{comment_id}/likes/", None)):
        response = (helpers_org.direct_post(page, path, data) if method == "post"
                    else helpers_org.direct_get(page, path))
        assert response.status == 404, f"{method.upper()} {path}: {response.status}, ожидался 404"
    page.goto(f"/kb/{article_id}/")
    expect(page.locator(f'li[data-comment-id="{comment_id}"]')).to_contain_text("комментарий статьи")


def test_f04_post_card_with_comments_has_no_horizontal_scroll_at_360px(admin_page, employee, new_context):
    """NFR-606: запись с комментариями (длинное слово, длинная ссылка, ответ с упоминанием) на ширине 360 px — и в
    ленте, и в карточке — без горизонтальной прокрутки."""
    writer = _writer(admin_page, employee)
    commenter = _staff(employee, "Комментов")
    post_id = publish(open_feed(new_context(), writer), f"Запись для узкого экрана {_word()}")
    page_c = open_feed(new_context(), commenter)
    long_word = "ы" * 180
    long_link = "https://example.org/" + "a" * 120
    add_comment(page_c, post_id, f"{long_word}")
    add_comment(page_c, post_id, f"ссылка {long_link}")
    add_comment(page_c, post_id, f"ещё один комментарий {_word()}")
    feed = open_feed(new_context(), writer)
    expect(feed.locator(f"#feed-post-{post_id}")).to_be_visible()
    assert check_360(feed)
    card = open_card(new_context(), writer, post_id)
    expect(_comments(card, post_id)).to_have_count(3)
    assert check_360(card)
    assert helpers.no_horizontal_scroll(card)
