"""T-5147: сценарий 8 — корзина: удаление, возврат, удаление навсегда, срок 90 дней (FR-406, FR-409, FR-415, FR-416,
FR-417, FR-425, FR-429, FR-435, FR-438, FR-444).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md, разделы 10.3, 11.3, 11.7, 12.3, 13, 17):
- каждый тест заводит своих сотрудников, свою рубрику и свои статьи; названия уникальны; управляющий — администратор
  круга `admin_page` (там, где важно имя удалившего, — сотрудник «Администратор портала» с уникальным ФИО);
- «Перенести в корзину» и «Удалить навсегда» подтверждаются окном браузера (`hx-confirm`, решение C-5): тест читает
  атрибут и принимает окно `dialog`; после нажатия ждёт зацепку результата (`[data-kb-trash-mark]`, `[data-kb-page="trash"]`,
  `article[data-article-state=…]`), а не адрес: механизм перехода (302 или подмена HTMX) контракт не фиксирует;
- команда `e2e_kb_trash_shift` сдвигает ВСЕ статьи корзины, а `e2e_kb_purge` очищает всё, что старше срока, поэтому
  тесты с ними (6 и 8) заодно очищают статьи корзины, оставшиеся от прежних тестов; те тесты уже закончились;
- общая настройка, которую меняет тест, — срок корзины (тест 8): прежнее значение возвращается в `finally`;
- вне интерфейса — только команды стенда `helpers_kb.trash_shift` и `helpers_kb.purge`; `stand_shell` не вызывается;
- ClamAV стенда: вложение в тестах 5 и 12 нужно только как строка списка (она есть в любом состоянии), ожидания
  «проверяется → чистый» нет.
"""
import re
import time
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org, helpers_sd
from tests.e2e.helpers_kb import (
    article_form, attach_file, create_draft, create_rubric, home_ids, open_article, open_edit, press_save,
    publish_from_article_page, rubric_id_by_name, rubric_page_ids, search_finds, unique_title, unique_word)

MSK = ZoneInfo("Europe/Moscow")
TRASH_CONFIRM = "Перенести статью в корзину?"                  # 12.3
PURGE_CONFIRM = "Удалить статью навсегда? Это нельзя отменить."  # 12.3
GONE = "Статья удалена"                                          # 12.1
SELECTOR_TRASH = 'form[data-form="kb-trash"]'
SELECTOR_RESTORE = 'form[data-form="kb-restore"]'
SELECTOR_PURGE = 'form[data-form="kb-purge"]'


# --- Свои помощники файла ----------------------------------------------------------------------------------

def _rubric(admin_page) -> str:
    """Своя рубрика круга (создаёт управляющий); возвращает название."""
    name = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, name)
    return name


def _published(author_page, rubric: str, *, title: str | None = None, text: str = "Текст статьи про корзину.") -> tuple:
    """Опубликованная статья автора; возвращает (номер, заголовок)."""
    title = title or unique_title()
    article_id = create_draft(author_page, title=title, text=text, rubric=rubric)
    publish_from_article_page(author_page, article_id)
    return article_id, title


def _word_of(title: str) -> str:
    """Уникальное слово заголовка (последнее слово `unique_title`), по нему статью находит поиск."""
    return title.split()[-1]


def _click_with_confirm(page, form_selector: str, expected: str) -> None:
    """Нажимает кнопку формы с `hx-confirm`: читает текст подтверждения, принимает окно браузера и проверяет, что
    окно показало именно этот текст."""
    form = page.locator(form_selector)
    expect(form).to_have_attribute("hx-confirm", expected)
    shown: list = []

    def accept(dialog) -> None:
        shown.append(dialog.message)
        dialog.accept()

    page.once("dialog", accept)
    form.locator("button").first.click()
    assert shown == [expected], f"окно подтверждения показало {shown!r}, ждали {expected!r}"


def _trash(page, article_id) -> None:
    """Управляющий переносит статью в корзину кнопкой страницы статьи (с подтверждением) и ждёт пометку «В корзине»."""
    open_article(page, article_id)
    _click_with_confirm(page, SELECTOR_TRASH, TRASH_CONFIRM)
    expect(page.locator("[data-kb-trash-mark]")).to_be_visible()
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()


