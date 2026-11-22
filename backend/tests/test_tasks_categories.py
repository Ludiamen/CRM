"""Срез 009 «Задачи»: справочник категорий (T-9111; FR-683).

Справочник ведёт администратор портала под `settings.portal`; удаление категории снимает её у задач, задачи
остаются; новая задача — «Без категории»; перенос по доске подчиняется правам полей (PLAN-009 «Мой план и
категории»; CONTRACT-009, 5.1, 6.2, 7). Код среза импортируется внутри тестов; тексты отказов — литералы 12.1.
"""
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_tasks as tasks

pytestmark = pytest.mark.django_db

TITLE_RANGE = "Название категории — от 1 до 100 знаков"
TITLE_TAKEN = "Категория с таким названием уже есть"
DELETE_CONFIRM = "Удалить категорию? Задачи останутся без категории"
MOVE_FORBIDDEN = "Нет права менять это поле задачи"

CATALOG_URL = "/settings/tasks/categories/"


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
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def _error(response, field, code, text) -> None:
    nodes = q(tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error={field}][data-code={code}] в ответе {response.status_code}"
    assert any(text in node.text() for node in nodes), f"нет текста «{text}» в отказе {code}"


def _fresh(task):
    return support.model("tasks.Task").objects.get(pk=task.pk)


# --- доступ к справочнику ---------------------------------------------------------------------------------------

def test_catalog_requires_portal_permission_for_get_and_writes():
    """FR-683, CONTRACT-009 6.1: справочник под `settings.portal`; сотрудник без права получает 403 на GET и на
    создание, переименование и удаление; администратор портала открывает страницу."""
    staff = tasks.staff_user()
    category = tasks.make_category(title="Работа", position=0)
    client = support.logged_in(staff)

    assert client.get(CATALOG_URL).status_code == 403
    assert client.post(CATALOG_URL, {"title": "Новая"}).status_code == 403
    assert client.post(f"{CATALOG_URL}{category.pk}/", {"title": "Новая", "position": "0"}).status_code == 403
    assert client.post(f"{CATALOG_URL}{category.pk}/delete/", {"confirm": "1"}).status_code == 403
    assert support.model("tasks.TaskCategory").objects.filter(pk=category.pk).exists()

    admin = support.logged_in(support.make_admin())
    assert admin.get(CATALOG_URL).status_code == 200


# --- создание, переименование, порядок --------------------------------------------------------------------------

def test_admin_creates_category_and_page_shows_it():
    """FR-683: администратор создаёт категорию через справочник — 302 на справочник, строка появляется в базе и на
    странице."""
    admin = support.logged_in(support.make_admin())

    response = admin.post(CATALOG_URL, {"title": "Работа"})

    assert response.status_code == 302, response.status_code
    assert response["Location"] == CATALOG_URL
    category = support.model("tasks.TaskCategory").objects.get(title="Работа")
    page = admin.get(CATALOG_URL)
    assert page.status_code == 200
    assert "Работа" in page.content.decode()


def test_admin_renames_category_and_position_changes_page_order():
    """FR-683: переименование и `position` меняют запись; справочник показывает категории по `position`, а не по
    порядку создания."""
    admin = support.logged_in(support.make_admin())
    first = tasks.make_category(title="Категория Альфа", position=0)
    second = tasks.make_category(title="Категория Бета", position=1)

    response = admin.post(f"{CATALOG_URL}{first.pk}/", {"title": "Категория Гамма", "position": "5"})
    assert response.status_code == 302, response.status_code
    first.refresh_from_db()
    assert (first.title, first.position) == ("Категория Гамма", 5)

    page = admin.get(CATALOG_URL).content.decode()
    assert page.index(second.title) < page.index(first.title), "порядок справочника — по position"


# --- удаление ---------------------------------------------------------------------------------------------------

