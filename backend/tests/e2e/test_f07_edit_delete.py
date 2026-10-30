"""T-7146: сценарий 7 — автор правит и удаляет, модератор удаляет чужое (FR-606, FR-611, FR-620, FR-621, FR-622,
FR-639).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 8, 10, 12, 13, 14.4; решения 8, 18, 36
задач):
- люди и узлы — `helpers_feed.feed_cast` (писатель с «Писать всем», модератор с «Модерировать ленту», сотрудник без прав,
  узлы, Петров, Сидоров); круг собирается один раз на браузер (фикстура `circle`) и дальше берётся по сохранённым сессиям
  (`Account.storage_state`): девять учёток с мастером активации на каждый из двенадцати тестов — это часы прохода;
- каждый тест публикует свои записи, адресованные названным людям (не «Всем»), чтобы не менять число «Ленты» соседям;
- вход и страницы — `helpers_feed.open_feed`, `open_card`; публикация, комментарии, «Нравится» — помощники приёмки;
- правка записи и комментария: страницы `[data-feed-page="edit"]` и `[data-feed-page="comment-edit"]` (CONTRACT-007,
  12.1); поля и кнопка сохранения берутся по общим признакам (`textarea[name="text"]`, `button[type=submit]`) — другого
  в контракте нет (вопрос в отчёте T-7146);
- подтверждение удаления записи — `dialog[data-feed-confirm][open]` с текстом «Удалить запись вместе с комментариями?»
  (12.3, 13.3), кнопка подтверждения — `button[type=submit]` диалога (вопрос в отчёте T-7146);
- запрос в обход страницы — `helpers_org.direct_post` / `direct_get` от имени страницы сотрудника (с токеном CSRF, без
  переходов по редиректам): 403 значит отказ по праву, а не по CSRF (решение 18 задач: запись видна, действие не
  разрешено — 403);
- «ответ как у несуществующей» сравнивается в пределах одного сотрудника: статус и текст `main#content` страницы
  `/feed/<номер>/` и страницы с заведомо отсутствующим номером, каждый раз после нейтральной `/me/`;
- журнал читает администратор круга (`helpers_org.audit_rows`, `audit_sides`, `helpers.audit_actions`); текст записи
  и комментария в журнале не ищется только по названию: в строках нет уникального слова теста.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed, helpers_org
from tests.e2e.helpers_feed import (
    add_comment, like, like_comment, open_card, open_feed, publish)

MISSING = 2_000_000_000
CONFIRM_TEXT = "Удалить запись вместе с комментариями?"
EDIT_ROOT = '[data-feed-page="edit"]'
COMMENT_EDIT_ROOT = '[data-feed-page="comment-edit"]'
MOSCOW = timezone(timedelta(hours=3))
DATE_TEXT = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")
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


def _aware(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=MOSCOW)


def _answer_of(page, path: str) -> tuple:
    """Статус и текст области содержимого страницы `path` после нейтральной страницы."""
    page.goto("/me/")
    response = page.goto(path)
    return response.status, page.locator("main#content").inner_text()


def _assert_missing_like_absent(page, path: str) -> None:
    got = _answer_of(page, path)
    absent = _answer_of(page, f"/feed/{MISSING}/")
    assert got[0] == 404, f"{path}: ожидался 404, получен {got[0]}"
    assert got == absent, f"{path}: ответ отличается от ответа на несуществующий номер: {got!r} и {absent!r}"


def _post_to_people(new_context, author, text: str, *people):
    """Автор публикует запись названным людям формой; возвращает страницу автора и номер записи."""
    page = open_feed(new_context(), author, live=False)
    pid = publish(page, text, to=[("person", p.full_name) for p in people])
    return page, pid


def _open_edit_form(page, post_id):
    page.goto(f"/feed/{post_id}/edit/")
    root = page.locator(EDIT_ROOT)
    expect(root).to_be_visible()
    return root.locator("form:has(textarea[name=text])").first


def _save_edit(page, post_id, form) -> None:
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()


def _edit_text(page, post_id, text: str) -> None:
    form = _open_edit_form(page, post_id)
    form.locator('textarea[name="text"]').fill(text)
    _save_edit(page, post_id, form)


def _delete_post_through_card(page, post_id) -> None:
    """Карточка записи → «Удалить» → подтверждение диалога; ждёт ответ на удаление."""
    page.goto(f"/feed/{post_id}/")
    post = page.locator(f"#feed-post-{post_id}")
    expect(post).to_be_visible()
    post.locator('button[data-action="post-delete"]').first.click()
    dialog = page.locator("dialog[data-feed-confirm][open]")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text(CONFIRM_TEXT)
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/delete/" in r.url):
        dialog.locator("button[type=submit]").first.click()
    page.wait_for_load_state()


def _delete_comment_through_card(page, post_id, comment_id) -> None:
    """Карточка → меню комментария → «Удалить»; если портал просит подтверждение (диалог), подтверждает."""
    page.goto(f"/feed/{post_id}/")
    comment = page.locator(f"#c{comment_id}")
    expect(comment).to_be_visible()
    comment.locator('button[data-action="comment-delete"]').first.click()
    dialog = page.locator("dialog[data-feed-confirm][open]")
    try:
        expect(dialog).to_be_visible(timeout=2_000)
        dialog.locator("button[type=submit]").first.click()
    except AssertionError:
        pass  # подтверждения у комментария нет: удаление ушло по нажатию
    expect(page.locator(f"#c{comment_id}")).to_have_count(0)


def _refused(response) -> bool:
    return response.status == 403


# --- Тесты --------------------------------------------------------------------------------------------------------

def test_f07_author_edits_text_and_post_shows_new_text_and_edited_mark_with_time(circle, new_context):
    """Сценарий 7, п. 1 (FR-620): автор меняет текст и сохраняет — текст обновлён, у записи пометка «изменено» со
    временем правки (время близко к текущему); у записи, которую не правили, пометки нет."""
    c = circle.cast
    old, new = _word("Первый текст"), _word("Второй текст")
    page, pid = _post_to_people(new_context, c.writer, old, c.petrov)
    page.goto(f"/feed/{pid}/")
    expect(page.locator(f"#feed-post-{pid}-body")).to_contain_text(old)
    expect(page.locator(f"#feed-post-{pid} [data-feed-edited]")).to_have_count(0)
    _edit_text(page, pid, new)
    page.goto(f"/feed/{pid}/")
    body = page.locator(f"#feed-post-{pid}-body")
    expect(body).to_contain_text(new)
    expect(body).not_to_contain_text(old)
    mark = page.locator(f"#feed-post-{pid} [data-feed-edited]").first
    expect(mark).to_contain_text("изменено")
    stamp = mark.locator("time[data-at]").first
    expect(stamp).to_have_text(DATE_TEXT)
    moment = _aware(stamp.get_attribute("datetime"))
    assert abs((datetime.now(timezone.utc) - moment).total_seconds()) < 600, f"время правки {moment} далеко от текущего"
    reader = open_card(new_context(), c.petrov, pid)  # адресат видит новый текст и пометку
    expect(reader.locator(f"#feed-post-{pid}-body")).to_contain_text(new)
    expect(reader.locator(f"#feed-post-{pid} [data-feed-edited]").first).to_contain_text("изменено")


def test_f07_person_added_to_unit_post_by_edit_sees_post(circle, new_context):
    """Сценарий 7, п. 2, первая часть (FR-620): запись подразделению, автор при правке добавляет человека — тот,
    кому запись до правки была недоступна (ответ как у несуществующей), видит её после правки."""
    c = circle.cast
    text = _word("Запись отделу")
    page = open_feed(new_context(), c.writer, live=False)
    pid = publish(page, text, to=[("unit", circle.names[c.accounting_unit])])
    outsider = open_feed(new_context(), c.it_member, live=False)  # «Отдел ИТ», не «Бухгалтерия»
    _assert_missing_like_absent(outsider, f"/feed/{pid}/")
    form = _open_edit_form(page, pid)
    pills = form.locator("[data-to-pill]")
    before = pills.count()
    field = form.locator('input[data-feed-picker="to"]')
    field.fill("")
    field.press_sequentially(c.it_member.full_name.split()[0], delay=30)
    option = page.locator(f'[data-feed-pick-list] [data-pick-label="{c.it_member.full_name}"]').first
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    expect(pills).to_have_count(before + 1)
    _save_edit(page, pid, form)
    outsider.goto(f"/feed/{pid}/")
    expect(outsider.locator(f"#feed-post-{pid}-body")).to_contain_text(text)
    outsider.goto("/")
    expect(outsider.locator(f"#feed-post-{pid}").first).to_be_visible()


def test_f07_saved_recipients_have_no_remove_cross_and_direct_removal_request_refused(circle, new_context):
    """Сценарий 7, п. 2, вторая часть (FR-620): у сохранённых адресатов кнопки снятия нет; запрос правки в обход
    страницы, который убирает уже стоящего адресата, отклонён (200 с кодом `only_add_recipients` у поля «Кому»), и
    убранный адресат по-прежнему видит запись."""
    c = circle.cast
    text = _word("Двум адресатам")
    page, pid = _post_to_people(new_context, c.writer, text, c.petrov, c.sidorov)
    form = _open_edit_form(page, pid)
    saved = form.locator("[data-to-pill][data-saved]")
    expect(saved).to_have_count(2)
    expect(saved.locator('button[data-action="to-remove"]')).to_have_count(0)
    response = helpers_org.direct_post(page, f"/feed/{pid}/edit/", {"text": text, "to": f"p{c.petrov.id}"})
    assert response.status == 200, f"снятие адресата: ожидался отказ 200, получен {response.status}"
    assert 'data-code="only_add_recipients"' in response.text(), "в ответе нет кода only_add_recipients"
    assert "Адресатов можно только добавить" in response.text()
    removed = open_card(new_context(), c.sidorov, pid)
    expect(removed.locator(f"#feed-post-{pid}-body")).to_contain_text(text)


def test_f07_employee_without_moderate_right_sees_no_edit_or_delete_on_others_post_and_direct_requests_refused(
        circle, new_context):
    """Сценарий 7, п. 3 (FR-620, FR-621): чужая запись, сотрудник без права «Модерировать ленту» — «Править» и
    «Удалить» ему не показаны, правка и удаление запросом в обход страницы отклонены (403), запись цела."""
    c = circle.cast
    text = _word("Чужая запись")
    page, pid = _post_to_people(new_context, c.writer, text, c.plain)
    reader = open_card(new_context(), c.plain, pid)
    post = reader.locator(f"#feed-post-{pid}")
    expect(post).to_be_visible()
    expect(post.locator('button[data-action="post-edit"], [data-action="post-edit"]')).to_have_count(0)
    expect(post.locator('button[data-action="post-delete"]')).to_have_count(0)
    assert _refused(helpers_org.direct_get(reader, f"/feed/{pid}/edit/")), "форма правки чужой записи не отказана"
    assert _refused(helpers_org.direct_post(reader, f"/feed/{pid}/edit/", {"text": "подмена", "to": f"p{c.plain.id}"}))
    assert _refused(helpers_org.direct_post(reader, f"/feed/{pid}/delete/"))
    page.goto(f"/feed/{pid}/")
    expect(page.locator(f"#feed-post-{pid}-body")).to_contain_text(text)


def test_f07_moderator_sees_delete_but_no_edit_on_others_post_and_direct_edit_refused(circle, new_context):
    """Сценарий 7, п. 3 и FR-620 («чужую запись не правит никто, в том числе модератор»): модератору, который видит
    чужую запись, показано «Удалить», «Править» нет; правка запросом в обход страницы отклонена (403)."""
    c = circle.cast
    text = _word("Запись модератору")
    page, pid = _post_to_people(new_context, c.writer, text, c.moderator)
    moderator = open_card(new_context(), c.moderator, pid)
    post = moderator.locator(f"#feed-post-{pid}")
    expect(post).to_be_visible()
    expect(post.locator('button[data-action="post-delete"]')).to_have_count(1)
    expect(post.locator('[data-action="post-edit"]')).to_have_count(0)
    assert _refused(helpers_org.direct_get(moderator, f"/feed/{pid}/edit/"))
    assert _refused(helpers_org.direct_post(moderator, f"/feed/{pid}/edit/",
                                            {"text": "правка модератора", "to": f"p{c.moderator.id}"}))
    page.goto(f"/feed/{pid}/")
    expect(page.locator(f"#feed-post-{pid}-body")).to_contain_text(text)


def test_f07_author_delete_after_confirm_removes_post_with_comments_files_and_likes_and_link_answers_like_missing(
        circle, new_context, tmp_path):
    """Сценарий 7, п. 4 (FR-621): своя запись с комментарием, файлом и отметками «Нравится»; автор нажимает «Удалить»
    и подтверждает «Удалить запись вместе с комментариями?» — запись исчезает; ссылка на неё, её комментарии, отметки
    и файл отвечают как несуществующие."""
    c = circle.cast
    text = _word("Запись под удаление")
    attachment = tmp_path / "note.txt"
    attachment.write_text("файл записи под удаление")
    author = open_feed(new_context(), c.writer, live=False)
    pid = publish(author, text, to=[("person", c.petrov.full_name)], files=[attachment])
    author.goto(f"/feed/{pid}/")
    file_id = author.locator(f"#feed-post-{pid}-files [data-feed-file]").first.get_attribute("data-feed-file")
    reader = open_card(new_context(), c.petrov, pid)
    cid = add_comment(reader, pid, _word("Комментарий"))
    assert like(reader, pid) is True
    assert like_comment(reader, cid) is True
    _delete_post_through_card(author, pid)
    _assert_missing_like_absent(author, f"/feed/{pid}/")
    for path in (f"/feed/{pid}/comments/", f"/feed/{pid}/likes/", f"/feed/comments/{cid}/likes/",
                 f"/feed/files/{file_id}/"):
        assert helpers_org.direct_get(author, path).status == 404, f"{path}: после удаления записи не 404"
    author.goto("/")
    expect(author.locator(f"#feed-post-{pid}")).to_have_count(0)
    _assert_missing_like_absent(reader, f"/feed/{pid}/")  # адресат: тот же ответ


def test_f07_author_edit_and_delete_of_own_post_leave_no_journal_entries(circle, new_context, admin_page):
    """Сценарий 7, п. 6 в части записи, FR-639: правка и удаление автором своей записи в журнал не пишутся."""
    c = circle.cast
    page, pid = _post_to_people(new_context, c.writer, _word("Своя запись"), c.petrov)
    _edit_text(page, pid, _word("Своя запись, правка"))
    _delete_post_through_card(page, pid)
    assert helpers_org.audit_rows(admin_page, "feed.post_deleted", pid) == []
    actions = helpers.audit_actions(admin_page, f"object_id={pid}")
    assert not [a for a in actions if a and a.startswith("feed.")], actions


def test_f07_moderator_deletes_others_post_and_journal_shows_post_deleted_with_author_time_and_deleter_without_text(
        circle, new_context, admin_page):
    """Сценарий 7, п. 5 (FR-621, FR-639): модератор удаляет чужую запись — запись удалена, в журнале «удалена запись
    ленты» (код `feed.post_deleted`): автор записи, время публикации, кто удалил, без текста."""
    c = circle.cast
    text = _word("Запись под модератора")
    page, pid = _post_to_people(new_context, c.writer, text, c.moderator, c.petrov)
    moderator = open_card(new_context(), c.moderator, pid)
    published = moderator.locator(f"#feed-post-{pid} time[data-at]").first.inner_text().strip()
    assert DATE_TEXT.fullmatch(published), published
    _delete_post_through_card(moderator, pid)
    _assert_missing_like_absent(moderator, f"/feed/{pid}/")
    _assert_missing_like_absent(page, f"/feed/{pid}/")
    rows = helpers_org.audit_rows(admin_page, "feed.post_deleted", pid)
    assert len(rows) == 1, rows
    row = rows[0]
    assert c.moderator.full_name in row, f"в строке журнала нет того, кто удалил: {row!r}"
    assert c.writer.full_name in row, f"в строке журнала нет автора записи: {row!r}"
    assert published in row, f"в строке журнала нет времени публикации {published}: {row!r}"
    assert text not in row, "в журнале есть текст записи"
    before, after = helpers_org.audit_sides(admin_page, "feed.post_deleted", pid)[0]
    assert c.writer.full_name in before and published in before, (before, after)
    assert text not in before and text not in after


def test_f07_moderator_deletes_others_comment_and_journal_entry_has_no_text(circle, new_context, admin_page):
    """Сценарий 7, п. 6, первая часть (FR-622, FR-639): модератор, видящий запись, удаляет чужой комментарий —
    комментарий удалён, в журнале запись `feed.comment_deleted` с автором, временем и номером записи, без текста."""
    c = circle.cast
    page, pid = _post_to_people(new_context, c.writer, _word("Запись с комментарием"), c.moderator, c.petrov)
    reader = open_card(new_context(), c.petrov, pid)
    comment_text = _word("Чужой комментарий")
    cid = add_comment(reader, pid, comment_text)
    moderator = open_card(new_context(), c.moderator, pid)
    _delete_comment_through_card(moderator, pid, cid)
    reader.goto(f"/feed/{pid}/")
    expect(reader.locator(f"#c{cid}")).to_have_count(0)
    rows = helpers_org.audit_rows(admin_page, "feed.comment_deleted", cid)
    assert len(rows) == 1, rows
    assert c.moderator.full_name in rows[0] and c.petrov.full_name in rows[0], rows[0]
    assert str(pid) in rows[0], f"в строке журнала нет номера записи {pid}: {rows[0]!r}"
    assert comment_text not in rows[0], "в журнале есть текст комментария"
    before, after = helpers_org.audit_sides(admin_page, "feed.comment_deleted", cid)[0]
    assert comment_text not in before and comment_text not in after


def test_f07_comment_author_edits_with_edited_mark_and_deletes_own_comment_without_journal_entries(
        circle, new_context, admin_page):
    """Сценарий 7, п. 6, вторая часть (FR-622, FR-639): автор комментария правит его (пометка «изменено») и удаляет
    сам — в журнал это не пишется."""
    c = circle.cast
    page, pid = _post_to_people(new_context, c.writer, _word("Запись для комментария"), c.petrov)
    author = open_card(new_context(), c.petrov, pid)
    first, second = _word("Первый комментарий"), _word("Правка комментария")
    cid = add_comment(author, pid, first)
    expect(author.locator(f"#c{cid} [data-feed-edited]")).to_have_count(0)
    author.locator(f'#c{cid} button[data-action="comment-edit"]').first.click()
    root = author.locator(COMMENT_EDIT_ROOT)
    expect(root).to_be_visible()
    form = root.locator("form:has(textarea[name=text])").first
    form.locator('textarea[name="text"]').fill(second)
    with author.expect_response(lambda r: r.request.method == "POST" and f"/feed/comments/{cid}/edit/" in r.url):
        form.locator("button[type=submit]").first.click()
    author.wait_for_load_state()
    author.goto(f"/feed/{pid}/")
    comment = author.locator(f"#c{cid}")
    expect(comment).to_contain_text(second)
    expect(comment).not_to_contain_text(first)
    expect(comment.locator("[data-feed-edited]").first).to_contain_text("изменено")
    _delete_comment_through_card(author, pid, cid)
    assert helpers_org.audit_rows(admin_page, "feed.comment_deleted", cid) == []
    actions = helpers.audit_actions(admin_page, f"object_id={cid}")
    assert not [a for a in actions if a and a.startswith("feed.")], actions


def test_f07_post_author_sees_no_delete_on_others_comment_and_direct_request_refused(circle, new_context):
    """FR-622: автор записи чужие комментарии к ней не удаляет — кнопки «Удалить» у чужого комментария нет, запрос в
    обход страницы отклонён (403), комментарий на месте."""
    c = circle.cast
    page, pid = _post_to_people(new_context, c.writer, _word("Запись автора"), c.petrov)
    reader = open_card(new_context(), c.petrov, pid)
    comment_text = _word("Комментарий коллеги")
    cid = add_comment(reader, pid, comment_text)
    page.goto(f"/feed/{pid}/")
    comment = page.locator(f"#c{cid}")
    expect(comment).to_contain_text(comment_text)
    expect(comment.locator('button[data-action="comment-delete"]')).to_have_count(0)
    assert _refused(helpers_org.direct_post(page, f"/feed/comments/{cid}/delete/"))
    page.goto(f"/feed/{pid}/")
    expect(page.locator(f"#c{cid}")).to_contain_text(comment_text)


def test_f07_moderator_not_addressed_gets_missing_answer_and_after_mention_in_comment_sees_and_deletes_post(
        circle, new_context):
    """Сценарий 7, п. 7 (FR-606, FR-611, FR-621): запись двум сотрудникам, модератора среди адресатов нет — его
    ответ как у несуществующей записи; после упоминания в комментарии он видит запись и удаляет её."""
    c = circle.cast
    text = _word("Запись двоим")
    page, pid = _post_to_people(new_context, c.writer, text, c.petrov, c.accountant)
    moderator = open_feed(new_context(), c.moderator, live=False)
    _assert_missing_like_absent(moderator, f"/feed/{pid}/")
    reader = open_card(new_context(), c.petrov, pid)
    add_comment(reader, pid, _word("Коллеги, посмотрите"), mentions=[c.moderator.full_name])
    moderator.goto(f"/feed/{pid}/")
    expect(moderator.locator(f"#feed-post-{pid}-body")).to_contain_text(text)
    _delete_post_through_card(moderator, pid)
    _assert_missing_like_absent(moderator, f"/feed/{pid}/")
    _assert_missing_like_absent(reader, f"/feed/{pid}/")
