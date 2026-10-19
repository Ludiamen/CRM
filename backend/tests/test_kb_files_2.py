"""T-5115: файлы и картинки статьи — выдача, заглушки, право на статью (FR-422, FR-423, NFR-405).

Сценарии спеки «Вложения и картинки»: скачивание «чистого» файла и показ «чистой» картинки через `X-Accel-Redirect`,
остальные состояния проверки (адрес файла отвечает как несуществующий, адрес картинки — заглушкой `image/svg+xml`),
разметка `att:N` в готовом HTML, недоступная статья (чужой черновик, корзина), проверка права на каждый запрос.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка).
"""
import re
from html.parser import HTMLParser
from urllib.parse import unquote

import pytest

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

CHECKING = "проверяется"
REMOVED = "вложение удалено"
UNAVAILABLE = "недоступно"
SVG = "image/svg+xml"


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


def noimg_texts(scope) -> list[str]:
    return [node.text() for node in q(scope, "span", **{"class": "kb-noimg"})]


# --- помощники данных и ответов -------------------------------------------------------------------------

def _body(response) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


def _kind(response) -> str:
    return response["Content-Type"].split(";")[0].strip()


def _files_url(article, file) -> str:
    return f"/kb/{article.pk}/files/{file.pk}/"


def _image_url(article, file) -> str:
    return f"/kb/{article.pk}/images/{file.pk}/"


def _set_status(file, status: str) -> None:
    support.model("core.StoredFile").objects.filter(pk=file.file_id).update(status=status)
    file.file.refresh_from_db()


def _drop(file) -> None:
    """Вложение удалено: строки `ArticleFile` и `StoredFile` стёрты."""
    stored_id = file.file_id
    file.delete()
    support.model("core.StoredFile").objects.filter(pk=stored_id).delete()


def _rerender(article):
    """Пересчитывает `html` и `plain` статьи так, как это делает сохранение: `render.render` и `files.files_map`."""
    from apps.knowledge.services import files as kb_files
    from apps.knowledge.services import render

    out = render.render(article.text, kb_files.files_map(article), article.pk)
    article.html, article.plain = out.html, out.plain
    article.save(update_fields=["html", "plain"])
    return out


def _to_trash(article) -> None:
    from django.utils import timezone

    support.model("knowledge.Article").objects.filter(pk=article.pk).update(
        state="trash", state_before_trash="published", deleted_at=timezone.now(), deleted_by=article.author)


def _from_trash(article) -> None:
    support.model("knowledge.Article").objects.filter(pk=article.pk).update(
        state="published", state_before_trash="", deleted_at=None, deleted_by=None)


def _gone_session():
    """Сотрудник без прав базы знаний, вошедший в портал, — читатель."""
    return kb.as_reader()


def _same_as_missing(session, path: str, missing: str):
    """Ответ по `path` неотличим от ответа по несуществующему адресу `missing` (код, перенос, тело)."""
    first, second = session.client.get(path), session.client.get(missing)
    assert first.status_code == 404, f"{path}: {first.status_code}"
    assert support.same_failure(first, second), f"{path}: ответ отличается от ответа несуществующего"
    assert "X-Accel-Redirect" not in first and "X-KB-Placeholder" not in first


def _placeholder(response, state: str, text: str) -> None:
    assert response.status_code == 200, response.status_code
    assert _kind(response) == SVG, _kind(response)
    assert response["X-KB-Placeholder"] == state
    assert "X-Accel-Redirect" not in response
    svg = _body(response).decode("utf-8")
    texts = ["".join(re.sub(r"<[^>]+>", "", part).split()) for part in re.findall(r"<text\b[^>]*>(.*?)</text>", svg, re.S)]
    assert any("".join(text.split()) in found for found in texts), \
        f"в SVG заглушки нет элемента `<text>` со словом «{text}» (п. 19): {texts}"


# --- скачивание файла: /kb/<id>/files/<N>/ --------------------------------------------------------------

