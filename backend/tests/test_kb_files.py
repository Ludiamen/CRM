"""T-5114: вложения статьи — загрузка, пределы, проверка (FR-422, FR-423, NFR-404, NFR-411). Сценарий 5 спеки.

Прикрепление и удаление файлов статьи (`/kb/<id>/files/`, `/kb/<id>/files/<N>/delete/`), пределы (20 МБ, 20 файлов),
отказы по содержимому (исполняемые, архивы с паролем, картинка-«бомба»), сбой хранилища, итог проверки антивирусом
через запись `FilePurpose("knowledge")` точки `file_purposes`, список вложений и его состояния. Антивирус
подменяется только помощниками `scan_clean`/`scan_found`/`scan_unavailable`, запись файла — `fail_file_write`;
том `protected` настоящий (`protected_root`). Код среза на уровне модуля не импортируется (CONTRACT-005, шапка).
"""
import importlib
import io
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from tests import support
from tests import support_kb as kb
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX

pytestmark = pytest.mark.django_db

MB = 1024 * 1024
GONE = "Статья удалена"
SCAN = "apps.core.tasks.scan_file"


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


# --- помощники файла --------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.knowledge.services.{name}")


def _errors():
    return importlib.import_module("apps.knowledge.services")


def _upload(name: str, data: bytes):
    return SimpleUploadedFile(name, data)


def _post_file(client, article, name: str, data: bytes, *, hx: bool = True):
    return client.post(f"/kb/{article.pk}/files/", {"file": _upload(name, data)}, **(HX if hx else {}))


def _files_block(response) -> Node:
    """Фрагмент `[data-kb-files]` из ответа (в самом ответе или внутри страницы)."""
    return q1(tree(response), data_kb_files=True)


def _rows(block) -> list:
    return q(block, "li", data_file_id=True)


def _row_of(block, file_id) -> Node:
    return q1(block, "li", data_file_id=str(file_id))


def _field(row, name: str) -> str:
    found = q(row, data_field=name)
    return found[0].text() if found else ""


def _counts() -> tuple[int, int]:
    """Число строк `ArticleFile` и `StoredFile` назначения «файл статьи»."""
    return (support.model("knowledge.ArticleFile").objects.count(),
            support.model("core.StoredFile").objects.filter(purpose="knowledge").count())


def _refused(response, code: str, text: str) -> Node:
    """Отказ по контракту (10.5): 200, тот же фрагмент со списком и `[role=alert][data-code=<код>]`, текст из 12.1."""
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    block = _files_block(response)
    alert = q1(block, role="alert", data_code=code)
    assert alert is not None
    assert text in response.content.decode("utf-8"), f"в ответе нет текста отказа {text!r}"
    return block


def _scan(stored, capture):
    """Исполняет проверку файла диспетчером ядра внутри фиксации (стирание файлов идёт после неё)."""
    from apps.core import tasks

    with capture(execute=True):
        tasks.scan_file(str(stored.pk))


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _article_state(article) -> tuple:
    """Всё, что должно остаться нетронутым при сбое вложения или проверки."""
    row = _fresh(article)
    versions = list(row.versions.order_by("number").values_list("number", "title", "text", "html"))
    return row.title, row.text, row.html, row.plain, row.version_no, row.state, versions


def _gif_bytes() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 200, 30)).save(out, "GIF")
    return out.getvalue()


def _webp_bytes() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 30, 200)).save(out, "WEBP")
    return out.getvalue()


