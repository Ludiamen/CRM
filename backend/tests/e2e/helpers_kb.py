"""Помощники приёмки среза 005 «База знаний» (T-5140; ими пользуются T-5141…T-5151).

Что здесь есть (CONTRACT-005.md: разделы 10, 11, 12, 13, 16, 17):
- имена и роли: `unique_word`, `unique_title`, `make_editor`, `make_reader`, `make_manager`;
- команды стенда `e2e_kb_trash_shift`, `e2e_kb_purge` (раздел 13): `trash_shift`, `purge`, `parse_kb_line`;
- рубрики и статьи через интерфейс: `create_rubric`, `rubric_id_by_name`, `open_new_article`, `article_form`,
  `fill_article_form`, `choose_rubric`, `clear_rubric`, `press_save`, `press_publish_in_form`, `create_draft`,
  `publish_from_article_page`, `article_id_from_url`, `open_article`, `open_edit`, `open_history`,
  `history_versions`, `open_preview`, `open_text_tab`;
- списки: `home_ids`, `rubric_page_ids`, `search_hrefs`, `search_finds`;
- комментарии и вложения через интерфейс: `add_comment`, `attach_file`, `try_attach_file`, `file_row`,
  `wait_file_clean`, `eicar_bytes`;
- Telegram через `fakebots`, письма Mailpit: `bots`, `bind_telegram`, `wait_telegram`, `kb_item_mail`;
- замер паузы ввода строки поиска: `search_pause_ms`;
- ширина 360 px: `narrow_context`, `page_fits`, `scrolls_inside`.

Как заводить людей (не придумывать третий путь): читатель без прав базы знаний — роль «Руководитель»
(`make_reader`), редактор — «Сотрудник ИТ» с `knowledge.edit` (`make_editor`), управляющий — «Администратор
портала» с `knowledge.manage` и `knowledge.edit` (`make_manager` или `admin_page` круга). Раздел 2.4 контракта.

Правила (шаблон e2e/template.md): код приложения (`apps.*`, `django`) и `tests.support*` не импортируются; локаторы —
только из контракта; ждать — `expect`, `wait_for_url`; сна нет (ожидание файла — опрос с `wait_for_timeout`);
данные круга общие, поэтому все названия уникальны. Готовое из прежних срезов не дублируется, а вызывается:
`helpers` (вход, `no_horizontal_scroll`, `make_png`, `stand_shell`), `helpers_sd._stand_command`,
`helpers_org` (`direct_get`, `direct_post`, `upload_file`, `audit_rows`, `audit_sides`, `unique_name`),
`helpers_notify` (`fakebots`, `wait_sent`, `sent_to`, `bind_channel`, `wait_item_mail`, `wait_template_mail`).
Файл правит только T-5140.
"""
import re
import secrets
import string
import time
from urllib.parse import urlencode

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd

READER_ROLE = "Руководитель"          # встроенная роль без прав базы знаний (2.4)
EDITOR_ROLE = helpers.STAFF_ROLE      # «Сотрудник ИТ»: `knowledge.edit`
MANAGER_ROLE = helpers.ADMIN_ROLE     # «Администратор портала»: `knowledge.edit` и `knowledge.manage`
SAVE_HINT = "Сохраните черновик"      # 12.1
TEXT_LIMIT = 200_000                  # знаков текста статьи (FR-401)
TITLE_LIMIT = 200                     # знаков заголовка (FR-401)
SCROLL_CLASS = "kb-scroll"            # блок прокрутки таблицы и кода (11.3)
_ARTICLE_URL = re.compile(r"/kb/(\d+)/")


# --- Имена и люди ------------------------------------------------------------------------------------------

def unique_word(prefix: str = "kb") -> str:
    """Уникальное слово из латинских букв: `<prefix>` и десять случайных строчных букв, без цифр. Годится как слово
    заголовка для поиска (цифры внутри слова поиск мог бы разобрать иначе); данные круга общие."""
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(10))


def unique_title(prefix: str = "Подключение VPN") -> str:
    """Уникальный заголовок статьи: `<prefix> <слово из unique_word>`; слово можно искать в поиске."""
    return f"{prefix} {unique_word()}"


