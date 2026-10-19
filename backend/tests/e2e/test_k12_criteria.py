"""T-5151: критерии успеха и сквозные проверки среза 005 — ширина 360 px, безопасность содержимого, одиночные замеры
времени, статья за пять минут (FR-401, FR-402, FR-403, FR-408, FR-425, NFR-401, NFR-402, NFR-403, NFR-405, NFR-406).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md):
- каждый тест заводит своих сотрудников (редактор — «Сотрудник ИТ», читатель — «Руководитель», управляющий —
  администратор круга `admin_page`), свои рубрики и статьи; названия уникальны; общих настроек тесты не меняют, сброса
  стенда в файле нет (данные круга общие);
- ширина 360 px — `helpers_kb.narrow_context` с сессией нужного сотрудника; проверка — `helpers_kb.page_fits`
  (`scrollWidth <= innerWidth`); прокрутка внутри блока `kb-scroll` допустима и проверяется `helpers_kb.scrolls_inside`;
- безопасность: «выполнение» ловится флагом `window.__kb_ran` и окнами `dialog`, «чужие адреса» — событием `request`
  контекста (узел, не совпадающий с узлом портала); сама разметка проверяется в области статьи или комментария;
- замеры времени (решение 38 задач) — одиночные, на обычных данных стенда, лучшее из трёх: это дополнительная проверка
  шагов, а не замена нагрузочного прогона T-5304 и серверного теста предпросмотра. Время берётся `time.perf_counter()`
  от действия до видимого результата (ожидание результата — `page.wait_for_function` с опросом по кадру, не сон);
- предпросмотр: текст обычной статьи ровно из 200 000 знаков (заголовки, списки, абзацы, код в строке, небольшие
  таблицы), а не патологический Markdown (план: «Риски»).
"""
import re
import time
from urllib.parse import quote, urlencode, urlparse

from playwright.sync_api import expect

from tests.e2e import helpers_kb, helpers_org
from tests.e2e.helpers_kb import (
    article_form, create_draft, create_rubric, history_versions, home_ids, open_article, open_edit, open_new_article,
    open_preview, open_text_tab, press_publish_in_form, press_save, publish_from_article_page, unique_title,
    unique_word)

BEST_OF = 3                # число замеров, из которых берётся лучший (как в серверном тесте предпросмотра)
PAGE_LIMIT = 0.5           # с: страницы базы знаний и срезов 001–004 (NFR-402)
SEARCH_LIMIT = 1.0         # с: всплывающая выдача и страница результатов (NFR-401)
PREVIEW_LIMIT = 1.0        # с: предпросмотр текста до 200 000 знаков (NFR-403)
FIVE_MINUTES = 300.0       # с: статья за пять минут (критерий успеха)
PREVIEW_MARK = "конецпредпросмотра"

# пробы разметки для статьи: перечень сокращён из 36 проб рендера (CONTRACT-005, 6.2), без почты и телефонов
# (публикация без предупреждения ПДн); любой из них не должен выполниться и не должен вывести разметку
ARTICLE_PROBES = (
    "<script>window.__kb_ran = 1</script>",
    '<img src="http://evil.example/p.png" onerror="window.__kb_ran = 2">',
    '<svg onload="window.__kb_ran = 3"></svg>',
    '<iframe src="http://evil.example/frame"></iframe>',
    '<div style="x" onclick="window.__kb_ran = 4">hi</div>',
    "[a](javascript:window.__kb_ran=5)",
    "[b](JaVaScRiPt:window.__kb_ran=6)",
    "[c](vbscript:msgbox(1))",
    "[d](data:text/html;base64,PHNjcmlwdD4=)",
    "[e](//evil.example/x)",
    "[f](/\\evil.example)",
    "[g][1]\n\n[1]: javascript:window.__kb_ran=7",
    "![h](http://evil.example/p.png)",
    "![i](data:image/svg+xml;base64,PHN2Zz4=)",
    "![j](/kb/1/files/1/)",
    "![k](att:99999)",
    '[l](http://ok.example "t\\" onmouseover=\\"window.__kb_ran=8")',
    "| a | <b onclick=x>b</b> |\n|---|---|\n| <script>1</script> | [y](javascript:1) |",
    "[m](/search/)",
    "[n](https://example.ru)",
)

# что нельзя найти внутри показанного текста статьи или комментария: возвращает список нарушений
_SCAN_JS = """el => {
  const bad = [];
  for (const n of el.querySelectorAll('script,iframe,svg,object,embed,form,style,link,base,meta')) {
    bad.push('тег ' + n.tagName);
  }
  for (const n of el.querySelectorAll('*')) {
    for (const a of n.attributes) {
      if (/^on/i.test(a.name) || a.name === 'style') bad.push('атрибут ' + a.name + ' у ' + n.tagName);
    }
  }
  for (const a of el.querySelectorAll('a')) {
    const h = a.getAttribute('href') || '';
    const rel = a.getAttribute('rel') || '';
    if (/^https?:\\/\\//i.test(h)) {
      if (!/noopener/.test(rel) || !/noreferrer/.test(rel)) bad.push('внешняя ссылка без rel: ' + h);
    } else if (/^mailto:/i.test(h)) {
    } else if (h.startsWith('/') && !h.startsWith('//') && !h.startsWith('/\\\\')) {
    } else {
      bad.push('недопустимая ссылка: ' + h);
    }
  }
  for (const i of el.querySelectorAll('img')) {
    const s = i.getAttribute('src') || '';
    if (!/^\\/kb\\/\\d+\\/images\\/\\d+\\/$/.test(s)) bad.push('картинка не из вложений статьи: ' + s);
  }
  return bad;
}"""