def _restore(page, article_id, state: str) -> None:
    """Управляющий возвращает статью из корзины кнопкой страницы статьи; ждёт состояние `state` (`draft`/`published`)."""
    open_article(page, article_id)
    page.locator(SELECTOR_RESTORE).locator("button").first.click()
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="{state}"]')).to_be_visible()


def _purge(page, article_id) -> None:
    """Управляющий удаляет статью из корзины навсегда (с подтверждением); ждёт страницу корзины."""
    open_article(page, article_id)
    _click_with_confirm(page, SELECTOR_PURGE, PURGE_CONFIRM)
    expect(page.locator('[data-kb-page="trash"]')).to_be_visible()


def _status(page, path: str) -> int:
    """Код ответа на прямой GET от имени страницы (без перехода по редиректам)."""
    return helpers_org.direct_get(page, path).status


def _pick_has(page, word: str, article_id) -> bool:
    """Есть ли статья в выдаче «Привязать статью» (`/kb/pick/?q=<слово>`, фрагмент `ul[data-kb-pick-results]`)."""
    response = helpers_org.direct_get(page, "/kb/pick/?q=" + quote(word))
    assert response.status == 200, f"/kb/pick/: ответ {response.status}"
    return f'data-article-id="{article_id}"' in response.text()


def _trash_row(page, article_id):
    """Строка статьи в списке корзины `/kb/trash/` (страница открыта заново)."""
    page.goto("/kb/trash/")
    expect(page.locator('[data-kb-page="trash"]')).to_be_visible()
    return page.locator(f'[data-kb-trash-list] tr[data-article-id="{article_id}"]')


def _ticket(page) -> int:
    """Заявка от исполнителя (форма `/tickets/new/`, категория «Другое»); возвращает номер из адреса карточки."""
    helpers_sd.ensure_ready(page)
    page.goto("/tickets/new/")
    form = page.locator('form[data-form="ticket-new"]')
    expect(form).to_be_visible()
    old_requester = form.locator("input[name=name]").element_handle()
    with page.expect_response(lambda r: "/tickets/new/requester/" in r.url):
        form.locator("input[name=email]").fill(helpers_sd.requester_email("kb"))
        form.locator("input[name=email]").press("Tab")
    page.wait_for_function("el => !el.isConnected", arg=old_requester)
    old_queue = form.locator("select[name=queue]").element_handle()
    with page.expect_response(lambda r: "/tickets/new/queue/" in r.url):
        form.locator("select[name=category]").select_option(label="Другое")
    page.wait_for_function("el => !el.isConnected", arg=old_queue)
    form.locator("select[name=source] option[value]:not([value=''])").first.wait_for(state="attached")
    source = form.locator("select[name=source] option[value]:not([value=''])").first.get_attribute("value")
    form.locator("select[name=source]").select_option(value=source)
    form.locator("input[name=subject]").fill(f"Корзина базы знаний {unique_word('t')}")
    form.locator("textarea[name=text]").fill("Заявка для проверки связи со статьёй")
    helpers.submit(form)
    page.wait_for_url(re.compile(r"/tickets/\d+/$"))
    return int(re.search(r"/tickets/(\d+)/", page.url).group(1))


def _link(page, number: int, word: str, article_id) -> None:
    """Привязывает опубликованную статью к заявке в разделе «Статьи» карточки (поле `pick`, кнопка «Привязать статью»);
    ждёт строку связи в `[data-card-part="kb-articles"]`."""
    helpers_sd.open_ticket(page, number)
    form = page.locator('form[data-form="kb-link"]')
    form.locator('input[name="pick"]').fill(word)
    add = form.locator(f'button[data-action="kb-link-add"][data-article-id="{article_id}"]')
    expect(add).to_be_visible()
    add.click()
    expect(page.locator(f'[data-card-part="kb-articles"] li[data-article-id="{article_id}"]')).to_be_visible()


def _card_link_rows(page, number: int, article_id):
    """Строки связи со статьёй в карточке заявки (карточка открыта заново, раздел «Статьи» дождались)."""
    helpers_sd.open_ticket(page, number)
    expect(page.locator('[data-card-part="kb-articles"]')).to_be_visible()  # у управляющего раздел с формой есть всегда
    return page.locator(f'[data-card-part="kb-articles"] li[data-article-id="{article_id}"]')


