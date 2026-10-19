"""T-5140: сценарий 1 — автор пишет статью: черновик, Markdown с кнопками, предпросмотр, публикация
(FR-401, FR-402, FR-403, FR-404, FR-406, FR-407, FR-408, FR-409, FR-410, FR-421, FR-422, FR-423, FR-438, FR-447,
NFR-405, NFR-406).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md):
- каждый тест заводит своих сотрудников (редактор — «Сотрудник ИТ», читатель — «Руководитель», управляющий —
  администратор круга `admin_page`), свою рубрику и свои статьи; названия уникальны (`helpers_kb.unique_title`);
  общих настроек тесты файла не меняют, сброса стенда в файле нет (данные круга общие);
- первое сохранение новой статьи ведёт на `/kb/<id>/edit/` (решение C-2), дальнейшие — на `/kb/<id>/`;
- «Опубликовать» без ПДн: тексты тестов не содержат похожего на адрес почты или телефон.
"""
import re

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org
from tests.e2e.helpers_kb import (
    article_form, article_id_from_url, create_draft, create_rubric, fill_article_form, home_ids, open_article,
    open_edit, open_new_article, open_preview, open_text_tab, press_publish_in_form, press_save, unique_title)

MISSING_ARTICLE = 2_000_000_000  # номер, которого на стенде нет (в пределах целого PostgreSQL)
SAMPLE_TEXT = (
    "# Заголовок раздела\n\n- пункт один\n- пункт два\n\n```\nvpn connect corp\n```\n\n"
    "| столбец а | столбец б |\n|---|---|\n| один | два |\n"
)
TOOLBAR = ("bold", "italic", "heading", "list", "olist", "code", "link", "table", "image")
IGNORED_TAGS = {"DIV", "SPAN", "SECTION", "ARTICLE"}  # оболочки, которыми предпросмотр и статья могут различаться


def _rubric(admin_page) -> str:
    """Своя рубрика круга (создаёт управляющий); возвращает название."""
    name = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, name)
    return name


def _norm(text: str) -> str:
    """Текст без различий в пробелах и переводах строк."""
    return " ".join(text.split())


def _tag_set(locator) -> set:
    """Множество имён тегов внутри элемента (без оболочек `IGNORED_TAGS`)."""
    names = locator.evaluate("el => Array.from(el.querySelectorAll('*')).map(e => e.tagName)")
    return set(names) - IGNORED_TAGS


def _lift_limits(page) -> None:
    """Снимает `maxlength` с полей заголовка и текста: ввод длиннее предела браузер мог бы обрезать, а проверка
    предела — дело сервера (так форму отправил бы обход браузера)."""
    form = article_form(page)
    form.locator("input[name=title]").evaluate("el => el.removeAttribute('maxlength')")
    form.locator("textarea[name=text]").evaluate("el => el.removeAttribute('maxlength')")


