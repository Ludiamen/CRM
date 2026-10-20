"""T-4129: журнал среза 004 — шесть кодов, «было / стало», русские названия, отсутствие текстов, чатов, адресов и
ключей, только дописывается и не удаляется ночным удалением (FR-341, NFR-310). Сценарии 3, 5, 6, 8 и 11 спеки среза 004.

Каждое событие § 9.2 контракта получает настоящее действие службы или страницы; записи читаются из `core.AuditEvent`
по `action` (не по тексту). Бот — учебная служба `fakebots` (`bots_on`), Web Push — подменённая точка транспорта
(`webpush_capture`), ключи браузера — `browser_keys`. Имена кода среза 004 — внутри тестов (шапка CONTRACT-004).
Образцы — `test_sd_audit.py`, `test_org_audit.py` (журнал среза 003 и 002).
"""
import importlib
import json
import re
import secrets
from datetime import time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from tests import support, support_notify as notify
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

IP = "198.51.100.77"
UA = support.FIREFOX_UA
CODES = ("notify.settings_changed", "notify.user_settings_changed", "notify.channel_bound",
         "notify.channel_unbound", "notify.push_subscribed", "notify.push_removed")
EXTERNAL = ("email", "push", "telegram", "max")
ASSIGNED = "servicedesk.assigned"
REPLIED = "servicedesk.requester_replied"
TITLE = {ASSIGNED: "Мне назначили заявку", REPLIED: "Заявитель ответил"}   # § 3.2, дословно


# --- помощники только этого файла ---------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.notify.services.{name}")


def _events(action: str | None = None) -> list:
    """События `notify.*` по порядку записи (по коду действия, не по тексту)."""
    found = model("core.AuditEvent").objects.filter(action__startswith="notify.")
    if action:
        found = found.filter(action=action)
    return list(found.order_by("id"))


def _one(action: str):
    found = _events(action)
    assert len(found) == 1, f"{action}: ждали одну запись, есть {len(found)}"
    return found[0]


def _dump(event) -> str:
    return json.dumps([event.before, event.after], ensure_ascii=False)


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))


def _is_russian(text: str, code: str) -> bool:
    return text != code and _has_cyrillic(text)


def _digits(n: int = 10) -> str:
    return str(secrets.randbelow(9 * 10 ** (n - 1)) + 10 ** (n - 1))


def _member():
    """Сотрудник, видящий строки таблицы уведомлений (участник очереди сервис-деска)."""
    unit = org.make_unit()
    sd.make_queue(unit)
    user = support.make_employee()
    org.make_member(user, unit)
    return user


def _current_table(user) -> dict:
    """Код вида -> включённые внешние каналы действующей таблицы (в порядке каталога)."""
    return {row.kind.code: [c for c in EXTERNAL if row.cells[c]] for row in _svc("prefs").effective(user).rows}


def _subscribe(user, *, ip=None, user_agent=UA, device_id=None):
    """Подписка Web Push сотрудника через `push.save` с браузером и платформой по `User-Agent`."""
    pair = notify.browser_keys()
    endpoint = f"https://fcm.googleapis.com/{secrets.token_urlsafe(18)}"
    sub = _svc("push").save(user, endpoint=endpoint, p256dh=pair.p256dh, auth=pair.auth, device_id=device_id,
                            user_agent=user_agent, ip=ip)
    return sub, endpoint, pair


def _telegram_start(chat: int) -> dict:
    return {"message": {"chat": {"id": chat, "type": "private"}, "from": {"id": chat}, "text": "/start"}}


def _telegram_text(chat: int, text: str) -> dict:
    return {"message": {"chat": {"id": chat, "type": "private"}, "from": {"id": chat}, "text": text}}


def _bind_telegram_by_code(user, chat: int) -> str:
    """Привязка так, как она идёт в жизни: код со страницы, затем сообщение боту. Возвращает открытый код."""
    binding, bots = _svc("binding"), _svc("bots")
    code = binding.new_code(user, "telegram").code
    assert bots.handle_update("telegram", _telegram_start(chat)) == "dialog_started"
    assert bots.handle_update("telegram", _telegram_text(chat, code)) == "bound"
    return code


