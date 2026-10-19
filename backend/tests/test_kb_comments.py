"""T-5116: комментарии (FR-425, FR-426, FR-438, NFR-405). Сценарии «Комментарии под статьёй» и связанные спеки.

Служба ядра `core.comments` (добавление, список, удаление, привязка по `object_ref`), блок под опубликованной статьёй,
форма и ответ HTMX, права на «Удалить», журнал удаления чужого комментария, черновик и корзина, уволенный автор,
событие `knowledge.comment_added`, внутренние комментарии заявок остаются записями ленты (CONTRACT-005, 3.4, 5.2, 7.1,
10.5, 10.7, 11.5, 12). Код среза на уровне модуля не импортируется: имена берутся внутри тестов (шапка контракта).
"""
import importlib
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import support
from tests import support_kb as kb
from tests import support_servicedesk as sd
from tests.support import HX

pytestmark = pytest.mark.django_db

GONE = "Статья удалена"
TOO_LONG = "Комментарий не длиннее 4000 знаков"
EMPTY = "Введите текст комментария"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

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

    def raw_text(self) -> str:
        """Текст узла без схлопывания пробелов и переводов строк."""
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return "".join(parts)


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


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста ---------------------------------------------------------------------------------------

def _comments():
    return importlib.import_module("apps.core.services.comments")


def _articles():
    return importlib.import_module("apps.knowledge.services.articles")


def _Comment():
    return support.model("core.Comment")


def _ref(article) -> str:
    return f"knowledge.article:{article.pk}"


def _photo(user):
    """Чистое фото сотрудника (строка `StoredFile` с назначением `photo`); возвращает её."""
    stored = support.model("core.StoredFile").objects.create(
        purpose="photo", owner=user, size=10, sha256="0" * 64, content_type="image/jpeg", status="clean")
    user.photo = stored
    user.save()
    return stored


def _author(name: str = "Автор Комментов", *, photo: bool = True):
    user = support.make_employee(full_name=name)
    if photo:
        _photo(user)
    return user


def _page(session, path):
    response = session.client.get(path)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    return tree(response)


def _block(page):
    return q1(page, "section", id="comments", data_kb_comments=True)


def _rows(page) -> dict:
    """Строки комментариев блока: номер комментария → `li`, в порядке разметки."""
    found = {}
    for li in q(_block(page), "li", data_comment_id=True):
        found[int(li.attrs["data-comment-id"])] = li
    return found


def _audit(action: str, article):
    return list(support.model("core.AuditEvent").objects.filter(action=action, object_id=str(article.pk)))


def _post_comment(session, article, text, *, nh: bool = True):
    extra = HX if nh else {}
    return session.client.post(f"/kb/{article.pk}/comments/", {"text": text}, **extra)


# --- служба ядра core.comments (FR-425, FR-426) ---------------------------------------------------------

def test_core_comment_add_trims_edges_and_keeps_inner_text():
    """FR-425, FR-426: `add` убирает пробелы и переводы строк по краям, внутренний текст не меняется; строка в базе."""
    comments = _comments()
    author = support.make_employee()
    raw = "  \n\t Первая строка,\n\n   вторая  с двойным пробелом \n  "
    created = comments.add(author, "knowledge.article:7", raw)
    assert created.text == "Первая строка,\n\n   вторая  с двойным пробелом"
    saved = _Comment().objects.get(pk=created.pk)
    assert saved.text == created.text
    assert saved.object_ref == "knowledge.article:7" and saved.author == author
    assert saved.created_at is not None
    assert _Comment().objects.count() == 1


def test_core_comment_add_4000_accepted_and_4001_refused():
    """FR-425: 4000 знаков принимается (длина — после обрезки краёв), 4001 — `CommentError("too_long")`, ничего не пишется."""
    comments = _comments()
    author = support.make_employee()
    ref = "knowledge.article:7"
    assert len(comments.add(author, ref, "я" * 4000).text) == 4000
    padded = comments.add(author, ref, "   \n" + "я" * 4000 + "\n  ")
    assert len(padded.text) == 4000, "пробелы по краям в длину не входят"
    assert _Comment().objects.count() == 2
    for raw in ("я" * 4001, "  " + "я" * 4001 + "\n"):
        with pytest.raises(comments.CommentError) as raised:
            comments.add(author, ref, raw)
        assert raised.value.code == "too_long"
        assert TOO_LONG in raised.value.message
    assert _Comment().objects.count() == 2, "при отказе ничего не записано"