def test_k01_form_has_fields_toolbar_and_preview_tab_with_attach_and_image_buttons_disabled_before_first_save(
        admin_page, employee):
    """Сценарий 1, п. 1: на «Новая статья» есть заголовок, рубрика, теги, поле текста, панель из девяти кнопок и
    вкладки «Текст» и «Предпросмотр»; «Вложить» и «Картинка» неактивны с подсказкой «Сохраните черновик»
    (FR-401, FR-403, FR-422)."""
    _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    # п. 1: открывает «Новая статья» — кнопка на главной ведёт на форму
    page.goto("/kb/")
    page.locator('a[data-action="kb-new-article"]').first.click()
    page.wait_for_url(re.compile(r"/kb/new/$"))
    form = article_form(page)
    expect(form.locator("input[name=title]")).to_be_visible()
    expect(form.locator("select[name=rubric]")).to_be_visible()
    expect(form.locator("input[name=tags]")).to_be_visible()
    expect(form.locator("textarea[name=text]")).to_be_visible()
    toolbar = page.locator("[data-kb-toolbar]")
    expect(toolbar).to_be_visible()
    for name in TOOLBAR:
        expect(toolbar.locator(f'button[data-md="{name}"]')).to_have_count(1)
    expect(page.locator('button[data-kb-tab="text"]')).to_have_text("Текст")
    expect(page.locator('button[data-kb-tab="preview"]')).to_have_text("Предпросмотр")
    # п. 1: «Вложить» и «Картинка» до первого сохранения неактивны, подсказка видна
    expect(page.locator('button[data-action="kb-attach"]')).to_be_disabled()
    expect(page.locator('button[data-md="image"]')).to_be_disabled()
    expect(page.locator('button[data-md="image"]')).to_have_attribute("title", helpers_kb.SAVE_HINT)
    expect(page.locator('[data-kb-hint="save-draft"]')).to_contain_text(helpers_kb.SAVE_HINT)
    # на новой статье кнопки «Опубликовать» нет: публикуют после первого сохранения
    expect(form.locator('button[data-action="kb-publish"]')).to_have_count(0)


def test_k01_toolbar_buttons_insert_markdown_markup_into_text_field(admin_page, employee):
    """Сценарий 1, п. 1 (текст «кнопками панели»): кнопки панели вставляют разметку Markdown в поле текста, а
    выделенный текст оборачивают (строки сверяются подстрокой, FR-403)."""
    author = helpers_kb.make_editor(employee)
    page = author.page
    open_new_article(page)
    area = article_form(page).locator("textarea[name=text]")
    inserted = {"bold": "**", "italic": "*", "heading": "# ", "list": "- ", "olist": "1. ", "code": "`",
                "link": "](https://)", "table": "|"}
    for name, markup in inserted.items():
        # п. 1: кнопка «<name>» без выделения вставляет разметку в позицию курсора
        area.fill("")
        page.locator(f'[data-kb-toolbar] button[data-md="{name}"]').click()
        assert markup in area.input_value(), f"кнопка {name}: в поле нет «{markup}»"
    # выделенный текст оборачивается: жирный, курсив, код, ссылка
    wrapped = {"bold": "**слово**", "italic": "*слово*", "code": "`слово`", "link": "[слово](https://)"}
    for name, expected in wrapped.items():
        area.fill("слово")
        area.select_text()
        page.locator(f'[data-kb-toolbar] button[data-md="{name}"]').click()
        assert expected in area.input_value(), f"кнопка {name}: выделенное слово не обёрнуто в «{expected}»"
    # заголовок и списки ставят знак в начало строки
    area.fill("строка")
    area.select_text()
    page.locator('[data-kb-toolbar] button[data-md="heading"]').click()
    assert area.input_value().startswith("# "), "заголовок: знак не в начале строки"
    # таблица — шаблон из двух столбцов с разделителем
    area.fill("")
    page.locator('[data-kb-toolbar] button[data-md="table"]').click()
    assert "---" in area.input_value(), "таблица: в шаблоне нет разделителя"


