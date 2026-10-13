"""T-4126: «Мои уведомления» — устройства, привязки, журнал, карточка (FR-323, FR-324, FR-325, FR-326, FR-336, FR-341,
FR-342). Сценарии 4-6 и 8 спеки.

Страница `/me/notifications/` и её маршруты (CONTRACT-004 § 13.2, зацепки § 14.3), службы `push` (§ 6.12), `binding`
(§ 6.13), `prefs.save` (§ 6.4), журнал (§ 9) и раздел карточки профиля (`card_sections`). Разметку читает разборщик
этого файла по зацепкам `data-*` § 14.3; журнал — `AuditEvent.objects.filter(action=…)` (§ 9). Имена кода среза 004
берутся внутри тестов или через `support.model`; Web Push и боты — настоящие (`webpush_on`, `bots_on`), подмен нет.
Секреты (ключи VAPID, токены ботов, ключи браузера) в проверках не печатаются: сравнения идут через логические значения.
"""
import json
import re
from datetime import time as clock_time, timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support, support_notify as notify, support_org, support_servicedesk
from tests.support import CHROME_UA, FIREFOX_UA, HX, model

pytestmark = pytest.mark.django_db

CLIENT_IP = "198.51.100.7"      # адрес клиента `support.make_client` по умолчанию
KIND = "servicedesk.assigned"   # вид со всеми пятью каналами по умолчанию (§ 3.2); виден участнику очереди (§ 4.3 `available`)
KIND_TITLE = "Мне назначили заявку"
ME = "/me/notifications/"


# --- помощники только этого файла ------------------------------------------------------------------------

class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children: list = []
        self.chunks: list[str] = []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def find_all(self, tag=None, **attrs):
        """Потомки с тегом `tag` и атрибутами (в именах `_` вместо `-`; значение `True` — «есть»)."""
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        found = []
        for node in self.walk():
            if node is self or (tag is not None and node.tag != tag):
                continue
            if all((name in node.attrs) if value is True else node.attrs.get(name) == value
                   for name, value in wanted.items()):
                found.append(node)
        return found

    def find(self, tag=None, **attrs):
        found = self.find_all(tag, **attrs)
        return found[0] if found else None

    def text(self) -> str:
        parts = list(self.chunks)
        for child in self.children:
            parts.append(child.text())
        return " ".join("".join(parts).split())

    def has_ancestor(self, **attrs) -> bool:
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        node = self.parent
        while node is not None:
            if all(node.attrs.get(name) == value for name, value in wanted.items()):
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.root = _Node("#root", [], None)
        self._current = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self._current)
        self._current.children.append(node)
        if tag not in self._VOID:
            self._current = node

    def handle_startendtag(self, tag, attrs):
        self._current.children.append(_Node(tag, attrs, self._current))

    def handle_endtag(self, tag):
        node = self._current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._current = node.parent

    def handle_data(self, data):
        self._current.chunks.append(data)


def _page(response_or_text) -> _Node:
    text = response_or_text if isinstance(response_or_text, str) else response_or_text.content.decode("utf-8")
    tree = _Tree()
    tree.feed(text)
    return tree.root


def _body(response) -> str:
    return response.content.decode("utf-8")


def _block(page, channel):
    """Корень блока привязки `#notify-binding-<канал>` (§ 14.3)."""
    return page.find(id=f"notify-binding-{channel}")


def _form_goes_to(form, path: str) -> bool:
    return form is not None and path in (form.attrs.get("action"), form.attrs.get("hx-post"))


def _checked_cells(page) -> list[str]:
    """Значения отмеченных ячеек таблицы (`input[name=cell][checked]`): так форма ушла бы без правок."""
    return [node.attrs["value"] for node in page.find_all("input", name="cell") if "checked" in node.attrs]


def _post_table(client, cells, **extra):
    return client.post(ME, {"table": "1", "cell": list(cells), **extra})


