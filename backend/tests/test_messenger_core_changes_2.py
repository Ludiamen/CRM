"""T-8126b: изменения `org` и `notify` среза 008 (FR-649, FR-650, FR-667).

План: «Изменения кода прежних срезов» — строки `org/views/structure_forms.py` и `templates/org/_slider.html` (поля
точки `unit_form_parts`, `on_saved` в своём savepoint, `unit_new` в `atomic`), `org/services/structure.py`
(`events.publish("unit.deleted", …)`), `notify/urls.py` и `notify/views/pages.py` (фрагмент `notifications/list/`,
`bell_link`, 302 старого адреса), `templates/notify/bell.html` и `_bell_panel.html`; «Вкладка „Уведомления“ и
совместимость адресов». Контракт: CONTRACT-008, 3.2 (форма узла, событие удаления), 3.3 (фрагмент потока,
`bell_link`, старый адрес), 4.1 (`org.services.structure`), 4.2 (`notify`), 10.2 (адреса и ответы), 15.3
(правки прежних тестов не повторяются).

Семь тестов T-8126b, других нет. Код среза на уровне модуля не импортируется: `apps.core.extensions`,
`apps.org.services`, `apps.core.events`, `apps.notify.views.pages` и модели берутся ленивыми импортами внутри
тестов (`support.model`), поэтому `pytest --collect-only` проходит до появления кода. Секретов и ПДн нет: ФИО —
вымышленные, адресов и телефонов тест не создаёт.
"""
import datetime
import logging
import re
from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import RequestFactory

from tests import support
from tests import support_messenger as sm
from tests import support_org as org

pytestmark = pytest.mark.django_db

# `REMOTE_ADDR` клиента `support.logged_in` (`support.make_client`): столько же ждёт `request.client_ip`
# при пустых `TRUSTED_PROXIES` (CONTRACT-008, 3.2: `on_saved(unit, post, actor, ip)`)
CLIENT_IP = "198.51.100.7"
# момент уведомлений (UTC, как в тестах среза 004), чтобы порядок строк не зависел от часов прогона
NOTIFY_BASE = datetime.datetime(2026, 11, 10, 6, 0, tzinfo=datetime.timezone.utc)
NOTIFY_KIND = "core.password_changed"


# --- помощники только этого файла ----------------------------------------------------------------------------------

def _Unit():
    return support.model("org.Unit")


@contextmanager
def _only_parts(*parts):
    """На время блока в точке `unit_form_parts` только эти записи; прежние возвращаются по выходу.

    Форма узла читает реестр и не знает, кто зарегистрировался (CONTRACT-008, 3.1–3.2), поэтому тест подменяет
    записи сам: галочка мессенджера и её обработчик не участвуют, а порядок `order` проверяется на своих полях.
    """
    from apps.core import extensions

    registry = extensions._registry["unit_form_parts"]
    saved = list(registry)
    registry[:] = list(parts)
    try:
        yield parts
    finally:
        registry[:] = saved


def _part(key: str, order: int, *, render=None, on_saved=None):
    """Запись точки `unit_form_parts` в форме контракта (CONTRACT-008, 3.1)."""
    from apps.core import extensions

    return extensions.UnitFormPart(
        key=key, order=order,
        render=render if render is not None else (lambda request, unit: ""),
        on_saved=on_saved if on_saved is not None else (lambda unit, post, actor, ip=None: None))


def _new_unit(client, name: str, *, description: str = "") -> "object":
    """`POST /structure/new/` формой узла; узел из базы (как `_post_new_unit` в `test_messenger_department.py`)."""
    response = client.post("/structure/new/", {"kind": "department", "name": name, "description": description,
                                               "parent": org.root_unit().pk})
    assert response.status_code == 302, f"создание узла: {response.status_code}"
    return _Unit().objects.get(name=name)


# --- разбор разметки (только этот файл; как `_Doc` в `test_notify_pages.py`) --------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {key: (value if value is not None else "") for key, value in attrs},
                 self._stack[-1] if self._stack else None)
        self.elements.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, {key: (value if value is not None else "") for key, value in attrs},
                                 self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        for el in self._stack:
            el.raw += data


