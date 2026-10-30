"""T-7153: сценарий 14 — главная: лента и блок напоминаний модулей, меню, узкий экран (FR-601, FR-641, NFR-606).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 10.2, 12, 13, решения 36 и 62 задач):
- пункт 4 сценария (модуль выключен — прежняя главная) приёмка не проходит: выключение модуля на стенде означает
  пересборку; это серверные тесты T-7104 и T-7137 (`without_feed()`); пункт «3» (360 px) разложен на три теста;
- напоминание модуля на главной — настоящее напоминание, которое выдаёт стенд: календарь (`org`, `home_notices`:
  «Не загружен производственный календарь на {год} год»; готовится как в `test_o11_calendar`). Напоминания о сроке записи
  списка среди `home_notices` нет — срок записи списка приходит уведомлением на колокольчик (T-7143 среза 006), поэтому
  имя теста про «срок в записи списка» проверяет то, что в нём сказано о месте блока: любое напоминание модуля стоит
  блоком над формой записи и лентой (вопрос Opus в итоге T-7153);
- «над формой и лентой» — порядок в разметке (`compareDocumentPosition`) и по высоте на странице;
- на ширине 360 px — `helpers_feed.check_360` (нет горизонтальной прокрутки страницы); окно меняется в тесте после
  открытия страницы, дальше идут действия на узком экране;
- для 360 px нужны люди и записи: сотрудники `employee`, действия «Нравится» и «Пойду» — прямые запросы тех же форм
  (`helpers_org.direct_post` с токеном CSRF страницы сотрудника), публикация, файл и «Нравится» администратора — формой;
- ПДн и адреса в данных не используются; общая часть имён уникальна на круг;
- сброса стенда в файле нет.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed as feed, helpers_org

MOSCOW = timezone(timedelta(hours=3))
FORM = "form#feed-form"


# --- Общие помощники файла ------------------------------------------------------------------------------------

def _marker() -> str:
    return f"Главная{secrets.token_hex(4)}"


def _word() -> str:
    """Уникальное слово из букв (поиск идёт по словам с приставкой): латиница и цифры в `to_tsquery` вели бы себя иначе."""
    return "лента" + "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(10))


def _reset_calendar_year(year: int) -> None:
    """Год календаря не загружен (напоминание `calendar-year` у обладателя «Рабочий календарь»): подготовка через
    `stand_shell`, как `_stand_reset_years` в `test_o11_calendar`."""
    helpers.stand_shell(
        "import redis\n"
        "from datetime import time\n"
        "from django.apps import apps\n"
        "from django.conf import settings\n"
        f"years = {[year]!r}\n"
        "apps.get_model('org.SpecialDay').objects.filter(date__year__in=years).delete()\n"
        "apps.get_model('org.CalendarYear').objects.filter(year__in=years).delete()\n"
        "apps.get_model('org.CalendarUpload').objects.filter(year__in=years).delete()\n"
        "apps.get_model('org.WorkCalendar').objects.update(work_weekdays=[0, 1, 2, 3, 4], "
        "day_start=time(9, 0), day_end=time(18, 0))\n"
        "r = redis.Redis.from_url(settings.VALKEY_URL)\n"
        "for k in list(r.scan_iter('*calendar:marks:*')):\n"
        "    r.delete(k)\n"
        "for k in list(r.scan_iter('*calendar:version')):\n"
        "    r.incr(k)\n"
        "print('ok')\n")


def _open_home(page) -> None:
    page.goto("/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()


def _event() -> dict:
    start = datetime.now(MOSCOW).replace(tzinfo=None, second=0, microsecond=0) + timedelta(days=2)
    return {"title": f"Событие {secrets.token_hex(3)}", "place": "Переговорная", "start": start,
            "end": start + timedelta(hours=1)}


def _surname(account) -> str:
    return account.full_name.split()[0]


def _post_ok(page, path: str, data: dict | None = None) -> None:
    response = helpers_org.direct_post(page, path, data)
    assert response.status == 302, f"{path}: ожидался 302, получен {response.status}"


# --- Главная и меню (п. 1, 2; FR-601, FR-641) ------------------------------------------------------------------

def test_f14_list_record_deadline_reminder_stands_as_block_above_post_form_and_feed(admin_page):
    """Сценарий 14, п. 1: у сотрудника есть напоминание модуля — на главной оно стоит блоком `[data-home-notices]` над
    формой записи и лентой (FR-601). Напоминание — календарь «Не загружен производственный календарь» (см. шапку)."""
    page = admin_page
    year = datetime.now(MOSCOW).year
    _reset_calendar_year(year)
    _open_home(page)
    notice = page.locator(f'[data-home-notices] [data-notice="calendar-year"][data-year="{year}"]')
    expect(notice).to_have_count(1)
    expect(notice).to_contain_text(f"Не загружен производственный календарь на {year} год.")
    order = page.evaluate("""() => {
        const nodes = ['[data-home-notices]', 'form#feed-form', '#feed-list'].map(s => document.querySelector(s));
        if (nodes.some(n => !n)) return null;
        const top = n => n.getBoundingClientRect().top + window.scrollY;
        const follows = (a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
        return {tops: nodes.map(top), dom: [follows(nodes[0], nodes[1]), follows(nodes[1], nodes[2])]};
    }""")
    assert order, "на главной нет блока напоминаний, формы записи или ленты"
    assert order["dom"] == [True, True], f"порядок в разметке: напоминания → форма → лента, получено {order['dom']}"
    assert order["tops"][0] < order["tops"][1] < order["tops"][2], f"порядок на странице: {order['tops']}"


def test_f14_feed_menu_item_is_first_leads_to_home_and_home_item_is_absent(employee, new_context):
    """Сценарий 14, п. 2: в меню пункт «Лента» стоит первым и ведёт на главную `/`; пункта «Главная» нет (FR-601,
    FR-641)."""
    staff = employee()
    page = feed.open_feed(new_context(), staff)
    items = page.locator("#main-menu a.menu-item")
    expect(items.first).to_have_attribute("href", "/")
    expect(items.first).to_contain_text("Лента")
    titles = [t.strip() for t in items.evaluate_all("els => els.map(e => e.innerText)")]
    assert all("Главная" not in t for t in titles), f"в меню есть пункт «Главная»: {titles}"
    assert len([t for t in titles if "Лента" in t]) == 1, f"пункт «Лента» не один: {titles}"
    expect(page.locator('#main-menu a.menu-item[href="/"]')).to_have_count(1)

    page.goto("/me/")
    page.locator("#main-menu a.menu-item").first.click()
    page.wait_for_url(re.compile(r"^https?://[^/]+/$"))
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()


def test_f14_home_with_feed_has_no_greeting_and_profile_security_and_section_cards(employee, new_context):
    """Сценарий 14, п. 1–2: главная с лентой — без приветствия, без карточек «Мой профиль», «Безопасность» и карточек
    разделов; форма записи и лента на месте (FR-601, FR-641)."""
    staff = employee()
    page = feed.open_feed(new_context(), staff)
    expect(page.locator(FORM)).to_be_visible()
    expect(page.locator("#feed-list, [data-empty-state=feed]").first).to_be_attached()
    root = page.locator('[data-feed-page="home"]')
    expect(page.locator("body")).not_to_contain_text("Здравствуйте")
    expect(page.locator("body")).not_to_contain_text("Добро пожаловать")
    for card in ("Мой профиль", "Безопасность"):
        expect(root.get_by_role("heading", name=card)).to_have_count(0)
    expect(root.locator('a[href="/me/"], a[href="/me/security/"]')).to_have_count(0)
    expect(root.locator("a.card")).to_have_count(0)


def test_f14_home_without_login_leads_to_login_and_back_to_feed_by_next(employee, new_context):
    """Сценарий 14 (FR-601): главная без входа ведёт на `/login/?next=/`; после входа (почта, пароль, код) возврат на
    главную с лентой."""
    account = employee()
    page = new_context().new_page()
    page.goto("/")
    page.wait_for_url(re.compile(r"/login/"))
    assert "next=" in page.url, f"в адресе входа нет next: {page.url}"
    expect(page.locator('[data-feed-page="home"]')).to_have_count(0)
    page.fill("input[name=email]", account.email)
    page.fill("input[name=password]", account.password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/login/code/"))
    page.fill("input[name=code]", helpers.totp_for(account.totp_secret))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"^https?://[^/]+/$"))
    expect(page.locator('[data-feed-page="home"]')).to_be_visible()
    expect(page.locator(FORM)).to_be_visible()


# --- Узкий экран (п. 3; NFR-606) ----------------------------------------------------------------------------------

def test_f14_feed_post_card_and_post_form_with_recipients_do_not_widen_page_at_360px(admin_page, employee):
    """Сценарий 14, п. 3: на 360 px лента, форма записи с выбранными адресатами (подразделение и человек), карточка
    записи в ленте и страница карточки `/feed/<id>/` — без горизонтальной прокрутки (NFR-606)."""
    page = admin_page
    token = secrets.token_hex(3)
    person = employee(full_name=f"Адресатов{token} Иван Иванович")
    helpers_org.open_structure(page)
    unit_name = helpers_org.unique_name("Отдел")
    unit_id = helpers_org.create_unit(page, unit_name, kind="department", parent_id=helpers_org.root_id(page))
    helpers_org.add_members(page, unit_id, [person.id], q=token, mode="concurrent")

    _open_home(page)
    assert feed.check_360(page), "лента на 360 px"
    feed.pick_to(page, unit_name, unit_name)
    feed.pick_to(page, _surname(person), person.full_name)
    expect(page.locator(f"{FORM} [data-to-pill]")).to_have_count(3)  # «Всем» стоит у администратора с начала
    assert feed.check_360(page), "форма с адресатами на 360 px"
    post_id = feed.publish(page, f"{_marker()} запись для узкого экрана")
    assert feed.check_360(page), "лента с карточкой записи на 360 px"
    page.goto(f"/feed/{post_id}/")
    expect(page.locator('[data-feed-page="card"]')).to_be_visible()
    assert feed.check_360(page), "страница карточки на 360 px"


def test_f14_event_block_likers_list_and_search_results_do_not_widen_page_at_360px(admin_page, employee):
    """Сценарий 14, п. 3: на 360 px блок события, список ответивших, полный список отметивших «Нравится» и выдача
    сквозного поиска — без горизонтальной прокрутки (NFR-606)."""
    page = admin_page
    word = _word()
    guests = [employee(full_name=f"Гостев{secrets.token_hex(3)} Иван Иванович") for _ in range(3)]
    _open_home(page)
    post_id = feed.publish(page, f"{word} событие для узкого экрана", kind="event", event=_event())
    for guest in guests:
        _post_ok(guest.page, f"/feed/{post_id}/answer/", {"answer": "go"})
        _post_ok(guest.page, f"/feed/{post_id}/like/")
    assert feed.like(page, post_id) is True  # четвёртый: «ФИО, ФИО и ещё 2»

    page.goto(f"/feed/{post_id}/")
    expect(page.locator('[data-feed-page="card"]')).to_be_visible()
    assert feed.check_360(page), "блок события на 360 px"
    event = page.locator(f"#feed-post-{post_id}-event")
    expect(event).to_be_visible()
    expect(event.locator('[data-feed-answers-count="go"]')).to_contain_text("3")
    event.locator("a[data-feed-answers-link]").click()
    expect(page.locator('ul[data-feed-list="answers"]')).to_be_visible()
    assert feed.check_360(page), "список ответивших на 360 px"
    likers = page.locator(f'#feed-post-{post_id}-likers a[hx-get*="/likes/"]')
    expect(likers).to_have_count(1)
    likers.click()
    expect(page.locator('ul[data-feed-list="likers"]')).to_be_visible()
    assert feed.check_360(page), "список отметивших на 360 px"

    page.goto(f"/search/?q={word}")
    group = page.locator('section[data-search-group="feed"]')
    expect(group).to_be_visible()
    expect(group).to_contain_text(word)
    assert feed.check_360(page), "выдача поиска на 360 px"


def test_f14_long_link_and_long_name_wrap_and_thumbnail_fits_width_at_360px(employee, admin_page, new_context, tmp_path):
    """Сценарий 14, п. 3: на 360 px длинная ссылка без пробелов, ФИО автора, название подразделения в «Кому» переносятся,
    а эскиз широкой картинки не шире окна — страница без горизонтальной прокрутки (NFR-606)."""
    page = admin_page
    long_unit = helpers_org.unique_name("Подразделение" + "Длиннейшее" * 6)
    helpers_org.open_structure(page)
    helpers_org.create_unit(page, long_unit, kind="department", parent_id=helpers_org.root_id(page))
    author = employee(full_name=f"{'Длиннофамильный' * 4}{secrets.token_hex(3)} {'Длинноимённый' * 3} Иванович")
    png = tmp_path / "wide.png"
    png.write_bytes(helpers.make_png(2400, 1600))

    author_page = feed.open_feed(new_context(), author)
    assert feed.check_360(author_page)
    link = "https://example.org/" + "a" * 400
    post_id = feed.publish(author_page, f"{_marker()} {link} {'Словобезпробелов' * 12}",
                           to=[("unit", long_unit)], files=(png,))
    file_id = author_page.locator(f"#feed-post-{post_id}-files [data-feed-file]").first.get_attribute("data-feed-file")
    feed.wait_clean(author_page, file_id)
    assert feed.check_360(author_page), "лента с длинными значениями на 360 px"
    thumb = author_page.locator(f'#feed-post-{post_id}-files a[href="/feed/files/{file_id}/"] > img[src="/feed/files/{file_id}/thumb/"]')
    expect(thumb).to_be_visible()
    box = thumb.bounding_box()
    assert box and box["x"] + box["width"] <= 360 + 1, f"эскиз выходит за окно 360 px: {box}"

    author_page.goto(f"/feed/{post_id}/")
    expect(author_page.locator('[data-feed-page="card"]')).to_be_visible()
    assert feed.check_360(author_page), "карточка с длинными значениями на 360 px"