def _queue_member():
    """Сотрудник — прямой участник очереди (ему виден вид `servicedesk.assigned`, § 4.3 `available`), как `_member()`
    в test_notify_prefs.py."""
    user = support.make_employee()
    support_org.make_member(user, support_servicedesk.make_queue().unit)
    return user


def _events(action: str, user=None) -> list:
    found = model("core.AuditEvent").objects.filter(action=action)
    if user is not None:
        found = found.filter(object_id=str(user.pk))
    return list(found.order_by("id"))


def _dump(event) -> str:
    return json.dumps([event.before, event.after, event.action, event.object_type, event.object_id], ensure_ascii=False)


def _chrome_browser() -> tuple[str, str]:
    from apps.core.services import devices
    return devices.parse_user_agent(CHROME_UA)


def _save_device(user, user_agent: str = CHROME_UA, *, host: str = "fcm.googleapis.com", keys=None):
    """Подписка Web Push сервисом `push.save` с заданным User-Agent (помощник `subscribe` его не принимает)."""
    from apps.notify.services import push
    pair = keys or notify.browser_keys()
    return push.save(user, endpoint=f"https://{host}/push/{notify.browser_keys().p256dh[:20]}",
                     p256dh=pair.p256dh, auth=pair.auth, user_agent=user_agent)


def _bind_direct(user, channel: str, chat_id: str):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=chat_id)


# --- устройства (FR-324) ---------------------------------------------------------------------------------

def test_device_list_shows_browser_platform_and_date_of_own_subscriptions(webpush_on):
    """FR-324: список «#notify-devices» показывает свои подписки, новые сверху: браузер, платформу и дату создания
    (`[data-field=browser]`, `[data-field=platform]`, `time[data-at]`), у каждой — форма удаления на её номер."""
    from apps.core.services import devices
    user = support.make_employee()
    old = _save_device(user, FIREFOX_UA)
    new = _save_device(user, CHROME_UA)
    sub_model = model("notify.PushSubscription")
    sub_model.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
    response = support.logged_in(user).get(ME)
    assert response.status_code == 200
    page = _page(response)
    root = page.find(id="notify-devices")
    assert root is not None, "нет #notify-devices"
    rows = root.find_all("li", data_device=True)
    assert [row.attrs["data-device"] for row in rows] == [str(new.pk), str(old.pk)], "новые сверху"
    for row, ua in zip(rows, (CHROME_UA, FIREFOX_UA)):
        browser, platform = devices.parse_user_agent(ua)
        assert row.find(**{"data_field": "browser"}).text() == browser
        assert row.find(**{"data_field": "platform"}).text() == platform
        assert row.find("time", data_at=True) is not None, "нет даты подписки"
        form = row.find("form", data_form="device-delete")
        assert _form_goes_to(form, f"/me/notifications/push/{row.attrs['data-device']}/delete/")
        assert form.find("button", data_action="device-delete") is not None
    assert root.find(data_empty_state=True) is None


def test_device_list_does_not_show_foreign_subscriptions(webpush_on):
    """FR-324, FR-342: чужих подписок в списке нет (ни строки, ни номера в форме удаления); у сотрудника без подписок —
    `[data-empty-state=devices]`."""
    user = support.make_employee()
    other = support.make_employee()
    foreign = _save_device(other, CHROME_UA)
    client = support.logged_in(user)
    page = _page(client.get(ME))
    root = page.find(id="notify-devices")
    assert root is not None
    assert not root.find_all("li", data_device=True), "чужая подписка попала в список"
    assert root.find(data_empty_state="devices") is not None
    own = _save_device(user, FIREFOX_UA)
    page = _page(client.get(ME))
    shown = [row.attrs["data-device"] for row in page.find(id="notify-devices").find_all("li", data_device=True)]
    assert shown == [str(own.pk)]
    leaked = f"/me/notifications/push/{foreign.pk}/delete/" in _body(client.get(ME))
    assert not leaked, "форма удаления чужой подписки на странице"