def _bomb_png() -> bytes:
    """PNG 20 000 x 10 000 точек (200 млн, больше двух пределов Pillow) при малом размере файла."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("1", (20000, 10000), 0).save(out, "PNG")
    return out.getvalue()


def _editor_with_draft(**over):
    """Редактор и его сохранённый черновик."""
    session = kb.as_editor()
    return session, kb.make_draft(author=session.user, **over)


# --- 1. прикрепление ------------------------------------------------------------------------------------

def test_attach_two_files_listed_pending_then_clean_after_scan(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422: два файла видны в списке «проверяется» (без ссылки), в `incoming/`, задания проверки поставлены; после проверки — «чистый» со ссылкой."""
    session, article = _editor_with_draft()
    data = {"vpn.ovpn": b"client\nremote vpn.example.test 1194\n", "screen.png": kb.png_bytes()}
    with django_capture_on_commit_callbacks(execute=True):
        for name, body in data.items():
            response = _post_file(session.client, article, name, body)
            assert response.status_code == 200
    block = _files_block(response)
    rows = _rows(block)
    assert [_field(row, "name") for row in rows] == ["vpn.ovpn", "screen.png"], "порядок — по времени загрузки"
    assert [row.attrs["data-file-state"] for row in rows] == ["pending", "pending"]
    assert [row.attrs["data-image"] for row in rows] == ["", "png"]
    assert all("проверяется" in _field(row, "state") for row in rows)
    assert all(q(row, "a", data_action="kb-download") == [] for row in rows), "до проверки ссылки нет"
    attached = list(support.model("knowledge.ArticleFile").objects.filter(article=article).order_by("id"))
    assert [(a.name, a.image_format) for a in attached] == [("vpn.ovpn", ""), ("screen.png", "png")]
    for a, row in zip(attached, rows):
        assert row.attrs["data-file-id"] == str(a.pk)
        assert (a.file.purpose, a.file.owner_id, a.file.status) == ("knowledge", None, "pending")
        assert (protected_root / "incoming" / str(a.file_id)).read_bytes() == data[a.name]
    queued = {tuple(job.args) for job in org.files_jobs() if job.func_name == SCAN}
    assert queued == {(str(a.file_id),) for a in attached}, "проверка ставится на каждый файл после фиксации"
    org.scan_clean(monkeypatch)
    for a in attached:
        _scan(a.file, django_capture_on_commit_callbacks)
    page = session.client.get(f"/kb/{article.pk}/edit/")
    assert page.status_code == 200
    rows = _rows(_files_block(page))
    assert [row.attrs["data-file-state"] for row in rows] == ["clean", "clean"]
    for a, row in zip(attached, rows):
        link = q1(row, "a", data_action="kb-download")
        assert link.attrs["href"] == f"/kb/{article.pk}/files/{a.pk}/"
        assert _field(row, "state") == ""


def test_attach_to_nonexistent_article_number_answers_404(protected_root):
    """FR-422: статьи с таким номером нет — 404 (не 410, не 500); файл не сохранён."""
    session = kb.as_editor()
    kb.make_draft(author=session.user)
    missing = support.model("knowledge.Article").objects.order_by("-pk").first().pk + 1000
    before = _counts()
    response = session.client.post(f"/kb/{missing}/files/", {"file": _upload("a.txt", b"data")}, **HX)
    assert response.status_code == 404
    plain = session.client.post(f"/kb/{missing}/files/", {"file": _upload("a.txt", b"data")})
    assert plain.status_code == 404
    assert _counts() == before
    assert [p for p in protected_root.rglob("*") if p.is_file()] == []


def test_editor_of_unsaved_draft_attach_and_image_buttons_disabled_with_hint(protected_root):
    """FR-422, FR-423: на странице новой статьи «Вложить» и «Картинка» неактивны с подсказкой «Сохраните черновик»; у сохранённой статьи активны, подсказки нет."""
    session, article = _editor_with_draft()
    page = tree(session.client.get("/kb/new/"))
    q1(page, data_kb_page="new")
    attach = q1(page, "button", data_action="kb-attach")
    image = q1(page, "button", data_md="image")
    for button in (attach, image):
        assert "disabled" in button.attrs
        assert button.attrs.get("title") == "Сохраните черновик"
    hint = q1(page, data_kb_hint="save-draft")
    assert "Сохраните черновик" in hint.text()
    saved = tree(session.client.get(f"/kb/{article.pk}/edit/"))
    q1(saved, data_kb_page="edit")
    for button in (q1(saved, "button", data_action="kb-attach"), q1(saved, "button", data_md="image")):
        assert "disabled" not in button.attrs
    assert q(saved, data_kb_hint="save-draft") == [], "у сохранённой статьи подсказки нет"
    form = q1(saved, "form", data_form="kb-attach")
    assert form.attrs.get("hx-post") == f"/kb/{article.pk}/files/"
    q1(form, "input", type="file", name="file")


def test_attach_refused_for_article_in_trash(django_capture_on_commit_callbacks, protected_root):
    """FR-422: файл к статье в корзине не принимается: 200 «Статья удалена» от имени автора и управляющего, службы — `ArticleGone`, ничего не записано."""
    from apps.knowledge.services import access

    manager = kb.as_manager()
    session = kb.as_editor()
    article = kb.make_trashed(author=session.user)
    before = _counts()
    for who in (session, manager):
        with django_capture_on_commit_callbacks(execute=True):
            response = _post_file(who.client, article, "поздно.txt", b"data")
        assert response.status_code == 200
        assert GONE in response.content.decode("utf-8")
        assert q1(tree(response), role="alert", data_code="article_gone") is not None
    assert _counts() == before
    assert org.files_jobs() == []
    with pytest.raises(access.ArticleGone):
        _svc("files").attach(manager.user, article.pk, _upload("поздно.txt", b"data"))
    assert _counts() == before


