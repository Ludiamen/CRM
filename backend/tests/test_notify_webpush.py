"""T-4115: подписка Web Push — сохранение, проверка адреса, список устройств (FR-324).

Сценарии спеки среза 004 о Web Push на устройстве сотрудника. Подписку создаёт представление
`POST /me/notifications/push/` (JSON `PushSubscription.toJSON()`, заголовок `X-CSRFToken`, CONTRACT-004 § 13.2);
адрес проверяет `push.check_endpoint` (§ 6.12, коды § 6.2); список и удаление — страница `/me/notifications/`
(§ 14.3) и `POST /me/notifications/push/<id>/delete/`. Push-сервис подменён помощником `webpush_capture`
(§ 5.3), сети нет. Имена кода среза 004 — внутри тестов, модели — через `support.model`.
"""
import json
import re
import secrets
import uuid
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_notify as notify
from tests.support import HX, model

pytestmark = pytest.mark.django_db

SUBSCRIBE_URL = "/me/notifications/push/"
PAGE_URL = "/me/notifications/"
HOST = "fcm.googleapis.com"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла) -------------------------------------------------------

class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = [c if isinstance(c, str) else c.text() for c in self.children]
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def inside(self, other) -> bool:
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response_or_html) -> _Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _find(root, tag=None, **attrs) -> list:
    """Элементы с тегом `tag` и атрибутами (`data_device="5"` → `data-device`); значение `True` — «атрибут есть»."""
    found = []
    for node in root.walk():
        if tag is not None and node.tag != tag:
            continue
        ok = True
        for name, expected in attrs.items():
            name = name.replace("_", "-")
            if name not in node.attrs or (expected is not True and node.attrs[name] != expected):
                ok = False
                break
        if ok:
            found.append(node)
    return found


# --- помощники только этого файла ---------------------------------------------------------------------------

class _Browser:
    """Вошедший сотрудник: клиент с проверкой CSRF (как у браузера) и номер устройства сессии."""

    def __init__(self, user, ua=support.FIREFOX_UA):
        self.user = user
        plain = support.logged_in(user, ua=ua)
        self.client = support.make_client(ua=ua, enforce_csrf_checks=True)
        self.client.cookies = plain.cookies
        self.session_key = plain.session.session_key
        self._csrf = None

    @property
    def device_id(self):
        return model("core.UserSession").objects.get(session_key=self.session_key).device_id

    def csrf(self) -> str:
        """Значение из скрытого поля страницы (так его берёт скрипт, § 13.2)."""
        if self._csrf is None:
            response = self.client.get(PAGE_URL)
            assert response.status_code == 200, f"страница {PAGE_URL}: {response.status_code}"
            fields = _find(_tree(response), "input", name="csrfmiddlewaretoken")
            assert fields, "на странице нет скрытого поля csrfmiddlewaretoken"
            self._csrf = fields[0].attrs["value"]
        return self._csrf

    def page(self, **extra):
        response = self.client.get(PAGE_URL, **extra)
        assert response.status_code == 200, f"страница {PAGE_URL}: {response.status_code}"
        return response

    def subscribe(self, endpoint, pair=None, *, body=None, with_csrf=True):
        pair = pair or notify.browser_keys()
        payload = body if body is not None else {"endpoint": endpoint, "keys": {"p256dh": pair.p256dh, "auth": pair.auth}}
        extra = {"HTTP_X_CSRFTOKEN": self.csrf()} if with_csrf else {}
        return self.client.post(SUBSCRIBE_URL, data=json.dumps(payload), content_type="application/json", **extra)

    def post(self, path, **extra):
        return self.client.post(path, HTTP_X_CSRFTOKEN=self.csrf(), **extra)


def _endpoint(host=HOST, path=None, scheme="https", port="") -> str:
    return f"{scheme}://{host}{':' + port if port else ''}/{path if path is not None else 'send/' + secrets.token_urlsafe(12)}"


def _subs(user=None):
    qs = model("notify.PushSubscription").objects.all()
    return qs.filter(user=user) if user is not None else qs


def _audit(action: str, owner=None) -> list:
    qs = model("core.AuditEvent").objects.filter(action=action)
    if owner is not None:
        qs = qs.filter(object_id=str(owner.pk))
    return list(qs.order_by("id"))