def test_delete_own_device_keeps_second_device(webpush_on):
    """FR-324: удаление своего устройства (НХ) — 200 фрагмент `#notify-devices` без удалённого; вторая подписка цела,
    в базе осталась только она."""
    user = support.make_employee()
    first = _save_device(user, CHROME_UA)
    second = _save_device(user, FIREFOX_UA, host="updates.push.services.mozilla.com")
    client = support.logged_in(user)
    response = client.post(f"/me/notifications/push/{first.pk}/delete/", **HX)
    assert response.status_code == 200
    html = _body(response)
    assert "<html" not in html.lower(), "ответ НХ — фрагмент"
    fragment = _page(html)
    root = fragment.find(id="notify-devices") or (fragment if fragment.attrs.get("id") == "notify-devices" else None)
    assert root is not None, "в ответе нет #notify-devices"
    assert [row.attrs["data-device"] for row in root.find_all("li", data_device=True)] == [str(second.pk)]
    pks = set(model("notify.PushSubscription").objects.filter(user=user).values_list("pk", flat=True))
    assert pks == {second.pk}


def test_delete_foreign_device_returns_404(webpush_on):
    """FR-324, FR-342: чужая и несуществующая подписка — 404 (не 403), запись цела, журнала нет."""
    user = support.make_employee()
    other = support.make_employee()
    foreign = _save_device(other, CHROME_UA)
    removed_before = len(_events("notify.push_removed"))
    client = support.logged_in(user)
    assert client.post(f"/me/notifications/push/{foreign.pk}/delete/").status_code == 404
    assert client.post(f"/me/notifications/push/{foreign.pk}/delete/", **HX).status_code == 404
    missing = foreign.pk + 1000
    assert client.post(f"/me/notifications/push/{missing}/delete/").status_code == 404
    assert model("notify.PushSubscription").objects.filter(pk=foreign.pk, user=other).exists()
    assert len(_events("notify.push_removed")) == removed_before


# --- кнопки push (FR-324, FR-336) ------------------------------------------------------------------------

def test_push_button_shown_when_web_push_enabled(webpush_on, settings):
    """FR-324, FR-336: Web Push включён и ключи заданы — `[data-section=push][data-web-push=on]`, кнопка
    «Включить push на этом устройстве» (`push-subscribe`) с открытым ключом, адресами подписки и сервис-воркера;
    кнопка разрешения (`push-permission`) тоже на месте, текста «отключён администратором» нет; закрытого ключа нет."""
    response = support.logged_in(support.make_employee()).get(ME)
    assert response.status_code == 200
    html = _body(response)
    page = _page(html)
    section = page.find(data_section="push")
    assert section is not None and section.attrs.get("data-web-push") == "on"
    subscribe = section.find("button", type="button", data_action="push-subscribe")
    assert subscribe is not None, "нет кнопки push-subscribe"
    assert subscribe.attrs.get("data-vapid-public") == settings.VAPID_PUBLIC_KEY
    assert subscribe.attrs.get("data-subscribe-url") == "/me/notifications/push/"
    assert subscribe.attrs.get("data-sw-url") == "/sw.js"
    assert section.find("button", type="button", data_action="push-permission") is not None
    assert section.find(data_push_disabled_text=True) is None
    leaked = settings.VAPID_PRIVATE_KEY in html
    assert not leaked, "закрытый ключ VAPID на странице"


