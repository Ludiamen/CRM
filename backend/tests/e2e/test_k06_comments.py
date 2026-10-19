"""T-5145: сценарий 6 — комментарии под статьёй (FR-409, FR-416, FR-425, FR-426, FR-438, NFR-405).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md: 10.5, 10.7, 11.5, 12, раздел 17):
- каждый тест заводит своих сотрудников (автор статьи — «Сотрудник ИТ», комментаторы — «Руководитель» без прав базы
  знаний, управляющий — администратор круга `admin_page`), свою рубрику и свои статьи; названия уникальны;
- общих настроек тесты файла не меняют; сброса стенда нет (данные круга общие);
- все локаторы строки комментария — внутри `li[data-comment-id="<id>"]` (`[data-field=author]`, `time[data-at]` и
  `[data-field=text]` есть и у статьи);
- подготовка вне интерфейса — только команды стенда `e2e_kb_trash_shift` и `e2e_kb_purge` (помощники `helpers_kb`);
  `stand_shell` в файле не вызывается.
"""
import re
import secrets
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org, helpers_sd
from tests.e2e.helpers_kb import (
    create_draft, create_rubric, make_editor, make_reader, open_article, publish_from_article_page, unique_title,
    unique_word)

MOSCOW = ZoneInfo("Europe/Moscow")
GONE = "Статья удалена"
LIMIT = 4000
_FEED = "ol[data-feed]"
_GONE_CODE = re.compile(r"data-code=[\"']?article_gone")


# --- Помощники файла ---------------------------------------------------------------------------------------

def _published(editor_page, admin_page) -> tuple:
    """Опубликованная статья со своей рубрикой (рубрику заводит управляющий, статью пишет и публикует редактор).
    Возвращает (номер статьи, заголовок)."""
    rubric = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, rubric)
    title = unique_title()
    article_id = create_draft(editor_page, title=title, text="Текст статьи про комментарии.", rubric=rubric)
    publish_from_article_page(editor_page, article_id)
    return article_id, title


def _open(page, article_id) -> None:
    """Страница статьи с блоком комментариев `section#comments[data-kb-comments]`."""
    open_article(page, article_id)
    expect(page.locator("section#comments[data-kb-comments]")).to_be_visible()


def _rows(page):
    return page.locator("[data-kb-comment-list] li[data-comment-id]")


def _row(page, comment_id):
    return page.locator(f'[data-kb-comment-list] li[data-comment-id="{comment_id}"]')


def _form(page):
    return page.locator('form[data-form="kb-comment"]')


def _type(page, text: str) -> None:
    """Вводит текст в поле комментария; `maxlength` снимается: ввод длиннее предела браузер обрезал бы, а проверка
    предела — дело сервера."""
    area = _form(page).locator("textarea[name=text]")
    area.evaluate("el => el.removeAttribute('maxlength')")
    area.fill(text)


def _post(page, text: str) -> str:
    """Комментарий через форму открытой страницы статьи: ждёт, что в списке стало на одну строку больше (строка
    приходит фрагментом HTMX в конец списка); возвращает номер новой строки."""
    before = _rows(page).count()
    _type(page, text)
    _form(page).locator('button[data-action="kb-comment-add"]').click()
    expect(_rows(page)).to_have_count(before + 1)
    return _rows(page).last.get_attribute("data-comment-id")


def _delete_button(page, comment_id):
    return _row(page, comment_id).locator('button[data-action="kb-comment-delete"]')