def test_download_clean_file_headers_x_accel_attachment_filename_star_nosniff_no_store():
    """FR-422: «чистый» файл — 200 без тела, `X-Accel-Redirect` в защищённый том, `attachment; filename*=UTF-8''…`,
    `application/octet-stream`, `nosniff`, `no-store` (3.5, 10.5)."""
    article = kb.make_published()
    file = kb.attach_file(article, "report.pdf", status="clean")
    reader = _gone_session()

    response = reader.client.get(_files_url(article, file))

    assert response.status_code == 200
    assert response.content == b""
    assert response["X-Accel-Redirect"] == f"/protected/attachments/{file.file_id}"
    disposition = response["Content-Disposition"]
    assert disposition.startswith("attachment;"), disposition
    assert "filename*=UTF-8''report.pdf" in disposition, disposition
    assert _kind(response) == "application/octet-stream"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]


def test_download_filename_star_keeps_cyrillic_name():
    """FR-422: имя файла с кириллицей, пробелом и «№» — в `filename*=UTF-8''` в процентной записи и без потерь."""
    article = kb.make_published()
    name = "Схема сети №1.pdf"
    file = kb.attach_file(article, name, status="clean")

    response = _gone_session().client.get(_files_url(article, file))

    assert response.status_code == 200
    disposition = response["Content-Disposition"]
    marker = "filename*=UTF-8''"
    assert marker in disposition, disposition
    encoded = disposition.split(marker, 1)[1].split(";", 1)[0].strip()
    assert encoded.isascii(), f"имя не в процентной записи: {encoded!r}"
    assert unquote(encoded) == name
    assert "Схема" not in disposition


def test_download_pending_file_not_served_as_missing():
    """FR-422: «проверяется» — файл не скачивается: ответ тот же, что у несуществующего вложения (10.5)."""
    article = kb.make_published()
    file = kb.attach_file(article, "report.pdf", status="pending")
    reader = _gone_session()

    _same_as_missing(reader, _files_url(article, file), f"/kb/{article.pk}/files/{file.pk + 100000}/")


def test_download_quarantined_file_not_served_as_missing():
    """FR-422: «карантин» — файл не скачивается: ответ тот же, что у несуществующего вложения (10.5)."""
    article = kb.make_published()
    file = kb.attach_file(article, "report.pdf", status="quarantine")
    reader = _gone_session()

    _same_as_missing(reader, _files_url(article, file), f"/kb/{article.pk}/files/{file.pk + 100000}/")


def test_download_removed_file_answers_as_missing():
    """FR-422: удалённое вложение и вложение другой статьи по адресу этой статьи — как несуществующее (10.5)."""
    article = kb.make_published()
    removed = kb.attach_file(article, "old.pdf", status="clean")
    other_article = kb.make_published()
    foreign = kb.attach_file(other_article, "foreign.pdf", status="clean")
    reader = _gone_session()
    missing = f"/kb/{article.pk}/files/{removed.pk + 100000}/"
    removed_url = _files_url(article, removed)
    assert reader.client.get(removed_url).status_code == 200  # пока вложение есть, файл выдаётся

    _drop(removed)

    _same_as_missing(reader, removed_url, missing)
    _same_as_missing(reader, f"/kb/{article.pk}/files/{foreign.pk}/", missing)


# --- показ картинки: /kb/<id>/images/<N>/ ---------------------------------------------------------------

def test_image_clean_served_type_from_image_format_without_content_disposition():
    """FR-423: «чистая» картинка — 200 без тела, `X-Accel-Redirect`, тип по `image_format`, без `Content-Disposition`,
    `nosniff`, `no-store` (3.5, 10.5)."""
    article = kb.make_published()
    file = kb.attach_file(article, "схема.png", status="clean")

    response = _gone_session().client.get(_image_url(article, file))

    assert response.status_code == 200
    assert response.content == b""
    assert response["X-Accel-Redirect"] == f"/protected/attachments/{file.file_id}"
    assert _kind(response) == "image/png"
    assert "Content-Disposition" not in response
    assert "X-KB-Placeholder" not in response
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]


def test_image_type_taken_from_image_format_not_from_name_or_browser():
    """FR-423: тип ответа — из `image_format` (по содержимому), а не из расширения имени и не из `content_type`
    строки `StoredFile` (то, что пришло от браузера)."""
    article = kb.make_published()
    reader = _gone_session()
    cases = [("png", "photo.jpg"), ("jpeg", "photo.png"), ("gif", "photo.webp"), ("webp", "photo.gif")]
    for image_format, name in cases:
        file = kb.attach_file(article, name, status="clean", image_format=image_format)
        support.model("core.StoredFile").objects.filter(pk=file.file_id).update(content_type="text/html")

        response = reader.client.get(_image_url(article, file))

        assert response.status_code == 200, f"{name}: {response.status_code}"
        assert _kind(response) == f"image/{image_format}", f"{name}: {_kind(response)}"
        assert "Content-Disposition" not in response