def test_push_button_hidden_and_disabled_by_admin_text_shown_when_web_push_off(settings):
    """FR-336: Web Push выключен администратором (и включён, но без ключей) — `data-web-push=off`, кнопки
    `push-subscribe` нет, есть `[data-push-disabled-text]` «Push при закрытой вкладке отключён администратором»;
    кнопка `push-permission` остаётся (решение 34 задач)."""
    user = support.make_employee()
    client = support.logged_in(user)
    settings_model = model("notify.NotifySettings")

    def check():
        page = _page(client.get(ME))
        section = page.find(data_section="push")
        assert section is not None and section.attrs.get("data-web-push") == "off"
        assert section.find("button", data_action="push-subscribe") is None
        assert page.find("button", data_action="push-subscribe") is None
        text = section.find(data_push_disabled_text=True)
        assert text is not None and "Push при закрытой вкладке отключён администратором" in text.text()
        assert section.find("button", type="button", data_action="push-permission") is not None

    settings_model.objects.update_or_create(pk=1, defaults={"webpush_enabled": False})
    check()
    settings.VAPID_PRIVATE_KEY = ""
    settings.VAPID_PUBLIC_KEY = ""
    settings_model.objects.update_or_create(pk=1, defaults={"webpush_enabled": True})
    check()


# --- привязки Telegram и MAX (FR-325, FR-326, FR-336) ----------------------------------------------------

def test_bind_button_shown_for_enabled_unbound_telegram_and_max(bots_on):
    """FR-325: канал включён, токен задан, привязки нет — блок `#notify-binding-<канал>[data-state=unbound]` с формой
    `bind` на `/me/notifications/bind/<канал>/` и кнопкой «Привязать»; ни кода, ни кнопки «Отвязать», ни текста
    «Привязан» нет."""
    page = _page(support.logged_in(support.make_employee()).get(ME))
    for channel in ("telegram", "max"):
        block = _block(page, channel)
        assert block is not None, f"нет блока {channel}"
        assert block.attrs.get("data-channel") == channel and block.attrs.get("data-state") == "unbound"
        form = block.find("form", data_form="bind")
        assert _form_goes_to(form, f"/me/notifications/bind/{channel}/")
        button = form.find("button", data_action="bind")
        assert button is not None and "Привязать" in button.text()
        assert block.find(data_bound=True) is None
        assert block.find("form", data_form="unbind") is None and block.find("button", data_action="unbind") is None
        assert block.find(data_bind_code=True) is None, "код показан без нажатия"
        assert block.find(data_disabled_text=True) is None


def test_bound_channel_shows_bound_status_and_unbind_button(bots_on):
    """FR-325, FR-326: привязанный канал — `[data-state=bound]`, `[data-bound]` «Привязан», форма `unbind` с кнопкой
    «Отвязать», кнопки «Привязать» нет, идентификатора чата нет; отвязка НХ — блок в состоянии `unbound`, привязка
    удалена, соседний канал цел; обычный POST — 302 и сообщение «MAX отвязан.»."""
    user = support.make_employee()
    telegram_chat, max_chat = "5550123456", "7770123456"
    _bind_direct(user, "telegram", telegram_chat)
    _bind_direct(user, "max", max_chat)
    client = support.logged_in(user)
    response = client.get(ME)
    html = _body(response)
    page = _page(html)
    for channel in ("telegram", "max"):
        block = _block(page, channel)
        assert block is not None and block.attrs.get("data-state") == "bound"
        bound = block.find(data_bound=True)
        assert bound is not None and "Привязан" in bound.text()
        form = block.find("form", data_form="unbind")
        assert _form_goes_to(form, f"/me/notifications/unbind/{channel}/")
        button = form.find("button", data_action="unbind")
        assert button is not None and "Отвязать" in button.text()
        assert block.find("button", data_action="bind") is None and block.find("form", data_form="bind") is None
        assert block.find(data_bind_code=True) is None and block.find("a", data_bot_link=True) is None
    leaked = telegram_chat in html or max_chat in html
    assert not leaked, "идентификатор чата на странице"
    # отвязка Telegram (НХ)
    unbound = client.post("/me/notifications/unbind/telegram/", **HX)
    assert unbound.status_code == 200
    fragment = _page(unbound)
    block = fragment.find(id="notify-binding-telegram")
    assert block is not None and block.attrs.get("data-state") == "unbound"
    assert block.find("form", data_form="unbind") is None
    links = model("notify.ChatBinding").objects.filter(user=user)
    assert [item.channel for item in links] == ["max"], "отвязан должен быть только Telegram"
    # отвязка MAX (обычный POST)
    plain = client.post("/me/notifications/unbind/max/")
    assert plain.status_code == 302 and plain["Location"] == ME
    flashes = _page(client.get(ME)).find_all(role="status")
    assert any("MAX отвязан" in node.text() for node in flashes), "нет сообщения «MAX отвязан.»"
    assert not any("Telegram отвязан" in node.text() for node in flashes), "НХ-отвязка оставила сообщение (п. 22 (б))"
    assert not model("notify.ChatBinding").objects.filter(user=user).exists()


