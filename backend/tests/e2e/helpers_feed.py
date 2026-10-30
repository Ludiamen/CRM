"""Помощники приёмки среза 007 «Живая лента» (T-7140a; ими пользуются T-7140b…T-7154).

Что здесь есть (CONTRACT-007.md: разделы 10.2, 12, 13, 14.4; решения 8, 54, 55 задач; имена вне строки T-7140a —
решение контракта К39):
- сценарные люди и узлы: `FeedCast`, `feed_cast`, `make_role` (роль только с названными правами);
- вход и страницы: `open_feed(context, account, live=True)`, `open_card(context, account, post_id)`;
- публикация формой: `publish`, `try_publish`; запросом той же формы (объёмы): `publish_request`;
- выбор из подсказок: `pick_to`, `pick_mention`, `pick_author`;
- действия над записью и комментарием: `add_comment`, `try_comment`, `like`, `like_comment`, `mark_read`, `answer`;
- число «Ленты» и плашка: `badge`, `wait_badge`, `wait_banner`; номера записей: `post_ids`, `important_ids`;
- файлы (ClamAV стенда): `upload`, `try_upload`, `wait_clean`, `wait_quarantine`, `wait_file_state`, `eicar_file`;
- команды стенда: `shift(minutes)` над `e2e_feed_shift`, `age(days, posts=None)` над `e2e_feed_retention`,
  разбор строк — `parse_shift_line`, `parse_retention_line`;
- без WebSocket (приёмка f08): `block_ws(context)`;
- отказы форм: `refusals`;
- письма, колокольчик, «Мои уведомления», Telegram, письма через 15 минут: `feed_mail`, `no_feed_mail`, `bell`,
  `wait_bell`, `my_notifications`, `fakebots`, `tick_mail` (готовое из `helpers`, `helpers_notify`);
- ширина 360 px: `check_360`.

Правила (шаблон e2e/template.md): код приложения (`apps.*`, `django`) и `tests.support*` не импортируются; локаторы —
только из контракта (раздел 12); ждать — `expect`, `expect_response`; сна нет. Данные круга общие: каждый тест заводит
свои записи; `shift` сдвигает события и важные записи ВСЕХ записей стенда, `age` без `posts` — все записи стенда.
Готовое из прежних срезов вызывается, не дублируется: `helpers` (`Account`, `make_employee`, `no_horizontal_scroll`,
`wait_mail`), `helpers_org` (`create_unit`, `add_members`, `unique_name`, `set_choice`), `helpers_sd._stand_command`,
`helpers_notify` (`adopt_session`, `tick`, `wait_item_mail`, `bell_count`, `fakebots`), `helpers_kb.eicar_bytes`.
Файл правит только T-7140a.
"""
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import NamedTuple

from playwright.sync_api import FormData
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_notify, helpers_org, helpers_sd

POST_ALL = "feed.post_all"          # право «Писать всем» (раздел 2, 7)
MODERATE = "feed.moderate"          # право «Модерировать ленту»
SHIFT_MIN, SHIFT_MAX = 1, 10_080    # границы `--minutes` (14.1)
AGE_MIN, AGE_MAX = 1, 4_000         # границы `--age-days` (14.2)
BANNER_TEXT = "Новых записей: {count}"
_FORM = "form#feed-form"
_REFUSAL = "[data-error][data-code], [role=alert][data-code]"  # отказы формы (10.1)
_POST_ID = re.compile(r'data-post-id="(\d+)"')
_COMMENT_ID = re.compile(r'data-comment-id="(\d+)"')
_FILE_ID = re.compile(r'data-feed-file="(\d+)"')
_SHIFT_KEYS = ("shifted", "reminded", "important")
_RETENTION_KEYS = ("aged", "deleted")
_WS_URL = re.compile(r"/ws/(feed|notify)/")


# --- Люди и узлы сценариев (14.4, `FeedCast`) --------------------------------------------------------------------

class FeedCast(NamedTuple):
    """Участники сценариев ленты. Учётки — `helpers.Account` (сессия — `account.page`); узлы — номера строкой."""
    writer: object            # роль с правом «Писать всем»
    moderator: object         # роль с правом «Модерировать ленту»
    plain: object             # сотрудник без прав ленты (роль без прав)
    it_unit: str              # «Отдел ИТ»
    net_unit: str             # «Группа сети», вложена в «Отдел ИТ»
    accounting_unit: str      # «Бухгалтерия»
    it_member: object         # сотрудник «Отдела ИТ»
    net_member: object        # сотрудник «Группы сети»
    part_timer: object        # основная работа — «Бухгалтерия», совместительство — «Группа сети»
    accountant: object        # сотрудник «Бухгалтерии»
    petrov: object            # сотрудник «Бухгалтерии»
    sidorov: object           # сотрудник «Бухгалтерии»


