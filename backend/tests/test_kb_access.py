"""T-5109: права и видимость базы знаний (FR-401, FR-405, FR-406, FR-407, FR-408, FR-409, FR-418).

Сценарии «Права, черновик, публикация» и «Корзина» спеки: пункт меню, вход, матрица «действие × роль»
(CONTRACT-005, 10.7), черновики автора без права и уволенного автора, корзина по старой ссылке, ответ на недоступное
равен ответу на несуществующее, проверка права на сервере без кнопки и в службе, миграция данных `knowledge 0002`.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка).

Порядок отказов при POST над статьёй в корзине — решение Opus (задание T-5109, контракт 10.1, 10.7, раздел 16):
сначала корзина (200 «Статья удалена»), затем право; это верно и для `restore/` и `purge/` от не-управляющего.
"""
import re
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support
from tests import support_kb as kb
from tests import support_servicedesk as sd
from tests.support import HX

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _storage(protected_root, monkeypatch):
    """Вложения пишутся во временный том, проверка ClamAV отвечает «чисто» (подмена строкой, контракт 1.2)."""
    kb.scan_clean(monkeypatch)

GONE = "Статья удалена"
IT_ROLE = "Сотрудник ИТ"
CHIEF_ROLE = "Руководитель"
ADMIN_ROLE = "Администратор портала"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


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

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
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
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; в имени атрибута `_` означает дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [node for node in scope.walk()
            if (tag is None or node.tag == tag)
            and all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items())]


def _html(response) -> str:
    return response.content.decode("utf-8")


def _ids(root) -> list[int]:
    return [int(node.attrs["data-article-id"]) for node in root.walk()
            if node.tag in ("li", "tr") and "data-article-id" in node.attrs]


# --- данные теста ---------------------------------------------------------------------------------------

def _model(label: str):
    return support.model(label)


def _svc(name: str):
    import importlib

    return importlib.import_module(f"apps.knowledge.services.{name}")


def _fresh(user):
    """Сотрудник из базы с пустым кэшем прав (изменение ролей в тесте не доходит до фиксации)."""
    from django.core.cache import cache

    from apps.core.services import permissions

    cache.delete(permissions._key(user.pk))
    return _model("core.User").objects.get(pk=user.pk)


def _published(**over):
    """Опубликованная статья с двумя версиями, тегом `vpn` и файлом (для проверки действий)."""
    over.setdefault("tags", ("vpn",))
    article = kb.make_published(**over)
    kb.add_version(article, text=article.text + " вторая версия", comment="правка")
    return article


def _snap(article) -> tuple:
    """Состояние статьи в базе: сравнивается до и после отказа."""
    current = _model("knowledge.Article").objects.get(pk=article.pk)
    versions = _model("knowledge.ArticleVersion").objects.filter(article=current).count()
    files = _model("knowledge.ArticleFile").objects.filter(article=current).count()
    return (current.state, current.version_no, current.title, current.text, current.deleted_at, current.published_at,
            versions, files)


def _read_pages(article) -> list[str]:
    """Страницы чтения без правки: статья, история, сравнение, просмотр версии 1."""
    return [path for path in kb.article_pages(article) if not path.endswith("/edit/")]


def _edit_data(article, **over) -> dict:
    data = {"title": article.title, "text": article.text + " правка", "rubric": article.rubric_id, "tags": "vpn",
            "comment": "правка по тесту", "base_version": article.version_no, "action": "save"}
    data.update(over)
    return data


def _upload():
    return SimpleUploadedFile("note.txt", b"plain text of the note", content_type="text/plain")


_ACTION_NAMES = ("edit", "publish", "restore_version", "file_attach", "file_delete")


def _action(name: str, article, file_row) -> tuple[str, dict]:
    """POST-действие над статьёй из строк 748-750 сводки (контракт 10.7): адрес и поля. `base_version` берётся у
    переданной статьи — перед каждым действием её надо обновить из базы."""
    base = f"/kb/{article.pk}/"
    return {
        "edit": (base + "edit/", _edit_data(article)),
        "publish": (base + "publish/", {"base_version": article.version_no}),
        "restore_version": (base + "versions/1/restore/", {}),
        "file_attach": (base + "files/", {"file": _upload()}),
        "file_delete": (base + f"files/{file_row.pk}/delete/", {}),
    }[name]


def _gone_alert(response) -> bool:
    """Отказ «Статья удалена»: 200, текст и `[role=alert][data-code="article_gone"]` (раздел 17, п. 10)."""
    return (response.status_code == 200 and GONE in _html(response)
            and bool(_q(_tree(response), None, role="alert", data_code="article_gone")))


def _expect(label: str, response, want) -> None:
    """`want`: число (код ответа) или `"gone"` (200 и `[role=alert][data-code="article_gone"]`). Успех (`"ok"`)
    проверяет `_expect_ok`: ему нужно имя действия и состояние статьи."""
    code = response.status_code
    if want == "gone":
        assert _gone_alert(response), f"{label}: ждали 200 и [role=alert][data-code=article_gone], получили {code}"
    else:
        assert code == want, f"{label}: ждали {want}, получили {code}"


def _expect_ok(label: str, response, name: str, was_published: bool) -> None:
    """Успех действия: 200 или 302, но не отказ формы — нет `article_gone`, `stale_version`, `[data-error]` и любого
    `[role=alert]`. Единственное исключение — повторная публикация уже опубликованной статьи: это не отказ права,
    а `[role=alert][data-code="already_published"]` (контракт 10.2)."""
    assert response.status_code in (200, 302), f"{label}: ждали 200 или 302, получили {response.status_code}"
    if response.status_code == 302:
        return
    root = _tree(response)
    assert not _gone_alert(response), f"{label}: ответ — «Статья удалена»"
    assert not _q(root, None, data_error=True), f"{label}: отказ поля формы"
    alerts = [node.attrs.get("data-code", "") for node in _q(root, None, role="alert")]
    allowed = ["already_published"] if (name == "publish" and was_published) else []
    assert alerts == allowed, f"{label}: ждали отказы {allowed}, получили {alerts}"


