"""T-7116: настройка срока хранения записей ленты — `/settings/feed/`, пункт меню «Настройки ленты», журнал (FR-638,
FR-639, FR-642). План: «Срок хранения и ночное задание» (настройка), «Точки расширения ядра и шина событий»
(`menu_items`), «Контракты» (`/settings/feed/`); CONTRACT-007: 2.2 (`FeedSettings`), 2.3, 3.3, 5.5 (`feed_settings`),
8.1, 10.2, 12.7, 13.1.

Страница — право ядра `settings.portal`; без него 403 на GET и POST без обращения к `feed_settings` (решение 11 задач).
Уменьшение срока — второй шаг с числом записей и «Подтвердить»; без подтверждения значение не меняется.
Код среза на уровне модуля не импортируется (CONTRACT-005/006, шапка). Тексты — литералы раздела 13.
"""
import datetime
import importlib
from html.parser import HTMLParser

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests import support
from tests import support_feed as fd

pytestmark = pytest.mark.django_db

URL = "/settings/feed/"
TEXT_RANGE = "Срок хранения — от 1 до 10 лет"
TEXT_TITLE = "Настройки портала → Лента"
TEXT_LABEL = "Хранить записи ленты, лет"
TEXT_CONFIRM = "Ближайшее ночное задание удалит записей: {n}"


# --- разбор разметки (помощник только этого файла) -----------------------------------------------------------------

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
    return support.model("feed.FeedSettings")


def _years() -> int:
    return _settings_model().objects.get(pk=1).retention_years


def _set_years(years: int) -> None:
    _settings_model().objects.update_or_create(pk=1, defaults={"retention_years": years})


def _admin():
    user = support.make_with_permissions("settings.portal")
    return user, support.logged_in(user)


def _journal(action: str = "feed.retention_changed") -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _old_posts(*ages_days: int) -> list:
    """Записи нужного возраста (дней), опубликованные прямой записью."""
    author = support.make_employee()
    now = timezone.now()
    return [fd.make_post(author, to=("all",), published_at=now - datetime.timedelta(days=age))
            for age in ages_days]


def _menu(user) -> list:
    from apps.core.services import permissions

    return permissions.menu_for(user)


def _item(items, url: str):
    found = [item for item in items if item["url"] == url]
    return found[0] if found else None


# --- страница -----------------------------------------------------------------------------------------------

def test_settings_feed_page_has_portal_settings_feed_title_and_retention_years_field_for_settings_portal():
    """FR-638: страница «Настройки портала → Лента» со своим полем «Хранить записи ленты, лет» у держателя права."""
    _, client = _admin()
    response = client.get(URL)
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    page = tree(html)
    assert q(page, data_feed_page="settings")
    assert TEXT_TITLE in html
    assert TEXT_LABEL in html
    assert len(q(page, "input", name="retention_years")) == 1


def test_settings_feed_without_settings_portal_is_403_on_get_and_post_without_calling_settings_service(monkeypatch):
    """FR-638 (решение 11 задач): без `settings.portal` — 403 на GET и POST; служба настройки не вызывается;
    другие права настроек и права ленты страницу не открывают."""
    module = importlib.import_module("apps.feed.services.feed_settings")
    calls = []
    real_get, real_save = module.get, module.save

    def spy_get(*args, **kwargs):
        calls.append("get")
        return real_get(*args, **kwargs)

    def spy_save(*args, **kwargs):
        calls.append("save")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(module, "get", spy_get)
    monkeypatch.setattr(module, "save", spy_save)
    _set_years(3)
    others = [support.make_employee(), support.make_with_permissions("settings.security"),
              support.make_with_permissions("feed.moderate", "feed.post_all")]
    for user in others:
        client = support.logged_in(user)
        assert client.get(URL).status_code == 403
        assert client.post(URL, {"retention_years": "1", "confirm": "1"}).status_code == 403
        assert client.post(URL, {"retention_years": "5"}).status_code == 403
    assert calls == []
    assert _years() == 3
    assert _journal() == []


def test_new_install_shows_retention_3_from_migration_row():
    """FR-638: на новой установке срок — 3 года из строки миграции; страница показывает 3."""
    row = _settings_model().objects.get(pk=1)
    assert row.retention_years == 3
    _, client = _admin()
    page = tree(client.get(URL))
    field = q(page, "input", name="retention_years")[0]
    assert field.attrs.get("value") == "3"


def test_feed_settings_get_creates_row_with_3_when_missing():
    """FR-638 (CONTRACT-007, 2.3): `feed_settings.get()` отдаёт строку `pk=1`, создаёт её со сроком 3, если нет."""
    from apps.feed.services import feed_settings

    _settings_model().objects.all().delete()
    assert not _settings_model().objects.exists()
    row = feed_settings.get()
    assert row.pk == 1
    assert row.retention_years == 3
    assert _settings_model().objects.filter(pk=1, retention_years=3).count() == 1


# --- границы значения ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["0", "11", "abc", "", "-1", "2.5"])
def test_retention_0_11_and_not_a_number_are_refused_with_from_1_to_10_years_and_value_is_unchanged(bad):
    """FR-638, FR-642: 0, 11 и не число — отказ «Срок хранения — от 1 до 10 лет» у поля; значение и журнал прежние."""
    _set_years(3)
    _, client = _admin()
    response = client.post(URL, {"retention_years": bad, "confirm": "1"})
    assert response.status_code == 200
    page = tree(response)
    errors = q(page, data_error="retention_years", data_code="retention_range")
    assert len(errors) == 1
    assert TEXT_RANGE in errors[0].text()
    assert _years() == 3
    assert _journal() == []


