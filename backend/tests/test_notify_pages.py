"""T-4123: колокольчик в шапке и страница «Уведомления» (FR-318, FR-319, FR-342). Сценарии 10 и 11 спеки среза 004.

Маршруты — CONTRACT-004 § 13.1 (`/notifications/`, `/notifications/bell/`); зацепки — § 14.1-14.2; тексты — § 15.5;
элемент `top_bar_items` — § 3.1; решение 22 задач (у колокольчика нет `role`, `data-error`, `data-warning`), решения C8, D10
(`data-count`, `99+`, класс `d-none`) и E21 (`data-ws="connecting"` в шаблоне). Уведомления создаются напрямую
моделью с заданным `created_at` (время — в UTC, чтобы ошибка пояса попала в тест). Разметку разбирает `html.parser`,
элементы ищутся по зацепкам. Имена кода среза 004 — внутри тестов или через `support.model`.
"""
import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

from tests import support
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
BASE = datetime.datetime(2026, 10, 14, 9, 0, tzinfo=datetime.timezone.utc)   # 12:00 по Москве
KIND = "core.password_changed"                                                # всегда есть в каталоге (решение C2)
KIND_TITLE = "Пароль изменён"                                                 # § 3.2, дословно


# --- разбор разметки -----------------------------------------------------------------------------------------

_VOID = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())

    @property
    def classes(self) -> list:
        return self.attrs.get("class", "").split()


class _Doc(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self._stack[-1] if self._stack else None)
        self.elements.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs},
                                 self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.raw += data


def doc_of(response) -> _Doc:
    return _Doc(response.content.decode("utf-8", "replace"))


def find(doc, tag=None, attrs=None, *, within=None) -> list:
    """Элементы с тегом и атрибутами (`True` — атрибут есть с любым значением); `within` — только потомки."""
    wanted = attrs or {}
    found = [el for el in doc.elements
             if (tag is None or el.tag == tag) and all(k in el.attrs and (v is True or el.attrs[k] == v)
                                                      for k, v in wanted.items())]
    return [el for el in found if inside(el, within)] if within is not None else found


def inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def one(doc, tag=None, attrs=None, *, within=None):
    found = find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент {tag or '*'}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста ----------------------------------------------------------------------------------------------

def _note(user, n: int = 0, *, text: str | None = None, kind: str = KIND, at=None, read: bool = False):
    """Уведомление напрямую моделью; `created_at` — `BASE` плюс `n` минут (или заданный момент)."""
    created = at or BASE + datetime.timedelta(minutes=n)
    return model("notify.Notification").objects.create(
        user=user, kind=kind, text=text or f"Событие {n} {user.pk}", url="/test/", object_ref="",
        created_at=created, read_at=created if read else None)


def _bulk(user, count: int, *, read_every: int = 0, prefix: str = "Массовое"):
    """`count` уведомлений одним запросом; `created_at` растёт на минуту; каждое `read_every`-е прочитано."""
    Notification = model("notify.Notification")
    rows = []
    for i in range(count):
        created = BASE + datetime.timedelta(minutes=i)
        rows.append(Notification(user=user, kind=KIND, text=f"{prefix} {i}", url="/test/", object_ref="",
                                 created_at=created,
                                 read_at=created if read_every and i % read_every == 0 else None))
    Notification.objects.bulk_create(rows)
    return list(Notification.objects.filter(user=user).order_by("pk"))


def _newest_first(notes) -> list:
    """Порядок списка по контракту: `created_at` по убыванию, затем номер по убыванию."""
    return sorted(notes, key=lambda n: (n.created_at, n.pk), reverse=True)


def _employee_client():
    user = support.make_employee()
    return user, support.logged_in(user)


def _ids(doc, *, within=None) -> list:
    """Номера строк `li[data-notification]` в порядке разметки."""
    return [int(el.attrs["data-notification"]) for el in find(doc, "li", {"data-notification": True}, within=within)]