def _doc(response) -> _Doc:
    return _Doc(response.content.decode("utf-8", "replace"))


def _inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _find(doc, tag=None, attrs=None, *, within=None) -> list:
    """Элементы с тегом и атрибутами (`True` — атрибут есть с любым значением); `within` — только потомки."""
    wanted = attrs or {}
    found = [el for el in doc.elements
             if (tag is None or el.tag == tag)
             and all(key in el.attrs and (value is True or el.attrs[key] == value)
                     for key, value in wanted.items())]
    return [el for el in found if _inside(el, within)] if within is not None else found


def _one(doc, tag=None, attrs=None, *, within=None):
    found = _find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент <{tag or '*'}> {attrs}, нашли {len(found)}"
    return found[0]


def _rows(response) -> list[int]:
    """Номера строк потока `li[data-notification]` в порядке разметки (тот же `notify/_row.html`)."""
    return [int(el.attrs["data-notification"]) for el in _find(_doc(response), "li", {"data-notification": True})]


# --- данные уведомлений -------------------------------------------------------------------------------------------

def _employee():
    """Действующий сотрудник и вошедший клиент; адресов в данных нет."""
    user = support.make_employee(full_name="Сотрудник Уведомлений")
    return user, support.logged_in(user)


def _note(user, minutes: int = 0, *, read: bool = False, text: str | None = None, url: str = "/test/"):
    """Уведомление напрямую моделью; `created_at` — `NOTIFY_BASE` плюс минуты (время в UTC, как в срезе 004)."""
    created = NOTIFY_BASE + datetime.timedelta(minutes=minutes)
    return support.model("notify.Notification").objects.create(
        user=user, kind=NOTIFY_KIND, text=text or f"Событие {minutes}", url=url, object_ref="",
        created_at=created, read_at=created if read else None)


def _newest_first(notes) -> list[int]:
    """Порядок потока по контракту: `created_at` по убыванию, затем номер по убыванию."""
    return [note.pk for note in sorted(notes, key=lambda item: (item.created_at, item.pk), reverse=True)]


# --- FR-649: поля точки `unit_form_parts` и вызов `on_saved` ------------------------------------------------------