def test_image_pending_shows_checking_placeholder():
    """FR-423: «проверяется» — заглушка «проверяется»: 200 `image/svg+xml`, `X-KB-Placeholder: checking`, без файла."""
    article = kb.make_published()
    file = kb.attach_file(article, "схема.png", status="pending")

    response = _gone_session().client.get(_image_url(article, file))

    _placeholder(response, "checking", CHECKING)
    assert "no-store" in response["Cache-Control"]


def test_image_appears_after_scan_without_resaving_article(protected_root, monkeypatch,
                                                           django_capture_on_commit_callbacks):
    """FR-423: статья не пересохраняется — после проверки тот же адрес `<img>` начинает отдавать картинку, HTML,
    версия и время статьи не меняются (сценарий 5 п. 10)."""
    from apps.core import tasks

    article = kb.make_published()
    file = kb.attach_file(article, "схема.png", status="pending", write=True)
    article.text = f"![схема](att:{file.pk})"
    article.save(update_fields=["text"])
    _rerender(article)
    article.refresh_from_db()
    saved = (article.html, article.plain, article.version_no, article.updated_at)
    reader = _gone_session()
    url = _image_url(article, file)
    assert q1(tree(reader.client.get(f"/kb/{article.pk}/")), "img", src=url)
    _placeholder(reader.client.get(url), "checking", CHECKING)
    kb.scan_clean(monkeypatch)

    with django_capture_on_commit_callbacks(execute=True):
        tasks.scan_file(str(file.file_id))

    response = reader.client.get(url)
    assert response.status_code == 200
    assert response["X-Accel-Redirect"] == f"/protected/attachments/{file.file_id}"
    assert _kind(response) == "image/png"
    article.refresh_from_db()
    assert (article.html, article.plain, article.version_no, article.updated_at) == saved
    assert q1(tree(reader.client.get(f"/kb/{article.pk}/")), "img", src=url)


def test_image_quarantined_shows_unavailable_placeholder_not_picture():
    """FR-422, FR-423: карантин — заглушка «недоступно» (`X-KB-Placeholder: unavailable`), самой картинки нет."""
    article = kb.make_published()
    file = kb.attach_file(article, "схема.png", status="quarantine")

    response = _gone_session().client.get(_image_url(article, file))

    _placeholder(response, "unavailable", UNAVAILABLE)
    assert _kind(response) != "image/png"


def test_image_of_non_image_file_shows_unavailable_placeholder():
    """FR-423: вложение не картинка (`image_format` пуст, даже при имени `.png`) — заглушка «недоступно»."""
    article = kb.make_published()
    reader = _gone_session()
    for name in ("report.pdf", "fake.png"):
        file = kb.attach_file(article, name, status="clean", image_format="")

        response = reader.client.get(_image_url(article, file))

        _placeholder(response, "unavailable", UNAVAILABLE)


def test_image_of_removed_attachment_shows_attachment_removed_placeholder():
    """FR-423: строки `ArticleFile` с этим номером нет — заглушка «вложение удалено» (`X-KB-Placeholder: removed`)."""
    article = kb.make_published()
    file = kb.attach_file(article, "схема.png", status="clean")
    url = _image_url(article, file)
    reader = _gone_session()
    assert reader.client.get(url).status_code == 200
    _drop(file)

    response = reader.client.get(url)

    _placeholder(response, "removed", REMOVED)


# --- разметка att:N в готовом HTML ----------------------------------------------------------------------

def test_rendered_html_img_src_does_not_depend_on_scan_state():
    """FR-423: в готовом HTML адрес картинки один и тот же при `pending`, `clean` и `quarantine`; страница статьи
    показывает `img[src="/kb/<id>/images/<N>/"]` во всех трёх состояниях (6.1, 11.4)."""
    from apps.knowledge.services import files as kb_files
    from apps.knowledge.services import render

    article = kb.make_published()
    file = kb.attach_file(article, "схема.png", status="pending")
    article.text = f"Смотрите: ![схема](att:{file.pk})"
    article.save(update_fields=["text"])
    url = _image_url(article, file)
    reader = _gone_session()
    outputs = []
    for status in ("pending", "clean", "quarantine"):
        _set_status(file, status)
        outputs.append(render.render(article.text, kb_files.files_map(article), article.pk).html)
        _rerender(article)

        page = tree(reader.client.get(f"/kb/{article.pk}/"))

        body = q1(page, data_field="body")
        image = q1(body, "img")
        assert image.attrs["src"] == url, f"{status}: {image.attrs}"
    assert outputs[0] == outputs[1] == outputs[2]
    assert q1(tree(outputs[0]), "img").attrs["src"] == url


