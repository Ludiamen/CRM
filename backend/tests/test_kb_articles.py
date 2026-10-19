"""T-5103: статья — создание, пределы, публикация, события и векторы (FR-401, FR-404, FR-406, FR-408, FR-409, FR-410,
FR-435, FR-447). Сценарий 1 спеки среза 005.

Первое сохранение черновика (версия 1 одной транзакцией, журнал), проверки формы и пределы, постоянный адрес по номеру,
невидимость черновика для других, публикация (с версией и без, `published_at`, `updated_*`, журнал, событие, векторы),
запрет возврата в черновик, показ страницы (`object.viewed`), кнопки «Вложить» и «Картинка» до первого сохранения, права
на создание и чужие черновики. Код среза на уровне модуля не импортируется: имена берутся внутри тестов
(CONTRACT-005, шапка). Гонок здесь нет (они в T-5104). Время — фикстурой `clock`, событие шины — фикстурой `bus`.
"""
import importlib
import logging
import uuid
from html.parser import HTMLParser

import pytest
from django.db import connection
from django.utils import timezone

from tests import support
from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}


# --- помощники только этого файла ------------------------------------------------------------------------

def _articles():
    return importlib.import_module("apps.knowledge.services.articles")


def _unique(prefix: str = "Статья") -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _form(rubric=None, **over) -> dict:
    """Поля формы `/kb/new/` и `/kb/<id>/edit/` (CONTRACT-005, 10.2)."""
    data = {"title": _unique(), "text": "Текст первой версии", "rubric": (rubric or kb.general_rubric()).pk,
            "tags": "", "comment": ""}
    data.update(over)
    return data


def _create(session, **over):
    """Первое сохранение через страницу; возвращает ответ и созданную статью (или `None`)."""
    data = _form(**over)
    response = session.client.post("/kb/new/", data)
    return response, model("knowledge.Article").objects.filter(title=data["title"]).first()


def _edit_data(article, **over) -> dict:
    """Форма правки: текущие значения статьи плюс `over`; `base_version` — текущая версия."""
    article.refresh_from_db()
    data = {"title": article.title, "text": article.text, "rubric": article.rubric_id,
            "tags": ", ".join(article.tags.order_by("name").values_list("name", flat=True)), "comment": "",
            "base_version": article.version_no, "confirm_pdn": "", "action": "save"}
    data.update(over)
    return data


def _versions(article) -> list:
    return list(article.versions.order_by("number"))