def test_unit_form_renders_registered_fields_and_calls_on_saved_after_save():
    """FR-649 (CONTRACT-008, 3.1–3.2): форма узла рисует поля точки `unit_form_parts` в порядке `order`, а не в
    порядке регистрации; пустая строка `render` поля не даёт; `render(request, unit)` зовётся и на создании узла
    (`unit is None`), и на правке (сам узел). После `create_unit` и после `update_unit` форма зовёт
    `on_saved(unit, post, actor, ip)` каждой записи в том же порядке, с созданным или изменённым узлом, данными
    формы, действующим администратором и адресом клиента."""
    admin = sm.as_admin()
    renders, calls = [], []

    def render_empty(request, unit):
        renders.append(("empty", unit))
        return ""

    def render_early(request, unit):
        renders.append(("early", unit))
        return '<input type="checkbox" name="early" data-probe="early">'

    def render_late(request, unit):
        renders.append(("late", unit))
        return '<input type="text" name="late" value="" data-probe="late">'

    def on_saved(key: str):
        def call(unit, post, actor, ip=None):
            calls.append({"key": key, "unit": unit.pk, "name": post.get("name"), "description":
                          post.get("description"), "actor": actor.pk, "ip": ip})
        return call

    # регистрация нарочно не по `order`: форма обязана отсортировать записи сама
    parts = (_part("late", 20, render=render_late, on_saved=on_saved("late")),
             _part("empty", 5, render=render_empty, on_saved=on_saved("empty")),
             _part("early", 10, render=render_early, on_saved=on_saved("early")))

    with _only_parts(*parts):
        new_form = admin.client.get("/structure/new/", **support.HX)
        assert new_form.status_code == 200, "форма нового узла — фрагмент слайдера"
        body = new_form.content.decode("utf-8")
        assert "<html" not in body.lower(), "форма узла пришла целой страницей"
        assert 'data-unit-form-part="empty"' not in body, "пустая строка render дала поле"
        assert body.index('data-probe="early"') < body.index('data-probe="late"'), "поля не по `order`"
        assert renders == [("empty", None), ("early", None), ("late", None)], "render не получил `unit=None`"

        name = "Отдел полей формы"
        created = _new_unit(admin.client, name, description="Описание узла")
        assert [(item["key"], item["unit"], item["name"], item["description"], item["actor"], item["ip"])
                for item in calls] == [
            ("empty", created.pk, name, "Описание узла", admin.user.pk, CLIENT_IP),
            ("early", created.pk, name, "Описание узла", admin.user.pk, CLIENT_IP),
            ("late", created.pk, name, "Описание узла", admin.user.pk, CLIENT_IP)], "on_saved после создания узла"

        renders.clear()
        calls.clear()
        edit = admin.client.post(f"/structure/{created.pk}/edit/", {"name": name, "description": "Новое описание"})
        assert edit.status_code == 302, "правка узла — 302 на карточку"
        created.refresh_from_db()
        assert created.description == "Новое описание"
        assert [(item["key"], item["unit"], item["description"]) for item in calls] == [
            ("empty", created.pk, "Новое описание"), ("early", created.pk, "Новое описание"),
            ("late", created.pk, "Новое описание")], "on_saved после правки узла"

        renders.clear()
        edit_form = admin.client.get(f"/structure/{created.pk}/edit/", **support.HX)
        assert edit_form.status_code == 200
        assert [key for key, _ in renders] == ["empty", "early", "late"]
        assert all(unit is not None and unit.pk == created.pk for _, unit in renders), \
            "на правке render не получил узел"
        assert 'data-probe="early"' in edit_form.content.decode("utf-8")


# --- FR-649: savepoint обработчика и запись предупреждения ---------------------------------------------------------

def test_on_saved_own_savepoint_failure_does_not_cancel_unit_save_and_logs(caplog):
    """FR-649 (CONTRACT-008, 3.2): каждый `on_saved` работает в своём `transaction.atomic()` (savepoint). Сбой
    обработчика откатывает только его работу, пишется предупреждением журнала `apps.messenger.unit_form` с ключом
    поля и текстом ошибки и не отменяет сохранение узла; следующие обработчики выполняются."""
    admin = sm.as_admin()
    User = support.model("core.User")
    marker = "T-8126b-след-сбоя"
    followed = []

    def broken(unit, post, actor, ip=None):
        support.make_employee(full_name=marker)   # запись того же обработчика: её откатит savepoint
        raise RuntimeError("on_saved упал намеренно")

    def follower(unit, post, actor, ip=None):
        followed.append({"unit": unit.pk, "name": post.get("name"), "actor": actor.pk, "ip": ip})

    parts = (_part("broken", 10, on_saved=broken), _part("follower", 20, on_saved=follower))
    name = "Отдел со сбоем обработчика"

    with _only_parts(*parts):
        with caplog.at_level(logging.WARNING, logger="apps.messenger.unit_form"):
            caplog.clear()
            response = admin.client.post("/structure/new/", {"kind": "department", "name": name,
                                                             "description": "", "parent": org.root_unit().pk})
        assert response.status_code == 302, "сбой обработчика отменил сохранение узла"
        unit = _Unit().objects.get(name=name)
        assert response["Location"] == f"/structure/{unit.pk}/"
        assert followed == [{"unit": unit.pk, "name": name, "actor": admin.user.pk, "ip": CLIENT_IP}], \
            "после сбоя следующий обработчик не выполнился"
        assert not User.objects.filter(full_name=marker).exists(), "запись сбойного обработчика не откатилась"

    records = [record for record in caplog.records if record.name == "apps.messenger.unit_form"]
    assert len(records) == 1, f"предупреждений журнала: {len(records)}"
    record = records[0]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert "broken" in message and "on_saved упал намеренно" in message, f"текст предупреждения: {message!r}"