def test_k01_save_draft_with_empty_title_or_no_rubric_is_refused_with_reason_and_input_kept(admin_page, employee):
    """Сценарий 1, п. 2: пустой заголовок или не выбранная рубрика — сохранения нет, у поля показана причина,
    введённое остаётся (FR-401)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    word = helpers_kb.unique_word()
    # п. 2: пустой заголовок
    open_new_article(page)
    fill_article_form(page, title="", text=f"Текст {word}", rubric=rubric, tags="сеть")
    press_save(page)
    error = page.locator('[data-error="title"][data-code="title_empty"]')
    expect(error).to_contain_text("Введите заголовок")
    assert re.search(r"/kb/new/$", page.url), "после отказа адрес сменился"
    expect(article_form(page).locator("textarea[name=text]")).to_have_value(f"Текст {word}")
    expect(article_form(page).locator("input[name=tags]")).to_have_value("сеть")
    # п. 2: не выбранная рубрика
    title = f"Без рубрики {word}"
    open_new_article(page)
    fill_article_form(page, title=title, text=f"Текст {word}")
    helpers_kb.clear_rubric(page)
    press_save(page)
    error = page.locator('[data-error="rubric"][data-code="rubric_missing"]')
    expect(error).to_contain_text("Выберите рубрику")
    assert re.search(r"/kb/new/$", page.url), "после отказа адрес сменился"
    expect(article_form(page).locator("input[name=title]")).to_have_value(title)
    expect(article_form(page).locator("textarea[name=text]")).to_have_value(f"Текст {word}")
    # п. 2: сохранения нет — в «Мои черновики» этих статей нет
    page.goto("/kb/")
    expect(page.locator('[data-kb-page="home"]')).to_be_visible()
    assert word not in page.locator("body").inner_text(), "статья сохранена, хотя форма отказала"


def test_k01_save_draft_creates_version_1_at_permanent_url_and_hides_it_from_new_changed_rubrics_and_search(
        admin_page, employee):
    """Сценарий 1, п. 3: «Сохранить черновик» — статья в состоянии «черновик», версия 1, постоянный адрес с номером;
    у других её нет в «Новые и изменённые», в рубриках и в поиске (FR-401, FR-404, FR-408, FR-410)."""
    rubric = _rubric(admin_page)
    rubric_id = helpers_kb.rubric_id_by_name(admin_page, rubric)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    title = unique_title()
    word = title.split()[-1]
    page = author.page
    # п. 3: заголовок «Подключение VPN» и текст с заголовком, списком, блоком кода и таблицей
    open_new_article(page)
    fill_article_form(page, title=title, text=SAMPLE_TEXT, rubric=rubric)
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    article_id = article_id_from_url(page.url)
    expect(page.locator("[role=status]").filter(has_text="Черновик сохранён")).to_be_visible()
    # п. 3: постоянный адрес с номером, состояние «черновик»
    open_article(page, article_id)
    root = page.locator(f'article[data-article-id="{article_id}"]')
    expect(root).to_have_attribute("data-article-state", "draft")
    expect(root.locator('h1[data-field="title"]')).to_have_text(title)
    body = root.locator('[data-field="body"]')
    expect(body.locator("h1, h2, h3, h4").first).to_contain_text("Заголовок раздела")
    expect(body.locator("ul li")).to_have_count(2)
    expect(body.locator("pre")).to_contain_text("vpn connect corp")
    expect(body.locator("table")).to_have_count(1)
    # п. 3: версия 1
    assert helpers_kb.history_versions(page, article_id) == [1], "у нового черновика не одна версия под номером 1"
    # п. 3: у других статьи нет — ни в «Новые и изменённые», ни в рубрике, ни в поиске
    other = reader.page
    assert article_id not in home_ids(other, "new-and-changed"), "черновик в «Новые и изменённые» читателя"
    assert article_id not in helpers_kb.rubric_page_ids(other, rubric_id), "черновик на странице рубрики читателя"
    assert not helpers_kb.search_finds(other, word, article_id), "черновик найден поиском читателя"
    assert article_id not in home_ids(author.page, "new-and-changed"), "черновик в «Новые и изменённые» автора"
    assert article_id in home_ids(author.page, "my-drafts"), "своего черновика нет в «Мои черновики»"
    # положительный контроль тех же трёх путей читателя: после публикации статья в них появляется
    helpers_kb.publish_from_article_page(author.page, article_id)
    assert helpers_kb.search_finds(other, word, article_id), "опубликованная статья не найдена поиском читателя"
    assert article_id in home_ids(other, "new-and-changed"), "опубликованной статьи нет в «Новые и изменённые»"
    assert article_id in helpers_kb.rubric_page_ids(other, rubric_id), "опубликованной статьи нет в рубрике"


def test_k01_script_and_javascript_link_are_shown_as_text_in_preview_and_saved_article(admin_page, employee):
    """Сценарий 1, п. 4: `<script>alert(1)</script>` выведен текстом и не выполняется, ссылка `javascript:` не
    работает как ссылка — в «Предпросмотре» и в сохранённой статье (FR-402, NFR-405)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    dialogs: list = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    text = ("<script>alert(1);window.__kb_ran = 1</script>\n\n"
            "[нажми сюда](javascript:window.__kb_ran=2)\n\nконец текста\n")
    open_new_article(page)
    fill_article_form(page, title=unique_title(), text=text, rubric=rubric)

    def check(container):
        # п. 4: скрипт выведен как обычный текст, ссылка с недопустимой схемой не ссылка
        expect(container).to_contain_text("<script>alert(1)")
        expect(container).to_contain_text("нажми сюда")
        assert container.locator("script").count() == 0, "в тексте статьи есть элемент script"
        assert container.locator('a[href*="javascript" i]').count() == 0, "ссылка javascript: осталась ссылкой"
        assert page.evaluate("window.__kb_ran") is None, "скрипт из текста выполнился"
        assert not dialogs, "скрипт из текста открыл окно"

    # п. 4: в «Предпросмотре»
    open_preview(page)
    check(page.locator("[data-kb-panel=preview] [data-kb-preview]"))
    # п. 4: в сохранённой статье
    open_text_tab(page)
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    open_article(page, article_id_from_url(page.url))
    check(page.locator('[data-field="body"]'))


