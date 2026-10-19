"""T-5150: сценарий 11 — права и роли: кто читает, пишет, управляет (FR-401, FR-405, FR-406, FR-407, FR-408, FR-409,
FR-411, FR-412).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md разделы 10.7, 11, 12, 16, 17):
- читатель — роль «Руководитель» (без прав базы знаний), редактор — «Сотрудник ИТ» (`knowledge.edit`), управляющий —
  администратор круга `admin_page` («Администратор портала»: `knowledge.edit` и `knowledge.manage`);
- права ролей тест меняет только на странице «Роли и права» (`/roles/<id>/`, флажки `permissions`) и возвращает в
  `finally` (`_set_rights`); изменённые роли: «Руководитель» (тест 2), «Сотрудник ИТ» (тест 6), «Администратор
  портала» и «Сотрудник ИТ» (тест 11);
- каждый тест заводит свои рубрику, статьи и людей (названия уникальны); сброса стенда в файле нет;
- отказ по праву — код ответа 403, чужой черновик — 404, статья в корзине у не-управляющего — 410 (10.7, решение 43);
- вне интерфейса: одна `helpers.stand_shell` — в тесте 11 (вызов `seed` миграции `knowledge 0002` на уже созданных ролях).
"""
import re
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_kb, helpers_org, helpers_sd
from tests.e2e.helpers_kb import (
    EDITOR_ROLE, MANAGER_ROLE, READER_ROLE, add_comment, attach_file, create_draft, create_rubric, fill_article_form,
    home_ids, open_article, open_edit, press_publish_in_form, press_save, publish_from_article_page,
    rubric_id_by_name, unique_title)

KB_EDIT = "knowledge.edit"
KB_MANAGE = "knowledge.manage"
EDIT_TITLE = "Редактирование базы знаний"   # подпись права в «Роли и права» (спека, сценарий 11, п. 1)
MANAGE_TITLE = "Управление базой знаний"
MISSING_ARTICLE = 2_000_000_000             # номера, которого на стенде нет
FIRST_TEXT = "Первая версия текста статьи."
SECOND_TEXT = "Вторая версия текста статьи."
SEED_SHELL = (
    "import importlib; from types import SimpleNamespace; from django.apps import apps; "
    "from django.db import connections; "
    "m = importlib.import_module('apps.knowledge.migrations.0002_initial_data'); "
    "m.seed(apps, SimpleNamespace(connection=connections['default'])); print('seed ok')"
)  # решения 37 и A-4 контракта: seed(apps, schema_editor) читает только schema_editor.connection.alias


# --- Помощники файла -------------------------------------------------------------------------------------------

def _rubric(admin_page) -> str:
    """Своя рубрика круга (создаёт управляющий); возвращает название."""
    name = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, name)
    return name


def _published(page, rubric: str, *, title: str | None = None) -> str:
    """Статья, опубликованная автором `page` (нужно право править): черновик, затем «Опубликовать» с изменённым
    текстом — версии [2, 1] (FR-408, FR-410). Возвращает номер статьи."""
    article_id = create_draft(page, title=title or unique_title(), text=FIRST_TEXT, rubric=rubric)
    open_edit(page, article_id)
    fill_article_form(page, text=SECOND_TEXT)
    press_publish_in_form(page)
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    return article_id


def _trash(page, article_id: str) -> None:
    """Удаляет статью в корзину кнопкой страницы статьи (`form[data-form="kb-trash"]`, управляющий); окно
    подтверждения (`hx-confirm`, 11.7) принимается; ждёт состояние `trash`."""
    open_article(page, article_id)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('form[data-form="kb-trash"] button[type=submit]').click()
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()