def _rubric(admin_page, *, parent_name=None, name=None):
    """Рубрика круга (создаёт управляющий); возвращает (название, номер)."""
    name = name or helpers_org.unique_name("Рубрика")
    return name, create_rubric(admin_page, name, parent_name=parent_name)


def _assert_csp(response, label) -> None:
    """Заголовок `Content-Security-Policy` ответа страницы статьи: `script-src 'self'` без `'unsafe-inline'` (1.2, NFR-405)."""
    csp = response.headers.get("content-security-policy", "")
    scripts = [part.strip() for part in csp.split(";") if part.strip().startswith("script-src")]
    assert scripts, f"{label}: в ответе нет script-src в Content-Security-Policy ({csp!r})"
    assert "'self'" in scripts[0].split() and "'unsafe-inline'" not in scripts[0], f"{label}: script-src {scripts[0]!r}"


def _watch(page, portal_url) -> dict:
    """Следит за страницей: чужие адреса (узел запроса не совпадает с узлом портала), окна `dialog` и выполнение
    (флаг `window.__kb_ran`). Окна закрываются. Возвращает словарь со списками `foreign` и `dialogs`."""
    host = urlparse(portal_url).hostname
    seen = {"foreign": [], "dialogs": []}

    def on_request(request):
        parts = urlparse(request.url)
        if parts.scheme in ("http", "https", "ws", "wss") and parts.hostname != host:
            seen["foreign"].append(parts.hostname)

    page.context.on("request", on_request)
    page.on("dialog", lambda dialog: (seen["dialogs"].append(dialog.message), dialog.dismiss()))
    return seen


def _assert_nothing_ran(page, seen, label) -> None:
    """Скрипты из текста не выполнились, окон не было, запросов на чужие адреса не было."""
    assert page.evaluate("window.__kb_ran") is None, f"{label}: скрипт из текста выполнился"
    assert not seen["dialogs"], f"{label}: текст открыл окно"
    assert not seen["foreign"], f"{label}: запросы на чужие адреса: {sorted(set(seen['foreign']))}"


def _assert_safe_markup(container, label) -> None:
    """В показанном тексте нет тегов, атрибутов, ссылок и картинок, которых не должно быть (FR-402, NFR-405)."""
    bad = container.evaluate(_SCAN_JS)
    assert not bad, f"{label}: {bad}"


def _wide_text() -> str:
    """Широкая таблица (14 столбцов) и длинная строка кода (400 знаков) — как у проверки сценария 1, п. 15."""
    head = "| " + " | ".join(f"столбец-{n}-с-длинным-названием" for n in range(14)) + " |\n"
    rule = "|" + "---|" * 14 + "\n"
    cells = "| " + " | ".join(f"значение-{n}-длинное" for n in range(14)) + " |\n"
    return "Вводный абзац статьи.\n\n" + head + rule + cells + "\n```\n" + "x" * 400 + "\n```\n"


def _wide_text_changed() -> str:
    """Тот же вид, другая правка: вторая версия для истории и сравнения."""
    return _wide_text().replace("значение-3-длинное", "значение-3-новое").replace("x" * 400, "y" * 400)


def _assert_scroll_blocks(page, container, label) -> None:
    """Таблица и блок кода в области `container` прокручиваются внутри своего блока `kb-scroll` (NFR-406)."""
    table_block = container.locator("div.kb-scroll:has(table)").first
    code_block = container.locator("div.kb-scroll:has(pre)").first
    expect(table_block).to_be_visible()
    expect(code_block).to_be_visible()
    assert helpers_kb.scrolls_inside(table_block), f"{label}: таблица не прокручивается внутри своего блока"
    assert helpers_kb.scrolls_inside(code_block), f"{label}: блок кода не прокручивается внутри своего блока"


def _fits(page, url, root, label=None) -> None:
    """Открывает страницу, ждёт корень и проверяет, что горизонтальной прокрутки у страницы нет."""
    page.goto(url)
    expect(page.locator(root)).to_be_visible()
    assert helpers_kb.page_fits(page), f"на 360 px страница шире экрана: {label or url}"


def _published(author_page, rubric, *, title=None, text="Текст статьи.", tags="") -> str:
    """Опубликованная статья автора через интерфейс; возвращает номер."""
    article_id = create_draft(author_page, title=title or unique_title(), text=text, rubric=rubric, tags=tags)
    publish_from_article_page(author_page, article_id)
    return article_id


