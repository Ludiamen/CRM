"""T-4127: страница администратора «Настройки уведомлений» (FR-334, FR-335, FR-336, FR-337, NFR-312). Сценарий 8 спеки.

Маршрут `/settings/notifications/` — CONTRACT-004 § 13.3; зацепки — § 14.4; тексты — § 15.4-15.5; сервис `settings` — § 6.5;
коды отказов — § 6.2; журнал `notify.settings_changed` — § 9.2 (решение C5: вложенный ключ `defaults` — название вида);
отказ ничего не сохраняет, в том числе остальные поля отправки (решение E24); признаки групп `channels`, `limits`,
`defaults_present` (решение D6); причина `channel_disabled` (решение B6). Ключи и токены — только сгенерированные на месте
(решение 23 задач), в сообщениях проверок значений нет: ищется список имён настроек, чьё значение попало в ответ.
Разметку разбирает `html.parser`, элементы ищутся по зацепкам. Имена кода среза 004 — внутри тестов или через `support.model`.
"""
import datetime
import json
import secrets
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

from tests import support, support_org as org, support_servicedesk as sd, support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

URL = "/settings/notifications/"
MSK = ZoneInfo("Europe/Moscow")
MOMENT = datetime.datetime(2026, 10, 13, 11, 0, 0, tzinfo=MSK)
NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
EXTERNAL = ("email", "push", "telegram", "max")
ENV_NAMES = ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT", "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN")
PRIVATE_NAMES = ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN")
CHANNEL_FLAGS = {"webpush": "webpush_enabled", "telegram": "telegram_enabled", "max": "max_enabled"}
ENV_EXPLANATION = "ключи задаются в окружении установки"


# --- разбор разметки (помощник только этого файла) ----------------------------------------------------------

_VOID = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


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
             if (tag is None or el.tag == tag) and all(k in el.attrs and (v is True or el.attrs[k] == v)
                                                      for k, v in wanted.items())]
    return [el for el in found if _inside(el, within)] if within is not None else found


def _one(doc, tag=None, attrs=None, *, within=None):
    found = _find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент {tag or '*'}{attrs}, нашли {len(found)}"
    return found[0]


def _doc(response) -> _Doc:
    return _Doc(response.content.decode("utf-8", "replace"))


def _body(response) -> str:
    return response.content.decode("utf-8", "replace")


# --- окружение и данные ---------------------------------------------------------------------------------------

def _set_env(settings, *names: str) -> None:
    """Задаёт сгенерированные значения (без обращения к коду среза); остальные из `ENV_NAMES` очищает."""
    for name in ENV_NAMES:
        value = ""
        if name in names:
            value = "mailto:noreply@example.test" if name == "VAPID_SUBJECT" else "g-" + secrets.token_hex(12)
        setattr(settings, name, value)


def _leaks(settings, *texts: str) -> list:
    """Имена настроек, чьё непустое значение встречается в любом из текстов (сами значения не возвращаются)."""
    found = []
    for name in PRIVATE_NAMES:
        value = getattr(settings, name, "")
        if value and any(value in text for text in texts):
            found.append(name)
    return found


def _cfg():
    return model("notify.NotifySettings").objects.get(pk=1)


def _set_cfg(**fields) -> None:
    model("notify.NotifySettings").objects.filter(pk=1).update(**fields)


def _svc():
    from apps.notify.services import settings as notify_settings
    return notify_settings


def _admin(ip: str = "198.51.100.31"):
    user = support.make_admin()
    return user, support.logged_in(user, ip=ip)


def _kinds() -> list:
    """Виды каталога, которых нет `mandatory` (строки таблицы администратора), в порядке каталога."""
    from apps.notify.services import kinds
    return [kind for kind in kinds.catalog() if not kind.mandatory]


def _defaults_of(kind) -> list:
    return [channel for channel in EXTERNAL if channel in kind.default_channels]


def _cells(spec: dict | None = None) -> list:
    """Значения поля `cell` для всех нематериальных видов: действующие по умолчанию, `spec` — свои каналы у видов."""
    spec = spec or {}
    out = []
    for kind in _kinds():
        for channel in spec.get(kind.code, _defaults_of(kind)):
            out.append(f"{kind.code}:{channel}")
    return out


def _post(client, *, enable=None, limits=None, cells=None, **extra):
    """POST страницы по правилам решения D6: группа отправляется только вместе со своим признаком.

    `enable` — список каналов (`webpush`, `telegram`, `max`) с включённым флажком (группа `channels`); `limits` — пара
    (срок письма, срок хранения) (группа `limits`); `cells` — список значений `cell` (группа `defaults_present`)."""
    data = dict(extra)
    if enable is not None:
        data["channels"] = "1"
        for channel in enable:
            data[CHANNEL_FLAGS[channel]] = "1"
    if limits is not None:
        data["limits"] = "1"
        data["email_delay_minutes"], data["retention_days"] = limits
    if cells is not None:
        data["defaults_present"] = "1"
        data["cell"] = list(cells)
    return client.post(URL, data)