def _run_actions(who, article, want, *, stay=True) -> None:
    """Выполняет действия над статьёй и сверяет ответ; при отказе состояние в базе не меняется. При `"ok"`: ответ —
    не отказ формы, а правка добавляет ровно одну версию (`version_no` + 1); остальные действия идут уже с
    актуальным `base_version`."""
    file_row = kb.attach_file(article, "схема.png")
    before = _snap(article)
    for name in _ACTION_NAMES:
        article.refresh_from_db()
        path, data = _action(name, article, file_row)
        version_before, was_published = article.version_no, article.state == "published"
        response = who.client.post(path, data)
        if want == "ok":
            _expect_ok(f"{name} {path}", response, name, was_published)
            if name == "edit":
                assert _model("knowledge.Article").objects.get(pk=article.pk).version_no == version_before + 1, \
                    "правка должна добавить версию"
        else:
            _expect(f"{name} {path}", response, want)
            if stay:
                assert _snap(article) == before, f"{name}: отказ не должен менять базу"


def _manage_actions(article, trashed: bool) -> list[tuple[str, str, dict]]:
    base = f"/kb/{article.pk}/"
    return [("trash", base + "trash/", {}), ("restore", base + "restore/", {}), ("purge", base + "purge/", {}),
            ("version_delete", base + "versions/1/delete/", {})] if not trashed else \
           [("trash", base + "trash/", {}), ("restore", base + "restore/", {}), ("purge", base + "purge/", {})]


def _manage_pages() -> list[str]:
    return ["/kb/trash/", "/kb/settings/", "/kb/rubrics/"]


def _rubric_posts(rubric) -> list[tuple[str, str, dict]]:
    return [("rubric_new", "/kb/rubrics/new/", {"name": "Новая рубрика теста", "parent": ""}),
            ("rubric_rename", f"/kb/rubrics/{rubric.pk}/rename/", {"name": "Другое название"}),
            ("rubric_move", f"/kb/rubrics/{rubric.pk}/move/", {"parent": ""}),
            ("rubric_delete", f"/kb/rubrics/{rubric.pk}/delete/", {}),
            ("settings", "/kb/settings/", {"trash_days": "30"})]


def _rubric_state() -> tuple:
    names = sorted(_model("knowledge.Rubric").objects.values_list("name", "parent_id"))
    return tuple(names), _model("knowledge.KnowledgeSettings").objects.get(pk=1).trash_days


def _login_redirect(response) -> bool:
    return response.status_code == 302 and response["Location"].startswith("/login/") and "next=" in response["Location"]


# --- FR-405: меню и вход ---------------------------------------------------------------------------------

def test_menu_item_knowledge_visible_to_every_employee_with_empty_permissions_order_7_without_badge():
    """FR-405: пункт «База знаний» — `menu_items` с пустыми `permissions`, видим любому вошедшему сотруднику, `order` 7
    (решение 10 задач), без `badge`; в левом меню страницы он есть и у читателя, и у менеджера."""
    from apps.core import extensions
    from apps.core.services import permissions

    described = [item for func in extensions.registered("menu_items") for item in func()
                 if item.get("title") == "База знаний"]
    assert len(described) == 1, f"ждали одно описание пункта «База знаний», нашли {len(described)}"
    item = described[0]
    assert tuple(item["permissions"]) == () and item["url"] == "/kb/" and item["order"] == 7
    assert "badge" not in item, "у пункта «База знаний» нет значка"
    reader, manager = kb.as_reader(), kb.as_manager()
    assert callable(item.get("visible")) and item["visible"](reader.user) is True and item["visible"](manager.user) is True
    for who in (reader, manager):
        entries = [entry for entry in permissions.menu_for(_fresh(who.user)) if entry["title"] == "База знаний"]
        assert len(entries) == 1 and entries[0]["url"] == "/kb/" and entries[0]["order"] == 7
        assert "badge" not in entries[0]
        page = who.client.get("/kb/")
        assert page.status_code == 200
        nav = re.search(r'<nav[^>]*id="main-menu".*?</nav>', _html(page), re.S)
        assert nav and 'href="/kb/"' in nav.group(0), "в левом меню нет ссылки на /kb/"


def test_requester_cannot_enter_portal_or_open_kb_urls():
    """FR-405: заявитель в портал не входит (общий отказ входа, как у неизвестного адреса) и статьи не видит: адреса
    базы знаний и поиска ведут его на страницу входа, ни заголовка, ни текста статьи в ответе нет."""
    article = _published(title="Заголовок для заявителя", text="Текст не для заявителя")
    requester = sd.make_requester()
    assert not _model("core.User").objects.filter(email=requester.email).exists()
    entered = support.factories.new_password()
    unknown = support.make_client().post("/login/", {"email": support.factories.new_email("none"), "password": entered})
    client = support.make_client()
    response = client.post("/login/", {"email": requester.email, "password": entered})
    assert response.status_code == 200 and support.same_failure(response, unknown)
    for path in ("/kb/", f"/kb/{article.pk}/", "/kb/new/", f"/kb/{article.pk}/history/", "/search/?q=statya",
                 "/kb/pick/?q=zagolovok"):
        got = client.get(path)
        assert _login_redirect(got), f"{path}: {got.status_code} {got.get('Location')}"
        assert article.title not in _html(got) and article.text not in _html(got)
    posted = client.post(f"/kb/{article.pk}/comments/", {"text": "Комментарий заявителя"})
    assert _login_redirect(posted)
    assert not _model("core.Comment").objects.filter(object_ref=f"knowledge.article:{article.pk}").exists()