def make_editor(employee, **kwargs):
    """Сотрудник с правом «Редактирование базы знаний»: `employee` — фикстура круга; роль «Сотрудник ИТ»."""
    return employee(role=EDITOR_ROLE, **kwargs)


def make_reader(employee, **kwargs):
    """Сотрудник без прав базы знаний (читатель): `employee` — фикстура круга; роль «Руководитель»."""
    return employee(role=READER_ROLE, **kwargs)


def make_manager(employee, **kwargs):
    """Сотрудник-управляющий (`knowledge.manage` и `knowledge.edit`): `employee` — фикстура круга; роль
    «Администратор портала». Если хватает администратора круга, берите `admin_page`."""
    return employee(role=MANAGER_ROLE, **kwargs)


# --- Команды стенда (раздел 13) ---------------------------------------------------------------------------

def parse_kb_line(line: str) -> dict:
    """Разбирает строку вывода команд стенда `имя: ключ=значение …` в словарь (числа — `int`, прочее — строкой):
    `kb_trash_shift: days=N shifted=<n>` → `{"days": N, "shifted": n}`; `kb_purge: purged=<n> skipped=<n> failed=<n>`."""
    _, _, tail = line.partition(":")
    out = {}
    for part in tail.split():
        name, _, value = part.partition("=")
        out[name] = int(value) if value.lstrip("-").isdigit() else value
    return out


def trash_shift(days: int) -> dict:
    """`e2e_kb_trash_shift --days N` (13): сдвигает `deleted_at` всех статей корзины на N суток назад (1…36500).
    Работает только на стенде (`E2E_STAND=1` у службы `standtools`). Возвращает разбор строки вывода
    `kb_trash_shift: days=N shifted=<число статей>` (`parse_kb_line`). Срок корзины после сдвига проверяет
    `purge()`, а не часы."""
    if not 1 <= int(days) <= 36500:
        raise ValueError("days должно быть целым от 1 до 36500")
    return parse_kb_line(helpers_sd._stand_command("e2e_kb_trash_shift", "--days", int(days)))


def purge() -> dict:
    """`e2e_kb_purge` (13): ночная очистка корзины сразу, как задание `purge_trash`; срок берётся из настроек базы
    знаний. Только на стенде. Возвращает разбор строки `kb_purge: purged=<n> skipped=<n> failed=<n>`; при
    непустом `failed` команда завершается с ошибкой, и помощник поднимает `AssertionError` (текст — вывод
    `_stand_command`, номера статей без текстов исключений)."""
    return parse_kb_line(helpers_sd._stand_command("e2e_kb_purge"))


# --- Рубрики -----------------------------------------------------------------------------------------------

def rubric_id_by_name(page, name: str) -> str:
    """Номер рубрики по названию на `/kb/rubrics/` (управляющий): ищет `[data-field="name"]` с точным текстом `name`
    и берёт номер у ближайшего `li[data-rubric-id]` (список плоский, раздел 17, п. 53; помощник устойчив и к
    вложенным `li`); несколько разных номеров или ни одного — `AssertionError`. Названия уникальны на круге."""
    page.goto("/kb/rubrics/")
    expect(page.locator("[data-kb-rubrics]")).to_be_visible()
    found = set()
    for cell in page.locator('[data-kb-rubrics] [data-field="name"]').all():
        if cell.inner_text().strip() == name:
            found.add(cell.evaluate("e => e.closest('li[data-rubric-id]').dataset.rubricId"))
    assert len(found) == 1, f"рубрик с названием «{name}»: {len(found)}"
    return found.pop()


def create_rubric(manager_page, name: str, *, parent_name: str | None = None) -> str:
    """Создаёт рубрику формой `form[data-form="kb-rubric-new"]` на `/kb/rubrics/` (управляющий: `admin_page`);
    `parent_name` — название родителя (нет — корневая). Ждёт возврат на `/kb/rubrics/`; возвращает номер рубрики
    (`rubric_id_by_name`)."""
    manager_page.goto("/kb/rubrics/")
    form = manager_page.locator('form[data-form="kb-rubric-new"]')
    form.locator("input[name=name]").fill(name)
    if parent_name is not None:
        _select_by_text(form.locator("select[name=parent]"), parent_name)
    form.locator("button[type=submit]").click()
    manager_page.wait_for_url(re.compile(r"/kb/rubrics/$"))
    expect(manager_page.locator("[data-kb-rubrics] [data-field=name]").filter(has_text=name).first).to_be_visible()
    return rubric_id_by_name(manager_page, name)