def test_disabled_or_tokenless_channel_shows_disabled_text_without_buttons(bots_on, settings):
    """FR-336 (решение E24, сценарий 6): канал выключен администратором (Telegram) или без токена (MAX) —
    `[data-state=disabled]` с `[data-disabled-text]` «Канал отключён администратором», без кнопок «Привязать» и
    «Отвязать» — и у привязанного сотрудника, и у непривязанного; привязка сохранена."""
    bound_user = support.make_employee()
    free_user = support.make_employee()
    _bind_direct(bound_user, "telegram", "5550000001")
    _bind_direct(bound_user, "max", "7770000001")
    model("notify.NotifySettings").objects.filter(pk=1).update(telegram_enabled=False)
    settings.MAX_BOT_TOKEN = ""
    for user in (bound_user, free_user):
        page = _page(support.logged_in(user).get(ME))
        for channel in ("telegram", "max"):
            block = _block(page, channel)
            assert block is not None and block.attrs.get("data-state") == "disabled", (user.pk, channel)
            text = block.find(data_disabled_text=True)
            assert text is not None and "Канал отключён администратором" in text.text()
            assert block.find("button", data_action="bind") is None
            assert block.find("button", data_action="unbind") is None
            assert block.find("form", data_form="bind") is None and block.find("form", data_form="unbind") is None
    assert model("notify.ChatBinding").objects.filter(user=bound_user).count() == 2, "привязки должны сохраниться"


# --- журнал (FR-341) -------------------------------------------------------------------------------------

def test_audit_records_changed_cells_and_quiet_hours_as_before_after_in_russian():
    """FR-341: сохранение таблицы — одна запись `notify.user_settings_changed` от сотрудника с `ip` запроса: в `cells`
    только изменённый вид (название вида, внешние каналы в порядке каталога, без `portal`), тихие часы — отдельной
    записью с `quiet_mode`, `own_days`, `own_start`, `own_end`; русские подписи ключей и значений — `audit_labels()`."""
    from apps.notify import audit_labels as labels
    user = _queue_member()
    client = support.logged_in(user)
    cells = _checked_cells(_page(client.get(ME)))
    assert f"{KIND}:email" in cells and f"{KIND}:push" in cells
    response = _post_table(client, [cell for cell in cells if cell != f"{KIND}:email"])
    assert response.status_code == 302 and response["Location"] == ME
    saved = _events("notify.user_settings_changed", user)
    assert len(saved) == 1, "одна запись на сохранение"
    event = saved[0]
    assert event.actor_id == user.pk and event.object_type == "user" and event.ip == CLIENT_IP
    assert set(event.after) == {"cells"} and set(event.before) == {"cells"}
    assert set(event.after["cells"]) == {KIND_TITLE} and set(event.before["cells"]) == {KIND_TITLE}
    assert event.before["cells"][KIND_TITLE] == ["email", "push", "telegram", "max"]
    assert event.after["cells"][KIND_TITLE] == ["push", "telegram", "max"]
    # тихие часы
    response = client.post(ME, {"quiet_mode": "own", "own_days": ["0", "1", "2", "3", "4"],
                                "own_start": "20:00", "own_end": "08:00"})
    assert response.status_code == 302
    saved = _events("notify.user_settings_changed", user)
    assert len(saved) == 2
    quiet = saved[1]
    assert quiet.actor_id == user.pk and quiet.ip == CLIENT_IP
    assert quiet.after == {"quiet_mode": "own", "own_days": [0, 1, 2, 3, 4], "own_start": "20:00", "own_end": "08:00"}
    assert quiet.before == {"quiet_mode": "calendar", "own_days": [], "own_start": None, "own_end": None}
    assert "cells" not in quiet.before and "cells" not in quiet.after
    assert set(quiet.before) <= {"quiet_mode", "own_days", "own_start", "own_end"}
    # русские подписи
    registered = labels.audit_labels()
    assert set(registered) == {"actions", "fields", "object_types", "values"}
    assert registered["actions"]["notify.user_settings_changed"] == "Личные настройки уведомлений изменены"
    for field in ("cells", "quiet_mode", "own_days", "own_start", "own_end"):
        assert registered["fields"].get(field), f"нет русской подписи ключа {field}"
        assert re.search("[а-яА-Я]", registered["fields"][field])
    assert registered["values"]["quiet_mode"] == {"calendar": "по рабочему календарю компании",
                                                  "own": "свои часы", "none": "без тихих часов"}
    assert re.search("[а-яА-Я]", KIND_TITLE) and KIND_TITLE in _dump(event)


