"""T-9125: настройки задач `/settings/tasks/` — срок хранения (FR-696; CONTRACT-009, 6.2, 10.1, 12.1, 12.2).

План «Настройки задач»: право `settings.portal`, срок 1–10 лет, второй шаг подтверждения при уменьшении, запись
`tasks.retention_changed` «было / стало», `TaskSettings` создаётся лениво; смена срока влияет только на будущие
уборки. Контракт: 6.1 (403 без права раньше службы), 6.2 (`/settings/tasks/`: `retention_years`, `confirm`), 6.3
(`[data-tasks-page="settings"]`, `[data-tasks-confirm]`, `[data-retention-years]`), 10.1 (запись журнала), 12.1
(`retention_range`, `retention_decrease`), 12.2 («Хранить задачи, лет»).

Код среза на уровне модуля не импортируется: модели — `support.model(...)`, службы и задания — внутри тестов, поэтому
`pytest --collect-only` проходит до появления кода. Секретов и ПДн нет.
"""
import datetime
import inspect
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_tasks

pytestmark = pytest.mark.django_db

URL = "/settings/tasks/"
LABEL = "Хранить задачи, лет"
TEXT_RANGE = "Срок хранения — от 1 до 10 лет"
TEXT_CONFIRM = "Ближайшая уборка удалит задач: {n}"
EDIT_WORD = "Подтвердить"
ACTION = "tasks.retention_changed"


# --- разбор разметки (помощник только этого файла, как в test_messenger_settings.py) ----------------------

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
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


# --- помощники файла --------------------------------------------------------------------------------------

def _settings_model():
    return support.model("tasks.TaskSettings")


def _set_settings(retention: int = 3) -> None:
    _settings_model().objects.update_or_create(pk=1, defaults={"retention_years": retention})


def _row():
    return _settings_model().objects.get(pk=1)


def _years() -> int:
    return _row().retention_years


def _events(action: str | None = None) -> list:
    found = support.model("core.AuditEvent").objects.order_by("id")
    if action is not None:
        found = found.filter(action=action)
    return list(found)


def _old_deleted(*ages_days: int) -> list:
    """Задачи, мягко удалённые известное число дней назад (для будущей уборки)."""
    author = support_tasks.staff_user(full_name="Автор Уборки")
    now = timezone.now()
    tasks = []
    for index, age in enumerate(ages_days, start=1):
        task = support_tasks.make_task(f"Удалённая задача {index}", author=author, assignee=author)
        support.model("tasks.Task").objects.filter(pk=task.pk).update(deleted_at=now - datetime.timedelta(days=age))
        tasks.append(task)
    return tasks


def _spy_settings_service(monkeypatch) -> list:
    from apps.tasks.services import settings as tasks_settings

    calls: list[str] = []
    module_name = tasks_settings.__name__
    for name, value in vars(tasks_settings).items():
        if name.startswith("_") or not inspect.isfunction(value) or value.__module__ != module_name:
            continue

        def spy(*args, __name=name, __func=value, **kwargs):
            calls.append(__name)
            return __func(*args, **kwargs)

        monkeypatch.setattr(tasks_settings, name, spy)
    return calls


# --- право и страница -------------------------------------------------------------------------------------

def test_page_requires_settings_portal_403(monkeypatch):
    """FR-696 (CONTRACT-009, 6.1, 10.1): без `settings.portal` — 403 на GET и POST, служба настроек не вызывается;
    значение и журнал не меняются. Права `settings.security` и права других срезов страницу не открывают."""
    _set_settings(3)
    calls = _spy_settings_service(monkeypatch)
    others = [support.logged_in(support.make_with_permissions("settings.security")),
              support.logged_in(support.make_with_permissions("tasks.use")),
              support_tasks.staff_user().client]
    for client in others:
        assert client.get(URL).status_code == 403
        assert client.post(URL, {"retention_years": "1", "confirm": "1"}).status_code == 403
        assert client.post(URL, {"retention_years": "5"}).status_code == 403
    assert calls == [], f"403 обратился к службе настроек: {calls}"
    assert _years() == 3
    assert _events(ACTION) == []


def test_form_shows_retention_and_confirm_hook():
    """FR-696 (CONTRACT-009, 6.3, 12.2): страница открывается с `[data-tasks-page="settings"]`, надписью «Настройки
    задач» и «Хранить задачи, лет», полем `retention_years` со значением из строки и зацепкой
    `[data-retention-years]`; второго шага на GET нет."""
    _set_settings(4)
    admin = support.make_admin(full_name="Администратор Формы Задач")
    response = support.logged_in(admin).get(URL)
    assert response.status_code == 200, f"{URL}: {response.status_code}"
    html = response.content.decode("utf-8")
    page = tree(html)
    assert len(q(page, data_tasks_page="settings")) == 1, "нет корня [data-tasks-page=\"settings\"]"
    assert "Настройки задач" in html and LABEL in html
    assert q(page, data_retention_years=True), "нет зацепки [data-retention-years]"
    fields = q(page, "input", name="retention_years")
    assert len(fields) == 1 and fields[0].attrs.get("value") == "4"
    assert not q(page, data_tasks_confirm=True), "на GET показан второй шаг"


# --- сохранение, журнал и второй шаг ----------------------------------------------------------------------

