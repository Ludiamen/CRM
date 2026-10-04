"""T-2121: общие правила страниц среза (FR-108, FR-123, FR-132, FR-146, NFR-104, NFR-107).

Сценарии 1, 9, 10, 11, 12 спеки. Проверяется то, что общо для всех страниц среза: `meta viewport` и
контейнер раскладки (раскладку на 360 px проверяет Playwright, T-2142/T-2149), русский интерфейс и время
по Москве, фрагмент для HTMX и полная страница для обычного запроса, CSRF и порядок отказов 302/403/404
без подробностей, `Cache-Control: no-store` везде, кроме выдачи фото, и напоминание о календаре только
обладателю `calendar.manage`. Контракт: CONTRACT-002 § 8, 8.2, 9.1, 9.5, § 11 (решение C7).
Помощники держатся внутри файла; общие файлы не правятся.
"""
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.conf import settings
from django.utils import timezone

from tests import support, support_org
from tests.support import HX, model

pytestmark = pytest.mark.django_db

VOID = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}
ALL_RIGHTS = ("staff.view", "org.manage", "calendar.manage", "accounts.manage", "roles.manage")
VIEWPORT = "width=device-width, initial-scale=1"


# --- помощники файла --------------------------------------------------------------------------

class Element:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.text, self.parent = tag, dict(attrs), "", None

    def inside(self, other):
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