def test_audit_of_push_subscription_has_no_endpoint_or_keys(webpush_on):
    """FR-341: подписка через `POST /me/notifications/push/` — запись `notify.push_subscribed` от сотрудника: `before`
    пуст, `after` — только браузер и платформа (как их читает `parse_user_agent`); адреса подписки и ключей браузера в
    записи нет."""
    user = support.make_employee()
    pair = notify.browser_keys()
    address = f"https://fcm.googleapis.com/fcm/send/{notify.browser_keys().p256dh[:24]}"
    client = support.logged_in(user)
    response = client.post("/me/notifications/push/",
                           json.dumps({"endpoint": address, "keys": {"p256dh": pair.p256dh, "auth": pair.auth}}),
                           content_type="application/json", HTTP_USER_AGENT=CHROME_UA)
    assert response.status_code == 200 and response.json().get("ok") is True
    saved = _events("notify.push_subscribed", user)
    assert len(saved) == 1
    event = saved[0]
    browser, platform = _chrome_browser()
    assert event.actor_id == user.pk and event.object_type == "user" and event.object_id == str(user.pk)
    assert event.ip == CLIENT_IP
    assert event.before == {} and event.after == {"browser": browser, "platform": platform}
    dump = _dump(event)
    leaked = any(part in dump for part in (address, "fcm.googleapis.com", pair.p256dh, pair.auth))
    assert not leaked, "в записи журнала адрес подписки или ключи браузера"


def test_audit_of_channel_bind_has_no_chat_id(bots_on):
    """FR-341: привязка канала — запись `notify.channel_bound` от самого сотрудника без `ip`, `before` `{"bound": false}`,
    `after` — канал и `bound`; при замене чата — `before` с каналом и `bound: true`; идентификаторов чатов в записях нет."""
    from apps.notify.services import binding
    user = support.make_employee()
    first_chat, second_chat = "5550999001", "5550999002"
    binding.bind(user.pk, "telegram", first_chat)
    saved = _events("notify.channel_bound", user)
    assert len(saved) == 1
    event = saved[0]
    assert event.actor_id == user.pk and event.object_type == "user" and event.ip is None
    assert event.before == {"bound": False} and event.after == {"channel": "telegram", "bound": True}
    binding.bind(user.pk, "telegram", second_chat)
    saved = _events("notify.channel_bound", user)
    assert len(saved) == 2
    assert saved[1].before == {"channel": "telegram", "bound": True}
    assert saved[1].after == {"channel": "telegram", "bound": True}
    dump = _dump(saved[0]) + _dump(saved[1])
    leaked = first_chat in dump or second_chat in dump
    assert not leaked, "идентификатор чата в записи журнала"