def test_anonymous_redirected_to_login_on_all_kb_urls():
    """FR-409: без входа все адреса базы знаний и поиска (GET и POST, любое состояние статьи, в том числе
    несуществующей) — 302 на `/login/` с `next`, в базе ничего не меняется."""
    published = _published()
    draft = kb.make_draft()
    trashed = kb.make_trashed()
    missing = published.pk + 1000
    file_row = kb.attach_file(published, "схема.png")
    comment = kb.make_comment(published)
    link = kb.link_ticket(published, 4101)
    rubric = published.rubric
    gets = ["/kb/", "/kb/new/", "/kb/trash/", "/kb/settings/", "/kb/rubrics/", f"/kb/rubrics/{rubric.pk}/",
            "/kb/tags/?name=vpn", "/kb/tags/suggest/?q=v", "/kb/pick/?q=vp", "/search/?q=vpn", "/search/popup/?q=vpn",
            "/search/count/?q=vpn&group=articles", "/search/more/?q=vpn&group=articles&offset=0",
            f"/kb/{published.pk}/files/{file_row.pk}/", f"/kb/{published.pk}/images/{file_row.pk}/"]
    for article in (published, draft, trashed):
        gets += kb.article_pages(article)
    gets += [f"/kb/{missing}/", f"/kb/{missing}/edit/", f"/kb/{missing}/history/"]
    posts = [("/kb/new/", {"title": "Заголовок", "text": "Текст", "rubric": rubric.pk, "tags": ""}),
             ("/kb/preview/", {"text": "Текст"}), ("/kb/links/", {"article": published.pk, "ticket": 4101}),
             (f"/kb/links/{link.pk}/delete/", {}), ("/kb/from-ticket/4101/", {}),
             (f"/kb/comments/{comment.pk}/delete/", {}), (f"/kb/rubrics/{rubric.pk}/subscribe/", {})]
    posts += [(path, data) for _name, path, data in _rubric_posts(rubric)]  # тройки → пары (путь, поля)
    for article in (published, draft, trashed, None):
        number = article.pk if article is not None else missing
        base = f"/kb/{number}/"
        posts += [(base + "edit/", {"title": "Заголовок", "text": "Текст", "rubric": rubric.pk, "base_version": 1}),
                  (base + "publish/", {"base_version": 1}), (base + "trash/", {}), (base + "restore/", {}),
                  (base + "purge/", {}), (base + "versions/1/restore/", {}), (base + "versions/1/delete/", {}),
                  (base + "files/", {}), (base + f"files/{file_row.pk}/delete/", {}), (base + "comments/", {"text": "Т"})]
    anonymous = support.make_client()
    totals = (_model("knowledge.Article").objects.count(), _model("core.Comment").objects.count(), _rubric_state())
    for path in gets:
        got = anonymous.get(path)
        assert _login_redirect(got), f"GET {path}: {got.status_code} {got.get('Location')}"
    for path, data in posts:
        got = anonymous.post(path, data)
        assert _login_redirect(got), f"POST {path}: {got.status_code} {got.get('Location')}"
    assert totals == (_model("knowledge.Article").objects.count(), _model("core.Comment").objects.count(),
                      _rubric_state()), "запросы без входа ничего не меняют"


# --- FR-407, FR-409: матрица «действие × роль» -----------------------------------------------------------

def test_access_matrix_reader_without_rights():
    """FR-407, FR-409: читатель (без прав базы знаний) читает главную, рубрику, тег, подбор, поиск и опубликованную
    статью с историей, сравнением и версией; создание, правка, публикация, вложения, предпросмотр, подсказка тегов,
    корзина, срок, рубрики — 403, в базе ничего не меняется (контракт 10.7)."""
    reader = kb.as_reader()
    article = _published(title="Статья для читателя")
    rubric = article.rubric
    for path in ("/kb/", f"/kb/rubrics/{rubric.pk}/", "/kb/tags/?name=vpn", "/kb/pick/?q=vp", "/search/?q=vpn"):
        assert reader.client.get(path).status_code == 200, path
    for path in _read_pages(article):
        assert reader.client.get(path).status_code == 200, path
    new_before = _model("knowledge.Article").objects.count()
    assert reader.client.get("/kb/new/").status_code == 403
    assert reader.client.post("/kb/new/", {"title": "Заголовок", "text": "Текст", "rubric": rubric.pk,
                                           "tags": ""}).status_code == 403
    assert _model("knowledge.Article").objects.count() == new_before
    assert reader.client.get(f"/kb/{article.pk}/edit/").status_code == 403
    _run_actions(reader, article, 403)
    assert reader.client.post("/kb/preview/", {"text": "Текст"}).status_code == 403
    assert reader.client.get("/kb/tags/suggest/?q=v").status_code == 403
    before, rubric_before = _snap(article), _rubric_state()
    for name, path, data in _manage_actions(article, trashed=False) + _rubric_posts(rubric):
        _expect(f"{name} {path}", reader.client.post(path, data), 403)
    for path in _manage_pages():
        _expect(path, reader.client.get(path), 403)
    assert _snap(article) == before and _rubric_state() == rubric_before


def test_access_matrix_editor():
    """FR-406, FR-407, FR-409: «Редактирование» — создаёт статью (302 на правку, черновик у автора), правит чужую
    опубликованную и свой черновик, пользуется предпросмотром и подсказкой тегов; корзина, срок, рубрики,
    удаление версии — 403; чужой черновик — 404; статья в корзине — 410 и «Статья удалена» на POST."""
    editor = kb.as_editor()
    rubric = kb.general_rubric()
    created_before = set(_model("knowledge.Article").objects.values_list("pk", flat=True))
    assert editor.client.get("/kb/new/").status_code == 200
    made = editor.client.post("/kb/new/", {"title": "Статья редактора", "text": "Текст редактора",
                                           "rubric": rubric.pk, "tags": "vpn"})
    new_ids = set(_model("knowledge.Article").objects.values_list("pk", flat=True)) - created_before
    assert len(new_ids) == 1, "создана одна статья"
    new = _model("knowledge.Article").objects.get(pk=new_ids.pop())
    assert (new.state, new.author_id) == ("draft", editor.user.pk)
    assert made.status_code == 302 and made["Location"] == f"/kb/{new.pk}/edit/"
    assert editor.client.post("/kb/preview/", {"text": "Текст", "article": ""}).status_code == 200
    assert editor.client.get("/kb/tags/suggest/?q=v").status_code == 200
    foreign = _published()
    for path in _read_pages(foreign):
        assert editor.client.get(path).status_code == 200, path
    assert editor.client.get(f"/kb/{foreign.pk}/edit/").status_code == 200
    _run_actions(editor, foreign, "ok")
    own_draft = kb.make_draft(author=editor.user)
    kb.add_version(own_draft, text="Вторая версия черновика")
    for path in _read_pages(own_draft) + [f"/kb/{own_draft.pk}/edit/"]:
        assert editor.client.get(path).status_code == 200, path
    _run_actions(editor, own_draft, "ok")
    published = _published()
    before, rubric_before = _snap(published), _rubric_state()
    for name, path, data in _manage_actions(published, trashed=False) + _rubric_posts(published.rubric):
        _expect(f"{name} {path}", editor.client.post(path, data), 403)
    for path in _manage_pages():
        _expect(path, editor.client.get(path), 403)
    assert _snap(published) == before and _rubric_state() == rubric_before
    foreign_draft = kb.make_draft()
    for path in kb.article_pages(foreign_draft):
        assert editor.client.get(path).status_code == 404, path
    trashed_row = kb.make_trashed(title="В корзине у редактора")
    for path in kb.article_pages(trashed_row):
        assert editor.client.get(path).status_code == 410, path
    _run_actions(editor, trashed_row, "gone")