def _select_by_text(select, text: str) -> str:
    """Выбирает пункт `<select>`, подпись которого (без отступа) содержит `text`; возвращает его `value`.
    Подпись у дерева рубрик идёт с отступом по глубине (11.3), поэтому точное равенство не годится."""
    value = select.evaluate(
        "(el, text) => { const o = Array.from(el.options).find(o => o.text.trim().includes(text)); "
        "return o ? o.value : null; }", text)
    assert value is not None, f"в списке нет пункта «{text}»"
    select.select_option(value=value)
    return value


# --- Статьи: форма -----------------------------------------------------------------------------------------

def article_form(page):
    """Форма статьи `form[data-form="kb-article"]` (новая и правка, 11.3)."""
    return page.locator('form[data-form="kb-article"]')


def open_new_article(page):
    """Открывает `/kb/new/` и ждёт форму статьи и корень `[data-kb-page="new"]`; возвращает локатор формы."""
    page.goto("/kb/new/")
    expect(page.locator('[data-kb-page="new"]')).to_be_visible()
    expect(article_form(page)).to_be_visible()
    return article_form(page)


def choose_rubric(page, name: str) -> str:
    """В форме статьи выбирает рубрику по названию (подпись пункта содержит `name`); возвращает номер рубрики."""
    return _select_by_text(article_form(page).locator("select[name=rubric]"), name)


def clear_rubric(page) -> None:
    """Оставляет рубрику «не выбранной»: выбирает пункт с пустым значением (если пункта нет, добавляет его в
    `<select>` скриптом страницы: так браузер отправил бы форму без рубрики). Нужен для отказа `rubric_missing`."""
    article_form(page).locator("select[name=rubric]").evaluate(
        "el => { let o = Array.from(el.options).find(o => o.value === ''); "
        "if (!o) { o = document.createElement('option'); o.value = ''; o.text = ''; el.add(o, 0); } "
        "el.value = ''; el.dispatchEvent(new Event('change', {bubbles: true})); }")


def fill_article_form(page, *, title: str | None = None, text: str | None = None, rubric: str | None = None,
                      tags: str | None = None, comment: str | None = None) -> None:
    """Заполняет форму статьи: только переданные поля (`title`, `text`, `tags`, `comment`); `rubric` — название
    рубрики (`choose_rubric`)."""
    form = article_form(page)
    if title is not None:
        form.locator("input[name=title]").fill(title)
    if text is not None:
        form.locator("textarea[name=text]").fill(text)
    if rubric is not None:
        choose_rubric(page, rubric)
    if tags is not None:
        form.locator("input[name=tags]").fill(tags)
    if comment is not None:
        form.locator("input[name=comment]").fill(comment)


def press_save(page) -> None:
    """Нажимает «Сохранить» / «Сохранить черновик» (`button[data-action="kb-save"]`); ничего не ждёт: после успеха
    переход, после отказа — замена формы (ждать должен тест)."""
    article_form(page).locator('button[data-action="kb-save"]').click()


def press_publish_in_form(page) -> None:
    """Нажимает «Опубликовать» в форме правки (`button[data-action="kb-publish"]` внутри `form[data-form="kb-article"]`);
    ничего не ждёт."""
    article_form(page).locator('button[data-action="kb-publish"]').click()


def article_id_from_url(url: str) -> str:
    """Номер статьи из адреса `/kb/<id>/…`; другой адрес — `AssertionError`."""
    found = _ARTICLE_URL.search(url)
    assert found, f"в адресе нет номера статьи: {url}"
    return found.group(1)