def _scenario(bots):
    """Все шесть кодов журнала настоящими действиями; возвращает значения, которых в журнале быть не должно."""
    from apps.core.extensions import Draft

    prefs, push, binding, bot_service = _svc("prefs"), _svc("push"), _svc("binding"), _svc("bots")
    notify_settings, dispatch = _svc("settings"), _svc("dispatch")
    admin = support.make_admin()
    admin_client = support.logged_in(admin, ip=IP)
    response = admin_client.post("/settings/notifications/", {
        "channels": "1", "telegram_enabled": "1", "max_enabled": "1",
        "limits": "1", "email_delay_minutes": "25", "retention_days": "45"})
    assert response.status_code == 302
    notify_settings.update(actor=admin, ip=IP, defaults={ASSIGNED: ["email", "push"]})

    user = _member()
    table = _current_table(user)
    flipped = {code: list(channels) for code, channels in table.items()}
    # срез 005: первым по алфавиту стал вид базы знаний только с «Почтой» — берём вид сервис-деска
    first = sorted(code for code in flipped if code.startswith("servicedesk."))[0]
    flipped[first] = [c for c in flipped[first] if c != "email"] or ["email"]
    assert prefs.save(user, table=flipped, ip=IP) is True
    assert prefs.save(user, quiet_mode="own", own_days=[0, 1, 2], own_start=time(22, 0), own_end=time(7, 0),
                      ip=IP) is True

    chat_telegram, chat_max = _digits(), _digits()
    code = _bind_telegram_by_code(user, int(chat_telegram))
    binding.bind(user.pk, "max", chat_max)

    first_sub, first_endpoint, first_pair = _subscribe(user, ip=IP)
    second_sub, second_endpoint, second_pair = _subscribe(user, ip=IP)
    push.delete(user, first_sub.pk, ip=IP)
    push.drop(second_sub.pk, reason="gone")

    binding.unbind(user, "max", actor=user, ip=IP)
    kicked = {"my_chat_member": {"chat": {"id": int(chat_telegram), "type": "private"},
                                 "new_chat_member": {"status": "kicked"}}}
    assert bot_service.handle_update("telegram", kicked) == "unbound"

    text = "Текст-" + secrets.token_hex(6)
    dispatch.create(ASSIGNED, [Draft(user.pk, text, "/tickets/1/", "ticket:1")])
    from django.conf import settings as dj

    hidden = [first_endpoint, second_endpoint, first_endpoint.rsplit("/", 1)[1], second_endpoint.rsplit("/", 1)[1],
              first_pair.p256dh, first_pair.auth, second_pair.p256dh, second_pair.auth,
              dj.VAPID_PRIVATE_KEY, dj.VAPID_PUBLIC_KEY, dj.TELEGRAM_BOT_TOKEN, dj.MAX_BOT_TOKEN,
              code, support.sha256(code)]
    return SimpleNamespace(admin=admin, user=user, text=text, chats=[chat_telegram, chat_max],
                           endpoints=[first_endpoint, second_endpoint], hidden=hidden)


# --- настройки администратора (FR-341, § 9.2, 13.3) -------------------------------------------------------------

def test_admin_settings_change_writes_was_became_event(bots_on):
    """FR-341: страница администратора меняет переключатель и два срока — одна запись `notify.settings_changed`
    (объект `notify_settings`, `"1"`, автор — администратор, адрес запроса), в «было / стало» только изменившиеся поля."""
    admin = support.make_admin()
    client = support.logged_in(admin, ip=IP)
    response = client.post("/settings/notifications/", {
        "channels": "1", "telegram_enabled": "1",            # MAX не отмечен: был включён, станет выключен
        "limits": "1", "email_delay_minutes": "30", "retention_days": "60"})
    assert response.status_code == 302
    event = _one("notify.settings_changed")
    assert (event.object_type, event.object_id) == ("notify_settings", "1")
    assert event.actor_id == admin.pk
    assert event.ip == IP
    assert event.before == {"max_enabled": True, "email_delay_minutes": 15, "retention_days": 90}
    assert event.after == {"max_enabled": False, "email_delay_minutes": 30, "retention_days": 60}
    assert _events("notify.user_settings_changed") == []


def test_channel_switch_writes_event(bots_on):
    """FR-341: каждое выключение и включение канала — своя запись; ключи — только этого переключателя, значения
    логические (ключей и токенов в записи нет)."""
    admin = support.make_admin()
    settings_service = _svc("settings")
    settings_service.update(actor=admin, ip=IP, telegram_enabled=False)
    settings_service.update(actor=admin, ip=IP, telegram_enabled=True)
    first, second = _events("notify.settings_changed")
    assert (first.before, first.after) == ({"telegram_enabled": True}, {"telegram_enabled": False})
    assert (second.before, second.after) == ({"telegram_enabled": False}, {"telegram_enabled": True})
    for event in (first, second):
        assert event.actor_id == admin.pk and event.ip == IP
        assert (event.object_type, event.object_id) == ("notify_settings", "1")