def test_k01_return_from_preview_to_text_tab_keeps_input_and_preview_looks_like_published_article(
        admin_page, employee):
    """Сценарий 1, п. 5: при возврате с «Предпросмотра» на вкладку текста введённое сохранено; вид предпросмотра
    тот же, что у статьи, показанной после сохранения (FR-403)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    title = unique_title()
    open_new_article(page)
    fill_article_form(page, title=title, text=SAMPLE_TEXT, rubric=rubric, tags="впн")
    # п. 5: открыт «Предпросмотр»
    open_preview(page)
    preview = page.locator("[data-kb-panel=preview] [data-kb-preview]")
    preview_tags = _tag_set(preview)
    preview_text = _norm(preview.inner_text())
    # п. 5: возврат на вкладку текста — введённое сохранено
    open_text_tab(page)
    form = article_form(page)
    expect(form.locator("textarea[name=text]")).to_have_value(SAMPLE_TEXT)
    expect(form.locator("input[name=title]")).to_have_value(title)
    expect(form.locator("input[name=tags]")).to_have_value("впн")
    # п. 5: вид тот же, что у сохранённой статьи: те же элементы и тот же текст
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    open_article(page, article_id_from_url(page.url))
    body = page.locator('[data-field="body"]')
    assert _tag_set(body) == preview_tags, "набор элементов предпросмотра и статьи различается"
    assert _norm(body.inner_text()) in preview_text, "текст статьи не совпал с текстом предпросмотра"


def test_k01_publish_without_pdn_makes_article_visible_to_all_in_search_and_new_changed_with_journal_entry(
        admin_page, employee):
    """Сценарий 1, п. 6: «Опубликовать» без похожего на почту или телефон — статья «опубликована», видна всем
    сотрудникам, в поиске и в «Новые и изменённые», в журнале запись «публикация» (FR-408, FR-421, FR-447, FR-438)."""
    rubric = _rubric(admin_page)
    rubric_id = helpers_kb.rubric_id_by_name(admin_page, rubric)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    title = unique_title()
    word = title.split()[-1]
    page = author.page
    article_id = create_draft(page, title=title, text=SAMPLE_TEXT, rubric=rubric)
    # п. 6: нажимает «Опубликовать»; предупреждения ПДн нет, статья «опубликована»
    helpers_kb.publish_from_article_page(page, article_id)
    assert page.locator("[data-kb-pdn]").count() == 0, "предупреждение ПДн на тексте без ПДн"
    # п. 6: видна всем сотрудникам: читатель открывает, находит поиском, видит в списках
    seen = reader.page
    open_article(seen, article_id)
    expect(seen.locator(f'article[data-article-id="{article_id}"]')).to_have_attribute(
        "data-article-state", "published")
    assert helpers_kb.search_finds(seen, word, article_id), "опубликованная статья не найдена поиском"
    assert article_id in home_ids(seen, "new-and-changed"), "статьи нет в «Новые и изменённые»"
    assert article_id in helpers_kb.rubric_page_ids(seen, rubric_id), "статьи нет на странице рубрики"
    # п. 6: в журнале запись «публикация» с номером статьи
    rows = helpers_org.audit_rows(admin_page, "knowledge.article_published", article_id)
    assert len(rows) == 1, f"записей «публикация» по статье {article_id}: {len(rows)}"
    assert "Статья опубликована" in rows[0], f"подпись записи журнала: {rows[0]!r}"


def test_k01_other_editor_opening_foreign_draft_by_direct_url_is_denied_like_missing_article(
        admin_page, employee):
    """Сценарий 1, п. 7: другой сотрудник с правом «Редактирование базы знаний» открывает чужой черновик по
    прямому адресу — отказ, как у несуществующей статьи (FR-407, FR-409)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    other = helpers_kb.make_editor(employee)
    title = unique_title()
    article_id = create_draft(author.page, title=title, text=SAMPLE_TEXT, rubric=rubric)
    word = title.split()[-1]
    # п. 7: прямой адрес чужого черновика — любая страница статьи
    missing = helpers_org.direct_get(other.page, f"/kb/{MISSING_ARTICLE}/")
    assert missing.status == 404, f"несуществующая статья: ответ {missing.status}, ждали 404"
    for path in (f"/kb/{article_id}/", f"/kb/{article_id}/edit/", f"/kb/{article_id}/history/"):
        answer = helpers_org.direct_get(other.page, path)
        assert answer.status == missing.status, f"{path}: ответ {answer.status}, как у несуществующей — {missing.status}"
        assert word not in answer.text(), f"{path}: в ответе есть заголовок чужого черновика"
    # автор свой черновик открывает
    assert helpers_org.direct_get(author.page, f"/kb/{article_id}/").status == 200
    # чужого черновика нет ни в «Мои черновики», ни в «Новые и изменённые» другого редактора
    assert article_id not in home_ids(other.page, "my-drafts")
    assert article_id not in home_ids(other.page, "new-and-changed")


