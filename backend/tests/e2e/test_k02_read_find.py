"""T-5141: сценарий 2 — сотрудник находит и читает статью: главная, рубрики, теги, поиск, корзина, уволенные
(FR-401, FR-406, FR-409, FR-411, FR-415, FR-420, FR-421, FR-422, FR-425, FR-437, FR-441, NFR-406).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md):
- читатель — сотрудник с ролью «Руководитель» (без прав базы знаний, `helpers_kb.make_reader`); статьи, рубрики и
  комментарии заводит управляющий (`admin_page` круга) через интерфейс; названия, слова и теги уникальны, поэтому
  списки, которые тест сверяет, состоят только из его статей (данные круга общие);
- общих настроек тесты файла не меняют; стенд сбрасывает только последний тест («в базе нет ни одной статьи»:
  без сброса пустой базы на общем стенде не получить), поэтому он стоит в файле последним;
- статья в корзине — кнопка «В корзину» страницы статьи (форма `kb-trash`, окно подтверждения принимается);
- время на странице — по Москве (12.1 раздела 1.2 контракта): день сверяется с московской датой.
"""
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org, helpers_sd
from tests.e2e.helpers_kb import (
    create_draft, create_rubric, history_versions, home_ids, make_reader, open_article, open_edit, press_save,
    publish_from_article_page, rubric_page_ids, scrolls_inside, unique_title, unique_word)

MOSCOW = timezone(timedelta(hours=3))  # Москва без перехода на летнее время (UTC+3)
TIME_RE = re.compile(r"\d\d\.\d\d\.\d{4} \d\d:\d\d")  # ДД.ММ.ГГГГ ЧЧ:ММ (контракт 11.1)
MISSING_ARTICLE = 2_000_000_000  # номер, которого на стенде нет (в пределах целого PostgreSQL)
GONE_TEXT = "Статья удалена"  # 12.1
EMPTY_TEXT = "В базе знаний пока нет статей"  # 12.3


# --- Общие помощники файла ------------------------------------------------------------------------------

def _rubric(admin_page, *, parent_name: str | None = None) -> str:
    """Своя рубрика (создаёт управляющий); возвращает название."""
    name = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, name, parent_name=parent_name)
    return name


def _published(page, *, rubric: str, title: str | None = None, text: str = "Текст статьи для чтения.",
               tags: str = "") -> tuple:
    """Опубликованная статья через интерфейс: черновик, затем кнопка страницы статьи; возвращает (номер, заголовок)."""
    title = title or unique_title()
    article_id = create_draft(page, title=title, text=text, rubric=rubric, tags=tags)
    publish_from_article_page(page, article_id)
    return article_id, title


def _trash(page, article_id) -> None:
    """Управляющий переносит статью в корзину кнопкой страницы (окно подтверждения `hx-confirm` принимается);
    ждёт корень страницы статьи в состоянии «корзина»."""
    open_article(page, article_id)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('form[data-form="kb-trash"] button').first.click()
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()


def _tree_cell(page, rubric_id, field: str) -> str:
    """Текст собственной ячейки строки дерева главной: `[data-field=<field>]` строки рубрики (не вложенных строк)."""
    return page.locator(f'[data-kb-tree] li[data-rubric-id="{rubric_id}"]').first.evaluate(
        "(li, field) => { const own = Array.from(li.querySelectorAll('[data-field=\"' + field + '\"]'))"
        ".find(e => e.closest('li[data-rubric-id]') === li); return own ? own.innerText.trim() : null; }", field)


def _msk_dates() -> set:
    """Московские дни «сейчас» и «минуту назад» в виде `ДД.ММ.ГГГГ` (защита от перехода через полночь)."""
    now = datetime.now(MOSCOW)
    return {now.strftime("%d.%m.%Y"), (now - timedelta(minutes=5)).strftime("%d.%m.%Y")}