def test_core_comment_add_empty_or_blank_refused():
    """FR-425: пустая строка и строка из одних пробелов и переводов строк — `CommentError("empty")`, ничего не пишется."""
    comments = _comments()
    author = support.make_employee()
    for raw in ("", " ", "\n\t  \r\n"):
        with pytest.raises(comments.CommentError) as raised:
            comments.add(author, "knowledge.article:7", raw)
        assert raised.value.code == "empty"
        assert EMPTY in raised.value.message
    assert _Comment().objects.count() == 0


def test_core_comment_list_for_oldest_first_newest_last_with_author(clock):
    """FR-425, FR-426: `list_for` — по `created_at`, затем по `id`; старые первыми, новый внизу; автор приложен; чужой `object_ref` не входит."""
    comments = _comments()
    first_author, second_author = _author("Первый Автор"), _author("Второй Автор", photo=False)
    ref = "knowledge.article:7"
    clock.set(kb.moscow(2026, 3, 10, 9, 0))
    oldest = comments.add(first_author, ref, "самый старый")
    same_moment_a = comments.add(second_author, ref, "в ту же минуту, первый")
    same_moment_b = comments.add(first_author, ref, "в ту же минуту, второй")
    clock.advance(minutes=30)
    newest = comments.add(second_author, ref, "самый новый")
    comments.add(first_author, "knowledge.article:8", "чужая статья")
    shown = comments.list_for(ref)
    assert [c.pk for c in shown] == [oldest.pk, same_moment_a.pk, same_moment_b.pk, newest.pk]
    assert [c.author.full_name for c in shown] == ["Первый Автор", "Второй Автор", "Первый Автор", "Второй Автор"]
    assert comments.list_for("knowledge.article:99") == []


def test_core_comment_list_for_loads_author_and_photo_in_one_query():
    """FR-425: число запросов `list_for` вместе с чтением автора и фото не зависит от числа комментариев (1 и 10 совпадают)."""
    comments = _comments()
    from apps.core.services import files

    def spent(ref: str, count: int) -> int:
        for number in range(count):
            comments.add(_author(f"Автор {ref} {number}"), ref, f"текст {number}")
        with CaptureQueriesContext(connection) as ctx:
            rows = comments.list_for(ref)
            for row in rows:
                assert row.author.full_name
                assert files.photo_url(row.author, 96)
        assert len(rows) == count
        return len(ctx)

    one, ten = spent("knowledge.article:1", 1), spent("knowledge.article:2", 10)
    assert one >= 1
    assert one == ten, f"запросов на 1 комментарий {one}, на 10 — {ten}: автор или фото читаются по запросу на строку"


def test_core_comment_delete_removes_one():
    """FR-426: `delete(comment)` удаляет одну строку физически, возвращает `None`, журнал сам не пишет."""
    comments = _comments()
    author = support.make_employee()
    ref = "knowledge.article:7"
    first, second = comments.add(author, ref, "один"), comments.add(author, ref, "два")
    audit_before = support.model("core.AuditEvent").objects.count()
    assert comments.delete(first) is None
    assert not _Comment().objects.filter(pk=first.pk).exists()
    assert [c.pk for c in comments.list_for(ref)] == [second.pk]
    assert support.model("core.AuditEvent").objects.count() == audit_before, "журнал пишет модуль, не ядро"


def test_core_comment_delete_for_removes_only_that_objects_comments():
    """FR-426: `delete_for` удаляет комментарии только этого `object_ref` (`:1` не задевает `:10`) и возвращает их число."""
    comments = _comments()
    author = support.make_employee()
    for ref in ("knowledge.article:1", "knowledge.article:1", "knowledge.article:10", "other.thing:1"):
        comments.add(author, ref, "текст " + ref)
    assert comments.delete_for("knowledge.article:1") == 2
    assert list(_Comment().objects.order_by("id").values_list("object_ref", flat=True)) == [
        "knowledge.article:10", "other.thing:1"]
    assert comments.delete_for("knowledge.article:1") == 0