def test_k01_employee_without_edit_right_is_denied_new_article_by_direct_link_and_sees_no_button(
        admin_page, employee):
    """Сценарий 1, п. 8: сотрудник без права «Редактирование базы знаний» по прямой ссылке «Новая статья» получает
    отказ, а кнопка «Новая статья» ему не показана (FR-406, FR-409)."""
    reader = helpers_kb.make_reader(employee)
    editor = helpers_kb.make_editor(employee)
    # п. 8: прямая ссылка — отказ (и на открытие, и на отправку формы)
    assert helpers_org.direct_get(reader.page, "/kb/new/").status == 403, "GET /kb/new/ читателю: не 403"
    answer = helpers_org.direct_post(reader.page, "/kb/new/", {"title": "x", "text": "x", "rubric": "1"})
    assert answer.status == 403, f"POST /kb/new/ читателю: {answer.status}, ждали 403"
    # п. 8: кнопки «Новая статья» у читателя нет, у редактора есть
    reader.page.goto("/kb/")
    expect(reader.page.locator('[data-kb-page="home"]')).to_be_visible()
    expect(reader.page.locator('a[data-action="kb-new-article"]')).to_have_count(0)
    expect(reader.page.locator('a[href="/kb/new/"]')).to_have_count(0)
    editor.page.goto("/kb/")
    expect(editor.page.locator('a[data-action="kb-new-article"]').first).to_be_visible()