def _reject(browser, endpoint, code, *, field="endpoint"):
    """Подписка с этим адресом отклонена: 400 JSON с кодом и полем, в базе ничего нового."""
    before = _subs().count()
    response = browser.subscribe(endpoint)
    assert response.status_code == 400, f"{code}: ждали 400, получили {response.status_code}"
    data = response.json()
    assert data["ok"] is False and data["code"] == code and data["field"] == field, f"{code}: ответ {data}"
    assert data["message"], "у отказа нет текста"
    assert _subs().count() == before, f"{code}: отклонённая подписка сохранена"


def _accept(browser, endpoint):
    response = browser.subscribe(endpoint)
    assert response.status_code == 200, f"адрес принят, получили {response.status_code}: {response.content[:200]!r}"
    data = response.json()
    assert data["ok"] is True
    stored = _subs().get(pk=data["id"])
    assert stored.endpoint == endpoint
    return stored


def _waiting_webpush(user, *, text_kind="servicedesk.assigned"):
    """Уведомление и доставка Web Push, срок которой наступил (прямая запись в базу)."""
    note = model("notify.Notification").objects.create(user=user, kind=text_kind, text="Вам назначена заявка",
                                                      url="/tickets/1/", object_ref=f"servicedesk.ticket:{uuid.uuid4().int % 10**6}")
    return model("notify.Delivery").objects.create(notification=note, channel="webpush", state="waiting",
                                                   due_at=timezone.now() - timedelta(seconds=1))


# --- сохранение подписки -------------------------------------------------------------------------------------

def test_subscribe_saves_endpoint_keys_device_browser_and_platform(webpush_on):
    """FR-324: подписка через представление сохраняется с адресом, ключами, устройством сессии и браузером с
    платформой по `User-Agent` (`devices.parse_user_agent`); в журнале `notify.push_subscribed` без адреса и ключей."""
    from apps.core.services import devices

    user = support.make_employee()
    browser = _Browser(user, ua=support.CHROME_UA)
    pair, endpoint = notify.browser_keys(), _endpoint()
    response = browser.subscribe(endpoint, pair)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    row = _subs(user).get()
    assert data["id"] == row.pk
    assert (row.endpoint, row.p256dh, row.auth) == (endpoint, pair.p256dh, pair.auth)
    assert row.device_id is not None and row.device_id == browser.device_id
    expected_browser, expected_platform = devices.parse_user_agent(support.CHROME_UA)
    assert expected_browser.startswith("Chrome") and expected_platform
    assert (row.browser, row.platform) == (expected_browser, expected_platform)
    events = _audit("notify.push_subscribed", user)
    assert len(events) == 1 and events[0].actor_id == user.pk
    assert events[0].after == {"browser": expected_browser, "platform": expected_platform}
    assert endpoint not in json.dumps([events[0].before, events[0].after])


def test_subscribe_rejects_post_without_csrf_token(webpush_on):
    """FR-324: запрос без заголовка `X-CSRFToken` отклоняется проверкой CSRF (403), подписки нет; с заголовком — 200."""
    browser = _Browser(support.make_employee())
    csrf_value = browser.csrf()
    assert csrf_value
    response = browser.subscribe(_endpoint(), with_csrf=False)
    assert response.status_code == 403
    assert _subs().count() == 0
    assert browser.subscribe(_endpoint()).status_code == 200
    assert _subs().count() == 1


def test_subscribed_device_is_listed_and_push_column_becomes_available(webpush_on):
    """FR-324: после подписки устройство видно в списке `li[data-device]` (браузер, платформа, дата), `push.list_for`
    отдаёт его, а столбец `push` таблицы из недоступного (`no_subscriptions`) становится доступным."""
    from apps.notify.services import push

    user = support.make_employee()
    browser = _Browser(user, ua=support.CHROME_UA)
    before = _tree(browser.page())
    cell = _find(before, "td", data_channel="push")
    assert cell and all(c.attrs.get("data-available") == "0" and c.attrs.get("data-reason") == "no_subscriptions"
                        for c in cell), "до подписки столбец push должен быть недоступен по причине no_subscriptions"
    assert _find(before, None, data_empty_state="devices")
    sub_id = browser.subscribe(_endpoint()).json()["id"]
    assert [s.pk for s in push.list_for(user.pk)] == [sub_id]
    after = _tree(browser.page())
    items = _find(after, "li", data_device=str(sub_id))
    assert len(items) == 1
    row = items[0]
    assert _find(row, None, data_field="browser")[0].text() == _subs(user).get().browser != ""
    assert _find(row, None, data_field="platform")[0].text() == _subs(user).get().platform != ""
    assert _find(row, "time", data_at=True)
    assert not _find(after, None, data_empty_state="devices")
    cell = _find(after, "td", data_channel="push")
    assert cell and all(c.attrs.get("data-available") == "1" and c.attrs.get("data-reason", "") == "" for c in cell)