def test_core_comments_attach_to_object_of_another_module():
    """FR-426: комментарий привязывается по строке `object_ref` к объекту любого модуля; служба ссылку не разбирает."""
    comments = _comments()
    author = support.make_employee()
    for ref in ("tickets.ticket:5", "org.unit:12", "anything.at-all:x" * 3 + "ab"):
        assert len(ref) <= 64
        created = comments.add(author, ref, "комментарий к " + ref)
        assert created.object_ref == ref
        assert [c.pk for c in comments.list_for(ref)] == [created.pk]
    assert _Comment().objects.count() == 3


def test_core_comments_service_knows_nothing_about_articles():
    """FR-426: в файле службы ядра нет слов `knowledge`, `Article`, `article` (ядро не знает, что такое статья)."""
    import apps.core.services as services

    path = Path(services.__path__[0]) / "comments.py"
    assert path.exists(), f"нет файла службы комментариев ядра: {path}"
    body = path.read_text(encoding="utf-8").lower()
    for word in ("knowledge", "article"):
        assert word not in body, f"в core/services/comments.py есть слово {word!r}"


# --- блок под статьёй: показ, форма, ответ HTMX (FR-425, NFR-405) -----------------------------------------

def test_published_article_shows_block_and_any_employee_posts_with_name_photo_time(clock):
    """FR-425: под опубликованной статьёй блок; любой сотрудник без прав базы знаний пишет, и строка с ФИО, фото и временем."""
    clock.set(kb.moscow(2026, 3, 10, 14, 5))
    article = kb.make_published(title="Как настроить VPN")
    reader = kb.as_reader(full_name="Читатель Читателев")
    stored = _photo(reader.user)
    empty_page = _page(reader, f"/kb/{article.pk}/")
    block = _block(empty_page)
    assert q1(block, "ul", data_kb_comment_list=True) is not None
    assert _rows(empty_page) == {}
    response = _post_comment(reader, article, "не сработало на Windows 11")
    assert response.status_code == 200
    created = _Comment().objects.get(object_ref=_ref(article))
    assert created.author == reader.user and created.text == "не сработало на Windows 11"
    other = kb.as_reader()
    page = _page(other, f"/kb/{article.pk}/")
    (row,) = _rows(page).values()
    assert row.attrs["data-comment-id"] == str(created.pk)
    assert "Читатель Читателев" in q1(row, data_field="author").text()
    assert q1(row, "img", data_field="photo").attrs["src"].startswith(f"/staff/{reader.user.pk}/photo/{stored.pk}/")
    assert q1(row, "time", data_at=True).text() == kb.moscow_text(kb.moscow(2026, 3, 10, 14, 5))
    assert q1(row, data_field="text").text() == "не сработало на Windows 11"


def test_comment_over_4000_not_saved_limit_shown():
    """FR-425: 4001 знак — комментарий не сохранён, ответ 200 с формой, введённым текстом и пределом 4000 у поля."""
    article = kb.make_published()
    session = kb.as_reader()
    long_text = "ж" * 4001
    response = _post_comment(session, article, long_text)
    assert response.status_code == 200
    page = tree(response)
    error = q1(page, data_error="text", data_code="too_long")
    assert TOO_LONG in error.text() and "4000" in error.text()
    form = q1(page, "form", data_form="kb-comment")
    assert q1(form, "textarea", name="text").raw_text().strip() == long_text, "введённое остаётся в форме"
    assert q(page, "li", data_comment_id=True) == []
    assert _Comment().objects.count() == 0
    blank = _post_comment(session, article, " \n ")
    assert blank.status_code == 200 and q1(tree(blank), data_error="text", data_code="empty")
    assert _Comment().objects.count() == 0


def test_comment_markup_and_links_shown_as_text_newlines_kept():
    """FR-425, NFR-405: `<b>`, `<script>` и ссылка показаны текстом, переводы строк — `<br>`; разметка не создаётся."""
    article = kb.make_published()
    session = kb.as_reader()
    link = "http" + "://example.test/path?a=1&b=2"
    text = f"<b>важно</b> и <script>alert(1)</script>\nвторая строка {link}\n\nчетвёртая"
    assert _post_comment(session, article, text).status_code == 200
    body = session.client.get(f"/kb/{article.pk}/").content.decode("utf-8")
    page = tree(body)
    (row,) = _rows(page).values()
    field = q1(row, data_field="text")
    assert q(field, "b") == [] and q(field, "script") == [] and q(field, "a") == [], "разметки в тексте комментария нет"
    shown = field.raw_text()
    assert "<b>важно</b>" in shown and "<script>alert(1)</script>" in shown and link in shown
    assert len(q(field, "br")) == 3, "три перевода строки сохранены"
    assert "&lt;b&gt;важно&lt;/b&gt;" in body and "<script>alert(1)" not in body