def test_att_markup_renders_image_and_file_link_for_own_attachment():
    """FR-423: `![имя](att:N)` своей статьи — `<img src="/kb/<id>/images/N/" alt="имя" loading="lazy">`;
    `[имя](att:N)` — `<a href="/kb/<id>/files/N/">имя</a>` без `rel` и `target` (6.1)."""
    from apps.knowledge.services import files as kb_files
    from apps.knowledge.services import render

    article = kb.make_published()
    picture = kb.attach_file(article, "схема.png", status="clean")
    document = kb.attach_file(article, "отчёт.pdf", status="clean")
    text = f"![схема сети](att:{picture.pk})\n\n[скачать отчёт](att:{document.pk})"

    html = render.render(text, kb_files.files_map(article), article.pk).html

    root = tree(html)
    image = q1(root, "img")
    assert image.attrs["src"] == _image_url(article, picture)
    assert image.attrs["alt"] == "схема сети"
    assert image.attrs["loading"] == "lazy"
    link = q1(root, "a")
    assert link.attrs["href"] == _files_url(article, document)
    assert link.text() == "скачать отчёт"
    assert "rel" not in link.attrs and "target" not in link.attrs
    assert noimg_texts(root) == []


def test_att_of_other_article_renders_text_placeholder_not_image():
    """FR-423, NFR-405: `att:N` чужой статьи — не картинка и не ссылка, а текст `[вложение недоступно: имя]`
    в `span.kb-noimg`; своя картинка в том же тексте остаётся картинкой."""
    from apps.knowledge.services import files as kb_files
    from apps.knowledge.services import render

    article = kb.make_published()
    own = kb.attach_file(article, "своя.png", status="clean")
    foreign = kb.attach_file(kb.make_published(), "чужая.png", status="clean")
    text = (f"![чужая](att:{foreign.pk})\n\n![своя](att:{own.pk})\n\n[доки](att:{foreign.pk})")

    html = render.render(text, kb_files.files_map(article), article.pk).html

    root = tree(html)
    assert [node.attrs["src"] for node in q(root, "img")] == [_image_url(article, own)]
    assert noimg_texts(root) == ["[вложение недоступно: чужая]", "[вложение недоступно: доки]"]
    assert q(root, "a") == []
    assert f"/images/{foreign.pk}/" not in html and f"/files/{foreign.pk}/" not in html
    assert f"att:{foreign.pk}" not in html


def test_external_image_url_renders_link_text_not_img():
    """FR-423, NFR-405: картинка по внешнему адресу — заглушка `[вложение недоступно: подпись]`, `img` нет и
    внешнего адреса в выводе нет (6.1)."""
    from apps.knowledge.services import render

    article = kb.make_published()
    address = "https://" + "example.test" + "/logo.png"

    html = render.render(f"![лого]({address})", {}, article.pk).html

    root = tree(html)
    assert q(root, "img") == []
    assert noimg_texts(root) == ["[вложение недоступно: лого]"]
    assert "example.test" not in html


def test_direct_kb_path_in_markup_renders_placeholder():
    """FR-423, NFR-405: прямой путь `/kb/…` в разметке картинки (даже путь картинки своей статьи) — заглушка,
    а не `img`: картинку можно показать только через `att:N`."""
    from apps.knowledge.services import files as kb_files
    from apps.knowledge.services import render

    article = kb.make_published()
    own = kb.attach_file(article, "схема.png", status="clean")
    text = f"![прямая]({_image_url(article, own)})\n\n![чужая](/kb/{article.pk + 1}/images/1/)"

    html = render.render(text, kb_files.files_map(article), article.pk).html

    root = tree(html)
    assert q(root, "img") == []
    assert noimg_texts(root) == ["[вложение недоступно: прямая]", "[вложение недоступно: чужая]"]