def _lists_contain(page, rubric_id, word: str, article_id) -> dict:
    """Где статью видно: главная («Новые и изменённые»), страница рубрики, страница поиска, выбор для привязки."""
    return {
        "главная": article_id in home_ids(page, "new-and-changed"),
        "рубрика": article_id in rubric_page_ids(page, rubric_id),
        "поиск": search_finds(page, word, article_id),
        "привязка": _pick_has(page, word, article_id),
    }


def _set_term(page, days) -> None:
    """Срок корзины формой `/kb/settings/`: вводит `days`, нажимает «Сохранить», ждёт флеш «Срок корзины сохранён»."""
    page.goto("/kb/settings/")
    expect(page.locator('[data-kb-page="settings"]')).to_be_visible()
    form = page.locator('form[data-form="kb-settings"]')
    form.locator("input[name=trash_days]").fill(str(days))
    form.locator('button[data-action="kb-settings-save"]').click()
    expect(page.locator("[role=status]").filter(has_text="Срок корзины сохранён")).to_be_visible()
    expect(page.locator('form[data-form="kb-settings"] input[name=trash_days]')).to_have_value(str(days))


def _current_term(page) -> str:
    page.goto("/kb/settings/")
    expect(page.locator('[data-kb-page="settings"]')).to_be_visible()
    return page.locator('form[data-form="kb-settings"] input[name=trash_days]').input_value()


def _wait_notification(page, text: str, *, timeout: float = 60.0) -> None:
    """Ждёт на `/notifications/` строку уведомления с текстом (опрос с перезагрузкой, предел `timeout` с)."""
    deadline = time.monotonic() + timeout
    while True:
        page.goto("/notifications/")
        rows = page.locator("ul[data-notifications] li[data-notification]").filter(has_text=text)
        if rows.count():
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"уведомление «{text}» не пришло за {timeout:.0f} с")
        page.wait_for_timeout(2000)


# --- Сценарий 8 --------------------------------------------------------------------------------------------

def test_k08_manager_trashes_article_and_it_disappears_from_base_rubrics_new_changed_search_and_attach_while_old_link_shows_deleted(
        admin_page, employee):
    """Сценарий 8, п. 1: управляющий нажимает «Удалить» и подтверждает — статьи нет в базе, рубриках, «Новых и
    изменённых», поиске и «Привязать статью»; по старой ссылке остальным «Статья удалена», управляющему — пометка
    (FR-415)."""
    rubric = _rubric(admin_page)
    rubric_id = rubric_id_by_name(admin_page, rubric)
    author = helpers_kb.make_editor(employee)
    article_id, title = _published(author.page, rubric)
    word = _word_of(title)
    # дано: до удаления статья видна везде (иначе проверки «нет» ничего не доказывают)
    for who, page in (("управляющий", admin_page), ("автор", author.page)):
        seen = _lists_contain(page, rubric_id, word, article_id)
        assert all(seen.values()), f"{who}: до удаления статью видно не везде: {seen}"
    # п. 1: управляющий нажимает «Удалить» (в корзину) и подтверждает окно
    _trash(admin_page, article_id)
    expect(admin_page.locator("[role=status]").filter(has_text="Статья перенесена в корзину")).to_be_visible()
    # п. 1: её нет в базе, рубриках, «Новых и изменённых», поиске и «Привязать статью» ни у управляющего, ни у автора
    for who, page in (("управляющий", admin_page), ("автор", author.page)):
        seen = _lists_contain(page, rubric_id, word, article_id)
        assert not any(seen.values()), f"{who}: статья в корзине осталась в списках: {seen}"
    # п. 1: по старой ссылке остальным — «Статья удалена»
    response = author.page.goto(f"/kb/{article_id}/")
    assert response.status == 410, f"автор по старой ссылке: ответ {response.status}, ждали 410"
    expect(author.page.locator('[data-kb-page="gone"]')).to_contain_text(GONE)
    expect(author.page.locator(f'article[data-article-id="{article_id}"]')).to_have_count(0)
    # п. 1: управляющему — статья с пометкой «в корзине»
    open_article(admin_page, article_id)
    expect(admin_page.locator("[data-kb-trash-mark]")).to_contain_text("В корзине")
    expect(admin_page.locator(f'article[data-article-id="{article_id}"] h1[data-field="title"]')).to_have_text(title)