def test_increase_saves_immediately_and_audits_before_after():
    """FR-696 (CONTRACT-009, 10.1, 10.2): увеличение срока сохраняется сразу — 302 на ту же страницу; журнал
    `tasks.retention_changed` — объект `tasks.settings`/`1`, «было / стало» с ключом `years`; `updated_at` и
    `updated_by` записаны."""
    _set_settings(3)
    admin = support.make_admin(full_name="Администратор Срока")
    client = support.logged_in(admin)
    before = timezone.now()
    response = client.post(URL, {"retention_years": "5"})
    assert response.status_code == 302
    assert response["Location"] == URL
    assert _years() == 5
    row = _row()
    assert row.updated_by_id == admin.pk and row.updated_at is not None and row.updated_at >= before

    events = _events(ACTION)
    assert len(events) == 1, f"записей журнала: {len(events)}"
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("tasks.settings", "1", admin.pk)
    assert event.before == {"years": 3} and event.after == {"years": 5}
    assert not q(tree(client.get(URL)), data_tasks_confirm=True), "увеличение — без второго шага"


def test_decrease_needs_second_step_with_count_and_keeps_value():
    """FR-696 (CONTRACT-009, 6.2, 12.1): уменьшение 3 → 1 без `confirm` — 200 со вторым шагом
    `[data-tasks-confirm]`: «Ближайшая уборка удалит задач: N» (N — удалённые задачи старше новой границы), кнопка
    «Подтвердить» `button[name="confirm"][value="1"]` и скрытое новое значение; значение и журнал прежние; с
    `confirm=1` значение сохраняется и пишется «было / стало»."""
    _set_settings(3)
    old = _old_deleted(800, 400, 1200)
    _old_deleted(30)
    admin = support.make_admin(full_name="Администратор Второго Шага")
    client = support.logged_in(admin)

    response = client.post(URL, {"retention_years": "1"})
    assert response.status_code == 200
    steps = q(tree(response), data_tasks_confirm=True)
    assert len(steps) == 1, "нет второго шага [data-tasks-confirm]"
    assert TEXT_CONFIRM.format(n=3) in steps[0].text(), steps[0].text()
    buttons = q(steps[0], "button", name="confirm", value="1")
    assert len(buttons) == 1 and EDIT_WORD in buttons[0].text()
    hidden = q(steps[0], "input", name="retention_years", type="hidden")
    assert [node.attrs.get("value") for node in hidden] == ["1"]
    assert _years() == 3, "без подтверждения значение изменилось"
    assert _events(ACTION) == []
    assert support.model("tasks.Task").objects.filter(pk__in=[task.pk for task in old]).count() == 3, (
        "второй шаг сразу убрал задачи")

    assert client.post(URL, {"retention_years": "1"}).status_code == 200
    assert _years() == 3, "повтор без подтверждения изменил значение"

    saved = client.post(URL, {"retention_years": "1", "confirm": "1"})
    assert saved.status_code == 302 and saved["Location"] == URL
    assert _years() == 1
    events = _events(ACTION)
    assert len(events) == 1
    assert (events[0].before.get("years"), events[0].after.get("years")) == (3, 1)


# --- границы значения -------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["0", "11", "abc", "", "-1", "2.5"])
def test_out_of_range_shows_reason_and_keeps_value(bad):
    """FR-696 (CONTRACT-009, 6.1, 12.1): 0, 11, не число, пусто, отрицательное и дробное — 200 с причиной
    «Срок хранения — от 1 до 10 лет» у поля `retention_years` (`data-code="retention_range"`); значение и журнал
    прежние."""
    _set_settings(4)
    admin = support.make_admin(full_name="Администратор Границы")
    response = support.logged_in(admin).post(URL, {"retention_years": bad})
    assert response.status_code == 200
    errors = q(tree(response), data_error="retention_years", data_code="retention_range")
    assert len(errors) == 1
    assert TEXT_RANGE in errors[0].text()
    assert _years() == 4
    assert _events(ACTION) == []


# --- влияние только на будущие уборки ---------------------------------------------------------------------

def test_change_affects_only_future_cleanup_runs():
    """FR-696 (CONTRACT-009, 6.2): смена срока сама ничего не удаляет — удалённые задачи остаются; ночная уборка
    `tasks_retention(now=…)` после смены срока убирает только то, что подпадает под новый срок: задача,
    удалённая два года назад, при сроке 3 года остаётся, после смены на 1 год — удаляется, а удалённая полгода назад
    остаётся."""
    _set_settings(3)
    two_years, six_months = _old_deleted(730, 180)
    admin = support.make_admin(full_name="Администратор Уборки")
    client = support.logged_in(admin)
    Task = support.model("tasks.Task")
    from apps.tasks import tasks as tasks_module

    now = timezone.now()
    tasks_module.tasks_retention(now=now)
    assert Task.objects.filter(pk=two_years.pk).exists(), "уборка при сроке 3 года удалила задачу двухлетней давности"
    assert Task.objects.filter(pk=six_months.pk).exists()

    assert client.post(URL, {"retention_years": "1", "confirm": "1"}).status_code == 302
    assert Task.objects.filter(pk=two_years.pk).exists(), "смена настройки сразу удалила задачу"
    tasks_module.tasks_retention(now=now)
    assert not Task.objects.filter(pk=two_years.pk).exists(), "будущая уборка не учла новый срок"
    assert Task.objects.filter(pk=six_months.pk).exists(), "уборка удалила задачу моложе нового срока"