def _ordinary_text(size: int = helpers_kb.TEXT_LIMIT) -> str:
    """Обычный текст статьи ровно из `size` знаков: заголовки, абзацы с жирным и кодом в строке, списки, небольшие
    таблицы; в конце — метка `PREVIEW_MARK`, по которой видно, что показан весь текст."""
    words = ("сервер доступ пароль подключение удалённый рабочий стол принтер настройка почтовый ящик сеть "
             "сертификат обновление драйвер резервная копия учётная запись заявка очередь ответ решение "
             "инструкция сотрудник отдел").split()
    tail = f"\n\n{PREVIEW_MARK}"
    blocks: list = []
    total = 0
    n = 0
    while True:
        part = [words[(n * 7 + k) % len(words)] for k in range(40)]
        block = (f"## Раздел {n}\n\n" + " ".join(part[:20]) + f" **{part[20]}** `{part[21]}` " + " ".join(part[22:])
                 + ".\n\n- " + part[0] + "\n- " + part[1] + "\n- " + part[2] + "\n\n")
        if n % 20 == 0:
            block += "| имя | значение |\n|---|---|\n| " + part[3] + " | " + part[4] + " |\n\n"
        if total + len(block) + len(tail) + 3 > size:
            break
        blocks.append(block)
        total += len(block)
        n += 1
    body = "".join(blocks)
    pad = size - len(body) - len(tail)
    text = body + ("слово " * (pad // 6 + 1))[:pad] + tail
    assert len(text) == size, f"текст должен быть из {size} знаков, а он из {len(text)}"
    return text


def _best(measure, times: int = BEST_OF) -> float:
    """Лучшее из `times` замеров (секунды): `measure()` возвращает одно время."""
    return min(measure() for _ in range(times))


def _title_of_word(word: str) -> str:
    return f"Подключение VPN {word}"


# --- Ширина 360 px (NFR-406) --------------------------------------------------------------------------------


def test_k12_read_pages_home_rubric_tag_article_have_no_horizontal_scroll_at_360px(
        browser, browser_context_args, admin_page, employee):
    """Критерий «все страницы среза работают на 360 px без горизонтальной прокрутки»: главная, рубрика, тег и статья
    с широкой таблицей, длинным кодом и комментарием; таблица и код прокручиваются внутри блока (NFR-406)."""
    parent_name, _parent_id = _rubric(admin_page)
    sub_name, sub_id = _rubric(admin_page, parent_name=parent_name)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    tag = unique_word("tag")
    article_id = _published(author.page, sub_name, text=_wide_text(), tags=tag)
    helpers_kb.add_comment(reader.page, article_id, "Комментарий читателя: не сработало на Windows 11, перезапуск помог.")
    context = helpers_kb.narrow_context(browser, browser_context_args, reader.page)
    try:
        page = context.new_page()
        # главная: дерево рубрик и «Новые и изменённые»
        _fits(page, "/kb/", '[data-kb-page="home"]', "главная")
        expect(page.locator("[data-kb-tree]")).to_be_visible()
        # рубрика со статьёй
        _fits(page, f"/kb/rubrics/{sub_id}/", '[data-kb-page="rubric"]', "рубрика")
        expect(page.locator(f'[data-kb-list] li[data-article-id="{article_id}"]')).to_be_visible()
        # тег (имя в процентной записи)
        _fits(page, "/kb/tags/?" + urlencode({"name": tag}), '[data-kb-page="tag"]', "тег")
        expect(page.locator(f'[data-kb-list] li[data-article-id="{article_id}"]')).to_be_visible()
        # статья: таблица и код — внутри своих блоков, комментарии под статьёй
        _fits(page, f"/kb/{article_id}/", f'article[data-article-id="{article_id}"]', "статья")
        _assert_scroll_blocks(page, page.locator('[data-field="body"]'), "статья")
        expect(page.locator("section#comments[data-kb-comments] li[data-comment-id]")).to_have_count(1)
        assert helpers_kb.page_fits(page), "на 360 px статья с комментарием шире экрана"
    finally:
        context.close()


def test_k12_edit_pages_form_with_preview_and_history_and_compare_of_versions_with_wide_table_and_long_code_scroll_inside_block_at_360px(
        browser, browser_context_args, admin_page, employee):
    """Критерий «страницы среза на 360 px»: новая статья, форма правки с предпросмотром, история, сравнение двух версий
    и просмотр версии с широкой таблицей и длинным кодом; страница не раздвигается, таблица и код прокручиваются
    внутри блока (NFR-406)."""
    rubric, _rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page0 = author.page
    article_id = create_draft(page0, title=unique_title(), text=_wide_text(), rubric=rubric)
    # вторая версия: правка таблицы и кода
    open_edit(page0, article_id)
    article_form(page0).locator("textarea[name=text]").fill(_wide_text_changed())
    press_save(page0)
    page0.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    assert history_versions(page0, article_id) == [2, 1], "для проверки нужны две версии: 2 и 1"
    context = helpers_kb.narrow_context(browser, browser_context_args, page0)
    try:
        page = context.new_page()
        # новая статья: форма со всеми полями и панелью
        _fits(page, "/kb/new/", '[data-kb-page="new"]', "новая статья")
        expect(page.locator("[data-kb-toolbar]")).to_be_visible()
        # правка с предпросмотром: таблица и код — внутри блоков
        _fits(page, f"/kb/{article_id}/edit/", '[data-kb-page="edit"]', "правка")
        open_preview(page)
        _assert_scroll_blocks(page, page.locator("[data-kb-panel=preview] [data-kb-preview]"), "предпросмотр")
        assert helpers_kb.page_fits(page), "на 360 px страница с предпросмотром шире экрана"
        open_text_tab(page)
        assert helpers_kb.page_fits(page), "на 360 px страница с полем текста шире экрана"
        # история с двумя версиями
        _fits(page, f"/kb/{article_id}/history/", '[data-kb-page="history"]', "история")
        expect(page.locator("tr[data-version]")).to_have_count(2)
        # сравнение версий 1 и 2: разница с длинными строками
        _fits(page, f"/kb/{article_id}/compare/?v=1&v=2", '[data-kb-page="compare"]', "сравнение")
        expect(page.locator("[data-kb-diff]")).to_be_visible()
        expect(page.locator("[data-kb-diff] div.kb-diff-add").first).to_be_visible()
        assert helpers_kb.page_fits(page), "на 360 px сравнение шире экрана"
        # просмотр версии: готовый вид, таблица и код — внутри блоков
        _fits(page, f"/kb/{article_id}/versions/1/", '[data-kb-page="version"]', "просмотр версии")
        _assert_scroll_blocks(page, page.locator('[data-field="body"]'), "версия")
    finally:
        context.close()


def test_k12_manage_pages_trash_rubric_management_and_notifications_have_no_horizontal_scroll_at_360px(
        browser, browser_context_args, admin_page, employee):
    """Критерий «страницы среза на 360 px»: корзина со статьёй, статья в корзине, управление рубриками с вложенными
    рубриками, срок корзины, главная управляющего, «Уведомления» и «Мои уведомления» — ширина страниц (NFR-406)."""
    base = "Длинное название рубрики для проверки узкого экрана"
    a_name, _a_id = _rubric(admin_page, name=f"{base} {unique_word('a')}")
    b_name, _b_id = _rubric(admin_page, parent_name=a_name, name=f"{base} {unique_word('b')}")
    c_name, _c_id = _rubric(admin_page, parent_name=b_name, name=f"{base} {unique_word('c')}")
    author = helpers_kb.make_editor(employee)
    trashed = _published(author.page, c_name, text="Статья для корзины.")
    create_draft(author.page, title=unique_title(), text="Черновик автора.", rubric=c_name)
    context = helpers_kb.narrow_context(browser, browser_context_args, admin_page)
    try:
        page = context.new_page()
        # управляющий переносит статью в корзину (подтверждение — окно браузера)
        open_article(page, trashed)
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator('form[data-form="kb-trash"] button').first.click()
        expect(page.locator(f'article[data-article-id="{trashed}"][data-article-state="trash"]')).to_be_visible()
        assert helpers_kb.page_fits(page), "на 360 px статья в корзине шире экрана"
        # корзина
        _fits(page, "/kb/trash/", '[data-kb-page="trash"]', "корзина")
        expect(page.locator(f'[data-kb-trash-list] tr[data-article-id="{trashed}"]')).to_be_visible()
        # управление рубриками: три уровня с длинными названиями, формы в строках
        _fits(page, "/kb/rubrics/", '[data-kb-page="rubrics"]', "управление рубриками")
        expect(page.locator("[data-kb-rubrics] li[data-rubric-id][data-depth='3']").first).to_be_visible()
        # срок корзины
        _fits(page, "/kb/settings/", '[data-kb-page="settings"]', "срок корзины")
        # главная управляющего: «Черновики»
        _fits(page, "/kb/", '[data-kb-page="home"]', "главная управляющего")
        expect(page.locator("[data-kb-all-drafts]")).to_be_visible()
        # «Уведомления» и «Мои уведомления»: ширина страниц
        _fits(page, "/notifications/", "[data-notify-list]", "уведомления")
        _fits(page, "/me/notifications/", "[data-notify-prefs]", "мои уведомления")
    finally:
        context.close()


def test_k12_search_field_and_results_page_have_no_horizontal_scroll_at_360px(
        browser, browser_context_args, admin_page, employee):
    """Критерий «строка поиска и страница результатов на 360 px»: поле в шапке, всплывающая выдача, страница результатов
    со статьёй и сотрудниками, подсказка короткого запроса и «Ничего не найдено» (NFR-406)."""
    rubric, _rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    word = unique_word("srch")
    _published(author.page, rubric, title=_title_of_word(word), text="Статья для поиска.")
    context = helpers_kb.narrow_context(browser, browser_context_args, admin_page)
    try:
        page = context.new_page()
        # поле в шапке и всплывающая выдача
        page.goto("/kb/")
        field = page.locator('[data-search-bar] input[name="q"]')
        expect(field).to_be_visible()
        assert helpers_kb.page_fits(page), "на 360 px страница со строкой поиска шире экрана"
        field.fill(word)
        expect(page.locator('[data-search-popup] section[data-search-group="articles"] li[data-search-row]')
               .first).to_be_visible()
        assert helpers_kb.page_fits(page), "на 360 px страница со всплывающей выдачей шире экрана"
        # страница результатов: статья и сотрудники (у администратора группа «Сотрудники» есть)
        _fits(page, "/search/?" + urlencode({"q": word}), "[data-search-page]", "результаты по статье")
        expect(page.locator('[data-search-page] section[data-search-group="articles"] li[data-search-row]')
               .first).to_be_visible()
        expect(page.locator("[data-search-count-value]").first).to_be_visible()
        assert helpers_kb.page_fits(page), "на 360 px результаты с числом группы шире экрана"
        _fits(page, "/search/?" + urlencode({"q": "Иванов"}), "[data-search-page]", "результаты по сотрудникам")
        expect(page.locator('[data-search-page] section[data-search-group="staff"] li[data-search-row]')
               .first).to_be_visible()
        assert helpers_kb.page_fits(page), "на 360 px результаты по сотрудникам шире экрана"
        # подсказка короткого запроса и пустая выдача
        _fits(page, "/search/?" + urlencode({"q": "а"}), "[data-search-page]", "короткий запрос")
        expect(page.locator('[data-search-hint="short"]')).to_be_visible()
        _fits(page, "/search/?" + urlencode({"q": unique_word("none")}), "[data-search-page]", "ничего не найдено")
        expect(page.locator('[data-empty-state="search"]')).to_be_visible()
    finally:
        context.close()


# --- Безопасность содержимого (FR-402, FR-425, NFR-405) -----------------------------------------------------


def test_k12_article_with_xss_probes_executes_nothing_and_makes_no_requests_to_foreign_addresses(
        admin_page, employee, portal_url):
    """Критерий «0 исполняемых скриптов и 0 внешних картинок в показанных статьях»: статья с пробами разметки — в
    «Предпросмотре», в черновике, в опубликованной статье у читателя — скрипты не выполняются, окон нет, разметка
    выведена текстом, внешних картинок и запросов на чужие адреса нет (FR-402, NFR-405)."""
    rubric, _rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    page = author.page
    seen_author = _watch(page, portal_url)
    seen_reader = _watch(reader.page, portal_url)
    text = "\n\n".join(ARTICLE_PROBES) + "\n\nконец проб\n"

    def check(current, seen, container, label):
        # разметка проб выведена текстом, не тегами
        expect(container).to_contain_text("<script>window.__kb_ran = 1</script>")
        expect(container).to_contain_text("//evil.example/x")
        expect(container).to_contain_text("конец проб")
        _assert_safe_markup(container, label)
        # внешняя картинка заменена заглушкой, картинок в тексте нет
        assert container.locator("img").count() == 0, f"{label}: в тексте есть картинка"
        expect(container.locator("span.kb-noimg").filter(has_text="[вложение недоступно: h]")).to_have_count(1)
        # ссылка портала и внешняя ссылка остаются ссылками; опасных ссылок нет (проверено выше по каждой)
        expect(container.locator('a[href="/search/"]')).to_have_count(1)
        expect(container.locator('a[href^="https://example.ru"]')).to_have_count(1)
        assert container.locator('a[href*="javascript" i]').count() == 0, f"{label}: осталась ссылка javascript:"
        _assert_nothing_ran(current, seen, label)

    open_new_article(page)
    helpers_kb.fill_article_form(page, title=unique_title(), text=text, rubric=rubric)
    # в «Предпросмотре»
    open_preview(page)
    check(page, seen_author, page.locator("[data-kb-panel=preview] [data-kb-preview]"), "предпросмотр")
    # в сохранённом черновике
    open_text_tab(page)
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    article_id = helpers_kb.article_id_from_url(page.url)
    open_article(page, article_id)
    check(page, seen_author, page.locator('[data-field="body"]'), "черновик")
    # в опубликованной статье у читателя
    publish_from_article_page(page, article_id)
    response = reader.page.goto(f"/kb/{article_id}/")
    expect(reader.page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()
    _assert_csp(response, "страница статьи")
    check(reader.page, seen_reader, reader.page.locator('[data-field="body"]'), "опубликованная статья")
    reader.page.reload()
    expect(reader.page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()
    check(reader.page, seen_reader, reader.page.locator('[data-field="body"]'), "статья после перезагрузки")


def test_k12_comment_with_xss_probes_executes_nothing_and_loads_no_external_images(
        admin_page, employee, portal_url):
    """Критерий «0 исполняемых скриптов и 0 внешних картинок в комментариях»: комментарий с разметкой, скриптом,
    картинкой и ссылками — сразу после отправки и после перезагрузки, у автора комментария и у автора статьи: разметки нет,
    всё текстом, переносы строк сохранены, внешних картинок и запросов на чужие адреса нет (FR-425, NFR-405)."""
    rubric, _rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    commenter = helpers_kb.make_reader(employee)
    article_id = _published(author.page, rubric, text="Статья для комментария.")
    seen_commenter = _watch(commenter.page, portal_url)
    seen_author = _watch(author.page, portal_url)
    word = unique_word("cmt")
    text = (f"<b>{word}</b> <script>window.__kb_ran = 1</script> "
            '<img src="http://evil.example/c.png" onerror="window.__kb_ran = 2">\n'
            "[x](javascript:window.__kb_ran=3) ![y](http://evil.example/d.png) http://evil.example/auto "
            "<http://evil.example/auto2>\nпоследняя строка")

    def check(page, seen, label):
        row = page.locator("[data-kb-comment-list] li[data-comment-id]").filter(has_text=word)
        expect(row).to_have_count(1)
        body = row.locator('[data-field="text"]')
        # разметка — текстом
        expect(body).to_contain_text(f"<b>{word}</b>")
        expect(body).to_contain_text("<script>window.__kb_ran = 1</script>")
        expect(body).to_contain_text("[x](javascript:window.__kb_ran=3)")
        expect(body).to_contain_text("http://evil.example/auto")
        expect(body).to_contain_text("последняя строка")
        # внутри текста только переносы строк: ни ссылок, ни картинок, ни тегов разметки
        tags = body.evaluate("el => Array.from(el.querySelectorAll('*')).map(e => e.tagName)")
        assert set(tags) <= {"BR"}, f"{label}: в тексте комментария есть теги {sorted(set(tags))}"
        assert "BR" in tags, f"{label}: переносы строк не сохранены"
        # во всём блоке комментариев нет чужих картинок и опасных атрибутов
        comments = page.locator("section#comments[data-kb-comments]")
        foreign_imgs = comments.evaluate(
            "el => Array.from(el.querySelectorAll('img')).filter("
            "i => new URL(i.getAttribute('src') || '', location.href).origin !== location.origin).map(i => i.src)")
        assert not foreign_imgs, f"{label}: внешние картинки в комментариях: {foreign_imgs}"
        assert comments.evaluate("el => el.querySelectorAll('[onerror],[onclick],[onload],script,iframe').length") == 0
        _assert_nothing_ran(page, seen, label)

    # комментарий сразу после отправки (фрагмент HTMX)
    page = commenter.page
    open_article(page, article_id)
    form = page.locator('form[data-form="kb-comment"]')
    form.locator("textarea[name=text]").fill(text)
    form.locator('button[data-action="kb-comment-add"]').click()
    expect(page.locator("[data-kb-comment-list] li[data-comment-id]").filter(has_text=word)).to_have_count(1)
    check(page, seen_commenter, "после отправки")
    # после перезагрузки страницы
    page.reload()
    expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()
    check(page, seen_commenter, "после перезагрузки")
    # у автора статьи
    open_article(author.page, article_id)
    check(author.page, seen_author, "у автора статьи")


# --- Одиночные замеры времени (решение 38 задач; NFR-401, NFR-402, NFR-403) ---------------------------------


def test_k12_preview_of_ordinary_200000_chars_text_is_shown_within_one_second(admin_page, employee):
    """Критерий «предпросмотр текста до 200 000 знаков не дольше 1 с»: обычный текст ровно из 200 000 знаков; время от
    отправки запроса предпросмотра до получения ответа (`page.expect_response`, раздел 17 п. 59), лучшее из трёх замеров
    (NFR-403); появление метки в конце текста ждётся обычным ожиданием без отдельного предела."""
    author = helpers_kb.make_editor(employee)
    page = author.page
    text = _ordinary_text()
    assert len(text) == helpers_kb.TEXT_LIMIT

    def measure() -> float:
        # свежая форма на каждый замер: прежний предпросмотр не должен подменить новый
        open_new_article(page)
        article_form(page).locator("textarea[name=text]").fill(text)
        started = time.perf_counter()
        with page.expect_response(lambda r: "/kb/preview/" in r.url, timeout=20_000) as info:
            page.locator('button[data-kb-tab="preview"]').click()
        assert info.value.status == 200, f"предпросмотр ответил {info.value.status}"
        info.value.body()   # ждёт тело ответа целиком
        elapsed = time.perf_counter() - started
        # метка в конце текста: обычное ожидание (раздел 17 п. 59), предел на неё не накладывается
        page.wait_for_function(
            "m => { const e = document.querySelector('[data-kb-panel=preview] [data-kb-preview]'); "
            "return !!e && e.textContent.includes(m); }", arg=PREVIEW_MARK, polling="raf", timeout=20_000)
        return elapsed

    best = _best(measure)
    # показан именно предпросмотр текста, а не отказ: заголовок первого раздела и таблица на месте
    expect(page.locator("[data-kb-panel=preview] [data-kb-preview] h2").first).to_contain_text("Раздел 0")
    expect(page.locator("[data-kb-panel=preview] [data-kb-preview] table").first).to_be_visible()
    assert best <= PREVIEW_LIMIT, f"предпросмотр 200 000 знаков: лучшее из {BEST_OF} замеров {best:.2f} с, предел {PREVIEW_LIMIT} с"


def test_k12_popup_and_results_page_appear_within_one_second_on_stand_data(admin_page, employee):
    """Критерий «всплывающая выдача и страница результатов — не дольше 1 с»: на обычных данных стенда запрос по редкому слову
    и по частому слову; время от запроса окна (или от перехода на страницу) до показа строки статьи, лучшее из
    трёх замеров (NFR-401)."""
    rubric, _rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    word = unique_word("fast")
    _published(author.page, rubric, title=_title_of_word(word), text="Статья для замера поиска.")
    page = reader.page
    # (запрос, метка в строке статьи): пустая метка — годится любая строка группы «Статьи»
    queries = ((word, word), ("VPN", ""))
    row_js = ("m => Array.from(document.querySelectorAll('%s section[data-search-group=\"articles\"] "
              "li[data-search-row]')).some(li => li.textContent.includes(m))")

    def popup_time(q, mark) -> float:
        page.goto("/kb/")
        field = page.locator('[data-search-bar] input[name="q"]')
        expect(field).to_be_visible()
        stamps: list = []

        def on_request(request):
            if "/search/popup/" in request.url and quote(q) in request.url:
                stamps.append(time.perf_counter())

        page.on("request", on_request)
        try:
            with page.expect_request(lambda r: "/search/popup/" in r.url and quote(q) in r.url, timeout=10_000):
                field.fill(q)
            page.wait_for_function(row_js % "[data-search-popup]", arg=mark, polling="raf", timeout=15_000)
            done = time.perf_counter()
        finally:
            page.remove_listener("request", on_request)
        return done - stamps[0]

    def results_time(q, mark) -> float:
        started = time.perf_counter()
        page.goto("/search/?" + urlencode({"q": q}))
        page.wait_for_function(row_js % "[data-search-page]", arg=mark, polling="raf", timeout=15_000)
        return time.perf_counter() - started

    for q, mark in queries:
        popup = _best(lambda: popup_time(q, mark))
        assert popup <= SEARCH_LIMIT, f"всплывающая выдача «{q}»: лучшее из {BEST_OF} замеров {popup:.2f} с, предел {SEARCH_LIMIT} с"
        results = _best(lambda: results_time(q, mark))
        assert results <= SEARCH_LIMIT, f"страница результатов «{q}»: лучшее из {BEST_OF} замеров {results:.2f} с, предел {SEARCH_LIMIT} с"


def test_k12_kb_pages_respond_within_500ms_for_single_user_on_stand(admin_page, employee):
    """Критерий «страницы базы знаний и страницы срезов 001–004 отвечают не дольше 500 мс»: для одного пользователя на
    данных стенда — главная, рубрика, статья, история, сравнение, корзина, заявки, сотрудники, уведомления; комментарий
    появляется не дольше чем за 500 мс; лучшее из трёх замеров (NFR-402)."""
    rubric, rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    article_id = _published(author.page, rubric, text=_wide_text())
    open_edit(author.page, article_id)
    article_form(author.page).locator("textarea[name=text]").fill(_wide_text_changed())
    press_save(author.page)
    author.page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    trashed = _published(author.page, rubric, text="Статья для корзины.")
    page = admin_page
    open_article(page, trashed)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('form[data-form="kb-trash"] button').first.click()
    expect(page.locator(f'article[data-article-id="{trashed}"][data-article-state="trash"]')).to_be_visible()
    pages = (
        ("/kb/", "главная"),
        (f"/kb/rubrics/{rubric_id}/", "рубрика"),
        (f"/kb/{article_id}/", "статья"),
        (f"/kb/{article_id}/history/", "история"),
        (f"/kb/{article_id}/compare/?v=1&v=2", "сравнение"),
        ("/kb/trash/", "корзина"),
        ("/tickets/", "заявки (срез 003)"),
        ("/staff/", "сотрудники (срез 002)"),
        ("/notifications/", "уведомления (срез 004)"),
    )

    def response_time(url) -> float:
        response = page.goto(url)
        assert response is not None and response.status == 200, f"{url}: ответ {response and response.status}"
        # время ответа сервера на документ: от начала навигации до конца тела ответа
        return page.evaluate(
            "() => { const n = performance.getEntriesByType('navigation')[0]; return (n.responseEnd - n.startTime) / 1000; }")

    for url, label in pages:
        best = _best(lambda: response_time(url))
        assert best <= PAGE_LIMIT, f"{label} ({url}): лучшее из {BEST_OF} замеров {best:.2f} с, предел {PAGE_LIMIT} с"
    # комментарий: от нажатия «Отправить» до новой строки под статьёй
    comment_page = reader.page
    open_article(comment_page, article_id)
    form = comment_page.locator('form[data-form="kb-comment"]')

    def comment_time() -> float:
        word = unique_word("c")
        form.locator("textarea[name=text]").fill(f"Комментарий для замера {word}")
        started = time.perf_counter()
        form.locator('button[data-action="kb-comment-add"]').click()
        comment_page.wait_for_function(
            "w => Array.from(document.querySelectorAll('[data-kb-comment-list] li[data-comment-id]'))"
            ".some(li => li.textContent.includes(w))", arg=word, polling="raf", timeout=15_000)
        return time.perf_counter() - started

    best = _best(comment_time)
    assert best <= PAGE_LIMIT, f"комментарий: лучшее из {BEST_OF} замеров {best:.2f} с, предел {PAGE_LIMIT} с"


# --- Статья за пять минут (FR-401, FR-403, FR-408) ----------------------------------------------------------


def test_k12_author_writes_and_publishes_article_with_buttons_and_preview_within_five_minutes(
        admin_page, employee):
    """Критерий «автор пишет и публикует статью с кнопками и предпросмотром не дольше чем за 5 минут»: от кнопки «Новая
    статья» до публикации — заголовок, рубрика, теги, текст кнопками панели, «Предпросмотр», «Сохранить черновик»,
    «Опубликовать»; другой сотрудник видит статью. Замер в браузере — дополнение к ручному проходу T-5308
    (решение 38 задач) (FR-401, FR-403, FR-408)."""
    rubric, _rubric_id = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    page = author.page
    title = unique_title()
    tag = unique_word("tag")
    started = time.monotonic()
    # кнопка «Новая статья» на главной
    page.goto("/kb/")
    page.locator('a[data-action="kb-new-article"]').first.click()   # на пустой базе их две (11.2)
    page.wait_for_url(re.compile(r"/kb/new/$"))
    helpers_kb.fill_article_form(page, title=title, rubric=rubric, tags=f"{tag}, инструкция")
    area = article_form(page).locator("textarea[name=text]")
    # текст — кнопками панели: каждая строка выделяется и оформляется своей кнопкой
    steps = (("Подключение к корпоративной сети", "heading"), ("первый пункт списка", "list"),
             ("первый шаг", "olist"), ("важно", "bold"), ("заметка", "italic"), ("vpn connect corp", "code"),
             ("портал", "link"))
    for line, button in steps:
        existing = area.input_value()
        area.fill(existing + ("\n\n" if existing else "") + line)
        area.evaluate("(el, n) => { el.focus(); el.setSelectionRange(el.value.length - n, el.value.length); }",
                      len(line))
        page.locator(f'[data-kb-toolbar] button[data-md="{button}"]').click()
    value = area.input_value()
    for expected in ("# Подключение к корпоративной сети", "- первый пункт списка", "1. первый шаг", "**важно**",
                     "*заметка*", "`vpn connect corp`", "[портал](https://)"):
        assert expected in value, f"кнопками панели не получено «{expected}»"
    area.fill(value.replace("[портал](https://)", "[портал](https://example.ru/)") + "\n\n")
    area.evaluate("el => { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }")
    page.locator('[data-kb-toolbar] button[data-md="table"]').click()
    assert "---" in area.input_value(), "кнопка «таблица» не вставила шаблон"
    # «Предпросмотр»: те же оформления, что у опубликованной статьи
    open_preview(page)
    preview = page.locator("[data-kb-panel=preview] [data-kb-preview]")
    expect(preview.locator("h1")).to_contain_text("Подключение к корпоративной сети")
    expect(preview.locator("strong")).to_contain_text("важно")
    expect(preview.locator("em")).to_contain_text("заметка")
    expect(preview.locator("code").first).to_be_visible()
    expect(preview.locator("ul li")).to_contain_text("первый пункт списка")
    expect(preview.locator("ol li")).to_contain_text("первый шаг")
    expect(preview.locator("table")).to_have_count(1)
    # возврат на «Текст»: введённое цело; «Сохранить черновик»
    open_text_tab(page)
    assert "# Подключение к корпоративной сети" in area.input_value(), "после предпросмотра текст изменился"
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    article_id = helpers_kb.article_id_from_url(page.url)
    # «Опубликовать»
    press_publish_in_form(page)
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()
    elapsed = time.monotonic() - started
    assert elapsed <= FIVE_MINUTES, f"статья за {elapsed:.0f} с, предел {FIVE_MINUTES:.0f} с"
    # статью видят другие: «Новые и изменённые» и сама статья с оформлением и тегом
    assert article_id in home_ids(reader.page), "опубликованной статьи нет в «Новые и изменённые» у читателя"
    open_article(reader.page, article_id)
    expect(reader.page.locator('article h1[data-field="title"]')).to_have_text(title)
    expect(reader.page.locator(f'a[data-tag="{tag}"]')).to_have_count(1)
    expect(reader.page.locator('[data-field="body"] h1')).to_contain_text("Подключение к корпоративной сети")