def test_audit_not_written_when_nothing_changed(bots_on):
    """FR-341: сохранение без изменений (та же таблица, режим «по календарю») и отвязка непривязанного канала записей
    не дают; строка `UserNotifySettings` не создаётся; повтор того же сохранения после изменения — тоже без записи."""
    user = _queue_member()
    client = support.logged_in(user)
    cells = _checked_cells(_page(client.get(ME)))
    assert f"{KIND}:email" in cells, "на странице нет отмеченных ячеек вида сервис-деска"
    assert _post_table(client, cells, quiet_mode="calendar").status_code == 302
    assert not _events("notify.user_settings_changed", user)
    assert not model("notify.UserNotifySettings").objects.filter(user=user).exists()
    assert client.post("/me/notifications/unbind/telegram/").status_code == 302
    assert not _events("notify.channel_unbound", user)
    changed = [cell for cell in cells if cell != f"{KIND}:email"]
    assert _post_table(client, changed).status_code == 302
    assert len(_events("notify.user_settings_changed", user)) == 1
    assert _post_table(client, changed).status_code == 302
    assert len(_events("notify.user_settings_changed", user)) == 1, "повтор без изменений записан в журнал"


# --- карточка профиля (FR-342) ---------------------------------------------------------------------------

def test_profile_card_shows_my_notifications_section_only_to_owner():
    """FR-342: в своей карточке (`/me/` и `/staff/<свой номер>/`) во вкладке «Профиль» есть
    `section[data-section=notifications]` со ссылкой `a[data-action=my-notifications]` «Мои уведомления» на
    `/me/notifications/`."""
    user = support.make_with_permissions("staff.view")
    client = support.logged_in(user)
    for path in ("/me/", f"/staff/{user.pk}/"):
        response = client.get(path, follow=True)
        assert response.status_code == 200, path
        page = _page(response)
        sections = page.find_all("section", data_section="notifications")
        assert len(sections) == 1, f"{path}: раздел «Мои уведомления» должен быть один"
        link = sections[0].find("a", data_action="my-notifications")
        assert link is not None and link.attrs.get("href") == ME and "Мои уведомления" in link.text()
        assert sections[0].has_ancestor(data_tab_panel="profile"), f"{path}: раздел не во вкладке «Профиль»"


def test_profile_card_of_other_employee_has_no_my_notifications_section():
    """FR-342: чужая карточка (у коллеги с `staff.view` и у администратора) без раздела «Мои уведомления» и без ссылки
    `a[data-action=my-notifications]`."""
    target = support.make_with_permissions("staff.view")
    own = _page(support.logged_in(target).get(f"/staff/{target.pk}/", follow=True))
    assert own.find_all("section", data_section="notifications"), "у владельца раздела нет: проверка «чужим нет» пуста"
    for viewer in (support.make_with_permissions("staff.view"), support.make_admin()):
        response = support.logged_in(viewer).get(f"/staff/{target.pk}/")
        assert response.status_code == 200
        page = _page(response)
        assert page.find(data_card=True) is not None, "карточка не открылась"
        assert not page.find_all("section", data_section="notifications")
        assert not page.find_all("a", data_action="my-notifications")


# --- тихие часы по умолчанию (FR-323) --------------------------------------------------------------------