def create_draft(page, *, title: str, text: str = "Текст статьи.", rubric: str, tags: str = "",
                 comment: str = "") -> str:
    """Новая статья через интерфейс: `/kb/new/`, поля, «Сохранить черновик»; ждёт `/kb/<id>/edit/` (первое
    сохранение ведёт в редактор, решение C-2) и форму правки; возвращает номер статьи. `rubric` — название."""
    open_new_article(page)
    fill_article_form(page, title=title, text=text, rubric=rubric, tags=tags, comment=comment)
    press_save(page)
    page.wait_for_url(re.compile(r"/kb/\d+/edit/$"))
    expect(page.locator('[data-kb-page="edit"]')).to_be_visible()
    return article_id_from_url(page.url)


def open_article(page, article_id) -> None:
    """Открывает `/kb/<id>/` и ждёт `article[data-article-id="<id>"]`."""
    page.goto(f"/kb/{article_id}/")
    expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()


def open_edit(page, article_id) -> None:
    """Открывает `/kb/<id>/edit/` и ждёт форму правки."""
    page.goto(f"/kb/{article_id}/edit/")
    expect(page.locator('[data-kb-page="edit"]')).to_be_visible()
    expect(article_form(page)).to_be_visible()


def publish_from_article_page(page, article_id) -> None:
    """Публикует черновик кнопкой страницы статьи (`form[data-form="kb-publish"]`): открывает `/kb/<id>/`, нажимает,
    ждёт `article[data-article-state="published"]`. Без предупреждения ПДн."""
    open_article(page, article_id)
    page.locator('form[data-form="kb-publish"] button[data-action="kb-publish"]').click()
    expect(page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')).to_be_visible()


def open_history(page, article_id) -> None:
    """Открывает `/kb/<id>/history/` и ждёт `[data-kb-page="history"]`."""
    page.goto(f"/kb/{article_id}/history/")
    expect(page.locator('[data-kb-page="history"]')).to_be_visible()


def history_versions(page, article_id) -> list:
    """Номера версий в истории статьи по порядку строк (`tr[data-version]`, номер вниз): список `int`."""
    open_history(page, article_id)
    return [int(row.get_attribute("data-version")) for row in page.locator("tr[data-version]").all()]


def open_preview(page) -> None:
    """Открывает вкладку «Предпросмотр» формы и ждёт содержимое `[data-kb-panel="preview"] [data-kb-preview]`."""
    page.locator('button[data-kb-tab="preview"]').click()
    expect(page.locator('[data-kb-panel="preview"] [data-kb-preview]')).to_be_visible()


def open_text_tab(page) -> None:
    """Возвращает вкладку «Текст» и ждёт видимое поле `textarea[name=text]`."""
    page.locator('button[data-kb-tab="text"]').click()
    expect(page.locator('[data-kb-panel="text"]')).to_be_visible()
    expect(article_form(page).locator("textarea[name=text]")).to_be_visible()


# --- Списки главной, рубрики, поиска -----------------------------------------------------------------------

def home_ids(page, block: str = "new-and-changed") -> list:
    """Номера статей блока главной `/kb/`: `block` — `new-and-changed` (`[data-kb-new-and-changed]`), `my-drafts`
    (`[data-kb-my-drafts]`) или `all-drafts` (`[data-kb-all-drafts]`); нет блока — пустой список. Строки —
    `li[data-article-id]`."""
    page.goto("/kb/")
    expect(page.locator('[data-kb-page="home"]')).to_be_visible()
    root = page.locator(f"[data-kb-{block}]")
    return [li.get_attribute("data-article-id") for li in root.locator("li[data-article-id]").all()]


def rubric_page_ids(page, rubric_id) -> list:
    """Номера статей первой порции страницы рубрики `/kb/rubrics/<id>/` (`[data-kb-list] li[data-article-id]`)."""
    page.goto(f"/kb/rubrics/{rubric_id}/")
    expect(page.locator('[data-kb-page="rubric"]')).to_be_visible()
    return [li.get_attribute("data-article-id") for li in page.locator("[data-kb-list] li[data-article-id]").all()]


def search_hrefs(page, q: str) -> list:
    """Адреса строк страницы результатов `/search/?q=<q>` (`[data-search-page] li[data-search-row] a[href]`, первая
    порция). Страница, а не всплывающее окно: пустое окно не даёт зацепки, которую можно ждать."""
    page.goto("/search/?" + _query(q))
    expect(page.locator("[data-search-page]")).to_be_visible()
    return [a.get_attribute("href") for a in page.locator("[data-search-page] li[data-search-row] a[href]").all()]


def search_finds(page, q: str, article_id) -> bool:
    """True, если на странице результатов по `q` есть строка с адресом статьи `/kb/<id>/`."""
    return f"/kb/{article_id}/" in search_hrefs(page, q)


def _query(q: str) -> str:
    return urlencode({"q": q})


# --- Комментарии -------------------------------------------------------------------------------------------

def add_comment(page, article_id, text: str) -> str:
    """Комментарий под опубликованной статьёй через форму `form[data-form="kb-comment"]`: ждёт новую строку
    `li[data-comment-id]` с этим текстом в `ul[data-kb-comment-list]`; возвращает номер комментария."""
    open_article(page, article_id)
    form = page.locator('form[data-form="kb-comment"]')
    form.locator("textarea[name=text]").fill(text)
    form.locator('button[data-action="kb-comment-add"]').click()
    row = page.locator("[data-kb-comment-list] li[data-comment-id]").filter(has_text=text).last
    expect(row).to_be_visible()
    return row.get_attribute("data-comment-id")


# --- Вложения ----------------------------------------------------------------------------------------------

def eicar_bytes() -> bytes:
    """Тестовая строка EICAR, собранная из частей (решение 17): ClamAV стенда отправляет такой файл в карантин."""
    parts = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$", "EICAR-STANDARD-ANTIVIRUS", "-TEST-FILE!$H+H*")
    return "".join(parts).encode("ascii")


def file_row(page, file_id):
    """Строка вложения `[data-kb-files] li[data-file-id="<id>"]` (на странице статьи и правки)."""
    return page.locator(f'[data-kb-files] li[data-file-id="{file_id}"]')


def try_attach_file(page, article_id, data: bytes, name: str, *, mime: str = "application/octet-stream") -> str:
    """Загружает файл формой `form[data-form="kb-attach"]` на `/kb/<id>/edit/` и ждёт ответ фрагмента
    `[data-kb-files]`: либо новая строка, либо `[role=alert][data-code]` над списком. Возвращает код отказа
    (`too_big`, `executable`, …) или пустую строку при успехе."""
    open_edit(page, article_id)
    before = {li.get_attribute("data-file-id") for li in page.locator("[data-kb-files] li[data-file-id]").all()}
    form = page.locator('form[data-form="kb-attach"]')
    alert = page.locator("[data-kb-files] [role=alert][data-code]")
    rows = page.locator("[data-kb-files] li[data-file-id]")
    # форма уходит сама при выборе файла (`hx-trigger="change"`, раздел 17 п. 70): ждём ответ на этот POST
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.split("?")[0].endswith(f"/kb/{article_id}/files/"),
                              timeout=30000):
        helpers_org.upload_file(form, data, name=name, mime=mime, submit=False)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if alert.count():
            return alert.first.get_attribute("data-code")
        if rows.count() > len(before):
            return ""
        page.wait_for_timeout(250)
    raise AssertionError("ответ на вложение не пришёл за 30 с")