def test_k01_published_article_has_no_return_to_draft_button(admin_page, employee):
    """Сценарий 1, п. 9: у опубликованной статьи нет кнопки «Вернуть в черновик» ни на странице статьи, ни в форме
    правки: правка видна сразу, откат — историей (FR-408)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    article_id = create_draft(page, title=unique_title(), text=SAMPLE_TEXT, rubric=rubric)
    helpers_kb.publish_from_article_page(page, article_id)
    # п. 9: на странице статьи
    expect(page.get_by_text("Вернуть в черновик")).to_have_count(0)
    expect(page.locator('form[data-form="kb-restore"]')).to_have_count(0)
    expect(page.locator('form[data-form="kb-publish"]')).to_have_count(0)
    expect(page.locator('a[data-action="kb-history"]')).to_be_visible()
    # п. 9: в форме правки
    open_edit(page, article_id)
    expect(page.get_by_text("Вернуть в черновик")).to_have_count(0)
    expect(page.get_by_role("button", name="Вернуть")).to_have_count(0)


def test_k01_text_over_200000_chars_or_title_over_200_chars_is_refused_with_limit_shown(admin_page, employee):
    """Сценарий 1, п. 10: текст длиннее 200 000 знаков или заголовок длиннее 200 знаков — сохранения нет, показан
    предел, введённое остаётся (FR-401)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    word = helpers_kb.unique_word()
    # п. 10: заголовок на один знак длиннее предела
    long_title = (word + "я" * helpers_kb.TITLE_LIMIT)[: helpers_kb.TITLE_LIMIT + 1]
    open_new_article(page)
    _lift_limits(page)
    fill_article_form(page, title=long_title, text="Короткий текст", rubric=rubric)
    press_save(page)
    error = page.locator('[data-error="title"][data-code="title_too_long"]')
    expect(error).to_contain_text("200")
    assert re.search(r"/kb/new/$", page.url), "после отказа адрес сменился"
    expect(article_form(page).locator("input[name=title]")).to_have_value(long_title)
    # п. 10: текст на один знак длиннее предела
    open_new_article(page)
    _lift_limits(page)
    long_text = "a" * (helpers_kb.TEXT_LIMIT + 1)
    fill_article_form(page, title=f"Длинный текст {word}", text=long_text, rubric=rubric)
    press_save(page)
    error = page.locator('[data-error="text"][data-code="text_too_long"]')
    expect(error).to_contain_text("200 000")
    assert re.search(r"/kb/new/$", page.url), "после отказа адрес сменился"
    kept = article_form(page).locator("textarea[name=text]").evaluate("el => el.value.length")
    assert kept == helpers_kb.TEXT_LIMIT + 1, "введённый текст не сохранён в форме после отказа"
    # п. 10: сохранения нет
    page.goto("/kb/")
    assert word not in page.locator("body").inner_text(), "статья сохранена, хотя предел превышен"