def test_retention_1_with_confirmation_and_10_are_accepted():
    """FR-638: границы 1 (уменьшение — с подтверждением) и 10 (увеличение) принимаются, адрес — 302 на страницу."""
    _set_years(3)
    _, client = _admin()
    response = client.post(URL, {"retention_years": "1", "confirm": "1"})
    assert response.status_code == 302
    assert response["Location"] == URL
    assert _years() == 1
    response = client.post(URL, {"retention_years": "10"})
    assert response.status_code == 302
    assert response["Location"] == URL
    assert _years() == 10


# --- уменьшение: второй шаг ---------------------------------------------------------------------------------

def test_decrease_from_3_to_1_shows_second_step_with_count_of_posts_before_new_boundary_and_confirm_button():
    """FR-638: уменьшение 3 → 1 без подтверждения — второй шаг «Ближайшее ночное задание удалит записей: N», где N —
    записи с `published_at` раньше новой границы (год назад), и кнопка «Подтвердить»; значение не меняется."""
    _set_years(3)
    _old_posts(800, 400, 1200, 200, 30)   # старше года: 800, 400, 1200 → три
    _, client = _admin()
    response = client.post(URL, {"retention_years": "1"})
    assert response.status_code == 200
    page = tree(response)
    steps = q(page, data_feed_confirm=True)
    assert len(steps) == 1
    assert TEXT_CONFIRM.format(n=3) in steps[0].text()
    buttons = q(page, "button", name="confirm", value="1")
    assert len(buttons) == 1
    assert "Подтвердить" in buttons[0].text()
    hidden = q(page, "input", name="retention_years", type="hidden")
    assert [node.attrs.get("value") for node in hidden] == ["1"]
    assert _years() == 3


def test_decrease_without_confirmation_keeps_value_and_writes_no_journal():
    """FR-638: без `confirm` значение прежнее, журнал пуст — и при повторной отправке без подтверждения."""
    _set_years(3)
    _, client = _admin()
    for _ in range(2):
        assert client.post(URL, {"retention_years": "1"}).status_code == 200
    assert client.post(URL, {"retention_years": "2", "confirm": ""}).status_code == 200
    assert _years() == 3
    assert _journal() == []


def test_decrease_with_confirmation_saves_value_and_writes_retention_changed_with_years_before_and_after():
    """FR-638, FR-639: подтверждённое уменьшение сохраняет значение и пишет `feed.retention_changed`:
    объект `feed.settings`/`1`, `before` и `after` — только `years`; автор правки записан."""
    _set_years(3)
    admin, client = _admin()
    response = client.post(URL, {"retention_years": "1", "confirm": "1"})
    assert response.status_code == 302
    row = _settings_model().objects.get(pk=1)
    assert row.retention_years == 1
    assert row.updated_by_id == admin.pk
    assert row.updated_at is not None
    events = _journal()
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id) == ("feed.settings", "1")
    assert event.actor_id == admin.pk
    assert event.before == {"years": 3}
    assert event.after == {"years": 1}


def test_increase_is_saved_at_once_without_second_step_and_journaled():
    """FR-638, FR-639: увеличение сохраняется сразу, без второго шага, и пишется в журнал «было / стало»."""
    _set_years(3)
    _, client = _admin()
    response = client.post(URL, {"retention_years": "5"})
    assert response.status_code == 302
    assert not q(tree(client.get(URL)), data_feed_confirm=True)
    assert _years() == 5
    events = _journal()
    assert len(events) == 1
    assert events[0].before == {"years": 3}
    assert events[0].after == {"years": 5}


# --- пункт меню ---------------------------------------------------------------------------------------------

def test_menu_item_feed_settings_has_url_order_63_and_gear_icon_for_settings_portal():
    """FR-638: пункт «Настройки ленты» — адрес `/settings/feed/`, `order` 63, значок `icons/gear.html`, право
    `settings.portal`; он есть в меню держателя права."""
    from apps.feed import extensions

    declared = _item(extensions.menu_items(), URL)
    assert declared is not None
    for name, value in fd.MENU_FEED_SETTINGS.items():
        assert declared[name] == value
    assert tuple(declared["permissions"]) == ("settings.portal",)
    user, _ = _admin()
    shown = _item(_menu(user), URL)
    assert shown is not None
    assert (shown["title"], shown["order"], shown["icon"]) == ("Настройки ленты", 63, "icons/gear.html")


def test_menu_item_feed_settings_is_absent_without_settings_portal():
    """FR-638: без `settings.portal` пункта «Настройки ленты» в меню нет (пункт «Лента» — есть)."""
    user = support.make_employee()
    items = _menu(user)
    assert _item(items, URL) is None
    assert _item(items, "/") is not None


# --- ограничение базы ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("years", [0, 11, 255])
def test_db_check_rejects_retention_years_outside_1_to_10(years):
    """FR-638 (CONTRACT-007, 2.2): `CheckConstraint` базы — срок только 1…10; 1 и 10 допустимы."""
    _set_years(3)
    for good in (1, 10):
        _settings_model().objects.filter(pk=1).update(retention_years=good)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _settings_model().objects.filter(pk=1).update(retention_years=years)
    assert _years() == 10