def test_access_matrix_manager():
    """FR-406, FR-407, FR-409: «Управление» — всё, что у редактора; чужие черновики и корзина (страница статьи; правка
    ведёт на страницу статьи); в корзину, возврат, удаление навсегда, удаление версии, срок и рубрики — успешно;
    POST правки и прочих действий над статьёй в корзине — 200 «Статья удалена»."""
    manager = kb.as_manager()
    published = _published()
    for path in _read_pages(published) + [f"/kb/{published.pk}/edit/"] + _manage_pages() + ["/kb/new/"]:
        assert manager.client.get(path).status_code == 200, path
    _run_actions(manager, published, "ok")
    foreign_draft = kb.make_draft()
    kb.add_version(foreign_draft, text="Вторая версия")
    for path in kb.article_pages(foreign_draft):
        assert manager.client.get(path).status_code == 200, path
    _run_actions(manager, foreign_draft, "ok")
    target = _published()
    base = f"/kb/{target.pk}/"
    response = manager.client.post(base + "trash/")
    assert response.status_code == 302 and response["Location"] == base
    assert _model("knowledge.Article").objects.get(pk=target.pk).state == "trash"
    for path in _read_pages(target):
        assert manager.client.get(path).status_code == 200, path
    edit = manager.client.get(base + "edit/")
    assert edit.status_code == 302 and edit["Location"] == base
    _run_actions(manager, target, "gone")
    again = manager.client.post(base + "trash/")
    assert _gone_alert(again)
    response = manager.client.post(base + "restore/")
    assert response.status_code == 302 and response["Location"] == base
    assert _model("knowledge.Article").objects.get(pk=target.pk).state == "published"
    assert manager.client.post(base + "versions/1/delete/").status_code == 302
    assert not _model("knowledge.ArticleVersion").objects.filter(article=target, number=1).exists()
    manager.client.post(base + "trash/")
    response = manager.client.post(base + "purge/")
    assert response.status_code == 302 and response["Location"] == "/kb/trash/"
    assert not _model("knowledge.Article").objects.filter(pk=target.pk).exists()
    rubric = kb.make_rubric("Рубрика менеджера")
    made = manager.client.post("/kb/rubrics/new/", {"name": "Создана менеджером", "parent": ""})
    assert made.status_code == 302 and made["Location"] == "/kb/rubrics/"
    assert _model("knowledge.Rubric").objects.filter(name="Создана менеджером").exists()
    assert manager.client.post(f"/kb/rubrics/{rubric.pk}/rename/", {"name": "Переименована"}).status_code == 302
    assert manager.client.post(f"/kb/rubrics/{rubric.pk}/delete/").status_code == 302
    saved = manager.client.post("/kb/settings/", {"trash_days": "45"})
    assert saved.status_code == 302 and saved["Location"] == "/kb/settings/"
    assert _model("knowledge.KnowledgeSettings").objects.get(pk=1).trash_days == 45


def test_access_matrix_draft_author_without_edit_right():
    """FR-407, FR-409: автор, потерявший «Редактирование», свой черновик не видит так же, как читатель: все адреса
    страниц и POST — 404, главная без блока «Мои черновики»; менеджеру черновик доступен; свою опубликованную статью
    автор только читает (правка — 403)."""
    author = kb.as_reader()
    draft = kb.make_draft(author=author.user, title="Черновик автора без права")
    kb.add_version(draft, text="Вторая версия")
    published = _published(author=author.user)
    for path in kb.article_pages(draft):
        assert author.client.get(path).status_code == 404, path
    _run_actions(author, draft, 404)
    home = author.client.get("/kb/")
    assert home.status_code == 200 and draft.title not in _html(home)
    assert _q(_tree(home), None, data_kb_my_drafts=True) == []
    assert author.client.get(f"/kb/{published.pk}/").status_code == 200
    assert author.client.get(f"/kb/{published.pk}/edit/").status_code == 403
    assert author.client.get("/kb/new/").status_code == 403
    manager = kb.as_manager()
    for path in kb.article_pages(draft):
        assert manager.client.get(path).status_code == 200, path


def test_access_matrix_fired_author_draft():
    """FR-407, FR-409: черновик уволенного автора читатель и редактор не видят (404 на страницах и POST), менеджер
    видит и правит (200 на страницах, правка проходит)."""
    fired = support.make_employee(state="dismissed")
    draft = kb.make_draft(author=fired, title="Черновик уволенного")
    kb.add_version(draft, text="Вторая версия")
    for who in (kb.as_reader(), kb.as_editor()):
        for path in kb.article_pages(draft):
            assert who.client.get(path).status_code == 404, path
        _run_actions(who, draft, 404)
    manager = kb.as_manager()
    for path in kb.article_pages(draft):
        assert manager.client.get(path).status_code == 200, path
    _run_actions(manager, draft, "ok")


def test_access_matrix_foreign_draft():
    """FR-407, FR-409: чужой черновик — читателю и редактору 404 на всех адресах страниц, действий и выдачи файлов,
    менеджеру — 200 или 302 (контракт 10.7, строки 744, 749)."""
    draft = kb.make_draft(title="Чужой черновик матрицы")
    kb.add_version(draft, text="Вторая версия")
    file_row = kb.attach_file(draft, "схема.png")
    for who in (kb.as_reader(), kb.as_editor()):
        for path in list(kb.article_pages(draft)) + [f"/kb/{draft.pk}/files/{file_row.pk}/",
                                                     f"/kb/{draft.pk}/images/{file_row.pk}/"]:
            assert who.client.get(path).status_code == 404, path
        _run_actions(who, draft, 404)
        comment = who.client.post(f"/kb/{draft.pk}/comments/", {"text": "Комментарий"})
        assert comment.status_code == 404
        assert not _model("core.Comment").objects.filter(object_ref=f"knowledge.article:{draft.pk}").exists()
    manager = kb.as_manager()
    for path in kb.article_pages(draft):
        assert manager.client.get(path).status_code == 200, path
    _run_actions(manager, draft, "ok")