def test_k08_editor_without_manage_right_has_no_delete_button_and_direct_call_is_denied(admin_page, employee):
    """Сценарий 8, п. 2: сотрудник с правом «Редактирование», но без права «Управление», не видит кнопки «Удалить»,
    прямое обращение — отказ 403 (FR-406, FR-415)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    article_id, title = _published(author.page, rubric)
    # п. 2: сотрудник открывает статью — кнопки «Удалить» нет (при этом править он может)
    open_article(author.page, article_id)
    expect(author.page.locator('a[data-action="kb-edit"]')).to_be_visible()
    expect(author.page.locator(SELECTOR_TRASH)).to_have_count(0)
    # п. 2: прямое обращение — отказ
    response = helpers_org.direct_post(author.page, f"/kb/{article_id}/trash/")
    assert response.status == 403, f"прямой POST /trash/ без права: ответ {response.status}, ждали 403"
    # статья осталась опубликованной
    open_article(admin_page, article_id)
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()


def test_k08_trash_lists_title_rubric_deletion_date_and_who_deleted(admin_page, employee):
    """Сценарий 8, п. 3: корзина показывает заголовок, рубрику, дату удаления и того, кто удалил (FR-416)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    manager = helpers_kb.make_manager(employee, full_name=helpers_org.unique_name("Корзинов"))
    article_id, title = _published(author.page, rubric)
    before = datetime.now(MSK)
    _trash(manager.page, article_id)
    after = datetime.now(MSK)
    # п. 3: управляющий открывает корзину — в строке заголовок, рубрика, дата удаления, кто удалил
    row = _trash_row(manager.page, article_id)
    expect(row).to_have_count(1)
    expect(row.locator('a[data-field="title"]')).to_have_text(title)
    expect(row.locator('[data-field="rubric"]')).to_contain_text(rubric)
    expect(row.locator('[data-field="deleted-by"]')).to_contain_text(manager.full_name)
    days = {before.strftime("%Y-%m-%d"), after.strftime("%Y-%m-%d")}
    stamp = row.locator("time[data-at]")
    moment = stamp.get_attribute("datetime")
    assert moment[:10] in days and moment.endswith("+03:00"), f"дата удаления {moment}, ждали день {sorted(days)} по Москве"
    shown = {d.strftime("%d.%m.%Y") for d in (before, after)}
    assert any(day in stamp.inner_text() for day in shown), f"видимая дата {stamp.inner_text()!r}, ждали {sorted(shown)}"


def test_k08_restore_returns_article_to_prior_state_and_rubric_with_same_url_and_no_subscriber_notice(
        admin_page, employee):
    """Сценарий 8, п. 4: «Вернуть» возвращает статью в прежнее состояние (опубликована или черновик) и рубрику, адрес
    прежний, подписчики не уведомляются (FR-416, FR-435)."""
    rubric = _rubric(admin_page)
    rubric_id = rubric_id_by_name(admin_page, rubric)
    author = helpers_kb.make_editor(employee)
    subscriber = helpers_kb.make_reader(employee)
    published_id, published_title = _published(author.page, rubric)
    draft_title = unique_title()
    draft_id = create_draft(author.page, title=draft_title, text="Черновик для корзины.", rubric=rubric)
    # дано: подписчик подписывается после публикации (уведомление о ней не мешает проверке)
    subscriber.page.goto(f"/kb/rubrics/{rubric_id}/")
    button = subscriber.page.locator('button[data-action="kb-subscribe"]')
    button.click()
    expect(subscriber.page.locator('button[data-action="kb-subscribe"][data-subscribed="true"]')).to_be_visible()
    # дано: обе статьи в корзине
    _trash(admin_page, published_id)
    _trash(admin_page, draft_id)
    # п. 4: «Вернуть» — опубликованная снова опубликована, черновик — снова черновик
    _restore(admin_page, published_id, "published")
    _restore(admin_page, draft_id, "draft")
    for article_id in (published_id, draft_id):
        # адрес прежний, рубрика прежняя
        open_article(admin_page, article_id)
        assert admin_page.url.endswith(f"/kb/{article_id}/"), f"адрес изменился: {admin_page.url}"
        expect(admin_page.locator(f'article[data-article-id="{article_id}"] [data-field="rubric"]')).to_contain_text(rubric)
        expect(admin_page.locator(f'article[data-article-id="{article_id}"] [data-kb-trash-mark]')).to_have_count(0)
    assert published_id in rubric_page_ids(admin_page, rubric_id), "возвращённая статья не вернулась в рубрику"
    assert draft_id not in rubric_page_ids(admin_page, rubric_id), "возвращённый черновик попал в рубрику"
    assert draft_id in home_ids(admin_page, "all-drafts"), "возвращённого черновика нет среди черновиков"
    # п. 4: подписчики не уведомлены. Контрольная публикация новой статьи в той же рубрике приходит подписчику; когда
    # она пришла, уведомления о возврате (если бы они были) уже обработаны вместе с ней
    _control_id, control_title = _published(author.page, rubric)
    _wait_notification(subscriber.page, control_title)
    notices = subscriber.page.locator("ul[data-notifications] li[data-notification]")
    expect(notices.filter(has_text=published_title)).to_have_count(0)
    expect(notices.filter(has_text=draft_title)).to_have_count(0)