def test_defaults_change_writes_event_by_kind(bots_on):
    """FR-341, решение C5: значения по умолчанию — словарь «название вида -> каналы», только по видам, чьи каналы
    изменились; `null` — вида не было в словаре; вид без изменений в запись не входит."""
    admin = support.make_admin()
    settings_service = _svc("settings")
    settings_service.update(actor=admin, ip=IP, defaults={ASSIGNED: ["email"]})
    first = _one("notify.settings_changed")
    assert first.before == {"defaults": {TITLE[ASSIGNED]: None}}
    assert first.after == {"defaults": {TITLE[ASSIGNED]: ["email"]}}

    settings_service.update(actor=admin, ip=IP, defaults={ASSIGNED: ["email"], REPLIED: ["push"]})
    last = _events("notify.settings_changed")[-1]
    assert last.before == {"defaults": {TITLE[REPLIED]: None}}
    assert last.after == {"defaults": {TITLE[REPLIED]: ["push"]}}

    settings_service.update(actor=admin, ip=IP, defaults={ASSIGNED: ["email", "telegram"], REPLIED: ["push"]})
    changed = _events("notify.settings_changed")[-1]
    assert changed.before == {"defaults": {TITLE[ASSIGNED]: ["email"]}}
    assert changed.after == {"defaults": {TITLE[ASSIGNED]: ["email", "telegram"]}}
    assert len(_events("notify.settings_changed")) == 3

    # вид убран из словаря: действующий список вернулся к `default_channels` (все внешние каналы), «стало» — `null`
    settings_service.update(actor=admin, ip=IP, defaults={REPLIED: ["push"]})
    removed = _events("notify.settings_changed")[-1]
    assert removed.before == {"defaults": {TITLE[ASSIGNED]: ["email", "telegram"]}}
    assert removed.after == {"defaults": {TITLE[ASSIGNED]: None}}
    assert len(_events("notify.settings_changed")) == 4

    # список равен `default_channels` вида, а в словаре вида не было: действующий список не изменился — записи нет
    settings_service.update(actor=admin, ip=IP, defaults={REPLIED: ["push"], ASSIGNED: list(EXTERNAL)})
    assert len(_events("notify.settings_changed")) == 4
    for event in _events("notify.settings_changed"):
        assert ASSIGNED not in _dump(event) and REPLIED not in _dump(event)   # ключи — русские названия, не коды


def test_save_without_changes_writes_no_event(bots_on):
    """FR-341, § 9.2: сохранение без изменений — записи нет ни у настроек администратора (страница и служба), ни у
    личных настроек сотрудника (`prefs.save` возвращает `False`, строка настроек не создаётся)."""
    admin = support.make_admin()
    client = support.logged_in(admin, ip=IP)
    same = {"channels": "1", "telegram_enabled": "1", "max_enabled": "1",
            "limits": "1", "email_delay_minutes": "15", "retention_days": "90"}
    assert client.post("/settings/notifications/", same).status_code == 302
    _svc("settings").update(actor=admin, ip=IP, email_delay_minutes=15, retention_days=90, defaults={})
    assert _events("notify.settings_changed") == []

    user = _member()
    assert _svc("prefs").save(user, table=_current_table(user), quiet_mode="calendar", ip=IP) is False
    assert not model("notify.UserNotifySettings").objects.filter(user=user).exists()
    assert _events() == []


# --- личные настройки (FR-341, § 9.2, 13.2) -----------------------------------------------------------------------

def test_employee_table_cell_change_writes_event(bots_on):
    """FR-341: сотрудник снимает галочку «Почта» у одного вида на странице — одна запись `notify.user_settings_changed`
    (объект — он сам, адрес запроса): ячейки только изменённого вида, список внешних каналов в порядке каталога."""
    user = _member()
    rows = _svc("prefs").effective(user).rows
    assert rows, "у участника очереди нет строк таблицы"
    target = rows[0].kind
    before_list = [c for c in EXTERNAL if rows[0].cells[c]]
    assert "email" in before_list
    cells = [f"{row.kind.code}:{c}" for row in rows for c in ("email", "push")
             if row.cells[c] and not (row.kind.code == target.code and c == "email")]
    client = support.logged_in(user, ip=IP)
    response = client.post("/me/notifications/", {"table": "1", "cell": cells, "quiet_mode": "calendar"})
    assert response.status_code == 302
    event = _one("notify.user_settings_changed")
    assert (event.object_type, event.object_id) == ("user", str(user.pk))
    assert event.actor_id == user.pk
    assert event.ip == IP
    assert event.before == {"cells": {target.title: before_list}}
    assert event.after == {"cells": {target.title: [c for c in before_list if c != "email"]}}
    assert "reason" not in event.before and "reason" not in event.after