def test_k01_manager_sees_foreign_draft_in_drafts_edits_and_publishes_it(admin_page, employee):
    """Сценарий 1, п. 11: управляющий базой знаний видит чужой черновик в «Черновики», открывает, правит и
    публикует его (FR-407, FR-408)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    title = unique_title()
    article_id = create_draft(author.page, title=title, text="Первый текст черновика.", rubric=rubric)
    word = helpers_kb.unique_word("новый")
    # п. 11: чужой черновик виден в «Черновики» и открывается из списка
    admin_page.goto("/kb/")
    row = admin_page.locator(f'[data-kb-all-drafts] li[data-article-id="{article_id}"]')
    expect(row).to_be_visible()
    row.locator('a[data-field="title"]').click()
    admin_page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(admin_page.locator(f'article[data-article-id="{article_id}"]')).to_have_attribute(
        "data-article-state", "draft")
    # п. 11: правит
    admin_page.locator('a[data-action="kb-edit"]').click()
    admin_page.wait_for_url(re.compile(rf"/kb/{article_id}/edit/$"))
    fill_article_form(admin_page, text=f"Правка управляющего {word}.")
    # п. 11: публикует
    press_publish_in_form(admin_page)
    admin_page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    root = admin_page.locator(f'article[data-article-id="{article_id}"]')
    expect(root).to_have_attribute("data-article-state", "published")
    expect(root.locator('[data-field="body"]')).to_contain_text(f"Правка управляющего {word}")


def test_k01_attach_and_image_buttons_show_save_draft_hint_then_work_after_first_save(admin_page, employee):
    """Сценарий 1, п. 12: у несохранённой статьи «Вложить» и «Картинка» неактивны с подсказкой «Сохраните
    черновик»; после первого сохранения работают (FR-422, FR-423)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    # п. 12: новая статья не сохранена
    open_new_article(page)
    expect(page.locator('button[data-action="kb-attach"]')).to_be_disabled()
    expect(page.locator('button[data-md="image"]')).to_be_disabled()
    expect(page.locator('[data-kb-hint="save-draft"]')).to_contain_text(helpers_kb.SAVE_HINT)
    expect(page.locator('button[data-action="kb-attach"]')).to_have_attribute("title", helpers_kb.SAVE_HINT)
    # п. 12: после первого сохранения черновика
    fill_article_form(page, title=unique_title(), text="Текст до картинки.", rubric=rubric)
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    expect(page.locator('button[data-action="kb-attach"]')).to_be_enabled()
    expect(page.locator('button[data-md="image"]')).to_be_enabled()
    expect(page.locator('[data-kb-hint="save-draft"]')).to_have_count(0)
    expect(page.locator('form[data-form="kb-attach"] input[type=file][name=file]')).to_have_count(1)
    # п. 12: «Картинка» работает: выбор картинки, загрузка, вставка `![имя](att:N)` (вопрос C-16, принят)
    name = f"{helpers_kb.unique_word('pic')}.png"
    with page.expect_file_chooser(timeout=10_000) as chooser:
        page.locator('[data-kb-toolbar] button[data-md="image"]').click()
    chooser.value.set_files({"name": name, "mimeType": "image/png", "buffer": helpers.make_png(20, 20)})
    expect(article_form(page).locator("textarea[name=text]")).to_have_value(
        re.compile(r"!\[[^\]]*\]\(att:\d+\)"), timeout=30_000)
    expect(page.locator("[data-kb-files] li[data-file-id]").filter(has_text=name)).to_be_visible()