def make_role(admin_page, permissions=(), name: str | None = None) -> str:
    """Новая роль формой `/roles/new/` с флажками `input[name=permissions][value="<код>"]` для `permissions`
    (образец — `test_d08_heads`). Возвращает название роли (`name` по умолчанию — уникальное «Роль ленты-<hex>»)."""
    name = name or helpers_org.unique_name("Роль ленты")
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    for code in permissions:
        form.locator(f'input[name=permissions][value="{code}"]').check()
    with admin_page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    admin_page.wait_for_load_state()
    return name


def feed_cast(admin_page, mailpit, new_context) -> FeedCast:
    """Создаёт роли, узлы и учётки через интерфейс (`make_role`, `helpers.make_employee`, `helpers_org.create_unit`,
    `helpers_org.add_members`). Названия узлов и ФИО — уникальные на круг (`<название>-<hex>`); у всех людей общая
    часть ФИО `<hex>`, чтобы один запрос `add_members(q=…)` находил их. Совместитель добавляется в «Бухгалтерию»
    (основная работа) и затем в «Группу сети» (совместительство, у команды режима нет)."""
    token = helpers_org.unique_name("к")[2:]
    writer_role = make_role(admin_page, [POST_ALL])
    moderator_role = make_role(admin_page, [MODERATE])
    plain_role = make_role(admin_page)

    def person(surname: str, role: str):
        return helpers.make_employee(admin_page, mailpit, new_context, role=role,
                                     full_name=f"{surname}{token} Иван Иванович")

    writer = person("Писарев", writer_role)
    moderator = person("Модераторов", moderator_role)
    plain = person("Простов", plain_role)
    it_member = person("Итов", plain_role)
    net_member = person("Сетев", plain_role)
    part_timer = person("Совместов", plain_role)
    accountant = person("Бухов", plain_role)
    petrov = person("Петров", plain_role)
    sidorov = person("Сидоров", plain_role)

    helpers_org.open_structure(admin_page)
    root_id = helpers_org.root_id(admin_page)
    it_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Отдел ИТ"), kind="department", parent_id=root_id)
    net_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Группа сети"), kind="team", parent_id=it_unit)
    accounting_unit = helpers_org.create_unit(admin_page, helpers_org.unique_name("Бухгалтерия"), kind="department", parent_id=root_id)

    helpers_org.add_members(admin_page, it_unit, [it_member.id], q=token, mode="concurrent")
    helpers_org.add_members(admin_page, net_unit, [net_member.id], q=token)
    helpers_org.add_members(admin_page, accounting_unit, [part_timer.id, accountant.id, petrov.id, sidorov.id],
                            q=token, mode="concurrent")
    helpers_org.add_members(admin_page, net_unit, [part_timer.id], q=token)
    return FeedCast(writer, moderator, plain, it_unit, net_unit, accounting_unit, it_member, net_member, part_timer,
                    accountant, petrov, sidorov)


# --- Вход и страницы (14.4) --------------------------------------------------------------------------------------

def _live_ready(page) -> None:
    expect(page.locator('#feed-live[data-ws="open"]')).to_be_attached(timeout=20_000)