def attach_file(page, article_id, data: bytes, name: str, *, mime: str = "application/octet-stream") -> str:
    """Вложение без отказа (`try_attach_file`); возвращает номер нового файла (`ArticleFile.pk`, решение 6 раздела
    17). Отказ — `AssertionError` с кодом."""
    code = try_attach_file(page, article_id, data, name, mime=mime)
    assert not code, f"вложение отклонено: {code}"
    row = page.locator("[data-kb-files] li[data-file-id]").filter(has_text=name).last
    expect(row).to_be_visible()
    return row.get_attribute("data-file-id")


def wait_file_clean(page, article_id, file_id, *, timeout: float = 60.0) -> str:
    """Опрос страницы правки до `timeout` с (пауза 2 с, перезагрузка): ждёт, пока `data-file-state` строки файла
    перестанет быть `pending` (NFR-404: не дольше минуты на ClamAV стенда). Возвращает `"clean"` или
    `"quarantine"`; по истечении срока — `AssertionError`. Образец — `helpers_org.wait_photo_checked`."""
    deadline = time.monotonic() + timeout
    while True:
        open_edit(page, article_id)
        row = file_row(page, file_id)
        expect(row).to_be_visible()
        state = row.get_attribute("data-file-state")
        if state in ("clean", "quarantine"):
            return state
        if time.monotonic() > deadline:
            raise AssertionError(f"проверка файла не закончилась за {timeout:.0f} с")
        page.wait_for_timeout(2000)