def test_comment_form_has_no_attachments_or_mentions():
    """FR-425: форма комментария — `textarea[name=text]` и кнопка «Отправить»; вложений и упоминаний нет; зацепки HTMX по 11.5."""
    article = kb.make_published()
    page = _page(kb.as_reader(), f"/kb/{article.pk}/")
    form = q1(_block(page), "form", data_form="kb-comment")
    assert form.attrs["hx-post"] == f"/kb/{article.pk}/comments/"
    assert form.attrs["hx-target"] == "[data-kb-comment-list]" and form.attrs["hx-swap"] == "beforeend"
    assert q1(form, "textarea", name="text") is not None
    assert q1(form, "button", data_action="kb-comment-add").text() == "Отправить"
    assert q(form, "input", type="file") == [] and "multipart" not in form.attrs.get("enctype", "")
    names = {node.attrs.get("name") for node in q(form, "input") + q(form, "textarea", name=True)}
    assert names - {None, "csrfmiddlewaretoken", "text"} == set(), f"лишние поля формы: {names}"
    assert "@" not in form.attrs.get("hx-post", "") and not any(
        "mention" in attr.lower() for node in form.walk() for attr in node.attrs)


# --- удаление: автор, не управляющий, управляющий (FR-425, FR-438) ---------------------------------------

def test_author_deletes_own_comment_hidden_for_all_no_journal():
    """FR-425, FR-438: автор удаляет свой комментарий: HTMX — 200 с пустым телом; исчез для всех; журнала нет."""
    article = kb.make_published()
    author = kb.as_reader()
    mine = kb.make_comment(article, author.user, "мой комментарий")
    kept = kb.make_comment(article, kb.as_reader().user, "чужой остаётся")
    page = _page(author, f"/kb/{article.pk}/")
    assert q1(_rows(page)[mine.pk], "button", data_action="kb-comment-delete").text() == "Удалить"
    response = author.client.post(f"/kb/comments/{mine.pk}/delete/", {}, **HX)
    assert response.status_code == 200 and response.content.strip() == b""
    assert not _Comment().objects.filter(pk=mine.pk).exists() and _Comment().objects.filter(pk=kept.pk).exists()
    for viewer in (author, kb.as_reader(), kb.as_manager()):
        assert list(_rows(_page(viewer, f"/kb/{article.pk}/"))) == [kept.pk]
    assert _audit("knowledge.comment_deleted", article) == [], "свой комментарий журнала не пишет"
    again = author.client.post(f"/kb/comments/{mine.pk}/delete/", {}, **HX)
    assert again.status_code == 404


def test_non_manager_has_no_delete_button_on_foreign_comment_direct_post_403():
    """FR-425: у не-управляющего (читателя и редактора) на чужом комментарии кнопки «Удалить» нет, прямой POST — 403, комментарий цел."""
    article = kb.make_published()
    writer = kb.as_reader()
    foreign = kb.make_comment(article, writer.user, "чужой комментарий")
    for viewer in (kb.as_reader(), kb.as_editor()):
        own = kb.make_comment(article, viewer.user, "свой комментарий")
        rows = _rows(_page(viewer, f"/kb/{article.pk}/"))
        assert q(rows[foreign.pk], "button", data_action="kb-comment-delete") == [], "на чужом комментарии кнопки нет"
        assert len(q(rows[own.pk], "button", data_action="kb-comment-delete")) == 1, "на своём — есть"
        for extra in (HX, {}):
            response = viewer.client.post(f"/kb/comments/{foreign.pk}/delete/", {}, **extra)
            assert response.status_code == 403
        assert _Comment().objects.filter(pk=foreign.pk).exists()
    missing = kb.as_manager().client.post("/kb/comments/999999999/delete/", {}, **HX)
    assert missing.status_code == 404
    assert _audit("knowledge.comment_deleted", article) == []