def _list_rows(doc):
    root = one(doc, None, {"data-notify-list": True})
    listing = one(doc, "ul", {"data-notifications": True}, within=root)
    return root, listing


def _list_ids(response) -> list:
    doc = doc_of(response)
    _, listing = _list_rows(doc)
    return _ids(doc, within=listing)


def _get_list(client, **params):
    response = client.get("/notifications/", params)
    assert response.status_code == 200, f"/notifications/ {params}: {response.status_code}"
    return response


def _bell(client, **extra):
    response = client.get("/", **extra)
    assert response.status_code == 200, f"GET /: {response.status_code}"
    doc = doc_of(response)
    return doc, one(doc, None, {"id": "notify-bell", "data-bell": True})


def _count_element(doc, bell):
    return one(doc, "span", {"id": "notify-count"}, within=bell)


# --- колокольчик (FR-318) ------------------------------------------------------------------------------------------

def test_bell_in_top_bar_has_count_and_toast_elements():
    """FR-318: шаблон колокольчика (элемент `top_bar`) рисует `#notify-bell[data-bell]` в блоке `top-actions` с кнопкой
    раскрытия панели «по нажатию», `#notify-count`, пустым `#notify-toast` и пустым `#notify-bell-panel`, подключает
    `notify.js`; у колокольчика нет `role`, `data-error`, `data-warning` (решение 22 задач)."""
    user, client = _employee_client()
    doc, bell = _bell(client)

    actions = [el for el in doc.elements if "top-actions" in el.classes]
    assert actions and any(inside(bell, el) for el in actions), "колокольчик вне блока top-actions"

    toggle = one(doc, "button", {"data-bell-toggle": True}, within=bell)
    assert toggle.attrs.get("aria-label") == "Уведомления"
    assert toggle.attrs.get("hx-get") == "/notifications/bell/"
    assert toggle.attrs.get("hx-trigger") == "click", "панель должна грузиться по нажатию, не при загрузке страницы"
    assert toggle.attrs.get("hx-target") == "#notify-bell-panel"
    assert toggle.attrs.get("hx-swap") == "innerHTML"

    count = _count_element(doc, bell)
    assert count.attrs.get("data-count") == "0"
    assert "hx-swap-oob" not in count.attrs, "в странице у числа нет hx-swap-oob (он только в кадре сервера)"

    toast = one(doc, "div", {"id": "notify-toast"}, within=bell)
    for name, value in (("data-text", ""), ("data-url", ""), ("data-tag", ""), ("data-show", "0")):
        assert toast.attrs.get(name) == value, f"#notify-toast: {name}={toast.attrs.get(name)!r}, ждали {value!r}"
    assert "hx-swap-oob" not in toast.attrs
    assert toast.text == ""

    panel = one(doc, None, {"id": "notify-bell-panel", "data-bell-panel": True}, within=bell)
    assert panel.text == "" and not find(doc, "li", {"data-notification": True}), "панель до нажатия должна быть пуста"

    scripts = [el for el in doc.elements if el.tag == "script" and "js/notify" in el.attrs.get("src", "")]
    assert len(scripts) == 1 and "defer" in scripts[0].attrs, "ждали один <script src=…js/notify….js defer>"
    assert scripts[0].attrs["src"].split("?")[0].endswith(".js")

    for el in doc.elements:
        if el is bell or inside(el, bell):
            for forbidden in ("role", "data-error", "data-warning"):
                assert forbidden not in el.attrs, f"<{el.tag}> колокольчика несёт {forbidden} (решение 22 задач)"


def test_bell_carries_ws_connect_to_notify_socket():
    """FR-318: корень колокольчика несёт `hx-ext="ws"`, `ws-connect="/ws/notify/"` и `data-ws="connecting"`
    (решение E21); других `ws-connect` на странице нет."""
    user, client = _employee_client()
    doc, bell = _bell(client)

    assert bell.attrs.get("hx-ext") == "ws"
    assert bell.attrs.get("ws-connect") == "/ws/notify/"
    assert bell.attrs.get("data-ws") == "connecting"
    assert [el for el in doc.elements if "ws-connect" in el.attrs] == [bell]
    assert one(doc, None, {"id": "notify-bell"}) is bell, "на странице один #notify-bell"