def test_employee_quiet_hours_change_writes_event(bots_on):
    """FR-341: изменение тихих часов — запись с режимом, днями и временем `ЧЧ:ММ`; следующее сохранение с одним полем
    даёт запись только с этим полем (одна запись на сохранение)."""
    user = _member()
    prefs = _svc("prefs")
    assert prefs.save(user, quiet_mode="own", own_days=[0, 1, 2], own_start=time(22, 0), own_end=time(7, 0),
                      ip=IP) is True
    first = _one("notify.user_settings_changed")
    assert first.actor_id == user.pk and first.ip == IP
    assert (first.object_type, first.object_id) == ("user", str(user.pk))
    assert first.after == {"quiet_mode": "own", "own_days": [0, 1, 2], "own_start": "22:00", "own_end": "07:00"}
    assert set(first.before) == set(first.after)
    assert first.before["quiet_mode"] == "calendar" and first.before["own_days"] == []
    assert first.before["own_start"] is None and first.before["own_end"] is None
    assert "cells" not in first.before and "cells" not in first.after

    assert prefs.save(user, quiet_mode="own", own_end=time(8, 0), ip=IP) is True
    second = _events("notify.user_settings_changed")[-1]
    assert (second.before, second.after) == ({"own_end": "07:00"}, {"own_end": "08:00"})
    assert len(_events("notify.user_settings_changed")) == 2


# --- привязки ботов (FR-341, § 9.2, 6.13) -------------------------------------------------------------------------

def test_binding_by_employee_writes_channel_bound_event(bots_on):
    """FR-341: привязка Telegram по коду из чата — `notify.channel_bound`: автор — сам сотрудник, адреса нет (идёт
    событием бота), `before = {"bound": false}`, `after` — канал и признак, без идентификатора чата и кода."""
    user = _member()
    chat = int(_digits())
    code = _bind_telegram_by_code(user, chat)
    event = _one("notify.channel_bound")
    assert (event.object_type, event.object_id) == ("user", str(user.pk))
    assert event.actor_id == user.pk
    assert event.ip is None
    assert event.before == {"bound": False}
    assert event.after == {"channel": "telegram", "bound": True}
    assert str(chat) not in _dump(event) and code not in _dump(event)


def test_unbinding_by_employee_writes_channel_unbound_event(bots_on):
    """FR-341: ручная отвязка — `notify.channel_unbound` от сотрудника с адресом запроса, без ключа `reason`; повторная
    отвязка (привязки нет) возвращает `False` и записи не даёт."""
    binding = _svc("binding")
    user = _member()
    chat = _digits()
    binding.bind(user.pk, "telegram", chat)
    assert binding.unbind(user, "telegram", actor=user, ip=IP) is True
    event = _one("notify.channel_unbound")
    assert (event.object_type, event.object_id) == ("user", str(user.pk))
    assert event.actor_id == user.pk
    assert event.ip == IP
    assert event.before == {"channel": "telegram", "bound": True}
    assert event.after == {"bound": False}
    assert chat not in _dump(event)
    assert binding.unbind(user, "telegram", actor=user, ip=IP) is False
    assert len(_events("notify.channel_unbound")) == 1


def test_automatic_unbinding_on_unavailable_bot_writes_event_from_system_with_reason(bots_on):
    """FR-341: бот недоступен (Telegram — `kicked`, MAX — `bot_stopped`) — `notify.channel_unbound` от системы (без автора
    и адреса) с причиной `bot_unavailable`; идентификаторов чатов в записях нет."""
    bots = _svc("bots")
    binding = _svc("binding")
    telegram_user, max_user = _member(), _member()
    chat_telegram, chat_max = int(_digits()), int(_digits())
    binding.bind(telegram_user.pk, "telegram", str(chat_telegram))
    binding.bind(max_user.pk, "max", str(chat_max))
    kicked = {"my_chat_member": {"chat": {"id": chat_telegram, "type": "private"},
                                 "new_chat_member": {"status": "kicked"}}}
    assert bots.handle_update("telegram", kicked) == "unbound"
    stopped = {"update_type": "bot_stopped", "chat_id": chat_max, "user": {"user_id": chat_max}}
    assert bots.handle_update("max", stopped) == "unbound"

    events = {e.object_id: e for e in _events("notify.channel_unbound")}
    assert set(events) == {str(telegram_user.pk), str(max_user.pk)}
    for owner, channel, chat in ((telegram_user, "telegram", chat_telegram), (max_user, "max", chat_max)):
        event = events[str(owner.pk)]
        assert event.object_type == "user"
        assert event.actor_id is None
        assert event.ip is None
        assert event.before == {"channel": channel, "bound": True}
        assert event.after == {"bound": False, "reason": "bot_unavailable"}
        assert str(chat) not in _dump(event)