def test_subscribe_does_not_send_probe_push(webpush_on):
    """FR-324: сохранение подписки не отправляет проверочного push: к push-сервису запросов нет."""
    browser = _Browser(support.make_employee())
    with notify.webpush_capture() as capture:
        assert browser.subscribe(_endpoint()).status_code == 200
    assert capture.requests == []
    assert _subs().count() == 1


# --- проверка адреса ---------------------------------------------------------------------------------------------

def test_endpoint_not_https_is_rejected(webpush_on):
    """FR-324: адрес со схемой не `https` — отказ `bad_scheme` (поле `endpoint`), подписки нет."""
    browser = _Browser(support.make_employee())
    _reject(browser, _endpoint(scheme="http"), "bad_scheme")
    _reject(browser, f"ftp://{HOST}/send/x", "bad_scheme")


def test_endpoint_with_foreign_host_is_rejected(webpush_on):
    """FR-324: хост вне `WEBPUSH_ALLOWED_HOSTS` — `bad_host`; допустимый хост рядом принимается."""
    browser = _Browser(support.make_employee())
    _reject(browser, _endpoint(host="push.example.org"), "bad_host")
    _reject(browser, _endpoint(host="fcm.googleapis.com.example.org"), "bad_host")
    _accept(browser, _endpoint(host="updates.push.services.mozilla.com"))


def test_endpoint_evilnotify_windows_com_is_rejected(webpush_on):
    """FR-324: шаблон `*.notify.windows.com` совпадает по целому суффиксу `.notify.windows.com`: `evilnotify.windows.com`
    и сам `notify.windows.com` — `bad_host` (§ 6.12)."""
    browser = _Browser(support.make_employee())
    _reject(browser, _endpoint(host="evilnotify.windows.com"), "bad_host")
    _reject(browser, _endpoint(host="notify.windows.com"), "bad_host")


def test_endpoint_subdomain_of_notify_windows_com_is_accepted(webpush_on):
    """FR-324: поддомен `*.notify.windows.com` (любой глубины, без учёта регистра) принимается."""
    browser = _Browser(support.make_employee())
    _accept(browser, _endpoint(host="wns2-par02p.notify.windows.com", path="w/abc"))
    _accept(browser, _endpoint(host="A.B.Notify.Windows.Com"))


def test_endpoint_with_port_other_than_443_is_rejected(webpush_on):
    """FR-324: порт, отличный от 443, — `bad_port`."""
    browser = _Browser(support.make_employee())
    _reject(browser, _endpoint(port="8443"), "bad_port")
    _reject(browser, _endpoint(port="80"), "bad_port")


def test_endpoint_with_explicit_port_443_is_accepted(webpush_on):
    """FR-324: явный порт 443 допустим, как и адрес без порта."""
    browser = _Browser(support.make_employee())
    stored = _accept(browser, _endpoint(port="443"))
    assert ":443/" in stored.endpoint


def test_endpoint_with_login_or_password_is_rejected(webpush_on):
    """FR-324: логин или пароль в адресе — `has_credentials`."""
    browser = _Browser(support.make_employee())
    credentials = f"someone:{secrets.token_hex(4)}"
    _reject(browser, f"https://{credentials}@{HOST}/send/x", "has_credentials")
    _reject(browser, f"https://someone@{HOST}/send/x", "has_credentials")


def test_endpoint_longer_than_1000_is_rejected(webpush_on):
    """FR-324: адрес длиннее 1000 знаков — `too_long` (проверяется первой, даже раньше схемы); ровно 1000 принимается."""
    browser = _Browser(support.make_employee())
    prefix = f"https://{HOST}/"
    _reject(browser, prefix + "a" * (1001 - len(prefix)), "too_long")
    _reject(browser, "http://" + HOST + "/" + "a" * 1001, "too_long")
    accepted = _accept(browser, prefix + "a" * (1000 - len(prefix)))
    assert len(accepted.endpoint) == 1000


def test_endpoint_with_internal_network_address_is_rejected(webpush_on):
    """FR-324: адреса внутренней сети и сам хост — `bad_host`: сервер не ходит на внутренние адреса (SSRF)."""
    browser = _Browser(support.make_employee())
    for host in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "localhost", "[::1]", "db", "web"):
        _reject(browser, _endpoint(host=host), "bad_host")