def test_bell_count_element_present_but_hidden_at_zero():
    """FR-318: при нуле непрочитанных `#notify-count` остаётся в разметке с `data-count="0"` и классом `d-none`
    (решение C8/D10); при `N > 0` класса нет, число точное, прочитанные не считаются."""
    user, client = _employee_client()
    doc, bell = _bell(client)
    count = _count_element(doc, bell)
    assert count.attrs["data-count"] == "0"
    assert "d-none" in count.classes

    _note(user, 1)
    _note(user, 2, read=True)
    _note(user, 3, read=True)
    doc, bell = _bell(client)
    count = _count_element(doc, bell)
    assert count.attrs["data-count"] == "1", "считаются только непрочитанные"
    assert count.text == "1"
    assert "d-none" not in count.classes


def test_bell_count_shows_99_at_99_and_99_plus_above():
    """FR-318: при 99 непрочитанных текст «99», при 100 — «99+»; `data-count` всегда точный (99 и 100)."""
    user, client = _employee_client()
    _bulk(user, 99)
    doc, bell = _bell(client)
    count = _count_element(doc, bell)
    assert (count.attrs["data-count"], count.text) == ("99", "99")
    assert "d-none" not in count.classes

    _note(user, 500)
    doc, bell = _bell(client)
    count = _count_element(doc, bell)
    assert (count.attrs["data-count"], count.text) == ("100", "99+")
    assert "d-none" not in count.classes


def test_bell_not_rendered_for_anonymous_user():
    """FR-318: у гостя (страница входа) колокольчика, числа, системного уведомления и соединения нет."""
    response = Client().get("/login/")
    assert response.status_code == 200
    doc = doc_of(response)
    assert any(el.tag == "form" for el in doc.elements), "ожидали страницу входа"
    assert not find(doc, None, {"id": "notify-bell"})
    assert not find(doc, None, {"data-bell": True})
    assert not find(doc, None, {"id": "notify-count"})
    assert not find(doc, None, {"id": "notify-toast"})
    assert not [el for el in doc.elements if "ws-connect" in el.attrs]
    assert not [el for el in doc.elements if el.tag == "script" and "js/notify" in el.attrs.get("src", "")]


def test_bell_fragment_lists_last_10_with_all_and_settings_links():
    """FR-318: `/notifications/bell/` отдаёт фрагмент (не страницу) с 10 последними уведомлениями, новые сверху, и
    ссылками «Все уведомления» (`/notifications/`) и «Настройки» (`/me/notifications/`); при пустом списке —
    `[data-empty-state="bell"]` «У вас нет уведомлений» и те же ссылки."""
    user, client = _employee_client()
    notes = [_note(user, i, text=f"Панель {i}") for i in range(12)]
    notes.append(_note(user, 11, text="Панель ничья"))        # то же время, что у 11-го: выше по номеру
    expected = [n.pk for n in _newest_first(notes)[:10]]

    for extra in (HX, {}):
        response = client.get("/notifications/bell/", **extra)
        assert response.status_code == 200
        body = response.content.decode("utf-8")
        assert "<html" not in body.lower(), "фрагмент панели, а не полная страница"
        doc = doc_of(response)
        listing = one(doc, None, {"data-bell-list": True})
        assert _ids(doc, within=listing) == expected
        rows = {int(el.attrs["data-notification"]): el.text for el in find(doc, "li", {"data-notification": True})}
        for note in notes:
            if note.pk in expected:
                assert note.text in rows[note.pk], "в строке панели нет текста уведомления"
            else:
                assert note.pk not in rows, "в панели лишняя (одиннадцатая и старше) запись"
        all_link = one(doc, "a", {"data-bell-all": True})
        assert all_link.attrs.get("href") == "/notifications/" and all_link.text == "Все уведомления"
        settings_link = one(doc, "a", {"data-bell-settings": True})
        assert settings_link.attrs.get("href") == "/me/notifications/" and settings_link.text == "Настройки"
        assert not find(doc, None, {"data-empty-state": "bell"})

    other, other_client = _employee_client()
    doc = doc_of(other_client.get("/notifications/bell/"))
    assert not find(doc, "li", {"data-notification": True})
    empty = one(doc, None, {"data-empty-state": "bell"})
    assert empty.text == "У вас нет уведомлений"
    assert one(doc, "a", {"data-bell-all": True}).attrs.get("href") == "/notifications/"
    assert one(doc, "a", {"data-bell-settings": True}).attrs.get("href") == "/me/notifications/"


