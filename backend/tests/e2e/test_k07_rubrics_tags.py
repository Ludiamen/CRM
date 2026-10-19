"""T-5146: сценарий 7 — рубрики, теги, подписка на рубрику (FR-404, FR-406, FR-409, FR-418, FR-419, FR-420, FR-434,
FR-437, FR-438).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md):
- каждый тест заводит свои рубрики (управляющий — администратор круга `admin_page`), своих сотрудников и свои статьи;
  названия уникальны (`helpers_org.unique_name`, `helpers_kb.unique_title`, `helpers_kb.unique_word`), потому что
  данные круга общие; общих настроек тесты файла не меняют, поэтому возвращать в `finally` нечего;
- отказы форм рубрик — `[data-error="name"|"parent"][data-code]` с текстом раздела 12.2; отказ удаления —
  `[role=alert][data-code]` в строке рубрики (10.4); успех — флеш `[role=status]` раздела 12.3 (он же точка ожидания:
  адрес `/kb/rubrics/` при успехе не меняется);
- пункт родителя в `select[name=parent]` выбирается по названию; если пункта нет (форма могла не предлагать себя и
  подрубрики), он добавляется скриптом страницы: так форму отправил бы прямой запрос, а отказ даёт служба;
- подсказка тегов проверяется дважды: в браузере (ввод в `input[name=tags]` и зацепка `ul[data-kb-tag-suggest]`) и
  прямым GET `/kb/tags/suggest/?q=` (отсутствие подсказки в браузере само по себе ничего не доказывает до прихода
  фрагмента, поэтому у каждого «нет подсказки» есть подсказка-контроль с тем же началом);
- уведомление подписчика — колокольчик и список `/notifications/` (текст раздела 7.2 контракта).
"""
import html
import re
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers_notify, helpers_org
from tests.e2e.helpers_kb import (
    article_form, create_draft, create_rubric, fill_article_form, make_editor, make_reader, open_article,
    open_edit, open_new_article, press_save, publish_from_article_page, rubric_page_ids,
    unique_title, unique_word)

NOTIFY_WAIT_MS = 30_000
DEPTH_LIMIT_TEXT = "Не глубже трёх уровней"
DUPLICATE_TEXT = "Рубрика с таким названием уже есть на этом уровне"
NOT_EMPTY_TEXT = "Сначала перенесите"
NAME_LIMIT_TEXT = "Название не длиннее 100 знаков"
TAGS_MANY_TEXT = "Не больше 10 тегов"
TAG_LONG_TEXT = "Тег не длиннее 40 знаков"
DEFAULT_RUBRIC = "Общее"

_PICK_JS = (
    "(el, [name, value]) => { const clean = s => s.trim().replace(/^[^\\p{L}\\p{N}]+/u, ''); "
    "let o = Array.from(el.options).find(o => clean(o.text) === name); "
    "if (!o) { o = document.createElement('option'); o.value = value; o.text = name; el.add(o); } "
    "el.value = o.value; el.dispatchEvent(new Event('change', {bubbles: true})); return o.value; }")


# --- Рубрики: помощники файла -----------------------------------------------------------------------------

def _row(page, rubric_id):
    """Строка рубрики в управлении рубриками."""
    return page.locator(f'[data-kb-rubrics] li[data-rubric-id="{rubric_id}"]')


def _own(row, selector: str):
    """Первый элемент строки: если дерево вложенное, свои элементы строки идут раньше элементов подрубрик."""
    return row.locator(selector).first


def _open_rubrics(page) -> None:
    page.goto("/kb/rubrics/")
    expect(page.locator('[data-kb-page="rubrics"]')).to_be_visible()
    expect(page.locator("[data-kb-rubrics]")).to_be_visible()


def _choose_parent(select, name: str, rubric_id: str = "") -> None:
    """Выбирает в `select[name=parent]` пункт с названием `name` (точно, без отступа); нет пункта — добавляет."""
    select.evaluate(_PICK_JS, [name, str(rubric_id)])


def _lift_name_limit(form) -> None:
    """Снимает `maxlength` с поля названия: проверка предела — дело сервера (прямой запрос обошёл бы браузер)."""
    form.locator("input[name=name]").evaluate("el => el.removeAttribute('maxlength')")