# --- подписки Web Push (FR-341, § 9.2, 6.12) --------------------------------------------------------------------

def test_push_subscription_by_employee_writes_event_with_browser_and_platform(webpush_on):
    """FR-341: подписка со страницы (`POST /me/notifications/push/`) — `notify.push_subscribed` с браузером и платформой по
    `User-Agent`; адреса подписки и ключей в записи нет; обновление ключей той же подписки второй записи не даёт."""
    user = _member()
    pair = notify.browser_keys()
    endpoint = f"https://fcm.googleapis.com/{secrets.token_urlsafe(18)}"
    body = {"endpoint": endpoint, "keys": {"p256dh": pair.p256dh, "auth": pair.auth}}
    client = support.logged_in(user, ip=IP)
    response = client.post("/me/notifications/push/", data=json.dumps(body), content_type="application/json")
    assert response.status_code == 200 and response.json()["ok"] is True

    from apps.core.services import devices

    browser, platform = devices.parse_user_agent(UA)
    assert browser and platform
    event = _one("notify.push_subscribed")
    assert (event.object_type, event.object_id) == ("user", str(user.pk))
    assert event.actor_id == user.pk
    assert event.ip == IP
    assert event.before == {}
    assert event.after == {"browser": browser, "platform": platform}
    text = _dump(event)
    for hidden in (endpoint, endpoint.rsplit("/", 1)[1], pair.p256dh, pair.auth):
        assert hidden not in text

    again = notify.browser_keys()
    _svc("push").save(user, endpoint=endpoint, p256dh=again.p256dh, auth=again.auth, user_agent=UA, ip=IP)
    assert len(_events("notify.push_subscribed")) == 1


def test_push_removal_by_employee_writes_event(webpush_on):
    """FR-341: удаление устройства сотрудником — `notify.push_removed` от него с адресом запроса: в «было» браузер и
    платформа удалённой подписки, в «стало» пусто, причины нет; чужая подписка записи не даёт."""
    from django.http import Http404

    from apps.core.services import devices

    push = _svc("push")
    user, stranger = _member(), _member()
    sub, endpoint, _pair = _subscribe(user, ip=None)
    foreign, _endpoint, _other = _subscribe(stranger, ip=None)
    with pytest.raises(Http404):
        push.delete(user, foreign.pk, ip=IP)
    assert _events("notify.push_removed") == []

    push.delete(user, sub.pk, ip=IP)
    browser, platform = devices.parse_user_agent(UA)
    event = _one("notify.push_removed")
    assert (event.object_type, event.object_id) == ("user", str(user.pk))
    assert event.actor_id == user.pk
    assert event.ip == IP
    assert event.before == {"browser": browser, "platform": platform}
    assert event.after == {}
    assert endpoint not in _dump(event)


def test_push_removal_by_system_on_service_refusal_logout_and_dismissal_writes_event_with_reason(webpush_on):
    """FR-341: удаление системой — `notify.push_removed` без автора и адреса, в «стало» только `reason`: `gone` (отказ
    push-сервиса), `logout` (выход из портала), `dismissed` (увольнение); объект — владелец подписки."""
    from apps.core.services import devices

    push, cleanup = _svc("push"), _svc("cleanup")
    admin = support.make_admin()
    gone_user, logout_user, dismissed_user = _member(), _member(), _member()
    gone_sub, _e1, _k1 = _subscribe(gone_user)
    support.logged_in(logout_user, ip=IP)
    device_id = model("core.UserSession").objects.filter(user=logout_user).values_list("device_id", flat=True).first()
    assert device_id, "у вошедшего сотрудника нет устройства сессии"
    _subscribe(logout_user, device_id=device_id)
    _subscribe(dismissed_user)

    push.drop(gone_sub.pk, reason="gone")
    push.on_logged_out(user_id=logout_user.pk, device_ids=[device_id], reason="logout")
    cleanup.on_dismissed(user_id=dismissed_user.pk, actor_id=admin.pk)

    browser, platform = devices.parse_user_agent(UA)
    found = {e.object_id: e for e in _events("notify.push_removed")}
    assert set(found) == {str(gone_user.pk), str(logout_user.pk), str(dismissed_user.pk)}
    for owner, reason in ((gone_user, "gone"), (logout_user, "logout"), (dismissed_user, "dismissed")):
        event = found[str(owner.pk)]
        assert event.object_type == "user"
        assert event.actor_id is None
        assert event.ip is None
        assert event.after == {"reason": reason}
        assert event.before == {"browser": browser, "platform": platform}
    assert not model("notify.PushSubscription").objects.filter(user__in=[gone_user, logout_user, dismissed_user]).exists()