def test_bell_fragment_shows_only_own_notifications():
    """FR-318, FR-342: панель показывает только уведомления самого сотрудника; чужие тексты и номера в ответе
    отсутствуют, а при пустом своём списке чужие не подставляются."""
    user, client = _employee_client()
    stranger = support.make_employee()
    own = [_note(user, i, text=f"Своё {i}") for i in range(3)]
    foreign = [_note(stranger, i, text=f"Чужое {i}") for i in range(3)]

    response = client.get("/notifications/bell/")
    assert response.status_code == 200
    doc = doc_of(response)
    assert set(_ids(doc)) == {n.pk for n in own}
    body = response.content.decode("utf-8")
    assert "Чужое" not in body
    for n in foreign:
        assert f'data-notification="{n.pk}"' not in body and f"/notifications/{n.pk}/" not in body

    lonely, lonely_client = _employee_client()
    doc = doc_of(lonely_client.get("/notifications/bell/"))
    assert _ids(doc) == [] and find(doc, None, {"data-empty-state": "bell"})


# --- страница списка (FR-319) ---------------------------------------------------------------------------------------

def test_list_page_shows_50_newest_first_with_kind_text_time_unread_mark():
    """FR-319: страница — 50 строк, новые сверху (`created_at`, затем номер, по убыванию); в строке вид (название из
    каталога), текст ссылкой `/notifications/<id>/open/`, время по Москве, отметка «новое» только у непрочитанных;
    разметка в тексте экранируется (NFR-311)."""
    from apps.notify.services import kinds

    user, client = _employee_client()
    notes = []
    for i in range(54):
        text = "Тема <b>жирный</b> & «кавычки»" if i == 53 else f"Строка списка {i}"
        notes.append(_note(user, i, text=text, read=(i % 3 == 0)))
    notes.append(_note(user, 53, text="Строка ничья", at=notes[53].created_at))
    expected = _newest_first(notes)[:50]
    assert expected[0].text == "Строка ничья", "при равном времени выше запись с большим номером"

    response = _get_list(client)
    doc = doc_of(response)
    html = [el for el in doc.elements if el.tag == "html"]
    assert html and html[0].attrs.get("lang") == "ru"
    assert [el for el in doc.elements if el.tag == "meta" and el.attrs.get("name") == "viewport"]
    assert one(doc, "h1").text == "Уведомления"
    assert "Уведомления" in one(doc, "title").text
    root, listing = _list_rows(doc)
    rows = find(doc, "li", {"data-notification": True}, within=listing)
    assert [int(r.attrs["data-notification"]) for r in rows] == [n.pk for n in expected]
    assert len(find(doc, "li", {"data-notification": True})) == 50

    title = kinds.get(KIND).title
    assert title == KIND_TITLE
    by_id = {n.pk: n for n in notes}
    for row in rows:
        note = by_id[int(row.attrs["data-notification"])]
        assert not [el for el in doc.elements if inside(el, row) and "data-kind" in el.attrs], "у строки нет [data-kind]"
        assert "role" not in row.attrs and "data-kind" not in row.attrs
        text_field = one(doc, None, {"data-field": "text"}, within=row)
        links = [text_field] if text_field.tag == "a" and "data-open" in text_field.attrs else \
            find(doc, "a", {"data-open": True}, within=text_field)
        assert len(links) == 1, "текст — одна ссылка a[data-open]"
        assert links[0].attrs.get("href") == f"/notifications/{note.pk}/open/"
        assert links[0].text == " ".join(note.text.split()), "текст как есть, без разметки"
        assert one(doc, None, {"data-field": "kind"}, within=row).text == title
        stamp = one(doc, "time", {"data-at": True}, within=row)
        moment = datetime.datetime.fromisoformat(stamp.attrs["data-at"])
        assert moment.utcoffset() == datetime.timedelta(hours=3) and moment == note.created_at
        assert stamp.text == note.created_at.astimezone(MSK).strftime("%d.%m.%Y %H:%M")
        marks = find(doc, None, {"data-unread-mark": True}, within=row)
        if note.read_at is None:
            assert row.attrs.get("data-unread") == "1"
            assert len(marks) == 1 and marks[0].text == "новое"
        else:
            assert row.attrs.get("data-unread") == "0"
            assert marks == []

    body = response.content.decode("utf-8")
    assert "<b>жирный</b>" not in body and "&lt;b&gt;" in body, "разметка в тексте уведомления должна экранироваться"