def _journal(action: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _kb_journal() -> list:
    return list(model("core.AuditEvent").objects.filter(action__startswith="knowledge.").order_by("id"))


def _article_count() -> int:
    return model("knowledge.Article").objects.count()


def _subscriber_errors(caplog) -> list:
    return [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]


# --- разбор разметки (помощник только этого файла) ---------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, Node) else parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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
        while node is not self.root:
            if node.tag == tag:
                self.cur = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {k.rstrip("_").replace("_", "-"): v for k, v in attrs.items()}
    result = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            result.append(node)
    return result


def _flashes(response) -> str:
    return " ".join(node.text() for node in _find(_tree(response), role="status"))


def _field_error(response, field: str, code: str, text: str) -> None:
    """Отказ у поля: `[data-error="<поле>"][data-code="<код>"]` с текстом раздела 12 (CONTRACT-005, 10.1)."""
    nodes = _find(_tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error={field}][data-code={code}] в ответе {response.status_code}"
    assert any(text in node.text() for node in nodes), f"нет текста «{text}» у отказа {code}"


# --- 1. первое сохранение ------------------------------------------------------------------------------------

def test_first_save_draft_creates_draft_article_and_version_1_in_one_transaction(bus, django_capture_on_commit_callbacks):
    """FR-401, FR-408, FR-410: «Сохранить черновик» — статья `draft`, `version_no=1`, версия 1 со снимком, векторов и событий нет."""
    editor = kb.as_editor()
    rubric = kb.make_rubric("Сети")
    bus.listen("knowledge.article_published", "knowledge.article_changed")
    title = _unique()
    with django_capture_on_commit_callbacks(execute=True):
        response = editor.client.post("/kb/new/", _form(
            rubric, title=title, text="Первый *курсив* текст", tags="VPN, Сеть, vpn", comment="первая запись"))
    article = model("knowledge.Article").objects.get(title=title)
    assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/edit/"
    assert article.state == "draft" and article.version_no == 1
    assert article.author == editor.user and article.updated_by == editor.user
    assert article.rubric == rubric and article.published_at is None and article.deleted_at is None
    assert article.search_head is None and article.search_full is None, "у черновика векторов нет"
    assert "<em>" in article.html and "курсив" in article.plain
    assert sorted(article.tags.values_list("name", flat=True)) == ["vpn", "сеть"]
    (version,) = _versions(article)
    assert version.number == 1 and version.author == editor.user and version.comment == "первая запись"
    assert (version.title, version.text, version.rubric, version.rubric_name) == (
        title, "Первый *курсив* текст", rubric, "Сети")
    assert sorted(version.tags) == ["vpn", "сеть"] and "<em>" in version.html
    assert _article_count() == 1
    assert bus.all() == [], "черновик событий не даёт"
    assert "Черновик сохранён" in _flashes(editor.client.get(response["Location"]))


def test_first_save_rolls_back_article_when_version_creation_fails(monkeypatch):
    """FR-401: сбой создания версии откатывает и статью — одна транзакция; журнала нет."""
    editor = kb.as_editor()
    articles = _articles()

    class Boom(Exception):
        pass

    kb.fail_version_creation(monkeypatch, Boom("сбой версии (тест)"))
    before = _article_count()
    form = articles.ArticleForm(title=_unique(), text="Текст", rubric_id=kb.general_rubric().pk, tags="", comment="")
    with pytest.raises(Boom):
        articles.create(editor.user, form)
    assert _article_count() == before, "статья не должна остаться без версии"
    assert model("knowledge.ArticleVersion").objects.count() == 0
    assert _kb_journal() == []


def test_first_save_writes_journal_entry_create_article():
    """FR-401: журнал `knowledge.article_created` — автор, статья, `after`: `number`, `title`, `version=1`; `before` пуст."""
    editor = kb.as_editor()
    _, article = _create(editor, title=_unique("Журнал"))
    (entry,) = _journal("knowledge.article_created")
    assert entry.actor == editor.user
    assert (entry.object_type, entry.object_id) == ("knowledge.article", str(article.pk))
    assert entry.before == {}
    assert set(entry.after) == {"number", "title", "version"}
    assert entry.after["number"] == article.pk
    assert entry.after["title"] == article.title and entry.after["version"] == 1
    assert _no_text_in(entry, article.text)


def _no_text_in(entry, text: str) -> bool:
    """Текста статьи в записи журнала нет (раздел 8)."""
    return text not in str(entry.before) and text not in str(entry.after)


# --- 2. проверки формы и пределы ----------------------------------------------------------------------------

def test_empty_title_or_missing_rubric_is_rejected_at_field_and_input_stays():
    """FR-401: пустой заголовок — отказ у `title`; рубрики нет (пусто или несуществующая) — у `rubric`; введённое остаётся."""
    editor = kb.as_editor()
    typed = {"text": "Набранный текст остаётся", "tags": "VPN, Сеть", "comment": "комментарий"}
    for blank in ("", "   "):
        response = editor.client.post("/kb/new/", _form(title=blank, **typed))
        assert response.status_code == 200
        _field_error(response, "title", "title_empty", "Введите заголовок")
        tree = _tree(response)
        (area,) = _find(tree, "textarea", name="text")
        assert "Набранный текст остаётся" in area.text()
        (tags,) = _find(tree, "input", name="tags")
        assert tags.attrs["value"] == "VPN, Сеть"
    title = _unique()
    for rubric in ("", "999999999"):
        data = _form(title=title, **typed)
        data["rubric"] = rubric
        response = editor.client.post("/kb/new/", data)
        assert response.status_code == 200
        _field_error(response, "rubric", "rubric_missing", "Выберите рубрику: такой рубрики нет")
        tree = _tree(response)
        (name,) = _find(tree, "input", name="title")
        assert name.attrs["value"] == title
        (area,) = _find(tree, "textarea", name="text")
        assert "Набранный текст остаётся" in area.text()
    assert _article_count() == 0 and _kb_journal() == []


def test_title_limit_200_accepted_201_rejected_with_input_kept():
    """FR-401: заголовок 200 знаков принимается, 201 — отказ у `title` (`title_too_long`), введённое остаётся."""
    editor = kb.as_editor()
    ok_title = "я" * 200
    response, article = _create(editor, title=ok_title)
    assert response.status_code == 302 and article is not None and len(article.title) == 200
    long_title = "ю" * 201
    response = editor.client.post("/kb/new/", _form(title=long_title, text="Текст при длинном заголовке"))
    assert response.status_code == 200
    _field_error(response, "title", "title_too_long", "Заголовок не длиннее 200 знаков")
    tree = _tree(response)
    (name,) = _find(tree, "input", name="title")
    assert name.attrs["value"] == long_title
    (area,) = _find(tree, "textarea", name="text")
    assert "Текст при длинном заголовке" in area.text()
    assert _article_count() == 1, "статья с заголовком 201 не создана"
    assert len(_journal("knowledge.article_created")) == 1


def test_text_limit_200000_accepted_200001_rejected_with_input_kept():
    """FR-401: текст 200 000 знаков принимается, 200 001 — отказ у `text` (`text_too_long`), введённое остаётся."""
    editor = kb.as_editor()
    response, article = _create(editor, text="a" * 200_000)
    assert response.status_code == 302 and article is not None and len(article.text) == 200_000
    title = _unique()
    response = editor.client.post("/kb/new/", _form(title=title, text="a" * 200_001))
    assert response.status_code == 200
    _field_error(response, "text", "text_too_long", "Текст не длиннее 200 000 знаков")
    assert "a" * 200_001 in response.content.decode("utf-8"), "введённый текст остаётся в форме"
    assert not model("knowledge.Article").objects.filter(title=title).exists()
    assert _article_count() == 1


def test_edit_comment_limit_200_accepted_201_rejected_with_input_kept():
    """FR-410: комментарий к правке 200 знаков принимается, 201 — отказ у `comment` (`comment_too_long`), версии нет."""
    editor = kb.as_editor()
    article = kb.make_draft(author=editor.user, text="Исходный текст")
    path = f"/kb/{article.pk}/edit/"
    response = editor.client.post(path, _edit_data(article, text="Правка раз", comment="к" * 201))
    assert response.status_code == 200
    _field_error(response, "comment", "comment_too_long", "Комментарий к правке не длиннее 200 знаков")
    tree = _tree(response)
    (comment,) = _find(tree, "input", name="comment")
    assert comment.attrs["value"] == "к" * 201
    (area,) = _find(tree, "textarea", name="text")
    assert "Правка раз" in area.text()
    article.refresh_from_db()
    assert article.version_no == 1 and article.text == "Исходный текст" and len(_versions(article)) == 1
    response = editor.client.post(path, _edit_data(article, text="Правка два", comment="к" * 200))
    assert response.status_code == 302
    article.refresh_from_db()
    assert article.version_no == 2 and article.text == "Правка два"
    assert [v.comment for v in _versions(article)][-1] == "к" * 200
    # на первом сохранении предел тот же
    response = editor.client.post("/kb/new/", _form(comment="к" * 201))
    assert response.status_code == 200
    _field_error(response, "comment", "comment_too_long", "Комментарий к правке не длиннее 200 знаков")
    _, created = _create(editor, comment="к" * 200)
    assert created is not None and _versions(created)[0].comment == "к" * 200


# --- 3. адрес и невидимость черновика ---------------------------------------------------------------------

def test_article_url_is_by_id_and_does_not_change_after_title_and_rubric_change():
    """FR-404: адрес `/kb/<id>/` по номеру; смена заголовка и рубрики адрес не меняет, второй статьи не создаёт."""
    editor = kb.as_editor()
    first, second = kb.make_rubric("Первая"), kb.make_rubric("Вторая")
    data = _form(first, title=_unique("Прежнее название"))
    response = editor.client.post("/kb/new/", data, **HX)
    article = model("knowledge.Article").objects.get(title=data["title"])
    assert response.status_code == 200 and response.content == b""
    assert response["HX-Redirect"] == f"/kb/{article.pk}/edit/", "после первого сохранения — редактор статьи по номеру"
    new_title = _unique("Новое название")
    response = editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(article, title=new_title, rubric=second.pk))
    assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/"
    assert _article_count() == 1
    article.refresh_from_db()
    assert article.title == new_title and article.rubric == second
    page = editor.client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200
    (root,) = _find(_tree(page), "article", data_article_id=str(article.pk))
    assert root.attrs["data-article-state"] == "draft"
    (heading,) = _find(root, "h1", data_field="title")
    assert heading.text() == new_title
    for path in (response["Location"], response["Location"] + "edit/"):
        assert new_title not in path and "Вторая" not in path