class Page(HTMLParser):
    """Плоский разбор: все элементы по порядку; текст элемента включает текст потомков."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = Element(tag, attrs)
        el.parent = self._stack[-1] if self._stack else None
        self.elements.append(el)
        if tag not in VOID:
            self._stack.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.text += data

    def find(self, tag=None, **attrs):
        """`find("li", data_unit_id="5")`; значение `True` — «атрибут есть»; `_` в имени — дефис."""
        out = []
        for el in self.elements:
            if tag and el.tag != tag:
                continue
            ok = True
            for key, want in attrs.items():
                name = key.replace("_", "-")
                if want is True:
                    ok = ok and name in el.attrs
                else:
                    ok = ok and el.attrs.get(name) == want
            if ok:
                out.append(el)
        return out


def page(response) -> Page:
    return Page(response.content.decode())


def manager(*extra):
    """Сотрудник со всеми правами среза (и с `extra`)."""
    return support.make_with_permissions(*ALL_RIGHTS, *extra)


def moscow_today() -> date:
    return timezone.localdate()


def load_year(year: int, user):
    """Год календаря «загружен» (строка `CalendarYear`, план: «Модель данных»)."""
    return model("org.CalendarYear").objects.create(
        year=year, loaded_by=user, loaded_at=timezone.now(), file_name=f"cal{year}.csv",
        totals={"holidays_on_weekdays": 0, "moved_days_off": 0, "moved_workdays": 0, "short_days": 0,
                "work_days": 247})


def has_viewport(parsed: Page) -> bool:
    return any(m.attrs.get("name") == "viewport" and m.attrs.get("content") == VIEWPORT
               for m in parsed.find("meta"))


def slice_pages(unit, user):
    """Страницы среза, открываемые GET с полным набором прав: путь -> (нужен ли контейнер раскладки)."""
    from apps.org.services import calendar_file, staff_import

    load_year(moscow_today().year, user)
    calendar_preview = calendar_file.make_preview(
        support_org.calendar_fixture("cal2027.csv"), year=2027, file_name="cal2027.csv", actor=user)
    staff_preview = staff_import.make_preview(
        support_org.staff_csv([support_org.staff_row()]), file_name="people.csv", actor=user)
    return {
        "/structure/": True,
        f"/structure/{unit.pk}/": True,
        "/structure/new/": False,
        f"/structure/{unit.pk}/edit/": False,
        "/structure/import/": False,
        "/calendar/": False,
        "/calendar/upload/": False,
        f"/calendar/days/{moscow_today().isoformat()}/": False,
        f"/structure/import/{staff_preview.pk}/": False,
        f"/calendar/upload/{calendar_preview.pk}/": False,
    }


def make_clean_photo(user):
    """Чистое фото через ORM (файлы на диске выдаче не нужны: ответ — заголовок `X-Accel-Redirect`)."""
    stored = model("core.StoredFile").objects.create(
        owner=user, purpose="photo", status="clean", content_type="image/jpeg", size=100, sha256="0" * 64,
        scanned_at=timezone.now())
    model("core.User").objects.filter(pk=user.pk).update(photo=stored)
    return stored


def assert_no_details(text: str, where: str):
    """Страницы 403 и 404 без подробностей (FR-123, доп. 42 к CONTRACT-002)."""
    for leak in ("Traceback", "DoesNotExist", "matching query", "org_unit", "org_membership", "SELECT", "CSRF",
                 "org.manage", "calendar.manage", "staff.view", "accounts.manage", "roles.manage"):
        assert leak not in text, f"{where}: в теле отказа подробности ({leak})"


def csrf_client(user):
    """Вошедший клиент, у которого проверка CSRF включена (вход выполняется до включения)."""
    client = support.logged_in(user)
    client.handler.enforce_csrf_checks = True
    return client


# --- NFR-104 ------------------------------------------------------------------------------------

def test_slice_pages_viewport_and_stacking_on_narrow_width():
    """NFR-104, FR-108: на каждой странице среза есть `meta viewport`; у «Структуры» (страница и прямое открытие
    узла) — контейнер раскладки `[data-structure-layout]` с деревом и карточкой внутри (дерево над карточкой
    на 360 px проверяет Playwright, решение C7)."""
    user = manager()
    unit = support_org.make_unit("Сеть")
    client = support.logged_in(user)

    for path, needs_layout in slice_pages(unit, user).items():
        response = client.get(path)
        assert response.status_code == 200, path
        parsed = page(response)
        assert has_viewport(parsed), f"{path}: нет <meta name=viewport content='{VIEWPORT}'>"
        if needs_layout:
            layout = parsed.find(data_structure_layout=True)
            assert len(layout) == 1, f"{path}: нужен ровно один [data-structure-layout]"
            tree = parsed.find(data_unit_tree=True)
            card = parsed.find(data_unit_card=True)
            assert tree and tree[0].inside(layout[0]), f"{path}: дерево вне контейнера раскладки"
            assert card and card[0].inside(layout[0]), f"{path}: карточка вне контейнера раскладки"


# --- NFR-107 ------------------------------------------------------------------------------------

def test_slice_pages_russian_and_moscow_time(clock):
    """NFR-107: страницы среза по-русски (`lang="ru"`, названия дней недели «Пн»…«Вс»), настройки — часовой пояс
    Europe/Moscow; «сейчас» берётся по Москве: в 21:30 UTC 31 декабря в Москве уже 1 января, и текущий год
    календаря и напоминание — следующие."""
    assert settings.TIME_ZONE == "Europe/Moscow" and settings.USE_TZ is True
    assert settings.LANGUAGE_CODE.startswith("ru")

    clock.set(datetime(2026, 12, 31, 21, 30, tzinfo=dt_timezone.utc))
    user = manager()
    unit = support_org.make_unit("Сеть")
    client = support.logged_in(user)

    for path in ("/", "/structure/", f"/structure/{unit.pk}/edit/", "/calendar/", "/calendar/upload/"):
        response = client.get(path)
        assert response.status_code == 200, path
        html = page(response).find("html")
        assert html and html[0].attrs.get("lang") == "ru", f"{path}: <html lang=ru>"

    calendar = page(client.get("/calendar/"))
    year = calendar.find(data_calendar_year=True)
    assert [y.attrs["data-year"] for y in year] == ["2027"], "год по умолчанию — текущий по Москве (2027), не по UTC"
    heads = [th.text.strip() for th in calendar.find("th") if th.text.strip() in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")]
    assert heads[:7] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"] and len(heads) == 12 * 7, "сетка с понедельника, по-русски"

    notices = page(client.get("/")).find(data_notice="calendar-year")
    assert [n.attrs["data-year"] for n in notices] == ["2027"], "напоминание о годе по московской дате"
    assert "Не загружен производственный календарь на 2027 год." in re.sub(r"\s+", " ", notices[0].text)

    from apps.org.services import calendar as org_calendar
    assert org_calendar.missing_years() == [2027], "служба берёт «сегодня» по Москве"


# --- FR-108 -------------------------------------------------------------------------------------

def test_htmx_request_gets_fragment_plain_request_full_page():
    """FR-108: `/structure/<id>/` — запрос HTMX получает фрагмент карточки без `<html>` и без дерева, обычный запрос —
    страницу целиком с деревом; ссылка узла несёт `hx-get` на тот же адрес, цель `#unit-card`, `hx-push-url`;
    `?q=` работает и во фрагменте, и на полной странице."""
    viewer = support.make_with_permissions("staff.view")
    root = support_org.root_unit()
    unit = support_org.make_unit("Сеть")
    ivan = support.make_employee(full_name="Иванов Пётр", position="Инженер связи")
    anna = support.make_employee(full_name="Белова Анна", position="Бухгалтер")
    support_org.make_member(ivan, unit)
    support_org.make_member(anna, unit)
    client = support.logged_in(viewer)

    fragment = client.get(f"/structure/{unit.pk}/", **HX)
    assert fragment.status_code == 200
    body = fragment.content.decode()
    assert "<html" not in body.lower() and "<body" not in body.lower(), "фрагмент без оболочки страницы"
    parsed = page(fragment)
    cards = parsed.find(data_unit_card=True)
    assert len(cards) == 1 and cards[0].attrs["data-unit-id"] == str(unit.pk)
    assert not parsed.find(data_unit_tree=True), "фрагмент — только карточка, без дерева"

    full = client.get(f"/structure/{unit.pk}/")
    assert full.status_code == 200
    assert "<html" in full.content.decode().lower()
    parsed = page(full)
    assert len(parsed.find(data_unit_tree=True)) == 1
    holder = parsed.find(id="unit-card")
    card = parsed.find(data_unit_card=True)
    assert len(holder) == 1 and len(card) == 1 and card[0].inside(holder[0]), "карточка внутри #unit-card"
    assert card[0].attrs["data-unit-id"] == str(unit.pk)

    links = {a.attrs["href"]: a for a in parsed.find("a", data_unit_link=True)}
    for node in (root, unit):
        link = links[f"/structure/{node.pk}/"]
        assert link.attrs.get("hx-get") == f"/structure/{node.pk}/"
        assert link.attrs.get("hx-target") == "#unit-card"
        assert link.attrs.get("hx-push-url") == "true"

    # поиск внутри узла: и во фрагменте, и на странице целиком
    found = page(client.get(f"/structure/{unit.pk}/?q=ИНЖЕНЕР", **HX))
    assert [m.attrs["data-user-id"] for m in found.find(data_member=True)] == [str(ivan.pk)]
    yo = page(client.get(f"/structure/{unit.pk}/?q=пётр"))
    assert [m.attrs["data-user-id"] for m in yo.find(data_member=True)] == [str(ivan.pk)]
    assert "<html" in client.get(f"/structure/{unit.pk}/?q=пётр").content.decode().lower()

    # /structure/ без HX — всегда страница целиком
    start = client.get("/structure/")
    assert "<html" in start.content.decode().lower() and page(start).find(data_unit_tree=True)


# --- FR-123 -------------------------------------------------------------------------------------

def test_forms_post_with_csrf_403_and_404_without_details():
    """FR-123: формы среза — только POST с CSRF (без токена 403 и база не меняется, с токеном — как обычно);
    без входа 302 на `/login/`; нет права — 403 раньше проверки существования объекта; неизвестный объект или
    неверный формат адреса — 404; тела отказов без подробностей (ни кодов прав, ни трассировок)."""
    unit = support_org.make_unit("Сеть")
    leaf = support_org.make_unit("Пустой")
    candidate = support.make_employee(full_name="Кандидат Тест")
    boss = manager()
    load_year(moscow_today().year, boss)
    day = moscow_today().isoformat()
    Unit, Special = model("org.Unit"), model("org.SpecialDay")
    calendar_before = model("org.WorkCalendar").objects.get()
    units_before = Unit.objects.count()

    posts = {
        "/structure/new/": {"kind": "department", "name": "Новый", "parent": support_org.root_unit().pk},
        f"/structure/{unit.pk}/edit/": {"name": "Иначе", "description": "", "parent": support_org.root_unit().pk},
        f"/structure/{leaf.pk}/delete/": {"confirm": "1"},
        f"/structure/{unit.pk}/members/": {"users": [candidate.pk], "mode": "concurrent"},
        f"/structure/{unit.pk}/roles/": {"roles": []},
        f"/structure/people/{candidate.pk}/dismiss/": {},
        "/calendar/settings/": {"work_weekdays": [0, 1, 2], "day_start": "08:00", "day_end": "17:00"},
        f"/calendar/days/{day}/": {"kind": "holiday"},
        "/me/photo/delete/": {},
    }

    # --- CSRF: без токена 403 и ничего не меняется; страница ошибки без подробностей
    client = csrf_client(boss)
    for path, data in posts.items():
        response = client.post(path, data)
        assert response.status_code == 403, f"{path}: POST без токена CSRF"
        assert_no_details(response.content.decode(), f"CSRF {path}")
    assert Unit.objects.count() == units_before
    assert Unit.objects.get(pk=unit.pk).name == "Сеть" and Unit.objects.filter(pk=leaf.pk).exists()
    assert not model("org.Membership").objects.filter(user=candidate).exists()
    assert model("core.User").objects.get(pk=candidate.pk).state == candidate.state
    assert not Special.objects.exists()
    after = model("org.WorkCalendar").objects.get()
    assert (after.work_weekdays, after.day_start, after.day_end) == (
        calendar_before.work_weekdays, calendar_before.day_start, calendar_before.day_end)

    # --- с токеном формы работают (значит, 403 выше — именно из-за токена)
    assert client.get("/structure/new/").status_code == 200
    token = client.cookies[settings.CSRF_COOKIE_NAME].value
    created = client.post("/structure/new/", {**posts["/structure/new/"], "csrfmiddlewaretoken": token})
    assert created.status_code == 302 and Unit.objects.count() == units_before + 1
    saved = client.post("/calendar/settings/", {**posts["/calendar/settings/"], "csrfmiddlewaretoken": token})
    assert saved.status_code == 302 and saved["Location"] == "/calendar/"
    assert model("org.WorkCalendar").objects.get().work_weekdays == [0, 1, 2]

    # --- без входа: 302 на /login/ (и для GET, и для POST)
    anon = support.make_client()
    for path in list(posts) + [f"/structure/{unit.pk}/", "/calendar/"]:
        for method in (anon.get, anon.post):
            response = method(path)
            assert response.status_code == 302 and response["Location"].startswith("/login/"), (method.__name__, path)

    # --- нет права: 403 раньше проверки существования объекта, без подробностей
    reader = support.logged_in(support.make_with_permissions("staff.view"))
    ghost = 999999
    forbidden = [
        ("get", "/structure/new/"), ("post", "/structure/new/"),
        ("get", f"/structure/{ghost}/edit/"), ("post", f"/structure/{ghost}/edit/"),
        ("post", f"/structure/{ghost}/delete/"), ("post", f"/structure/{ghost}/members/"),
        ("post", f"/structure/{ghost}/marks/"), ("post", f"/structure/{ghost}/roles/"),
        ("get", f"/structure/{ghost}/candidates/"), ("post", f"/structure/people/{ghost}/dismiss/"),
        ("post", "/calendar/settings/"), ("post", f"/calendar/days/{day}/"), ("get", "/calendar/upload/"),
        ("get", "/structure/import/"),
    ]
    for method, path in forbidden:
        response = getattr(reader, method)(path)
        assert response.status_code == 403, f"{method} {path}: нет права — 403, а не 404"
        assert_no_details(response.content.decode(), f"{method} {path}")
    nobody = support.logged_in(support.make_employee())
    for path in ("/structure/", f"/structure/{unit.pk}/"):
        response = nobody.get(path)
        assert response.status_code == 403, path
        assert_no_details(response.content.decode(), f"nobody {path}")

    # --- есть право: неизвестный объект и неверный формат адреса — 404 без подробностей
    client.handler.enforce_csrf_checks = False
    owner = client
    missing = [
        ("get", f"/structure/{ghost}/"), ("get", f"/structure/{ghost}/edit/"), ("post", f"/structure/{ghost}/edit/"),
        ("get", f"/structure/{ghost}/delete/"), ("post", f"/structure/{ghost}/delete/"),
        ("get", f"/structure/{ghost}/candidates/"), ("post", f"/structure/{ghost}/members/"),
        ("post", f"/structure/{ghost}/marks/"), ("post", f"/structure/{ghost}/roles/"),
        ("get", f"/structure/people/{ghost}/dismiss/"), ("post", f"/structure/people/{ghost}/dismiss/"),
        ("get", f"/structure/import/{ghost}/"), ("get", f"/calendar/upload/{ghost}/"),
        ("get", "/structure/abc/"), ("post", "/structure/abc/edit/"),
        ("get", "/calendar/days/2027-02-30/"), ("post", "/calendar/days/2027-02-30/"),
        ("get", "/calendar/days/вчера/"),
    ]
    for method, path in missing:
        response = getattr(owner, method)(path, {"kind": "holiday"} if method == "post" else {})
        assert response.status_code == 404, f"{method} {path}"
        assert_no_details(response.content.decode(), f"404 {method} {path}")
    assert Unit.objects.filter(pk=unit.pk).exists() and Unit.objects.get(pk=unit.pk).name == "Сеть"


# --- FR-132 -------------------------------------------------------------------------------------

def test_slice_pages_no_store_except_photo(protected_root):
    """FR-132 (решение 5 задач): все страницы, фрагменты и ответы форм среза — `Cache-Control: no-store` (в том числе
    переходы на вход и отказы); исключение одно — выдача фото `/staff/<id>/photo/<номер>/<размер>/` с
    `private, max-age=86400`; соседние адреса (`photo/delete/`, `/me/photo/`) исключением не становятся."""
    boss = manager()
    unit = support_org.make_unit("Сеть")
    owner = support.make_employee()
    stored = make_clean_photo(owner)
    pages = list(slice_pages(unit, boss)) + [
        f"/structure/{unit.pk}/candidates/", "/ui/date-picker/", "/structure/import/sample.csv",
        "/structure/import/sample.xlsx", f"/structure/people/{owner.pk}/dismiss/", f"/staff/{owner.pk}/", "/staff/", "/me/"]
    client = support.logged_in(boss)

    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "no-store" in response["Cache-Control"], f"{path}: страница среза без no-store"
    assert "no-store" in client.get(f"/structure/{unit.pk}/", **HX)["Cache-Control"], "фрагмент HTMX"
    assert "no-store" in client.get("/structure/999999/")["Cache-Control"], "404 тоже"

    # ответы форм (302 и 200 с отказом) и отказы по праву / входу
    created = client.post("/structure/new/", {"kind": "department", "name": "Сеть", "parent": support_org.root_unit().pk})
    assert created.status_code == 200 and "no-store" in created["Cache-Control"], "отказ формы (имя занято)"
    ok = client.post("/calendar/settings/", {"work_weekdays": [0, 1, 2, 3], "day_start": "09:00", "day_end": "18:00"})
    assert ok.status_code == 302 and "no-store" in ok["Cache-Control"]
    reader = support.logged_in(support.make_with_permissions("staff.view"))
    denied = reader.get("/structure/new/")
    assert denied.status_code == 403 and "no-store" in denied["Cache-Control"]
    anon = support.make_client()
    for path in ("/structure/", "/calendar/"):
        redirect = anon.get(path)
        assert redirect.status_code == 302 and "no-store" in redirect["Cache-Control"], path

    # исключение — только выдача фото
    photo_url = f"/staff/{owner.pk}/photo/{stored.id}/%s/"
    own = support.logged_in(owner)
    for size in ("512", "96"):
        for who in (own, client):
            response = who.get(photo_url % size)
            assert response.status_code == 200 and response["X-Accel-Redirect"].startswith("/protected/photos/")
            cache = response["Cache-Control"]
            assert "private" in cache and "max-age=86400" in cache and "no-store" not in cache, cache
    # порядок двух POST важен: первый удаляет фото владельца, второй идёт уже без фото; по дополнению 49 к
    # CONTRACT-002 удаление, когда фото нет, — тоже 302 (событие не пишется), так что оба ответа — 302
    for response in (client.post(f"/staff/{owner.pk}/photo/delete/"), own.post("/me/photo/delete/")):
        assert response.status_code == 302 and "no-store" in response["Cache-Control"], "соседние адреса фото — no-store"
    # отказ CSRF (другое представление, `csrf_failure`) — тоже 403 с no-store
    strict = csrf_client(boss)
    refused = strict.post("/structure/new/", {"kind": "department", "name": "Без токена", "parent": support_org.root_unit().pk})
    assert refused.status_code == 403 and "no-store" in refused["Cache-Control"], "403 по CSRF — no-store"
    assert "no-store" in own.get("/me/")["Cache-Control"]


# --- FR-146 -------------------------------------------------------------------------------------

def test_home_notice_for_calendar_manage_only(clock):
    """FR-146: напоминание о календаре видит только обладатель `calendar.manage`, на `/` (в `[data-home-notices]`)
    и на `/calendar/`; в течение года — если текущий не загружен, с 1 декабря — и пока не загружен следующий;
    по одному напоминанию на год, с текстом и ссылкой «Загрузить файл» на `/calendar/upload/`."""
    clock.set(datetime(2026, 12, 5, 9, 0, tzinfo=dt_timezone.utc))
    keeper = support.make_with_permissions("calendar.manage")
    reader = support.make_with_permissions("staff.view")
    admin_like = support.make_with_permissions("staff.view", "org.manage", "accounts.manage")
    keeper_client, reader_client, other_client = (support.logged_in(u) for u in (keeper, reader, admin_like))

    def notices(client, path):
        parsed = page(client.get(path))
        return parsed, parsed.find(data_notice="calendar-year")

    # декабрь, ничего не загружено: 2026 и 2027
    parsed, found = notices(keeper_client, "/")
    assert sorted(n.attrs["data-year"] for n in found) == ["2026", "2027"]
    holders = parsed.find(data_home_notices=True)
    assert len(holders) == 1 and all(n.inside(holders[0]) for n in found), "на главной — внутри [data-home-notices]"
    for n in found:
        year = n.attrs["data-year"]
        assert n.attrs.get("role") == "status"
        assert f"Не загружен производственный календарь на {year} год." in re.sub(r"\s+", " ", n.text)
        links = [a for a in parsed.find("a", href="/calendar/upload/") if a.inside(n)]
        assert links and "Загрузить файл" in links[0].text
    _, on_calendar = notices(keeper_client, "/calendar/")
    assert sorted(n.attrs["data-year"] for n in on_calendar) == ["2026", "2027"], "то же на /calendar/"

    # без права «Рабочий календарь» напоминания нет нигде (даже при других правах и staff.view)
    for client in (reader_client, other_client):
        assert notices(client, "/")[1] == [], "напоминание только для calendar.manage"
        assert client.get("/calendar/").status_code == 200
        assert notices(client, "/calendar/")[1] == []
    assert page(reader_client.get("/")).find(data_notice=True) == []

    # загружен текущий год — остаётся следующий (декабрь)
    load_year(2026, keeper)
    assert [n.attrs["data-year"] for n in notices(keeper_client, "/")[1]] == ["2027"]
    # загружен и следующий — напоминаний нет
    load_year(2027, keeper)
    assert notices(keeper_client, "/")[1] == [] and notices(keeper_client, "/calendar/")[1] == []

    # в течение года (до декабря) следующий год не напоминается; текущий — напоминается
    model("org.CalendarYear").objects.all().delete()
    clock.set(datetime(2026, 6, 10, 9, 0, tzinfo=dt_timezone.utc))
    keeper_client = support.logged_in(keeper)
    assert [n.attrs["data-year"] for n in notices(keeper_client, "/")[1]] == ["2026"]
    load_year(2026, keeper)
    assert notices(keeper_client, "/")[1] == []
    # граница: 30 ноября — ещё не напоминаем про следующий год, 1 декабря — уже
    clock.set(datetime(2026, 11, 30, 9, 0, tzinfo=dt_timezone.utc))
    keeper_client = support.logged_in(keeper)
    assert notices(keeper_client, "/")[1] == []
    clock.set(datetime(2026, 12, 1, 9, 0, tzinfo=dt_timezone.utc) + timedelta(minutes=1))
    keeper_client = support.logged_in(keeper)
    assert [n.attrs["data-year"] for n in notices(keeper_client, "/")[1]] == ["2027"]
    # граница по Москве: 21:00 UTC 30 ноября = 00:00 1 декабря МСК (уже напоминаем); 20:59 UTC = 23:59 30 ноября МСК (ещё нет)
    clock.set(datetime(2026, 11, 30, 20, 59, tzinfo=dt_timezone.utc))
    keeper_client = support.logged_in(keeper)
    assert notices(keeper_client, "/")[1] == [], "23:59 30 ноября по Москве"
    clock.set(datetime(2026, 11, 30, 21, 0, tzinfo=dt_timezone.utc))
    keeper_client = support.logged_in(keeper)
    assert [n.attrs["data-year"] for n in notices(keeper_client, "/")[1]] == ["2027"], "00:00 1 декабря по Москве"