def _closed_ticket_with_link(admin_page, article_id, article_word: str) -> tuple:
    """Заявка корпоративного заявителя, закрытая администратором с решением, и её связь со статьёй (привязывает
    администратор в разделе «Статьи» карточки по слову `article_word` из заголовка статьи). Возвращает `(номер заявки, номер связи)`; нужна тестам прямых вызовов,
    чтобы порядок проверок на сервере не влиял на ответ (раздел 17 п. 60)."""
    helpers_sd.ensure_ready(admin_page)
    word = helpers_kb.unique_word("tk")
    msg = MIMEText(f"Описание сбоя {word}", "plain", "utf-8")
    msg["From"] = helpers_sd.requester_email()
    msg["To"] = helpers_sd.MAILBOX
    msg["Subject"] = Header(f"Права базы знаний {word}", "utf-8")
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain="client.test")
    helpers_sd.deliver(msg.as_bytes())
    number = helpers_sd.ticket_number_by_subject(admin_page, word)
    helpers_sd.open_ticket(admin_page, number)
    admin_page.locator('a[data-action="ticket-close"]').click()
    dialog = admin_page.locator('[data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(f"Решено {word}")
    dialog.locator("button[type=submit]").click()
    expect(admin_page.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute("data-kind", "closed")
    # связь: поиск статьи по названию в форме «Привязать статью»
    part = admin_page.locator('div[data-card-part="kb-articles"]')
    part.locator('form[data-form="kb-link"] input[name="pick"]').fill(article_word)
    row = part.locator(f'ul[data-kb-pick-results] li[data-article-id="{article_id}"]')
    expect(row).to_have_count(1)
    row.locator('button[data-action="kb-link-add"]').click()
    link = admin_page.locator('div[data-card-part="kb-articles"]').locator(
        f'li[data-link-id][data-article-id="{article_id}"]')
    expect(link).to_have_count(1)
    return number, link.get_attribute("data-link-id")


def _role_page(page, role_name: str):
    """Открывает страницу роли `/roles/<id>/`; возвращает `(номер роли, локатор формы роли)`."""
    role_id = helpers_org.role_id(page, role_name)
    page.goto(f"/roles/{role_id}/")
    form = page.locator(f'form[action="/roles/{role_id}/"]')
    expect(form).to_be_visible()
    return role_id, form


def _right(form, code: str):
    return form.locator(f'input[name=permissions][value="{code}"]')


def _checked_codes(page, role_name: str) -> set:
    """Коды прав, отмеченные у роли на её странице."""
    _, form = _role_page(page, role_name)
    return {box.get_attribute("value") for box in form.locator("input[name=permissions]:checked").all()}


def _set_rights(page, role_name: str, *, edit: bool | None = None, manage: bool | None = None) -> None:
    """Выставляет права базы знаний роли на странице «Роли и права» (`None` — не трогать), сохраняет и проверяет
    повторным открытием страницы роли."""
    _, form = _role_page(page, role_name)
    if edit is not None:
        _right(form, KB_EDIT).set_checked(edit)
    if manage is not None:
        _right(form, KB_MANAGE).set_checked(manage)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    _, form = _role_page(page, role_name)
    if edit is not None:
        expect(_right(form, KB_EDIT)).to_be_checked(checked=edit)
    if manage is not None:
        expect(_right(form, KB_MANAGE)).to_be_checked(checked=manage)


def _dismiss_employee(page, user_id: str) -> None:
    """Увольняет сотрудника из его карточки (диалог и подтверждение, срез 002); ждёт отметку «уволен»."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_k11_roles_after_install_have_kb_rights_for_admin_and_it_employee_and_chief_has_none(admin_page):
    """Сценарий 11, п. 1: на странице «Роли и права» у «Администратор портала» отмечены «Редактирование базы
    знаний» и «Управление базой знаний», у «Сотрудник ИТ» — только «Редактирование», у «Руководитель» новых прав
    нет (FR-406)."""
    page = admin_page
    expected = {MANAGER_ROLE: (True, True), EDITOR_ROLE: (True, False), READER_ROLE: (False, False)}
    for role_name, (edit, manage) in expected.items():
        # п. 1: открывает права роли
        _, form = _role_page(page, role_name)
        # оба права названы в списке прав своими подписями (по одному на странице роли)
        expect(form.get_by_label(EDIT_TITLE, exact=True)).to_have_count(1)
        expect(form.get_by_label(MANAGE_TITLE, exact=True)).to_have_count(1)
        # п. 1: отмечены ровно те, что названы
        expect(_right(form, KB_EDIT)).to_be_checked(checked=edit)
        expect(_right(form, KB_MANAGE)).to_be_checked(checked=manage)


def test_k11_admin_grants_edit_right_to_chief_in_interface_and_chief_opens_new_article_without_code(
        admin_page, employee):
    """Сценарий 11, п. 2: администратор выдал роли «Руководитель» право «Редактирование базы знаний» в интерфейсе;
    руководитель открывает «Новая статья» — страница доступна без правки кода и перезапуска; после снятия права
    снова 403 (FR-406)."""
    rubric = _rubric(admin_page)
    chief = helpers_kb.make_reader(employee)
    page = chief.page
    # до выдачи: страница закрыта, ссылки нет
    assert page.goto("/kb/new/").status == 403, "руководитель без права открыл «Новая статья»"
    page.goto("/kb/")
    expect(page.locator('[data-kb-page="home"]')).to_be_visible()
    expect(page.locator('a[data-action="kb-new-article"]')).to_have_count(0)
    try:
        # п. 2: администратор выдаёт право в интерфейсе «Роли и права»
        _set_rights(admin_page, READER_ROLE, edit=True)
        # п. 2: «Новая статья» доступна на следующем запросе, без повторного входа
        response = page.goto("/kb/new/")
        assert response.status == 200, "после выдачи права «Новая статья» недоступна"
        expect(page.locator('[data-kb-page="new"]')).to_be_visible()
        expect(helpers_kb.article_form(page)).to_be_visible()
        page.goto("/kb/")
        # на пустой базе таких ссылок две (шапка и пустое состояние, 11.2), поэтому `.first`
        expect(page.locator('a[data-action="kb-new-article"]').first).to_be_visible()
        # и пользоваться правом можно: черновик сохраняется
        article_id = create_draft(page, title=unique_title(), rubric=rubric)
        expect(page.locator('[data-kb-page="edit"]')).to_be_visible()
        assert article_id
    finally:
        _set_rights(admin_page, READER_ROLE, edit=False)
    assert page.goto("/kb/new/").status == 403, "после снятия права «Новая статья» осталась доступной"


def test_k11_reader_without_kb_rights_reads_article_without_edit_delete_new_restore_buttons_with_history_and_compare(
        admin_page, employee):
    """Сценарий 11, п. 3: сотрудник без прав базы знаний читает опубликованную статью: страница доступна, кнопок
    «Править», «Удалить», «Новая статья», «Восстановить эту версию» нет, а «История» и сравнение версий
    доступны (FR-407, FR-411, FR-412)."""
    rubric = _rubric(admin_page)
    article = _published(admin_page, rubric)
    reader = helpers_kb.make_reader(employee)
    page = reader.page
    # п. 3: читает опубликованную статью
    response = page.goto(f"/kb/{article}/")
    assert response.status == 200
    expect(page.locator(f'article[data-article-id="{article}"][data-article-state="published"]')).to_be_visible()
    expect(page.locator('[data-field="body"]')).to_contain_text(SECOND_TEXT)
    # п. 3: «Править», «Удалить» нет
    expect(page.locator('a[data-action="kb-edit"]')).to_have_count(0)
    expect(page.locator('form[data-form="kb-trash"]')).to_have_count(0)
    # п. 3: «Новая статья» нет
    page.goto("/kb/")
    expect(page.locator('[data-kb-page="home"]')).to_be_visible()
    expect(page.locator('a[data-action="kb-new-article"]')).to_have_count(0)
    # контроль: у правящего те же кнопки есть, значит отсутствие у читателя — следствие права
    open_article(admin_page, article)
    expect(admin_page.locator('a[data-action="kb-edit"]')).to_have_count(1)
    expect(admin_page.locator('form[data-form="kb-trash"]')).to_have_count(1)
    # п. 3: «История» доступна
    open_article(page, article)
    expect(page.locator('a[data-action="kb-history"]').first).to_be_visible()
    assert helpers_kb.history_versions(page, article) == [2, 1]
    # п. 3: сравнение двух версий доступно
    page.locator('tr[data-version="2"] input[name="v"]').check()
    page.locator('tr[data-version="1"] input[name="v"]').check()
    page.locator('button[data-action="kb-compare"]').click()
    page.wait_for_url(re.compile(rf"/kb/{article}/compare/"))
    expect(page.locator('[data-kb-page="compare"]')).to_be_visible()
    expect(page.locator("[data-kb-diff]")).to_contain_text("Вторая версия")
    # п. 3: просмотр старой версии доступен, «Восстановить эту версию» и «Удалить версию» нет
    response = page.goto(f"/kb/{article}/versions/1/")
    assert response.status == 200
    expect(page.locator('[data-kb-page="version"]')).to_be_visible()
    expect(page.locator('form[data-form="kb-version-restore"]')).to_have_count(0)
    expect(page.locator('form[data-form="kb-version-delete"]')).to_have_count(0)
    # контроль: у управляющего на той же версии обе кнопки есть
    admin_page.goto(f"/kb/{article}/versions/1/")
    expect(admin_page.locator('[data-kb-page="version"]')).to_be_visible()
    expect(admin_page.locator('form[data-form="kb-version-restore"] button[data-action="kb-restore-version"]')
           ).to_have_count(1)
    expect(admin_page.locator('form[data-form="kb-version-delete"]')).to_have_count(1)
    # п. 3: правка по прямой ссылке закрыта правом
    assert page.goto(f"/kb/{article}/edit/").status == 403


def test_k11_it_employee_edits_foreign_published_article_and_edit_is_accepted(admin_page, employee):
    """Сценарий 11, п. 4: «Сотрудник ИТ» с правом «Редактирование базы знаний» правит чужую опубликованную статью —
    правка принята: новый текст на странице, новая версия в истории (FR-407)."""
    rubric = _rubric(admin_page)
    article = _published(admin_page, rubric)  # автор — администратор, для редактора статья чужая
    editor = helpers_kb.make_editor(employee)
    page = editor.page
    # п. 4: открывает правку чужой опубликованной статьи
    open_edit(page, article)
    new_text = "Правка сотрудника ИТ принята."
    fill_article_form(page, text=new_text)
    press_save(page)
    # п. 4: правка принята
    page.wait_for_url(re.compile(rf"/kb/{article}/$"))
    expect(page.locator(f'article[data-article-id="{article}"][data-article-state="published"]')).to_be_visible()
    expect(page.locator('[data-field="body"]')).to_contain_text(new_text)
    assert helpers_kb.history_versions(page, article) == [3, 2, 1], "правка чужой статьи не создала версию 3"
    # правку видит и автор
    open_article(admin_page, article)
    expect(admin_page.locator('[data-field="body"]')).to_contain_text(new_text)


def test_k11_it_employee_opening_foreign_draft_or_trash_by_direct_link_is_denied(admin_page, employee):
    """Сценарий 11, п. 5: «Сотрудник ИТ» открывает чужой черновик или корзину по прямой ссылке — отказ: чужой
    черновик — 404 как у несуществующей статьи, статья в корзине — 410 «Статья удалена» без данных статьи, список
    корзины — 403 (FR-407, FR-409)."""
    rubric = _rubric(admin_page)
    draft_title = unique_title("Чужой черновик")
    draft = create_draft(admin_page, title=draft_title, rubric=rubric)
    trashed_title = unique_title("Чужая корзина")
    trashed = _published(admin_page, rubric, title=trashed_title)
    _trash(admin_page, trashed)
    editor = helpers_kb.make_editor(employee)
    page = editor.page
    tails = ("", "edit/", "history/", "versions/1/", "compare/?v=1&v=2")
    # п. 5: чужой черновик — 404, как несуществующая статья, без данных
    assert page.goto(f"/kb/{MISSING_ARTICLE}/").status == 404
    for tail in tails:
        response = page.goto(f"/kb/{draft}/{tail}")
        assert response.status == 404, f"чужой черновик /kb/{draft}/{tail}: код {response.status}, нужен 404"
        assert draft_title not in page.content(), f"в ответе 404 есть заголовок чужого черновика ({tail})"
    # черновика нет и в списках редактора
    assert draft not in home_ids(page, "my-drafts")
    assert home_ids(page, "all-drafts") == []
    # п. 5: корзина — 410 «Статья удалена», без заголовка и текста
    for tail in tails:
        response = page.goto(f"/kb/{trashed}/{tail}")
        assert response.status == 410, f"корзина /kb/{trashed}/{tail}: код {response.status}, нужен 410"
        expect(page.locator('[data-kb-page="gone"]')).to_be_visible()
        expect(page.locator('[data-kb-page="gone"]')).to_contain_text("Статья удалена")
        assert trashed_title not in page.content(), f"в ответе 410 есть заголовок статьи из корзины ({tail})"
    # п. 5: список корзины закрыт
    assert page.goto("/kb/trash/").status == 403


def test_k11_author_who_lost_edit_right_is_denied_own_draft_while_manager_sees_and_publishes_it(
        admin_page, employee):
    """Сценарий 11, п. 6: автор потерял право «Редактирование базы знаний» — его собственный черновик ему закрыт
    (404), а управляющий видит его в «Черновики» и публикует (FR-407, FR-408)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    title = unique_title("Черновик автора")
    draft = create_draft(page, title=title, rubric=rubric)
    try:
        # п. 6: автор теряет право (администратор снимает его у роли «Сотрудник ИТ»)
        _set_rights(admin_page, EDITOR_ROLE, edit=False)
        # п. 6: свой черновик открыть нельзя
        for tail in ("", "edit/"):
            response = page.goto(f"/kb/{draft}/{tail}")
            assert response.status == 404, f"автор без права: /kb/{draft}/{tail} — код {response.status}, нужен 404"
            assert title not in page.content()
        assert page.goto("/kb/new/").status == 403
        # п. 6: управляющий видит черновик в «Черновики» и открывает его
        assert draft in home_ids(admin_page, "all-drafts")
        open_article(admin_page, draft)
        expect(admin_page.locator(f'article[data-article-id="{draft}"][data-article-state="draft"]')).to_be_visible()
        # п. 6: управляющий публикует
        publish_from_article_page(admin_page, draft)
        # опубликованную статью автор без права читает как все
        assert page.goto(f"/kb/{draft}/").status == 200
        expect(page.locator('[data-field="body"]')).to_be_visible()
    finally:
        _set_rights(admin_page, EDITOR_ROLE, edit=True)


def test_k11_manager_sees_foreign_drafts_and_trash_edits_rubrics_and_deletes_foreign_comments(
        admin_page, employee):
    """Сценарий 11, п. 7: управляющий открывает «Черновики» и корзину — видит чужие черновики и статьи в корзине,
    правит рубрики и удаляет чужие комментарии; у читателя кнопки удаления чужого комментария нет
    (FR-406, FR-407)."""
    rubric = _rubric(admin_page)
    editor = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    draft = create_draft(editor.page, title=unique_title("Чужой черновик"), rubric=rubric)
    published = _published(editor.page, rubric)
    trashed = _published(editor.page, rubric)
    _trash(admin_page, trashed)
    # п. 7: «Черновики» — чужой черновик виден и открывается
    assert draft in home_ids(admin_page, "all-drafts")
    assert admin_page.goto(f"/kb/{draft}/").status == 200
    expect(admin_page.locator(f'article[data-article-id="{draft}"][data-article-state="draft"]')).to_be_visible()
    # п. 7: корзина — чужая статья видна и открывается
    admin_page.goto("/kb/trash/")
    expect(admin_page.locator('[data-kb-page="trash"]')).to_be_visible()
    expect(admin_page.locator(f'[data-kb-trash-list] tr[data-article-id="{trashed}"]')).to_have_count(1)
    assert admin_page.goto(f"/kb/{trashed}/").status == 200
    expect(admin_page.locator('[data-kb-trash-mark]')).to_be_visible()
    # п. 7: правит рубрики (переименование)
    rubric_id = rubric_id_by_name(admin_page, rubric)
    renamed = helpers_org.unique_name("Переименована")
    admin_page.goto("/kb/rubrics/")
    row = admin_page.locator(f'[data-kb-rubrics] li[data-rubric-id="{rubric_id}"]')
    rename = row.locator('form[data-form="kb-rubric-rename"]').first
    rename.locator("input[name=name]").fill(renamed)
    rename.locator("button[type=submit]").click()
    expect(row.locator('[data-field="name"]').first).to_contain_text(renamed)
    assert rubric_id_by_name(admin_page, renamed) == rubric_id
    # п. 7: чужой комментарий — читатель кнопки удаления не видит, управляющий удаляет
    text = f"Комментарий редактора {helpers_kb.unique_word()}"
    comment = add_comment(editor.page, published, text)
    open_article(reader.page, published)
    reader_row = reader.page.locator(f'[data-kb-comment-list] li[data-comment-id="{comment}"]')
    expect(reader_row).to_be_visible()
    expect(reader_row.locator('button[data-action="kb-comment-delete"]')).to_have_count(0)
    open_article(admin_page, published)
    manager_row = admin_page.locator(f'[data-kb-comment-list] li[data-comment-id="{comment}"]')
    expect(manager_row).to_be_visible()
    admin_page.once("dialog", lambda dialog: dialog.accept())
    manager_row.locator('button[data-action="kb-comment-delete"]').click()
    expect(manager_row).to_have_count(0)
    open_article(admin_page, published)
    expect(admin_page.locator(f'[data-kb-comment-list] li[data-comment-id="{comment}"]')).to_have_count(0)


def test_k11_requester_and_cc_participant_cannot_open_article_address_because_they_have_no_portal_login(
        admin_page, new_context):
    """Сценарий 11, п. 8: заявитель и участник из копии заявки пытаются открыть адрес статьи — входа нет: адрес
    ведёт на страницу входа, их адрес с любым паролем в портал не пускает, статья им не показывается; в портал они
    не входят (REQ-CTX, ADR-0012 п. 7) (FR-409)."""
    rubric = _rubric(admin_page)
    title = unique_title("Статья для заявителя")
    article = _published(admin_page, rubric, title=title)
    for who, email in (("заявитель", helpers_sd.requester_email("req")), ("участник из копии", helpers_sd.requester_email("cc"))):
        page = new_context().new_page()
        # п. 8: открывает адрес статьи без входа — страница входа
        page.goto(f"/kb/{article}/")
        expect(page).to_have_url(re.compile(r"/login/"))
        assert title not in page.content(), f"{who}: заголовок статьи показан без входа"
        # п. 8: вход адресом заявителя невозможен: второго шага нет, шапки портала нет
        helpers.fill_login(page, email, factories.new_password())
        expect(page).to_have_url(re.compile(r"/login/"))   # отказ общий, как у неизвестного адреса: страница входа
        expect(page.locator("[role=alert]").first).to_be_visible()
        assert page.locator("input[name=code]").count() == 0, f"{who}: пустило на ввод кода"
        expect(page.locator("#top-bar")).to_have_count(0)
        # п. 8: после попытки входа адрес статьи по-прежнему ведёт на вход
        page.goto(f"/kb/{article}/")
        expect(page).to_have_url(re.compile(r"/login/"))
        assert title not in page.content(), f"{who}: заголовок статьи показан после попытки входа"


def test_k11_each_kb_action_called_directly_without_button_is_checked_for_right_on_server(admin_page, employee):
    """Сценарий 11, п. 9: любое действие базы знаний, вызванное напрямую без кнопки, проверяется по праву на
    сервере: читатель получает 403 на всё, что требует права править или управлять, редактор — 403 на всё
    управляющее; после этого статья, версии, рубрика, комментарий, вложение и срок корзины прежние (FR-409)."""
    direct_get, direct_post = helpers_org.direct_get, helpers_org.direct_post
    rubric_name = _rubric(admin_page)
    rubric_id = rubric_id_by_name(admin_page, rubric_name)
    title = unique_title()
    article = _published(admin_page, rubric_name, title=title)
    ticket, link_id = _closed_ticket_with_link(admin_page, article, title.split()[-1])
    new_title = unique_title("Новая без права")
    file_id = attach_file(admin_page, article, b"note for rights test", "note.txt", mime="text/plain")
    comment = add_comment(admin_page, article, f"Комментарий управляющего {helpers_kb.unique_word()}")
    admin_page.goto("/kb/settings/")
    days_before = admin_page.locator("input[name=trash_days]").input_value()
    reader = helpers_kb.make_reader(employee)
    editor = helpers_kb.make_editor(employee)
    base = f"/kb/{article}"
    edit_form = {"title": title + " чужая правка", "text": "Текст не должен сохраниться", "rubric": rubric_id,
                 "tags": "", "comment": "", "base_version": "2", "action": "save"}
    # действия, которые требуют права «Редактирование базы знаний»: читателю — 403
    needs_edit = [
        ("GET", "/kb/new/", None),
        ("POST", "/kb/new/", {**edit_form, "title": new_title, "action": "save"}),
        ("GET", f"{base}/edit/", None),
        ("POST", f"{base}/edit/", edit_form),
        ("POST", f"{base}/publish/", {"base_version": "2"}),
        ("POST", f"{base}/versions/1/restore/", {}),
        ("POST", f"{base}/files/", {}),
        ("POST", f"{base}/files/{file_id}/delete/", {}),
        ("POST", "/kb/preview/", {"text": "Текст предпросмотра"}),
        ("GET", "/kb/tags/suggest/?q=ab", None),
        # связи и «Статья из решения»: заявка закрыта с решением, связь есть — отказ идёт по праву (раздел 17 п. 60)
        ("POST", "/kb/links/", {"article": article, "ticket": str(ticket)}),
        ("POST", f"/kb/links/{link_id}/delete/", {}),
        ("POST", f"/kb/from-ticket/{ticket}/", {}),
    ]
    # GET на «Статью из решения» — 405 любому: метод проверяется раньше права (10.2, раздел 17 п. 60)
    assert direct_get(reader.page, f"/kb/from-ticket/{ticket}/").status == 405
    # действия, которые требуют права «Управление базой знаний»: читателю и редактору — 403
    needs_manage = [
        ("POST", f"{base}/trash/", {}),
        ("POST", f"{base}/restore/", {}),
        ("POST", f"{base}/purge/", {}),
        ("POST", f"{base}/versions/1/delete/", {}),
        ("GET", "/kb/trash/", None),
        ("GET", "/kb/settings/", None),
        ("POST", "/kb/settings/", {"trash_days": "30"}),
        ("GET", "/kb/rubrics/", None),
        ("POST", "/kb/rubrics/new/", {"name": helpers_org.unique_name("Рубрика без права"), "parent": ""}),
        ("POST", f"/kb/rubrics/{rubric_id}/rename/", {"name": helpers_org.unique_name("Переименование без права")}),
        ("POST", f"/kb/rubrics/{rubric_id}/move/", {"parent": ""}),
        ("POST", f"/kb/rubrics/{rubric_id}/delete/", {}),
        ("POST", f"/kb/comments/{comment}/delete/", {}),  # чужой комментарий — только управляющий
    ]

    def call(page, method, path, data):
        return direct_get(page, path) if method == "GET" else direct_post(page, path, data)

    for who, page, calls in (("читатель", reader.page, needs_edit + needs_manage),
                             ("редактор", editor.page, needs_manage)):
        for method, path, data in calls:
            status = call(page, method, path, data).status
            assert status == 403, f"{who}: {method} {path} напрямую — код {status}, нужен 403"
    # после всех отказов в базе знаний ничего не изменилось
    # статьи из попытки `POST /kb/new/` нет ни среди черновиков, ни среди своих черновиков управляющего (п. 54: свежий
    # черновик был бы в блоке); из заявки черновик тоже не создан
    admin_page.goto("/kb/")
    expect(admin_page.locator('[data-kb-page="home"]')).to_be_visible()
    expect(admin_page.locator('[data-kb-page="home"]')).not_to_contain_text(new_title)
    helpers_sd.open_ticket(admin_page, ticket)
    expect(admin_page.locator('div[data-card-part="kb-articles"]').locator(
        f'li[data-link-id="{link_id}"][data-article-id="{article}"]')).to_have_count(1)
    expect(admin_page.locator('div[data-card-part="kb-articles"] li[data-link-id]')).to_have_count(1)
    open_article(admin_page, article)
    expect(admin_page.locator('h1[data-field="title"]')).to_have_text(title)
    expect(admin_page.locator(f'article[data-article-id="{article}"][data-article-state="published"]')
           ).to_be_visible()
    expect(admin_page.locator('[data-field="body"]')).to_contain_text(SECOND_TEXT)
    assert helpers_kb.history_versions(admin_page, article) == [2, 1]
    assert rubric_id_by_name(admin_page, rubric_name) == rubric_id
    open_article(admin_page, article)
    expect(admin_page.locator(f'[data-kb-comment-list] li[data-comment-id="{comment}"]')).to_have_count(1)
    open_edit(admin_page, article)
    expect(helpers_kb.file_row(admin_page, file_id)).to_have_count(1)
    admin_page.goto("/kb/settings/")
    assert admin_page.locator("input[name=trash_days]").input_value() == days_before


def test_k11_left_menu_has_kb_section_for_employee_without_kb_rights(admin_page, employee, new_context):
    """Сценарий 11, п. 10: в левом меню вошедшего сотрудника без прав базы знаний есть раздел «База знаний» и он
    открывается; у того, кто не вошёл (заявитель), портала нет — адрес ведёт на вход (FR-405)."""
    reader = helpers_kb.make_reader(employee)
    page = reader.page
    # п. 10: смотрит левое меню
    page.goto("/me/")
    menu = page.locator('#main-menu a[href="/kb/"]')
    expect(menu).to_have_count(1)
    expect(menu).to_contain_text("База знаний")
    # раздел открывается; прав на запись и корзину у читателя нет
    menu.click()
    page.wait_for_url(re.compile(r"/kb/$"))
    expect(page.locator('[data-kb-page="home"]')).to_be_visible()
    expect(page.locator('a[data-action="kb-new-article"]')).to_have_count(0)
    expect(page.locator('a[data-action="kb-trash-link"]')).to_have_count(0)
    # положительный контроль: у управляющего ссылка «Корзина» есть (11.2)
    admin_page.goto("/kb/")
    expect(admin_page.locator('a[data-action="kb-trash-link"]')).to_have_count(1)
    # п. 10: у заявителя входа в портал нет
    guest = new_context().new_page()
    guest.goto("/kb/")
    expect(guest).to_have_url(re.compile(r"/login/"))
    expect(guest.locator("#main-menu")).to_have_count(0)


def test_k11_portal_updated_to_this_slice_has_admin_and_it_employee_rights_not_only_new_installs(admin_page):
    """Сценарий 11, п. 11: на работающем портале с уже созданными ролями после обновления роль «Администратор
    портала» получила оба права, «Сотрудник ИТ» — «Редактирование базы знаний», «Руководитель» — ничего; прежние
    права ролей остались. Состояние «до обновления» воспроизводится снятием двух прав через «Роли и права», а
    обновление — вызовом функции данных миграции `knowledge 0002` (`stand_shell`) (FR-406)."""
    page = admin_page
    before = {role: _checked_codes(page, role) for role in (MANAGER_ROLE, EDITOR_ROLE, READER_ROLE)}
    prior = {role: codes - {KB_EDIT, KB_MANAGE} for role, codes in before.items()}
    try:
        # состояние до обновления: у встроенных ролей прав базы знаний нет, остальные права на месте
        _set_rights(page, MANAGER_ROLE, edit=False, manage=False)
        _set_rights(page, EDITOR_ROLE, edit=False, manage=False)
        for role in (MANAGER_ROLE, EDITOR_ROLE):
            assert not ({KB_EDIT, KB_MANAGE} & _checked_codes(page, role)), f"{role}: права не сняты"
            assert _checked_codes(page, role) == prior[role]
        # обновление до этого среза: данные миграции на уже созданных ролях
        output = helpers.stand_shell(SEED_SHELL)
        assert "seed ok" in output, "функция данных миграции knowledge 0002 не выполнилась"
        # п. 11: «Администратор портала» — оба права, «Сотрудник ИТ» — только «Редактирование»
        for role, (edit, manage) in {MANAGER_ROLE: (True, True), EDITOR_ROLE: (True, False),
                                     READER_ROLE: (False, False)}.items():
            _, form = _role_page(page, role)
            expect(_right(form, KB_EDIT)).to_be_checked(checked=edit)
            expect(_right(form, KB_MANAGE)).to_be_checked(checked=manage)
        # п. 11: прежние права ролей остались (выдача добавляет, а не заменяет)
        for role in (MANAGER_ROLE, EDITOR_ROLE, READER_ROLE):
            assert _checked_codes(page, role) - {KB_EDIT, KB_MANAGE} == prior[role], f"{role}: прежние права изменились"
    finally:
        _set_rights(page, MANAGER_ROLE, edit=KB_EDIT in before[MANAGER_ROLE], manage=KB_MANAGE in before[MANAGER_ROLE])
        _set_rights(page, EDITOR_ROLE, edit=KB_EDIT in before[EDITOR_ROLE], manage=KB_MANAGE in before[EDITOR_ROLE])


def test_k11_dismissed_draft_author_draft_is_visible_to_manager_who_publishes_or_deletes_it_with_dismissed_mark(
        admin_page, employee):
    """Сценарий 11, п. 12: автор черновика уволен — управляющий видит его черновики в «Черновики» и может
    опубликовать один и удалить другой; автор статьи, «изменено» и версии показаны ФИО с пометкой «уволен»
    (FR-401, FR-407)."""
    rubric = _rubric(admin_page)
    surname = helpers_org.unique_name("Дроздов")
    author = helpers_kb.make_editor(employee, full_name=f"{surname} Иван Петрович")
    to_publish = create_draft(author.page, title=unique_title("Черновик уволенного"), rubric=rubric)
    to_delete = create_draft(author.page, title=unique_title("Черновик уволенного"), rubric=rubric)
    # п. 12: автор уволен
    _dismiss_employee(admin_page, author.id)
    # п. 12: управляющий видит оба черновика
    drafts = home_ids(admin_page, "all-drafts")
    assert to_publish in drafts and to_delete in drafts, "черновики уволенного автора не видны управляющему"
    # п. 12: автор статьи и «изменено» — ФИО с пометкой «уволен»
    open_article(admin_page, to_publish)
    article = admin_page.locator(f'article[data-article-id="{to_publish}"]')
    expect(article.locator('[data-field="author"] span[data-dismissed="true"]')).to_be_visible()
    expect(article.locator('[data-field="author"]')).to_contain_text("уволен")
    expect(article.locator('[data-field="author"]')).to_contain_text(surname)
    expect(article.locator('[data-field="updated"] span[data-dismissed="true"]')).to_be_visible()
    # п. 12: версия 1 в истории — тоже с пометкой
    helpers_kb.open_history(admin_page, to_publish)
    version_author = admin_page.locator('tr[data-version="1"] [data-field="author"]')
    expect(version_author.locator('span[data-dismissed="true"]')).to_be_visible()
    expect(version_author).to_contain_text("уволен")
    # п. 12: управляющий публикует один черновик
    publish_from_article_page(admin_page, to_publish)
    expect(admin_page.locator(f'article[data-article-id="{to_publish}"] [data-field="author"] '
                              f'span[data-dismissed="true"]')).to_be_visible()
    # п. 12: и удаляет другой — он в корзине с пометкой автора «уволен» на странице статьи
    open_article(admin_page, to_delete)
    expect(admin_page.locator(f'article[data-article-id="{to_delete}"] [data-field="author"] '
                              f'span[data-dismissed="true"]')).to_be_visible()
    _trash(admin_page, to_delete)
    admin_page.goto("/kb/trash/")
    expect(admin_page.locator(f'[data-kb-trash-list] tr[data-article-id="{to_delete}"]')).to_have_count(1)
    assert to_delete not in home_ids(admin_page, "all-drafts")