def open_feed(context, account, live: bool = True):
    """Сессия сотрудника `account` переносится в `context` (`helpers_notify.adopt_session`), новая страница, `/`.
    `live=True` — ждёт `#feed-live[data-ws="open"]`; `live=False` (после `block_ws`, приёмка f08) — только загрузки
    страницы и корня тела главной `[data-feed-page="home"]`. Возвращает страницу."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto("/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()
    if live:
        _live_ready(page)
    return page


def open_card(context, account, post_id):
    """Сессия `account` в `context`, `/feed/<post_id>/`, ждёт `#feed-live[data-ws="open"]`. Возвращает страницу."""
    helpers_notify.adopt_session(context, account)
    page = context.new_page()
    page.goto(f"/feed/{post_id}/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="card"]')).to_be_visible()
    _live_ready(page)
    return page


# --- Подсказки «Кому», «@», «автор» (10.2, 12.2) ------------------------------------------------------------------

def _pick(page, field, query: str, label: str) -> None:
    field.fill("")
    field.press_sequentially(query, delay=30)
    option = page.locator(f'[data-feed-pick-list] [data-pick-label="{label}"]').first
    expect(option).to_be_visible(timeout=10_000)
    option.click()


def pick_to(page, query: str, label: str) -> None:
    """Вводит `query` в `input[data-feed-picker="to"]` формы записи и выбирает строку `[data-pick-label="<label>"]`
    (ФИО или название узла); ждёт, что число таблеток `[data-to-pill]` в форме выросло."""
    pills = page.locator(f"{_FORM} [data-to-pill]")
    before = pills.count()
    _pick(page, page.locator(f'{_FORM} input[data-feed-picker="to"]'), query, label)
    expect(pills).to_have_count(before + 1)


def pick_mention(page, field, query: str, label: str) -> None:
    """Упоминание «@»: в поле текста `field` (локатор `textarea` или его CSS-селектор) набирает `@<query>` и выбирает
    строку `[data-pick-label="<label>"]`; ждёт `@<label>` в тексте поля. Если у поля есть отдельный
    `input[data-feed-picker="mention"]` вне текста, `field` — он (тогда проверки текста нет)."""
    box = page.locator(field) if isinstance(field, str) else field
    box.click()
    box.press_sequentially("@" + query, delay=30)
    option = page.locator(f'[data-feed-pick-list] [data-pick-label="{label}"]').first
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    if box.evaluate("el => el.tagName") == "TEXTAREA":
        expect(box).to_have_value(re.compile(re.escape("@" + label)))


def pick_author(page, query: str, label: str) -> None:
    """Автор в фильтрах: `input[data-feed-picker="author"]` в `form#feed-filters`, выбор строки `label`; ждёт, что
    скрытое `input[name="author"]` получило значение."""
    scope = page.locator("form#feed-filters")
    _pick(page, scope.locator('input[data-feed-picker="author"]'), query, label)
    expect(scope.locator('input[name="author"]')).not_to_have_value("")


# --- Даты полей --------------------------------------------------------------------------------------------------

def _fill_date(field, value) -> None:
    """Заполняет поле даты или времени по его типу: `date` — `YYYY-MM-DD`, `datetime-local` — `YYYY-MM-DDTHH:MM`,
    иное — `ДД.ММ.ГГГГ[ ЧЧ:ММ]`. Значение — строка в любом из этих видов, `date` или `datetime`."""
    if isinstance(value, datetime):
        iso, ru = value.strftime("%Y-%m-%dT%H:%M"), value.strftime("%d.%m.%Y %H:%M")
    elif isinstance(value, date):
        iso, ru = value.isoformat(), value.strftime("%d.%m.%Y")
    else:
        text = str(value).strip()
        m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})(?: (\d{2}):(\d{2}))?", text)
        if m:
            d, mo, y, hh, mm = m.groups()
            ru = text
            iso = f"{y}-{mo}-{d}" + (f"T{hh}:{mm}" if hh else "")
        else:
            m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", text)
            assert m, f"дата {value!r}: нужен вид ДД.ММ.ГГГГ[ ЧЧ:ММ] или YYYY-MM-DD[THH:MM]"
            y, mo, d, hh, mm = m.groups()
            iso = f"{y}-{mo}-{d}" + (f"T{hh}:{mm}" if hh else "")
            ru = f"{d}.{mo}.{y}" + (f" {hh}:{mm}" if hh else "")
    kind = (field.get_attribute("type") or "text").lower()
    if kind in ("date", "datetime-local"):
        field.fill(iso[:10] if kind == "date" else (iso if "T" in iso else iso + "T00:00"))
    else:
        field.fill(ru)


# --- Публикация формой (10.2, 12.2) ------------------------------------------------------------------------------

def _choose_kind(form, kind: str) -> None:
    radio = form.locator(f'input[name="kind"][value="{kind}"]')
    expect(radio).to_have_count(1)
    try:
        radio.check(timeout=3_000)
    except PlaywrightTimeoutError:  # переключатель скрыт оформлением: нажимается подпись
        form.locator(f'label:has(input[name="kind"][value="{kind}"])').click()
    expect(radio).to_be_checked()
    if kind in ("important", "event"):
        expect(form.locator(f'[data-kind-fields="{kind}"]')).to_be_visible()


def _set_to(page, form, to) -> None:
    """Приводит «Кому» к `to`: «Всем» — таблетка `all`, которая у сотрудника с «Писать всем» уже стоит при открытии
    формы (план); лишняя таблетка снимается крестиком, адресаты — подсказкой."""
    items = list(to)
    all_pill = form.locator('[data-to-pill="all"]')
    if "all" in items:
        expect(all_pill).to_have_count(1)  # кнопки «Всем» в форме нет: у держателя права таблетка уже стоит
    elif all_pill.count():
        all_pill.locator('button[data-action="to-remove"]').click()
        expect(all_pill).to_have_count(0)
    for item in items:
        if item == "all":
            continue
        kind, label = item
        assert kind in ("unit", "person"), f"адресат {item!r}: нужен 'all', ('unit', название) или ('person', ФИО)"
        query = label if kind == "unit" else label.split()[0]
        pick_to(page, query, label)


def _fill_form(page, text, kind, to, term, until, event, files, mentions) -> None:
    form = page.locator(_FORM)
    expect(form).to_be_visible()
    _choose_kind(form, kind)
    body = form.locator('textarea[name="text"]')
    body.fill(text)
    for label in mentions:
        body.press("End")
        pick_mention(page, body, label.split()[0], label)
    if to is not None:
        _set_to(page, form, to)
    if kind == "important" and term is not None:
        helpers_org.set_choice(form, "term", term)
        if term == "date":
            assert until is not None, "term='date' требует until"
            _fill_date(form.locator('input[name="until"]'), until)
    if kind == "event" and event:
        for key, name in (("title", "event_title"), ("place", "event_place")):
            if key in event:
                form.locator(f'[name="{name}"]').fill(str(event[key]))
        for key, name in (("start", "event_start"), ("end", "event_end")):
            if key in event:
                _fill_date(form.locator(f'[name="{name}"]'), event[key])
    for path in files:
        upload(page, path, scope="post")


def _submit(page, button, url_part: str, method: str = "POST") -> str:
    """Нажимает `button` и возвращает тело ответа на запрос `method` с `url_part` в адресе (ждёт его)."""
    with page.expect_response(lambda r: r.request.method == method and url_part in r.url) as info:
        button.click()
    return info.value.text()


def _publish_button(page):
    return page.locator(_FORM).get_by_role("button", name="Опубликовать", exact=True)


def publish(page, text: str = "", *, kind: str = "post", to=None, term=None, until=None, event=None, files=(),
            mentions=(), confirm_pdn: bool = False) -> int:
    """Публикует запись формой `form#feed-form` и возвращает её `data-post-id`.
    - `kind`: `post`, `important`, `event`; `to` — список адресатов: `"all"`, `("unit", <название>)`,
      `("person", <ФИО>)`; `None` — «Кому» как в форме при открытии (у держателя «Писать всем» стоит «Всем»);
    - `term` (важное): `day`, `week`, `month`, `date`; при `date` — `until` (`ДД.ММ.ГГГГ`, `YYYY-MM-DD`, `date`);
    - `event` (событие): словарь `title`, `place`, `start`, `end` (`ДД.ММ.ГГГГ ЧЧ:ММ`, `YYYY-MM-DDTHH:MM`, `datetime`);
    - `files` — пути (грузятся `upload` до отправки); `mentions` — ФИО, выбираются через «@» в конце текста;
    - `confirm_pdn=True` — при предупреждении о ПДн нажимает «Опубликовать всё равно».
    Отказ — `AssertionError` с кодами (для проверки отказов — `try_publish`). Ждёт появления записи на странице."""
    html = _send(page, text, kind, to, term, until, event, files, mentions, confirm_pdn)
    codes = _codes_in(html)
    assert not codes, f"публикация отклонена: {codes}"
    ids = _POST_ID.findall(html)
    assert ids, "в ответе на публикацию нет записи (data-post-id)"
    post_id = int(ids[0])
    expect(page.locator(f"#feed-post-{post_id}").first).to_be_visible()
    return post_id


def try_publish(page, text: str = "", *, kind: str = "post", to=None, term=None, until=None, event=None, files=(),
                mentions=(), confirm_pdn: bool = False) -> list:
    """То же, что `publish`, но без ожидания записи: возвращает пары `(поле или "", data-code)` отказов из ответа
    (общий отказ `[role=alert]` — поле `""`). Пустой список — отказа нет (запись опубликована или показано
    предупреждение о ПДн: его смотрят по `[data-feed-pdn]` на странице)."""
    return _codes_in(_send(page, text, kind, to, term, until, event, files, mentions, confirm_pdn))


def _send(page, text, kind, to, term, until, event, files, mentions, confirm_pdn) -> str:
    _fill_form(page, text, kind, to, term, until, event, files, mentions)
    html = _submit(page, _publish_button(page), "/feed/posts/")
    if confirm_pdn and "data-feed-pdn" in html:
        html = _submit(page, page.locator(_FORM).locator('button[name="pdn_confirmed"][value="1"]'), "/feed/posts/")
    return html


def _codes_in(html: str) -> list:
    """Отказы в HTML ответа: пары `(поле или "", код)` по порядку (разбор элементов с `data-code`)."""
    out = []
    for tag in re.findall(r"<[^>]*\bdata-code=\"[^\"]*\"[^>]*>", html):
        code = re.search(r'data-code="([^"]*)"', tag).group(1)
        field = re.search(r'data-error="([^"]*)"', tag)
        out.append((field.group(1) if field else "", code))
    return out


def refusals(page) -> list:
    """Отказы, которые сейчас видны на странице (10.1): пары `(поле или "", data-code)`."""
    out = []
    for el in page.locator(_REFUSAL).all():
        field = el.get_attribute("data-error")
        out.append((field or "", el.get_attribute("data-code")))
    return out


def publish_request(page, **fields) -> int:
    """Публикация POST-запросом той же формы (`page.request` с токеном CSRF страницы) для объёмов (45 записей, 120
    непрочитанных). `fields` — поля раздела 10.2: `kind`, `text`, `to` (строка или список: `all`, `u<id>`, `p<id>`),
    `term`, `until`, `event_title`, `event_place`, `event_start`, `event_end`, `files`, `pdn_confirmed`; список в `to` —
    повторяющийся ключ `to` в теле (К87). Запрос без заголовка HTMX — ответ 302 на `/` (запись создана); отказ — 200
    с формой. Возвращает номер новой записи: он берётся из первой записи страницы `/` после запроса
    (`#feed-list [data-post-id]` — самая новая у автора)."""
    data = {k: v for k, v in fields.items() if v is not None}
    if isinstance(data.get("to"), (list, tuple)):
        # несколько адресатов — повторяющийся ключ `to` (К87): словарь `form` ключ не повторяет, `FormData` — да
        if not data["to"]:
            raise ValueError("to: пустой список адресатов")
        form = FormData()
        for key, value in data.items():
            for item in (value if key == "to" else [value]):
                form.append(key, item)
        data = form
    response = helpers_org.direct_post(page, "/feed/posts/", data)
    assert response.status == 302, (f"публикация запросом: ожидался 302, получен {response.status}: "
                                    f"{_codes_in(response.text())}")
    html = helpers_org.direct_get(page, "/").text()
    ids = _POST_ID.findall(html[html.find('id="feed-list"'):]) if 'id="feed-list"' in html else []
    assert ids, "после публикации запросом лента пуста"
    return int(ids[0])


# --- Комментарии, «Нравится», «Прочитано», ответ на событие -------------------------------------------------------

def _comment_form(page, post_id):
    return page.locator(f"#feed-post-{post_id} form[data-feed-comment-form]").first


def _send_comment(page, post_id, text, files, mentions) -> str:
    form = _comment_form(page, post_id)
    expect(form).to_be_visible()
    body = form.locator('textarea[name="text"]')
    body.fill(text)
    for label in mentions:
        body.press("End")
        pick_mention(page, body, label.split()[0], label)
    for path in files:
        upload(page, path, scope="comment", post_id=post_id)
    return _submit(page, form.locator("button[type=submit]").first, f"/feed/{post_id}/comments/")


def add_comment(page, post_id, text: str, *, files=(), mentions=()) -> int:
    """Пишет комментарий к записи `post_id` формой записи (`form[data-feed-comment-form]`); `files` — пути,
    `mentions` — ФИО через «@». Возвращает `data-comment-id`; отказ — `AssertionError` с кодами."""
    html = _send_comment(page, post_id, text, files, mentions)
    codes = _codes_in(html)
    assert not codes, f"комментарий отклонён: {codes}"
    ids = _COMMENT_ID.findall(html)
    assert ids, "в ответе на комментарий нет data-comment-id"
    expect(page.locator(f"#c{ids[0]}").first).to_be_visible()
    return int(ids[0])


def try_comment(page, post_id, text: str, *, files=(), mentions=()) -> list:
    """Как `add_comment`, но возвращает пары `(поле или "", data-code)` отказов из ответа."""
    return _codes_in(_send_comment(page, post_id, text, files, mentions))


def like(page, post_id) -> bool:
    """Нажимает «Нравится» у записи; возвращает новое `aria-pressed` кнопки (`True` — отмечено)."""
    button = page.locator(f"#feed-post-{post_id} button[data-feed-like]").first
    _submit(page, button, f"/feed/{post_id}/like/")
    state = page.locator(f"#feed-post-{post_id} button[data-feed-like]").first.get_attribute("aria-pressed")
    return state == "true"


def like_comment(page, comment_id) -> bool:
    """«Нравится» у комментария `#c<id>`; возвращает новое `aria-pressed`."""
    button = page.locator(f"#c{comment_id} button[data-feed-like]").first
    _submit(page, button, f"/feed/comments/{comment_id}/like/")
    return page.locator(f"#c{comment_id} button[data-feed-like]").first.get_attribute("aria-pressed") == "true"


def mark_read(page, post_id) -> None:
    """«Прочитано» у важной записи: `#feed-post-<id>-imp button[data-action="read"]`; ждёт ответ."""
    button = page.locator(f'#feed-post-{post_id}-imp button[data-action="read"]').first
    _submit(page, button, f"/feed/{post_id}/read/")


def answer(page, post_id, value: str) -> None:
    """Ответ на событие: `value` — `go` («Пойду») или `no` («Не смогу»); ждёт ответ и обновлённый блок события."""
    assert value in ("go", "no"), f"ответ {value!r}: нужен 'go' или 'no'"
    button = page.locator(f'#feed-post-{post_id}-event button[data-action="answer"][value="{value}"]').first
    _submit(page, button, f"/feed/{post_id}/answer/")


# --- Число «Ленты», плашка, номера записей (12.2) ----------------------------------------------------------------

def badge(page) -> int:
    """Число у пункта «Лента»: `#menu-badge-feed[data-count]`. Нет узла или атрибута — `AssertionError`."""
    node = page.locator("#menu-badge-feed")
    value = node.get_attribute("data-count") if node.count() else None
    if value is None:
        raise AssertionError(f"на странице {page.url} нет #menu-badge-feed[data-count]")
    return int(value)


def wait_badge(page, value, timeout: int = 4_000) -> None:
    """Ждёт `#menu-badge-feed[data-count="<value>"]` (по умолчанию 4 с — число приходит кадром, без перезагрузки)."""
    expect(page.locator("#menu-badge-feed")).to_have_attribute("data-count", str(value), timeout=timeout)


def wait_banner(page, count, timeout: int = 4_000) -> None:
    """Ждёт плашку `#feed-new[data-count="<count>"]` с текстом «Новых записей: N»."""
    banner = page.locator("#feed-new")
    expect(banner).to_have_attribute("data-count", str(count), timeout=timeout)
    expect(banner).to_contain_text(BANNER_TEXT.format(count=count), timeout=timeout)


def _ids(page, selector: str) -> list:
    return [int(v) for v in page.locator(selector).evaluate_all(
        "els => els.map(e => e.getAttribute('data-post-id'))")]


def post_ids(page) -> list:
    """Номера записей ленты `#feed-list [data-post-id]` по порядку (сверху вниз)."""
    return _ids(page, "#feed-list [data-post-id]")


def important_ids(page) -> list:
    """Номера записей блока важных `#feed-important [data-post-id]` по порядку; нет блока — пустой список."""
    return _ids(page, "#feed-important [data-post-id]")


# --- Файлы (12.6, ClamAV стенда) ---------------------------------------------------------------------------------

def _upload_scope(page, scope: str, post_id):
    if scope == "post":
        return page.locator(_FORM)
    assert scope == "comment", f"scope {scope!r}: нужен 'post' или 'comment'"
    return _comment_form(page, post_id) if post_id is not None else page.locator("form[data-feed-comment-form]").first


def try_upload(page, path, *, scope: str = "post", post_id=None) -> list:
    """Кладёт файл в `input[type=file][data-feed-upload="<scope>"]` формы (для `comment` — форма записи `post_id`,
    без него — первая форма комментария страницы) и возвращает пары `(поле, код)` отказов ответа `/feed/files/`."""
    form = _upload_scope(page, scope, post_id)
    with page.expect_response(lambda r: r.request.method == "POST" and "/feed/files/" in r.url) as info:
        form.locator(f'input[type="file"][data-feed-upload="{scope}"]').set_input_files(str(path))
    return _codes_in(info.value.text())


def upload(page, path, *, scope: str = "post", post_id=None) -> int:
    """Загрузка файла формы: возвращает номер файла (`data-feed-file` новой таблетки). Отказ — `AssertionError`."""
    form = _upload_scope(page, scope, post_id)
    with page.expect_response(lambda r: r.request.method == "POST" and "/feed/files/" in r.url) as info:
        form.locator(f'input[type="file"][data-feed-upload="{scope}"]').set_input_files(str(path))
    html = info.value.text()
    codes = _codes_in(html)
    assert not codes, f"файл {Path(str(path)).name} отклонён: {codes}"
    ids = _FILE_ID.findall(html)
    assert ids, "в ответе на загрузку нет таблетки data-feed-file"
    expect(form.locator(f'[data-feed-file="{ids[0]}"]').first).to_be_visible()
    return int(ids[0])


def wait_file_state(page, file_id, states=("clean", "quarantine"), timeout: int = 60_000) -> str:
    """Опрос с обновлением страницы (пауза 2 с): ждёт, пока `[data-feed-file="<id>"][data-file-state]` примет одно из
    `states` («проверяется» — `pending`). Возвращает состояние; по истечении `timeout` мс — `AssertionError`."""
    deadline = time.monotonic() + timeout / 1000
    node = page.locator(f'[data-feed-file="{file_id}"][data-file-state]').first
    while True:
        if node.count():
            state = node.get_attribute("data-file-state")
            if state in states:
                return state
        if time.monotonic() > deadline:
            raise AssertionError(f"файл {file_id}: проверка не закончилась за {timeout // 1000} с")
        page.wait_for_timeout(2_000)
        page.reload()
        page.wait_for_load_state()


def wait_clean(page, file_id, timeout: int = 60_000) -> None:
    """Ждёт «проверяется → чистый» (`[data-file-state="clean"]` после обновления страницы, NFR: до минуты);
    «карантин» — `AssertionError`."""
    state = wait_file_state(page, file_id, ("clean", "quarantine"), timeout)
    assert state == "clean", f"файл {file_id}: ожидался чистый, а состояние {state}"


def wait_quarantine(page, file_id, timeout: int = 60_000) -> None:
    """Ждёт `[data-file-state="quarantine"]` (EICAR); «чистый» — `AssertionError`."""
    state = wait_file_state(page, file_id, ("clean", "quarantine"), timeout)
    assert state == "quarantine", f"файл {file_id}: ожидался карантин, а состояние {state}"


def eicar_file(tmp_path) -> Path:
    """Файл с тестовой строкой EICAR, собранной из частей (`helpers_kb.eicar_bytes`), в `tmp_path`; имя
    `eicar-test.txt` (не исполняемый тип: до ClamAV файл доходит)."""
    path = Path(tmp_path) / "eicar-test.txt"
    path.write_bytes(helpers_kb.eicar_bytes())
    return path


# --- Команды стенда (14.1, 14.2; решение 54) ----------------------------------------------------------------------

def _parse(line: str, prefix: str, keys) -> dict:
    """Строка `<prefix>: ключ=число …` → словарь; другая форма, набор ключей или нечисло — `AssertionError`."""
    assert line.startswith(prefix + ": "), f"ожидалась строка «{prefix}: …», получено: {line[:200]!r}"
    out = {}
    for part in line[len(prefix) + 2:].split():
        key, sep, value = part.partition("=")
        assert sep and re.fullmatch(r"\d+", value), f"в строке «{prefix}» часть {part[:80]!r} не вида ключ=число"
        out[key] = int(value)
    assert tuple(out) == tuple(keys), f"строка «{prefix}»: ключи {tuple(out)}, ожидались {tuple(keys)}"
    return out


def parse_shift_line(line: str) -> dict:
    """`feed_shift: shifted=<N> reminded=<M> important=<K>` → `{"shifted": N, "reminded": M, "important": K}`."""
    return _parse(line, "feed_shift", _SHIFT_KEYS)


def parse_retention_line(line: str) -> dict:
    """`feed_retention: aged=<N> deleted=<M>` → `{"aged": N, "deleted": M}`."""
    return _parse(line, "feed_retention", _RETENTION_KEYS)


def _whole(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name}: нужно целое от {low} до {high}, получено {value!r}")
    return value


def shift(minutes) -> dict:
    """`e2e_feed_shift --minutes N` (14.1) через `helpers_sd._stand_command`: сдвигает назад на N минут события
    (`event_start`, `event_end`, `remind_at`, `reminded_for_start`) и `important_until` важных записей ВСЕХ записей
    стенда, затем выполняет задание напоминаний. N — целое 1…10 080 (иначе `ValueError` до вызова). Возвращает
    `{"shifted": …, "reminded": …, "important": …}`."""
    minutes = _whole(minutes, "minutes", SHIFT_MIN, SHIFT_MAX)
    return parse_shift_line(helpers_sd._stand_command("e2e_feed_shift", "--minutes", str(minutes)))


def age(days, posts=None) -> dict:
    """`e2e_feed_retention --age-days N [--posts 12,15]` (14.2, решение 54): состаривает на N суток записи `posts`
    (номера; без `posts` — все записи стенда) и выполняет ночное удаление. N — целое 1…4000 (иначе `ValueError`).
    Возвращает `{"aged": …, "deleted": …}`."""
    days = _whole(days, "days", AGE_MIN, AGE_MAX)
    args = ["e2e_feed_retention", "--age-days", str(days)]
    if posts is not None:
        numbers = [int(p) for p in posts]
        if not numbers:
            raise ValueError("posts: пустой список (чтобы состарить все записи, не передавайте posts)")
        args += ["--posts", ",".join(str(n) for n in numbers)]
    return parse_retention_line(helpers_sd._stand_command(*args))


# --- Без WebSocket (решение 55) -----------------------------------------------------------------------------------

def _close_ws(ws) -> None:
    ws.close(reason="blocked by test")


def block_ws(context) -> None:
    """Перехват соединений `/ws/feed/` и `/ws/notify/` в `context` (`BrowserContext.route_web_socket`, Playwright
    1.63): страница получает закрытие соединения, сервер соединения не видит. Звать ДО создания страниц (маршрут
    действует на соединения, открытые после вызова). Дальше — `open_feed(context, account, live=False)`: лента
    работает обычными запросами (f08)."""
    context.route_web_socket(_WS_URL, _close_ws)


# --- Письма, колокольчик, «Мои уведомления», Telegram (готовое из прежних срезов) ---------------------------------

def feed_mail(mailpit, to: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое письмо об одном уведомлении (`notify.item`) на `to` (`helpers_notify.wait_item_mail`)."""
    return helpers_notify.wait_item_mail(mailpit, to, seen=seen, timeout=timeout)