def test_manager_deletes_foreign_comment_journal_without_text():
    """FR-425, FR-438: управляющий видит «Удалить» на любом комментарии и удаляет чужой; в журнале запись без текста комментария."""
    article = kb.make_published(title="Статья про принтеры")
    manager = kb.as_manager()
    marker = "уникальная фраза чужого комментария"
    foreign = kb.make_comment(article, kb.as_reader().user, marker)
    own = kb.make_comment(article, manager.user, "комментарий самого управляющего")
    rows = _rows(_page(manager, f"/kb/{article.pk}/"))
    assert all(len(q(row, "button", data_action="kb-comment-delete")) == 1 for row in rows.values())
    response = manager.client.post(f"/kb/comments/{foreign.pk}/delete/", {})
    assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/#comments"
    assert not _Comment().objects.filter(pk=foreign.pk).exists()
    (event,) = _audit("knowledge.comment_deleted", article)
    assert event.actor == manager.user and event.object_type == "knowledge.article"
    assert int(event.before["number"]) == article.pk and event.before["title"] == "Статья про принтеры"
    assert set(event.before) == {"number", "title"} and event.after == {}
    assert marker not in json.dumps([event.before, event.after], ensure_ascii=False)
    response = manager.client.post(f"/kb/comments/{own.pk}/delete/", {}, **HX)
    assert response.status_code == 200
    assert len(_audit("knowledge.comment_deleted", article)) == 1, "удаление своего журнала не пишет"


# --- черновик, корзина, удаление навсегда (FR-425, FR-426) ------------------------------------------------

def test_draft_has_no_comment_block_and_post_answers_as_missing():
    """FR-425: под черновиком блока нет; POST комментария к черновику — 404 даже управляющему; ничего не сохраняется."""
    manager = kb.as_manager()
    draft = kb.make_draft(author=manager.user)
    page = _page(manager, f"/kb/{draft.pk}/")
    assert q(page, "section", id="comments") == [] and q(page, data_kb_comments=True) == []
    assert q(page, "form", data_form="kb-comment") == []
    assert kb.as_reader().client.get(f"/kb/{draft.pk}/").status_code == 404
    for session in (manager, kb.as_editor(), kb.as_reader()):
        for extra in (HX, {}):
            response = session.client.post(f"/kb/{draft.pk}/comments/", {"text": "можно?"}, **extra)
            assert response.status_code == 404
    assert _Comment().objects.count() == 0
    assert kb.as_manager().client.post("/kb/999999999/comments/", {"text": "x"}, **HX).status_code == 404


def test_trashed_article_has_no_block_and_post_answers_200_article_deleted():
    """FR-425: у статьи в корзине блока нет; POST комментария — 200 «Статья удалена» от любого сотрудника; комментарий не создан."""
    article = kb.make_trashed()
    manager = kb.as_manager()
    page = _page(manager, f"/kb/{article.pk}/")
    assert q(page, "section", id="comments") == [] and q(page, "form", data_form="kb-comment") == []
    assert kb.as_reader().client.get(f"/kb/{article.pk}/").status_code == 410
    for session in (kb.as_reader(), kb.as_editor(), manager):
        for extra in (HX, {}):
            response = session.client.post(f"/kb/{article.pk}/comments/", {"text": "можно?"}, **extra)
            assert response.status_code == 200
            assert GONE in response.content.decode("utf-8")
            assert q1(tree(response), role="alert", data_code="article_gone") is not None
    assert _Comment().objects.count() == 0


def test_comments_hidden_in_trash_and_back_with_restored_article():
    """FR-425, FR-426: в корзине комментарии скрыты, но не удалены; после «Вернуть» блок и комментарии на месте, в прежнем порядке."""
    article = kb.make_published()
    manager = kb.as_manager()
    first = kb.make_comment(article, kb.as_reader().user, "первый")
    second = kb.make_comment(article, kb.as_reader().user, "второй")
    assert list(_rows(_page(manager, f"/kb/{article.pk}/"))) == [first.pk, second.pk]
    assert manager.client.post(f"/kb/{article.pk}/trash/", {}).status_code == 302
    article.refresh_from_db()
    assert article.state == "trash"
    assert q(_page(manager, f"/kb/{article.pk}/"), "section", id="comments") == []
    assert _Comment().objects.filter(object_ref=_ref(article)).count() == 2, "комментарии в корзине не стёрты"
    assert manager.client.post(f"/kb/{article.pk}/restore/", {}).status_code == 302
    article.refresh_from_db()
    assert article.state == "published"
    for viewer in (manager, kb.as_reader()):
        assert list(_rows(_page(viewer, f"/kb/{article.pk}/"))) == [first.pk, second.pk]