def test_access_matrix_trashed_article_old_link():
    """FR-409: статья в корзине по старой ссылке (опубликованная и бывший черновик) — читателю и редактору 410
    без заголовка и текста на страницах, 404 на файлах и картинках, «Статья удалена» на любом POST (в том числе
    «Вернуть» и «Удалить навсегда» — решение Opus), состояние не меняется; менеджеру — страница; несуществующий номер —
    404; без входа — вход."""
    for was in ("published", "draft"):
        article = kb.make_trashed(was=was, title=f"Заголовок корзины {was}", text=f"Текст корзины {was}")
        kb.add_version(article, text=f"Текст корзины {was}, вторая версия")
        file_row = kb.attach_file(article, "схема.png")
        for who in (kb.as_reader(), kb.as_editor()):
            for path in kb.article_pages(article):
                got = who.client.get(path)
                assert got.status_code == 410, f"{path}: {got.status_code}"
                assert GONE in _html(got) and article.title not in _html(got) and article.text not in _html(got)
            for path in (f"/kb/{article.pk}/files/{file_row.pk}/", f"/kb/{article.pk}/images/{file_row.pk}/"):
                assert who.client.get(path).status_code == 404, path
            _run_actions(who, article, "gone")
            before = _snap(article)
            for name, path, data in _manage_actions(article, trashed=True):
                got = who.client.post(path, data)
                assert _gone_alert(got), f"{name}: {got.status_code}"
            got = who.client.post(f"/kb/{article.pk}/comments/", {"text": "Комментарий"})
            assert _gone_alert(got)
            assert _snap(article) == before, "действия не-управляющего над статьёй в корзине ничего не меняют"
        missing = who.client.get(f"/kb/{article.pk + 1000}/")
        assert missing.status_code == 404, "несуществующий номер — 404, не 410"
        manager = kb.as_manager()
        for path in kb.article_pages(article):
            got = manager.client.get(path)
            if path.endswith("/edit/"):
                assert got.status_code == 302 and got["Location"] == f"/kb/{article.pk}/"
            else:
                assert got.status_code == 200, f"{path}: {got.status_code}"
        assert _login_redirect(support.make_client().get(f"/kb/{article.pk}/"))


def test_inaccessible_object_response_equals_nonexistent():
    """FR-409: чужой черновик у читателя и редактора даёт тот же ответ, что и несуществующая статья: код 404 на
    страницах и POST, а в теле нет заголовка и текста черновика."""
    draft = kb.make_draft(title="Заголовок скрытого черновика", text="Текст скрытого черновика")
    kb.add_version(draft, text="Текст скрытого черновика, вторая версия")
    missing = draft.pk + 1000
    suffixes = ["", "edit/", "history/", "compare/?v=1&v=2", "versions/1/", "files/1/", "images/1/"]
    posts = [("edit/", {"title": "Заголовок", "text": "Текст", "rubric": draft.rubric_id, "base_version": 1}),
             ("publish/", {"base_version": 1}), ("versions/1/restore/", {}), ("comments/", {"text": "Комментарий"}),
             ("files/1/delete/", {})]
    for who in (kb.as_reader(), kb.as_editor()):
        for suffix in suffixes:
            real = who.client.get(f"/kb/{draft.pk}/{suffix}")
            absent = who.client.get(f"/kb/{missing}/{suffix}")
            assert real.status_code == absent.status_code == 404, f"GET {suffix}: {real.status_code}/{absent.status_code}"
            assert draft.title not in _html(real) and "Текст скрытого" not in _html(real)
        for suffix, data in posts:
            real = who.client.post(f"/kb/{draft.pk}/{suffix}", data)
            absent = who.client.post(f"/kb/{missing}/{suffix}", data)
            assert real.status_code == absent.status_code == 404, f"POST {suffix}: {real.status_code}/{absent.status_code}"
            assert draft.title not in _html(real)


# --- FR-407, FR-409: видимость -----------------------------------------------------------------------------

def test_visible_articles_set_per_role():
    """FR-407, FR-409: `access.visible_articles` — читатель: опубликованные; редактор: плюс свои черновики; менеджер:
    плюс все черновики (в том числе уволенного автора); корзина не входит ни у кого, и у менеджера тоже."""
    from apps.knowledge.services import access

    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()
    fired = support.make_employee(state="dismissed")
    published = kb.make_published()
    own_draft = kb.make_draft(author=editor.user)
    foreign_draft = kb.make_draft()
    fired_draft = kb.make_draft(author=fired)
    trashed_published = kb.make_trashed(was="published")
    trashed_draft = kb.make_trashed(was="draft", author=editor.user)

    def seen(who):
        return set(access.visible_articles(_fresh(who.user)).values_list("pk", flat=True))

    assert seen(reader) == {published.pk}
    assert seen(editor) == {published.pk, own_draft.pk}
    assert seen(manager) == {published.pk, own_draft.pk, foreign_draft.pk, fired_draft.pk}
    for who in (reader, editor, manager):
        assert not seen(who) & {trashed_published.pk, trashed_draft.pk}
    lost = kb.as_reader()
    kb.make_draft(author=lost.user)
    assert seen(lost) == {published.pk}, "автор без права «Редактирование» своих черновиков не видит"


def test_reader_sees_no_edit_buttons_but_history_and_compare():
    """FR-407, FR-409: на странице статьи читатель видит «История», но не «Править», «Опубликовать» и «В корзину»;
    на главной нет «Новая статья» и «Корзина»; история и сравнение доступны; у редактора и менеджера кнопки есть
    (иначе отсутствие у читателя ничего не доказывает)."""
    article = _published(title="Статья для кнопок")
    draft = kb.make_draft(title="Черновик для кнопок")
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()

    def marks(who, target):
        root = _tree(who.client.get(f"/kb/{target.pk}/"))
        return {"edit": bool(_q(root, "a", data_action="kb-edit")),
                "publish": bool(_q(root, "form", data_form="kb-publish")),
                "trash": bool(_q(root, "form", data_form="kb-trash")),
                "history": bool(_q(root, "a", data_action="kb-history"))}

    assert marks(reader, article) == {"edit": False, "publish": False, "trash": False, "history": True}
    assert marks(editor, article) == {"edit": True, "publish": False, "trash": False, "history": True}
    assert marks(manager, article) == {"edit": True, "publish": False, "trash": True, "history": True}
    assert marks(manager, draft) == {"edit": True, "publish": True, "trash": True, "history": True}
    home = _tree(reader.client.get("/kb/"))
    assert not _q(home, "a", data_action="kb-new-article") and not _q(home, "a", data_action="kb-trash-link")
    for who, new_link, trash_link in ((editor, True, False), (manager, True, True)):
        root = _tree(who.client.get("/kb/"))
        assert bool(_q(root, "a", data_action="kb-new-article")) is new_link
        assert bool(_q(root, "a", data_action="kb-trash-link")) is trash_link
    history = reader.client.get(f"/kb/{article.pk}/history/")
    assert history.status_code == 200 and _q(_tree(history), "form", data_form="kb-compare")
    compare = reader.client.get(f"/kb/{article.pk}/compare/?v=1&v=2")
    assert compare.status_code == 200 and _q(_tree(compare), None, data_kb_diff=True)


# --- FR-407, FR-408: правка и публикация --------------------------------------------------------------------