# --- FR-649: `unit_new` в транзакции ------------------------------------------------------------------------------

def test_unit_new_wrapped_in_atomic():
    """FR-649 (CONTRACT-008, 3.2): сохранение нового узла (`unit_new`) идёт в `transaction.atomic()`: между
    `SAVEPOINT` и `RELEASE SAVEPOINT` лежат и вставка узла (`org_unit`), и работа `on_saved` (вставка `core_user`
    обработчиком) — до среза транзакции у формы не было."""
    admin = sm.as_admin()
    touched = []

    def on_saved(unit, post, actor, ip=None):
        support.make_employee(full_name="След атомарности")
        touched.append(unit.pk)

    name = "Отдел атомарности"
    with _only_parts(_part("atomic_probe", 10, on_saved=on_saved)):
        with sm.capture_sql() as sqls:
            response = admin.client.post("/structure/new/", {"kind": "department", "name": name,
                                                             "description": "", "parent": org.root_unit().pk})
    assert response.status_code == 302, "узел не создан формой"
    unit = _Unit().objects.get(name=name)
    assert touched == [unit.pk], "on_saved не выполнился"

    def first(pattern: str) -> int:
        found = [index for index, sql in enumerate(sqls) if re.match(pattern, sql, re.I)]
        assert found, f"в запросах нет {pattern!r}"
        return found[0]

    savepoint = first(r"\s*SAVEPOINT")
    unit_insert = first(r'\s*INSERT INTO "org_unit"')
    handler_insert = first(r'\s*INSERT INTO "core_user"')
    releases = [index for index, sql in enumerate(sqls) if re.search(r"RELEASE SAVEPOINT", sql, re.I)]
    assert releases, "нет RELEASE SAVEPOINT"
    assert savepoint < unit_insert, "вставка узла вне транзакции формы"
    assert unit_insert < handler_insert < max(releases), "работа on_saved вне транзакции формы"


# --- FR-650: шина `unit.deleted` после удаления узла --------------------------------------------------------------

def test_structure_delete_unit_publishes_unit_deleted_after_delete(django_capture_on_commit_callbacks, caplog):
    """FR-650 (CONTRACT-008, 3.2, 3.5): `delete_unit` публикует `unit.deleted` после удаления узла с ключами
    `unit_id`, `name`, `actor_id`; подписчики шины зовутся после фиксации — в обработчике узла уже нет; сбой
    одного обработчика не откатывает удаление и не мешает остальным."""
    from apps.core import events
    from apps.org.services import structure

    Unit = _Unit()
    admin = sm.as_admin()
    doomed = sm.unit("Удаляемый узел шины")
    unit_pk, unit_name = doomed.pk, doomed.name
    payloads, existed = [], []

    def broken(**payload):
        raise RuntimeError("обработчик unit.deleted упал")

    def spy(**payload):
        payloads.append(dict(payload))
        existed.append(Unit.objects.filter(pk=unit_pk).exists())

    def spy_late(**payload):
        payloads.append(dict(payload))
        existed.append(Unit.objects.filter(pk=unit_pk).exists())

    handlers = (broken, spy, spy_late)
    for handler in handlers:
        events.subscribe("unit.deleted", handler)
    try:
        with caplog.at_level(logging.ERROR, logger="apps.core.events"):
            with django_capture_on_commit_callbacks(execute=True):
                structure.delete_unit(doomed, actor=admin.user, ip="203.0.113.9")
    finally:
        for handler in handlers:
            events.unsubscribe("unit.deleted", handler)

    assert not Unit.objects.filter(pk=unit_pk).exists(), "узел не удалён"
    assert existed == [False, False], "обработчик шины увидел ещё не удалённый узел"
    expected = {"unit_id": unit_pk, "name": unit_name, "actor_id": admin.user.pk}
    assert payloads == [expected, expected], f"данные события: {payloads}"
    errors = [record for record in caplog.records if record.name == "apps.core.events"]
    assert any("unit.deleted" in record.getMessage() for record in errors), "сбой обработчика не записан в журнал"