def test_k01_publish_with_changed_form_text_creates_new_version_and_with_unchanged_text_creates_none(
        admin_page, employee):
    """Сценарий 1, п. 13: «Опубликовать» с изменённым текстом формы создаёт новую версию с этим текстом и
    публикует; с неизменённым — публикует без новой версии (FR-408, FR-410)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    # п. 13: текст формы изменён
    changed = create_draft(page, title=unique_title(), text="Исходный текст.", rubric=rubric)
    assert helpers_kb.history_versions(page, changed) == [1]
    open_edit(page, changed)
    fill_article_form(page, text="Изменённый перед публикацией текст.")
    press_publish_in_form(page)
    page.wait_for_url(re.compile(rf"/kb/{changed}/$"))
    expect(page.locator(f'article[data-article-id="{changed}"]')).to_have_attribute(
        "data-article-state", "published")
    expect(page.locator('[data-field="body"]')).to_contain_text("Изменённый перед публикацией текст")
    assert helpers_kb.history_versions(page, changed) == [2, 1], "изменённый текст не создал версию 2"
    page.locator('tr[data-version="2"] a[data-action="kb-version-open"]').click()
    expect(page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(
        "Изменённый перед публикацией текст")
    # п. 13: текст формы не изменён
    same = create_draft(page, title=unique_title(), text="Текст без правок.", rubric=rubric)
    open_edit(page, same)
    press_publish_in_form(page)
    page.wait_for_url(re.compile(rf"/kb/{same}/$"))
    expect(page.locator(f'article[data-article-id="{same}"]')).to_have_attribute("data-article-state", "published")
    assert helpers_kb.history_versions(page, same) == [1], "неизменённый текст создал новую версию"


def test_k01_portal_link_works_protocol_relative_link_does_not_and_external_link_has_noopener_noreferrer(
        admin_page, employee):
    """Сценарий 1, п. 14: ссылка `/search/` работает как ссылка портала, `//evil.example/x` не работает как
    ссылка, `https://example.ru` — внешняя с `rel="noopener noreferrer"` (FR-402)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    text = "[портал](/search/) и [чужая](//evil.example/x) и [внешняя](https://example.ru)\n"
    article_id = create_draft(page, title=unique_title(), text=text, rubric=rubric)
    open_article(page, article_id)
    body = page.locator('[data-field="body"]')
    # п. 14: ссылка портала — ссылка, ведёт внутри портала
    portal = body.locator('a[href="/search/"]')
    expect(portal).to_have_count(1)
    # п. 14: `//evil.example/x` — не ссылка; текст остаётся
    assert body.locator('a[href*="evil.example"]').count() == 0, "ссылка //evil.example/x осталась ссылкой"
    expect(body).to_contain_text("чужая")
    # п. 14: внешняя ссылка с rel="noopener noreferrer"
    external = body.locator('a[href="https://example.ru"]')
    expect(external).to_have_count(1)
    rel = set((external.get_attribute("rel") or "").split())
    assert {"noopener", "noreferrer"} <= rel, f"у внешней ссылки rel={sorted(rel)}"
    # п. 14: ссылка портала работает
    portal.click()
    page.wait_for_url(re.compile(r"/search/"))


def test_k01_wide_table_and_long_code_line_scroll_inside_block_in_preview_at_360px(
        browser, browser_context_args, admin_page, employee):
    """Сценарий 1, п. 15: широкая таблица и длинная строка кода в «Предпросмотре» на 360 px — страница не
    раздвигается, таблица и блок кода прокручиваются внутри своего блока (FR-403, NFR-406)."""
    author = helpers_kb.make_editor(employee)
    head = "| " + " | ".join(f"столбец-{n}-с-длинным-названием" for n in range(14)) + " |\n"
    rule = "|" + "---|" * 14 + "\n"
    cells = "| " + " | ".join(f"значение-{n}-длинное" for n in range(14)) + " |\n"
    text = head + rule + cells + "\n```\n" + "x" * 400 + "\n```\n"
    context = helpers_kb.narrow_context(browser, browser_context_args, author.page)
    try:
        page = context.new_page()
        open_new_article(page)
        fill_article_form(page, title=unique_title(), text=text)
        # п. 15: «Предпросмотр» на 360 px
        open_preview(page)
        preview = page.locator("[data-kb-panel=preview] [data-kb-preview]")
        table_block = preview.locator("div.kb-scroll:has(table)").first
        code_block = preview.locator("div.kb-scroll:has(pre)").first
        expect(table_block).to_be_visible()
        expect(code_block).to_be_visible()
        # п. 15: страница не раздвигается
        assert helpers_kb.page_fits(page), "на 360 px страница с предпросмотром шире экрана"
        # п. 15: таблица и блок кода прокручиваются внутри своего блока
        assert helpers_kb.scrolls_inside(table_block), "таблица не прокручивается внутри своего блока"
        assert helpers_kb.scrolls_inside(code_block), "блок кода не прокручивается внутри своего блока"
    finally:
        context.close()
