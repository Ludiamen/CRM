"""T-8120: настройки портала `/settings/messenger/` — срок хранения и «Общий чат» (FR-651, FR-670, FR-671).

План: «Срок хранения и ночное задание» → «Настройка» (поле 1–10, второй шаг при уменьшении, журнал «было / стало»,
`updated_at`/`updated_by`), «Права среза» (`settings.portal`); CONTRACT-008: 2.2 (`MessengerSettings`), 2.3
(`messenger_settings.get`), 8.1 (`messenger.retention_changed`, `messenger.general_changed` — «включён» / «выключен»),
10.1 (403 без права раньше обращения к службе), 10.2 (`/settings/messenger/`), 12.6 (`[data-messenger-page="settings"]`,
`[data-messenger-confirm]`), 13.1 (`retention_range`), 13.2 (`purge_count`), 13.3 («Настройки портала → Мессенджер»,
«Хранить сообщения, лет»).

Семь тестов T-8120, других нет. Код среза на уровне модуля не импортируется (правила для всех тестов среза):
модели — `support.model(...)`, службы — ленивые импорты внутри тестов; тексты — литералы разделов 13. Секретов и ПДн
нет.
"""
import datetime
import inspect
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_messenger as mm

pytestmark = pytest.mark.django_db

URL = "/settings/messenger/"
TEXT_TITLE = "Настройки портала → Мессенджер"
TEXT_LABEL = "Хранить сообщения, лет"
TEXT_RANGE = "Срок хранения — от 1 до 10 лет"
TEXT_CONFIRM = "Ближайшее ночное задание удалит сообщений: {n}"
EDIT_WORD = "Подтвердить"
ENABLED_WORD = "включён"
DISABLED_WORD = "выключен"
ACTION_RETENTION = "messenger.retention_changed"
ACTION_GENERAL = "messenger.general_changed"


# --- разбор разметки (помощник только этого файла, как в test_feed_settings.py) --------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- помощники файла ------------------------------------------------------------------------------------------

def _settings_model():
    return support.model("messenger.MessengerSettings")


def _set_settings(retention: int = 3, general: bool = True) -> None:
    """Строка `pk=1` с известными значениями (`MessengerSettings`, CONTRACT-008, 2.2)."""
    _settings_model().objects.update_or_create(
        pk=1, defaults={"retention_years": retention, "general_chat_enabled": general})


def _row():
    return _settings_model().objects.get(pk=1)


def _years() -> int:
    return _row().retention_years


def _events(action: str | None = None) -> list:
    """Записи журнала (`core.AuditEvent`) по коду действия, в порядке появления."""
    found = support.model("core.AuditEvent").objects.order_by("id")
    if action is not None:
        found = found.filter(action=action)
    return list(found)


def _old_messages(*ages_days: int) -> None:
    """Сообщения известного возраста (дней) в личном диалоге — прямой записью помощника среза."""
    author = mm.make_user(full_name="Автор Старых")
    peer = mm.make_user(full_name="Собеседник Старых")
    chat = mm.personal(author, peer)
    now = timezone.now()
    for index, age in enumerate(ages_days, start=1):
        mm.post(chat, author, text=f"Старое сообщение {index}", created_at=now - datetime.timedelta(days=age))


def _spy_settings_service(monkeypatch) -> list:
    """Оборачивает функции модуля `messenger_settings`: 403 не должен доходить до службы (CONTRACT-008, 10.1)."""
    from apps.messenger.services import messenger_settings

    calls: list[str] = []
    module_name = messenger_settings.__name__
    for name, value in vars(messenger_settings).items():
        if name.startswith("_") or not inspect.isfunction(value) or value.__module__ != module_name:
            continue

        def spy(*args, __name=name, __func=value, **kwargs):
            calls.append(__name)
            return __func(*args, **kwargs)

        monkeypatch.setattr(messenger_settings, name, spy)
    return calls


# --- право и страница -----------------------------------------------------------------------------------------