def test_allowed_hosts_are_taken_from_setting(webpush_on, settings):
    """FR-324: список хостов читается из `settings.WEBPUSH_ALLOWED_HOSTS` при каждом запросе: хост из настройки
    принимается, прежний хост по умолчанию отклоняется; шаблон `*.хост` работает."""
    browser = _Browser(support.make_employee())
    settings.WEBPUSH_ALLOWED_HOSTS = ["push.example.test", "*.edge.example.test"]
    _accept(browser, _endpoint(host="push.example.test"))
    _accept(browser, _endpoint(host="n1.edge.example.test"))
    _reject(browser, _endpoint(host=HOST), "bad_host")
    _reject(browser, _endpoint(host="edge.example.test"), "bad_host")


def test_rejected_endpoint_saves_nothing(webpush_on):
    """FR-324: отклонённая подписка ничего не меняет: нет новой строки, чужая подписка с тем же адресом не удалена,
    свои подписки на месте, журнал без `notify.push_subscribed` и `notify.push_removed`."""
    owner, user = support.make_employee(), support.make_employee()
    foreign = notify.subscribe(owner)
    own = notify.subscribe(user)
    browser = _Browser(user)
    events_before = len(_audit("notify.push_subscribed")), len(_audit("notify.push_removed"))
    _reject(browser, _endpoint(scheme="http"), "bad_scheme")
    pair = notify.browser_keys()
    response = browser.subscribe(foreign.endpoint, body={"endpoint": foreign.endpoint,
                                                         "keys": {"p256dh": "", "auth": pair.auth}})
    assert response.status_code == 400 and response.json()["code"] == "bad_keys"
    assert response.json()["field"] == "p256dh"
    response = browser.subscribe(foreign.endpoint, body={"endpoint": foreign.endpoint,
                                                         "keys": {"p256dh": pair.p256dh, "auth": "не base64url!"}})
    assert response.status_code == 400 and response.json()["code"] == "bad_keys" and response.json()["field"] == "auth"
    assert {s.pk for s in _subs()} == {foreign.pk, own.pk}
    assert _subs(owner).get().pk == foreign.pk, "подписка прежнего владельца удалена отклонённым запросом"
    assert (len(_audit("notify.push_subscribed")), len(_audit("notify.push_removed"))) == events_before


def test_same_endpoint_is_removed_from_other_account(webpush_on):
    """FR-324: адрес, уже подписанный другой учётной записью, переходит новому владельцу: у прежнего подписка удалена
    (журнал `notify.push_removed` от системы, причина `moved`, объект — прежний владелец), строка с адресом одна."""
    first, second = support.make_employee(), support.make_employee()
    old = notify.subscribe(first)
    endpoint = old.endpoint
    browser = _Browser(second)
    response = browser.subscribe(endpoint)
    assert response.status_code == 200
    assert list(_subs(first)) == []
    rows = list(_subs().filter(endpoint=endpoint))
    assert len(rows) == 1 and rows[0].user_id == second.pk and rows[0].pk == response.json()["id"]
    removed = _audit("notify.push_removed", first)
    assert len(removed) == 1 and removed[0].actor_id is None and removed[0].after == {"reason": "moved"}
    assert endpoint not in json.dumps([removed[0].before, removed[0].after])
    assert len(_audit("notify.push_subscribed", second)) == 1


def test_eleventh_subscription_removes_the_oldest(webpush_on):
    """FR-324: больше 10 подписок — самая старая (по `created_at`, при равенстве по номеру) удаляется, в журнале
    `notify.push_removed` с причиной `limit`; новая сохранена, подписок остаётся 10."""
    user = support.make_employee()
    subs = [notify.subscribe(user) for _ in range(10)]
    base = timezone.now() - timedelta(days=10)
    for index, sub in enumerate(subs):
        _subs().filter(pk=sub.pk).update(created_at=base + timedelta(hours=index))
    oldest = subs[4]
    _subs().filter(pk=oldest.pk).update(created_at=base - timedelta(days=1))
    browser = _Browser(user)
    response = browser.subscribe(_endpoint())
    assert response.status_code == 200
    ids = {s.pk for s in _subs(user)}
    assert len(ids) == 10 and oldest.pk not in ids and response.json()["id"] in ids
    assert {s.pk for s in subs} - {oldest.pk} <= ids
    removed = [e for e in _audit("notify.push_removed", user) if e.after == {"reason": "limit"}]
    assert len(removed) == 1 and removed[0].actor_id is None
    # равный `created_at` у двух самых старых: уходит с меньшим номером
    twins = sorted([subs[7], subs[2]], key=lambda s: s.pk)
    for twin in twins:
        _subs().filter(pk=twin.pk).update(created_at=base - timedelta(days=2))
    assert browser.subscribe(_endpoint()).status_code == 200
    ids = {s.pk for s in _subs(user)}
    assert len(ids) == 10 and twins[0].pk not in ids and twins[1].pk in ids