# --- недоступная статья и право -------------------------------------------------------------------------

def _article_with_both(**make):
    """Статья с чистыми файлом и картинкой и адреса `/kb/<id>/files/N/`, `/kb/<id>/images/N/`."""
    article = kb.make_article(**make)
    document = kb.attach_file(article, "report.pdf", status="clean")
    picture = kb.attach_file(article, "схема.png", status="clean")
    return article, [_files_url(article, document), _image_url(article, picture)]


def test_foreign_draft_files_and_images_answer_as_missing():
    """FR-422, FR-423: чужой черновик — 404 как у несуществующей статьи (не заглушка и не 410) для читателя,
    чужого редактора и автора, потерявшего право (10.7)."""
    author = support.make_employee()
    article, paths = _article_with_both(state="draft", author=author)
    missing = ["/kb/999999/files/1/", "/kb/999999/images/1/"]
    viewers = [_gone_session(), kb.as_editor(), kb.Session(author, support.logged_in(author))]

    for session in viewers:
        for path, absent in zip(paths, missing):
            _same_as_missing(session, path, absent)


def test_trashed_article_files_and_images_answer_as_missing_not_410_for_non_manager():
    """FR-422, FR-423: статья в корзине — читателю и редактору 404, как у несуществующей (не 410 и не заглушка)."""
    article, paths = _article_with_both(state="trash")
    missing = ["/kb/999999/files/1/", "/kb/999999/images/1/"]

    for session in (_gone_session(), kb.as_editor()):
        for path, absent in zip(paths, missing):
            _same_as_missing(session, path, absent)
            assert session.client.get(path).status_code != 410


def test_manager_gets_files_and_images_of_draft_and_trashed_article():
    """FR-422, FR-423: управляющий получает файл и картинку чужого черновика и статьи в корзине (10.7)."""
    manager = kb.as_manager()
    for state in ("draft", "trash"):
        article = kb.make_article(state=state)
        document = kb.attach_file(article, "report.pdf", status="clean")
        picture = kb.attach_file(article, "схема.png", status="clean")

        download = manager.client.get(_files_url(article, document))
        image = manager.client.get(_image_url(article, picture))

        assert download.status_code == 200, f"{state}: файл {download.status_code}"
        assert download["X-Accel-Redirect"] == f"/protected/attachments/{document.file_id}"
        assert image.status_code == 200, f"{state}: картинка {image.status_code}"
        assert image["X-Accel-Redirect"] == f"/protected/attachments/{picture.file_id}"
        assert _kind(image) == "image/png"


def test_right_to_article_rechecked_on_every_file_and_image_request():
    """FR-422, FR-423: право на статью проверяется на каждый запрос, без запоминания: тот же клиент получает 200,
    затем 404 после корзины, снова 200 после возврата, 404 после перевода в черновик и после потери права автором."""
    from django.core.cache import cache

    from apps.core.services import permissions

    model = support.model("knowledge.Article")
    article, paths = _article_with_both(state="published")
    for session in (_gone_session(), kb.as_editor(), kb.as_manager()):
        for path in paths:
            response = session.client.get(path)
            assert response.status_code == 200 and "X-Accel-Redirect" in response, f"{path}: {response.status_code}"
    reader = _gone_session()

    def statuses():
        return [reader.client.get(path).status_code for path in paths]

    assert statuses() == [200, 200]
    _to_trash(article)
    assert statuses() == [404, 404]
    _from_trash(article)
    assert statuses() == [200, 200]
    model.objects.filter(pk=article.pk).update(state="draft", published_at=None)
    assert statuses() == [404, 404]

    author = kb.as_editor()
    own, own_paths = _article_with_both(state="draft", author=author.user)
    assert [author.client.get(path).status_code for path in own_paths] == [200, 200]
    author.user.roles.clear()
    cache.delete(permissions._key(author.user.pk))
    assert [author.client.get(path).status_code for path in own_paths] == [404, 404]


def test_anonymous_redirected_to_login_on_files_and_images():
    """FR-422: без входа адреса файлов и картинок — 302 на `/login/` с `next` (10.1, 10.7), файла в ответе нет."""
    article, paths = _article_with_both(state="published")
    client = support.make_client()

    for path in paths:
        response = client.get(path)

        assert response.status_code == 302, f"{path}: {response.status_code}"
        assert response["Location"].startswith("/login/") and "next=" in response["Location"], response["Location"]
        assert "X-Accel-Redirect" not in response


