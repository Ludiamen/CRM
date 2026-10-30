"""T-7150: сценарий 11 — фильтры ленты и сквозной поиск (FR-602, FR-606, FR-635, FR-636, FR-637, NFR-606, NFR-608).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 9, 10.2, 12.2, 12.3, 12.7, 13.3, 14.4; решения 8,
23, 26, 54 задач; образцы — test_l12_search.py, test_k10_search.py):
- помощники ленты — из `helpers_feed.py` (`publish`, `add_comment`, `open_feed`, `post_ids`, `important_ids`, `age`,
  `check_360`, `pick_author`); фильтры по адресу `/?f=…&author=…&from=…&to=…` (раздел 10.2: даты `YYYY-MM-DD`), через форму —
  только там, где проверяется сама форма (`form#feed-filters`);
- каждый тест заводит своих людей и записи; слова поиска — только латинские буквы (`_word`; цифры внутри слова поиск
  разобрал бы иначе), рядом с русским словом стоит уникальное латинское слово теста (запрос из нескольких слов — «И»),
  поэтому чужие записи стенда выдачу не меняют;
- страница результатов — `/search/?q=…` (`[data-search-page]`, группа `section[data-search-group="feed"]`, строки
  `li[data-search-row]`, `[data-field="title"]`, `[data-field="subtitle"]`, число `span[data-search-count-value]`);
  первый положительный поиск после публикации — с повтором до 20 с (пересчёт вектора может идти после фиксации);
  отсутствие записи проверяется только после положительной проверки той же записи по соседнему запросу;
- «время публикации» записи состаривается командой `helpers_feed.age(дни, posts=[номер])` (всегда с `posts`: без них
  состарились бы все записи стенда), даты периода считаются от сегодняшнего дня по Москве (срок хранения по умолчанию —
  3 года, состаренное на дни не удаляется);
- правка и удаление записи и комментария — свои короткие помощники файла (в `helpers_feed.py` их нет — вопрос Opus).
"""
import re
import secrets
import string
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed, helpers_org
from tests.e2e.helpers_feed import POST_ALL

MOSCOW = ZoneInfo("Europe/Moscow")
FIND_TIMEOUT = 20.0
NO_POSTS = "По фильтру записей нет"   # CONTRACT-007, 12.1, 13.3
DATE_IN_TITLE = r"\d{2}\.\d{2}\.\d{4}"


# --- Общие помощники файла ---------------------------------------------------------------------------------------

def _word(prefix: str = "w") -> str:
    """Уникальное слово из латинских букв (цифры внутри слова поиск разобрал бы иначе)."""
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(9))


def _uid() -> str:
    return secrets.token_hex(3)


def _writers(admin_page, employee, count: int, prefix: str = "Писарев") -> list:
    """`count` сотрудников с правом «Писать всем» (одна роль на всех)."""
    role = helpers_feed.make_role(admin_page, [POST_ALL])
    return [employee(role=role, full_name=f"{prefix}{_uid()} Иван Иванович") for _ in range(count)]


def _reader(employee, surname: str = "Читатель"):
    return employee(full_name=f"{surname}{_uid()} Пётр Петрович")


def _open(new_context, account):
    return helpers_feed.open_feed(new_context(), account)


def _home(page, **params):
    """Главная с фильтром по адресу; ждёт корень тела (без ожидания соединения)."""
    page.goto("/" + (("?" + urlencode(params)) if params else ""))
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()


def _shown(page) -> list:
    """Номера записей, показанных на странице: основная лента и блок важных."""
    return helpers_feed.post_ids(page) + helpers_feed.important_ids(page)


def _today():
    return datetime.now(MOSCOW).date()


def _results(page, q: str) -> None:
    page.goto("/search/?" + urlencode({"q": q}))
    expect(page.locator("[data-search-page]")).to_be_visible()


def _feed_group(page):
    return page.locator('[data-search-page] section[data-search-group="feed"]')


def _hrefs(page, q: str) -> list:
    """Адреса строк группы «Лента» по запросу `q` (пусто, если группы нет)."""
    _results(page, q)
    return _feed_group(page).locator("li[data-search-row]").evaluate_all(
        "els => els.map(li => li.querySelector('a[href]').getAttribute('href'))")