def _submit_new(page, name: str, *, parent_name: str | None = None, parent_id: str = "") -> None:
    """Отправляет форму «Новая рубрика» (`form[data-form="kb-rubric-new"]`), ничего не ожидая."""
    _open_rubrics(page)
    form = page.locator('form[data-form="kb-rubric-new"]')
    _lift_name_limit(form)
    form.locator("input[name=name]").fill(name)
    if parent_name is not None:
        _choose_parent(form.locator("select[name=parent]"), parent_name, parent_id)
    form.locator("button[type=submit]").click()


def _submit_move(page, rubric_id: str, target_name: str | None, target_id: str = "") -> None:
    """Переносит рубрику формой строки (`form[data-form="kb-rubric-move"]`); `target_name=None` — «В корень»."""
    _open_rubrics(page)
    form = _own(_row(page, rubric_id), 'form[data-form="kb-rubric-move"]')
    if target_name is None:
        form.locator("select[name=parent]").select_option(index=0)
    else:
        _choose_parent(form.locator("select[name=parent]"), target_name, target_id)
    form.locator("button[type=submit]").click()


def _submit_rename(page, rubric_id: str, new_name: str) -> None:
    _open_rubrics(page)
    form = _own(_row(page, rubric_id), 'form[data-form="kb-rubric-rename"]')
    _lift_name_limit(form)
    form.locator("input[name=name]").fill(new_name)
    form.locator("button[type=submit]").click()


def _submit_delete(page, rubric_id: str) -> list:
    """Нажимает «Удалить» у строки рубрики и принимает окно подтверждения; возвращает тексты окон (список заполняется
    при показе окна)."""
    _open_rubrics(page)
    messages: list = []
    page.once("dialog", lambda dialog: (messages.append(dialog.message), dialog.accept()))
    _own(_row(page, rubric_id), 'form[data-form="kb-rubric-delete"]').locator("button").first.click()
    return messages


def _flash(page, text: str):
    """Флеш `[role=status]` с текстом раздела 12.3."""
    return page.locator("[role=status]").filter(has_text=text).first


def _depth(page, rubric_id: str) -> str:
    _open_rubrics(page)
    return _row(page, rubric_id).get_attribute("data-depth")


def _error(page, field: str):
    """Отказ у поля формы рубрики на странице (одновременно показан один)."""
    return page.locator(f'[data-error="{field}"]').first


def _tree(admin_page, parent_name: str, child_name: str, grand_name: str | None = None) -> tuple:
    """Создаёт «родитель → ребёнок [→ внук]»; возвращает номера."""
    parent_id = create_rubric(admin_page, parent_name)
    child_id = create_rubric(admin_page, child_name, parent_name=parent_name)
    if grand_name is None:
        return parent_id, child_id
    return parent_id, child_id, create_rubric(admin_page, grand_name, parent_name=child_name)


# --- Статьи и теги: помощники файла -----------------------------------------------------------------------

def _published(page, rubric_name: str, *, tags: str = "", title: str | None = None) -> tuple:
    """Статья через интерфейс: черновик, затем публикация; возвращает (номер, заголовок)."""
    title = title or unique_title()
    article_id = create_draft(page, title=title, rubric=rubric_name, tags=tags)
    publish_from_article_page(page, article_id)
    return article_id, title


def _trash(admin_page, article_id) -> None:
    """Переносит статью в корзину (управляющий): кнопка страницы статьи и окно подтверждения."""
    open_article(admin_page, article_id)
    admin_page.once("dialog", lambda dialog: dialog.accept())
    admin_page.locator('form[data-form="kb-trash"] button').first.click()
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()


def _suggest_ui(page, prefix: str) -> None:
    """В новой статье печатает начало тега в `input[name=tags]` (знак за знаком: нужны и события ввода)."""
    open_new_article(page)
    tags = article_form(page).locator("input[name=tags]")
    tags.click()
    tags.press_sequentially(prefix, delay=30)


def _suggestion(page, tag: str):
    return page.locator("ul[data-kb-tag-suggest]").locator(f'li[data-tag="{tag}"]')


def _suggested_by_route(page, prefix: str) -> list:
    """Теги ответа `/kb/tags/suggest/?q=<prefix>` (прямой GET от имени вошедшего автора)."""
    response = helpers_org.direct_get(page, "/kb/tags/suggest/?" + urlencode({"q": prefix}))
    assert response.status == 200, f"подсказка тегов: код {response.status}"
    return [html.unescape(name) for name in re.findall(r'data-tag="([^"]*)"', response.text())]