def test_list_page_page_param_returns_next_50():
    """FR-319: `?page=2` — следующие 50, `?page=3` — остаток; не число и меньше 1 — первая, больше числа страниц —
    последняя; пейджер `nav[data-pager]` ведёт по страницам и хранит фильтр `f`."""
    user, client = _employee_client()
    notes = _bulk(user, 120)
    order = [n.pk for n in _newest_first(notes)]

    assert _list_ids(_get_list(client)) == order[:50]
    assert _list_ids(_get_list(client, page=1)) == order[:50]
    assert _list_ids(_get_list(client, page=2)) == order[50:100]
    assert _list_ids(_get_list(client, page=3)) == order[100:]
    assert _list_ids(_get_list(client, page=99)) == order[100:], "больше числа страниц — последняя"
    assert _list_ids(_get_list(client, page="abc")) == order[:50]
    assert _list_ids(_get_list(client, page=0)) == order[:50]
    assert _list_ids(_get_list(client, page=-4)) == order[:50]

    def pager(response):
        doc = doc_of(response)
        nav = one(doc, "nav", {"data-pager": True})
        current = one(doc, None, {"data-page-current": True}, within=nav)
        prev = find(doc, "a", {"data-page-prev": True}, within=nav)
        nxt = find(doc, "a", {"data-page-next": True}, within=nav)
        return current.text, prev, nxt

    current, prev, nxt = pager(_get_list(client, page=2, f="unread"))
    assert current == "2"
    assert len(prev) == 1 and len(nxt) == 1
    next_query = parse_qs(urlsplit(nxt[0].attrs["href"]).query)
    assert next_query.get("page") == ["3"] and next_query.get("f") == ["unread"], "ссылка хранит фильтр и ведёт на 3"
    prev_query = parse_qs(urlsplit(prev[0].attrs["href"]).query)
    assert prev_query.get("page", ["1"]) == ["1"] and prev_query.get("f") == ["unread"]

    current, prev, nxt = pager(_get_list(client))
    assert current == "1" and prev == [] and len(nxt) == 1, "у первой страницы нет ссылки назад"
    current, prev, nxt = pager(_get_list(client, page=3))
    assert current == "3" and len(prev) == 1 and nxt == [], "у последней страницы нет ссылки вперёд"

    short, short_client = _employee_client()
    _bulk(short, 5)
    assert not find(doc_of(_get_list(short_client)), "nav", {"data-pager": True}), "одна страница — без пейджера"