# --- Telegram (fakebots) и письма (Mailpit): готовое из helpers_notify -------------------------------------

def bots() -> "helpers_notify.FakeBots":
    """Клиент учебной службы `fakebots` без сброса (`helpers_notify.fakebots`): сообщения своего теста выбирать по
    своему уникальному `chat_id`."""
    return helpers_notify.fakebots()


def bind_telegram(page, fake, chat_id) -> str:
    """Привязывает Telegram сотрудника страницы кодом через `fakebots` (`helpers_notify.bind_channel`, канал
    должен быть включён администратором: `helpers_notify.channels_on`); возвращает использованный код."""
    return helpers_notify.bind_channel(page, fake, "telegram", chat_id)


def wait_telegram(fake, chat_id, *, text_has: str | None = None, count: int = 1, timeout: float = 30.0) -> list:
    """Ждёт сообщения бота Telegram в чат `chat_id` (`helpers_notify.wait_sent`), с подстрокой `text_has`;
    возвращает подходящие по порядку отправки."""
    return helpers_notify.wait_sent(fake, "telegram", count=count, timeout=timeout, text_has=text_has,
                                    chat_id=chat_id)


def kb_item_mail(mailpit, to: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое письмо об одном уведомлении (`notify.item`) на адрес `to`: полный текст Mailpit
    (`helpers_notify.wait_item_mail`). Письма базы знаний идут тем же шаблоном; срок письма сдвигает
    `helpers_notify.tick(shift=…)`."""
    return helpers_notify.wait_item_mail(mailpit, to, seen=seen, timeout=timeout)


# --- Строка поиска: пауза ввода ----------------------------------------------------------------------------

def search_pause_ms(page, text: str, *, typing_delay_ms: int = 40) -> float:
    """Время в миллисекундах от последнего введённого знака в `input[name=q]` шапки до запроса `/search/popup/`
    (контракт 11.9: пауза 300 мс; приёмка допускает 300 ± 100). Запрос ловит событие Playwright (`page.on("request")`),
    время берётся в тот же миг по `time.perf_counter`. Поле перед вводом очищается; ввод — по знаку с задержкой, чтобы
    паузы между знаками были короче срока. Возвращает число (положительное)."""
    field = page.locator('[data-search-bar] input[name="q"]')
    field.fill("")
    stamps: list = []

    def on_request(request):
        if "/search/popup/" in request.url:
            stamps.append(time.perf_counter())

    page.on("request", on_request)
    try:
        with page.expect_request(lambda r: "/search/popup/" in r.url, timeout=10_000):
            field.press_sequentially(text, delay=typing_delay_ms)
            last = time.perf_counter()
    finally:
        page.remove_listener("request", on_request)
    return (stamps[-1] - last) * 1000.0


# --- Ширина 360 px -----------------------------------------------------------------------------------------

def narrow_context(browser, browser_context_args, source_page, *, height: int = 740):
    """Новый контекст шириной 360 px с сессией страницы `source_page` (её `context.storage_state()`); закрывает
    вызывающий (`context.close()` в `finally`). Страницу открывают `context.new_page()`."""
    return browser.new_context(**browser_context_args, viewport={"width": 360, "height": height},
                               storage_state=source_page.context.storage_state())


def page_fits(page) -> bool:
    """True, если у страницы нет горизонтальной прокрутки: `document.documentElement.scrollWidth <= innerWidth`
    (так сформулировано в шаблоне приёмки среза 005; прокрутка внутри `kb-scroll` допустима)."""
    return bool(page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))


def scrolls_inside(block) -> bool:
    """True, если блок (локатор, один элемент) прокручивается внутри себя: его содержимое шире его самого
    (`scrollWidth > clientWidth`) и `overflow-x` равен `auto` или `scroll`."""
    return bool(block.evaluate(
        "el => el.scrollWidth > el.clientWidth && ['auto', 'scroll'].includes(getComputedStyle(el).overflowX)"))
