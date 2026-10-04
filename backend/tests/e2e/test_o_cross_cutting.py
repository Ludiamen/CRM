"""T-2149: сквозная приёмка среза 002 — ширина 360 px, фото через nginx, русский язык и время по Москве
(FR-132, NFR-104, NFR-107).

Серверную разметку (viewport, lang) проверяет T-2121; здесь — настоящий стенд с nginx и браузерами.
"""
import csv
import io
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers
from tests.e2e.helpers_org import (add_members, calendar_fixture, create_unit, direct_get, unique_name,
                                   upload_file, wait_photo_checked)

MOSCOW = ZoneInfo("Europe/Moscow")
PHOTO_URL = re.compile(r"^/staff/(\d+)/photo/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/(512|96)/$")
UI_TEXT_SELECTOR = "h1, h2, h3, label, legend, button, th, [data-field-label]"
# пользовательские данные (CONTRACT-002 § 9): названия узлов, участники, ФИО, значения полей, роли, кандидаты
USER_DATA_SELECTOR = ("[data-unit-tree], [data-member], [data-unit-name], [data-person-name], [data-field], "
                      "[data-role-name], [data-candidate]")
MIN_UI_LETTERS = 20
JPEG_MAGIC = b"\xff\xd8\xff"


def _cyrillic_share(text: str) -> float:
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    if not letters:
        return 0.0
    return sum(1 for c in letters if re.match(r"[А-Яа-яЁё]", c)) / len(letters)


def _ui_text(page, selector: str) -> str:
    """Текст элементов интерфейса без пользовательских данных: пропускаются элементы внутри блоков с данными,
    а также заголовки, в которых стоит название узла или имя человека."""
    texts = page.evaluate(
        """([selector, exclude]) => Array.from(document.querySelectorAll(selector))
            .filter(el => !el.closest(exclude) && !el.querySelector('[data-unit-name], [data-person-name]'))
            .map(el => el.innerText)""",
        [selector, USER_DATA_SELECTOR])
    return " ".join(texts)