def test_list_filter_unread_shows_only_unread_and_all_shows_every_one():
    """FR-319: `?f=unread` — только непрочитанные, `?f=all`, пусто и любое другое значение — все; переключатель
    `a[data-filter]` ведёт на `/notifications/` и `/notifications/?f=unread`, активный помечен `aria-current="true"`."""
    user, client = _employee_client()
    unread = [_note(user, i, text=f"Новое {i}") for i in (1, 3, 5)]
    read = [_note(user, i, text=f"Старое {i}", read=True) for i in (2, 4, 6)]
    every = {n.pk for n in unread + read}

    only = _get_list(client, f="unread")
    assert set(_list_ids(only)) == {n.pk for n in unread}
    assert all(r.attrs.get("data-unread") == "1" for r in find(doc_of(only), "li", {"data-notification": True}))
    for params in ({}, {"f": "all"}, {"f": ""}, {"f": "что-то"}):
        assert set(_list_ids(_get_list(client, **params))) == every, f"фильтр {params}: ждали все уведомления"

    def switch(response):
        doc = doc_of(response)
        nav = one(doc, "nav", {"data-notify-filter": True})
        return {a.attrs["data-filter"]: a for a in find(doc, "a", {"data-filter": True}, within=nav)}

    links = switch(only)
    assert set(links) == {"all", "unread"}
    assert links["all"].attrs.get("href") == "/notifications/" and links["all"].text == "Все"
    assert links["unread"].attrs.get("href") == "/notifications/?f=unread" and links["unread"].text == "Непрочитанные"
    assert links["unread"].attrs.get("aria-current") == "true" and links["all"].attrs.get("aria-current") != "true"
    default = switch(_get_list(client))
    assert default["all"].attrs.get("aria-current") == "true" and default["unread"].attrs.get("aria-current") != "true"


def test_list_page_has_filter_switch_read_all_and_mark_read_controls():
    """FR-319: на странице есть переключатель, форма «Прочитать все» на `/notifications/read-all/` и у каждой
    непрочитанной строки форма «Прочитать» на `/notifications/<id>/read/` (POST, CSRF, HTMX-атрибуты); у прочитанной
    формы, отметки и кнопки нет."""
    user, client = _employee_client()
    fresh = _note(user, 1, text="Непрочитанное")
    old = _note(user, 2, text="Прочитанное", read=True)

    doc = doc_of(_get_list(client, f="unread", page=1))
    root = one(doc, None, {"data-notify-list": True})
    assert find(doc, "nav", {"data-notify-filter": True}, within=root)
    assert find(doc, "ul", {"data-notifications": True}, within=root)

    read_all = one(doc, "form", {"data-form": "read-all"}, within=root)
    assert read_all.attrs.get("action") == "/notifications/read-all/"
    assert read_all.attrs.get("method", "").lower() == "post"
    assert find(doc, "input", {"name": "csrfmiddlewaretoken"}, within=read_all), "в форме нет CSRF"
    button = one(doc, "button", {"data-action": "read-all"}, within=read_all)
    assert button.text == "Прочитать все"
    hidden = {i.attrs["name"]: i.attrs.get("value") for i in find(doc, "input", {"type": "hidden"}, within=read_all)}
    assert hidden.get("f") == "unread", "в форме «Прочитать все» скрытое поле f с текущим фильтром"

    row = one(doc, "li", {"data-notification": str(fresh.pk)})
    form = one(doc, "form", {"data-form": "read"}, within=row)
    url = f"/notifications/{fresh.pk}/read/"
    assert form.attrs.get("action") == url and form.attrs.get("method", "").lower() == "post"
    assert find(doc, "input", {"name": "csrfmiddlewaretoken"}, within=form)
    read_button = one(doc, "button", {"data-action": "read"}, within=form)
    assert read_button.text == "Прочитать"
    carriers = [form, read_button]
    assert any(c.attrs.get("hx-post") == url for c in carriers), "нет hx-post на форме или кнопке"
    assert any(c.attrs.get("hx-target") == "closest li" for c in carriers)
    assert any(c.attrs.get("hx-swap") == "outerHTML" for c in carriers)
    fields = {i.attrs["name"]: i.attrs.get("value") for i in find(doc, "input", {"type": "hidden"}, within=form)}
    assert fields.get("f") == "unread" and fields.get("page") == "1", "скрытые поля f и page"

    doc = doc_of(_get_list(client))
    old_row = one(doc, "li", {"data-notification": str(old.pk)})
    assert old_row.attrs.get("data-unread") == "0"
    assert not find(doc, "form", {"data-form": "read"}, within=old_row)
    assert not find(doc, "button", {"data-action": "read"}, within=old_row)
    assert not find(doc, None, {"data-unread-mark": True}, within=old_row)
    assert len(find(doc, "form", {"data-form": "read"})) == 1, "форма «Прочитать» только у непрочитанной"