# --- FR-667: колокольчик ссылается на вкладку только с мессенджером -----------------------------------------------

def test_notify_bell_link_present_only_with_messenger():
    """FR-667 (CONTRACT-008, 3.3): `top_bar_context` отдаёт `bell_link` = `/messenger/notifications/` только при
    установленном `apps.messenger`; `notify/bell.html` рисует ссылку `a[data-bell-link]` вместо кнопки панели, а
    `#notify-count`, `#notify-toast`, пустой `#notify-bell-panel`, `data-ws` и `ws-connect="/ws/notify/"`
    остаются. Без мессенджера — прежняя кнопка панели и прежний адрес «Все уведомления» в панели."""
    from apps.notify.views import pages

    user, client = _employee()
    _note(user, 1, text="Новое уведомление")
    request = RequestFactory().get("/")
    request.user = user

    assert pages.top_bar_context(request).get("bell_link") == "/messenger/notifications/", \
        "с мессенджером нет признака `bell_link`"
    home = _doc(client.get("/"))
    bell = _one(home, None, {"id": "notify-bell"})
    link = _one(home, "a", {"data-bell-link": True}, within=bell)
    assert link.attrs.get("href") == "/messenger/notifications/"
    assert _find(home, "button", {"data-bell-toggle": True}) == [], "кнопка панели осталась при ссылке"
    assert _find(home, "button", {"hx-get": "/notifications/bell/"}) == []
    assert _one(home, "span", {"id": "notify-count"}, within=bell).text.isdigit()
    _one(home, None, {"id": "notify-toast"}, within=bell)
    panel = _one(home, None, {"id": "notify-bell-panel"}, within=bell)
    assert panel.text == "" and _find(home, "li", None, within=panel) == [], "панель при ссылке не пуста"
    assert bell.attrs.get("data-ws") == "connecting"
    assert bell.attrs.get("ws-connect") == "/ws/notify/"

    panel_doc = _doc(client.get("/notifications/bell/"))
    assert _one(panel_doc, "a", {"data-bell-all": True}).attrs.get("href") == "/messenger/notifications/", \
        "«Все уведомления» в панели не ведут на вкладку"

    with sm.without_messenger():
        assert "bell_link" not in pages.top_bar_context(request), "без мессенджера остался `bell_link`"
        old = _doc(client.get("/"))
        old_bell = _one(old, None, {"id": "notify-bell"})
        button = _one(old, "button", {"data-bell-toggle": True}, within=old_bell)
        assert button.attrs.get("hx-get") == "/notifications/bell/", "прежняя кнопка панели изменилась"
        assert _find(old, None, {"data-bell-link": True}) == [], "без мессенджера осталась ссылка"
        _one(old, "span", {"id": "notify-count"}, within=old_bell)
        _one(old, None, {"id": "notify-toast"}, within=old_bell)
        _one(old, None, {"id": "notify-bell-panel"}, within=old_bell)
        old_panel = _doc(client.get("/notifications/bell/"))
        assert _one(old_panel, "a", {"data-bell-all": True}).attrs.get("href") == "/notifications/", \
            "без мессенджера «Все уведомления» ведут не на прежний список"


# --- FR-667: фрагмент потока `/notifications/list/` ----------------------------------------------------------------