def test_saved_draft_is_absent_from_new_and_changed_rubric_page_and_search_for_other_users():
    """FR-408, FR-447: черновик не виден в «Новые и изменённые», на странице рубрики (в том числе новой) и в поиске."""
    author = kb.as_editor()
    first, second = kb.make_rubric("Исходная"), kb.make_rubric("Новая")
    published = kb.make_published(title="Квантоплан опубликованная заметка", rubric=first)
    word = "Квантоплан"
    draft_title = word + " черновая заметка"
    _, draft = _create(author, title=draft_title, rubric=first, text="Квантоплан в тексте")
    reader, other_editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()

    def check_absent(session):
        home = session.client.get("/kb/")
        assert home.status_code == 200
        (recent,) = _find(_tree(home), data_kb_new_and_changed=True)
        assert [n.attrs["data-article-id"] for n in _find(recent, "li", data_article_id=True)].count(str(draft.pk)) == 0
        for rubric in (first, second):
            page = session.client.get(f"/kb/rubrics/{rubric.pk}/")
            assert page.status_code == 200
            ids = [n.attrs["data-article-id"] for n in _find(_tree(page), "li", data_article_id=True)]
            assert str(draft.pk) not in ids
        for path in ("/search/?q=" + word.lower(), "/search/popup/?q=" + word.lower()):
            found = session.client.get(path)
            assert found.status_code == 200
            body = found.content.decode("utf-8")
            assert "опубликованная заметка" in body, "поиск работает: опубликованная статья найдена"
            assert draft_title not in body

    for session in (reader, other_editor, manager, author):
        check_absent(session)
    response = author.client.post(f"/kb/{draft.pk}/edit/", _edit_data(draft, rubric=second.pk, comment="перенос"))
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.rubric == second and draft.state == "draft"
    assert draft.search_head is None and draft.search_full is None
    for session in (reader, other_editor, manager, author):
        check_absent(session)
    assert published.state == "published"