def test_attach_and_remove_refused_without_edit_right(django_capture_on_commit_callbacks, protected_root):
    """FR-422: читатель без права — 403 на загрузку и удаление (и в службе `PermissionDenied`); чужой черновик у редактора — 404; файлы целы."""
    reader = kb.as_reader()
    editor = kb.as_editor()
    published = kb.make_published(author=editor.user)
    kept = kb.attach_file(published, "схема.png", write=True)
    before = _counts()
    assert _post_file(reader.client, published, "a.txt", b"data").status_code == 403
    assert reader.client.post(f"/kb/{published.pk}/files/{kept.pk}/delete/", **HX).status_code == 403
    assert reader.client.post(f"/kb/{published.pk}/files/{kept.pk}/delete/").status_code == 403
    files = _svc("files")
    with pytest.raises(PermissionDenied):
        files.attach(reader.user, published.pk, _upload("a.txt", b"data"))
    with pytest.raises(PermissionDenied):
        files.remove(reader.user, kept.pk)
    assert _counts() == before
    foreign = kb.make_draft(author=kb.as_editor().user)
    foreign_file = kb.attach_file(foreign, "тайна.png", write=True)
    before = _counts()
    assert _post_file(editor.client, foreign, "a.txt", b"data").status_code == 404
    assert editor.client.post(f"/kb/{foreign.pk}/files/{foreign_file.pk}/delete/", **HX).status_code == 404
    assert _counts() == before
    assert support.model("knowledge.ArticleFile").objects.filter(pk=kept.pk).exists()
    assert (protected_root / "attachments" / str(kept.file_id)).is_file()


# --- 2. пределы и отказы по содержимому -----------------------------------------------------------------

def test_attach_exactly_20_mb_accepted_and_20_mb_plus_1_byte_refused(protected_root):
    """FR-422, NFR-404: ровно 20 МБ принимается, на байт больше — «Файл больше 20 МБ» (200, список прежний, на диске и в базе новых строк нет)."""
    session, article = _editor_with_draft()
    exact = _post_file(session.client, article, "ровно.txt", b"a" * (20 * MB))
    assert exact.status_code == 200
    (row,) = _rows(_files_block(exact))
    assert q(row, role="alert") == [] and row.attrs["data-file-state"] == "pending"
    (attached,) = support.model("knowledge.ArticleFile").objects.filter(article=article)
    assert attached.file.size == 20 * MB
    assert (protected_root / "incoming" / str(attached.file_id)).stat().st_size == 20 * MB
    before = _counts()
    over = _post_file(session.client, article, "больше.txt", b"a" * (20 * MB + 1))
    block = _refused(over, "too_big", "Файл больше 20 МБ")
    assert [row.attrs["data-file-id"] for row in _rows(block)] == [str(attached.pk)], "список прежний"
    assert _counts() == before
    assert sorted(p.name for p in (protected_root / "incoming").iterdir()) == [str(attached.file_id)]


def test_attach_21st_file_refused_with_message_status_200(protected_root):
    """FR-422: двадцатый файл принимается, двадцать первый — «У статьи уже 20 файлов» (200; и на обычном запросе — страница правки с сообщением), строк не прибавилось."""
    session, article = _editor_with_draft()
    for number in range(19):
        kb.attach_file(article, f"файл{number}.txt", b"data", status="clean")
    twentieth = _post_file(session.client, article, "двадцатый.txt", b"data")
    assert twentieth.status_code == 200 and q(tree(twentieth), role="alert") == []
    assert len(_rows(_files_block(twentieth))) == 20
    before = _counts()
    assert before[0] == 20
    block = _refused(_post_file(session.client, article, "лишний.txt", b"data"), "limit_20", "У статьи уже 20 файлов")
    assert len(_rows(block)) == 20
    plain = _post_file(session.client, article, "лишний.txt", b"data", hx=False)
    assert plain.status_code == 200
    page = tree(plain)
    q1(page, data_kb_page="edit")
    q1(page, role="alert", data_code="limit_20")
    assert "У статьи уже 20 файлов" in plain.content.decode("utf-8")
    assert _counts() == before


def test_attach_executable_refused_with_new_text_status_200(protected_root):
    """FR-422: исполняемый файл по расширению и по содержимому (`#!`) — «Исполняемые файлы не принимаются», 200, ничего не сохранено."""
    session, article = _editor_with_draft()
    before = _counts()
    for name, data in (("программа.exe", b"not really a program"), ("запуск.txt", b"#!/bin/sh\necho hello\n")):
        response = _post_file(session.client, article, name, data)
        block = _refused(response, "executable", "Исполняемые файлы не принимаются")
        assert _rows(block) == []
        assert _counts() == before
    with pytest.raises(_errors().FileRefused) as caught:
        _svc("files").attach(session.user, article.pk, _upload("программа.exe", b"x"))
    assert caught.value.code == "executable" and caught.value.field == ""
    assert _counts() == before
    assert not (protected_root / "incoming").exists() or list((protected_root / "incoming").iterdir()) == []