# --- устройство -------------------------------------------------------------------------------------------------

def test_subscription_is_bound_to_session_device(webpush_on):
    """FR-324: подписка привязана к устройству сессии (`UserSession.device_id`), а не к номеру из тела запроса;
    у второго входа сотрудника — своё устройство; удаление устройства каскадом удаляет его подписку."""
    user = support.make_employee()
    here, there = _Browser(user), _Browser(user, ua=support.CHROME_UA)
    assert here.device_id is not None and there.device_id is not None and here.device_id != there.device_id
    pair, endpoint = notify.browser_keys(), _endpoint()
    body = {"endpoint": endpoint, "keys": {"p256dh": pair.p256dh, "auth": pair.auth}, "device": there.device_id,
            "device_id": there.device_id}
    first = here.subscribe(endpoint, body=body)
    assert first.status_code == 200
    assert _subs().get(pk=first.json()["id"]).device_id == here.device_id
    second = there.subscribe(_endpoint())
    assert second.status_code == 200
    assert _subs().get(pk=second.json()["id"]).device_id == there.device_id
    model("core.KnownDevice").objects.filter(pk=here.device_id).delete()
    assert not _subs().filter(pk=first.json()["id"]).exists(), "подписка удалённого устройства осталась"
    assert _subs().filter(pk=second.json()["id"]).exists()


def test_subscription_without_device_cookie_is_saved_without_device(webpush_on):
    """FR-324: у сессии без устройства (нет куки устройства) подписка сохраняется с пустым `device`, браузер и
    платформа по `User-Agent` всё равно записаны."""
    user = support.make_employee()
    browser = _Browser(user, ua=support.CHROME_UA)
    model("core.UserSession").objects.filter(session_key=browser.session_key).update(device_id=None)
    assert browser.device_id is None
    response = browser.subscribe(_endpoint())
    assert response.status_code == 200
    row = _subs().get(pk=response.json()["id"])
    assert row.device_id is None
    assert row.browser.startswith("Chrome") and row.platform


# --- список и удаление ------------------------------------------------------------------------------------------------

def test_user_deletes_own_subscription_from_list(webpush_on):
    """FR-324: сотрудник удаляет своё устройство из списка: обычный POST — 302 на `/me/notifications/` и
    `[role=status]` «Устройство удалено.»; НХ — 200 фрагмент `#notify-devices` без удалённого; журнал
    `notify.push_removed` от самого сотрудника, без причины; другая подписка остаётся."""
    user = support.make_employee()
    browser = _Browser(user)
    first, second, third = (browser.subscribe(_endpoint()).json()["id"] for _ in range(3))
    response = browser.post(f"/me/notifications/push/{first}/delete/")
    assert response.status_code == 302 and response["Location"] == PAGE_URL
    assert not _subs().filter(pk=first).exists() and _subs().filter(pk__in=[second, third]).count() == 2
    page = browser.client.get(PAGE_URL)
    status = _find(_tree(page), None, role="status")
    assert status and any("Устройство удалено." in s.text() for s in status)
    assert not _find(_tree(page), "li", data_device=str(first))
    removed = _audit("notify.push_removed", user)
    assert len(removed) == 1 and removed[0].actor_id == user.pk and removed[0].after == {}
    fragment = browser.client.post(f"/me/notifications/push/{second}/delete/", HTTP_X_CSRFTOKEN=browser.csrf(), **HX)
    assert fragment.status_code == 200
    tree = _tree(fragment)
    assert _find(tree, None, id="notify-devices")
    assert not _find(tree, "li", data_device=str(second)) and _find(tree, "li", data_device=str(third))
    assert not _subs().filter(pk=second).exists()