def _trash(manager_page, article_id) -> None:
    """Управляющий переносит статью в корзину кнопкой страницы статьи (окно подтверждения принимается)."""
    open_article(manager_page, article_id)
    manager_page.once("dialog", lambda dialog: dialog.accept())
    manager_page.locator('form[data-form="kb-trash"]').get_by_role("button", name="В корзину").click()
    expect(manager_page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()


def _dismiss(page, user_id) -> None:
    """Увольнение из карточки сотрудника (срез 002): `[data-action="dismiss"]`, диалог, подтверждение; ждёт отметку
    `[data-dismissed-badge]` рядом с ФИО."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def test_k06_comment_appears_below_article_with_name_photo_and_time(admin_page, employee):
    """Сценарий 6, п. 1: опубликованная статья; сотрудник вводит текст и нажимает «Отправить» — комментарий появился
    снизу под статьёй с ФИО, фото и временем по Москве (FR-425)."""
    editor = make_editor(employee)
    full_name = f"Комментов{secrets.token_hex(3)} Иван Иванович"
    commenter = make_reader(employee, full_name=full_name)
    article_id, _ = _published(editor.page, admin_page)
    # у комментатора есть фото (чистое: ClamAV стенда проверяет его до минуты)
    commenter.page.goto("/me/")
    form = commenter.page.locator('form[action="/me/photo/"]')
    with commenter.page.expect_navigation():
        helpers_org.upload_file(form, helpers.make_png(120, 120), field="photo", name="photo.png", mime="image/png")
    assert helpers_org.wait_photo_checked(commenter.page, "/me/", timeout=60) == "clean", "чистое фото не принято"
    page = commenter.page
    _open(page, article_id)
    expect(page.locator("section#comments[data-kb-comments]")).to_contain_text("Комментарии")
    expect(_form(page).locator('button[data-action="kb-comment-add"]')).to_have_text("Отправить")
    # п. 1: вводит текст и нажимает «Отправить»
    text = f"не сработало на Windows 11 {unique_word()}"
    comment_id = _post(page, text)
    # когда: форма очищена, строка внизу списка
    expect(_form(page).locator("textarea[name=text]")).to_have_value("")
    for reloaded in (False, True):
        if reloaded:
            _open(page, article_id)
        row = _row(page, comment_id)
        # п. 1: ФИО, фото, время, текст — внутри строки
        expect(row.locator('[data-field="author"]')).to_contain_text(full_name)
        photo = row.locator('img[data-field="photo"]')
        expect(photo).to_have_count(1)
        expect(photo).to_have_attribute("src", re.compile(r"\S"))
        page.wait_for_function(
            "sel => { const e = document.querySelector(sel); return !!e && e.complete && e.naturalWidth > 0; }",
            arg=f'[data-kb-comment-list] li[data-comment-id="{comment_id}"] img[data-field="photo"]')
        expect(row.locator('[data-field="text"]')).to_contain_text(text)
        stamp = row.locator("time[data-at]")
        shown = stamp.inner_text().strip()
        assert re.fullmatch(r"\d\d\.\d\d\.\d{4} \d\d:\d\d", shown), f"вид времени: {shown!r}"
        now = datetime.now(MOSCOW)
        moment = datetime.strptime(shown, "%d.%m.%Y %H:%M").replace(tzinfo=MOSCOW)
        assert abs(now - moment) < timedelta(minutes=10), f"время комментария {shown} далеко от московского {now:%H:%M}"
        stamped = datetime.fromisoformat(stamp.get_attribute("datetime"))
        assert stamped.utcoffset() == timedelta(hours=3), "время не по Москве"
        assert abs(now - stamped) < timedelta(minutes=10)
    # «снизу под статьёй»: блок комментариев идёт после текста статьи
    body_box = page.locator('article[data-article-id] [data-field="body"]').bounding_box()
    block_box = page.locator("section#comments[data-kb-comments]").bounding_box()
    assert block_box["y"] >= body_box["y"] + body_box["height"] - 1, "комментарии не под текстом статьи"
    # второй комментарий — в конец списка («старые первыми»)
    second = _post(page, f"второй комментарий {unique_word()}")
    ids = [row.get_attribute("data-comment-id") for row in _rows(page).all()]
    assert ids == [comment_id, second], ids


def test_k06_comment_of_4001_chars_is_not_saved_and_limit_is_shown(admin_page, employee):
    """Сценарий 6, п. 2: комментарий из 4001 знака — «Отправить» не сохраняет его, показан предел 4000; ровно 4000
    знаков принимаются (FR-425)."""
    editor = make_editor(employee)
    commenter = make_reader(employee)
    article_id, _ = _published(editor.page, admin_page)
    page = commenter.page
    _open(page, article_id)
    marker = unique_word()
    too_long = marker + "а" * (LIMIT + 1 - len(marker))
    assert len(too_long) == LIMIT + 1
    # п. 2: 4001 знак, нажато «Отправить»
    _type(page, too_long)
    _form(page).locator('button[data-action="kb-comment-add"]').click()
    # п. 2: показан предел; введённый текст остался в поле
    error = _form(page).locator('[data-error="text"][data-code="too_long"]')
    expect(error).to_be_visible()
    expect(error).to_contain_text("Комментарий не длиннее 4000 знаков")
    expect(_form(page).locator("textarea[name=text]")).to_have_value(too_long)
    expect(_rows(page)).to_have_count(0)
    # п. 2: не сохранён — и после перезагрузки страницы строки нет
    _open(page, article_id)
    expect(_rows(page).filter(has_text=marker)).to_have_count(0)
    expect(_rows(page)).to_have_count(0)
    # граница: ровно 4000 знаков принимаются
    marker_ok = unique_word()
    exact = marker_ok + "б" * (LIMIT - len(marker_ok))
    assert len(exact) == LIMIT
    comment_id = _post(page, exact)
    expect(_row(page, comment_id).locator('[data-field="text"]')).to_contain_text(marker_ok)
    expect(_form(page).locator('[data-error="text"]')).to_have_count(0)


def test_k06_comment_markup_is_shown_as_text_with_line_breaks_kept_and_link_as_text(admin_page, employee):
    """Сценарий 6, п. 3: текст с `<b>` и ссылкой — разметки нет: `<b>` показан текстом, переносы строк сохранены,
    ссылка показана текстом; скрипт и картинка не выполняются (FR-425, NFR-405)."""
    editor = make_editor(employee)
    commenter = make_reader(employee)
    article_id, _ = _published(editor.page, admin_page)
    page = commenter.page
    _open(page, article_id)
    marker = unique_word()
    lines = [f"{marker} <b>жирный</b>", "вторая строка", "https://example.test/page",
             '<img src="x" onerror="window.__kbxss = 1">']
    # п. 3: комментарий с разметкой и ссылкой отправлен
    comment_id = _post(page, "\n".join(lines))
    for reloaded in (False, True):  # ответ HTMX и страница, собранная сервером
        if reloaded:
            _open(page, article_id)
        text = _row(page, comment_id).locator('[data-field="text"]')
        # п. 3: `<b>` — текст, тега нет
        expect(text).to_contain_text("<b>жирный</b>")
        expect(text.locator("b")).to_have_count(0)
        # п. 3: ссылка показана текстом, ссылкой не стала
        expect(text).to_contain_text("https://example.test/page")
        expect(text.locator("a")).to_have_count(0)
        expect(text.locator("img, script")).to_have_count(0)
        # п. 3: переносы строк сохранены, построчно
        shown = [part.strip() for part in text.inner_text().split("\n") if part.strip()]
        assert shown == lines, shown
        assert text.locator("br").count() >= len(lines) - 1
    assert page.evaluate("window.__kbxss") is None, "разметка комментария выполнилась"


def test_k06_author_deletes_own_comment_and_it_disappears_for_everyone(admin_page, employee):
    """Сценарий 6, п. 4: свой комментарий — автор нажимает «Удалить», комментарий исчез для всех (FR-425)."""
    editor = make_editor(employee)
    author = make_reader(employee)
    viewer = make_reader(employee)
    article_id, _ = _published(editor.page, admin_page)
    _open(author.page, article_id)
    text = f"комментарий для удаления {unique_word()}"
    comment_id = _post(author.page, text)
    _open(viewer.page, article_id)
    expect(_row(viewer.page, comment_id)).to_have_count(1)  # другим он виден
    # п. 4: у своего комментария есть «Удалить»; автор нажимает
    button = _delete_button(author.page, comment_id)
    expect(button).to_be_visible()
    author.page.once("dialog", lambda dialog: dialog.accept())
    button.click()
    expect(_row(author.page, comment_id)).to_have_count(0)
    # п. 4: исчез для всех — автор, другой сотрудник, управляющий (страницы грузятся заново)
    for who in (author.page, viewer.page, admin_page, editor.page):
        _open(who, article_id)
        expect(_rows(who).filter(has_text=text)).to_have_count(0)
    # повторное удаление — комментария нет
    assert helpers_org.direct_post(author.page, f"/kb/comments/{comment_id}/delete/").status == 404


def test_k06_foreign_comment_has_no_delete_button_for_non_manager_and_direct_call_is_denied(admin_page, employee):
    """Сценарий 6, п. 5: чужой комментарий и сотрудник без права «Управление базой знаний» — кнопки «Удалить» нет,
    прямое обращение — отказ 403 (FR-425, FR-409)."""
    editor = make_editor(employee)
    commenter = make_reader(employee)
    other_reader = make_reader(employee)
    other_editor = make_editor(employee)
    article_id, _ = _published(editor.page, admin_page)
    _open(commenter.page, article_id)
    text = f"чужой комментарий {unique_word()}"
    comment_id = _post(commenter.page, text)
    expect(_delete_button(commenter.page, comment_id)).to_be_visible()  # у автора кнопка есть
    for viewer in (other_reader, other_editor, editor):
        # п. 5: комментарий виден, «Удалить» нет
        _open(viewer.page, article_id)
        expect(_row(viewer.page, comment_id)).to_have_count(1)
        expect(_delete_button(viewer.page, comment_id)).to_have_count(0)
        # п. 5: прямое обращение — отказ
        assert helpers_org.direct_post(viewer.page, f"/kb/comments/{comment_id}/delete/").status == 403
    # комментарий остался
    _open(commenter.page, article_id)
    expect(_row(commenter.page, comment_id).locator('[data-field="text"]')).to_contain_text(text)


def test_k06_manager_deletes_foreign_comment_and_journal_records_it_without_comment_text(admin_page, employee):
    """Сценарий 6, п. 6: чужой комментарий и управляющий — «Удалить» удаляет, в журнале запись «Чужой комментарий
    удалён» с номером и заголовком статьи и без текста комментария (FR-425, FR-438)."""
    editor = make_editor(employee)
    commenter = make_reader(employee)
    article_id, title = _published(editor.page, admin_page)
    _open(commenter.page, article_id)
    marker = unique_word()
    comment_id = _post(commenter.page, f"текст для журнала {marker}")
    code = "knowledge.comment_deleted"
    before = helpers_org.audit_rows(admin_page, code, article_id)
    # п. 6: у управляющего на чужом комментарии «Удалить» есть; нажимает
    _open(admin_page, article_id)
    button = _delete_button(admin_page, comment_id)
    expect(button).to_be_visible()
    admin_page.once("dialog", lambda dialog: dialog.accept())
    button.click()
    expect(_row(admin_page, comment_id)).to_have_count(0)
    _open(commenter.page, article_id)
    expect(_rows(commenter.page).filter(has_text=marker)).to_have_count(0)
    # п. 6: в журнале одна новая запись по этой статье
    rows = helpers_org.audit_rows(admin_page, code, article_id)
    assert len(rows) == len(before) + 1, (len(before), len(rows))
    assert "Чужой комментарий удалён" in rows[0]
    assert title in rows[0], "в записи нет заголовка статьи"
    sides = helpers_org.audit_sides(admin_page, code, article_id)
    assert title in sides[0][0], sides[0]
    # п. 6: текста комментария в журнале нет
    for text in [*rows, *(left + right for left, right in sides)]:
        assert marker not in text
    admin_page.goto("/audit/?" + f"action={code}&object_id={article_id}")
    assert marker not in admin_page.locator("body").inner_text()


def test_k06_comment_on_draft_or_trashed_article_is_refused(admin_page, employee):
    """Сценарий 6, п. 7: черновик — под ним нет блока комментариев, прямая отправка — как у несуществующего (404);
    статья в корзине — отказ «Статья удалена», комментарий не сохранён и после возврата из корзины его нет (FR-425)."""
    editor = make_editor(employee)
    reader = make_reader(employee)
    # --- черновик ---
    rubric = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, rubric)
    draft_id = create_draft(editor.page, title=unique_title(), rubric=rubric)
    draft_marker = unique_word()
    open_article(editor.page, draft_id)
    expect(editor.page.locator("section#comments[data-kb-comments]")).to_have_count(0)
    for who in (editor.page, reader.page, admin_page):
        response = helpers_org.direct_post(who, f"/kb/{draft_id}/comments/", {"text": draft_marker})
        assert response.status == 404, response.status
        assert draft_marker not in response.text()
    publish_from_article_page(editor.page, draft_id)
    expect(editor.page.locator("section#comments[data-kb-comments]")).to_be_visible()
    expect(_rows(editor.page).filter(has_text=draft_marker)).to_have_count(0)
    assert _rows(editor.page).count() == 0
    # --- статья в корзине ---
    article_id, title = _published(editor.page, admin_page)
    _open(reader.page, article_id)
    kept = _post(reader.page, f"комментарий до корзины {unique_word()}")
    _trash(admin_page, article_id)
    expect(admin_page.locator("section#comments[data-kb-comments]")).to_have_count(0)  # в корзине блока нет
    trash_marker = unique_word()
    for who in (reader.page, admin_page):
        response = helpers_org.direct_post(who, f"/kb/{article_id}/comments/", {"text": trash_marker})
        assert response.status == 200, response.status
        body = response.text()
        assert GONE in body and _GONE_CODE.search(body) and helpers_org.has_alert(response), "нет отказа «Статья удалена»"
        assert trash_marker not in body
    gone = helpers_org.direct_get(reader.page, f"/kb/{article_id}/")
    assert gone.status == 410 and GONE in gone.text() and title not in gone.text()
    # возврат из корзины: сохранён только прежний комментарий, отказанного нет
    open_article(admin_page, article_id)
    admin_page.locator('form[data-form="kb-restore"]').get_by_role("button", name="Вернуть").click()
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    _open(reader.page, article_id)
    expect(_rows(reader.page).filter(has_text=trash_marker)).to_have_count(0)
    ids = [row.get_attribute("data-comment-id") for row in _rows(reader.page).all()]
    assert ids == [kept], ids


def test_k06_purged_article_has_no_comments(admin_page, employee):
    """Сценарий 6, п. 8: статья удалена навсегда (срок корзины прошёл, ночная очистка) — комментариев нет: статья
    и её комментарии как несуществующие (FR-416, FR-426)."""
    editor = make_editor(employee)
    commenter = make_reader(employee)
    article_id, _ = _published(editor.page, admin_page)
    _open(commenter.page, article_id)
    marker = unique_word()
    comment_id = _post(commenter.page, f"комментарий до удаления навсегда {marker}")
    _trash(admin_page, article_id)
    # срок корзины прошёл (команды стенда): сдвиг на 100 лет надёжно больше любого срока, очистка — сразу
    assert helpers_kb.trash_shift(36500)["shifted"] >= 1
    assert helpers_kb.purge()["purged"] >= 1
    # п. 8: статьи нет ни для кого (404, не 410), комментария нет
    for who in (admin_page, commenter.page, editor.page):
        assert helpers_org.direct_get(who, f"/kb/{article_id}/").status == 404
    for who in (commenter.page, admin_page):
        assert helpers_org.direct_post(who, f"/kb/comments/{comment_id}/delete/").status == 404
        assert helpers_org.direct_post(who, f"/kb/{article_id}/comments/", {"text": marker}).status == 404


def test_k06_dismissed_commenter_is_signed_with_dismissed_mark(admin_page, employee):
    """Сценарий 6, п. 9: сотрудника уволили — его прежний комментарий подписан именем с пометкой «уволен» (FR-425;
    SPEC-002 FR-127)."""
    editor = make_editor(employee)
    full_name = f"Уволенов{secrets.token_hex(3)} Пётр Петрович"
    commenter = make_reader(employee, full_name=full_name)
    viewer = make_reader(employee)
    article_id, _ = _published(editor.page, admin_page)
    _open(commenter.page, article_id)
    marker = unique_word()
    comment_id = _post(commenter.page, f"комментарий будущего уволенного {marker}")
    _open(viewer.page, article_id)
    expect(_row(viewer.page, comment_id).locator('[data-field="author"] [data-dismissed="true"]')).to_have_count(0)
    # когда: сотрудника увольняет администратор
    _dismiss(admin_page, commenter.id)
    # п. 9: прежний комментарий остался, подпись — имя с пометкой «уволен»
    _open(viewer.page, article_id)
    row = _row(viewer.page, comment_id)
    expect(row.locator('[data-field="text"]')).to_contain_text(marker)
    mark = row.locator('[data-field="author"] span[data-dismissed="true"]')
    expect(mark).to_have_count(1)
    expect(mark).to_contain_text(full_name)
    expect(mark).to_contain_text("(уволен)")


def test_k06_ticket_internal_comments_stay_feed_records_and_cannot_be_edited_or_deleted(admin_page):
    """Сценарий 6, п. 10: внутренние комментарии заявки остаются записями ленты заявки (не комментариями базы знаний),
    не правятся и не удаляются, как прежде (FR-426; SPEC-003 FR-246)."""
    helpers_sd.ensure_ready(admin_page)
    word = f"t{secrets.token_hex(3)}"
    subject = f"Заявка про комментарии {word}"
    letter = EmailMessage()
    letter["From"] = helpers_sd.requester_email()
    letter["To"] = helpers_sd.MAILBOX
    letter["Subject"] = subject
    letter["Message-ID"] = f"<{secrets.token_hex(8)}@client.test>"
    letter.set_content(f"Не работает принтер {word}")
    helpers_sd.deliver(letter.as_bytes())
    number = helpers_sd.ticket_number_by_subject(admin_page, word)
    # когда: исполнитель работает с внутренним комментарием заявки (форма карточки)
    card = helpers_sd.open_ticket(admin_page, number)
    text = f"Служебная заметка {secrets.token_hex(3)}"
    form = card.locator('form[data-form="ticket-comment"]')
    form.locator("textarea[name=text]").fill(text)
    helpers.submit(form)
    item = card.locator(f'{_FEED} li[data-kind="comment"]').filter(has_text=text)
    expect(item).to_have_count(1)
    # п. 10: запись ленты, помечена «внутренний»; комментарием базы знаний не стала
    expect(item.locator("[data-internal]")).to_contain_text("внутренний")
    expect(item.locator("[data-comment-id]")).to_have_count(0)
    expect(card.locator('button[data-action="kb-comment-delete"], [data-kb-comments], [data-kb-comment-list]')) \
        .to_have_count(0)
    entry_id = item.get_attribute("data-entry-id")
    assert entry_id, "у записи ленты нет номера"
    # п. 10: не правится и не удаляется — в ленте нет форм, кнопок и ссылок правки и удаления
    feed = card.locator(_FEED)
    expect(feed.locator("form")).to_have_count(0)
    expect(feed.locator("button")).to_have_count(0)
    expect(feed.locator('a[href*="edit"], a[href*="delete"], [data-action*="edit"], [data-action*="delete"]')) \
        .to_have_count(0)
    after = helpers_sd.open_ticket(admin_page, number)
    expect(after.locator(f'{_FEED} li[data-kind="comment"]').filter(has_text=text)).to_have_count(1)