def test_empty_list_shows_no_notifications_text():
    """FR-319: пустой список объясняет, что здесь будет: `[data-empty-state="notifications"]` «У вас нет
    уведомлений» (при `f=unread` — «Непрочитанных уведомлений нет», § 15.5), без строк и кнопок."""
    user, client = _employee_client()
    for params, text in (({}, "У вас нет уведомлений"), ({"f": "unread"}, "Непрочитанных уведомлений нет")):
        doc = doc_of(_get_list(client, **params))
        empty = one(doc, None, {"data-empty-state": "notifications"})
        assert empty.text == text
        assert not find(doc, "li", {"data-notification": True})
        assert not [el for el in doc.elements if el.tag == "button" and inside(el, empty)]
        assert not find(doc, "form", {"data-form": "read-all"}), "«Прочитать все» не нужна при пустом списке"

    _note(user, 1, read=True)
    doc = doc_of(_get_list(client, f="unread"))
    assert one(doc, None, {"data-empty-state": "notifications"}).text == "Непрочитанных уведомлений нет"
    doc = doc_of(_get_list(client))
    assert not find(doc, None, {"data-empty-state": "notifications"}) and len(find(doc, "li", {"data-notification": True})) == 1


# --- чужие записи и вход (FR-342, FR-319) -----------------------------------------------------------------------------

def test_list_page_does_not_show_other_users_notifications():
    """FR-342: страница списка (все, непрочитанные, любая страница) показывает только свои уведомления; чужих текстов,
    номеров и ссылок открытия в ответе нет."""
    user, client = _employee_client()
    stranger = support.make_employee()
    own = [_note(user, i, text=f"Своя запись {i}") for i in range(4)]
    foreign = [_note(stranger, i, text=f"Чужая запись {i}") for i in range(60)]

    for params in ({}, {"f": "unread"}, {"page": 2}, {"f": "unread", "page": 9}):
        response = _get_list(client, **params)
        assert set(_list_ids(response)) == {n.pk for n in own}, f"{params}: в списке не только свои записи"
        body = response.content.decode("utf-8")
        assert "Чужая запись" not in body
        for n in foreign[:5]:
            assert f'data-notification="{n.pk}"' not in body and f"/notifications/{n.pk}/" not in body

    doc = doc_of(_get_list(client))
    assert len(find(doc, "li", {"data-notification": True})) == 4
    assert not find(doc, "nav", {"data-pager": True}), "чужие записи не увеличивают число страниц"


def test_list_page_requires_login():
    """FR-319: без входа `/notifications/` и `/notifications/bell/` отвечают 302 на `/login/` с `next`."""
    for path in ("/notifications/", "/notifications/bell/"):
        response = Client().get(path)
        assert response.status_code == 302, f"{path}: {response.status_code}"
        target = urlsplit(response["Location"])
        assert target.path == "/login/", f"{path}: переход на {response['Location']}"
        assert unquote(parse_qs(target.query).get("next", [""])[0]) == path