def test_page_shows_calendar_mode_selected_for_employee_without_settings_row():
    """FR-323: у сотрудника без строки `UserNotifySettings` выбран режим «По рабочему календарю компании»
    (`fieldset[data-quiet]`: три радиокнопки, отмечена `calendar`; семь дней и поля времени есть, но пусты); открытие
    страницы строку не создаёт; у сотрудника со строкой `own` отмечены его режим, дни и часы."""
    user = support.make_employee()
    user_row = model("notify.UserNotifySettings")
    assert not user_row.objects.filter(user=user).exists()
    page = _page(support.logged_in(user).get(ME))
    quiet = page.find("fieldset", data_quiet=True)
    assert quiet is not None
    radios = quiet.find_all("input", type="radio", name="quiet_mode")
    assert [item.attrs["value"] for item in radios] == ["calendar", "own", "none"]
    assert [item.attrs["value"] for item in radios if "checked" in item.attrs] == ["calendar"]
    days = quiet.find_all("input", type="checkbox", name="own_days")
    assert [item.attrs["value"] for item in days] == ["0", "1", "2", "3", "4", "5", "6"]
    assert not [item for item in days if "checked" in item.attrs]
    for name in ("own_start", "own_end"):
        field = quiet.find("input", type="time", name=name)
        assert field is not None and not field.attrs.get("value")
    assert not user_row.objects.filter(user=user).exists(), "GET создал строку настроек"
    # контраст: сохранённые «свои часы»
    other = support.make_employee()
    user_row.objects.create(user=other, quiet_mode="own", own_days=[0, 1], own_start=clock_time(20, 0),
                            own_end=clock_time(8, 0))
    quiet = _page(support.logged_in(other).get(ME)).find("fieldset", data_quiet=True)
    radios = quiet.find_all("input", type="radio", name="quiet_mode")
    assert [item.attrs["value"] for item in radios if "checked" in item.attrs] == ["own"]
    days = quiet.find_all("input", type="checkbox", name="own_days")
    assert [item.attrs["value"] for item in days if "checked" in item.attrs] == ["0", "1"]
    assert quiet.find("input", name="own_start").attrs.get("value") == "20:00"
    assert quiet.find("input", name="own_end").attrs.get("value") == "08:00"


# --- журнал привязки и устройств (FR-341) ----------------------------------------------------------------

def test_unbind_by_employee_writes_channel_unbound_journal_by_employee_without_chat_id(bots_on):
    """FR-341: ручная отвязка — одна запись `notify.channel_unbound` от сотрудника с `ip` запроса, `before`
    `{"channel": …, "bound": true}`, `after` `{"bound": false}` — без ключа `reason` и без идентификатора чата."""
    user = support.make_employee()
    chat = "5550777123"
    _bind_direct(user, "telegram", chat)
    client = support.logged_in(user)
    assert client.post("/me/notifications/unbind/telegram/").status_code == 302
    saved = _events("notify.channel_unbound", user)
    assert len(saved) == 1
    event = saved[0]
    assert event.actor_id == user.pk and event.object_type == "user" and event.ip == CLIENT_IP
    assert event.before == {"channel": "telegram", "bound": True}
    assert event.after == {"bound": False}, "у ручной отвязки ключа reason нет"
    assert chat not in _dump(event), "идентификатор чата в записи журнала"
    assert not model("notify.ChatBinding").objects.filter(user=user, channel="telegram").exists()


def test_device_removed_by_employee_writes_push_removed_journal_by_employee(webpush_on):
    """FR-341: удаление устройства сотрудником — одна запись `notify.push_removed` от сотрудника с `ip` запроса:
    `before` — браузер и платформа удалённой подписки, `after` пуст (ключа `reason` нет); адреса подписки и ключей нет."""
    user = support.make_employee()
    pair = notify.browser_keys()
    sub = _save_device(user, CHROME_UA, keys=pair)
    address = sub.endpoint
    client = support.logged_in(user)
    assert client.post(f"/me/notifications/push/{sub.pk}/delete/").status_code == 302
    saved = _events("notify.push_removed", user)
    assert len(saved) == 1
    event = saved[0]
    browser, platform = _chrome_browser()
    assert event.actor_id == user.pk and event.object_type == "user" and event.ip == CLIENT_IP
    assert event.before == {"browser": browser, "platform": platform} and event.after == {}
    dump = _dump(event)
    leaked = any(part in dump for part in (address, pair.p256dh, pair.auth))
    assert not leaked, "в записи журнала адрес подписки или ключи браузера"
    assert not model("notify.PushSubscription").objects.filter(pk=sub.pk).exists()