def _dismiss(admin_page, user_id) -> None:
    """Увольняет сотрудника из карточки `/staff/<id>/`: диалог, подтверждение; ждёт отметку «уволен» в карточке."""
    admin_page.goto(f"/staff/{user_id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


# --- Тесты ----------------------------------------------------------------------------------------------

def test_k02_reader_without_kb_rights_sees_rubric_tree_with_counts_and_ten_latest_but_no_new_article_or_drafts(
        admin_page, employee):
    """Сценарий 2, п. 1: сотрудник без прав базы знаний видит дерево рубрик с числом опубликованных статей (с
    подрубриками, без черновиков), «Новые и изменённые» — десять последних по времени правки, и не видит ни
    «Новая статья», ни «Мои черновики» (FR-421, FR-406)."""
    parent = _rubric(admin_page)
    child = _rubric(admin_page, parent_name=parent)
    parent_id = helpers_kb.rubric_id_by_name(admin_page, parent)
    child_id = helpers_kb.rubric_id_by_name(admin_page, child)
    made = []  # (номер, заголовок, рубрика) по порядку публикации: одиннадцать — чтобы десять последних были выбраны
    for index in range(11):
        rubric = child if index < 2 else parent
        article_id, title = _published(admin_page, rubric=rubric)
        made.append((article_id, title, rubric))
    draft_id = create_draft(admin_page, title=unique_title(), rubric=child)  # черновик в числе не считается
    reader = make_reader(employee)

    reader.page.goto("/kb/")
    expect(reader.page.locator('[data-kb-page="home"]')).to_be_visible()
    # п. 1: дерево с числом опубликованных статей: подрубрика — 2, рубрика с подрубрикой — 11 (без черновика)
    expect(reader.page.locator(f'[data-kb-tree] li[data-rubric-id="{parent_id}"]').first).to_be_visible()
    assert reader.page.locator(f'[data-kb-tree] li[data-rubric-id="{parent_id}"]').first.get_attribute(
        "data-depth") == "1"
    assert reader.page.locator(f'[data-kb-tree] li[data-rubric-id="{child_id}"]').first.get_attribute(
        "data-depth") == "2"
    assert parent in _tree_cell(reader.page, parent_id, "name")
    assert child in _tree_cell(reader.page, child_id, "name")
    assert "11 статей" in _tree_cell(reader.page, parent_id, "count"), "у рубрики с подрубрикой — 11 статей"
    assert "2 статьи" in _tree_cell(reader.page, child_id, "count"), "у подрубрики — 2 статьи, черновик не считается"
    expect(reader.page.locator(f'[data-kb-tree] a[data-field="name"][href="/kb/rubrics/{parent_id}/"]')).to_have_count(1)
    # п. 1: «Новые и изменённые» — ровно десять последних опубликованных, новые сверху
    rows = reader.page.locator("[data-kb-new-and-changed] li[data-article-id]")
    expected = list(reversed(made))[:10]
    assert [li.get_attribute("data-article-id") for li in rows.all()] == [item[0] for item in expected]
    for li, (_, title, rubric) in zip(rows.all(), expected):
        expect(li.locator('a[data-field="title"]')).to_have_text(title)
        expect(li.locator('[data-field="rubric"]')).to_contain_text(rubric)
        expect(li.locator("time[data-at]").first).to_have_text(TIME_RE)
    assert made[0][0] not in home_ids(reader.page), "одиннадцатая, самая старая статья попала в десять последних"
    assert draft_id not in home_ids(reader.page), "черновик виден читателю в «Новые и изменённые»"
    # п. 1: ни «Новая статья», ни «Мои черновики», ни «Черновики», ни «Корзина»
    expect(reader.page.locator('a[data-action="kb-new-article"]')).to_have_count(0)
    expect(reader.page.locator('a[href="/kb/new/"]')).to_have_count(0)
    expect(reader.page.locator("[data-kb-my-drafts]")).to_have_count(0)
    expect(reader.page.locator("[data-kb-all-drafts]")).to_have_count(0)
    expect(reader.page.locator('a[data-action="kb-trash-link"]')).to_have_count(0)
    body = reader.page.locator('[data-kb-page="home"]').inner_text()
    assert "Мои черновики" not in body and "Новая статья" not in body
    # FR-406: адрес новой статьи читателю закрыт
    assert helpers_org.direct_get(reader.page, "/kb/new/").status == 403


def test_k02_rubric_page_shows_articles_of_rubric_and_subrubrics_with_subscribe_button(admin_page, employee):
    """Сценарий 2, п. 2: страница рубрики с подрубриками показывает опубликованные статьи рубрики и подрубрик (без
    черновиков и чужих рубрик) и кнопку «Подписаться» (FR-421, FR-437)."""
    parent = _rubric(admin_page)
    child = _rubric(admin_page, parent_name=parent)
    other = _rubric(admin_page)
    parent_id = helpers_kb.rubric_id_by_name(admin_page, parent)
    child_id = helpers_kb.rubric_id_by_name(admin_page, child)
    in_parent, in_parent_title = _published(admin_page, rubric=parent)
    in_child, in_child_title = _published(admin_page, rubric=child)
    in_other, _ = _published(admin_page, rubric=other)
    draft_in_child = create_draft(admin_page, title=unique_title(), rubric=child)
    reader = make_reader(employee)

    # п. 2: у рубрики — её статьи и статьи подрубрики; черновика и чужой рубрики нет
    ids = rubric_page_ids(reader.page, parent_id)
    assert set(ids) == {in_parent, in_child}, f"на странице рубрики: {ids}"
    assert len(ids) == 2
    assert draft_in_child not in ids and in_other not in ids
    titles = reader.page.locator('[data-kb-list] li[data-article-id] a[data-field="title"]').all_inner_texts()
    assert sorted(t.strip() for t in titles) == sorted([in_parent_title, in_child_title])
    # п. 2: кнопка «Подписаться» (подписки ещё нет)
    button = reader.page.locator('button[data-action="kb-subscribe"]')
    expect(button).to_have_count(1)
    expect(button).to_have_text(re.compile(r"Подписаться"))
    expect(button).to_have_attribute("data-subscribed", "false")
    # подрубрика: только её статья, кнопка та же
    assert rubric_page_ids(reader.page, child_id) == [in_child]
    expect(reader.page.locator('button[data-action="kb-subscribe"]')).to_have_text(re.compile(r"Подписаться"))


def test_k02_article_page_shows_title_text_rubric_path_tags_changed_by_attachments_and_comments(
        admin_page, employee, stand_admin):
    """Сценарий 2, п. 3: опубликованная статья показывает заголовок, текст, рубрику (путь), теги, «изменено: имя,
    время», вложения и комментарии (FR-401, FR-422, FR-425)."""
    parent = _rubric(admin_page)
    child = _rubric(admin_page, parent_name=parent)
    parent_id = helpers_kb.rubric_id_by_name(admin_page, parent)
    child_id = helpers_kb.rubric_id_by_name(admin_page, child)
    word = unique_word("txt")
    first_tag, second_tag = unique_word("tag"), unique_word("tag")
    title = unique_title()
    text = f"Первый абзац {word}.\n\nЗдесь **важное слово** и обычный текст.\n\n- пункт один\n- пункт два\n"
    article_id = create_draft(admin_page, title=title, text=text, rubric=child, tags=f"{first_tag}, {second_tag}")
    file_name = f"{word}.txt"
    file_id = helpers_kb.attach_file(admin_page, article_id, f"вложение {word}".encode(), file_name,
                                     mime="text/plain")
    assert helpers_kb.wait_file_clean(admin_page, article_id, file_id) == "clean"
    publish_from_article_page(admin_page, article_id)
    reader = make_reader(employee)
    comment_text = f"Комментарий читателя {word}"
    helpers_kb.add_comment(reader.page, article_id, comment_text)

    open_article(reader.page, article_id)
    page = reader.page
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    # п. 3: заголовок и текст (готовый html)
    expect(page.locator('h1[data-field="title"]')).to_have_text(title)
    body = page.locator('[data-field="body"]')
    expect(body).to_contain_text(f"Первый абзац {word}.")
    expect(body.locator("strong")).to_have_text("важное слово")
    expect(body.locator("li")).to_have_count(2)
    # п. 3: рубрика — путь от корня, со ссылками на обе рубрики
    path = page.locator('[data-field="rubric"]')
    expect(path).to_contain_text(parent)
    expect(path).to_contain_text(child)
    assert path.inner_text().index(parent) < path.inner_text().index(child), "путь рубрики: сначала родитель"
    expect(path.locator(f'a[href="/kb/rubrics/{parent_id}/"]')).to_have_count(1)
    expect(path.locator(f'a[href="/kb/rubrics/{child_id}/"]')).to_have_count(1)
    # п. 3: теги ссылками на страницу тега
    for tag in (first_tag, second_tag):
        link = page.locator(f'a[data-tag="{tag}"]')
        expect(link).to_have_count(1)
        assert f"/kb/tags/?name={tag}" in link.get_attribute("href")
    # п. 3: «изменено: имя, время» — имя автора правки и московское время
    updated = page.locator('[data-field="updated"]')
    expect(updated).to_contain_text(re.compile("изменено", re.IGNORECASE))
    expect(updated).to_contain_text(stand_admin.full_name)
    stamp = updated.locator("time[data-at]").first
    expect(stamp).to_have_text(TIME_RE)
    assert stamp.inner_text().strip()[:10] in _msk_dates(), f"время правки не по Москве: {stamp.inner_text()}"
    assert stamp.get_attribute("datetime").endswith("+03:00"), "атрибут datetime — с поясом Москвы"
    # п. 3: вложение — имя и ссылка на скачивание чистого файла
    row = helpers_kb.file_row(page, file_id)
    expect(row).to_be_visible()
    expect(row.locator('[data-field="name"]')).to_have_text(file_name)
    assert row.locator('a[data-action="kb-download"]').get_attribute("href") == f"/kb/{article_id}/files/{file_id}/"
    # п. 3: комментарии — заголовок раздела и сам комментарий с автором
    comments = page.locator("section#comments[data-kb-comments]")
    expect(comments).to_contain_text("Комментарии")
    comment_row = comments.locator("li[data-comment-id]").filter(has_text=comment_text)
    expect(comment_row).to_have_count(1)
    expect(comment_row.locator('[data-field="author"]')).to_contain_text(reader.full_name)


def test_k02_article_with_wide_table_and_long_code_does_not_widen_page_at_360px(
        browser, browser_context_args, admin_page, employee):
    """Сценарий 2, п. 3: на 360 px страница статьи с широкой таблицей и длинным блоком кода не раздвигается, а
    таблица и код прокручиваются внутри своих блоков (NFR-406)."""
    rubric = _rubric(admin_page)
    cells = [f"очень-длинное-значение-ячейки-{index}" for index in range(12)]
    table = ("| " + " | ".join(f"колонка{index}" for index in range(12)) + " |\n"
             + "|" + "---|" * 12 + "\n"
             + "| " + " | ".join(cells) + " |\n")
    code_line = "vpn-connect-" + "x" * 400
    text = f"Перед таблицей.\n\n{table}\n```\n{code_line}\n```\n"
    article_id, title = _published(admin_page, rubric=rubric, text=text)
    reader = make_reader(employee)
    context = helpers_kb.narrow_context(browser, browser_context_args, reader.page)
    try:
        page = context.new_page()
        page.goto(f"/kb/{article_id}/")
        expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()
        expect(page.locator('h1[data-field="title"]')).to_have_text(title)
        # п. 3: страница не раздвигается
        assert helpers_kb.page_fits(page), "на 360 px у страницы статьи есть горизонтальная прокрутка"
        # п. 3: таблица и код — каждый в своём блоке прокрутки, и блок прокручивается внутри себя
        blocks = page.locator('[data-field="body"] div.kb-scroll')
        table_block = blocks.filter(has=page.locator("table"))
        code_block = blocks.filter(has=page.locator("pre"))
        expect(table_block).to_have_count(1)
        expect(code_block).to_have_count(1)
        assert scrolls_inside(table_block.first), "широкая таблица не прокручивается внутри блока"
        assert scrolls_inside(code_block.first), "длинный код не прокручивается внутри блока"
        for block in (table_block.first, code_block.first):
            assert block.evaluate("el => { el.scrollLeft = 40; return el.scrollLeft; }") > 0
        assert helpers_kb.page_fits(page), "после прокрутки блока страница раздвинулась"
    finally:
        context.close()


def test_k02_tag_click_opens_tag_page_with_published_articles_only_without_drafts_and_trash(
        admin_page, employee):
    """Сценарий 2, п. 4: по щелчку на тег статьи открывается страница тега со списком опубликованных статей с этим
    тегом; черновиков и корзины в ней нет (FR-420, FR-421)."""
    rubric = _rubric(admin_page)
    tag = unique_word("vpn")
    other_tag = unique_word("wifi")
    first_id, first_title = _published(admin_page, rubric=rubric, tags=f"{tag}, {other_tag}")
    second_id, second_title = _published(admin_page, rubric=rubric, tags=tag)
    without_tag_id, _ = _published(admin_page, rubric=rubric, tags=other_tag)
    draft_title = unique_title()
    draft_id = create_draft(admin_page, title=draft_title, rubric=rubric, tags=tag)
    trashed_id, trashed_title = _published(admin_page, rubric=rubric, tags=tag)
    _trash(admin_page, trashed_id)
    reader = make_reader(employee)

    open_article(reader.page, first_id)
    reader.page.locator(f'a[data-tag="{tag}"]').click()
    reader.page.wait_for_url(re.compile(r"/kb/tags/\?name="))
    assert tag in reader.page.url
    expect(reader.page.locator('[data-kb-page="tag"]')).to_be_visible()
    rows = reader.page.locator("[data-kb-list] li[data-article-id]")
    expect(rows.first).to_be_visible()
    ids = [li.get_attribute("data-article-id") for li in rows.all()]
    # п. 4: только опубликованные статьи с этим тегом
    assert set(ids) == {first_id, second_id}, f"на странице тега: {ids}"
    assert len(ids) == 2
    assert without_tag_id not in ids and draft_id not in ids and trashed_id not in ids
    page_text = reader.page.locator('[data-kb-page="tag"]').inner_text()
    assert draft_title not in page_text and trashed_title not in page_text
    # строка списка — заголовок и тег ссылкой
    first_row = rows.filter(has=reader.page.locator('a[data-field="title"]', has_text=first_title))
    expect(first_row).to_have_count(1)
    expect(first_row.locator(f'a[data-tag="{tag}"]')).to_have_count(1)
    assert second_title in page_text


def test_k02_click_on_global_search_row_opens_the_article(admin_page, employee):
    """Сценарий 2, п. 5: сотрудник находит статью сквозным поиском; по щелчку на строку выдачи статья открывается
    (FR-441)."""
    rubric = _rubric(admin_page)
    article_id, title = _published(admin_page, rubric=rubric)
    word = title.split()[-1]
    reader = make_reader(employee)
    page = reader.page

    page.goto("/kb/")
    field = page.locator('[data-search-bar] input[name="q"]')
    expect(field).to_be_visible()
    field.fill(word)
    # п. 5: строка статьи в группе «Статьи» всплывающей выдачи
    group = page.locator('[data-search-popup] section[data-search-group="articles"]')
    row = group.locator("li[data-search-row]").filter(has_text=title)
    expect(row).to_have_count(1)
    expect(row.locator("a[href]").first).to_have_attribute("href", f"/kb/{article_id}/")
    # п. 5: щелчок по строке открывает статью
    row.locator("a[href]").first.click()
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()
    expect(page.locator('h1[data-field="title"]')).to_have_text(title)


def test_k02_trashed_article_old_link_shows_deleted_page_without_text_and_manager_sees_in_trash_mark(
        admin_page, employee):
    """Сценарий 2, п. 6: по старой ссылке на статью в корзине сотрудник видит страницу «Статья удалена» без текста,
    а управляющий — статью с пометкой «в корзине» (FR-409, FR-415)."""
    rubric = _rubric(admin_page)
    word = unique_word("body")
    article_id, title = _published(admin_page, rubric=rubric, text=f"Секретный для корзины абзац {word}.")
    reader = make_reader(employee)
    open_article(reader.page, article_id)  # ссылка работала, пока статья была опубликована
    _trash(admin_page, article_id)

    # п. 6: сотрудник — страница 410 без заголовка и текста
    answer = helpers_org.direct_get(reader.page, f"/kb/{article_id}/")
    assert answer.status == 410, f"ответ {answer.status}, ждали 410"
    assert GONE_TEXT in answer.text()
    assert word not in answer.text() and title.split()[-1] not in answer.text(), "в ответе есть данные статьи"
    reader.page.goto(f"/kb/{article_id}/")
    expect(reader.page.locator('[data-kb-page="gone"]')).to_be_visible()
    expect(reader.page.locator('[data-kb-page="gone"]')).to_contain_text(GONE_TEXT)
    expect(reader.page.locator("article[data-article-id]")).to_have_count(0)
    expect(reader.page.locator('h1[data-field="title"]')).to_have_count(0)
    # п. 6: управляющий — та же статья с пометкой «В корзине»
    admin_page.goto(f"/kb/{article_id}/")
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()
    expect(admin_page.locator("[data-kb-trash-mark]")).to_contain_text("В корзине")
    expect(admin_page.locator('h1[data-field="title"]')).to_have_text(title)
    expect(admin_page.locator('[data-field="body"]')).to_contain_text(word)
    expect(admin_page.locator('[data-kb-page="gone"]')).to_have_count(0)


def test_k02_unknown_article_number_shows_not_found_same_as_foreign_draft(admin_page, employee):
    """Сценарий 2, п. 7: неизвестный номер статьи даёт то же, что чужой черновик — страницу «не найдено» (404), без
    данных черновика (FR-409)."""
    rubric = _rubric(admin_page)
    draft_title = unique_title()
    draft_id = create_draft(admin_page, title=draft_title, text=f"Текст черновика {unique_word('dr')}.", rubric=rubric)
    word = draft_title.split()[-1]
    reader = make_reader(employee)
    page = reader.page

    missing = helpers_org.direct_get(page, f"/kb/{MISSING_ARTICLE}/")
    assert missing.status == 404, f"несуществующая статья: ответ {missing.status}, ждали 404"
    for path in (f"/kb/{draft_id}/", f"/kb/{draft_id}/history/"):
        answer = helpers_org.direct_get(page, path)
        assert answer.status == missing.status, f"{path}: ответ {answer.status}, как у несуществующей — 404"
        assert word not in answer.text(), f"{path}: в ответе есть заголовок чужого черновика"
    # то, что видит человек, у обоих адресов одно и то же
    page.goto(f"/kb/{MISSING_ARTICLE}/")
    expect(page.locator("article[data-article-id]")).to_have_count(0)
    expect(page.locator('[data-kb-page="gone"]')).to_have_count(0)
    missing_headings = page.locator("h1").all_inner_texts()
    assert missing_headings == ["Статья не найдена"], f"заголовок h1 404 несуществующей статьи: {missing_headings}"
    page.goto(f"/kb/{draft_id}/")
    expect(page.locator("article[data-article-id]")).to_have_count(0)
    expect(page.locator('[data-kb-page="gone"]')).to_have_count(0)
    assert page.locator("h1").all_inner_texts() == ["Статья не найдена"], "h1 404 чужого черновика не «Статья не найдена»"
    assert word not in page.locator("body").inner_text()
    # автор-управляющий свой черновик открывает
    assert helpers_org.direct_get(admin_page, f"/kb/{draft_id}/").status == 200


def test_k02_dismissed_author_editor_and_commenter_are_shown_with_dismissed_mark_in_article_history_and_comments(
        admin_page, employee):
    """Сценарий 2, п. 9: автор статьи, её последний редактор и автор комментария уволены — на странице статьи, в
    истории и в комментариях везде ФИО с пометкой «уволен» (FR-401, FR-411, FR-425)."""
    mark = unique_word("u")
    author = helpers_kb.make_editor(employee, full_name=f"Автор{mark} Иван Петрович")
    editor = helpers_kb.make_editor(employee, full_name=f"Правщик{mark} Олег Иванович")
    commenter = make_reader(employee, full_name=f"Комментатор{mark} Пётр Олегович")
    rubric = _rubric(admin_page)
    title = unique_title()
    article_id = create_draft(author.page, title=title, text="Первая редакция статьи.", rubric=rubric)
    publish_from_article_page(author.page, article_id)
    open_edit(editor.page, article_id)  # последняя правка — не автора
    helpers_kb.fill_article_form(editor.page, text="Вторая редакция статьи.", comment="правка")
    press_save(editor.page)
    editor.page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    comment_text = f"Комментарий {mark}"
    helpers_kb.add_comment(commenter.page, article_id, comment_text)
    assert len(history_versions(admin_page, article_id)) >= 2

    # до увольнения пометки нет ни у кого
    open_article(admin_page, article_id)
    expect(admin_page.locator('[data-field="author"]').first).to_contain_text(author.full_name)
    expect(admin_page.locator('[data-dismissed="true"]')).to_have_count(0)

    for person in (author, editor, commenter):
        _dismiss(admin_page, person.id)

    def marked(locator, person):
        """У элемента есть пометка «уволен» с ФИО этого человека."""
        expect(locator.locator('[data-dismissed="true"]')).to_contain_text(
            re.compile(re.escape(person.full_name) + r"\s*\(уволен\)"))

    # п. 9: страница статьи — автор и последний редактор («изменено»)
    open_article(admin_page, article_id)
    marked(admin_page.locator('article [data-field="author"]').first, author)
    marked(admin_page.locator('[data-field="updated"]'), editor)
    # п. 9: история — авторы версий
    helpers_kb.open_history(admin_page, article_id)
    authors = admin_page.locator('tr[data-version] [data-field="author"]')
    texts = [" ".join(t.split()) for t in authors.all_inner_texts()]
    assert any(author.full_name in t and "(уволен)" in t for t in texts), f"в истории нет уволенного автора: {texts}"
    assert any(editor.full_name in t and "(уволен)" in t for t in texts), f"в истории нет уволенного редактора: {texts}"
    for person in (author, editor):
        marked(authors.filter(has_text=person.full_name).first, person)
    # п. 9: комментарии — автор комментария
    open_article(admin_page, article_id)
    comment_row = admin_page.locator("section#comments li[data-comment-id]").filter(has_text=comment_text)
    expect(comment_row).to_have_count(1)
    marked(comment_row.locator('[data-field="author"]'), commenter)


def test_k02_empty_knowledge_base_explains_purpose_and_shows_new_article_button_only_with_right(
        browser, browser_context_args, stand_admin, admin_page, employee):
    """Сценарий 2, п. 8: в базе нет ни одной статьи — страница объясняет, что здесь будет, а кнопка «Новая статья»
    есть только у сотрудника с правом (FR-421)."""
    # без сброса пустой базы на общем стенде не получить (данные круга общие); тест последний в файле
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    reader = make_reader(employee)

    # п. 8: читатель — пояснение, ни кнопки, ни списков
    reader.page.goto("/kb/")
    empty = reader.page.locator('[data-empty-state="kb"]')
    expect(empty).to_be_visible()
    expect(empty).to_contain_text(EMPTY_TEXT)
    expect(reader.page.locator('a[data-action="kb-new-article"]')).to_have_count(0)
    expect(reader.page.locator('a[href="/kb/new/"]')).to_have_count(0)
    expect(reader.page.locator("[data-kb-new-and-changed] li[data-article-id]")).to_have_count(0)
    # п. 8: сотрудник с правом — то же пояснение и кнопка «Новая статья» внутри него
    admin_page.goto("/kb/")
    expect(admin_page.locator('[data-kb-page="home"]')).to_be_visible()
    empty_admin = admin_page.locator('[data-empty-state="kb"]')
    expect(empty_admin).to_be_visible()
    expect(empty_admin).to_contain_text(EMPTY_TEXT)
    button = empty_admin.locator('a[data-action="kb-new-article"]')
    expect(button).to_be_visible()
    assert button.get_attribute("href") == "/kb/new/"