def _staff_csv() -> bytes:
    """Файл сотрудников (CSV, UTF-8 с BOM, `;`): годная строка и строка с ошибкой почты и фамилии. Собран здесь,
    потому что `tests.support_org` при импорте тянет django (приёмка идёт с хоста)."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Почта", "Фамилия", "Имя", "Должность"])
    writer.writerow([factories.new_email("narrow"), "Тестов", "Тест", "Инженер"])
    writer.writerow(["not-an-address", "", "Тест", "Инженер"])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def test_slice_pages_no_horizontal_scroll_at_360px(browser, browser_context_args, admin_page, employee):
    """Сквозная приёмка, NFR-104: на ширине 360 px у всех страниц среза нет горизонтальной прокрутки —
    «Структура» (дерево и карточка узла идут друг под другом, меню «…» участника открыто), формы узла,
    загрузка сотрудников и её предпросмотр, «Календарь», загрузка календаря и её предпросмотр, список
    «Сотрудники», карточка сотрудника и «Мой профиль» (NFR-104)."""
    suffix = secrets.token_hex(3)
    person = employee(full_name=f"Узкий{suffix} Сотрудник")
    long_name = (unique_name("Узел") + " Подразделение с очень длинным названием для проверки переноса слов "
                 "на узком экране телефона")[:140]
    unit_id = create_unit(admin_page, long_name, kind="department")
    add_members(admin_page, unit_id, [person.id], q=f"Узкий{suffix}", mode="concurrent")

    narrow = browser.new_context(**browser_context_args, viewport={"width": 360, "height": 740},
                                 storage_state=admin_page.context.storage_state())
    try:
        page = narrow.new_page()
        # «Структура»: дерево и карточка узла
        page.goto(f"/structure/{unit_id}/")
        expect(page.locator("[data-structure-layout]")).to_be_visible()
        expect(page.locator(f'#unit-card [data-unit-card][data-unit-id="{unit_id}"]')).to_be_visible()
        assert helpers.no_horizontal_scroll(page), "/structure/<id>/: горизонтальная прокрутка"
        tree = page.locator("[data-unit-tree]").bounding_box()
        card = page.locator("#unit-card").bounding_box()
        assert tree and card, "дерево или карточка узла не показаны"
        assert card["y"] >= tree["y"] + tree["height"] - 1, "на 360 px карточка узла не под деревом"
        page.locator("[data-member-menu-button]").first.click()
        expect(page.locator("[data-menu-item]").first).to_be_visible()
        assert helpers.no_horizontal_scroll(page), "/structure/<id>/: открытое меню «…», горизонтальная прокрутка"

        for path in ("/structure/", "/structure/new/", f"/structure/{unit_id}/edit/", "/structure/import/",
                     "/calendar/", "/calendar/upload/", "/staff/", f"/staff/{person.id}/", "/me/"):
            page.goto(path)
            expect(page.locator("main, body").first).to_be_visible()
            assert helpers.no_horizontal_scroll(page), f"{path}: горизонтальная прокрутка"

        # предпросмотр загрузки сотрудников (ничего не создаёт, подтверждения нет)
        page.goto("/structure/import/")
        upload_file(page.locator('form:has(input[type=file][name=file])'), _staff_csv(), name="staff.csv",
                    mime="text/csv")
        page.wait_for_url(re.compile(r"/structure/import/\d+/"))
        assert helpers.no_horizontal_scroll(page), "предпросмотр загрузки сотрудников: горизонтальная прокрутка"

        # предпросмотр загрузки календаря (без подтверждения: календарь стенда не меняется)
        page.goto("/calendar/upload/")
        form = page.locator('form[data-form="calendar-upload"]')
        form.locator("input[name=year]").fill("2026")
        upload_file(form, calendar_fixture("cal2026.csv"), name="cal2026.csv", mime="text/csv")
        page.wait_for_url(re.compile(r"/calendar/upload/\d+/"))
        expect(page.locator("[data-calendar-preview]")).to_be_visible()
        assert helpers.no_horizontal_scroll(page), "предпросмотр календаря: горизонтальная прокрутка"
    finally:
        narrow.close()


def test_photo_headers_from_nginx_and_protected_not_reachable_directly(employee, new_context):
    """FR-132 (§ 8.2, доп. 41): чистое фото отдаёт nginx по `X-Accel-Redirect` — с типом `image/jpeg`,
    `nosniff`, `Cache-Control: private, max-age=86400` и настоящим JPEG в теле; другие страницы остаются
    `no-store`; прямой адрес `/protected/…` снаружи недоступен (вошедшему и гостю); чужой номер, неверный
    размер и неизвестный uuid — 404 после входа; гость на адрес фото — на вход, без байтов."""
    owner = employee()
    colleague = employee()
    page = owner.page

    # п. 1: свою фотографию загружает сам сотрудник; после проверки она чистая
    page.goto("/me/")
    form = page.locator("form:has(input[type=file][name=photo])")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith("/me/photo")):
        upload_file(form, helpers.make_png(300, 300), field="photo", name="photo.png", mime="image/png")
    assert wait_photo_checked(page) == "clean", "фото не прошло проверку на стенде"
    src = page.locator("[data-card] img[data-photo-img]").first.get_attribute("src")
    found = PHOTO_URL.match(src or "")
    assert found, f"адрес фото в карточке не по § 8.2: {src}"
    user_id, photo_id = found.group(1), found.group(2)
    assert user_id == owner.id

    # п. 2: ответ браузеру — заголовки nginx и настоящий JPEG, для владельца и для коллеги
    for who, label in ((page, "владелец"), (colleague.page, "коллега")):
        for size in ("512", "96"):
            url = f"/staff/{user_id}/photo/{photo_id}/{size}/"
            response = who.request.get(url, max_redirects=0)
            assert response.status == 200, f"{label}, {size}: статус {response.status}"
            headers = {k.lower(): v for k, v in response.headers.items()}
            assert headers.get("content-type", "").split(";")[0].strip() == "image/jpeg", f"{label}, {size}: тип"
            assert headers.get("x-content-type-options") == "nosniff", f"{label}, {size}: нет nosniff"
            cache = headers.get("cache-control", "")
            assert "private" in cache and "max-age=86400" in cache and "no-store" not in cache, \
                f"{label}, {size}: Cache-Control {cache!r}"
            assert response.body().startswith(JPEG_MAGIC), f"{label}, {size}: в теле нет JPEG (отдал не nginx?)"
    assert "no-store" in page.request.get("/me/").headers.get("cache-control", ""), \
        "исключение из no-store вышло за пределы маршрута фото"

    # п. 3: журнал доступа nginx — запрос фото прошёл, тело не пустое (после внутреннего перехода адрес — /protected/…)
    log = helpers.nginx_access_log()
    assert re.search(rf"GET /protected/photos/{photo_id}-512\.jpg 200 [1-9]\d*", log), \
        "в журнале доступа nginx нет успешной отдачи фото"

    # п. 4: прямой адрес тома снаружи не отдаётся — ни вошедшему, ни гостю
    guest = new_context().new_page()
    for path in (f"/protected/photos/{photo_id}-512.jpg", f"/protected/photos/{photo_id}-96.jpg", "/protected/",
                 "/protected/incoming/"):
        for who, label in ((page, "вошедший"), (guest, "гость")):
            response = who.request.get(path, max_redirects=0)
            assert response.status == 404, f"{label}: {path} вернул {response.status}"
            assert not response.body().startswith(JPEG_MAGIC), f"{label}: {path} отдал файл"

    # п. 5: гость на адрес фото — на вход, байтов нет; неверные размер, uuid и номер — 404 без подробностей
    response = guest.request.get(f"/staff/{user_id}/photo/{photo_id}/512/", max_redirects=0)
    assert response.status == 302 and "/login/" in response.headers.get("location", "")
    assert not response.body().startswith(JPEG_MAGIC)
    other_uuid = "00000000-0000-4000-8000-" + secrets.token_hex(6)
    for path in (f"/staff/{user_id}/photo/{photo_id}/256/", f"/staff/{user_id}/photo/{other_uuid}/512/",
                 f"/staff/{colleague.id}/photo/{photo_id}/512/"):
        response = direct_get(page, path)
        assert response.status == 404, f"{path}: {response.status}"
        body = response.text()
        for banned in ("Traceback", "DoesNotExist", "matching query"):
            assert banned not in body, f"{path}: в теле 404 есть {banned}"


def test_slice_pages_russian_and_moscow_time_in_browser(browser, browser_context_args, admin_page):
    """Сквозная приёмка, NFR-107: страницы среза по-русски (`lang="ru"`, русские названия месяцев и дней
    недели, нет английских служебных слов, 404 без чужих слов), а время события в журнале показано по Москве
    даже при часовом поясе браузера America/New_York (NFR-107; разметку на сервере проверяет T-2121)."""
    unit_name = unique_name("Узел")
    context = browser.new_context(**{**browser_context_args, "timezone_id": "America/New_York",
                                     "storage_state": admin_page.context.storage_state()})
    try:
        page = context.new_page()
        # п. 1: язык страниц среза
        too_few_letters = []
        for path in ("/structure/", "/structure/new/", "/structure/import/", "/calendar/", "/calendar/upload/",
                     "/staff/", "/me/"):
            page.goto(path)
            assert page.locator("html").get_attribute("lang") == "ru", f"{path}: нет lang=ru"
            # только элементы интерфейса: без данных пользователей (имён узлов, ФИО, почты)
            ui_selector = "th" if path == "/staff/" else UI_TEXT_SELECTOR
            text = _ui_text(page, ui_selector)
            if path != "/staff/":  # в списке много адресов почты латиницей
                if len(re.findall(r"[A-Za-zА-Яа-яЁё]", text)) < MIN_UI_LETTERS:
                    too_few_letters.append(path)  # слишком мало подписей для доли — проверка пропущена
                else:
                    assert _cyrillic_share(text) > 0.6, f"{path}: страница не по-русски"
            assert not re.search(r"\b(Submit|Save|Cancel|Delete|Loading|Traceback|Not Found)\b", text), \
                f"{path}: английские служебные слова"
        assert len(too_few_letters) <= 1, \
            f"доля кириллицы не проверена (меньше {MIN_UI_LETTERS} букв подписей) на страницах: {too_few_letters}"
        page.goto("/staff/")
        headers = " ".join(page.locator("th").all_inner_texts())
        assert headers.strip() and _cyrillic_share(headers) > 0.8, "заголовки списка «Сотрудники» не по-русски"
        page.goto("/calendar/")
        expect(page.locator("[data-month]")).to_have_count(12)
        month_text = page.locator('[data-month="1"]').inner_text().lower()
        assert "январ" in month_text, "название месяца в календаре не по-русски"
        assert [t.strip() for t in page.locator('[data-month="1"] thead th').all_inner_texts()] == \
            ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        response = direct_get(page, "/structure/999999999/")
        assert response.status == 404 and _cyrillic_share(response.text()) > 0.5, "страница 404 не по-русски"

        # п. 2: время события журнала — по Москве
        unit_id = create_unit(page, unit_name, kind="department")
        now = datetime.now(MOSCOW)
        page.goto(f"/audit/?action=unit.created&object_id={unit_id}")
        row = page.locator('tr[data-event-id][data-action="unit.created"]').first
        expect(row).to_be_visible()
        times = re.findall(r"\b(\d{2}):(\d{2})\b", row.inner_text())
        assert times, "в строке журнала нет времени"
        shown = now.replace(hour=int(times[0][0]), minute=int(times[0][1]), second=0, microsecond=0)
        assert abs(shown - now) < timedelta(minutes=10) or abs(shown - now) > timedelta(hours=23, minutes=50), \
            f"время события не по Москве: {times[0][0]}:{times[0][1]}, по Москве сейчас {now:%H:%M}"
    finally:
        context.close()

