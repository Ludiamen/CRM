"""T-9115: комментарии задачи — права, правка и мягкое удаление своего, серая запись, журнал без текста, лента
(FR-693, FR-694).

Источники: PLAN-009 «Комментарии, файлы и лента» (`services.comments`: добавить — все, кто видит задачу; править и
удалить свой; мягко, `deleted_at` — серая запись; события в ленте, записи журнала без текста; своя `TaskComment`);
CONTRACT-009: 2.1 (`TaskComment.text` 1–10 000, `edited_at`, `deleted_at`), 4 (`can_comment`, `can_edit_comment`),
5.1 (`comments.add/edit/remove`), 6.2 (`POST /tasks/<id>/comments/`, `POST /tasks/comments/<id>/edit|delete/`),
6.3 (`[data-comment-id]`, `[data-comment-edited]`), 10.1 (`tasks.comment_changed` без текста), 12.1
(`comment_empty`, `comment_too_long`, `comment_forbidden`), 12.2 («Комментарий удалён», «изменено»).

Код среза импортируется внутри тестов, модели — через `support.model`; сбор проходит до появления кода. Адреса и
тексты — литералы контракта; ПДн нет.
"""
import importlib
import json
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_org
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

EMPTY_TEXT = "Напишите комментарий"
LONG_TEXT = "Предел: 10 000 знаков"
FORBIDDEN_TEXT = "Комментировать может только тот, кто видит задачу"
DELETED_TEXT = "Комментарий удалён"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки ---------------------------------------------------------------------------------------------

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
        parts = []
        for child in self.children:
            parts.append(child.text() if isinstance(child, _Node) else child)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(response.content.decode("utf-8", "replace"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


def _refusals(response) -> list[tuple[str, str, str]]:
    return [(node.attrs["data-error"], node.attrs.get("data-code", ""), node.text())
            for node in _tree(response).walk() if "data-error" in node.attrs]


def _refused(response, field: str, code: str, text: str) -> None:
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    found = _refusals(response)
    assert (field, code, text) in found, f"нет отказа {field}/{code}/{text!r}: {found}"


# --- помощники файла ---------------------------------------------------------------------------------------------

def _comments():
    return importlib.import_module("apps.tasks.services.comments")


def _tasks():
    return importlib.import_module("apps.tasks.services.tasks")


def _errors():
    return importlib.import_module("apps.tasks.services.errors")


def _fresh(comment):
    return support.model("tasks.TaskComment").objects.get(pk=comment.pk)


def _comment_of(task, author):
    return support.model("tasks.TaskComment").objects.get(task=task, author=author)


def _audit(action: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _dump(events) -> str:
    return json.dumps([[event.action, event.object_type, event.object_id, event.before, event.after]
                       for event in events], ensure_ascii=False)


def _world():
    """Автор, исполнитель, соисполнитель, наблюдатель и руководитель узла исполнителя — все видят задачу."""
    unit = support_org.make_tree({"Узел комментариев": {}})["Узел комментариев"]
    author = tasks_helpers.staff_user(full_name="Автор Комментариев")
    assignee = tasks_helpers.staff_user(full_name="Исполнитель Комментариев")
    coexecutor = tasks_helpers.staff_user(full_name="Соисполнитель Комментариев")
    observer = tasks_helpers.staff_user(full_name="Наблюдатель Комментариев")
    manager = tasks_helpers.head_of(unit, full_name="Руководитель Комментариев")
    support_org.make_member(assignee, unit)
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None, title="Задача комментариев")
    tasks_helpers.add_member(task, coexecutor)
    tasks_helpers.add_member(task, observer, role="observer")
    return {"task": task, "author": author, "assignee": assignee, "coexecutor": coexecutor,
            "observer": observer, "manager": manager}


# --- FR-693: пишут все видящие ----------------------------------------------------------------------------------

def test_every_participant_and_manager_can_comment():
    """FR-693 (CONTRACT-009, 4): комментарий пишут все, кто видит задачу, — постановщик, исполнитель,
    соисполнитель, наблюдатель и руководитель узла исполнителя; каждая запись — своя `TaskComment`."""
    world = _world()
    for key in ("author", "assignee", "coexecutor", "observer", "manager"):
        comment = _comments().add(world[key], world["task"], f"Пишет {key}")
        assert comment.author_id == world[key].pk
        assert comment.task_id == world["task"].pk
        assert comment.deleted_at is None and comment.edited_at is None

    assert support.model("tasks.TaskComment").objects.filter(task=world["task"]).count() == 5


def test_outsider_comment_on_invisible_task_is_404_like_missing():
    """FR-693, CONTRACT-009 6.1: постороннему чужая задача не видна — `POST /tasks/<id>/comments/` отвечает 404
    «Не найдено», неотличимо от несуществующей задачи; служба поднимает `TasksError` `comment_forbidden`."""
    world = _world()
    outsider = tasks_helpers.staff_user(full_name="Посторонний Комментариев")
    client = support.logged_in(outsider)
    missing = client.post("/tasks/999999/comments/", {"text": "Текст"}, **support.HX)
    hidden = tasks_helpers.post_comment(client, world["task"], "Текст", **support.HX)
    assert hidden.status_code == 404 and missing.status_code == 404
    assert support.same_failure(hidden, missing)

    with pytest.raises(_errors().TasksError) as caught:
        _comments().add(outsider, world["task"], "Текст")
    assert caught.value.code == "comment_forbidden"
    assert caught.value.field == "text"


# --- FR-693: правка и мягкое удаление своего -------------------------------------------------------------------

def test_author_edits_own_comment_marks_edited_and_returns_comment_fragment():
    """FR-693 (CONTRACT-009, 6.2, 6.3): автор правит свой комментарий — `edited_at` заполняется, текст меняется,
    HTMX-ответ 200 отдаёт комментарий с `[data-comment-id]` и пометкой `[data-comment-edited]` («изменено»)."""
    world = _world()
    comment = _comments().add(world["author"], world["task"], "Черновик")
    client = support.logged_in(world["author"])

    response = client.post(f"/tasks/comments/{comment.pk}/edit/", {"text": "Исправленный текст"}, **support.HX)

    assert response.status_code == 200
    fresh = _fresh(comment)
    assert fresh.text == "Исправленный текст"
    assert fresh.edited_at is not None
    nodes = _find(_tree(response), data_comment_id=str(comment.pk))
    assert nodes, "в ответе нет комментария с data-comment-id"
    assert _find(nodes[0], data_comment_edited=True), "нет пометки [data-comment-edited]"
    assert "изменено" in response.content.decode("utf-8").lower()


def test_foreign_comment_edit_and_delete_403_and_deleted_404():
    """FR-693 (CONTRACT-009, 4, 6.1): чужой комментарий править и удалять нельзя — 403 (задача видна); удалённый
    комментарий — 404, неотличимый от несуществующего."""
    world = _world()
    comment = _comments().add(world["author"], world["task"], "Чужой для соисполнителя")
    other = support.logged_in(world["coexecutor"])
    assert other.post(f"/tasks/comments/{comment.pk}/edit/", {"text": "Подмена"}, **support.HX).status_code == 403
    assert other.post(f"/tasks/comments/{comment.pk}/delete/", {}, **support.HX).status_code == 403
    assert _fresh(comment).text == "Чужой для соисполнителя" and _fresh(comment).deleted_at is None

    _comments().remove(world["author"], comment)
    author_client = support.logged_in(world["author"])
    edited = author_client.post(f"/tasks/comments/{comment.pk}/edit/", {"text": "После удаления"}, **support.HX)
    deleted = author_client.post(f"/tasks/comments/{comment.pk}/delete/", {}, **support.HX)
    missing = author_client.post("/tasks/comments/999999/delete/", {}, **support.HX)
    assert (edited.status_code, deleted.status_code, missing.status_code) == (404, 404, 404)
    assert support.same_failure(deleted, missing)


def test_soft_deleted_comment_is_grey_record_without_text():
    """FR-693 (CONTRACT-009, 12.2): мягко удалённый комментарий остаётся серой записью «Комментарий удалён» с
    `[data-comment-id]`, текст в разметке не показывается; в карточке он тоже серый."""
    marker = "Текст, который не должен показываться"
    world = _world()
    comment = _comments().add(world["author"], world["task"], marker)
    client = support.logged_in(world["author"])

    response = client.post(f"/tasks/comments/{comment.pk}/delete/", {}, **support.HX)

    assert response.status_code == 200
    assert _fresh(comment).deleted_at is not None
    body = response.content.decode("utf-8")
    assert DELETED_TEXT in body and marker not in body
    assert _find(_tree(response), data_comment_id=str(comment.pk)), "серая запись без data-comment-id"

    card = client.get(f"/tasks/{world['task'].pk}/")
    assert card.status_code == 200
    card_body = card.content.decode("utf-8")
    assert DELETED_TEXT in card_body and marker not in card_body


# --- FR-693: отказы ----------------------------------------------------------------------------------------------

def test_empty_and_too_long_comment_refused_with_texts():
    """FR-693 (CONTRACT-009, 12.1): пустой комментарий — «Напишите комментарий» (`comment_empty`) у поля `text`,
    10 001 знак — «Предел: 10 000 знаков» (`comment_too_long`); ответ 200, комментарий не создан."""
    world = _world()
    client = support.logged_in(world["author"])
    before = support.model("tasks.TaskComment").objects.filter(task=world["task"]).count()

    empty = tasks_helpers.post_comment(client, world["task"], "", **support.HX)
    _refused(empty, "text", "comment_empty", EMPTY_TEXT)
    long = tasks_helpers.post_comment(client, world["task"], "я" * 10_001, **support.HX)
    _refused(long, "text", "comment_too_long", LONG_TEXT)
    assert support.model("tasks.TaskComment").objects.filter(task=world["task"]).count() == before


# --- FR-694: журнал без текста и лента карточки -----------------------------------------------------------------

def test_comment_edit_and_delete_write_journal_without_text():
    """FR-694 (CONTRACT-009, 10.1, NFR-718): правка и удаление комментария пишут `tasks.comment_changed` на объект
    `tasks.comment` с номером задачи и комментария — без текста комментария ни до, ни после правки."""
    marker_before, marker_after = "Секретный старый текст", "Секретный новый текст"
    world = _world()
    edited = _comments().add(world["author"], world["task"], marker_before)
    removed = _comments().add(world["author"], world["task"], marker_before)
    _comments().edit(world["author"], edited, marker_after)
    _comments().remove(world["author"], removed)

    events = _audit("tasks.comment_changed")
    assert len(events) == 2, f"записей tasks.comment_changed: {len(events)}"
    assert {event.object_type for event in events} == {"tasks.comment"}
    assert {event.object_id for event in events} == {str(edited.pk), str(removed.pk)}
    dump = _dump(events)
    assert marker_before not in dump and marker_after not in dump, "текст комментария попал в журнал"
    assert str(world["task"].pk) in dump, "в журнале нет номера задачи"


def test_card_feed_starts_with_task_created_and_lists_comments_in_order():
    """FR-693, FR-694 (CONTRACT-009, 10.1): лента карточки — записи журнала по объекту задачи плюс комментарии;
    первая строка — «Создал задачу», затем комментарии в порядке создания."""
    world = _world()
    task = _tasks().create(world["author"], title="Задача ленты", assignee=world["author"])
    tasks_helpers.add_member(task, world["assignee"])
    _comments().add(world["author"], task, "Первый комментарий ленты")
    _comments().add(world["assignee"], task, "Второй комментарий ленты")
    client = support.logged_in(world["author"])

    response = client.get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "Создал задачу" in body, "первая строка ленты — не «Создал задачу»"
    first = body.index("Создал задачу")
    one = body.index("Первый комментарий ленты")
    two = body.index("Второй комментарий ленты")
    assert first < one < two, "порядок ленты карточки нарушен"