def test_k08_delete_forever_removes_article_versions_comments_attachments_and_ticket_links_with_journal_entry(
        admin_page, employee):
    """Сценарий 8, п. 5: «Удалить навсегда» с подтверждением удаляет статью, версии, комментарии, вложения и связи с
    заявками; в журнале запись с номером и заголовком (FR-416, FR-438)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    article_id, title = _published(author.page, rubric)
    word = _word_of(title)
    # дано: у статьи две версии, комментарий, вложение и связь с заявкой
    open_edit(author.page, article_id)
    article_form(author.page).locator("textarea[name=text]").fill("Новый текст статьи про корзину.")
    press_save(author.page)
    author.page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    assert helpers_kb.history_versions(author.page, article_id) == [2, 1]
    comment_id = helpers_kb.add_comment(author.page, article_id, f"Комментарий {unique_word()}")
    file_id = attach_file(author.page, article_id, b"file body", f"{unique_word('f')}.txt", mime="text/plain")
    number = _ticket(admin_page)
    _link(admin_page, number, word, article_id)
    # п. 5: управляющий переносит статью в корзину и удаляет навсегда с подтверждением
    _trash(admin_page, article_id)
    _purge(admin_page, article_id)
    expect(admin_page.locator("[role=status]").filter(has_text="Статья удалена навсегда")).to_be_visible()
    expect(_trash_row(admin_page, article_id)).to_have_count(0)
    # п. 5: статьи, её версий и вложений нет (даже у управляющего: 404); связи с заявкой нет
    assert _status(admin_page, f"/kb/{article_id}/") == 404
    assert _status(admin_page, f"/kb/{article_id}/history/") == 404
    assert _status(admin_page, f"/kb/{article_id}/versions/1/") == 404
    assert _status(admin_page, f"/kb/{article_id}/files/{file_id}/") == 404
    # комментарий удалён вместе со статьёй: его адреса больше нет (404); полное доказательство — серверный тест T-5108
    assert helpers_org.direct_post(admin_page, f"/kb/comments/{comment_id}/delete/").status == 404, \
        "комментарий удалённой навсегда статьи остался"
    expect(_card_link_rows(admin_page, number, article_id)).to_have_count(0)
    # п. 5: в журнале запись с номером и заголовком
    rows = helpers_org.audit_rows(admin_page, "knowledge.article_purged", article_id)
    assert len(rows) == 1, f"записей «удалена навсегда» по статье {article_id}: {len(rows)}"
    assert "Статья удалена навсегда" in rows[0]
    before, _after = helpers_org.audit_sides(admin_page, "knowledge.article_purged", article_id)[0]
    assert title in before and str(article_id) in before, f"в «было» нет заголовка и номера: {before!r}"
    # раздел 17, п. 62: ручное удаление — «по сроку: нет»
    assert re.search(r"по сроку:\s*нет", before), f"у ручного удаления нет «по сроку: нет»: {before!r}"


def test_k08_nightly_purge_removes_article_in_trash_91_days_with_journal_and_keeps_89_days(admin_page, employee):
    """Сценарий 8, п. 6: ночное задание удаляет навсегда статью, пролежавшую в корзине 91 день (запись в журнале «по
    сроку»), а статью 89 дней оставляет (FR-417, FR-438)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    old_id, old_title = _published(author.page, rubric)
    young_id, _young_title = _published(author.page, rubric)
    # дано: срок корзины — 90 суток (по умолчанию; тест 8 возвращает его в `finally`)
    assert _current_term(admin_page) == "90", "срок корзины не 90: настройка осталась от другого теста"
    # дано: старая статья в корзине 91 день, молодая — 89 (команда сдвигает все статьи корзины: 2 + 89 = 91, 89)
    _trash(admin_page, old_id)
    assert helpers_kb.trash_shift(2)["shifted"] >= 1
    _trash(admin_page, young_id)
    assert helpers_kb.trash_shift(89)["shifted"] >= 2
    # п. 6: проходит ночное задание
    result = helpers_kb.purge()
    assert result["purged"] >= 1 and result["failed"] == 0, f"ночная очистка: {result}"
    # п. 6: 91 день — удалена навсегда, в журнале запись «по сроку»; 89 дней — осталась в корзине
    assert _status(admin_page, f"/kb/{old_id}/") == 404
    expect(_trash_row(admin_page, old_id)).to_have_count(0)
    rows = helpers_org.audit_rows(admin_page, "knowledge.article_purged", old_id)
    assert len(rows) == 1, f"записей «удалена навсегда» по статье {old_id}: {len(rows)}"
    before, _after = helpers_org.audit_sides(admin_page, "knowledge.article_purged", old_id)[0]
    assert old_title in before and str(old_id) in before, f"в «было» нет заголовка и номера: {before!r}"
    assert re.search(r"по сроку:\s*да", before), f"в записи нет «по сроку: да»: {before!r}"
    expect(_trash_row(admin_page, young_id)).to_have_count(1)
    open_article(admin_page, young_id)
    expect(admin_page.locator(f'article[data-article-id="{young_id}"][data-article-state="trash"]')).to_be_visible()
    assert helpers_org.audit_rows(admin_page, "knowledge.article_purged", young_id) == []