def test_notify_list_fragment_50_per_page_filter_and_pages():
    """FR-667 (CONTRACT-008, 3.3, 10.2): `GET /notifications/list/` — фрагмент потока, а не страница: 50 строк
    `_row.html` на страницу, новые сверху; фильтр `f` (`""` и всё, кроме `unread`, — все; `unread` — только
    непрочитанные), `page` (неверный и за последней — первая или последняя), «Прочитать все» и страницы;
    переключатель фильтра и страницы ходят в этот же фрагмент через `hx-get`, `href` прежних ссылок не меняется;
    пустой список — `[data-empty-state="notifications"]` без пейджера и «Прочитать все»."""
    user, client = _employee()
    notes = [_note(user, index, read=(index % 3 == 0)) for index in range(120)]
    order = _newest_first(notes)
    unread = _newest_first([note for note in notes if note.read_at is None])
    assert len(order) == 120 and 50 < len(unread) <= 100, "данные теста не дают вторую страницу непрочитанных"

    response = client.get("/notifications/list/")
    assert response.status_code == 200, "/notifications/list/ недоступен"
    body = response.content.decode("utf-8")
    assert "<html" not in body.lower() and "<body" not in body.lower(), "фрагмент потока пришёл целой страницей"
    assert _rows(response) == order[:50]
    assert _rows(client.get("/notifications/list/", **support.HX)) == order[:50]

    assert _rows(client.get("/notifications/list/", {"page": "1"})) == order[:50]
    assert _rows(client.get("/notifications/list/", {"page": "2"})) == order[50:100]
    assert _rows(client.get("/notifications/list/", {"page": "3"})) == order[100:]
    assert _rows(client.get("/notifications/list/", {"page": "99"})) == order[100:], "за последней — последняя"
    assert _rows(client.get("/notifications/list/", {"page": "abc"})) == order[:50]
    assert _rows(client.get("/notifications/list/", {"page": "0"})) == order[:50]
    assert _rows(client.get("/notifications/list/", {"page": "-4"})) == order[:50]

    only = client.get("/notifications/list/", {"f": "unread"})
    assert _rows(only) == unread[:50]
    assert _rows(client.get("/notifications/list/", {"f": "unread", "page": "2"})) == unread[50:100]
    for params in ({"f": "all"}, {"f": ""}, {"f": "что-то"}):
        assert _rows(client.get("/notifications/list/", params)) == order[:50], f"фильтр {params}: ждали все"

    doc = _doc(only)
    filter_nav = _one(doc, "nav", {"data-notify-filter": True})
    links = {el.attrs["data-filter"]: el for el in _find(doc, "a", {"data-filter": True}, within=filter_nav)}
    assert set(links) == {"all", "unread"}
    assert links["all"].attrs.get("href") == "/notifications/" and links["all"].text == "Все"
    assert links["unread"].attrs.get("href") == "/notifications/?f=unread"
    assert links["all"].attrs.get("hx-get") == "/notifications/list/"
    assert links["unread"].attrs.get("hx-get") == "/notifications/list/?f=unread"
    assert links["unread"].attrs.get("aria-current") == "true" and "aria-current" not in links["all"].attrs

    read_all = _one(doc, "form", {"data-form": "read-all"})
    assert read_all.attrs.get("hx-post") == "/notifications/read-all/"
    assert "Прочитать все" in read_all.text
    assert _one(doc, "input", {"name": "f"}, within=read_all).attrs.get("value") == "unread"

    def pager(response_):
        page_doc = _doc(response_)
        nav = _one(page_doc, "nav", {"data-pager": True})
        current = _one(page_doc, None, {"data-page-current": True}, within=nav).text
        return (current, _find(page_doc, "a", {"data-page-prev": True}, within=nav),
                _find(page_doc, "a", {"data-page-next": True}, within=nav))

    current, previous, following = pager(client.get("/notifications/list/"))
    assert current == "1" and previous == [] and len(following) == 1
    assert urlsplit(following[0].attrs["href"]).path == "/notifications/", "href прежней ссылки изменился"
    assert parse_qs(urlsplit(following[0].attrs["href"]).query) == {"page": ["2"]}
    fragment = urlsplit(following[0].attrs["hx-get"])
    assert fragment.path == "/notifications/list/"
    assert parse_qs(fragment.query) == {"page": ["2"]}

    current, previous, following = pager(client.get("/notifications/list/", {"f": "unread", "page": "2"}))
    assert current == "2" and len(previous) == 1 and len(following) == 1
    back = urlsplit(previous[0].attrs["hx-get"])
    assert back.path == "/notifications/list/" and parse_qs(back.query).get("f") == ["unread"]
    assert parse_qs(back.query).get("page", ["1"]) == ["1"]
    ahead = urlsplit(following[0].attrs["hx-get"])
    assert ahead.path == "/notifications/list/"
    assert parse_qs(ahead.query) == {"f": ["unread"], "page": ["3"]}

    current, previous, following = pager(client.get("/notifications/list/", {"page": "3"}))
    assert current == "3" and len(previous) == 1 and following == [], "у последней страницы нет ссылки вперёд"

    lonely, lonely_client = _employee()
    empty = lonely_client.get("/notifications/list/")
    assert empty.status_code == 200
    empty_doc = _doc(empty)
    assert _rows(empty) == []
    assert "нет уведомлений" in _one(empty_doc, None, {"data-empty-state": "notifications"}).text.lower()
    assert _find(empty_doc, "nav", {"data-pager": True}) == []
    assert _find(empty_doc, "form", {"data-form": "read-all"}) == []