def _wait_found(page, q: str, href: str, timeout: float = FIND_TIMEOUT) -> list:
    """Повторяет поиск, пока в группе «Лента» не появится строка с адресом `href` (вектор мог ещё считаться)."""
    deadline = time.monotonic() + timeout
    while True:
        hrefs = _hrefs(page, q)
        if href in hrefs:
            return hrefs
        if time.monotonic() > deadline:
            raise AssertionError(f"запрос «{q}»: строки {href} нет в группе «Лента» за {timeout:.0f} с: {hrefs}")
        page.wait_for_timeout(1000)


def _row(page, href: str):
    """Строка группы «Лента» с адресом `href` (после `_results`)."""
    return _feed_group(page).locator("li[data-search-row]").filter(has=page.locator(f'a[href="{href}"]')).first


def _post_href(post_id) -> str:
    return f"/feed/{post_id}/"


def _comment_href(post_id, comment_id) -> str:
    return f"/feed/{post_id}/#c{comment_id}"


def _edit_post(page, post_id, **fields) -> None:
    """Правка записи формой `/feed/<id>/edit/` (поле `text`); ждёт карточку. Помощника правки в `helpers_feed.py` нет."""
    page.goto(f"/feed/{post_id}/edit/")
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="edit"] form:has(textarea[name="text"])').first
    for name, value in fields.items():
        form.locator(f'[name="{name}"]').fill(value)
    with page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="card"]')).to_be_visible()


def _delete_post(page, post_id) -> None:
    """Удаление записи с карточки: «Удалить» и подтверждение `dialog[data-feed-confirm]`."""
    page.goto(f"/feed/{post_id}/")
    post = page.locator(f"#feed-post-{post_id}")
    post.locator('button[data-action="post-delete"]').first.click()
    dialog = page.locator("dialog[data-feed-confirm][open]")
    expect(dialog).to_be_visible()
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/delete/" in r.url):
        dialog.locator("button[type=submit]").click()
    expect(post).to_have_count(0)