def test_k08_trash_by_direct_link_is_denied_for_non_manager(admin_page, employee):
    """Сценарий 8, п. 7: сотрудник без права «Управление базой знаний» открывает корзину по прямой ссылке — отказ
    (FR-406, FR-416)."""
    editor = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    for who, account in (("редактор", editor), ("читатель", reader)):
        # п. 7: прямая ссылка на корзину — отказ 403, списка корзины нет
        response = account.page.goto("/kb/trash/")
        assert response.status == 403, f"{who}: /kb/trash/ ответ {response.status}, ждали 403"
        expect(account.page.locator("[data-kb-trash-list]")).to_have_count(0)
        # ссылки на корзину на главной у него тоже нет
        account.page.goto("/kb/")
        expect(account.page.locator('[data-kb-page="home"]')).to_be_visible()
        expect(account.page.locator('a[data-action="kb-trash-link"]')).to_have_count(0)
    # у управляющего корзина открывается и ссылка на главной есть
    admin_page.goto("/kb/")
    expect(admin_page.locator('a[data-action="kb-trash-link"]')).to_be_visible()
    response = admin_page.goto("/kb/trash/")
    assert response.status == 200
    expect(admin_page.locator('[data-kb-page="trash"]')).to_be_visible()


def test_k08_trash_term_changed_to_30_days_is_used_by_nightly_job_and_journal_records_before_after(
        admin_page, employee):
    """Сценарий 8, п. 8: управляющий меняет срок корзины на 30 дней — ночное задание считает по нему, в журнале «было /
    стало» (FR-417, FR-438)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    old_id, _old_title = _published(author.page, rubric)
    young_id, _young_title = _published(author.page, rubric)
    start = _current_term(admin_page)
    try:
        # дано: две статьи в корзине — 31 и 29 день (2 + 29 = 31, 29)
        _trash(admin_page, old_id)
        assert helpers_kb.trash_shift(2)["shifted"] >= 1
        _trash(admin_page, young_id)
        assert helpers_kb.trash_shift(29)["shifted"] >= 2
        if int(start) > 31:
            # контроль: при прежнем сроке статья 31 день не удаляется
            assert helpers_kb.purge()["failed"] == 0
            expect(_trash_row(admin_page, old_id)).to_have_count(1)
        # п. 8: управляющий меняет срок на 30 дней и сохраняет
        _set_term(admin_page, 30)
        # п. 8: в журнале «было / стало»
        before, after = helpers_org.audit_sides(admin_page, "knowledge.trash_days_changed")[0]
        assert start in before and "30" in after, f"журнал срока: было {before!r}, стало {after!r}"
        # п. 8: ночное задание считает по новому сроку — 31 день удалена, 29 дней осталась
        result = helpers_kb.purge()
        assert result["purged"] >= 1 and result["failed"] == 0, f"ночная очистка: {result}"
        assert _status(admin_page, f"/kb/{old_id}/") == 404
        expect(_trash_row(admin_page, old_id)).to_have_count(0)
        expect(_trash_row(admin_page, young_id)).to_have_count(1)
    finally:
        _set_term(admin_page, start)


def test_k08_trashed_article_is_absent_in_attach_article_search_and_global_search(admin_page, employee):
    """Сценарий 8, п. 9: статью в корзине не находят ни «Привязать статью», ни сквозной поиск (FR-415, FR-444)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    shared = unique_word()
    trashed_id, _trashed_title = _published(author.page, rubric, title=f"Корзина {shared} {unique_word()}")
    kept_id, _kept_title = _published(author.page, rubric, title=f"Остаётся {shared} {unique_word()}")
    # дано: до удаления обе статьи находятся и в выборе для привязки, и в поиске
    for page in (admin_page, author.page):
        assert _pick_has(page, shared, trashed_id) and _pick_has(page, shared, kept_id)
        assert search_finds(page, shared, trashed_id) and search_finds(page, shared, kept_id)
    # дано: одна статья — в корзине
    _trash(admin_page, trashed_id)
    # п. 9: ищут через «Привязать статью» и сквозной поиск — статьи в корзине нет, другая есть (поиск работает)
    for who, page in (("управляющий", admin_page), ("автор", author.page)):
        assert _pick_has(page, shared, kept_id), f"{who}: выбор для привязки не нашёл оставшуюся статью"
        assert not _pick_has(page, shared, trashed_id), f"{who}: «Привязать статью» нашла статью из корзины"
        assert search_finds(page, shared, kept_id), f"{who}: поиск не нашёл оставшуюся статью"
        assert not search_finds(page, shared, trashed_id), f"{who}: сквозной поиск нашёл статью из корзины"