def _events(action: str = "notify.settings_changed") -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _error(doc, field: str):
    found = _find(doc, None, {"data-error": field, "data-code": True})
    return found[0] if found else None


def _block(doc, channel: str):
    return _one(doc, "section", {"data-channel-block": channel})


def _queue_employee():
    """Сотрудник — прямой участник узла-очереди: ему видны все четыре вида сервис-деска."""
    user = support.make_employee()
    org.make_member(user, sd.make_queue(org.make_unit()).unit)
    return user


def _rows_of(user) -> dict:
    from apps.notify.services import prefs
    return {row.kind.code: dict(row.cells) for row in prefs.effective(user).rows}


def _bind(user, channel: str):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id="chat-" + secrets.token_hex(6))


def _note(user):
    return model("notify.Notification").objects.create(
        user=user, kind=ASSIGNED, text="Тест " + secrets.token_hex(4), url="/tickets/1/", object_ref="servicedesk.ticket:1")


def _delivery(channel: str, user):
    from django.utils import timezone
    return model("notify.Delivery").objects.create(
        notification=_note(user), channel=channel, state="waiting", due_at=timezone.now() - datetime.timedelta(seconds=5))


def _send(row) -> str:
    from apps.notify.services import delivery
    return delivery.send_delivery(row.pk)


def _fresh(row):
    row.refresh_from_db()
    return row


def _menu_has_item(response) -> bool:
    """`#main-menu a.menu-item[href="/settings/notifications/"]` (§ 14.4)."""
    doc = _doc(response)
    return any("menu-item" in a.attrs.get("class", "").split()
               for menu in _find(doc, "nav", {"id": "main-menu"})
               for a in _find(doc, "a", {"href": URL}, within=menu))


def _checked_cells(doc) -> set:
    table = _one(doc, "table", {"data-defaults-table": True})
    return {el.attrs["value"] for el in _find(doc, "input", {"type": "checkbox", "name": "cell", "checked": True},
                                              within=table)}


# --- 1. право (FR-334) -------------------------------------------------------------------------------------------

def test_manage_permission_exists_and_portal_admin_has_it_after_install():
    """FR-334: право `notify.manage` «Настройка уведомлений» создано миграцией и есть только у «Администратора портала»."""
    permission = model("core.Permission").objects.get(code="notify.manage")
    assert permission.title == notify.TITLES_004["notify.manage"]
    holders = sorted(role.name for role in model("core.Role").objects.filter(is_builtin=True)
                     if role.permissions.filter(code="notify.manage").exists())
    assert holders == [support.ADMIN_ROLE]
    for name in (support.MANAGER_ROLE, support.STAFF_ROLE):
        assert not support.role_by_name(name).permissions.filter(code="notify.manage").exists(), name
    _, client = _admin()
    assert client.get(URL).status_code == 200


def test_manage_permission_granted_to_other_role_without_code():
    """FR-334: администратор выдаёт право другой роли в интерфейсе (без кода): держатель роли открывает страницу."""
    _, admin = _admin()
    created = admin.post("/roles/new/", {"name": "Настройщик уведомлений", "permissions": ["notify.manage"]})
    assert created.status_code == 302
    role = model("core.Role").objects.get(name="Настройщик уведомлений")
    assert set(role.permissions.values_list("code", flat=True)) == {"notify.manage"}
    holder = support.make_employee(roles=[role])
    assert support.logged_in(holder, ip="198.51.100.32").get(URL).status_code == 200


def test_admin_page_forbidden_without_manage_permission_by_direct_link():
    """FR-334: без права — 403 на прямой адрес (даже с другими правами настроек), без входа — переход на вход."""
    outsider = support.logged_in(support.make_with_permissions("settings.portal", "settings.security"), ip="198.51.100.33")
    got = outsider.get(URL)
    assert got.status_code == 403
    assert 'data-notify-settings' not in _body(got)
    anonymous = support.make_client(ip="198.51.100.34").get(URL)
    assert anonymous.status_code == 302 and "/login/" in anonymous["Location"]


def test_every_admin_action_forbidden_without_manage_permission(settings):
    """FR-334: каждая отправка страницы (переключатели, сроки, таблица, всё вместе) без права — 403 и ничего не меняется."""
    _set_env(settings, "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN")
    before = _cfg()
    snapshot = (before.webpush_enabled, before.telegram_enabled, before.max_enabled, before.email_delay_minutes,
                before.retention_days, before.defaults)
    outsider = support.logged_in(support.make_with_permissions("settings.portal"), ip="198.51.100.35")
    anonymous = support.make_client(ip="198.51.100.36")
    attempts = [
        dict(enable=["telegram", "max"]),
        dict(limits=("30", "100")),
        dict(cells=_cells({NEW_IN_QUEUE: ["push"]})),
        dict(enable=["telegram"], limits=("30", "100"), cells=_cells({NEW_IN_QUEUE: []})),
    ]
    for attempt in attempts:
        assert _post(outsider, **attempt).status_code == 403, attempt
        got = _post(anonymous, **attempt)
        assert got.status_code == 302 and "/login/" in got["Location"], attempt
    after = _cfg()
    assert (after.webpush_enabled, after.telegram_enabled, after.max_enabled, after.email_delay_minutes,
            after.retention_days, after.defaults) == snapshot
    assert _events() == []