def test_page_requires_settings_portal_403(monkeypatch):
    """FR-670 (CONTRACT-008, 10.1): без `settings.portal` — 403 на GET и POST, служба `messenger_settings` не
    вызывается; ни значение, ни журнал не меняются. Другие права настроек страницу не открывают."""
    _set_settings(3, True)
    calls = _spy_settings_service(monkeypatch)
    others = [
        mm.make_user().client,
        support.logged_in(support.make_with_permissions("settings.security")),
        support.logged_in(support.make_with_permissions("feed.moderate", "feed.post_all")),
    ]
    for client in others:
        assert client.get(URL).status_code == 403
        assert client.post(URL, {"retention_years": "1", "confirm": "1"}).status_code == 403
        assert client.post(URL, {"retention_years": "5"}).status_code == 403
    assert calls == [], f"403 обратился к службе настроек: {calls}"
    assert _years() == 3
    assert _row().general_chat_enabled is True
    assert _events(ACTION_RETENTION) == [] and _events(ACTION_GENERAL) == []


def test_form_shows_retention_and_general_checkbox():
    """FR-651, FR-670 (CONTRACT-008, 10.2, 12.6, 13.3): держателю права страница открывается с зацепкой
    `[data-messenger-page="settings"]`, заголовком «Настройки портала → Мессенджер», полем «Хранить сообщения, лет»
    со сроком из строки настроек и галочкой `general_chat_enabled`, отмеченной по текущему значению."""
    _set_settings(3, True)
    admin = mm.as_admin()
    response = admin.client.get(URL)
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    page = tree(html)
    assert len(q(page, data_messenger_page="settings")) == 1
    assert TEXT_TITLE in html
    assert TEXT_LABEL in html
    fields = q(page, "input", name="retention_years")
    assert len(fields) == 1
    assert fields[0].attrs.get("value") == "3"
    boxes = q(page, "input", name="general_chat_enabled")
    assert len(boxes) == 1
    assert boxes[0].attrs.get("type") == "checkbox"
    assert "checked" in boxes[0].attrs, "включённый «Общий чат» — галочка отмечена"

    _set_settings(3, False)
    off = q(tree(admin.client.get(URL)), "input", name="general_chat_enabled")
    assert len(off) == 1
    assert "checked" not in off[0].attrs, "выключенный «Общий чат» — галочка снята"


# --- срок хранения: сохранение и второй шаг -------------------------------------------------------------------

def test_increase_saves_immediately_and_audits_before_after():
    """FR-670, FR-671 (CONTRACT-008, 8.1, 10.2): увеличение срока сохраняется сразу без второго шага — 302 на ту же
    страницу, поле показывает новое значение; журнал `messenger.retention_changed` — объект `messenger.settings`/`1`,
    `before`/`after` с ключом `years`; неизменённая галочка «Общий чат» записи не даёт."""
    _set_settings(3, True)
    admin = mm.as_admin()
    response = admin.client.post(URL, {"retention_years": "5", "general_chat_enabled": "on"})
    assert response.status_code == 302
    assert response["Location"] == URL
    assert _years() == 5
    assert not q(tree(admin.client.get(URL)), data_messenger_confirm=True), "увеличение — без второго шага"
    field = q(tree(admin.client.get(URL)), "input", name="retention_years")[0]
    assert field.attrs.get("value") == "5"
    events = _events(ACTION_RETENTION)
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("messenger.settings", "1", admin.user.pk)
    assert event.before == {"years": 3}
    assert event.after == {"years": 5}
    assert _events(ACTION_GENERAL) == [], "неизменённая галочка не пишет запись журнала"