def test_deleting_category_detaches_tasks_and_keeps_them():
    """FR-683, CONTRACT-009 6.2: удаление категории (`confirm=1`) снимает её у задач; задачи остаются без
    категории и не удаляются."""
    admin = support.logged_in(support.make_admin())
    owner = tasks.staff_user()
    category = tasks.make_category(title="Работа", position=0)
    task = tasks.make_task(title="Задача", author=owner, assignee=owner, category=category)

    response = admin.post(f"{CATALOG_URL}{category.pk}/delete/", {"confirm": "1"})

    assert response.status_code == 302, response.status_code
    assert not support.model("tasks.TaskCategory").objects.filter(pk=category.pk).exists()
    assert _fresh(task).category_id is None
    assert support.model("tasks.Task").objects.filter(pk=task.pk).exists()


def test_deleting_category_without_confirm_asks_second_step():
    """FR-683, CONTRACT-009 12.1: без `confirm` — 200, второй шаг `confirm`/`category_delete_confirm` с текстом;
    категория остаётся."""
    admin = support.logged_in(support.make_admin())
    category = tasks.make_category(title="Работа", position=0)

    response = admin.post(f"{CATALOG_URL}{category.pk}/delete/")

    assert response.status_code == 200
    _error(response, "confirm", "category_delete_confirm", DELETE_CONFIRM)
    assert support.model("tasks.TaskCategory").objects.filter(pk=category.pk).exists()


# --- «Без категории» и перенос ----------------------------------------------------------------------------------

def test_new_task_has_no_category_and_board_puts_it_under_none_last():
    """FR-683, K19: задача без категории (умолчание новой) попадает в колонку «Без категории» с ключом `none`,
    и эта колонка последняя."""
    from apps.tasks.services import boards

    owner = tasks.staff_user()
    task = tasks.make_task(title="Новая", author=owner, assignee=owner)

    assert task.category_id is None
    columns = boards.category_columns(owner)
    assert columns[-1]["key"] == "none"
    assert columns[-1]["title"] == "Без категории"
    assert task.pk in {row.pk for row in columns[-1]["tasks"]}


def test_category_move_follows_field_edit_rights_and_none_clears_category():
    """FR-678, FR-683: постановщик переносит задачу в категорию, затем в «Без категории» и категория снимается;
    соисполнитель без прав полей получает `board`/`move_forbidden`, категория не меняется."""
    author = tasks.staff_user()
    coexecutor = tasks.staff_user()
    category = tasks.make_category(title="Работа", position=0)
    task = tasks.make_task(title="Задача", author=author, assignee=author)
    tasks.add_member(task, coexecutor, role="coexecutor")
    author_client = support.logged_in(author)

    response = tasks.move(author_client, task, "category", str(category.pk))
    assert response.status_code == 200
    assert _fresh(task).category_id == category.pk

    denied = tasks.move(support.logged_in(coexecutor), task, "category", "none")
    assert denied.status_code == 200
    _error(denied, "board", "move_forbidden", MOVE_FORBIDDEN)
    assert _fresh(task).category_id == category.pk

    response = tasks.move(author_client, task, "category", "none")
    assert response.status_code == 200
    assert _fresh(task).category_id is None


# --- названия категорий -----------------------------------------------------------------------------------------

def test_category_title_limits_and_uniqueness():
    """FR-683: название категории — от 1 до 100 знаков и уникально: пустое и 101 знак —
    `title`/`category_title_range`, повтор — `title`/`category_title_taken`; 100 знаков принимается."""
    admin = support.logged_in(support.make_admin())
    Category = support.model("tasks.TaskCategory")

    empty = admin.post(CATALOG_URL, {"title": ""})
    assert empty.status_code == 200
    _error(empty, "title", "category_title_range", TITLE_RANGE)

    too_long = admin.post(CATALOG_URL, {"title": "к" * 101})
    assert too_long.status_code == 200
    _error(too_long, "title", "category_title_range", TITLE_RANGE)

    longest = "к" * 100
    assert admin.post(CATALOG_URL, {"title": longest}).status_code == 302
    assert Category.objects.filter(title=longest).exists()

    duplicate = admin.post(CATALOG_URL, {"title": longest})
    assert duplicate.status_code == 200
    _error(duplicate, "title", "category_title_taken", TITLE_TAKEN)