def test_menu_item_notifications_visible_only_with_manage_permission():
    """FR-334: пункт меню «Уведомления» (`#main-menu a.menu-item`) виден только с правом `notify.manage`."""
    _, admin = _admin()
    holder = support.logged_in(support.make_with_permissions("notify.manage"), ip="198.51.100.37")
    outsider = support.logged_in(support.make_with_permissions("settings.portal"), ip="198.51.100.38")
    for client in (admin, holder):
        got = client.get("/me/")
        assert got.status_code == 200 and _menu_has_item(got)
        doc = _doc(got)
        item = [a for menu in _find(doc, "nav", {"id": "main-menu"})
                for a in _find(doc, "a", {"href": URL}, within=menu)][0]
        assert item.text == "Уведомления"
    got = outsider.get("/me/")
    assert got.status_code == 200 and not _menu_has_item(got)
    # порядок (`order` 62, CONTRACT-004 § 13.3): после «Настройки портала» (60), до «Сервис-деск» (65)
    got = admin.get("/me/")
    doc = _doc(got)
    titles = [a.text for menu in _find(doc, "nav", {"id": "main-menu"})
              for a in _find(doc, "a", {}, within=menu) if "menu-item" in a.attrs.get("class", "").split()]

    def position(title):
        found = [number for number, text in enumerate(titles) if title in text]
        assert len(found) == 1, f"пункт «{title}» в меню администратора: {titles}"
        return found[0]

    assert position("Настройки портала") < position("Уведомления") < position("Сервис-деск"), titles


# --- 2. страница, ключи, переключатели (FR-335, FR-336) -----------------------------------------------------------

def test_page_shows_three_channels_with_switch_keys_state_and_default_values(settings):
    """FR-335, FR-336: три блока каналов по порядку, переключатели (не `disabled`), состояние ключей, таблица значений."""
    _set_env(settings, "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT", "TELEGRAM_BOT_TOKEN")
    _set_cfg(webpush_enabled=False, telegram_enabled=True, max_enabled=False)
    first = _kinds()[0]
    _set_cfg(defaults={first.code: ["email"]})
    _, admin = _admin()
    got = admin.get(URL)
    assert got.status_code == 200
    doc = _doc(got)
    assert _one(doc, "h1").text == "Настройки уведомлений"
    form = _one(doc, "form", {"data-form": "notify-settings", "novalidate": True})
    for name in ("channels", "limits", "defaults_present"):
        hidden = _one(doc, "input", {"type": "hidden", "name": name}, within=form)
        assert hidden.attrs["value"] == "1", name
    assert _one(doc, "button", {"type": "submit", "data-action": "save-settings"}, within=form).text == "Сохранить"
    assert [b.attrs["data-channel-block"] for b in _find(doc, "section", {"data-channel-block": True})] == [
        "webpush", "telegram", "max"]
    state = {}
    for channel, flag in CHANNEL_FLAGS.items():
        block = _block(doc, channel)
        switch = _one(doc, "input", {"type": "checkbox", "name": flag}, within=block)
        assert "disabled" not in switch.attrs, flag
        state[channel] = ("checked" in switch.attrs, _one(doc, None, {"data-keys": True}, within=block).attrs["data-keys"])
    assert state == {"webpush": (False, "set"), "telegram": (True, "set"), "max": (False, "unset")}
    table = _one(doc, "table", {"data-defaults-table": True})
    rows = _find(doc, "tr", {"data-notify-kind": True}, within=table)
    assert {r.attrs["data-notify-kind"] for r in rows} == {kind.code for kind in _kinds()}
    for kind in _kinds():
        row = _one(doc, "tr", {"data-notify-kind": kind.code}, within=table)
        shown = {}
        for cell in _find(doc, "td", {"data-channel": True}, within=row):
            box = _one(doc, "input", {"type": "checkbox", "name": "cell"}, within=cell)
            assert box.attrs["value"] == f"{kind.code}:{cell.attrs['data-channel']}"
            shown[cell.attrs["data-channel"]] = "checked" in box.attrs
        assert sorted(shown) == sorted(EXTERNAL), kind.code
        wanted = ["email"] if kind.code == first.code else _defaults_of(kind)
        assert [c for c in EXTERNAL if shown[c]] == wanted, kind.code