def test_dismissal_cleanup_writes_events_for_bindings_and_subscriptions(bots_on, webpush_on):
    """FR-341: увольнение — по каждой привязке (Telegram, MAX) `notify.channel_unbound` и по каждой подписке
    `notify.push_removed` от системы с причиной `dismissed`, без идентификаторов чатов и адресов; новых `channel_bound`
    нет; привязок и подписок сотрудника после очистки не остаётся."""
    binding, cleanup = _svc("binding"), _svc("cleanup")
    admin = support.make_admin()
    user = _member()
    chat_telegram, chat_max = _digits(), _digits()
    binding.bind(user.pk, "telegram", chat_telegram)
    binding.bind(user.pk, "max", chat_max)
    _s1, endpoint_one, _k1 = _subscribe(user)
    _s2, endpoint_two, _k2 = _subscribe(user)
    bound_before = len(_events("notify.channel_bound"))

    cleanup.on_dismissed(user_id=user.pk, actor_id=admin.pk)

    unbound = _events("notify.channel_unbound")
    assert sorted(e.before["channel"] for e in unbound) == ["max", "telegram"]
    for event in unbound:
        assert (event.object_type, event.object_id) == ("user", str(user.pk))
        assert event.actor_id is None and event.ip is None
        assert event.before["bound"] is True
        assert event.after == {"bound": False, "reason": "dismissed"}
    removed = _events("notify.push_removed")
    assert len(removed) == 2
    for event in removed:
        assert (event.object_type, event.object_id) == ("user", str(user.pk))
        assert event.actor_id is None and event.ip is None
        assert event.after == {"reason": "dismissed"}
    assert len(_events("notify.channel_bound")) == bound_before
    dump = " ".join(_dump(e) for e in _events())
    for hidden in (chat_telegram, chat_max, endpoint_one, endpoint_two):
        assert hidden not in dump
    assert not model("notify.ChatBinding").objects.filter(user=user).exists()
    assert not model("notify.PushSubscription").objects.filter(user=user).exists()


# --- русские названия (FR-341, § 9.1) ---------------------------------------------------------------------------

