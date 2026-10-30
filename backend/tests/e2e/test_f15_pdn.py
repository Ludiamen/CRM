"""T-7154: сценарий 15 — предупреждение о персональных данных в записи, комментарии, правке и событии (FR-612).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 10.2, 12.4, 13.3, решение 47 задач):
- пишет и публикует администратор круга `admin_page` («Писать всем» у него есть; запись идёт «Всем» без выбора
  адресатов, у каждого теста свой уникальный маркер текста);
- адрес почты и телефон собираются из частей (в файле нет готовых «настоящих» значений); находки сверяются по
  узнаваемым частям: адрес — целиком, телефон — по цифрам (оформление находки — дело службы `find_plain`);
- предупреждение — `[data-feed-pdn]` ответа формы, найденное — `li[data-feed-pdn-item]`, кнопки — «Исправить»
  `button[data-action="pdn-fix"]` и «Опубликовать всё равно» (при правке — «Сохранить всё равно»)
  `button[name="pdn_confirmed"][value="1"]`; «Исправить» — действие клиента над тем же ответом, отдельного запроса нет
  (решение 47 задач): проверяется, что форма открыта с введённым текстом, а на сервере записи нет;
- пункт сценария «в комментарии и при правке записи» — тесты 4 и 5; поля события и обратные кавычки (FR-612: исключения
  для кода нет) — тесты 6 и 7;
- сброса стенда в файле нет.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers_feed as feed

MOSCOW = timezone(timedelta(hours=3))
FORM = "form#feed-form"
PDN = "[data-feed-pdn]"
ITEM = "li[data-feed-pdn-item]"
FIX = 'button[data-action="pdn-fix"]'
CONFIRM = 'button[name="pdn_confirmed"][value="1"]'


# --- Данные из частей и помощники --------------------------------------------------------------------------------

def _email() -> str:
    return "ivan" + secrets.token_hex(2) + "@" + "example" + "." + "org"


def _phone() -> str:
    return "+7 (" + "912" + ") " + "345" + "-" + "67" + "-" + "89"


PHONE_TAIL = "3456789"  # цифры телефона без «+7 (912)»: узнаваемая часть находки


def _marker() -> str:
    return f"Пдн{secrets.token_hex(4)}"


def _open_home(page) -> None:
    page.goto("/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _items_text(scope) -> str:
    items = scope.locator(ITEM)
    expect(items.first).to_be_visible()
    return " | ".join(items.all_inner_texts())


def _expect_warning(scope, *, email: str | None = None, phone: bool = False, confirm_title: str) -> None:
    """Предупреждение видно, найденное названо, есть «Исправить» и кнопка подтверждения с названием `confirm_title`."""
    warning = scope.locator(PDN)
    expect(warning.first).to_be_visible()
    found = _items_text(warning)
    if email:
        assert email in found, f"в списке найденного нет адреса: {found!r}"
    if phone:
        assert PHONE_TAIL in _digits(found), f"в списке найденного нет телефона: {found!r}"
    expect(warning.locator(FIX)).to_have_count(1)
    expect(warning.locator(FIX)).to_contain_text("Исправить")
    expect(warning.locator(CONFIRM)).to_have_count(1)
    expect(warning.locator(CONFIRM)).to_contain_text(confirm_title)


def _event(title: str, place: str) -> dict:
    start = datetime.now(MOSCOW).replace(tzinfo=None, second=0, microsecond=0) + timedelta(days=2)
    return {"title": title, "place": place, "start": start, "end": start + timedelta(hours=1)}


def _post_text_in_list(page, marker: str):
    return page.locator("#feed-list").get_by_text(marker)


# --- Запись (п. 1–3) ------------------------------------------------------------------------------------------------

def test_f15_post_with_phone_and_email_shows_warning_listing_found_with_fix_and_publish_anyway(admin_page):
    """Сценарий 15, п. 1: в тексте «звонил <телефон>, <почта>» после «Опубликовать» — предупреждение со списком найденного
    (и телефон, и адрес) и кнопками «Исправить» и «Опубликовать всё равно»; записи в ленте ещё нет (FR-612)."""
    page = admin_page
    marker, email = _marker(), _email()
    _open_home(page)
    assert feed.try_publish(page, f"{marker} звонил {_phone()}, {email}") == [], "ПДн — предупреждение, а не отказ"
    _expect_warning(page.locator(FORM), email=email, phone=True, confirm_title="Опубликовать всё равно")
    expect(_post_text_in_list(page, marker)).to_have_count(0)
    page.goto("/")
    expect(page.locator("#feed-list")).not_to_contain_text(marker)  # на сервере записи нет


def test_f15_fix_leaves_post_unpublished_and_form_open_with_entered_text(admin_page):
    """Сценарий 15, п. 2: «Исправить» — запись не опубликована, форма открыта с введённым текстом, предупреждения нет;
    после правки текста запись публикуется без предупреждения (FR-612)."""
    page = admin_page
    marker, email = _marker(), _email()
    text = f"{marker} звонил {_phone()}, {email}"
    _open_home(page)
    feed.try_publish(page, text)
    form = page.locator(FORM)
    _expect_warning(form, email=email, phone=True, confirm_title="Опубликовать всё равно")
    form.locator(FIX).click()
    expect(form).to_be_visible()
    expect(form.locator('textarea[name="text"]')).to_be_visible()
    expect(form.locator('textarea[name="text"]')).to_have_value(text)
    expect(form.locator(PDN)).to_have_count(0)
    expect(_post_text_in_list(page, marker)).to_have_count(0)
    page.goto("/")
    expect(page.locator("#feed-list")).not_to_contain_text(marker)

    # контроль: исправленный текст без находок публикуется, предупреждения нет
    _open_home(page)
    post_id = feed.publish(page, f"{marker} звонил заявитель, контакты в заявке")
    expect(page.locator(f"#feed-post-{post_id}")).to_contain_text("контакты в заявке")
    expect(page.locator(PDN)).to_have_count(0)


def test_f15_publish_anyway_publishes_post(admin_page):
    """Сценарий 15, п. 3: «Опубликовать всё равно» — запись опубликована, остаётся после перезагрузки (FR-612)."""
    page = admin_page
    marker, email = _marker(), _email()
    _open_home(page)
    post_id = feed.publish(page, f"{marker} звонил {_phone()}, {email}", confirm_pdn=True)
    expect(page.locator(f"#feed-post-{post_id}")).to_contain_text(marker)
    expect(page.locator(f"#feed-post-{post_id}")).to_contain_text(email)
    page.goto("/")
    expect(page.locator(f"#feed-post-{post_id}")).to_have_count(1)


# --- Комментарий и правка (п. 4) ---------------------------------------------------------------------------------

def test_f15_comment_with_phone_or_email_shows_same_warning_and_publish_anyway_publishes_comment(admin_page):
    """Сценарий 15, п. 4: комментарий с телефоном и комментарий с адресом — то же предупреждение (список найденного,
    «Исправить», «Опубликовать всё равно»); пока не подтверждено, комментария нет; «Опубликовать всё равно» его
    публикует (FR-612)."""
    page = admin_page
    marker = _marker()
    _open_home(page)
    post_id = feed.publish(page, f"{marker} запись без ПДн")
    scope = page.locator(f"#feed-post-{post_id}")
    comments = scope.locator("[data-comment-id]")

    email = _email()
    assert feed.try_comment(page, post_id, f"{marker} пишите на {email}") == []
    form = scope.locator("form[data-feed-comment-form]").first
    _expect_warning(form, email=email, confirm_title="Опубликовать всё равно")
    expect(comments).to_have_count(0)
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/comments/" in r.url):
        form.locator(CONFIRM).click()
    expect(comments).to_have_count(1)
    expect(comments.first).to_contain_text(email)

    assert feed.try_comment(page, post_id, f"{marker} звоните {_phone()}") == []
    form = scope.locator("form[data-feed-comment-form]").first
    _expect_warning(form, phone=True, confirm_title="Опубликовать всё равно")
    form.locator(FIX).click()
    expect(form.locator('textarea[name="text"]')).to_have_value(f"{marker} звоните {_phone()}")
    expect(comments).to_have_count(1)  # «Исправить» второй комментарий не публикует
    assert feed.try_comment(page, post_id, f"{marker} звоните {_phone()}") == []
    form = scope.locator("form[data-feed-comment-form]").first
    _expect_warning(form, phone=True, confirm_title="Опубликовать всё равно")
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/comments/" in r.url):
        form.locator(CONFIRM).click()
    expect(comments).to_have_count(2)


def test_f15_post_edit_adding_email_shows_warning_with_save_anyway_which_saves(admin_page):
    """Сценарий 15, п. 4: автор правит запись и добавляет в текст адрес почты — предупреждение с «Исправить» и
    «Сохранить всё равно» (кнопки «Опубликовать всё равно» нет); «Сохранить всё равно» сохраняет правку (FR-612)."""
    page = admin_page
    marker, email = _marker(), _email()
    _open_home(page)
    post_id = feed.publish(page, f"{marker} исходный текст")

    page.goto(f"/feed/{post_id}/edit/")
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="edit"] form').first
    form.locator('textarea[name="text"]').fill(f"{marker} исходный текст, почта {email}")
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        form.locator('button:not([type="button"])').first.click()
    scope = page.locator('[data-feed-page="edit"]')
    _expect_warning(scope, email=email, confirm_title="Сохранить всё равно")
    expect(scope.get_by_role("button", name="Опубликовать всё равно")).to_have_count(0)
    page.goto(f"/feed/{post_id}/")  # без подтверждения правка не сохранена
    expect(page.locator(f"#feed-post-{post_id}-body")).not_to_contain_text(email)

    page.goto(f"/feed/{post_id}/edit/")
    form = page.locator('[data-feed-page="edit"] form').first
    form.locator('textarea[name="text"]').fill(f"{marker} исходный текст, почта {email}")
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        form.locator('button:not([type="button"])').first.click()
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        page.locator('[data-feed-page="edit"]').locator(CONFIRM).click()
    page.goto(f"/feed/{post_id}/")
    expect(page.locator(f"#feed-post-{post_id}-body")).to_contain_text(email)


# --- Событие и обратные кавычки ----------------------------------------------------------------------------------

def test_f15_email_or_phone_in_event_title_or_place_shows_warning(admin_page):
    """FR-612: адрес в названии события и телефон в месте события — то же предупреждение (текст записи пуст);
    контроль — событие без находок публикуется без предупреждения."""
    page = admin_page
    word = secrets.token_hex(3)
    _open_home(page)
    control = feed.publish(page, "", kind="event", event=_event(f"Собрание {word}", "Переговорная"))
    expect(page.locator(f"#feed-post-{control}")).to_be_visible()
    expect(page.locator(PDN)).to_have_count(0)

    email = _email()
    _open_home(page)
    assert feed.try_publish(page, "", kind="event", event=_event(f"Собрание {word}, пишите {email}", "Переговорная")) == []
    _expect_warning(page.locator(FORM), email=email, confirm_title="Опубликовать всё равно")

    _open_home(page)
    assert feed.try_publish(page, "", kind="event", event=_event(f"Встреча {word}", f"кабинет, звонить {_phone()}")) == []
    _expect_warning(page.locator(FORM), phone=True, confirm_title="Опубликовать всё равно")
    page.goto("/")
    expect(page.locator("#feed-list")).not_to_contain_text(f"Встреча {word}")
    expect(page.locator("#feed-list")).not_to_contain_text("пишите")


def test_f15_email_inside_backticks_still_shows_warning(admin_page):
    """FR-612: исключения для кода нет — адрес в обратных кавычках (в строке и в блоке из трёх кавычек) тоже даёт
    предупреждение; записи нет, пока не подтверждено."""
    page = admin_page
    marker, email = _marker(), _email()
    tick = "`"
    for text in (f"{marker} пример: {tick}{email}{tick}",
                 f"{marker} блок:\n{tick * 3}\n{email}\n{tick * 3}"):
        _open_home(page)
        assert feed.try_publish(page, text) == []
        _expect_warning(page.locator(FORM), email=email, confirm_title="Опубликовать всё равно")
    page.goto("/")
    expect(page.locator("#feed-list")).not_to_contain_text(marker)