# --- список вложений в форме правки ---------------------------------------------------------------------

def test_editor_list_offers_picture_button_only_for_images_and_link_button_for_all():
    """FR-423: в списке вложений формы правки «Вставить ссылку» есть у всех, кроме карантина (вставляет
    `[имя](att:N)`), «Картинка» — только у картинки (вставляет `![имя](att:N)`) (11.4)."""
    editor = kb.as_editor()
    article = kb.make_published(author=editor.user)
    picture = kb.attach_file(article, "схема.png", status="clean")
    document = kb.attach_file(article, "отчёт.pdf", status="clean")
    waiting = kb.attach_file(article, "ожидает.pdf", status="pending")
    blocked = kb.attach_file(article, "карантин.pdf", status="quarantine")
    waiting_picture = kb.attach_file(article, "ждёт.png", status="pending")
    blocked_picture = kb.attach_file(article, "вирус.png", status="quarantine")

    response = editor.client.get(f"/kb/{article.pk}/edit/")

    assert response.status_code == 200
    block = q1(tree(response), data_kb_files=True)

    def buttons(file, action):
        row = q1(block, "li", data_file_id=str(file.pk))
        return q(row, "button", data_action=action)

    link = buttons(picture, "kb-insert-link")
    assert [b.attrs["data-insert"] for b in link] == [f"[схема.png](att:{picture.pk})"]
    image = buttons(picture, "kb-insert-image")
    assert [b.attrs["data-insert"] for b in image] == [f"![схема.png](att:{picture.pk})"]
    assert [b.attrs["data-insert"] for b in buttons(document, "kb-insert-link")] == [f"[отчёт.pdf](att:{document.pk})"]
    assert buttons(document, "kb-insert-image") == []
    assert [b.attrs["data-insert"] for b in buttons(waiting, "kb-insert-link")] == [f"[ожидает.pdf](att:{waiting.pk})"]
    assert buttons(waiting, "kb-insert-image") == []
    assert buttons(blocked, "kb-insert-link") == []
    assert buttons(blocked, "kb-insert-image") == []
    assert [b.attrs["data-insert"] for b in buttons(waiting_picture, "kb-insert-link")] == [
        f"[ждёт.png](att:{waiting_picture.pk})"], "у проверяемой картинки «Вставить ссылку» есть (п. 20)"
    assert buttons(waiting_picture, "kb-insert-image") == [], "«Картинка» — только у чистой картинки (п. 20)"
    assert buttons(blocked_picture, "kb-insert-link") == [] and buttons(blocked_picture, "kb-insert-image") == []


def test_att_of_attachment_uploaded_after_save_revives_at_next_save():
    """FR-423: `att:N` вложения, загруженного после сохранения, пока показывает заглушку (HTML считается при
    сохранении), а при следующем сохранении статьи оживает: в `html` появляется `<img>` (план, «Как статья ссылается»)."""
    from apps.knowledge.services import articles
    from apps.knowledge.services import render

    editor = kb.as_editor()
    article = kb.make_published(author=editor.user)
    file = kb.attach_file(article, "схема.png", status="clean")
    text = f"Схема: ![схема](att:{file.pk})"
    # состояние «статья сохранена раньше, чем вложение появилось»: в тексте уже `att:N`, а HTML считали без вложения
    article.text = text
    article.html, article.plain = render.render(text, {}, article.pk)
    article.save(update_fields=["text", "html", "plain"])
    url = _image_url(article, file)
    reader = _gone_session()
    body = q1(tree(reader.client.get(f"/kb/{article.pk}/")), data_field="body")
    assert q(body, "img") == []
    assert noimg_texts(body) == ["[вложение недоступно: схема]"]

    form = articles.ArticleForm(title=article.title, text=text + "\n\nДобавлено.", rubric_id=article.rubric_id,
                                tags="", comment="")
    result = articles.save(editor.user, article.pk, article.version_no, form)

    assert result.kind == "saved"
    article.refresh_from_db()
    assert article.version_no == 2
    body = q1(tree(reader.client.get(f"/kb/{article.pk}/")), data_field="body")
    assert [node.attrs["src"] for node in q(body, "img")] == [url]
    assert noimg_texts(body) == []
    assert q1(tree(article.html), "img").attrs["src"] == url