def test_every_action_has_russian_label_in_audit_labels(bots_on, webpush_on):
    """FR-341, решение 29 задач: названия — как в § 9.2 (`ACTIONS`, `OBJECT_TYPES`, `FIELDS`, `VALUES`), зарегистрированы в
    ядре, и каждый записанный сценарием ключ (в том числе вложенный в `cells` и `defaults`) и значение — по-русски."""
    from apps.core.services import audit_labels as core_labels
    from apps.core.services import audit_search
    from apps.notify import audit_labels as own

    labels = own.audit_labels()
    assert set(labels) == {"actions", "fields", "object_types", "values"}
    titles = {
        "notify.settings_changed": "Настройки уведомлений изменены",
        "notify.user_settings_changed": "Личные настройки уведомлений изменены",
        "notify.channel_bound": "Канал уведомлений привязан",
        "notify.channel_unbound": "Канал уведомлений отвязан",
        "notify.push_subscribed": "Устройство подписано на push",
        "notify.push_removed": "Подписка push удалена",
    }
    known = dict(audit_search.known_actions())
    for code, title in titles.items():
        assert labels["actions"][code] == title, code
        assert known.get(code) == title, code
    assert labels["object_types"]["notify_settings"] == "настройки уведомлений"
    assert core_labels.object_title("notify_settings") == "настройки уведомлений"
    fields = {
        "webpush_enabled": "Web Push включён", "telegram_enabled": "Telegram включён", "max_enabled": "MAX включён",
        "email_delay_minutes": "срок до письма, минут", "retention_days": "срок хранения уведомлений, дней",
        "defaults": "значения по умолчанию", "cells": "ячейки таблицы", "quiet_mode": "тихие часы",
        "own_days": "дни своих часов", "own_start": "свои часы: с", "own_end": "свои часы: до",
        "bound": "привязан", "browser": "браузер", "platform": "платформа",
    }
    for key, title in fields.items():
        assert labels["fields"][key] == title, key
        assert core_labels.label(key) == title, key
    values = {
        ("quiet_mode", "calendar"): "по рабочему календарю компании", ("quiet_mode", "own"): "свои часы",
        ("quiet_mode", "none"): "без тихих часов", ("channel", "telegram"): "Telegram", ("channel", "max"): "MAX",
        ("reason", "bot_unavailable"): "бот недоступен", ("reason", "dismissed"): "увольнение",
        ("reason", "gone"): "подписка недействительна", ("reason", "logout"): "выход из портала",
        ("reason", "moved"): "подписка перенесена на другую учётную запись", ("reason", "limit"): "больше десяти подписок",
    }
    for (field, value), title in values.items():
        assert core_labels.text(field, value) == title, (field, value)
    assert core_labels.text("reason", "manual") == "вручную"      # прежние значения не переопределены

    _scenario(bots_on)
    events = _events()
    assert {e.action for e in events} == set(titles)
    for event in events:
        for side in (event.before, event.after):
            for key, value in side.items():
                assert _is_russian(core_labels.label(key), key), f"{event.action}: ключ {key} не переведён"
                if isinstance(value, str) and key in ("reason", "quiet_mode"):
                    assert _is_russian(core_labels.text(key, value), value), (key, value)
                if isinstance(value, str) and key == "channel":   # § 9.2: подписи каналов — латиницей
                    assert core_labels.text(key, value) == {"telegram": "Telegram", "max": "MAX"}[value], value
                if key in ("cells", "defaults"):
                    for nested in value:
                        assert _has_cyrillic(nested), f"{event.action}: вложенный ключ {nested} не русский"


# --- чего в журнале нет (FR-341, § 9.1) -------------------------------------------------------------------------

def test_no_event_contains_notification_texts(bots_on, webpush_on):
    """FR-341: текстов уведомлений в записях нет: ни созданного уведомления, ни текста «Канал отвязан», который создаёт
    автоматическая отвязка; в записях нет ключей `text`, `url`, `link`."""
    world = _scenario(bots_on)
    events = _events()
    assert events
    assert model("notify.Notification").objects.filter(text=world.text).exists()
    assert model("notify.Notification").objects.filter(kind="notify.channel_unbound").exists()
    for event in events:
        text = _dump(event)
        assert world.text not in text, event.action
        assert "отвязан: бот недоступен" not in text, event.action
        for key in ("text", "url", "link", "body"):
            assert key not in event.before and key not in event.after, (event.action, key)


def test_no_event_contains_chat_identifiers(bots_on, webpush_on):
    """FR-341: идентификаторов чатов Telegram и MAX нет ни как значения, ни как ключа (в том числе в записях привязки,
    ручной и автоматической отвязки)."""
    world = _scenario(bots_on)
    for event in _events():
        text = _dump(event)
        for chat in world.chats:
            assert chat not in text, event.action
        for key in ("chat_id", "chat", "user_id"):
            assert key not in event.before and key not in event.after, (event.action, key)


def test_no_event_contains_subscription_addresses(bots_on, webpush_on):
    """FR-341: адресов подписок Web Push нет в записях подписки и удаления (ни целиком, ни хвостом адреса)."""
    world = _scenario(bots_on)
    kinds = {e.action for e in _events()}
    assert {"notify.push_subscribed", "notify.push_removed"} <= kinds
    for event in _events():
        text = _dump(event)
        for endpoint in world.endpoints:
            assert endpoint not in text and endpoint.rsplit("/", 1)[1] not in text, event.action
        for key in ("endpoint", "address", "sub"):
            assert key not in event.before and key not in event.after, (event.action, key)


def test_no_event_contains_keys_tokens_or_binding_codes(bots_on, webpush_on):
    """FR-341, NFR-310: ключей браузера (`p256dh`, `auth`), ключей VAPID, токенов ботов, кода привязки и его хеша в записях
    нет, как и ключей `code`, `token`, `key`, `secret`; значения настроек администратора — только логические и целые."""
    world = _scenario(bots_on)
    events = _events()
    assert len(events) >= 8
    for event in events:
        text = _dump(event)
        for hidden in world.hidden:
            assert hidden not in text, event.action
        for key in ("code", "codes", "token", "key", "secret", "p256dh", "auth", "code_hash", "vapid"):
            assert key not in event.before and key not in event.after, (event.action, key)