def test_k08_trashed_article_is_absent_from_related_ticket_articles_section(admin_page, employee):
    """Сценарий 8, п. 10: статья удалена — в карточке связанной заявки её уже нет в разделе «Статьи» (FR-429)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    article_id, title = _published(author.page, rubric)
    number = _ticket(admin_page)
    _link(admin_page, number, _word_of(title), article_id)
    # дано: связь есть в разделе «Статьи» карточки
    expect(_card_link_rows(admin_page, number, article_id)).to_have_count(1)
    # п. 10: статью переносят в корзину — в разделе «Статьи» её уже нет
    _trash(admin_page, article_id)
    expect(_card_link_rows(admin_page, number, article_id)).to_have_count(0)
    expect(admin_page.locator('[data-card-part="kb-articles"]').get_by_text(title)).to_have_count(0)


def test_k08_trash_term_6_or_366_days_is_refused_with_limits_7_to_365_shown(admin_page):
    """Сценарий 8, п. 11: срок корзины 6 или 366 дней не сохраняется, показаны пределы 7–365 (FR-417)."""
    start = _current_term(admin_page)
    for entered in ("6", "366"):
        admin_page.goto("/kb/settings/")
        expect(admin_page.locator('[data-kb-page="settings"]')).to_be_visible()
        form = admin_page.locator('form[data-form="kb-settings"]')
        field = form.locator("input[name=trash_days]")
        # браузер сам не пропустил бы значение вне min/max: снимаем эти пределы, проверка — дело сервера
        field.evaluate("el => { el.removeAttribute('min'); el.removeAttribute('max'); el.removeAttribute('step'); }")
        form.evaluate("f => f.setAttribute('novalidate', 'novalidate')")
        field.fill(entered)
        form.locator('button[data-action="kb-settings-save"]').click()
        # п. 11: сохранения нет, показаны пределы, введённое значение осталось
        error = admin_page.locator('[data-error="trash_days"][data-code="out_of_range"]')
        expect(error).to_be_visible()
        expect(error).to_contain_text("Срок корзины — от 7 до 365 суток")
        expect(admin_page.locator('form[data-form="kb-settings"] input[name=trash_days]')).to_have_value(entered)
        expect(admin_page.locator("[role=status]").filter(has_text="Срок корзины сохранён")).to_have_count(0)
        # настройка не изменилась
        assert _current_term(admin_page) == start, f"после отказа на {entered} срок стал другим"


def test_k08_trashed_article_hides_comments_attachments_and_ticket_link_and_restore_brings_them_back(
        admin_page, employee):
    """Сценарий 8, п. 12: у статьи есть комментарии, вложения и связь с заявкой; в корзине их не видно (на странице
    статьи и в карточке заявки); после «Вернуть» они на месте (FR-415, FR-416, FR-425, FR-429)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    article_id, title = _published(author.page, rubric)
    comment = f"Комментарий {unique_word()}"
    helpers_kb.add_comment(author.page, article_id, comment)
    file_name = f"{unique_word('f')}.txt"
    file_id = attach_file(author.page, article_id, b"file body", file_name, mime="text/plain")
    number = _ticket(admin_page)
    _link(admin_page, number, _word_of(title), article_id)
    # дано: управляющий видит всё это на странице статьи и в карточке заявки
    open_article(admin_page, article_id)
    expect(admin_page.locator("[data-kb-comments] li[data-comment-id]").filter(has_text=comment)).to_have_count(1)
    expect(helpers_kb.file_row(admin_page, file_id)).to_have_count(1)
    expect(admin_page.locator("[data-kb-tickets] li[data-ticket-number]")).to_have_count(1)
    # п. 12: статья в корзине — на её странице комментариев, вложений и связанных заявок нет
    _trash(admin_page, article_id)
    expect(admin_page.locator("[data-kb-comments] li[data-comment-id]")).to_have_count(0)
    expect(admin_page.locator("[data-kb-files] li[data-file-id]")).to_have_count(0)
    expect(admin_page.locator("[data-kb-tickets] li[data-ticket-number]")).to_have_count(0)
    expect(admin_page.locator("body")).not_to_contain_text(comment)
    expect(admin_page.locator("body")).not_to_contain_text(file_name)
    # п. 12: и в карточке заявки связи нет
    expect(_card_link_rows(admin_page, number, article_id)).to_have_count(0)
    # п. 12: после «Вернуть» всё на месте
    _restore(admin_page, article_id, "published")
    expect(admin_page.locator("[data-kb-comments] li[data-comment-id]").filter(has_text=comment)).to_have_count(1)
    expect(helpers_kb.file_row(admin_page, file_id)).to_have_count(1)
    expect(admin_page.locator("[data-kb-tickets] li[data-ticket-number]")).to_have_count(1)
    expect(_card_link_rows(admin_page, number, article_id)).to_have_count(1)