def test_editor_edits_foreign_published_article():
    """FR-407: редактор правит чужую опубликованную статью как вики: форма открывается, сохранение даёт 302 на статью
    и новую версию, автор статьи прежний, правил редактор."""
    editor = kb.as_editor()
    article = _published(title="Чужая опубликованная")
    author_id, before_no = article.author_id, article.version_no
    form = editor.client.get(f"/kb/{article.pk}/edit/")
    assert form.status_code == 200 and _q(_tree(form), "form", data_form="kb-article")
    response = editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(article, text="Новый текст редактора"))
    assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/"
    current = _model("knowledge.Article").objects.get(pk=article.pk)
    assert current.version_no == before_no + 1 and current.text == "Новый текст редактора"
    assert (current.author_id, current.updated_by_id, current.state) == (author_id, editor.user.pk, "published")
    version = _model("knowledge.ArticleVersion").objects.get(article=current, number=before_no + 1)
    assert version.author_id == editor.user.pk and version.text == "Новый текст редактора"


def test_editor_foreign_draft_and_trash_denied():
    """FR-407, FR-409: редактору чужой черновик недоступен (404 на странице, правке, публикации), статья в корзине —
    410 на страницах и «Статья удалена» на POST (решение Opus); состояние в базе не меняется, в видимых статьях их нет."""
    from apps.knowledge.services import access

    editor = kb.as_editor()
    draft = kb.make_draft(title="Чужой черновик редактору")
    trashed = kb.make_trashed(title="Корзина редактору")
    before_draft, before_trash = _snap(draft), _snap(trashed)
    assert editor.client.get(f"/kb/{draft.pk}/").status_code == 404
    assert editor.client.get(f"/kb/{draft.pk}/edit/").status_code == 404
    assert editor.client.post(f"/kb/{draft.pk}/edit/", _edit_data(draft)).status_code == 404
    assert editor.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1}).status_code == 404
    assert editor.client.get(f"/kb/{trashed.pk}/").status_code == 410
    for path, data in ((f"/kb/{trashed.pk}/edit/", _edit_data(trashed)), (f"/kb/{trashed.pk}/publish/", {"base_version": 1}),
                       (f"/kb/{trashed.pk}/restore/", {}), (f"/kb/{trashed.pk}/purge/", {})):
        got = editor.client.post(path, data)
        assert _gone_alert(got), f"{path}: {got.status_code}"
    assert _snap(draft) == before_draft and _snap(trashed) == before_trash
    seen = set(access.visible_articles(_fresh(editor.user)).values_list("pk", flat=True))
    assert draft.pk not in seen and trashed.pk not in seen


def test_invalid_form_on_foreign_draft_or_article_without_right_reveals_nothing():
    """FR-407, FR-409 (проверка безопасности 2026-10-23): служба проверяет поля формы раньше права (CONTRACT-005 B-3),
    но ответ на неверную форму не должен выдавать чужую статью: чужой черновик и несуществующий номер — 404 без имён
    вложений, номера версии и заголовка; опубликованная статья у сотрудника без права — 403; у редактора с правом —
    отказ у поля, как прежде."""
    reader, editor = kb.as_reader(), kb.as_editor()
    draft = kb.make_draft(title="Скрытый черновик для проверки")
    kb.attach_file(draft, name="секретный-план-закупок.png")
    published = kb.make_published(title="Опубликованная для проверки формы")
    kb.attach_file(published, name="вложение-опубликованной.txt")
    before = _snap(draft)
    for who in (reader, editor):
        for action in ("save", "publish"):
            got = who.client.post(f"/kb/{draft.pk}/edit/", _edit_data(draft, title="", action=action))
            assert got.status_code == 404, (action, got.status_code)
            body = got.content.decode()
            assert "секретный-план-закупок" not in body and "Скрытый черновик" not in body
        missing = who.client.post("/kb/99999999/edit/", _edit_data(draft, title=""))
        assert missing.status_code == 404
    denied = reader.client.post(f"/kb/{published.pk}/edit/", _edit_data(published, title=""))
    assert denied.status_code == 403 and "вложение-опубликованной" not in denied.content.decode()
    allowed = editor.client.post(f"/kb/{published.pk}/edit/", _edit_data(published, title=""))
    assert allowed.status_code == 200 and 'data-error="title"' in allowed.content.decode()
    assert _snap(draft) == before


def test_author_lost_edit_right_draft_denied_manager_publishes():
    """FR-407, FR-408: автор, потерявший «Редактирование», получает 404 на свой черновик и на публикацию; менеджер
    публикует его: статья `published`, `published_at` поставлен, версия не добавляется (текст не менялся, FR-410)."""
    author = kb.as_editor()
    draft = kb.make_draft(author=author.user, title="Черновик потерявшего право")
    assert author.client.get(f"/kb/{draft.pk}/").status_code == 200
    role = author.user.roles.first()
    author.user.roles.remove(role)
    from django.core.cache import cache

    from apps.core.services import permissions

    cache.delete(permissions._key(author.user.pk))
    assert author.client.get(f"/kb/{draft.pk}/").status_code == 404
    assert author.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1}).status_code == 404
    assert _model("knowledge.Article").objects.get(pk=draft.pk).state == "draft"
    manager = kb.as_manager()
    page = _tree(manager.client.get(f"/kb/{draft.pk}/"))
    assert _q(page, "form", data_form="kb-publish"), "менеджеру показана кнопка «Опубликовать»"
    response = manager.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1})
    assert response.status_code == 302 and response["Location"] == f"/kb/{draft.pk}/"
    current = _model("knowledge.Article").objects.get(pk=draft.pk)
    assert current.state == "published" and current.published_at is not None and current.version_no == 1
    assert _model("knowledge.ArticleVersion").objects.filter(article=current).count() == 1


def test_manager_sees_drafts_trash_edits_rubrics_deletes_foreign_comment():
    """FR-406, FR-407: менеджер видит на главной чужие черновики и ссылку «Корзина», открывает корзину, правит
    рубрики и удаляет чужой комментарий (комментарий исчезает), а у редактора такого права нет (403, комментарий
    остаётся)."""
    manager, editor = kb.as_manager(), kb.as_editor()
    draft = kb.make_draft(title="Чужой черновик менеджеру")
    trashed = kb.make_trashed(title="Статья в корзине менеджера")
    article = kb.make_published()
    comment = kb.make_comment(article, author=editor.user, text="Комментарий редактора")
    home = _tree(manager.client.get("/kb/"))
    assert draft.pk in _ids(_q(home, None, data_kb_all_drafts=True)[0])
    assert _q(home, "a", data_action="kb-trash-link")
    page = manager.client.get("/kb/trash/")
    assert page.status_code == 200 and trashed.title in _html(page)
    made = manager.client.post("/kb/rubrics/new/", {"name": "Рубрика менеджера", "parent": ""})
    assert made.status_code == 302 and _model("knowledge.Rubric").objects.filter(name="Рубрика менеджера").exists()
    other = kb.as_editor()
    foreign = kb.make_comment(article, author=other.user, text="Чужой комментарий")
    assert editor.client.post(f"/kb/comments/{foreign.pk}/delete/").status_code == 403
    assert _model("core.Comment").objects.filter(pk=foreign.pk).exists()
    assert manager.client.post(f"/kb/comments/{foreign.pk}/delete/").status_code == 302
    assert not _model("core.Comment").objects.filter(pk=foreign.pk).exists()
    assert _model("core.Comment").objects.filter(pk=comment.pk).exists()