def test_deleted_device_gets_no_push_and_other_device_still_gets(webpush_on):
    """FR-324: после удаления устройства push на него не уходит, на оставшееся — уходит: запрос ровно один, на
    адрес оставшейся подписки, и нагрузка расшифровывается её ключами."""
    from apps.notify.services import delivery

    user = support.make_employee()
    browser = _Browser(user)
    pair_a, pair_b = notify.browser_keys(), notify.browser_keys()
    endpoint_a, endpoint_b = _endpoint(), _endpoint()
    id_a = browser.subscribe(endpoint_a, pair_a).json()["id"]
    assert browser.subscribe(endpoint_b, pair_b).status_code == 200
    assert browser.post(f"/me/notifications/push/{id_a}/delete/").status_code == 302
    row = _waiting_webpush(user)
    with notify.webpush_capture() as capture:
        outcome = delivery.send_delivery(row.pk)
    assert outcome == "sent"
    assert [r.url for r in capture.requests] == [endpoint_b]
    payload = capture.decrypt(capture.requests[0], pair_b)
    assert set(payload) == {"title", "url", "tag"}


def test_deleting_foreign_subscription_returns_404(webpush_on):
    """FR-324: чужая и несуществующая подписка при удалении — 404, чужая остаётся, журнала удаления нет."""
    owner, other = support.make_employee(), support.make_employee()
    foreign = notify.subscribe(owner)
    browser = _Browser(other)
    assert browser.post(f"/me/notifications/push/{foreign.pk}/delete/").status_code == 404
    assert browser.post("/me/notifications/push/987654321/delete/").status_code == 404
    assert _subs(owner).get().pk == foreign.pk
    assert _audit("notify.push_removed") == []


# --- кнопка и сервис-воркер -------------------------------------------------------------------------------------------------

def test_subscribe_button_shown_when_webpush_enabled(webpush_on, settings):
    """FR-324: при включённом Web Push в разделе `[data-section="push"]` с `data-web-push="on"` есть кнопка
    `push-subscribe` с открытым ключом VAPID, адресом подписки и адресом сервис-воркера; текста отключения нет."""
    browser = _Browser(support.make_employee())
    tree = _tree(browser.page())
    section = _find(tree, None, data_section="push")
    assert len(section) == 1 and section[0].attrs.get("data-web-push") == "on"
    buttons = [b for b in _find(tree, "button", data_action="push-subscribe") if b.inside(section[0])]
    assert len(buttons) == 1
    button = buttons[0]
    assert button.attrs["data-vapid-public"] == settings.VAPID_PUBLIC_KEY
    assert button.attrs["data-subscribe-url"] == SUBSCRIBE_URL and button.attrs["data-sw-url"] == "/sw.js"
    assert button.attrs.get("type") == "button"
    assert not _find(tree, None, data_push_disabled_text=True)


def test_subscribe_button_absent_and_disabled_text_shown_when_webpush_disabled(settings):
    """FR-324: при выключенном Web Push кнопки `push-subscribe` нет, раздел с `data-web-push="off"` показывает
    `[data-push-disabled-text]`; прямой запрос подписки отклонён кодом `channel_disabled` и ничего не сохраняет."""
    settings.VAPID_PRIVATE_KEY = settings.VAPID_PUBLIC_KEY = ""
    user = support.make_employee()
    browser = _Browser(user)
    tree = _tree(browser.page())
    section = _find(tree, None, data_section="push")
    assert len(section) == 1 and section[0].attrs.get("data-web-push") == "off"
    assert not _find(tree, "button", data_action="push-subscribe")
    assert [t for t in _find(tree, None, data_push_disabled_text=True) if t.text()]
    response = browser.subscribe(_endpoint())
    assert response.status_code == 400
    data = response.json()
    assert data["ok"] is False and data["code"] == "channel_disabled"
    assert _subs().count() == 0


def test_sw_js_served_as_javascript_with_no_store_and_without_login():
    """FR-324: `/sw.js` без входа — 200, `Content-Type: application/javascript`, `Cache-Control: no-store`, в теле
    обработчики `push` и `notificationclick`; POST — 405."""
    guest = support.make_client()
    response = guest.get("/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].split(";")[0].strip() == "application/javascript"
    assert "no-store" in response["Cache-Control"]
    body = b"".join(response.streaming_content) if response.streaming else response.content
    text = body.decode("utf-8")
    assert re.search(r"""(addEventListener\(\s*['"]push['"]|onpush\s*=)""", text), "в сервис-воркере нет обработчика push"
    assert re.search(r"""(addEventListener\(\s*['"]notificationclick['"]|onnotificationclick\s*=)""", text), \
        "нет обработчика notificationclick"
    assert guest.post("/sw.js").status_code == 405