def _edit_comment(page, comment_id, text: str) -> None:
    """Правка комментария формой `/feed/comments/<id>/edit/` (раздел 10.2, 12.1: страница `comment-edit`)."""
    page.goto(f"/feed/comments/{comment_id}/edit/")
    expect(page.locator('[data-feed-page="comment-edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="comment-edit"] form:has(textarea[name="text"])').first
    form.locator('textarea[name="text"]').fill(text)
    with page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()


def _delete_comment(page, comment_id) -> None:
    """Удаление комментария запросом той же кнопки (`POST /feed/comments/<id>/delete/`, обычный POST — 302 на карточку)."""
    response = helpers_org.direct_post(page, f"/feed/comments/{comment_id}/delete/")
    assert response.status == 302, f"удаление комментария: ответ {response.status}"


def _dismiss(admin_page, user_id) -> None:
    """Увольняет из карточки: диалог и подтверждение; ждёт отметку `[data-dismissed-badge]`."""
    admin_page.goto(f"/staff/{user_id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = admin_page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


# --- Тесты: фильтры ----------------------------------------------------------------------------------------------

def test_f11_filters_important_events_mine_and_mentions_me_show_only_such_posts(
        admin_page, employee, new_context):
    """Сценарий 11, п. 1: лента с важными записями, событиями, своими записями и упоминаниями — «Важные», «События», «Мои»,
    «Упоминают меня» оставляют только такие записи (FR-635)."""
    mark = _uid()
    author, me = _writers(admin_page, employee, 2)
    start = (datetime.now(MOSCOW) + timedelta(days=3)).replace(tzinfo=None, second=0, microsecond=0)
    page = _open(new_context, author)
    plain = helpers_feed.publish(page, f"Обычная {mark}")
    important = helpers_feed.publish(page, f"Важная {mark}", kind="important", term="week")
    event = helpers_feed.publish(page, "", kind="event", event={
        "title": f"Событие {mark}", "place": f"Зал {mark}", "start": start, "end": start + timedelta(hours=1)})
    mention = helpers_feed.publish(page, f"Упоминание {mark}", mentions=[me.full_name])
    mine = helpers_feed.publish(_open(new_context, me), f"Моя {mark}")
    mine_page = _open(new_context, me)
    mine_all = {plain, important, event, mention, mine}

    def check(filter_value: str, expected: set) -> None:
        _home(mine_page, f=filter_value)
        shown = set(_shown(mine_page))
        assert expected <= shown, f"f={filter_value}: нет записей {expected - shown}"
        assert not ((mine_all - expected) & shown), f"f={filter_value}: лишние записи {(mine_all - expected) & shown}"

    # п. 1: «Важные» — важная запись; все показанные записи важные (или были важными)
    check("important", {important})
    # п. 1: «События» — событие; у всех показанных есть блок события
    check("events", {event})
    _home(mine_page, f="events")
    for post_id in helpers_feed.post_ids(mine_page):
        expect(mine_page.locator(f"#feed-post-{post_id}-event")).to_have_count(1)
    # п. 1: «Мои» — только записи самого сотрудника
    check("mine", {mine})
    _home(mine_page, f="mine")
    for node in mine_page.locator("#feed-list [data-post-id] [data-feed-author]").all():
        assert me.full_name in node.inner_text(), "в «Моих» есть чужая запись"
    # п. 1: «Упоминают меня» — запись с упоминанием
    check("mentions", {mention})


def test_f11_mentions_me_filter_shows_post_where_employee_is_mentioned_only_in_comment(
        admin_page, employee, new_context):
    """Сценарий 11, п. 1 (комментарий): «Упоминают меня» показывает запись, где сотрудник упомянут только в комментарии
    (FR-635)."""
    mark = _uid()
    author, other = _writers(admin_page, employee, 2)
    me = _reader(employee)
    page = _open(new_context, author)
    commented = helpers_feed.publish(page, f"Запись без упоминаний {mark}")
    plain = helpers_feed.publish(page, f"Запись совсем без упоминаний {mark}")
    card = helpers_feed.open_card(new_context(), other, commented)
    helpers_feed.add_comment(card, commented, f"Прошу посмотреть {mark}", mentions=[me.full_name])
    mine_page = _open(new_context, me)
    _home(mine_page, f="mentions")
    shown = _shown(mine_page)
    assert commented in shown, "запись с упоминанием в комментарии не показана"
    assert plain not in shown, "показана запись без упоминаний"


def test_f11_author_filter_with_period_shows_that_authors_posts_published_in_period_inclusive(
        admin_page, employee, new_context):
    """Сценарий 11, п. 2: фильтр «Автор» с периодом — записи этого автора, опубликованные в период, границы включены
    (FR-635)."""
    mark = _uid()
    author, other = _writers(admin_page, employee, 2)
    viewer = _reader(employee)
    page_a, page_o = _open(new_context, author), _open(new_context, other)
    day_from, day_to = 12, 6   # период: от «сегодня минус 12» до «сегодня минус 6» включительно
    posts = {
        "в первый день": (helpers_feed.publish(page_a, f"Первый день {mark}"), day_from),
        "в последний день": (helpers_feed.publish(page_a, f"Последний день {mark}"), day_to),
        "внутри": (helpers_feed.publish(page_a, f"Внутри {mark}"), 9),
        "до периода": (helpers_feed.publish(page_a, f"До периода {mark}"), day_from + 1),
        "после периода": (helpers_feed.publish(page_a, f"После периода {mark}"), day_to - 1),
    }
    foreign = helpers_feed.publish(page_o, f"Чужая внутри {mark}")
    for post_id, days in [*posts.values(), (foreign, 9)]:
        helpers_feed.age(days, posts=[post_id])
    start, end = _today() - timedelta(days=day_from), _today() - timedelta(days=day_to)
    viewer_page = _open(new_context, viewer)
    # дано: фильтр «Автор» и период с границами включительно
    _home(viewer_page, author=author.id, **{"from": start.isoformat(), "to": end.isoformat()})
    shown = set(_shown(viewer_page))
    inside = {posts["в первый день"][0], posts["в последний день"][0], posts["внутри"][0]}
    assert inside <= shown, f"нет записей периода: {inside - shown}"
    outside = {posts["до периода"][0], posts["после периода"][0], foreign}
    assert not (outside & shown), f"показаны записи вне периода или чужие: {outside & shown}"


def test_f11_author_suggestion_finds_active_and_dismissed_employees_by_part_of_name_as_full_name_rows(
        admin_page, employee, new_context):
    """Сценарий 11 (подсказка «Автор»): по части имени находятся действующий и уволенный сотрудники, строки — ФИО целиком
    (FR-635)."""
    mark = _uid()
    active = employee(full_name=f"Лебедев{mark} Иван Иванович")
    gone = employee(full_name=f"Лебедев{mark}а Анна Ивановна")
    viewer = _reader(employee)
    _dismiss(admin_page, gone.id)
    page = _open(new_context, viewer)
    field = page.locator('form#feed-filters input[data-feed-picker="author"]')
    field.fill("")
    field.press_sequentially(f"Лебедев{mark}", delay=30)  # часть имени: короче полного ФИО
    options = page.locator("[data-feed-pick-list] [data-pick-value][data-pick-label]")
    expect(options.first).to_be_visible(timeout=10_000)
    expect(options).to_have_count(2, timeout=10_000)
    labels = options.evaluate_all("els => els.map(e => e.dataset.pickLabel)")
    # строки — ФИО целиком (у уволенного допустима пометка «(уволен)» после ФИО)
    assert any(label == active.full_name for label in labels), labels
    assert any(label.startswith(gone.full_name) for label in labels), labels
    # выбор уволенного ставит его номер в скрытое поле формы
    options.filter(has_text=gone.full_name).first.click()
    expect(page.locator('form#feed-filters input[name="author"]')).to_have_value(str(gone.id))


def test_f11_filter_choice_is_in_page_address_and_filters_combine_by_and(admin_page, employee, new_context):
    """Сценарий 11 (адрес и «И»): выбор фильтров виден в адресе страницы и сохраняется при обновлении; фильтры сочетаются
    по «И» (FR-635)."""
    mark = _uid()
    author, other = _writers(admin_page, employee, 2)
    viewer = _reader(employee)
    page_a, page_o = _open(new_context, author), _open(new_context, other)
    both = helpers_feed.publish(page_a, f"Важная автора {mark}", kind="important", term="week")
    plain_of_author = helpers_feed.publish(page_a, f"Обычная автора {mark}")
    important_of_other = helpers_feed.publish(page_o, f"Важная чужая {mark}", kind="important", term="week")
    page = _open(new_context, viewer)
    form = page.locator("form#feed-filters")
    # когда: выбирает «Важные» и автора, применяет форму
    helpers_org.set_choice(form, "f", "important")
    helpers_feed.pick_author(page, author.full_name.split()[0], author.full_name)
    with page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()
    # выбор — в адресе страницы
    query = dict(part.split("=", 1) for part in page.url.split("?", 1)[1].split("&"))
    assert query.get("f") == "important" and query.get("author") == str(author.id), page.url
    # «И»: важная запись этого автора; чужая важная и обычная этого автора не показаны
    shown = set(_shown(page))
    assert both in shown and not ({plain_of_author, important_of_other} & shown), shown
    # после обновления страницы выбор сохранён в форме и в результате
    page.reload()
    expect(page.locator('form#feed-filters input[name="author"]')).to_have_value(str(author.id))
    shown = set(_shown(page))
    assert both in shown and not ({plain_of_author, important_of_other} & shown)


def test_f11_empty_result_of_filter_says_no_posts_by_filter(admin_page, employee, new_context):
    """Сценарий 11 (пустой результат): фильтр без записей — «По фильтру записей нет» (FR-635)."""
    me = _reader(employee)  # новый сотрудник: своих записей нет
    page = _open(new_context, me)
    _home(page, f="mine")
    empty = page.locator('[data-empty-state="feed-filter"]')
    expect(empty).to_be_visible()
    expect(empty).to_contain_text(NO_POSTS)
    assert helpers_feed.post_ids(page) == []


def test_f11_unknown_filter_key_or_wrong_value_in_address_is_ignored_without_server_error(
        admin_page, employee, new_context):
    """Сценарий 11, п. 3: ключ фильтра не из белого списка и неверное значение в адресе не учитываются, ошибки сервера нет
    (FR-635, NFR-608)."""
    me = _reader(employee)
    page = _open(new_context, me)
    addresses = (
        "/?foo=bar&debug=1",
        "/?f=bogus",
        "/?author=abc&from=xx&to=yy",
        "/?author=999999999999999999999&from=31.31.2026",
        "/?f=mine&f=events&unknown[]=1",
        "/feed/more/?f=bogus&before=zzz&opened=zzz&author=!",
        "/feed/new/?since=zzz&f=bogus&from=xx",
    )
    for path in addresses:
        response = helpers_org.direct_get(page, path)
        assert response.status == 200, f"{path}: ответ {response.status}"
        assert "Traceback" not in response.text() and "Server Error" not in response.text(), path
    # страница с чужим ключом открывается как обычная главная
    _home(page, foo="bar", f="bogus")
    expect(page.locator("form#feed-filters")).to_be_visible()


# --- Тесты: сквозной поиск ---------------------------------------------------------------------------------------

def test_f11_top_search_finds_post_by_word_form_and_comment_by_word_start_in_feed_group_as_name_date_text_rows(
        admin_page, employee, new_context):
    """Сценарий 11, п. 4: запись со словом «серверная» и комментарий со словом «коммутатора» находятся запросами «серверной»
    и «коммутатор» в группе «Лента» строками «ФИО, дата — начало текста» (FR-636)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    post_word, comment_word = _word("p"), _word("c")
    page = _open(new_context, author)
    post_id = helpers_feed.publish(page, f"Заменили серверная {post_word}")
    card = helpers_feed.open_card(new_context(), author, post_id)
    comment_id = helpers_feed.add_comment(card, post_id, f"Порт коммутатора {comment_word}")
    search = _open(new_context, viewer)
    # п. 4: запись — по другой форме слова
    _wait_found(search, f"серверной {post_word}", _post_href(post_id))
    row = _row(search, _post_href(post_id))
    title = row.locator('[data-field="title"]').inner_text()
    assert re.match(rf"^{re.escape(author.full_name)}, {DATE_IN_TITLE} — ", title), title
    assert post_word in title and "серверная" in title
    expect(row.locator('[data-field="subtitle"]')).to_have_text("Запись")
    # п. 4: комментарий — по началу слова
    _wait_found(search, f"коммутатор {comment_word}", _comment_href(post_id, comment_id))
    row = _row(search, _comment_href(post_id, comment_id))
    title = row.locator('[data-field="title"]').inner_text()
    assert re.match(rf"^{re.escape(author.full_name)}, {DATE_IN_TITLE} — ", title), title
    assert comment_word in title
    expect(row.locator('[data-field="subtitle"]')).to_have_text("Комментарий")


def test_f11_found_post_row_opens_post_card_and_found_comment_row_opens_comment_anchor(
        admin_page, employee, new_context):
    """Сценарий 11, п. 4 (переход): нажатие на найденную запись ведёт к карточке записи, на найденный комментарий — к самому
    комментарию (FR-636)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    post_word, comment_word = _word("p"), _word("c")
    page = _open(new_context, author)
    post_id = helpers_feed.publish(page, f"Запись про серверная {post_word}")
    card = helpers_feed.open_card(new_context(), author, post_id)
    comment_id = helpers_feed.add_comment(card, post_id, f"Комментарий про коммутатора {comment_word}")
    search = _open(new_context, viewer)
    _wait_found(search, f"серверной {post_word}", _post_href(post_id))
    with search.expect_navigation():
        _row(search, _post_href(post_id)).locator("a[href]").first.click()
    assert search.url.rstrip("/").endswith(f"/feed/{post_id}"), search.url
    expect(search.locator('[data-feed-page="card"]')).to_be_visible()
    expect(search.locator(f"#feed-post-{post_id}")).to_be_visible()
    _wait_found(search, f"коммутатор {comment_word}", _comment_href(post_id, comment_id))
    with search.expect_navigation():
        _row(search, _comment_href(post_id, comment_id)).locator("a[href]").first.click()
    search.wait_for_load_state()
    assert search.url.endswith(f"/feed/{post_id}/#c{comment_id}"), search.url
    expect(search.locator(f"#c{comment_id}")).to_be_visible()


def test_f11_invisible_post_and_its_comments_are_absent_and_feed_group_shows_no_count_for_them(
        admin_page, employee, new_context):
    """Сценарий 11, п. 5: запись, которую сотрудник не видит, и её комментарии в выдаче отсутствуют, группа «Лента» их число
    не показывает (FR-606, FR-636)."""
    author, = _writers(admin_page, employee, 1)
    addressee, outsider = _reader(employee, "Петров"), _reader(employee, "Чужов")
    shared, hidden_only = _word("s"), _word("h")
    page = _open(new_context, author)
    visible_id = helpers_feed.publish(page, f"Видимая серверная {shared}")
    hidden_id = helpers_feed.publish(page, f"Скрытая серверная {shared} {hidden_only}",
                                     to=[("person", addressee.full_name)])
    card = helpers_feed.open_card(new_context(), author, hidden_id)
    hidden_comment = helpers_feed.add_comment(card, hidden_id, f"Скрытый комментарий коммутатора {shared}")
    # контроль: адресату видны и скрытая запись, и её комментарий
    insider = _open(new_context, addressee)
    _wait_found(insider, f"серверной {shared}", _post_href(hidden_id))
    _wait_found(insider, f"коммутатор {shared}", _comment_href(hidden_id, hidden_comment))
    # контроль: посторонний находит видимую запись
    search = _open(new_context, outsider)
    _wait_found(search, f"серверной {shared}", _post_href(visible_id))
    # п. 5: общее слово — в выдаче только видимая запись, число группы — 1
    hrefs = _hrefs(search, shared)
    assert hrefs == [_post_href(visible_id)], hrefs
    expect(_feed_group(search).locator("[data-search-count-value]")).to_have_attribute("data-count", "1", timeout=15_000)
    # п. 5: слово только в скрытой записи — группы «Лента» с ними нет, комментария нет
    assert _hrefs(search, f"коммутатор {shared}") == []
    assert _hrefs(search, hidden_only) == []
    expect(_feed_group(search)).to_have_count(0)


def test_f11_deleted_post_and_old_text_of_edited_post_are_not_found_and_new_text_is_found(
        admin_page, employee, new_context):
    """Сценарий 11, п. 6 (запись): запись удалена или её текст исправлен — прежний текст не находится, новый находится
    (FR-637)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    deleted_word, old_word, new_word = _word("d"), _word("o"), _word("n")
    page = _open(new_context, author)
    deleted_id = helpers_feed.publish(page, f"Будет удалена серверная {deleted_word}")
    edited_id = helpers_feed.publish(page, f"Было серверная {old_word}")
    search = _open(new_context, viewer)
    # контроль: обе записи находятся
    _wait_found(search, f"серверной {deleted_word}", _post_href(deleted_id))
    _wait_found(search, f"серверной {old_word}", _post_href(edited_id))
    # когда: одна удалена, у другой исправлен текст
    _delete_post(page, deleted_id)
    _edit_post(page, edited_id, text=f"Стало серверная {new_word}")
    # п. 6: прежнее не находится, новое находится
    assert _post_href(deleted_id) not in _hrefs(search, f"серверной {deleted_word}")
    assert _post_href(edited_id) not in _hrefs(search, f"серверной {old_word}")
    _wait_found(search, f"серверной {new_word}", _post_href(edited_id))


def test_f11_deleted_comment_and_old_text_of_edited_comment_are_not_found_and_new_text_is_found(
        admin_page, employee, new_context):
    """Сценарий 11, п. 6 (комментарий): комментарий удалён или исправлен — прежний текст не находится, новый находится
    (FR-637)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    deleted_word, old_word, new_word = _word("d"), _word("o"), _word("n")
    page = _open(new_context, author)
    post_id = helpers_feed.publish(page, f"Запись для комментариев {_uid()}")
    card = helpers_feed.open_card(new_context(), author, post_id)
    deleted_comment = helpers_feed.add_comment(card, post_id, f"Будет удалён коммутатора {deleted_word}")
    edited_comment = helpers_feed.add_comment(card, post_id, f"Было коммутатора {old_word}")
    search = _open(new_context, viewer)
    _wait_found(search, f"коммутатор {deleted_word}", _comment_href(post_id, deleted_comment))
    _wait_found(search, f"коммутатор {old_word}", _comment_href(post_id, edited_comment))
    # когда: один комментарий удалён, у другого исправлен текст
    _delete_comment(card, deleted_comment)
    _edit_comment(card, edited_comment, f"Стало коммутатора {new_word}")
    assert _comment_href(post_id, deleted_comment) not in _hrefs(search, f"коммутатор {deleted_word}")
    assert _comment_href(post_id, edited_comment) not in _hrefs(search, f"коммутатор {old_word}")
    _wait_found(search, f"коммутатор {new_word}", _comment_href(post_id, edited_comment))


def test_f11_event_found_by_title_and_place_word_forms_as_row_with_event_title(admin_page, employee, new_context):
    """Сценарий 11, п. 7: событие «Учения по пожарной безопасности», место «Корпус 2» — находится запросами «пожарной» и
    «корпусе», строка — с названием события (FR-636)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    title_word, place_word = _word("t"), _word("p")
    title = f"Учения по пожарной безопасности {title_word}"
    place = f"Корпус 2 {place_word}"
    start = (datetime.now(MOSCOW) + timedelta(days=4)).replace(tzinfo=None, second=0, microsecond=0)
    page = _open(new_context, author)
    post_id = helpers_feed.publish(page, "", kind="event", event={
        "title": title, "place": place, "start": start, "end": start + timedelta(hours=2)})
    search = _open(new_context, viewer)
    for query in (f"пожарной {title_word}", f"корпусе {place_word}"):
        _wait_found(search, query, _post_href(post_id))
        row_title = _row(search, _post_href(post_id)).locator('[data-field="title"]').inner_text()
        # строка — «ФИО, дата — название события» (текст записи пуст)
        assert re.match(rf"^{re.escape(author.full_name)}, {DATE_IN_TITLE} — ", row_title), row_title
        assert title in row_title, row_title


def test_f11_feed_group_rows_go_from_newer_to_older(admin_page, employee, new_context):
    """Сценарий 11, п. 7 (порядок): найденное в группе «Лента» идёт от новых к старым (FR-636)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    word = _word("o")
    page = _open(new_context, author)
    first = helpers_feed.publish(page, f"Первая серверная {word}")
    card = helpers_feed.open_card(new_context(), author, first)
    comment = helpers_feed.add_comment(card, first, f"Затем комментарий коммутатора {word}")
    second = helpers_feed.publish(page, f"Вторая серверная {word}")
    third = helpers_feed.publish(page, f"Третья серверная {word}")
    search = _open(new_context, viewer)
    _wait_found(search, word, _post_href(third))
    mine = [_post_href(third), _post_href(second), _comment_href(first, comment), _post_href(first)]
    deadline = time.monotonic() + FIND_TIMEOUT
    while True:  # запись и комментарии одной выдачей: ждём всех четырёх
        hrefs = _hrefs(search, word)
        if all(href in hrefs for href in mine) or time.monotonic() > deadline:
            break
        search.wait_for_timeout(1000)
    ours = [href for href in hrefs if href in mine]
    # п. 7: от новых к старым — третья, вторая, комментарий (написан после первой), первая
    assert ours == mine, f"порядок {ours}, ожидался {mine}"


def test_f11_word_only_in_attached_file_content_does_not_find_post(admin_page, employee, new_context, tmp_path):
    """Сценарий 11 (файлы): слово, которое есть только в содержимом прикреплённого файла, запись не находит (FR-636)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    text_word, file_word = _word("t"), _word("f")
    path = tmp_path / f"заметки{_uid()}.txt"
    path.write_text(f"Содержимое файла с редким словом {file_word}\n", encoding="utf-8")
    page = _open(new_context, author)
    post_id = helpers_feed.publish(page, f"Запись с файлом серверная {text_word}", files=[path])
    (file_id,) = [int(v) for v in page.locator(f"#feed-post-{post_id} [data-feed-file]").evaluate_all(
        "els => els.map(e => e.dataset.feedFile)")]
    helpers_feed.wait_clean(page, file_id)  # файл проверен и доступен
    search = _open(new_context, viewer)
    # контроль: по слову текста запись находится
    _wait_found(search, f"серверной {text_word}", _post_href(post_id))
    # по слову из файла — нет
    assert _post_href(post_id) not in _hrefs(search, file_word)
    expect(_feed_group(search)).to_have_count(0)


# --- Тесты: упоминания и важное ----------------------------------------------------------------------------------

def test_f11_mentions_me_filter_shows_unread_important_post_by_publication_time_without_important_block(
        admin_page, employee, new_context):
    """Сценарий 11, п. 8 (упоминания): сотрудника упомянули в важной записи, он не нажал «Прочитано» — при «Упоминают меня»
    запись видна в выдаче по времени публикации, блока важных нет (FR-602, FR-635)."""
    mark = _uid()
    author, = _writers(admin_page, employee, 1)
    me = _reader(employee)
    page = _open(new_context, author)
    important = helpers_feed.publish(page, f"Важная упоминание {mark}", kind="important", term="week",
                                     mentions=[me.full_name])
    later = helpers_feed.publish(page, f"Позже упоминание {mark}", mentions=[me.full_name])
    mine_page = _open(new_context, me)
    _home(mine_page, f="mentions")
    # п. 8: блока важных нет, запись — в основной ленте
    expect(mine_page.locator("#feed-important")).to_have_count(0)
    ids = helpers_feed.post_ids(mine_page)
    assert important in ids and later in ids, ids
    # п. 8: по времени публикации (новая выше), запись не закреплена наверху как «важная»
    assert ids.index(later) < ids.index(important), f"порядок {ids}"


def test_f11_all_filter_without_author_and_period_shows_same_important_post_in_block_not_repeated_in_feed(
        admin_page, employee, new_context):
    """Сценарий 11, п. 8 («Все»): при «Все» без автора и периода та же запись стоит в блоке важных и в основной ленте не
    повторяется (FR-602, FR-635)."""
    mark = _uid()
    author, = _writers(admin_page, employee, 1)
    me = _reader(employee)
    page = _open(new_context, author)
    important = helpers_feed.publish(page, f"Важная блок {mark}", kind="important", term="week",
                                     mentions=[me.full_name])
    mine_page = _open(new_context, me)
    _home(mine_page)
    assert important in helpers_feed.important_ids(mine_page), "важной записи нет в блоке важных"
    assert important not in helpers_feed.post_ids(mine_page), "важная запись повторена в основной ленте"
    _home(mine_page, f="all")
    assert important in helpers_feed.important_ids(mine_page)
    assert important not in helpers_feed.post_ids(mine_page)


# --- Тесты: узкий экран ------------------------------------------------------------------------------------------

def test_f11_search_results_and_filters_do_not_widen_page_at_360px(admin_page, employee, new_context):
    """Сценарий 11, NFR-606: на ширине 360 px фильтры ленты и выдача поиска не расширяют страницу (NFR-606)."""
    author, = _writers(admin_page, employee, 1)
    viewer = _reader(employee)
    word = _word("n")
    long_word = "ы" * 150   # слово без пробелов: не должно раздвигать страницу
    page = _open(new_context, author)
    post_id = helpers_feed.publish(page, f"Серверная {word} {long_word}", kind="important", term="week")
    search = _open(new_context, viewer)
    _wait_found(search, f"серверной {word}", _post_href(post_id))
    # фильтры ленты с выбранным значением
    _home(search, f="important", author=author.id)
    assert helpers_feed.check_360(search)
    # выдача поиска с найденной длинной записью
    _results(search, f"серверной {word}")
    expect(_feed_group(search).locator("li[data-search-row]")).to_have_count(1)
    assert helpers_feed.check_360(search)