# --- 4. публикация ---------------------------------------------------------------------------------------

def test_publish_with_changed_form_text_creates_new_version_and_publishes():
    """FR-408, FR-410: «Опубликовать» с изменённым текстом формы — версия 2 и состояние `published` одним действием."""
    editor = kb.as_editor()
    article = kb.make_draft(author=editor.user, text="Старый текст черновика")
    response = editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(
        article, text="Новый текст при публикации", comment="перед публикацией", action="publish"))
    assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/"
    article.refresh_from_db()
    assert article.state == "published" and article.version_no == 2 and article.published_at is not None
    versions = _versions(article)
    assert [v.number for v in versions] == [1, 2]
    assert versions[1].text == "Новый текст при публикации" and versions[1].comment == "перед публикацией"
    assert versions[1].author == editor.user and versions[0].text == "Старый текст черновика"
    assert article.text == "Новый текст при публикации"
    assert "Статья опубликована" in _flashes(editor.client.get(response["Location"]))
    assert len(_journal("knowledge.article_published")) == 1


def test_publish_without_text_change_publishes_without_new_version():
    """FR-408, FR-410: кнопка на странице черновика и «Опубликовать» с неизменной формой — публикация без новой версии."""
    editor = kb.as_editor()
    first = kb.make_draft(author=editor.user)
    response = editor.client.post(f"/kb/{first.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 302 and response["Location"] == f"/kb/{first.pk}/"
    first.refresh_from_db()
    assert first.state == "published" and first.version_no == 1 and len(_versions(first)) == 1
    second = kb.make_draft(author=editor.user, tags=("vpn",))
    response = editor.client.post(f"/kb/{second.pk}/edit/", _edit_data(second, action="publish"))
    assert response.status_code == 302
    second.refresh_from_db()
    assert second.state == "published" and second.version_no == 1 and len(_versions(second)) == 1
    assert len(_journal("knowledge.article_published")) == 2


def test_publish_sets_published_at_updated_by_and_updated_at_to_publisher_and_lists_in_new_and_changed(clock):
    """FR-408, FR-410: публикация без версии ставит `published_at`, `updated_by` и `updated_at` — время и тот, кто опубликовал."""
    author, manager, reader = kb.as_editor(), kb.as_manager(), kb.as_reader()
    draft = kb.make_draft(author=author.user, title=_unique("Давний черновик"))
    created_at = draft.updated_at
    clock.advance(minutes=5)
    kb.make_published(title=_unique("Промежуточная"))
    clock.advance(minutes=5)
    publish_time = timezone.now()
    assert publish_time > created_at
    response = manager.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.state == "published" and draft.version_no == 1
    assert draft.published_at == publish_time
    assert draft.updated_by == manager.user and draft.updated_at == publish_time
    assert draft.author == author.user, "автор статьи не меняется"
    home = reader.client.get("/kb/")
    (recent,) = _find(_tree(home), data_kb_new_and_changed=True)
    ids = [n.attrs["data-article-id"] for n in _find(recent, "li", data_article_id=True)]
    assert ids and ids[0] == str(draft.pk), "опубликованный давний черновик — первым в «Новых и изменённых»"


def test_published_at_stays_the_time_of_first_publication_after_later_saves(clock):
    """FR-408: `published_at` — время первой публикации; позднейшие сохранения его не меняют, `updated_at` меняют."""
    editor = kb.as_editor()
    article = kb.make_draft(author=editor.user)
    first_time = timezone.now()
    response = editor.client.post(f"/kb/{article.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 302
    article.refresh_from_db()
    assert article.published_at == first_time
    for number in (2, 3):
        clock.advance(minutes=10)
        moment = timezone.now()
        response = editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(article, text=f"Правка номер {number}"))
        assert response.status_code == 302
        article.refresh_from_db()
        assert article.version_no == number and article.updated_at == moment
        assert article.published_at == first_time


def test_publish_makes_article_visible_to_all_writes_journal_publication_and_event_article_published(
        bus, django_capture_on_commit_callbacks, caplog):
    """FR-408, FR-447: публикация открывает статью всем, пишет журнал `knowledge.article_published` и событие шины."""
    author, reader = kb.as_editor(), kb.as_reader()
    manager = kb.as_manager()
    rubric = kb.make_rubric("Публикации")
    draft = kb.make_draft(author=author.user, rubric=rubric, title=_unique("К публикации"))
    bus.listen("knowledge.article_published", "knowledge.article_changed")
    assert reader.client.get(f"/kb/{draft.pk}/").status_code == 404
    with django_capture_on_commit_callbacks(execute=True):
        response = manager.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 302
    page = reader.client.get(f"/kb/{draft.pk}/")
    assert page.status_code == 200
    (root,) = _find(_tree(page), "article", data_article_id=str(draft.pk))
    assert root.attrs["data-article-state"] == "published"
    assert bus.calls("knowledge.article_published") == [
        {"article_id": draft.pk, "actor_id": manager.user.pk, "rubric_id": rubric.pk}]
    assert bus.calls("knowledge.article_changed") == [], "публикация — не «изменение»"
    (entry,) = _journal("knowledge.article_published")
    assert entry.actor == manager.user
    assert (entry.object_type, entry.object_id) == ("knowledge.article", str(draft.pk))
    assert entry.before == {} and set(entry.after) == {"number", "title", "version"}
    assert entry.after["number"] == draft.pk and entry.after["title"] == draft.title
    assert entry.after["version"] == 1
    assert _subscriber_errors(caplog) == []


def test_published_article_has_no_return_to_draft_button_and_service_has_no_such_action():
    """FR-408: опубликованную статью нельзя вернуть в черновик: кнопки нет ни у кого, у службы такого действия нет."""
    author, other, manager = kb.as_editor(), kb.as_editor(), kb.as_manager()
    article = kb.make_published(author=author.user)
    articles = _articles()
    names = set(dir(articles))
    assert not names & {"unpublish", "to_draft", "revert"}, "в `articles` нет обратного перехода"
    for session in (author, other, manager):
        page = session.client.get(f"/kb/{article.pk}/")
        assert page.status_code == 200
        tree = _tree(page)
        (root,) = _find(tree, "article", data_article_id=str(article.pk))
        assert root.attrs["data-article-state"] == "published"
        assert not _find(tree, "form", data_form="kb-publish"), "у опубликованной нет кнопки публикации"
        assert "Вернуть в черновик" not in page.content.decode("utf-8")
    response = author.client.post(f"/kb/{article.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 200
    assert _find(_tree(response), role="alert", data_code="already_published")
    article.refresh_from_db()
    assert article.state == "published" and article.version_no == 1 and len(_versions(article)) == 1
    assert _journal("knowledge.article_published") == []


def test_search_vectors_are_empty_for_draft_and_computed_at_publication():
    """FR-447: у черновика `search_head` и `search_full` — `NULL`; публикация считает их: заголовок и теги — в `head`, текст — в `full`."""
    editor = kb.as_editor()
    response, article = _create(editor, title="Принтеры бухгалтерии", text="Драйверы устанавливаются из каталога",
                                tags="печать")
    assert response.status_code == 302
    assert article.search_head is None and article.search_full is None
    response = editor.client.post(f"/kb/{article.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 302
    article.refresh_from_db()
    assert article.state == "published"
    assert article.search_head is not None and article.search_full is not None

    # Готовые строки запроса без подстановки в текст SQL (инвариант «sql-только-параметры»), значения — параметрами `%s`;
    # имя таблицы — буквально, его совпадение с моделью проверяется отдельно
    assert model("knowledge.Article")._meta.db_table == "knowledge_article"
    sql = {
        "search_head": "SELECT search_head @@ to_tsquery('russian', %s) FROM knowledge_article WHERE id = %s",
        "search_full": "SELECT search_full @@ to_tsquery('russian', %s) FROM knowledge_article WHERE id = %s",
    }

    def matches(column: str, query: str) -> bool:
        with connection.cursor() as cursor:
            cursor.execute(sql[column], [query, article.pk])
            return bool(cursor.fetchone()[0])

    assert matches("search_head", "принтер:*") and matches("search_full", "принтер:*"), "заголовок"
    assert matches("search_head", "печат:*") and matches("search_full", "печат:*"), "тег"
    assert matches("search_full", "драйвер:*") and not matches("search_head", "драйвер:*"), "текст только в full"


# --- 5. показ страницы, кнопки до первого сохранения ----------------------------------------------------------

def test_viewing_article_publishes_object_viewed_with_knowledge_article_ref(bus, django_capture_on_commit_callbacks):
    """FR-435: показ страницы статьи публикует `object.viewed` (`object_ref`, `user_id`); при 404 и 410 — нет."""
    reader = kb.as_reader()
    article = kb.make_published()
    foreign_draft = kb.make_draft()
    trashed = kb.make_trashed()
    bus.listen("object.viewed")
    with django_capture_on_commit_callbacks(execute=True):
        assert reader.client.get(f"/kb/{foreign_draft.pk}/").status_code == 404
        assert reader.client.get(f"/kb/{trashed.pk}/").status_code == 410
        assert bus.calls("object.viewed") == []
        assert reader.client.get(f"/kb/{article.pk}/").status_code == 200
    assert bus.calls("object.viewed") == [{"object_ref": f"knowledge.article:{article.pk}", "user_id": reader.user.pk}]


def test_attach_and_image_buttons_are_disabled_with_save_draft_hint_before_first_save_and_active_after():
    """FR-401, FR-408: до первого сохранения «Вложить» и «Картинка» неактивны с подсказкой «Сохраните черновик»; после — активны."""
    editor = kb.as_editor()
    response = editor.client.get("/kb/new/")
    assert response.status_code == 200
    tree = _tree(response)
    (form,) = _find(tree, "form", data_form="kb-article")
    (attach,) = _find(tree, "button", data_action="kb-attach")
    (image,) = _find(tree, "button", data_md="image")
    for button in (attach, image):
        assert "disabled" in button.attrs and button.attrs.get("title") == "Сохраните черновик"
    (hint,) = _find(tree, data_kb_hint="save-draft")
    assert "Сохраните черновик" in hint.text()
    assert not _find(tree, "button", data_action="kb-publish"), "на новой статье кнопки «Опубликовать» нет"
    (save,) = _find(form, "button", data_action="kb-save")
    assert save.attrs.get("value") == "save" and "Сохранить черновик" in save.text()
    _, article = _create(editor)
    response = editor.client.get(f"/kb/{article.pk}/edit/")
    assert response.status_code == 200
    tree = _tree(response)
    (attach,) = _find(tree, "button", data_action="kb-attach")
    (image,) = _find(tree, "button", data_md="image")
    for button in (attach, image):
        assert "disabled" not in button.attrs and button.attrs.get("title") != "Сохраните черновик"
    assert not _find(tree, data_kb_hint="save-draft"), "после первого сохранения подсказки нет"


# --- 6. права ------------------------------------------------------------------------------------------------

def test_new_article_without_edit_right_is_forbidden_and_new_article_button_is_not_shown():
    """FR-406, FR-409: без `knowledge.edit` и `knowledge.manage` — 403 на GET и POST `/kb/new/`, кнопки нет; с правом — есть."""
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()
    assert reader.client.get("/kb/new/").status_code == 403
    assert reader.client.post("/kb/new/", _form()).status_code == 403
    assert reader.client.post("/kb/new/", _form(), **HX).status_code == 403
    assert _article_count() == 0 and _kb_journal() == []
    home = reader.client.get("/kb/")
    assert home.status_code == 200
    assert not _find(_tree(home), "a", data_action="kb-new-article")
    for session in (editor, manager):
        assert session.client.get("/kb/new/").status_code == 200
        links = _find(_tree(session.client.get("/kb/")), "a", data_action="kb-new-article")
        assert links and all(a.attrs["href"] == "/kb/new/" for a in links)
    assert manager.client.post("/kb/new/", _form()).status_code == 302
    assert _article_count() == 1


def test_foreign_draft_edit_and_publish_by_non_manager_with_edit_right_gives_404():
    """FR-408: чужой черновик у редактора (не управляющего) — 404 на чтение, правку и публикацию, как у несуществующего."""
    author, other = kb.as_editor(), kb.as_editor()
    draft = kb.make_draft(author=author.user, title=_unique("Чужой черновик"), text="Содержимое чужого черновика")
    missing = other.client.get("/kb/999999999/")
    assert missing.status_code == 404
    responses = [
        other.client.get(f"/kb/{draft.pk}/"),
        other.client.get(f"/kb/{draft.pk}/edit/"),
        other.client.post(f"/kb/{draft.pk}/edit/", _edit_data(draft, text="Чужая правка")),
        other.client.post(f"/kb/{draft.pk}/edit/", _edit_data(draft, action="publish")),
        other.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": ""}),
        other.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": ""}, **HX),
    ]
    for response in responses:
        assert response.status_code == 404
        body = response.content.decode("utf-8")
        assert draft.title not in body and "Содержимое чужого черновика" not in body
    draft.refresh_from_db()
    assert draft.state == "draft" and draft.version_no == 1 and draft.text == "Содержимое чужого черновика"
    assert len(_versions(draft)) == 1 and _journal("knowledge.article_published") == []


def test_manager_sees_foreign_draft_edits_it_and_publishes_it(bus, django_capture_on_commit_callbacks, caplog):
    """FR-408: управляющий видит чужой черновик, правит его (версия 2 — его) и публикует; событие несёт его `actor_id`."""
    author, manager = kb.as_editor(), kb.as_manager()
    draft = kb.make_draft(author=author.user, title=_unique("Черновик автора"), text="Текст автора")
    bus.listen("knowledge.article_published")
    page = manager.client.get(f"/kb/{draft.pk}/")
    assert page.status_code == 200
    tree = _tree(page)
    (root,) = _find(tree, "article", data_article_id=str(draft.pk))
    assert root.attrs["data-article-state"] == "draft"
    assert _find(tree, "a", data_action="kb-edit") and _find(tree, "form", data_form="kb-publish")
    assert manager.client.get(f"/kb/{draft.pk}/edit/").status_code == 200
    response = manager.client.post(f"/kb/{draft.pk}/edit/", _edit_data(
        draft, text="Текст после правки управляющего", comment="правка управляющего"))
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.state == "draft" and draft.version_no == 2 and draft.author == author.user
    assert draft.updated_by == manager.user
    assert _versions(draft)[1].author == manager.user and _versions(draft)[1].comment == "правка управляющего"
    with django_capture_on_commit_callbacks(execute=True):
        response = manager.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 2, "confirm_pdn": ""})
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.state == "published" and draft.version_no == 2 and draft.published_at is not None
    assert [c["actor_id"] for c in bus.calls("knowledge.article_published")] == [manager.user.pk]
    assert _subscriber_errors(caplog) == []
    assert support.model("core.AuditEvent").objects.filter(
        action="knowledge.article_published", actor=manager.user, object_id=str(draft.pk)).count() == 1