def test_webpush_keys_set_only_when_all_three_variables_are_set(settings):
    """FR-336: ключи Web Push заданы, только если заданы все три переменные; страница показывает «ключи заданы / не заданы»."""
    svc = _svc()
    _, admin = _admin()
    _set_env(settings, "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT")
    assert svc.keys_set("webpush") is True
    got = _doc(admin.get(URL))
    marker = _one(got, None, {"data-keys": True}, within=_block(got, "webpush"))
    assert marker.attrs["data-keys"] == "set" and marker.text == "ключи заданы"
    for missing in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT"):
        _set_env(settings, *[n for n in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT") if n != missing])
        assert svc.keys_set("webpush") is False, missing
        got = _doc(admin.get(URL))
        marker = _one(got, None, {"data-keys": True}, within=_block(got, "webpush"))
        assert marker.attrs["data-keys"] == "unset" and marker.text == "ключи не заданы", missing
    _set_env(settings)
    assert svc.keys_set("webpush") is False
    with pytest.raises(ValueError):
        svc.keys_set("email")


def test_telegram_and_max_keys_set_when_bot_token_is_set(settings):
    """FR-336: ключи Telegram и MAX заданы, когда задан токен бота этого канала (каждого — свой)."""
    svc = _svc()
    _, admin = _admin()
    for channel, name, other in (("telegram", "TELEGRAM_BOT_TOKEN", "max"), ("max", "MAX_BOT_TOKEN", "telegram")):
        _set_env(settings, name)
        assert svc.keys_set(channel) is True and svc.keys_set(other) is False, channel
        doc = _doc(admin.get(URL))
        assert _one(doc, None, {"data-keys": True}, within=_block(doc, channel)).attrs["data-keys"] == "set"
        assert _one(doc, None, {"data-keys": True}, within=_block(doc, other)).attrs["data-keys"] == "unset"
    _set_env(settings)
    assert svc.keys_set("telegram") is False and svc.keys_set("max") is False


def test_page_shows_no_key_or_token_values(settings):
    """FR-336, FR-337, NFR-312: значений ключей и токенов нет в ответе вообще (ни в тексте, ни в `value`, ни в `data-*`)."""
    _set_env(settings, *ENV_NAMES)
    _set_cfg(webpush_enabled=True, telegram_enabled=True, max_enabled=True)
    _, admin = _admin()
    got = admin.get(URL)
    assert got.status_code == 200
    doc = _doc(got)
    assert [_one(doc, None, {"data-keys": True}, within=_block(doc, c)).attrs["data-keys"]
            for c in ("webpush", "telegram", "max")] == ["set", "set", "set"]
    leaks = _leaks(settings, _body(got))
    assert not leaks, leaks
    saved = _post(admin, enable=["webpush", "telegram", "max"], limits=("20", "100"))
    assert saved.status_code == 302
    again = admin.get(URL)
    leaks = _leaks(settings, _body(saved), _body(again))
    assert not leaks, leaks


def test_enable_channel_without_keys_refused_with_environment_explanation(settings):
    """FR-336, FR-337: включить канал без ключей нельзя — отказ `keys_missing` у переключателя с объяснением про окружение;
    остальные поля той же отправки не сохраняются (E24); выключить канал можно всегда."""
    _set_env(settings, "TELEGRAM_BOT_TOKEN")
    before = _cfg()
    wanted_missing = {"webpush": "webpush_enabled", "max": "max_enabled"}
    _, admin = _admin()
    for channel, flag in wanted_missing.items():
        got = _post(admin, enable=[channel], limits=("30", "100"), cells=_cells({NEW_IN_QUEUE: ["push"]}))
        assert got.status_code == 200, channel
        doc = _doc(got)
        error = _error(doc, flag)
        assert error is not None and error.attrs["data-code"] == "keys_missing", channel
        assert ENV_EXPLANATION in error.text, channel
        box = _one(doc, "input", {"type": "checkbox", "name": flag})
        assert "disabled" not in box.attrs
        after = _cfg()
        assert (getattr(after, flag), after.email_delay_minutes, after.retention_days, after.defaults) == (
            False, before.email_delay_minutes, before.retention_days, before.defaults), channel
    # Telegram: токен задан — включается; токен убран — отказ
    _set_env(settings)
    got = _post(admin, enable=["telegram"], limits=("30", "100"))
    error = _error(_doc(got), "telegram_enabled")
    assert got.status_code == 200 and error is not None and error.attrs["data-code"] == "keys_missing"
    assert ENV_EXPLANATION in error.text
    assert (_cfg().telegram_enabled, _cfg().email_delay_minutes, _cfg().retention_days) == (False, 15, 90)
    # выключить без ключей можно всегда
    _set_cfg(telegram_enabled=True)
    saved = _post(admin, enable=[])
    assert saved.status_code == 302 and saved["Location"].endswith(URL)
    assert _cfg().telegram_enabled is False


def test_enable_channel_with_keys_is_saved_and_channel_becomes_available(settings):
    """FR-335, FR-336: ключи заданы — включение сохраняется (302, «Настройки уведомлений сохранены.»), канал работает."""
    _set_env(settings, "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT", "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN")
    svc = _svc()
    assert not any(svc.channel_on(c) for c in CHANNEL_FLAGS)
    _, admin = _admin()
    saved = _post(admin, enable=["telegram", "max", "webpush"])
    assert saved.status_code == 302 and saved["Location"].endswith(URL)
    cfg = _cfg()
    assert (cfg.webpush_enabled, cfg.telegram_enabled, cfg.max_enabled) == (True, True, True)
    page = admin.get(URL)
    assert "Настройки уведомлений сохранены." in [e.text for e in _find(_doc(page), None, {"role": "status"})]
    assert all(svc.channel_on(c) for c in CHANNEL_FLAGS)
    from apps.notify.services import prefs
    user = support.make_employee()
    _bind(user, "telegram")
    states = prefs.channel_states(user.pk)
    assert states["telegram"].available is True and states["telegram"].reason == ""
    assert states["max"].available is False and states["max"].reason == "not_bound"
    # выключаем один — остальные остаются
    assert _post(admin, enable=["telegram", "webpush"]).status_code == 302
    assert (_cfg().webpush_enabled, _cfg().telegram_enabled, _cfg().max_enabled) == (True, True, False)
    assert svc.channel_on("max") is False and svc.channel_on("telegram") is True


def test_key_removed_from_environment_makes_channel_off_though_switch_is_on(settings):
    """FR-336: ключ убрали из окружения — канал выключен (`channel_on`), хотя переключатель включён; страница это показывает."""
    _set_env(settings, "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN")
    _set_cfg(telegram_enabled=True, max_enabled=True)
    svc = _svc()
    assert svc.channel_on("telegram") is True and svc.channel_on("max") is True
    settings.TELEGRAM_BOT_TOKEN = ""
    assert svc.channel_on("telegram") is False and svc.channel_on("max") is True
    assert _cfg().telegram_enabled is True
    from apps.notify.services import prefs
    user = support.make_employee()
    _bind(user, "telegram")
    states = prefs.channel_states(user.pk)
    assert states["telegram"].available is False and states["telegram"].reason == "channel_disabled"
    _, admin = _admin()
    doc = _doc(admin.get(URL))
    block = _block(doc, "telegram")
    assert "checked" in _one(doc, "input", {"type": "checkbox", "name": "telegram_enabled"}, within=block).attrs
    assert _one(doc, None, {"data-keys": True}, within=block).attrs["data-keys"] == "unset"
    assert _one(doc, None, {"data-keys": True}, within=_block(doc, "max")).attrs["data-keys"] == "set"


def test_disabled_channel_is_unavailable_to_employees(settings, webpush_on, bots_on):
    """FR-336: выключенный канал недоступен сотрудникам: `channel_states`, страница «Мои уведомления», доставки в него не создаются."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch, prefs
    user = _queue_employee()
    _bind(user, "telegram")
    _bind(user, "max")
    notify.subscribe(user)
    states = prefs.channel_states(user.pk)
    assert states["telegram"].available and states["max"].available
    assert prefs.effective(user).web_push_available is True
    _, admin = _admin()
    assert _post(admin, enable=[]).status_code == 302
    states = prefs.channel_states(user.pk)
    for channel in ("telegram", "max"):
        assert states[channel].available is False and states[channel].reason == "channel_disabled", channel
    table = prefs.effective(user)
    assert table.web_push_available is False and table.web_push_reason == "channel_disabled"
    page = _doc(support.logged_in(user, ip="198.51.100.39").get("/me/notifications/"))
    for channel in ("telegram", "max"):
        cells = _find(page, "td", {"data-channel": channel, "data-available": "0", "data-reason": "channel_disabled"})
        assert cells, channel
        assert "Канал отключён администратором" in _one(page, None, {"data-hint": True}, within=cells[0]).text
    assert _one(page, None, {"data-section": "push", "data-web-push": "off"}) is not None
    dispatch.create(ASSIGNED, [Draft(user_id=user.pk, text="Назначена заявка", url="/tickets/1/", object_ref="servicedesk.ticket:1")])
    channels = set(model("notify.Delivery").objects.filter(notification__user=user).values_list("channel", flat=True))
    assert channels == {"email"}


def test_disabled_channel_deliveries_are_skipped_with_reason_channel_off(settings, webpush_on, bots_on):
    """FR-336: доставки в выключенный администратором канал — `skipped`; причина `channel_disabled` (решение B6; имя неточно),
    сеть и боты не вызываются."""
    user = support.make_employee()
    _bind(user, "telegram")
    _bind(user, "max")
    notify.subscribe(user)
    rows = [_delivery("telegram", user), _delivery("max", user), _delivery("webpush", user)]
    _, admin = _admin()
    assert _post(admin, enable=[]).status_code == 302
    with notify.fake_bot_send("telegram") as telegram, notify.fake_bot_send("max") as max_bot, \
            notify.webpush_capture() as push:
        assert [_send(row) for row in rows] == ["skipped"] * 3
    assert telegram.calls == [] and max_bot.calls == [] and push.requests == []
    for row in rows:
        row = _fresh(row)
        assert (row.state, row.reason, row.lease_until) == ("skipped", "channel_disabled", None), row.channel


def test_disabled_channel_keeps_bindings_and_subscriptions_and_they_work_after_enable(settings, webpush_on, bots_on):
    """FR-336: выключение не удаляет привязки и подписки; после включения они снова действуют (отправка проходит)."""
    from apps.notify.services import prefs
    user = support.make_employee()
    bindings = [_bind(user, "telegram").pk, _bind(user, "max").pk]
    subscription = notify.subscribe(user)
    _, admin = _admin()
    assert _post(admin, enable=[]).status_code == 302
    assert sorted(model("notify.ChatBinding").objects.filter(user=user).values_list("pk", flat=True)) == sorted(bindings)
    assert list(model("notify.PushSubscription").objects.filter(user=user).values_list("pk", flat=True)) == [subscription.pk]
    assert prefs.channel_states(user.pk)["telegram"].available is False
    assert _post(admin, enable=["webpush", "telegram", "max"]).status_code == 302
    assert (_cfg().webpush_enabled, _cfg().telegram_enabled, _cfg().max_enabled) == (True, True, True)
    states = prefs.channel_states(user.pk)
    assert states["telegram"].available is True and states["max"].available is True
    assert prefs.effective(user).web_push_available is True
    rows = {channel: _delivery(channel, user) for channel in ("telegram", "max", "webpush")}
    with notify.fake_bot_send("telegram") as telegram, notify.fake_bot_send("max") as max_bot, \
            notify.webpush_capture() as push:
        assert [_send(row) for row in rows.values()] == ["sent"] * 3
    assert len(telegram.calls) == 1 and len(max_bot.calls) == 1 and len(push.requests) == 1
    assert {_fresh(row).state for row in rows.values()} == {"sent"}


# --- 3. сроки (FR-335) ---------------------------------------------------------------------------------------------

def test_email_wait_outside_5_to_120_refused_by_field(settings):
    """FR-335: срок письма вне 5…120 (и не число) — отказ `out_of_range` у поля с текстом про пределы; ничего не сохранено,
    в том числе остальные поля той же отправки (E24)."""
    _set_env(settings, "TELEGRAM_BOT_TOKEN")
    _, admin = _admin()
    for bad in ("4", "0", "121", "1000", "abc", ""):
        got = _post(admin, enable=["telegram"], limits=(bad, "100"), cells=_cells({NEW_IN_QUEUE: ["push"]}))
        assert got.status_code == 200, bad
        doc = _doc(got)
        error = _error(doc, "email_delay_minutes")
        assert error is not None and error.attrs["data-code"] == "out_of_range", bad
        assert "от 5 до 120" in error.text, bad
        assert _error(doc, "retention_days") is None, bad
        cfg = _cfg()
        assert (cfg.telegram_enabled, cfg.email_delay_minutes, cfg.retention_days, cfg.defaults) == (
            False, 15, 90, {}), bad
    assert _events() == []


def test_retention_days_outside_30_to_365_refused_by_field(settings):
    """FR-335: срок хранения вне 30…365 (и не число) — отказ `out_of_range` у поля с текстом про пределы; ничего не сохранено (E24)."""
    _set_env(settings, "TELEGRAM_BOT_TOKEN")
    _, admin = _admin()
    for bad in ("29", "0", "366", "5000", "abc", ""):
        got = _post(admin, enable=["telegram"], limits=("30", bad), cells=_cells({NEW_IN_QUEUE: ["push"]}))
        assert got.status_code == 200, bad
        doc = _doc(got)
        error = _error(doc, "retention_days")
        assert error is not None and error.attrs["data-code"] == "out_of_range", bad
        assert "от 30 до 365" in error.text, bad
        assert _error(doc, "email_delay_minutes") is None, bad
        cfg = _cfg()
        assert (cfg.telegram_enabled, cfg.email_delay_minutes, cfg.retention_days, cfg.defaults) == (
            False, 15, 90, {}), bad
    assert _events() == []


def test_limit_boundaries_accepted_and_defaults_are_15_minutes_and_90_days():
    """FR-335: по умолчанию 15 минут и 90 дней; границы 5, 120 и 30, 365 принимаются; поля — `number` без `min`/`max`."""
    cfg = _cfg()
    assert (cfg.email_delay_minutes, cfg.retention_days) == (15, 90)
    _, admin = _admin()
    doc = _doc(admin.get(URL))
    delay = _one(doc, "input", {"name": "email_delay_minutes"})
    days = _one(doc, "input", {"name": "retention_days"})
    assert (delay.attrs["type"], delay.attrs["value"], days.attrs["type"], days.attrs["value"]) == ("number", "15", "number", "90")
    for field in (delay, days):
        assert "min" not in field.attrs and "max" not in field.attrs
    for pair in (("5", "30"), ("120", "365")):
        saved = _post(admin, limits=pair)
        assert saved.status_code == 302 and saved["Location"].endswith(URL), pair
        assert (str(_cfg().email_delay_minutes), str(_cfg().retention_days)) == pair
        shown = _doc(admin.get(URL))
        assert _one(shown, "input", {"name": "email_delay_minutes"}).attrs["value"] == pair[0]
        assert _one(shown, "input", {"name": "retention_days"}).attrs["value"] == pair[1]


def test_email_wait_30_minutes_applies_to_new_notifications(clock):
    """FR-335: срок письма 30 минут действует для новых уведомлений: письмо — через 30 минут; прежние не меняются."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    clock.set(MOMENT)
    user = support.make_employee()
    draft = Draft(user_id=user.pk, text="Назначена заявка", url="/tickets/1/", object_ref="servicedesk.ticket:1")
    old = dispatch.create(ASSIGNED, [draft])[0]
    old_due = model("notify.Delivery").objects.get(notification_id=old, channel="email").due_at
    assert old_due == MOMENT + datetime.timedelta(minutes=15)
    _, admin = _admin()
    assert _post(admin, limits=("30", "90")).status_code == 302
    assert _cfg().email_delay_minutes == 30
    new = dispatch.create(ASSIGNED, [Draft(user_id=user.pk, text="Ещё одна заявка", url="/tickets/2/",
                                           object_ref="servicedesk.ticket:2")])[0]
    assert model("notify.Delivery").objects.get(notification_id=new, channel="email").due_at == (
        MOMENT + datetime.timedelta(minutes=30))
    assert model("notify.Delivery").objects.get(notification_id=old, channel="email").due_at == old_due


# --- 4. значения по умолчанию (FR-335) -----------------------------------------------------------------------------

def test_changed_defaults_apply_to_employee_who_did_not_save_table():
    """FR-335: изменённые значения по умолчанию действуют у сотрудника, не сохранявшего таблицу; его строка не создаётся."""
    from apps.notify.services import prefs
    user = _queue_employee()
    assert prefs.row_of(user.pk) is None
    before = _rows_of(user)
    assert before[NEW_IN_QUEUE] == {"portal": True, "email": True, "push": True, "telegram": True, "max": True}
    spec = {NEW_IN_QUEUE: ["push"], ASSIGNED: ["email", "max"]}
    _, admin = _admin()
    saved = _post(admin, cells=_cells(spec))
    assert saved.status_code == 302 and saved["Location"].endswith(URL)
    assert _cfg().defaults[NEW_IN_QUEUE] == ["push"] and _cfg().defaults[ASSIGNED] == ["email", "max"]
    after = _rows_of(user)
    assert after[NEW_IN_QUEUE] == {"portal": True, "email": False, "push": True, "telegram": False, "max": False}
    assert after[ASSIGNED] == {"portal": True, "email": True, "push": False, "telegram": False, "max": True}
    assert prefs.row_of(user.pk) is None
    from apps.notify.services import kinds
    assert prefs.channels_for(user.pk, kinds.get(NEW_IN_QUEUE)) == ["push"]
    assert _checked_cells(_doc(admin.get(URL))) == set(_cells(spec))


def test_changed_defaults_do_not_touch_values_of_employee_who_saved_table():
    """FR-335: сотрудник, сохранивший таблицу, свои значения сохраняет; новые значения администратора его не меняют."""
    from apps.notify.services import prefs
    saver, fresh = _queue_employee(), _queue_employee()
    assert prefs.save(saver, table={NEW_IN_QUEUE: ["email"]}) is True
    assert prefs.row_of(saver.pk) is not None
    mine = _rows_of(saver)
    assert mine[NEW_IN_QUEUE]["email"] is True and mine[NEW_IN_QUEUE]["push"] is False
    spec = {NEW_IN_QUEUE: ["push"], ASSIGNED: ["max"]}
    _, admin = _admin()
    assert _post(admin, cells=_cells(spec)).status_code == 302
    assert _rows_of(saver) == mine
    assert _rows_of(fresh)[NEW_IN_QUEUE]["push"] is True and _rows_of(fresh)[NEW_IN_QUEUE]["email"] is False
    assert _rows_of(fresh)[ASSIGNED]["max"] is True and _rows_of(fresh)[ASSIGNED]["email"] is False


# --- 5. состояние каналов на странице, журнал, секреты (FR-336, FR-337, NFR-312) -------------------------------------

def test_page_shows_bot_name_and_last_error_time_and_code_of_channel(settings):
    """FR-336: блок канала показывает имя бота (`BotState.bot_username`) и последнюю ошибку: код, текст по коду и время."""
    _set_env(settings, *ENV_NAMES)
    model("notify.BotState").objects.create(channel="telegram", bot_username="portal_test_bot")
    stored = "2026-10-14T09:30:00+00:00"                                  # 12:30 по Москве
    _set_cfg(channel_status={"max": {"at": stored, "code": "unavailable"}})
    svc = _svc()
    svc.note_channel_error("telegram", "bad_token")
    svc.note_channel_error("webpush", "rate_limited")
    _, admin = _admin()
    doc = _doc(admin.get(URL))
    assert _one(doc, None, {"data-bot-name": True}, within=_block(doc, "telegram")).text == "portal_test_bot"
    assert _find(doc, None, {"data-bot-name": True}, within=_block(doc, "max")) == []
    assert _find(doc, None, {"data-bot-name": True}, within=_block(doc, "webpush")) == []
    texts = {"webpush": ("rate_limited", "слишком много запросов"), "telegram": ("bad_token", "токен не принят"),
             "max": ("unavailable", "канал недоступен")}
    for channel, (code, text) in texts.items():
        error = _one(doc, None, {"data-channel-error": True}, within=_block(doc, channel))
        assert error.attrs["data-code"] == code, channel
        assert text in error.text, channel
        moment = _one(doc, "time", {"data-at": True}, within=error)
        shown = datetime.datetime.fromisoformat(moment.attrs["data-at"]).replace(microsecond=0)   # § 14: ISO 8601 со смещением
        assert shown == datetime.datetime.fromisoformat(svc.channel_error(channel)["at"]).replace(microsecond=0), channel
    max_time = _one(doc, "time", {"data-at": True}, within=_block(doc, "max"))
    assert max_time.text == "14.10.2026 12:30"
    # ошибки нет — элемента нет
    svc.clear_channel_error("telegram")
    doc = _doc(admin.get(URL))
    assert _find(doc, None, {"data-channel-error": True}, within=_block(doc, "telegram")) == []
    assert _find(doc, None, {"data-channel-error": True}, within=_block(doc, "max")) != []


def test_admin_change_is_audited_as_was_became_without_key_values(settings):
    """FR-337: изменение пишется в журнал `notify.settings_changed` «было / стало» только по изменившимся полям (по видам —
    названием вида, решение C5), со значениями администратора и без значений ключей."""
    _set_env(settings, "TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT")
    kind = next(k for k in _kinds() if k.code == NEW_IN_QUEUE)
    user, admin = _admin(ip="198.51.100.41")
    saved = _post(admin, enable=["telegram"], limits=("30", "100"), cells=_cells({NEW_IN_QUEUE: ["push"]}))
    assert saved.status_code == 302
    events = _events()
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id, event.ip) == ("notify_settings", "1", user.pk, "198.51.100.41")
    assert event.before["telegram_enabled"] is False and event.after["telegram_enabled"] is True
    assert (event.before["email_delay_minutes"], event.after["email_delay_minutes"]) == (15, 30)
    assert (event.before["retention_days"], event.after["retention_days"]) == (90, 100)
    assert event.before["defaults"][kind.title] is None and event.after["defaults"][kind.title] == ["push"]
    # неизменённые виды в запись не входят (п. 21 (в)): форма прислала всю таблицу, изменился один вид
    assert set(event.before["defaults"]) == {kind.title} and set(event.after["defaults"]) == {kind.title}
    for field in ("webpush_enabled", "max_enabled"):
        assert field not in event.before and field not in event.after, field
    text = json.dumps([event.before, event.after], ensure_ascii=False)
    leaks = _leaks(settings, text)
    assert not leaks, leaks
    assert model("core.AuditEvent").objects.filter(action="notify.settings_changed").count() == 1
    # повторная отправка той же таблицы ничего не меняет — новой записи нет
    again = _post(admin, enable=["telegram"], limits=("30", "100"), cells=_cells({NEW_IN_QUEUE: ["push"]}))
    assert again.status_code == 302
    assert len(_events()) == 1, "повтор без изменений записан в журнал"


def test_error_messages_and_responses_of_page_contain_no_secrets(settings, caplog):
    """FR-337, NFR-312: значений ключей и токенов нет в отказах страницы, ответе 403, ошибке сервиса и журнале приложения."""
    from apps.notify.services import NotifyError
    _set_env(settings, "TELEGRAM_BOT_TOKEN", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY")
    user, admin = _admin(ip="198.51.100.42")
    bodies = []
    refused = _post(admin, enable=["webpush", "max", "telegram"], limits=("3", "400"), cells=_cells({NEW_IN_QUEUE: ["push"]}))
    assert refused.status_code == 200
    bodies.append(_body(refused))
    doc = _doc(refused)
    codes = {e.attrs["data-error"]: e.attrs["data-code"] for e in _find(doc, None, {"data-error": True, "data-code": True})}
    assert codes and set(codes.values()) <= {"keys_missing", "out_of_range"}
    bodies.append(_body(admin.get(URL)))
    bodies.append(_body(_post(admin, enable=["telegram"], limits=("20", "100"))))
    outsider = support.logged_in(support.make_with_permissions("settings.portal"), ip="198.51.100.43")
    bodies.append(_body(outsider.get(URL)))
    bodies.append(_body(_post(outsider, enable=["telegram"])))
    with pytest.raises(NotifyError) as info:
        _svc().update(actor=user, webpush_enabled=True)
    assert info.value.code == "keys_missing"
    with pytest.raises(NotifyError) as other:
        _svc().update(actor=user, max_enabled=True)
    assert other.value.code == "keys_missing"
    bodies += [str(info.value), str(other.value), info.value.message, other.value.message, caplog.text]
    leaks = _leaks(settings, *bodies)
    assert not leaks, leaks
    bad = [r for r in caplog.records if r.name == "apps.core.events" and r.levelname == "ERROR"]
    assert not bad