def test_notifications_deliveries_and_bot_messages_are_not_written_to_journal(
        bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-341, § 9.1: создание уведомления, его доставки и отправка, отметка «прочитано», ответ бота на чужой текст и чистка
    кодов привязки журнал не пополняют; текста уведомления в журнале нет."""
    from apps.core.extensions import Draft

    dispatch, binding, bots, reading = _svc("dispatch"), _svc("binding"), _svc("bots"), _svc("reading")
    user = _member()
    binding.bind(user.pk, "telegram", _digits())
    _subscribe(user)
    Event = model("core.AuditEvent")
    baseline = list(Event.objects.order_by("id").values_list("id", flat=True))
    text = "Текст-" + secrets.token_hex(6)

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            ids = dispatch.create(ASSIGNED, [Draft(user.pk, text, "/tickets/1/", "ticket:1")])
    assert ids and model("notify.Delivery").objects.filter(notification_id__in=ids).exists()
    with notify.fake_bot_send("telegram"), notify.webpush_capture():
        notify.run_jobs()
    reading.mark_object(user.pk, "ticket:1")
    stranger_chat = int(_digits())
    assert bots.handle_update("telegram", _telegram_text(stranger_chat, "не код")) == "ask_code"
    binding.purge_expired_codes()

    assert list(Event.objects.order_by("id").values_list("id", flat=True)) == baseline
    for event in Event.objects.all():
        assert text not in json.dumps([event.action, event.before, event.after], ensure_ascii=False)
    assert not Event.objects.filter(object_type__in=("notification", "delivery", "digest", "bot_message")).exists()


# --- только дописывается и не удаляется (NFR-310) ---------------------------------------------------------------

def test_notify_events_are_append_only(bots_on, webpush_on):
    """NFR-310: у роли приложения нет UPDATE, DELETE и TRUNCATE на журнал; изменить и удалить события `notify.*` нельзя,
    код `apps/notify` журнал не правит и не удаляет."""
    Event = model("core.AuditEvent")
    _scenario(bots_on)
    ids = sorted(e.pk for e in _events())
    assert len(ids) >= 8
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=CODES).update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action = ANY(%s)", [list(CODES)])
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=CODES).delete()
    assert sorted(e.pk for e in _events()) == ids
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot

    sources = [p for p in Path(support.BACKEND_DIR / "apps" / "notify").rglob("*.py") if "migrations" not in p.parts]
    assert sources, "нет кода apps/notify"
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not (re.search(r"auditevent", line, re.I)
                        and re.search(r"\.delete\(|_raw_delete|truncate|\.update\(", line, re.I)), (
                f"{path}: правка журнала: {line.strip()}")


def test_notify_events_are_not_removed_by_retention_job_within_three_years(bots_on, webpush_on):
    """NFR-310: ночное удаление `run_retention()` (под ролью приложения) удаляет старые уведомления, но ни одной записи
    журнала `notify.*` не трогает, в том числе записи возрастом 400 суток, 2 года 11 месяцев и старше трёх лет (1200 суток): журнал ночное удаление
    не трогает вовсе."""
    admin = support.make_admin()
    _svc("settings").update(actor=admin, ip=IP, retention_days=30)
    user = _member()
    _scenario(bots_on)
    Event = model("core.AuditEvent")
    now = timezone.now()
    old = [Event.objects.create(action=action, object_type="user", object_id=str(user.pk), before={}, after={},
                                at=now - timedelta(days=age))
           for action, age in (("notify.user_settings_changed", 400), ("notify.channel_bound", 365 * 3 - 30),
                               ("notify.push_removed", 1200))]
    stale = model("notify.Notification").objects.create(
        user=user, kind="core.password_changed", text="старое", url="/me/security/",
        created_at=now - timedelta(days=400))
    before_events = sorted(Event.objects.values_list("id", flat=True))
    before_notify = sorted(e.pk for e in _events())

    result = notify.run_retention()

    assert result["notifications"] >= 1
    assert not model("notify.Notification").objects.filter(pk=stale.pk).exists()
    assert sorted(Event.objects.values_list("id", flat=True)) == before_events
    assert sorted(e.pk for e in _events()) == before_notify
    assert all(Event.objects.filter(pk=e.pk).exists() for e in old)