def no_feed_mail(mailpit, to: str, *, seen=(), wait: float = 4.0) -> bool:
    """`True`, если нового письма об уведомлении на `to` за `wait` секунд нет."""
    return helpers_notify.no_item_mail(mailpit, to, seen=seen, wait=wait)


def tick_mail() -> dict:
    """Письма через 15 минут: `helpers_notify.tick(shift=15)` (решение 14 задач) — сдвигает сроки доставок на 15 минут
    и делает обход; письма шлёт рабочий процесс стенда, результат ждут в Mailpit."""
    return helpers_notify.tick(shift=15)


def bell(page) -> int:
    """Число на колокольчике `#notify-count[data-count]` (`helpers_notify.bell_count`)."""
    return helpers_notify.bell_count(page)


def wait_bell(page, expected: int, timeout: int = 4_000) -> None:
    """Ждёт число на колокольчике (`helpers_notify.wait_bell_count`)."""
    helpers_notify.wait_bell_count(page, expected, timeout_ms=timeout)


def my_notifications(page) -> list:
    """Тексты строк «Мои уведомления» (`/notifications/`, `ul[data-notifications] li[data-notification]`), новые
    сверху; страница открывается заново."""
    page.goto("/notifications/")
    page.wait_for_load_state()
    return [li.inner_text() for li in page.locator("ul[data-notifications] li[data-notification]").all()]


def fakebots() -> helpers_notify.FakeBots:
    """Учебная служба Telegram/MAX без сброса (`helpers_notify.fakebots`): сообщения — по своему `chat_id`."""
    return helpers_notify.fakebots()


# --- Узкий экран ---------------------------------------------------------------------------------------------------

def check_360(page) -> bool:
    """Окно шириной 360 px (высота прежняя) и проверка: нет горизонтальной прокрутки (`helpers.no_horizontal_scroll`).
    Нарушение — `AssertionError`; иначе возвращает `True` (годится и как `assert check_360(page)`)."""
    height = page.viewport_size["height"] if page.viewport_size else 800
    page.set_viewport_size({"width": 360, "height": height})
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")  # перерисовка
    assert helpers.no_horizontal_scroll(page), f"на ширине 360 px у {page.url} есть горизонтальная прокрутка"
    return True