def test_comments_deleted_with_article_on_permanent_delete(django_capture_on_commit_callbacks):
    """FR-426: удаление навсегда стирает комментарии этой статьи и только их (комментарий соседней статьи и объект другого модуля целы)."""
    articles = _articles()
    manager = kb.as_manager()
    doomed = kb.make_trashed()
    neighbour = kb.make_published()
    for number in range(3):
        kb.make_comment(doomed, kb.as_reader().user, f"к удалённой {number}")
    kept = kb.make_comment(neighbour, kb.as_reader().user, "к соседней")
    foreign = support.model("core.Comment").objects.create(
        object_ref="other.thing:%d" % doomed.pk, author=manager.user, text="чужой объект")
    with django_capture_on_commit_callbacks(execute=True):
        articles.purge(doomed, manager.user)
    assert not _Comment().objects.filter(object_ref=_ref(doomed)).exists()
    assert {c.pk for c in _Comment().objects.all()} == {kept.pk, foreign.pk}
    assert not support.model("knowledge.Article").objects.filter(pk=doomed.pk).exists()


# --- автор, добавление в конец, событие (FR-425) --------------------------------------------------------

def test_fired_author_comment_signed_with_name_and_fired_mark():
    """FR-425: комментарий уволенного подписан ФИО с пометкой «(уволен)» (`span[data-dismissed=true]`); у действующего пометки нет."""
    article = kb.make_published()
    fired = support.make_employee(full_name="Уволенный Иван", state="dismissed")
    active = _author("Действующая Анна")
    gone_row = kb.make_comment(article, fired, "написал до увольнения")
    live_row = kb.make_comment(article, active, "пишу сейчас")
    rows = _rows(_page(kb.as_reader(), f"/kb/{article.pk}/"))
    author = q1(rows[gone_row.pk], data_field="author")
    mark = q1(author, "span", data_dismissed="true")
    assert "Уволенный Иван" in author.text() and "(уволен)" in author.text() and "(уволен)" in mark.text()
    live = q1(rows[live_row.pk], data_field="author")
    assert "Действующая Анна" in live.text() and "(уволен)" not in live.text()
    assert q(live, "span", data_dismissed="true") == []


def test_added_comment_appended_to_end_of_list_by_htmx_fragment():
    """FR-425: ответ HTMX — фрагмент без `<html>` с одним `li` нового комментария и формой с `hx-swap-oob` и пустым полем."""
    article = kb.make_published()
    older = kb.make_comment(article, kb.as_reader().user, "уже был")
    writer = kb.as_reader(full_name="Новый Автор")
    response = _post_comment(writer, article, "добавлен без перезагрузки")
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert "<html" not in html.lower()
    fragment = tree(response)
    (row,) = q(fragment, "li", data_comment_id=True)
    created = _Comment().objects.exclude(pk=older.pk).get()
    assert row.attrs["data-comment-id"] == str(created.pk)
    assert q1(row, data_field="text").text() == "добавлен без перезагрузки"
    assert "Новый Автор" in q1(row, data_field="author").text()
    form = q1(fragment, "form", data_form="kb-comment")
    assert form.attrs["id"] == "kb-comment-form" and form.attrs.get("hx-swap-oob") == "true"
    assert q1(form, "textarea", name="text").raw_text().strip() == "", "поле очищено"
    assert q(fragment, data_error=True) == []
    page = _page(writer, f"/kb/{article.pk}/")
    assert list(_rows(page)) == [older.pk, created.pk], "новый — внизу"
    ordinary = _post_comment(writer, article, "второй, без HTMX", nh=False)
    assert ordinary.status_code == 302 and ordinary["Location"] == f"/kb/{article.pk}/#comments"


def test_comment_added_event_published_after_commit_with_article_and_comment(
        bus, django_capture_on_commit_callbacks, caplog):
    """FR-425: `knowledge.comment_added` — после фиксации, ключи ровно `article_id`, `comment_id`, `actor_id`; без текста; при отказе не публикуется."""
    articles = _articles()
    comments = _comments()
    bus.listen("knowledge.comment_added")
    article = kb.make_published()
    writer = support.make_employee()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        created = articles.add_comment(writer, article.pk, "комментарий для события")
        assert _Comment().objects.filter(pk=created.pk).exists()
        assert bus.calls("knowledge.comment_added") == [], "до фиксации события нет"
    for callback in callbacks:
        callback()
    assert bus.calls("knowledge.comment_added") == [
        {"article_id": article.pk, "comment_id": created.pk, "actor_id": writer.pk}]
    assert _audit("knowledge.comment_deleted", article) == []
    assert not [r for r in caplog.records if r.name == "apps.core.events" and r.levelname == "ERROR"], \
        "подписчики события отработали без ошибок (п. 39)"
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(comments.CommentError):
            articles.add_comment(writer, article.pk, "я" * 4001)
    assert len(bus.calls("knowledge.comment_added")) == 1, "отказ события не публикует"
    assert "комментарий для события" not in json.dumps(bus.calls("knowledge.comment_added"), ensure_ascii=False)