def _tag_status(page, tag: str) -> int:
    """Код ответа страницы тега `/kb/tags/?name=<tag>`."""
    response = page.goto("/kb/tags/?" + urlencode({"name": tag}))
    return response.status


def _tag_page_ids(page, tag: str) -> list:
    assert _tag_status(page, tag) == 200
    expect(page.locator('[data-kb-page="tag"]')).to_be_visible()
    return [li.get_attribute("data-article-id") for li in page.locator("[data-kb-list] li[data-article-id]").all()]


# --- Подписка: помощники файла ----------------------------------------------------------------------------

def _subscribe_button(page):
    return page.locator('button[data-action="kb-subscribe"]')


def _open_rubric_page(page, rubric_id: str) -> None:
    page.goto(f"/kb/rubrics/{rubric_id}/")
    expect(page.locator('[data-kb-page="rubric"]')).to_be_visible()
    expect(_subscribe_button(page)).to_be_visible()


def _notice_row(page, word: str):
    """Строка списка `/notifications/` со словом темы (список только читается)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _expect_subscription_notice(reader_page, base: int, title: str, subscribed_rubric: str) -> None:
    """Ждёт +1 на колокольчике подписчика и сверяет текст уведомления «Статья в рубрике «…»: …», где в кавычках — рубрика
    ПОДПИСКИ получателя, а не рубрика статьи (п. 51 раздела 17)."""
    helpers_notify.wait_bell_count(reader_page, base + 1, timeout_ms=NOTIFY_WAIT_MS)
    word = title.split()[-1]
    rows = _notice_row(reader_page, word)
    expect(rows).to_have_count(1)
    assert _norm(rows.locator('[data-field="text"]').inner_text()) == _norm(f"Статья в рубрике «{subscribed_rubric}»: {title}")


def _bell_base(page) -> int:
    page.goto("/kb/")
    helpers_notify.wait_ws_open(page)
    return helpers_notify.bell_count(page)


# --- Тесты: рубрики -----------------------------------------------------------------------------------------

def test_k07_manager_creates_three_level_rubrics_and_fourth_level_is_refused_with_limit(admin_page):
    """Сценарий 7, п. 1: управляющий создаёт «Сеть», в ней «VPN», в ней «Клиенты» — дерево на три уровня; четвёртый
    уровень создать нельзя, показан предел «Не глубже трёх уровней» (FR-418)."""
    net, vpn, clients = (helpers_org.unique_name(n) for n in ("Сеть", "VPN", "Клиенты"))
    # п. 1: создаёт «Сеть», в ней «VPN», в ней «Клиенты»
    net_id, vpn_id, clients_id = _tree(admin_page, net, vpn, clients)
    # п. 1: дерево показывает три уровня
    _open_rubrics(admin_page)
    assert _depth(admin_page, net_id) == "1"
    assert _depth(admin_page, vpn_id) == "2"
    assert _depth(admin_page, clients_id) == "3"
    # п. 1: четвёртый уровень (внутри «Клиенты») создать нельзя — отказ у поля «Родитель» с пределом
    fourth = helpers_org.unique_name("Четвёртый")
    _submit_new(admin_page, fourth, parent_name=clients, parent_id=clients_id)
    expect(_error(admin_page, "parent")).to_contain_text(DEPTH_LIMIT_TEXT)
    _open_rubrics(admin_page)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=fourth)).to_have_count(0)


def test_k07_duplicate_sibling_name_case_insensitive_is_refused_and_same_name_in_other_branch_is_allowed(admin_page):
    """Сценарий 7, п. 2: второе «VPN» или «vpn» в той же «Сети» — отказ (уникальность среди соседей без учёта
    регистра); то же название в другой ветке допустимо (FR-418)."""
    net, other = helpers_org.unique_name("Сеть"), helpers_org.unique_name("Другая")
    word = helpers_org.unique_name("VPN")
    net_id = create_rubric(admin_page, net)
    create_rubric(admin_page, word, parent_name=net)
    other_id = create_rubric(admin_page, other)
    # п. 2: создаёт ещё такое же название в «Сети» — отказ у поля «Название»
    _submit_new(admin_page, word, parent_name=net, parent_id=net_id)
    expect(_error(admin_page, "name")).to_contain_text(DUPLICATE_TEXT)
    # п. 2: то же название строчными — тоже отказ
    _submit_new(admin_page, word.lower(), parent_name=net, parent_id=net_id)
    expect(_error(admin_page, "name")).to_contain_text(DUPLICATE_TEXT)
    _open_rubrics(admin_page)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=word.lower())).to_have_count(1)
    # п. 2: в другой ветке такое название допустимо — рубрика создана, флеш успеха
    _submit_new(admin_page, word, parent_name=other, parent_id=other_id)
    expect(_flash(admin_page, "Рубрика создана")).to_be_visible()
    _open_rubrics(admin_page)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=word)).to_have_count(2)


def test_k07_delete_of_rubric_with_subrubric_or_article_even_in_trash_is_refused_and_general_is_not_deletable(
        admin_page, employee):
    """Сценарий 7, п. 3: «Удалить» у рубрики с подрубрикой, со статьёй или со статьёй в корзине — отказ «Сначала
    перенесите»; «Общее» не удаляется (FR-419)."""
    author = make_editor(employee)
    parent, child = helpers_org.unique_name("Сеть"), helpers_org.unique_name("VPN")
    with_article, with_trashed = helpers_org.unique_name("Со-статьёй"), helpers_org.unique_name("С-корзиной")
    parent_id, _ = _tree(admin_page, parent, child)
    article_rubric_id = create_rubric(admin_page, with_article)
    trashed_rubric_id = create_rubric(admin_page, with_trashed)
    _published(author.page, with_article)
    trashed_id, _ = _published(author.page, with_trashed)
    _trash(admin_page, trashed_id)
    # п. 3: рубрика с подрубрикой, рубрика со статьёй, рубрика только со статьёй в корзине — отказ в строке рубрики
    for rubric_id in (parent_id, article_rubric_id, trashed_rubric_id):
        _submit_delete(admin_page, rubric_id)
        alert = _own(_row(admin_page, rubric_id), "[role=alert][data-code]")
        expect(alert).to_have_attribute("data-code", "not_empty")
        expect(alert).to_contain_text(NOT_EMPTY_TEXT)
        _open_rubrics(admin_page)
        expect(_row(admin_page, rubric_id)).to_have_count(1)
    # п. 3: «Общее» не удаляется
    default_row = admin_page.locator("[data-kb-rubrics] li[data-rubric-id]").filter(
        has=admin_page.locator('[data-field="name"]', has_text=re.compile(rf"^\s*{DEFAULT_RUBRIC}\s*$"))).first
    default_id = default_row.get_attribute("data-rubric-id")
    _submit_delete(admin_page, default_id)
    alert = _own(_row(admin_page, default_id), "[role=alert][data-code]")
    expect(alert).to_have_attribute("data-code", "default_undeletable")
    expect(alert).to_contain_text("Рубрику «Общее» нельзя удалить")
    _open_rubrics(admin_page)
    expect(_row(admin_page, default_id)).to_have_count(1)


def test_k07_delete_of_empty_rubric_succeeds_and_journal_records_it(admin_page):
    """Сценарий 7, п. 4: «Удалить» у пустой рубрики — она удалена, в журнале запись `knowledge.rubric_deleted` с
    названием (FR-419, FR-438)."""
    name = helpers_org.unique_name("Пустая")
    rubric_id = create_rubric(admin_page, name)
    # п. 4: нажимает «Удалить» (окно подтверждения «Удалить рубрику?») — рубрика удалена, флеш
    messages = _submit_delete(admin_page, rubric_id)
    expect(_flash(admin_page, "Рубрика удалена")).to_be_visible()
    assert messages == ["Удалить рубрику?"]
    expect(_row(admin_page, rubric_id)).to_have_count(0)
    _open_rubrics(admin_page)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=name)).to_have_count(0)
    # п. 4: в журнале запись об удалении этой рубрики, название — в значении «было»
    sides = helpers_org.audit_sides(admin_page, "knowledge.rubric_deleted", rubric_id)
    assert len(sides) == 1, f"записей rubric_deleted по рубрике {rubric_id}: {len(sides)}"
    assert name in sides[0][0]


def test_k07_move_or_rename_of_rubric_keeps_articles_in_it_and_article_urls_unchanged(admin_page, employee):
    """Сценарий 7, п. 5: перенос рубрики в другую и переименование оставляют статьи в ней, адреса статей не
    меняются (FR-418, FR-404)."""
    author = make_editor(employee)
    name, target = helpers_org.unique_name("Сеть"), helpers_org.unique_name("Куда")
    renamed = helpers_org.unique_name("Переименована")
    rubric_id, target_id = create_rubric(admin_page, name), create_rubric(admin_page, target)
    article_id, _ = _published(author.page, name)
    # п. 5: переносит рубрику в другую — флеш, рубрика на втором уровне
    _submit_move(admin_page, rubric_id, target, target_id)
    expect(_flash(admin_page, "Рубрика перенесена")).to_be_visible()
    assert _depth(admin_page, rubric_id) == "2"
    # п. 5: статья осталась в ней, адрес тот же
    admin_page.goto(f"/kb/{article_id}/")
    assert admin_page.url.rstrip("/").endswith(f"/kb/{article_id}")
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    expect(admin_page.locator('article [data-field="rubric"]')).to_contain_text(name)
    assert article_id in rubric_page_ids(admin_page, rubric_id)
    # п. 5: переименовывает — флеш, статья в ней, адрес тот же, на странице статьи новое название
    _submit_rename(admin_page, rubric_id, renamed)
    expect(_flash(admin_page, "Рубрика переименована")).to_be_visible()
    admin_page.goto(f"/kb/{article_id}/")
    assert admin_page.url.rstrip("/").endswith(f"/kb/{article_id}")
    expect(admin_page.locator('article [data-field="rubric"]')).to_contain_text(renamed)
    expect(admin_page.locator('article [data-field="rubric"]')).not_to_contain_text(name)
    assert article_id in rubric_page_ids(admin_page, rubric_id)


def test_k07_rubric_management_by_direct_link_is_denied_for_non_manager(admin_page, employee):
    """Сценарий 7, п. 6: сотрудник без права «Управление базой знаний» (с правом править и без прав) по прямой ссылке
    на управление рубриками получает отказ; прямые действия над рубриками тоже отклонены и ничего не меняют
    (FR-406, FR-409)."""
    name = helpers_org.unique_name("Сеть")
    rubric_id = create_rubric(admin_page, name)
    attempted = helpers_org.unique_name("Чужая")
    for person in (make_editor(employee), make_reader(employee)):
        page = person.page
        # п. 6: открывает управление рубриками по прямой ссылке — отказ, дерева управления нет
        response = page.goto("/kb/rubrics/")
        assert response.status == 403
        expect(page.locator("[data-kb-rubrics]")).to_have_count(0)
        # п. 6: прямые POST создания, переименования, переноса и удаления — отказ 403
        assert helpers_org.direct_post(page, "/kb/rubrics/new/", {"name": attempted, "parent": ""}).status == 403
        assert helpers_org.direct_post(page, f"/kb/rubrics/{rubric_id}/rename/", {"name": attempted}).status == 403
        assert helpers_org.direct_post(page, f"/kb/rubrics/{rubric_id}/move/", {"parent": ""}).status == 403
        assert helpers_org.direct_post(page, f"/kb/rubrics/{rubric_id}/delete/").status == 403
    # п. 6: ничего не изменилось — своя рубрика на месте, чужой нет
    _open_rubrics(admin_page)
    expect(_row(admin_page, rubric_id)).to_have_count(1)
    expect(_own(_row(admin_page, rubric_id), '[data-field="name"]')).to_have_text(name)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=attempted)).to_have_count(0)


# --- Тесты: теги --------------------------------------------------------------------------------------------

def test_k07_tag_input_suggests_existing_tags_of_published_articles_and_merges_vpn_case_variants(admin_page, employee):
    """Сценарий 7, п. 7: автор печатает начало тега — подсказывается существующий тег опубликованных статей; «VPN» и
    «vpn» склеиваются в один тег (FR-420)."""
    author = make_editor(employee)
    rubric = helpers_org.unique_name("Сеть")
    create_rubric(admin_page, rubric)
    tag = unique_word("vp")
    first_id, _ = _published(author.page, rubric, tags=tag.upper())
    second_id, _ = _published(author.page, rubric, tags=tag)
    # п. 7: на страницах статей тег один и тот же — строчный
    for article_id in (first_id, second_id):
        open_article(author.page, article_id)
        expect(author.page.locator(f'article a[data-tag="{tag}"]')).to_have_count(1)
        expect(author.page.locator(f'article a[data-tag="{tag.upper()}"]')).to_have_count(0)
    # п. 7: печатает начало — подсказан «vpn»-тег, в одном экземпляре
    _suggest_ui(author.page, tag[:7])
    expect(_suggestion(author.page, tag)).to_have_count(1)
    assert _suggested_by_route(author.page, tag[:7]).count(tag) == 1
    assert tag.upper() not in _suggested_by_route(author.page, tag[:7])
    # п. 7: страница тега одна — обе статьи на ней
    ids = _tag_page_ids(author.page, tag)
    assert first_id in ids and second_id in ids


def test_k07_eleven_tags_or_tag_over_40_chars_is_refused_with_limit_shown(admin_page, employee):
    """Сценарий 7, п. 8: 11 тегов или тег длиннее 40 знаков — сохранения нет, показан предел; 10 тегов и тег из
    40 знаков принимаются (FR-420)."""
    author = make_editor(employee)
    rubric = helpers_org.unique_name("Сеть")
    create_rubric(admin_page, rubric)
    page = author.page
    root = unique_word("kt")
    # п. 8: 11 тегов — сохранения нет, показан предел «Не больше 10 тегов»
    title = unique_title()
    open_new_article(page)
    fill_article_form(page, title=title, text="Текст статьи.", rubric=rubric,
                      tags=", ".join(f"{root}{letter}" for letter in "abcdefghijk"))
    press_save(page)
    expect(page.locator('[data-error="tags"][data-code="tags_too_many"]')).to_contain_text(TAGS_MANY_TEXT)
    assert re.search(r"/kb/new/$", page.url)
    page.goto("/kb/")
    expect(page.locator("body")).not_to_contain_text(title.split()[-1])
    # п. 8: ровно 10 тегов — сохранено (граница)
    title = unique_title()
    open_new_article(page)
    fill_article_form(page, title=title, text="Текст статьи.", rubric=rubric,
                      tags=", ".join(f"{root}{letter}" for letter in "abcdefghij"))
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    # п. 8: тег из 41 знака — сохранения нет, показан предел «Тег не длиннее 40 знаков»
    long_tag = root + "z" * (41 - len(root))
    title = unique_title()
    open_new_article(page)
    article_form(page).locator("input[name=tags]").evaluate("el => el.removeAttribute('maxlength')")
    fill_article_form(page, title=title, text="Текст статьи.", rubric=rubric, tags=long_tag)
    press_save(page)
    expect(page.locator('[data-error="tags"][data-code="tag_too_long"]')).to_contain_text(TAG_LONG_TEXT)
    assert re.search(r"/kb/new/$", page.url)
    page.goto("/kb/")
    expect(page.locator("body")).not_to_contain_text(title.split()[-1])
    # п. 8: тег ровно из 40 знаков — сохранён (граница)
    ok_tag = root + "y" * (40 - len(root))
    open_new_article(page)
    article_form(page).locator("input[name=tags]").evaluate("el => el.removeAttribute('maxlength')")
    fill_article_form(page, title=unique_title(), text="Текст статьи.", rubric=rubric, tags=ok_tag)
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    expect(article_form(page).locator("input[name=tags]")).to_have_value(re.compile(re.escape(ok_tag)))


def test_k07_tag_losing_last_published_article_disappears_from_suggestions_and_tag_page(admin_page, employee):
    """Сценарий 7, п. 9: тег, у которого пропала последняя опубликованная статья, исчезает из подсказок и со страницы
    тега (FR-420)."""
    author = make_editor(employee)
    rubric = helpers_org.unique_name("Сеть")
    create_rubric(admin_page, rubric)
    page = author.page
    root = unique_word("kt")
    lost, kept = root + "lost", root + "kept"
    lost_id, _ = _published(page, rubric, tags=lost)
    _published(page, rubric, tags=kept)
    # до: оба тега подсказываются, страница тега есть
    _suggest_ui(page, root)
    expect(_suggestion(page, kept)).to_have_count(1)
    expect(_suggestion(page, lost)).to_have_count(1)
    assert _tag_status(page, lost) == 200
    # п. 9: последняя статья теряет тег (автор убирает тег и сохраняет)
    open_edit(page, lost_id)
    fill_article_form(page, tags="")
    press_save(page)
    page.wait_for_url(re.compile(rf"/kb/{lost_id}/$"))
    expect(page.locator(f'article[data-article-id="{lost_id}"]')).to_be_visible()
    expect(page.locator(f'article a[data-tag="{lost}"]')).to_have_count(0)
    # п. 9: в подсказках тега больше нет (второй тег с тем же началом — контроль), страницы тега нет
    _suggest_ui(page, root)
    expect(_suggestion(page, kept)).to_have_count(1)
    expect(_suggestion(page, lost)).to_have_count(0)
    names = _suggested_by_route(page, root)
    assert kept in names and lost not in names
    assert _tag_status(page, lost) == 404
    assert _tag_status(page, kept) == 200


def test_k07_tag_only_on_draft_or_trashed_article_gives_no_suggestion_and_no_tag_page(admin_page, employee):
    """Сценарий 7, п. 12: тег есть только у черновика или у статьи в корзине — подсказки нет, страница тега не
    показывается (FR-420)."""
    author = make_editor(employee)
    rubric = helpers_org.unique_name("Сеть")
    create_rubric(admin_page, rubric)
    page = author.page
    root = unique_word("kt")
    published_tag, draft_tag, trashed_tag = root + "pub", root + "dra", root + "tra"
    _published(page, rubric, tags=published_tag)
    create_draft(page, title=unique_title(), rubric=rubric, tags=draft_tag)
    trashed_id, _ = _published(page, rubric, tags=trashed_tag)
    _trash(admin_page, trashed_id)
    # п. 12: автор вводит начало — подсказан только тег опубликованной статьи (он же — признак прихода фрагмента)
    _suggest_ui(page, root)
    expect(_suggestion(page, published_tag)).to_have_count(1)
    expect(_suggestion(page, draft_tag)).to_have_count(0)
    expect(_suggestion(page, trashed_tag)).to_have_count(0)
    names = _suggested_by_route(page, root)
    assert published_tag in names and draft_tag not in names and trashed_tag not in names
    # п. 12: страница тега у черновика и у статьи в корзине не показывается, у опубликованной есть
    assert _tag_status(page, draft_tag) == 404
    assert _tag_status(page, trashed_tag) == 404
    assert _tag_status(page, published_tag) == 200


# --- Тесты: подписка ----------------------------------------------------------------------------------------

def test_k07_subscribe_button_becomes_unsubscribe_and_subscription_covers_subrubrics(admin_page, employee):
    """Сценарий 7, п. 10: «Подписаться» на рубрику «Сеть» становится «Отписаться» (и при повторном открытии), снова
    нажатая возвращает «Подписаться»; подписка действует на подрубрику (FR-437)."""
    reader, author = make_reader(employee), make_editor(employee)
    net, vpn = helpers_org.unique_name("Сеть"), helpers_org.unique_name("VPN")
    net_id, _ = _tree(admin_page, net, vpn)
    page = reader.page
    # п. 10: на странице рубрики кнопка «Подписаться»; нажимает — «Отписаться»
    _open_rubric_page(page, net_id)
    button = _subscribe_button(page)
    expect(button).to_have_attribute("data-subscribed", "false")
    expect(button).to_have_text("Подписаться")
    button.click()
    expect(button).to_have_attribute("data-subscribed", "true")
    expect(button).to_have_text("Отписаться")
    # п. 10: открывает рубрику снова — «Отписаться»
    _open_rubric_page(page, net_id)
    expect(_subscribe_button(page)).to_have_attribute("data-subscribed", "true")
    expect(_subscribe_button(page)).to_have_text("Отписаться")
    # п. 10: подписка действует на подрубрику: публикация в «VPN» даёт уведомление
    base = _bell_base(page)
    _, title = _published(author.page, vpn)
    _expect_subscription_notice(page, base, title, net)
    # п. 10: «Отписаться» возвращает «Подписаться», и после повторного открытия тоже
    _open_rubric_page(page, net_id)
    _subscribe_button(page).click()
    expect(_subscribe_button(page)).to_have_attribute("data-subscribed", "false")
    expect(_subscribe_button(page)).to_have_text("Подписаться")
    _open_rubric_page(page, net_id)
    expect(_subscribe_button(page)).to_have_attribute("data-subscribed", "false")


def test_k07_subscriber_gets_notification_when_article_is_published_in_subrubric(admin_page, employee):
    """Сценарий 7, п. 11: подписчик «Сети» получает уведомление, когда в подрубрике «VPN» публикуется статья; текст —
    «Статья в рубрике «Сеть»: <заголовок>» (рубрика подписки, п. 51 раздела 17) (FR-434, FR-437)."""
    reader, author = make_reader(employee), make_editor(employee)
    net, vpn = helpers_org.unique_name("Сеть"), helpers_org.unique_name("VPN")
    net_id, _ = _tree(admin_page, net, vpn)
    page = reader.page
    _open_rubric_page(page, net_id)
    _subscribe_button(page).click()
    expect(_subscribe_button(page)).to_have_attribute("data-subscribed", "true")
    base = _bell_base(page)
    # п. 11: в подрубрике «VPN» публикуется статья — на колокольчике +1, в списке уведомление нужного вида
    _, title = _published(author.page, vpn)
    _expect_subscription_notice(page, base, title, net)


# --- Тесты: перенос и предел названия ----------------------------------------------------------------------

def test_k07_move_of_rubric_into_own_subrubric_is_refused_with_explanation(admin_page):
    """Сценарий 7, п. 13: перенос «Сети» в её подрубрику «Клиенты» — отказ с объяснением «Нельзя перенести рубрику в её
    подрубрику»; дерево не меняется (FR-418)."""
    net, clients = helpers_org.unique_name("Сеть"), helpers_org.unique_name("Клиенты")
    net_id, clients_id = _tree(admin_page, net, clients)
    # п. 13: переносит «Сеть» в «Клиенты» — отказ у поля «Родитель» с объяснением
    _submit_move(admin_page, net_id, clients, clients_id)
    expect(_error(admin_page, "parent")).to_contain_text("Нельзя перенести рубрику в её подрубрику")
    expect(_error(admin_page, "parent")).to_have_attribute("data-code", "parent_descendant")
    # п. 13: дерево прежнее
    assert _depth(admin_page, net_id) == "1"
    assert _depth(admin_page, clients_id) == "2"


def test_k07_move_of_rubric_making_subtree_deeper_than_three_levels_is_refused_with_explanation(admin_page):
    """Сценарий 7, п. 14: перенос трёхуровневой «Сети» в «Общее» — отказ «Не глубже трёх уровней»: глубина поддерева
    стала бы больше трёх; дерево не меняется (FR-418)."""
    net, vpn, clients = (helpers_org.unique_name(n) for n in ("Сеть", "VPN", "Клиенты"))
    net_id, vpn_id, clients_id = _tree(admin_page, net, vpn, clients)
    default_row = admin_page.locator("[data-kb-rubrics] li[data-rubric-id]").filter(
        has=admin_page.locator('[data-field="name"]', has_text=re.compile(rf"^\s*{DEFAULT_RUBRIC}\s*$"))).first
    default_id = default_row.get_attribute("data-rubric-id")
    # п. 14: переносит «Сеть» в «Общее» — отказ с объяснением про три уровня
    _submit_move(admin_page, net_id, DEFAULT_RUBRIC, default_id)
    expect(_error(admin_page, "parent")).to_contain_text(DEPTH_LIMIT_TEXT)
    expect(_error(admin_page, "parent")).to_have_attribute("data-code", re.compile(r"^(depth_exceeded|too_deep)$"))
    # п. 14: рубрики остались на своих уровнях
    assert _depth(admin_page, net_id) == "1"
    assert _depth(admin_page, vpn_id) == "2"
    assert _depth(admin_page, clients_id) == "3"


def test_k07_rubric_name_of_100_chars_is_accepted_and_101_chars_is_refused_with_limit(admin_page):
    """Сценарий 7, п. 15: название из 100 знаков принято, из 101 — отказ с пределом «Название не длиннее 100 знаков»
    (FR-418)."""
    base = unique_word("r")
    ok_name = (base + "я" * 100)[:100]
    bad_base = unique_word("r")
    bad_name = (bad_base + "я" * 101)[:101]
    assert len(ok_name) == 100 and len(bad_name) == 101
    # п. 15: 100 знаков — принято
    _submit_new(admin_page, ok_name)
    expect(_flash(admin_page, "Рубрика создана")).to_be_visible()
    _open_rubrics(admin_page)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=base)).to_have_count(1)
    # п. 15: 101 знак — отказ с пределом, рубрики нет
    _submit_new(admin_page, bad_name)
    expect(_error(admin_page, "name")).to_contain_text(NAME_LIMIT_TEXT)
    expect(_error(admin_page, "name")).to_have_attribute("data-code", "name_too_long")
    _open_rubrics(admin_page)
    expect(admin_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=bad_base)).to_have_count(0)