def test_k08_manager_old_link_shows_trashed_article_with_restore_and_delete_forever_while_others_see_deleted(
        admin_page, employee):
    """Сценарий 8, п. 13: по старой ссылке на статью в корзине управляющий видит статью с пометкой «в корзине» и
    кнопками «Вернуть» и «Удалить навсегда», остальные — «Статья удалена» (FR-409, FR-415)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    manager = helpers_kb.make_manager(employee, full_name=helpers_org.unique_name("Корзинов"))
    article_id, title = _published(author.page, rubric)
    _trash(manager.page, article_id)
    # п. 13: управляющий открывает старую ссылку — статья с пометкой и двумя кнопками
    response = manager.page.goto(f"/kb/{article_id}/")
    assert response.status == 200, f"управляющий: ответ {response.status}, ждали 200"
    article = manager.page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')
    expect(article).to_be_visible()
    expect(article.locator('h1[data-field="title"]')).to_have_text(title)
    expect(manager.page.locator("[data-kb-trash-mark]")).to_contain_text("В корзине")
    expect(manager.page.locator("body")).to_contain_text(f"Удалил: {manager.full_name}")
    expect(manager.page.locator(SELECTOR_RESTORE)).to_have_count(1)
    expect(manager.page.locator(SELECTOR_PURGE)).to_have_count(1)
    assert _status(manager.page, f"/kb/{article_id}/history/") == 200  # другие адреса статьи — тоже страницы
    # п. 13: остальные (автор, читатель) видят «Статья удалена»: ответ 410, без заголовка и текста статьи
    for who, account in (("автор", author), ("читатель", reader)):
        response = account.page.goto(f"/kb/{article_id}/")
        assert response.status == 410, f"{who}: ответ {response.status}, ждали 410"
        expect(account.page.locator('[data-kb-page="gone"]')).to_contain_text(GONE)
        expect(account.page.locator(f'article[data-article-id="{article_id}"]')).to_have_count(0)
        expect(account.page.locator("body")).not_to_contain_text(title)
        assert _status(account.page, f"/kb/{article_id}/history/") == 410, f"{who}: история статьи в корзине открыта"