# --- внутренние комментарии заявок не затронуты (FR-426) ------------------------------------------------

def _ticket_with_actor():
    actor = support.make_with_permissions("servicedesk.all")
    ticket = sd.make_ticket(queue=sd.make_queue(), kind="in_progress")
    return actor, ticket


def test_ticket_internal_comments_remain_feed_records_not_core_comments():
    """FR-426: внутренний комментарий заявки — запись ленты `TicketEntry` вида `comment`, а не `core.Comment`; ядро комментариев его не знает."""
    actor, ticket = _ticket_with_actor()
    client = support.logged_in(actor)
    article = kb.make_published()
    kb.make_comment(article, actor, "комментарий к статье")
    Entry = support.model("servicedesk.TicketEntry")
    comments_before = _Comment().objects.count()
    response = client.post(f"/tickets/{ticket.number}/comment/", {"text": "Только для своих"})
    assert response.status_code in (200, 302)
    entry = Entry.objects.get(ticket=ticket, kind="comment")
    assert entry.text == "Только для своих" and entry.author == actor
    assert _Comment().objects.count() == comments_before, "внутренний комментарий заявки не создаёт `core.Comment`"
    assert not _Comment().objects.filter(text="Только для своих").exists()
    page = tree(client.get(f"/tickets/{ticket.number}/"))
    (item,) = [li for li in q(page, "li", data_entry_id=True) if li.attrs.get("data-kind") == "comment"]
    assert item.attrs["data-entry-id"] == str(entry.pk) and "Только для своих" in item.text()
    assert q(page, "section", id="comments") == [] and q(page, data_kb_comments=True) == []
    entries_before = Entry.objects.filter(ticket=ticket).count()
    assert _post_comment(kb.as_reader(), article, "комментарий к статье 2").status_code == 200
    assert Entry.objects.filter(ticket=ticket).count() == entries_before, "комментарий к статье в ленту заявки не попадает"


def test_ticket_internal_comment_still_not_editable_or_deletable():
    """FR-426: внутренний комментарий заявки по-прежнему нельзя править и удалять: нет кнопок, адреса правки и удаления — 404; адрес удаления статейного комментария его не касается."""
    actor, ticket = _ticket_with_actor()
    client = support.logged_in(actor)
    entry = sd.make_entry(ticket, "comment", author=actor, text="Внутренний комментарий")
    article = kb.make_published()
    comment = kb.make_comment(article, actor, "комментарий к статье")
    while comment.pk == entry.pk:
        comment = kb.make_comment(article, actor, "ещё один комментарий к статье")
    _Comment().objects.filter(pk=entry.pk).exclude(pk=comment.pk).delete()
    page = tree(client.get(f"/tickets/{ticket.number}/"))
    (item,) = [li for li in q(page, "li", data_entry_id=True) if li.attrs["data-entry-id"] == str(entry.pk)]
    assert q(item, "form") == []
    for node in q(item, "button") + q(item, "a"):
        label = (node.text() + " " + node.attrs.get("data-action", "")).lower()
        assert not any(word in label for word in ("удал", "править", "изменить", "delete", "edit")), label
    for suffix in ("edit/", "delete/"):
        for method in (client.get, client.post):
            assert method(f"/tickets/{ticket.number}/comment/{entry.pk}/{suffix}").status_code == 404
    manager = kb.as_manager()
    response = manager.client.post(f"/kb/comments/{entry.pk}/delete/", {}, **HX)
    assert response.status_code == 404, "номер записи ленты — не номер комментария статьи"
    assert support.model("servicedesk.TicketEntry").objects.filter(pk=entry.pk, text="Внутренний комментарий").exists()
    assert _Comment().objects.filter(pk=comment.pk).exists()