def test_attach_storage_write_error_keeps_article_and_shows_message_not_500(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422, NFR-411: `OSError` записи файла — «Не удалось сохранить файл» (200, не 500), строки откатились, статья, её текст и версии целы, проверка не поставлена."""
    session, article = _editor_with_draft(text="Текст, который нельзя потерять")
    kb.add_version(article, text="Вторая версия текста", author=session.user)
    state = _article_state(article)
    before = _counts()
    calls = kb.fail_file_write(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_file(session.client, article, "схема.png", kb.png_bytes())
    assert calls, "запись файла была вызвана через `uploads.write_file`"
    block = _refused(response, "write_failed", "Не удалось сохранить файл")
    assert _rows(block) == []
    assert _counts() == before, "ни `ArticleFile`, ни `StoredFile` не осталось"
    assert _article_state(article) == state
    assert org.files_jobs() == []
    with pytest.raises(_errors().FileRefused) as caught:
        _svc("files").attach(session.user, article.pk, _upload("схема.png", kb.png_bytes()))
    assert caught.value.code == "write_failed" and caught.value.field == ""
    assert _counts() == before
    assert _article_state(article) == state


def test_attach_pixel_bomb_image_refused_with_message_not_500(protected_root):
    """FR-422: картинка-«бомба» (больше двух пределов Pillow) и картинка больше 40 млн точек — «Картинка слишком большая», 200, не 500, ничего не сохранено."""
    session, article = _editor_with_draft()
    before = _counts()
    for name, data in (("бомба.png", _bomb_png()), ("огромная.png", org.huge_pixels_png())):
        assert len(data) < 5 * MB, "файл мал, огромна только разметка точек"
        block = _refused(_post_file(session.client, article, name, data), "image_too_large", "Картинка слишком большая")
        assert _rows(block) == []
        assert _counts() == before
    with pytest.raises(_errors().FileRefused) as caught:
        _svc("files").attach(session.user, article.pk, _upload("бомба.png", _bomb_png()))
    assert caught.value.code == "image_too_large"
    assert _counts() == before


def test_attach_password_zip_refused_with_new_text_status_200(protected_root):
    """FR-422: архивы с паролем (ZIP ZipCrypto и AES, RAR5) — «Архивы с паролем не принимаются», 200, ничего не сохранено."""
    session, article = _editor_with_draft()
    before = _counts()
    for sample in ("enc_zip_zipcrypto.zip", "enc_zip_aes.zip", "enc_rar5_data.rar"):
        response = _post_file(session.client, article, "архив" + sample[sample.rindex("."):], sd.sample(sample))
        block = _refused(response, "encrypted", "Архивы с паролем не принимаются")
        assert _rows(block) == []
        assert _counts() == before
    plain = _post_file(session.client, article, "обычный.zip", sd.sample("plain.zip"))
    assert plain.status_code == 200 and q(tree(plain), role="alert") == []
    assert len(_rows(_files_block(plain))) == 1, "архив без пароля принимается"


def test_attach_executable_renamed_to_png_refused_by_content(protected_root):
    """FR-422: исполняемый файл (PE, ELF), названный `photo.png`, не принят: тип определён по содержимому, отказ `executable`, картинкой он не сохраняется."""
    session, article = _editor_with_draft()
    before = _counts()
    for sample, name in (("exe_pe.bin", "photo.png"), ("exe_elf.bin", "picture.jpg")):
        response = _post_file(session.client, article, name, sd.sample(sample))
        block = _refused(response, "executable", "Исполняемые файлы не принимаются")
        assert _rows(block) == []
        assert _counts() == before


def test_attach_image_format_set_by_content_not_by_extension(protected_root):
    """FR-423: формат картинки — по содержимому, а не по расширению: PNG под именем `.dat`, JPEG под `.png`, GIF под `.jpg`, WebP под `.png`; текст под `.png` — не картинка."""
    session, article = _editor_with_draft()
    cases = [("картинка.dat", kb.png_bytes(), "png"), ("фото.png", kb.jpeg_bytes(), "jpeg"),
             ("анимация.jpg", _gif_bytes(), "gif"), ("схема.png", _webp_bytes(), "webp"),
             ("текст.png", b"just a text, not an image", "")]
    for name, data, expected in cases:
        response = _post_file(session.client, article, name, data)
        assert response.status_code == 200 and q(tree(response), role="alert") == [], name
    attached = {a.name: a for a in support.model("knowledge.ArticleFile").objects.filter(article=article)}
    assert {name: attached[name].image_format for name, _, _ in cases} == {name: fmt for name, _, fmt in cases}
    assert {name: attached[name].file.content_type for name, _, _ in cases} == {
        name: (f"image/{fmt}" if fmt else "application/octet-stream") for name, _, fmt in cases}, \
        "`StoredFile.content_type`: у картинки `image/<формат>`, у прочего `application/octet-stream` (п. 16)"
    rows = _rows(_files_block(session.client.get(f"/kb/{article.pk}/edit/")))
    assert {_field(row, "name"): row.attrs["data-image"] for row in rows} == {name: fmt for name, _, fmt in cases}


# --- 3. список вложений и корзина -----------------------------------------------------------------------

def test_attachment_list_of_article_in_trash_hidden_on_page_and_back_with_restored_article(protected_root):
    """FR-422: вложения статьи в корзине скрыты (управляющему страница без списка и имён файлов, остальным 410); после возврата список снова виден, строки целы."""
    manager = kb.as_manager()
    editor = kb.as_editor()
    article = kb.make_published(author=editor.user)
    attached = kb.attach_file(article, "конфиг-впн.txt", b"data", status="clean")
    page = manager.client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200 and "конфиг-впн.txt" in page.content.decode("utf-8")
    _svc("articles").trash(manager.user, article.pk)
    page = manager.client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200
    root = tree(page)
    assert q1(root, "article", data_article_state="trash") is not None
    assert q(root, "li", data_file_id=True) == [] and "конфиг-впн.txt" not in page.content.decode("utf-8")
    gone = editor.client.get(f"/kb/{article.pk}/")
    assert gone.status_code == 410 and "конфиг-впн.txt" not in gone.content.decode("utf-8")
    assert support.model("knowledge.ArticleFile").objects.filter(pk=attached.pk).exists(), "строки не удаляются"
    _svc("articles").restore(manager.user, article.pk)
    back = manager.client.get(f"/kb/{article.pk}/")
    (row,) = _rows(_files_block(back))
    assert row.attrs["data-file-id"] == str(attached.pk) and _field(row, "name") == "конфиг-впн.txt"
    assert row.attrs["data-file-state"] == "clean"


# --- 4. итог проверки антивирусом (запись `FilePurpose("knowledge")`) -----------------------------------

def _attach_via_service(session, article, name, data, capture):
    with capture(execute=True):
        return _svc("files").attach(session.user, article.pk, _upload(name, data))


def test_purpose_knowledge_clean_moves_file_to_attachments(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422, NFR-404: чисто — файл из `incoming/` в `attachments/<id>`, статус `clean`, `scanned_at` стоит, прежний путь стёрт; антивирусу ушёл путь из `incoming/`."""
    session, article = _editor_with_draft()
    data = kb.png_bytes()
    attached = _attach_via_service(session, article, "схема.png", data, django_capture_on_commit_callbacks)
    stored = attached.file
    incoming = protected_root / "incoming" / str(stored.pk)
    assert incoming.read_bytes() == data and _fresh(stored).status == "pending"
    calls = org.scan_clean(monkeypatch)
    _scan(stored, django_capture_on_commit_callbacks)
    assert calls == [str(incoming)]
    _fresh(stored)
    assert stored.status == "clean" and stored.scanned_at is not None
    assert (protected_root / "attachments" / str(stored.pk)).read_bytes() == data
    assert not incoming.exists()
    assert support.model("knowledge.ArticleFile").objects.filter(pk=attached.pk).exists()


def test_purpose_knowledge_found_moves_file_to_quarantine(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422, NFR-404: найден вирус — файл в `quarantine/<id>` с подписью, строки остались, в списке «в карантине» без ссылки и без вставки ссылки."""
    session, article = _editor_with_draft()
    attached = _attach_via_service(session, article, "заражён.txt", kb.eicar_bytes(), django_capture_on_commit_callbacks)
    stored = attached.file
    org.scan_found(monkeypatch, "Eicar-Signature")
    _scan(stored, django_capture_on_commit_callbacks)
    _fresh(stored)
    assert stored.status == "quarantine" and stored.signature == "Eicar-Signature" and stored.scanned_at is not None
    assert (protected_root / "quarantine" / str(stored.pk)).is_file()
    assert not (protected_root / "incoming" / str(stored.pk)).exists()
    assert not (protected_root / "attachments" / str(stored.pk)).exists()
    (row,) = _rows(_files_block(session.client.get(f"/kb/{article.pk}/edit/")))
    assert row.attrs["data-file-state"] == "quarantine" and "в карантине" in _field(row, "state")
    assert q(row, "a", data_action="kb-download") == []
    assert q(row, "button", data_action="kb-insert-link") == [], "из карантина ссылку не вставляют"
    assert session.client.get(f"/kb/{article.pk}/files/{attached.pk}/").status_code == 404


def test_purpose_knowledge_found_encrypted_heuristics_deletes_both_rows(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422: подпись `Heuristics.Encrypted.*` — не вирус: строки `ArticleFile` и `StoredFile` удалены, файл стёрт, в карантин не уходит."""
    session, article = _editor_with_draft()
    attached = _attach_via_service(session, article, "архив.dat", sd.sample("nested_enc_zip.zip"),
                                   django_capture_on_commit_callbacks)
    stored_id = attached.file_id
    assert (protected_root / "incoming" / str(stored_id)).is_file()
    org.scan_found(monkeypatch, "Heuristics.Encrypted.Zip")
    _scan(attached.file, django_capture_on_commit_callbacks)
    assert not support.model("knowledge.ArticleFile").objects.filter(pk=attached.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=stored_id).exists()
    for folder in ("incoming", "attachments", "quarantine"):
        assert not (protected_root / folder / str(stored_id)).exists(), folder
    assert _rows(_files_block(session.client.get(f"/kb/{article.pk}/edit/"))) == []


def test_purpose_knowledge_registered_so_pending_file_is_resolved(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422, NFR-404: запись `FilePurpose("knowledge")` есть в точке `file_purposes` (`still_waiting` верно только для ждущего файла со строкой `ArticleFile`), поэтому рабочий процесс очереди решает судьбу файла; без записи файл остался бы «проверяется»."""
    from apps.core import extensions

    session, article = _editor_with_draft()
    purposes = [item for func in extensions.registered("file_purposes") for item in func() if item.purpose == "knowledge"]
    assert len(purposes) == 1
    purpose = purposes[0]
    waiting = kb.attach_file(article, "ждёт.txt", b"data", status="pending", write=True)
    done = kb.attach_file(article, "готов.txt", b"data", status="clean", write=True)
    orphan = kb.attach_file(article, "сирота.txt", b"data", status="pending", write=True)
    orphan_stored = orphan.file
    orphan.delete()
    assert purpose.still_waiting(waiting.file) is True
    assert purpose.still_waiting(done.file) is False
    assert purpose.still_waiting(orphan_stored) is False, "без строки `ArticleFile` ждать нечего"
    queued = _attach_via_service(session, article, "через-очередь.txt", b"queue data", django_capture_on_commit_callbacks)
    org.scan_clean(monkeypatch)
    org.run_files_worker()
    assert _fresh(queued.file).status == "clean", "задание очереди дошло до записи `knowledge`"
    assert (protected_root / "attachments" / str(queued.file_id)).read_bytes() == b"queue data"
    # без записи точки итог не решается: файл остаётся ждущим
    stray = kb.attach_file(article, "без-записи.txt", b"data", status="pending", write=True)
    with kb.without_registrations("file_purposes"):
        _scan(stray.file, django_capture_on_commit_callbacks)
    assert _fresh(stray.file).status == "pending"
    _scan(stray.file, django_capture_on_commit_callbacks)
    assert _fresh(stray.file).status == "clean"


# --- 5. список и удаление -------------------------------------------------------------------------------

def test_list_pending_and_quarantined_marked_and_without_links(protected_root):
    """FR-422: в списке «проверяется» и «в карантине» помечены и без ссылки скачивания; у «чистого» ссылка и пустое состояние; кнопки вставки — как в 11.4 (`data-insert`), порядок по времени загрузки."""
    session = kb.as_editor()
    article = kb.make_published()
    pending = kb.attach_file(article, "ждёт.png", status="pending")
    clean = kb.attach_file(article, "чистый.png", status="clean")
    clean_text = kb.attach_file(article, "заметки.txt", b"notes", status="clean")
    quarantined = kb.attach_file(article, "вирус.png", status="quarantine")
    for url, editing in ((f"/kb/{article.pk}/edit/", True), (f"/kb/{article.pk}/", False)):
        response = session.client.get(url)
        assert response.status_code == 200, url
        block = _files_block(response)
        rows = _rows(block)
        assert [row.attrs["data-file-id"] for row in rows] == [
            str(a.pk) for a in (pending, clean, clean_text, quarantined)], url
        by_id = {row.attrs["data-file-id"]: row for row in rows}
        row = by_id[str(pending.pk)]
        assert row.attrs["data-file-state"] == "pending" and "проверяется" in _field(row, "state")
        assert q(row, "a", data_action="kb-download") == []
        row = by_id[str(quarantined.pk)]
        assert row.attrs["data-file-state"] == "quarantine" and "в карантине" in _field(row, "state")
        assert q(row, "a", data_action="kb-download") == []
        row = by_id[str(clean.pk)]
        assert row.attrs["data-file-state"] == "clean" and _field(row, "state") == ""
        assert q1(row, "a", data_action="kb-download").attrs["href"] == f"/kb/{article.pk}/files/{clean.pk}/"
        assert _field(row, "name") == "чистый.png" and _field(row, "size") != ""
        assert [row.attrs["data-image"] for row in rows] == ["png", "png", "", "png"]
        if editing:
            link = q1(row, "button", data_action="kb-insert-link")
            assert link.attrs["data-insert"] == "[чистый.png](att:" + str(clean.pk) + ")"
            image = q1(row, "button", data_action="kb-insert-image")
            assert image.attrs["data-insert"] == "![чистый.png](att:" + str(clean.pk) + ")"
            q1(row, "button", data_action="kb-file-delete")
            text_row = by_id[str(clean_text.pk)]
            assert q(text_row, "button", data_action="kb-insert-image") == [], "не картинке «Картинка» не нужна"
            assert q1(text_row, "button", data_action="kb-insert-link") is not None
            pending_row = by_id[str(pending.pk)]
            assert q1(pending_row, "button", data_action="kb-insert-link") is not None
            assert q(by_id[str(quarantined.pk)], "button", data_action="kb-insert-link") == []
            assert q(pending_row, "button", data_action="kb-insert-image") == [], \
                "«Картинка» только у чистой картинки: у проверяемой нет (п. 20)"
            assert q(by_id[str(quarantined.pk)], "button", data_action="kb-insert-image") == [], \
                "у карантина нет ни «Картинка», ни «Вставить ссылку» (п. 20)"


def test_remove_file_keeps_att_markup_and_writes_no_journal(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422: удаление вложения стирает строки и файл, текст и версия статьи не меняются (разметка `att:N` остаётся и даёт заглушку «вложение удалено»), журнал не пишется ни при загрузке, ни при удалении."""
    session, article = _editor_with_draft()
    journal_before = support.model("core.AuditEvent").objects.count()
    attached = _attach_via_service(session, article, "схема.png", kb.png_bytes(), django_capture_on_commit_callbacks)
    org.scan_clean(monkeypatch)
    _scan(attached.file, django_capture_on_commit_callbacks)
    article.text = f"Смотрите ![схема](att:{attached.pk}) и [файл](att:{attached.pk})"
    article.save()
    state = _article_state(article)
    stored_id = attached.file_id
    assert (protected_root / "attachments" / str(stored_id)).is_file()
    with django_capture_on_commit_callbacks(execute=True):
        response = session.client.post(f"/kb/{article.pk}/files/{attached.pk}/delete/", **HX)
    assert response.status_code == 200
    assert _rows(_files_block(response)) == []
    assert _counts() == (0, 0)
    assert not support.model("core.StoredFile").objects.filter(pk=stored_id).exists()
    assert not (protected_root / "attachments" / str(stored_id)).exists()
    assert _article_state(article) == state, "ни текста, ни версии удаление не трогает"
    assert f"att:{attached.pk}" in _fresh(article).text
    assert support.model("core.AuditEvent").objects.count() == journal_before, "журнала вложений нет"
    placeholder = session.client.get(f"/kb/{article.pk}/images/{attached.pk}/")
    assert placeholder.status_code == 200 and placeholder["X-KB-Placeholder"] == "removed"
    assert session.client.post(f"/kb/{article.pk}/files/{attached.pk}/delete/", **HX).status_code == 404


def test_remove_quarantined_file_disappears_from_list(django_capture_on_commit_callbacks, protected_root):
    """FR-422: файл в карантине автор удаляет из статьи — он исчезает из списка, строки и файл карантина стёрты, соседний чистый файл остаётся."""
    session, article = _editor_with_draft()
    infected = kb.attach_file(article, "вирус.txt", b"bad", status="quarantine", write=True)
    neighbour = kb.attach_file(article, "чистый.txt", b"good", status="clean", write=True)
    (before_row, _) = _rows(_files_block(session.client.get(f"/kb/{article.pk}/edit/")))
    assert before_row.attrs["data-file-state"] == "quarantine"
    quarantine_path = protected_root / "quarantine" / str(infected.file_id)
    assert quarantine_path.is_file()
    with django_capture_on_commit_callbacks(execute=True):
        response = session.client.post(f"/kb/{article.pk}/files/{infected.pk}/delete/", **HX)
    assert response.status_code == 200
    rows = _rows(_files_block(response))
    assert [row.attrs["data-file-id"] for row in rows] == [str(neighbour.pk)]
    assert not support.model("knowledge.ArticleFile").objects.filter(pk=infected.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=infected.file_id).exists()
    assert not quarantine_path.exists()
    assert (protected_root / "attachments" / str(neighbour.file_id)).is_file()
    plain = session.client.post(f"/kb/{article.pk}/files/{neighbour.pk}/delete/")
    assert plain.status_code == 302 and plain["Location"] == f"/kb/{article.pk}/edit/"


def test_remove_erases_disk_file_only_after_commit(django_capture_on_commit_callbacks, protected_root):
    """FR-422, NFR-411: строки удаляются в транзакции, а файл с диска стирается только после фиксации (откат транзакции файла не лишает)."""
    session, article = _editor_with_draft()
    attached = kb.attach_file(article, "схема.png", status="clean", write=True)
    path = protected_root / "attachments" / str(attached.file_id)
    assert path.is_file()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        _svc("files").remove(session.user, attached.pk)
        assert not support.model("knowledge.ArticleFile").objects.filter(pk=attached.pk).exists()
        assert path.is_file(), "до фиксации файл на месте"
    assert callbacks, "стирание поставлено на фиксацию"
    assert path.is_file()
    for callback in callbacks:
        callback()
    assert not path.exists()


# --- 6. сбои антивируса ---------------------------------------------------------------------------------

def test_clamav_down_file_stays_pending_portal_works_core_retries(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-422, NFR-411: ClamAV недоступен — файл остаётся «проверяется», страницы работают, файл не скачивается, задание уходит на повтор (24 повтора, срок 300 с); позже проверка проходит."""
    from rq.job import Job

    session, article = _editor_with_draft()
    with django_capture_on_commit_callbacks(execute=True):
        attached = _svc("files").attach(session.user, article.pk, _upload("файл.txt", b"data"))
    stored = attached.file
    calls = org.scan_unavailable(monkeypatch)
    org.run_files_worker()
    assert calls, "антивирус вызывали"
    _fresh(stored)
    assert stored.status == "pending" and stored.attempts == 1 and stored.last_error
    assert str(protected_root) not in stored.last_error
    assert (protected_root / "incoming" / str(stored.pk)).is_file()
    queue = org.files_queue()
    (job_id,) = queue.scheduled_job_registry.get_job_ids()
    job = Job.fetch(job_id, connection=queue.connection)
    assert job.func_name == SCAN and job.args == (str(stored.pk),)
    assert len(job.retry_intervals) == 24 and job.timeout == 300
    for url in (f"/kb/{article.pk}/", f"/kb/{article.pk}/edit/"):
        assert session.client.get(url).status_code == 200, url
    (row,) = _rows(_files_block(session.client.get(f"/kb/{article.pk}/edit/")))
    assert row.attrs["data-file-state"] == "pending" and "проверяется" in _field(row, "state")
    assert session.client.get(f"/kb/{article.pk}/files/{attached.pk}/").status_code == 404
    org.scan_clean(monkeypatch)
    _scan(stored, django_capture_on_commit_callbacks)
    assert _fresh(stored).status == "clean"
    assert session.client.get(f"/kb/{article.pk}/files/{attached.pk}/").status_code == 200


def test_clamav_failure_keeps_article_text_and_version(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """NFR-411: недоступный ClamAV и найденный вирус не меняют статью: заголовок, текст, HTML, номер и строки версий, время и автор правки прежние."""
    session = kb.as_editor()
    article = kb.make_published(author=session.user, text="Первая версия")
    kb.add_version(article, text="Текст, который нельзя потерять", author=session.user, comment="правка")
    state = _article_state(article)
    first = _attach_via_service(session, article, "первый.txt", b"one", django_capture_on_commit_callbacks)
    second = _attach_via_service(session, article, "второй.txt", kb.eicar_bytes(), django_capture_on_commit_callbacks)
    assert _article_state(article) == state, "загрузка текст и версии не трогает"
    org.scan_unavailable(monkeypatch)
    org.run_files_worker()
    assert _fresh(first.file).status == "pending" and _fresh(second.file).status == "pending"
    assert _article_state(article) == state
    org.scan_found(monkeypatch, "Eicar-Signature")
    _scan(second.file, django_capture_on_commit_callbacks)
    assert _fresh(second.file).status == "quarantine"
    assert _article_state(article) == state
    page = session.client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200 and "Текст, который нельзя потерять" in page.content.decode("utf-8")


def test_purge_quarantine_erases_article_file_by_attachment_path(protected_root, clock):
    """FR-422, NFR-404: прежнее задание ядра `purge_quarantine` стирает файл статьи из `quarantine/` через `attachment_path` через 30 суток (на 29-е сутки файл на месте), строки остаются."""
    from apps.core import tasks

    session, article = _editor_with_draft()
    infected = kb.attach_file(article, "вирус.txt", b"bad", status="quarantine", write=True)
    young = kb.attach_file(article, "свежий.txt", b"bad too", status="quarantine", write=True)
    path = protected_root / "quarantine" / str(infected.file_id)
    assert path.is_file()
    clock.advance(days=29)
    young.file.scanned_at = timezone.now()
    young.file.save(update_fields=["scanned_at"])
    assert tasks.purge_quarantine() == 0 and path.is_file()
    clock.advance(days=2)
    assert tasks.purge_quarantine() == 1
    assert not path.exists()
    assert (protected_root / "quarantine" / str(young.file_id)).is_file(), "свежий файл карантина на месте"
    assert support.model("knowledge.ArticleFile").objects.filter(pk=infected.pk).exists()
    assert _fresh(infected.file).status == "quarantine", "строка остаётся"