# --- FR-667: старый адрес `/notifications/` ----------------------------------------------------------------------

def test_old_notifications_address_redirects_with_f_and_page():
    """FR-667 (CONTRACT-008, 3.3, 10.2): при установленном мессенджере `GET /notifications/` — 302 на
    `/messenger/notifications/` с сохранением `f` и `page`; пустые ключи не добавляются; конечный ответ вкладки
    содержит строки той же страницы и фильтра. Без мессенджера прежняя страница 200 со строками;
    `/notifications/<id>/open/`, `/read/`, `/read-all/` и `/notifications/bell/` не меняются."""
    user, client = _employee()
    notes = [_note(user, index, text=f"Уведомление {index}", url=f"/tickets/{700 + index}/") for index in range(120)]
    order = _newest_first(notes)
    target = notes[119]   # свежее всех — колокольчик показывает последние десять

    base = client.get("/notifications/")
    assert base.status_code == 302 and base["Location"] == "/messenger/notifications/"

    filtered = client.get("/notifications/", {"f": "unread", "page": "2"})
    assert filtered.status_code == 302
    location = urlsplit(filtered["Location"])
    assert location.path == "/messenger/notifications/"
    assert parse_qs(location.query) == {"f": ["unread"], "page": ["2"]}, "302 потерял фильтр или страницу"

    assert client.get("/notifications/", {"f": "", "page": ""})["Location"] == "/messenger/notifications/", \
        "пустые ключи попали в адрес вкладки"
    assert parse_qs(urlsplit(client.get("/notifications/", {"page": "3"})["Location"]).query) == {"page": ["3"]}

    followed = client.get("/notifications/", {"f": "unread", "page": "2"}, follow=True)
    assert [code for _, code in followed.redirect_chain] == [302]
    assert urlsplit(followed.redirect_chain[-1][0]).path == "/messenger/notifications/"
    assert followed.status_code == 200, "вкладка «Уведомления» не открылась"
    assert _rows(followed) == order[50:100], "в конечном ответе вкладки не строки той же страницы"

    opened = client.get(f"/notifications/{target.pk}/open/")
    assert opened.status_code == 302 and opened["Location"] == "/tickets/819/"
    read = client.post(f"/notifications/{target.pk}/read/")
    assert read.status_code == 302 and read["Location"] == "/notifications/", "переход после «прочитано» изменился"
    read_all = client.post("/notifications/read-all/")
    assert read_all.status_code == 302 and read_all["Location"] == "/notifications/"
    bell = client.get("/notifications/bell/")
    assert bell.status_code == 200 and target.pk in _rows(bell), "панель колокольчика изменилась"

    with sm.without_messenger():
        old = client.get("/notifications/")
        assert old.status_code == 200, "без мессенджера `/notifications/` перестала быть страницей"
        assert _rows(old) == order[:50]
        old_doc = _doc(old)
        old_links = {el.attrs["data-filter"]: el
                     for el in _find(old_doc, "a", {"data-filter": True})}
        assert old_links["all"].attrs.get("href") == "/notifications/"
        assert old_links["unread"].attrs.get("href") == "/notifications/?f=unread"