# --- FR-409: проверка на сервере -----------------------------------------------------------------------------

def test_direct_post_without_button_checked_on_server():
    """FR-409: кнопки нет — и право всё равно проверяется на сервере. У читателя на странице нет форм правки,
    публикации и корзины, прямой POST (обычный и НХ) — 403 и ничего не меняется; у редактора — 403 на корзину,
    удаление навсегда и удаление версии; чужой черновик — 404. POST без токена CSRF у менеджера — 403, статья остаётся.
    (CSRF здесь проверен по строке 662 контракта: отдельного теста у него нет — допущение исполнителя.)"""
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()
    article = _published()
    base = f"/kb/{article.pk}/"
    root = _tree(reader.client.get(base))
    assert not _q(root, "form", data_form="kb-trash") and not _q(root, "a", data_action="kb-edit")
    before = _snap(article)
    for path, data in ((base + "trash/", {}), (base + "edit/", _edit_data(article)), (base + "publish/", {"base_version": 2}),
                       (base + "versions/1/delete/", {}), (base + "purge/", {})):
        assert reader.client.post(path, data).status_code == 403, path
        assert reader.client.post(path, data, **HX).status_code == 403, f"НХ {path}"
    for path in (base + "trash/", base + "purge/", base + "versions/1/delete/"):
        assert editor.client.post(path).status_code == 403, path
    assert _snap(article) == before
    foreign_draft = kb.make_draft()
    assert editor.client.post(f"/kb/{foreign_draft.pk}/publish/", {"base_version": 1}).status_code == 404
    assert _model("knowledge.Article").objects.get(pk=foreign_draft.pk).state == "draft"
    strict = support.make_client(enforce_csrf_checks=True)
    strict.cookies = manager.client.cookies
    assert strict.post(base + "trash/").status_code == 403
    assert _snap(article) == before


def test_stale_button_recheck_in_service():
    """FR-409: кнопка могла устареть — службы проверяют право сами. После потери права `articles.publish` у автора
    черновика, `articles.trash` у бывшего менеджера и `articles.save` у бывшего редактора поднимают `PermissionDenied`
    (чужой или недоступный черновик — `Http404`), `access.get_for` — `Http404`, состояние статей не меняется."""
    from django.core.exceptions import PermissionDenied
    from django.http import Http404

    from apps.knowledge.services import access, articles

    author = kb.as_editor()
    draft = kb.make_draft(author=author.user)
    published = _published()
    assert access.can_change(_fresh(author.user), draft) is True and access.can_publish(_fresh(author.user), draft) is True
    author.user.roles.clear()
    gone = _fresh(author.user)
    assert access.can_edit(gone) is False and access.can_change(gone, draft) is False
    with pytest.raises(Http404):
        articles.publish(gone, draft.pk, 1)
    with pytest.raises(Http404):
        access.get_for(gone, draft.pk)
    form = articles.ArticleForm(title=published.title, text="Правка без права", rubric_id=published.rubric_id, tags="vpn")
    with pytest.raises(PermissionDenied):
        articles.save(gone, published.pk, published.version_no, form)
    assert _snap(draft)[0] == "draft"
    manager = kb.as_manager()
    manager.user.roles.clear()
    with pytest.raises(PermissionDenied):
        articles.trash(_fresh(manager.user), published.pk)
    current = _model("knowledge.Article").objects.get(pk=published.pk)
    assert (current.state, current.version_no, current.text) == ("published", published.version_no, published.text)


# --- FR-406, FR-418: миграция данных knowledge 0002 --------------------------------------------------------

def _role(name: str):
    return _model("core.Role").objects.get(name=name, is_builtin=True)


def _codes(role) -> set:
    return set(role.permissions.values_list("code", flat=True))


def _wipe_seed_data() -> None:
    """Возвращает базу к виду «до миграции данных»: прав базы знаний, рубрики «Общее» и строки настроек нет.
    Тестовая база уже мигрирована, поэтому без этого проверка создания прошла бы вхолостую."""
    _model("core.Permission").objects.filter(code__in=kb.PERMISSIONS_005).delete()
    _model("knowledge.Rubric").objects.filter(is_default=True).delete()
    _model("knowledge.KnowledgeSettings").objects.all().delete()


def test_migration_0002_creates_permissions_general_rubric_and_settings_and_grants_builtin_roles_chief_gets_none():
    """FR-406, FR-418: `seed` создаёт права «Редактирование базы знаний» и «Управление базой знаний», рубрику «Общее»
    (корневая, глубина 1, по умолчанию), строку настроек (90 суток), выдаёт «Администратору портала» оба права,
    «Сотруднику ИТ» — редактирование, «Руководителю» — ничего; повторный вызов ничего не меняет, чужие заголовки и
    значения не перезаписывает. Вызов идёт на соединении `default` (допущение: см. отчёт T-5109)."""
    _wipe_seed_data()
    before = {name: _codes(_role(name)) for name in (ADMIN_ROLE, IT_ROLE, CHIEF_ROLE)}
    assert not any(code in codes for codes in before.values() for code in kb.PERMISSIONS_005)
    kb.run_seed(using="default")
    Permission = _model("core.Permission")
    for code, title in kb.TITLES_005.items():
        assert Permission.objects.get(code=code).title == title
    rubric = _model("knowledge.Rubric").objects.get(is_default=True)
    assert (rubric.name, rubric.parent_id, rubric.depth) == ("Общее", None, 1)
    settings_row = _model("knowledge.KnowledgeSettings").objects.get(pk=1)
    assert settings_row.trash_days == 90
    assert _codes(_role(ADMIN_ROLE)) == before[ADMIN_ROLE] | set(kb.PERMISSIONS_005)
    assert _codes(_role(IT_ROLE)) == before[IT_ROLE] | {"knowledge.edit"}
    assert _codes(_role(CHIEF_ROLE)) == before[CHIEF_ROLE], "«Руководитель» новых прав не получает"
    assert not any(code in _codes(_role(CHIEF_ROLE)) for code in kb.PERMISSIONS_005)
    Permission.objects.filter(code="knowledge.edit").update(title="Свой заголовок права")
    _model("knowledge.KnowledgeSettings").objects.filter(pk=1).update(trash_days=120)
    snapshot = ({name: _codes(_role(name)) for name in before}, Permission.objects.filter(code__in=kb.PERMISSIONS_005).count(),
                _model("knowledge.Rubric").objects.filter(is_default=True).count())
    kb.run_seed(using="default")
    assert snapshot == ({name: _codes(_role(name)) for name in before},
                        Permission.objects.filter(code__in=kb.PERMISSIONS_005).count(),
                        _model("knowledge.Rubric").objects.filter(is_default=True).count())
    assert Permission.objects.get(code="knowledge.edit").title == "Свой заголовок права"
    assert _model("knowledge.KnowledgeSettings").objects.get(pk=1).trash_days == 120
    assert _model("knowledge.KnowledgeSettings").objects.count() == 1


