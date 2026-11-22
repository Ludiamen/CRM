"""Общие помощники серверных тестов среза 009 «Задачи» (T-9006; CONTRACT-009, 5.4).

Код среза (`apps.tasks`) на уровне модуля не импортируется: сбор тестов проходит до появления кода, а падения
видны поимённо при вызове. Модели берутся лениво через `support.model(...)`; службы — внутри функций.
Пароли и секреты — только из `tests.factories`; настоящих ПДн в помощниках нет.
"""
from html.parser import HTMLParser

from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import support, support_org

PERMISSIONS_009 = ("tasks.use", "tasks.assign")

PAGE_PATHS = (
    "/tasks/",
    "/tasks/new/",
    "/tasks/board/status/",
    "/tasks/board/deadline/",
    "/tasks/board/plan/",
    "/tasks/board/category/",
    "/settings/tasks/",
    "/settings/tasks/categories/",
)


# --- люди и роли ---------------------------------------------------------------------------------

def staff_user(**extra):
    """Сотрудник с встроенной ролью «Сотрудник ИТ» (у неё `tasks.use` и `tasks.assign`)."""
    return support.make_employee(roles=[support.role_by_name(support.STAFF_ROLE)], **extra)


def viewer(**extra):
    """Сотрудник с правами `tasks.use` и `tasks.assign` через свою роль (не встроенную)."""
    return support.make_with_permissions(*PERMISSIONS_009, **extra)


def head_of(unit, **extra):
    """Сотрудник — руководитель узла `unit` (членство с `mark="head"`)."""
    user = staff_user(**extra)
    support_org.make_member(user, unit, mark="head")
    return user


def deputy_of(unit, **extra):
    """Сотрудник — заместитель узла `unit` (членство с `mark="deputy"`)."""
    user = staff_user(**extra)
    support_org.make_member(user, unit, mark="deputy")
    return user


# --- задачи и справочники ------------------------------------------------------------------------

def make_task(title="Задача", *, author=None, assignee=None, deadline=None, status="new",
              description="", category=None, plan_column=None, **extra):
    """Задача через ORM; по умолчанию автор и исполнитель — свежий сотрудник с ролью «Сотрудник ИТ»."""
    Task = support.model("tasks.Task")
    author = author or staff_user()
    assignee = assignee or author
    return Task.objects.create(
        title=title, description=description, deadline=deadline, author=author, assignee=assignee,
        status=status, category=category, plan_column=plan_column, **extra)


def add_member(task, user, role="coexecutor"):
    """Строка `TaskMember`: роль `coexecutor` или `observer`."""
    return support.model("tasks.TaskMember").objects.create(task=task, user=user, role=role)


def make_column(user, title="Сегодня", position=0):
    """Колонка личного плана сотрудника."""
    return support.model("tasks.PlanColumn").objects.create(user=user, title=title, position=position)


def make_category(title="Работа", position=0):
    """Строка справочника категорий."""
    return support.model("tasks.TaskCategory").objects.create(title=title, position=position)


def reminders_of(task):
    """Напоминания задачи по возрастанию момента, затем номера."""
    return list(support.model("tasks.TaskReminder").objects.filter(task=task).order_by("moment", "pk"))


# --- запросы и разбор разметки -------------------------------------------------------------------

def move(client, task, board, value, **extra):
    """`POST /tasks/<id>/move/`; по умолчанию — запрос HTMX (фрагмент колонок), иначе передайте свой заголовок."""
    extra.setdefault("HTTP_HX_REQUEST", "true")
    return client.post(f"/tasks/{task.pk}/move/", {"board": board, "value": value}, **extra)


def post_comment(client, task, text="Комментарий", **extra):
    """`POST /tasks/<id>/comments/`; по умолчанию — обычный запрос (302 на карточку)."""
    return client.post(f"/tasks/{task.pk}/comments/", {"text": text}, **extra)


class _BoardParser(HTMLParser):
    """Собирает `[data-column="<ключ>"]` и следующие за ними `[data-task-id]` (порядок документа).

    Карточки стоят внутри своей колонки, поэтому достаточно помнить текущий ключ: следующая колонка его меняет.
    Так разбор не зависит от вложенности и незакрытых тегов фрагмента.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.columns: dict[str, list[int]] = {}
        self._current: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-column" in attrs:
            self._current = str(attrs["data-column"])
            self.columns.setdefault(self._current, [])
        elif "data-task-id" in attrs and self._current is not None:
            try:
                self.columns[self._current].append(int(attrs["data-task-id"]))
            except (TypeError, ValueError):
                pass


def board_rows(response_or_html, board=None):
    """Разбор доски: `{ключ колонки: [номер задачи, …]}`; `board` — только для проверки вызова."""
    html = getattr(response_or_html, "content", response_or_html)
    if isinstance(html, bytes):
        html = html.decode()
    parser = _BoardParser()
    parser.feed(html)
    return parser.columns


def capture_sql(call):
    """SQL вызова списком (как `support_feed`/`support_messenger`)."""
    with CaptureQueriesContext(connection) as ctx:
        call()
    return [query["sql"] for query in ctx.captured_queries]


def queries_with_params(call):
    """SQL вызова с параметрами: `(sql, params)` — значения фильтров ищутся в `params` (NFR-712)."""
    with CaptureQueriesContext(connection) as ctx:
        call()
    return [(query["sql"], query["params"]) for query in ctx.captured_queries]


# --- синтетические контакты и адреса страниц -----------------------------------------------------

def email_of(user) -> str:
    """Синтетическая почта для проверок вывода (настоящих ПДн нет)."""
    return f"user{user.pk}@example.test"


def phone_of(user) -> str:
    """Синтетический телефон для проверок вывода (настоящих ПДн нет)."""
    return f"+7 900 000-00-{int(user.pk) % 100:02d}"


def tasks_pages() -> tuple[str, ...]:
    """Адреса страниц среза для обходов разметки и проверок статики (CONTRACT-009, 6.3)."""
    return PAGE_PATHS