def test_decrease_needs_second_step_with_count_and_keeps_value_without_confirm():
    """FR-670 (CONTRACT-008, 10.2, 13.2): уменьшение 3 → 1 без `confirm` — 200 со вторым шагом
    `[data-messenger-confirm]`: «Ближайшее ночное задание удалит сообщений: N», где N — сообщения старше новой
    границы (год назад; 3 из 5), кнопка «Подтвердить» `button[name="confirm"][value="1"]` и скрытое новое значение;
    значение и журнал прежние и при повторе; с `confirm=1` значение сохраняется и пишется «было / стало»."""
    _set_settings(3, True)
    _old_messages(800, 400, 1200, 200, 30)   # старше года: 800, 400, 1200 → три
    admin = mm.as_admin()

    response = admin.client.post(URL, {"retention_years": "1"})
    assert response.status_code == 200
    steps = q(tree(response), data_messenger_confirm=True)
    assert len(steps) == 1
    assert TEXT_CONFIRM.format(n=3) in steps[0].text(), steps[0].text()
    buttons = q(steps[0], "button", name="confirm", value="1")
    assert len(buttons) == 1
    assert EDIT_WORD in buttons[0].text()
    hidden = q(steps[0], "input", name="retention_years", type="hidden")
    assert [node.attrs.get("value") for node in hidden] == ["1"]
    assert _years() == 3, "без подтверждения значение не меняется"
    assert _events(ACTION_RETENTION) == []

    assert admin.client.post(URL, {"retention_years": "1"}).status_code == 200
    assert _years() == 3, "повтор без подтверждения тоже не меняет значение"

    saved = admin.client.post(URL, {"retention_years": "1", "confirm": "1"})
    assert saved.status_code == 302
    assert saved["Location"] == URL
    assert _years() == 1
    events = _events(ACTION_RETENTION)
    assert len(events) == 1
    assert (events[0].before.get("years"), events[0].after.get("years")) == (3, 1)


# --- «Общий чат» ----------------------------------------------------------------------------------------------

def test_general_toggle_writes_audit_enabled_disabled():
    """FR-651, FR-671 (CONTRACT-008, 8.1): снятая галочка выключает «Общий чат», поставленная — включает; обе смены
    пишут по записи `messenger.general_changed` объекта `messenger.settings`/`1` со словами «включён» / «выключен»
    в «было / стало»; срок хранения не меняется и `messenger.retention_changed` не пишется."""
    _set_settings(3, True)
    admin = mm.as_admin()
    for data, enabled in (({"retention_years": "3"}, False),
                          ({"retention_years": "3", "general_chat_enabled": "on"}, True)):
        response = admin.client.post(URL, data)
        assert response.status_code == 302
        assert response["Location"] == URL
        assert _row().general_chat_enabled is enabled, "галочка «Общий чат» не сохранена"

    events = _events(ACTION_GENERAL)
    assert len(events) == 2, "выключение и включение — две записи журнала"
    off, on = events
    for event in events:
        assert (event.object_type, event.object_id, event.actor_id) == ("messenger.settings", "1", admin.user.pk)
    assert ENABLED_WORD in off.before.values() and DISABLED_WORD in off.after.values(), (
        f"запись выключения: было {off.before}, стало {off.after}")
    assert DISABLED_WORD in on.before.values() and ENABLED_WORD in on.after.values(), (
        f"запись включения: было {on.before}, стало {on.after}")
    assert _events(ACTION_RETENTION) == [], "смена галочки не пишет срок хранения"


# --- границы значения -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["0", "11", "abc", "", "-1", "2.5"])
def test_out_of_range_shows_reason_and_keeps_value(bad):
    """FR-670 (CONTRACT-008, 10.2, 13.1): 0, 11, не число, пусто, отрицательное и дробное — 200 с причиной
    «Срок хранения — от 1 до 10 лет» у поля `retention_years` (`data-code="retention_range"`); значение, галочка и
    журнал прежние."""
    _set_settings(4, True)
    admin = mm.as_admin()
    response = admin.client.post(URL, {"retention_years": bad})
    assert response.status_code == 200
    errors = q(tree(response), data_error="retention_years", data_code="retention_range")
    assert len(errors) == 1
    assert TEXT_RANGE in errors[0].text()
    assert _years() == 4
    assert _row().general_chat_enabled is True
    assert _events(ACTION_RETENTION) == [] and _events(ACTION_GENERAL) == []


# --- отметка изменения ----------------------------------------------------------------------------------------

def test_settings_updated_at_and_by_saved():
    """FR-670 (план, «Настройка»): сохранение срока пишет `updated_at` (время сохранения) и `updated_by`
    (администратор портала) в строку настроек."""
    _set_settings(3, True)
    _settings_model().objects.filter(pk=1).update(updated_at=None, updated_by=None)
    admin = mm.as_admin()
    before = timezone.now()
    assert admin.client.post(URL, {"retention_years": "6", "general_chat_enabled": "on"}).status_code == 302
    row = _row()
    assert (row.retention_years, row.updated_by_id) == (6, admin.user.pk)
    assert row.updated_at is not None, "время сохранения не записано"
    assert before <= row.updated_at <= timezone.now()