def test_migration_0002_adds_rights_to_existing_roles_keeps_prior():
    """FR-406: при обновлении портала права получают и уже существующие роли, а прежние права остаются
    (`add`, не `set`): у «Сотрудника ИТ» и «Администратора портала» прежний набор цел, добавлены только права базы знаний."""
    _wipe_seed_data()
    Permission = _model("core.Permission")
    prior = Permission.objects.get(code="audit.view")
    it_role, admin_role = _role(IT_ROLE), _role(ADMIN_ROLE)
    it_role.permissions.add(prior)
    it_before, admin_before = _codes(it_role), _codes(admin_role)
    assert "audit.view" in it_before
    kb.run_seed(using="default")
    assert _codes(_role(IT_ROLE)) == it_before | {"knowledge.edit"}
    assert _codes(_role(ADMIN_ROLE)) == admin_before | set(kb.PERMISSIONS_005)
    assert {"audit.view"} <= _codes(_role(IT_ROLE)) and {"audit.view"} <= _codes(_role(ADMIN_ROLE))


def test_migration_0002_without_it_role_passes():
    """FR-406: нет встроенной роли «Сотрудник ИТ» (переименована; одноимённая пользовательская роль встроенной не
    является) — миграция данных не падает и пропускает её; администратор права получает, пользовательская роль — нет."""
    _wipe_seed_data()
    Role = _model("core.Role")
    Role.objects.filter(name=IT_ROLE, is_builtin=True).update(name="Сотрудник ИТ (старая)")
    custom = Role.objects.create(name=IT_ROLE, is_builtin=False)
    kb.run_seed(using="default")
    assert _codes(Role.objects.get(name=ADMIN_ROLE, is_builtin=True)) >= set(kb.PERMISSIONS_005)
    assert _codes(Role.objects.get(pk=custom.pk)) == set(), "пользовательская роль не получает права"
    assert _model("core.Permission").objects.filter(code__in=kb.PERMISSIONS_005).count() == 2
    assert _model("knowledge.Rubric").objects.filter(is_default=True).count() == 1


def test_permission_granted_to_other_role_in_interface_without_code(django_capture_on_commit_callbacks):
    """FR-406: права базы знаний выдаются ролям в интерфейсе без кода: администратор создаёт роль с правом
    «Редактирование базы знаний» страницей ролей, сотрудник с этой ролью создаёт статьи, а после снятия права той же
    страницей — получает 403. Страница роли показывает названия обоих прав."""
    admin = support.logged_in(support.make_admin())
    page = admin.get("/roles/new/")
    assert page.status_code == 200
    for title in kb.TITLES_005.values():
        assert title in _html(page), f"на странице роли нет права «{title}»"
    with django_capture_on_commit_callbacks(execute=True):
        created = admin.post("/roles/new/", {"name": "Редакторы базы знаний", "permissions": ["knowledge.edit"]})
    assert created.status_code == 302
    role = _model("core.Role").objects.get(name="Редакторы базы знаний")
    assert _codes(role) == {"knowledge.edit"}
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        user.roles.add(role)
    _fresh(user)  # кэш прав сброшен; вход — исходным объектом: у перечитанного из базы нет `test_password`
    employee = support.logged_in(user)
    rubric = kb.general_rubric()
    assert employee.get("/kb/new/").status_code == 200
    made = employee.post("/kb/new/", {"title": "Статья по роли", "text": "Текст", "rubric": rubric.pk, "tags": ""})
    assert made.status_code == 302
    assert _model("knowledge.Article").objects.filter(title="Статья по роли", author=user).exists()
    assert employee.get("/kb/trash/").status_code == 403, "управления у роли нет"
    with django_capture_on_commit_callbacks(execute=True):
        changed = admin.post(f"/roles/{role.pk}/", {"name": "Редакторы базы знаний", "permissions": []})
    assert changed.status_code == 302
    assert employee.get("/kb/new/").status_code == 403


def test_fired_author_drafts_visible_and_publishable_by_manager():
    """FR-401, FR-407: черновик уволенного автора виден менеджеру (в списке «Черновики» главной) и публикуется им:
    на странице автор показан ФИО с пометкой «уволен»; публикация без правки даёт статью `published` без новой версии."""
    from apps.knowledge.services import access, articles

    fired = support.make_employee(state="dismissed", full_name="Уволенов Автор")
    draft = kb.make_draft(author=fired, title="Черновик уволенного автора")
    manager = kb.as_manager()
    assert draft.pk in set(access.visible_articles(_fresh(manager.user)).values_list("pk", flat=True))
    home = _tree(manager.client.get("/kb/"))
    assert draft.pk in _ids(_q(home, None, data_kb_all_drafts=True)[0])
    page = _tree(manager.client.get(f"/kb/{draft.pk}/"))
    author_text = _q(page, None, data_field="author")[0].text()
    assert "Уволенов Автор" in author_text and "уволен" in author_text.replace("Уволенов", "")
    result = articles.publish(_fresh(manager.user), draft.pk, 1)
    assert result.kind == "saved" and result.version is None
    current = _model("knowledge.Article").objects.get(pk=draft.pk)
    assert (current.state, current.version_no, current.author_id) == ("published", 1, fired.pk)
    assert current.published_at is not None and current.updated_by_id == manager.user.pk
    assert _model("knowledge.ArticleVersion").objects.filter(article=current).count() == 1
