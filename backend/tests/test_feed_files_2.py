"""T-7130: файлы ленты — назначение `feed`, эскизы, выдача, показ (FR-606, FR-633, FR-634, FR-642, NFR-613, NFR-614).

Итог проверки антивирусом (`FilePurpose("feed")`: «чистый» с эскизом, «карантин», сбой ClamAV и хранилища), эскиз
(`thumbs.build`: форматы, 1280 px, WebP для прозрачного PNG, EXIF, первый кадр GIF, сбой), выдача `GET /feed/files/<id>/`
и `/feed/files/<id>/thumb/` (заголовки, видимость записи раньше состояния файла, непривязанный файл), показ в записи и
комментарии (`[data-feed-file][data-file-state]`). Антивирус подменяют `scan_clean`, `scan_found`, `scan_unavailable`
(решение 21 задач); все тесты с файлами на диске идут с фикстурой `protected_root`. Для сбоя хранилища при переносе
контракт не называет точки подмены: каталог `attachments` подменяется обычным файлом, из-за чего создание каталога
назначения даёт `OSError` внутри обработчика ядра (см. итог T-7130). Тексты — литералы раздела 13 (решение 19 задач).
Код среза на уровне модуля не импортируется (CONTRACT-007, шапка).
"""
import io
import logging
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

from tests import support
from tests import support_feed as fd
from tests import support_org as org
from tests.support import HX, model

pytestmark = pytest.mark.django_db

SCAN = "apps.core.tasks.scan_file"
TEXT_PENDING = "Файл ещё проверяется"
TEXT_QUARANTINE = "Файл в карантине"
TEXT_NOT_FOUND = "Не найдено"
SCAN_LOGGER = "apps.feed.services.files"


# --- разбор разметки (помощник только этого файла) -------------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}

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
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def _file_node(page: Node, item) -> Node:
    found = _find(page, data_feed_file=str(item.pk))
    assert len(found) == 1, f"ждали один элемент [data-feed-file={item.pk}], нашли {len(found)}"
    return found[0]


# --- помощники файла ---------------------------------------------------------------------------------------

def _world():
    """Автор с правом «Писать всем», адресат-читатель, посторонний и запись автора для читателя."""
    writer, viewer, outsider = fd.as_writer(), fd.as_plain(), fd.as_plain()
    post = fd.make_post(writer.user, to=(viewer.user,), text="Запись с файлами")
    return SimpleNamespace(writer=writer, viewer=viewer, outsider=outsider, post=post)


def _fresh(item):
    return model("feed.FeedFile").objects.select_related("file").get(pk=item.pk)


def _scan(stored, capture):
    """Исполняет проверку файла диспетчером ядра внутри фиксации (стирание файлов идёт после неё)."""
    from apps.core import tasks

    with capture(execute=True):
        tasks.scan_file(str(stored.pk))


def _pending(post_or_comment, name="схема.png", data=None, **extra):
    return fd.attach(post_or_comment, name, data, status="pending", write=True, **extra)


def _uploaded(session, post, name, data, capture, comment=None):
    """Файл через `POST /feed/files/` (очередь проверки поставлена после фиксации), затем привязан к записи или
    комментарию прямой правкой строки."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    fields = {"file": SimpleUploadedFile(name, data), "scope": "comment" if comment is not None else "post"}
    with capture(execute=True):
        response = session.client.post("/feed/files/", fields, **HX)
    assert response.status_code == 200
    made = model("feed.FeedFile").objects.filter(uploaded_by=session.user).order_by("-pk").first()
    assert made is not None and made.file.status == "pending"
    model("feed.FeedFile").objects.filter(pk=made.pk).update(post=post, comment=comment)
    return _fresh(made)


def _image(width, height, *, mode="RGB", color=(30, 90, 200), fmt="JPEG") -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new(mode, (width, height), color).save(out, fmt)
    return out.getvalue()


def _thumb_image(protected_root, relative: str):
    from PIL import Image

    assert relative, "эскиз не построен"
    path = protected_root / relative
    assert path.is_file(), f"нет файла эскиза {relative}"
    image = Image.open(path)
    image.load()
    return image


def _build(protected_root, data: bytes, stored_id: int) -> str:
    from apps.feed.services import thumbs

    source = protected_root / "incoming" / str(stored_id)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return thumbs.build(source, stored_id)


def _get(session, path):
    return session.client.get(path)


# --- 1. назначение `feed`: итог проверки -----------------------------------------------------------------------

def test_clean_scan_moves_file_to_attachments_and_builds_thumb(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-634: чисто — файл из `incoming/<id>` в `attachments/<id>`, статус `clean`, `scanned_at` стоит, прежний путь
    стёрт, антивирусу ушёл путь из `incoming/`; для картинки построен эскиз `attachments/thumbs/<id>.jpg|webp`, поле
    `FeedFile.thumb` заполнено."""
    w = _world()
    data = org.png_bytes(300, 200)
    item = _pending(w.post, "схема.png", data)
    stored = item.file
    incoming = protected_root / "incoming" / str(stored.pk)
    assert incoming.read_bytes() == data
    calls = org.scan_clean(monkeypatch)
    _scan(stored, django_capture_on_commit_callbacks)
    assert calls == [str(incoming)]
    done = _fresh(item)
    assert done.file.status == "clean" and done.file.scanned_at is not None
    assert (protected_root / "attachments" / str(stored.pk)).read_bytes() == data
    assert not incoming.exists()
    assert done.thumb.startswith(f"attachments/thumbs/{stored.pk}.") and done.thumb.rsplit(".", 1)[1] in ("jpg", "webp")
    assert (protected_root / done.thumb).is_file()


def test_found_scan_puts_file_to_quarantine(django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-634: найден вирус — файл в `quarantine/<id>` с подписью, статус `quarantine`, прежний путь стёрт, эскиза
    нет; строка `FeedFile` остаётся."""
    w = _world()
    item = _pending(w.post, "заражён.txt", org.eicar_bytes())
    stored = item.file
    org.scan_found(monkeypatch, "Eicar-Signature")
    _scan(stored, django_capture_on_commit_callbacks)
    done = _fresh(item)
    assert done.file.status == "quarantine" and done.file.signature == "Eicar-Signature"
    assert done.file.scanned_at is not None
    assert (protected_root / "quarantine" / str(stored.pk)).is_file()
    assert not (protected_root / "incoming" / str(stored.pk)).exists()
    assert not (protected_root / "attachments" / str(stored.pk)).exists()
    assert done.thumb == ""
    assert not (protected_root / "attachments" / "thumbs").exists() or not list(
        (protected_root / "attachments" / "thumbs").iterdir())


def test_clamav_unavailable_post_and_comment_intact_file_pending_requeued(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """NFR-614: ClamAV недоступен — файл остаётся «проверяется» (попытка и ошибка записаны, путь тома в ошибке не
    виден), запись и комментарий целы, страницы работают, файл не отдаётся; задание ушло на повтор в очередь `files`;
    после возвращения ClamAV проверка проходит."""
    from rq.job import Job

    w = _world()
    comment = fd.comment(w.post, w.writer.user, "Комментарий автора")
    on_post = _uploaded(w.writer, w.post, "запись.txt", b"post file", django_capture_on_commit_callbacks)
    on_comment = _uploaded(w.writer, w.post, "комментарий.txt", b"comment file", django_capture_on_commit_callbacks,
                           comment=comment)
    state = (w.post.text, model("feed.Post").objects.filter(pk=w.post.pk).count(), comment.text)
    calls = org.scan_unavailable(monkeypatch)
    org.run_files_worker()
    assert calls, "антивирус вызывали"
    for item in (on_post, on_comment):
        done = _fresh(item)
        assert done.file.status == "pending" and done.file.attempts == 1 and done.file.last_error
        assert str(protected_root) not in done.file.last_error
        assert (protected_root / "incoming" / str(done.file_id)).is_file()
    assert (w.post.text, model("feed.Post").objects.filter(pk=w.post.pk).count(), comment.text) == state
    assert model("core.Comment").objects.filter(pk=comment.pk, text="Комментарий автора").exists()
    queue = org.files_queue()
    job_ids = queue.scheduled_job_registry.get_job_ids()
    assert len(job_ids) == 2
    jobs = [Job.fetch(job_id, connection=queue.connection) for job_id in job_ids]
    assert {(job.func_name, job.args) for job in jobs} == {
        (SCAN, (str(on_post.file_id),)), (SCAN, (str(on_comment.file_id),))}
    assert all(job.retry_intervals for job in jobs)
    for session in (w.writer, w.viewer):
        assert _get(session, f"/feed/{w.post.pk}/").status_code == 200
    assert _get(w.viewer, f"/feed/files/{on_post.pk}/").status_code == 404
    org.scan_clean(monkeypatch)
    for item in (on_post, on_comment):
        _scan(item.file, django_capture_on_commit_callbacks)
        assert _fresh(item).file.status == "clean"
    assert _get(w.viewer, f"/feed/files/{on_post.pk}/").status_code == 200


def test_storage_failure_on_clean_move_keeps_post_comment_and_file_pending_requeued(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-633, NFR-614: сбой хранилища при переносе «чистого» (`OSError` при создании каталога `attachments/`) —
    транзакция проверки откатывается, файл остаётся «проверяется» в `incoming/`, запись, комментарий и строка
    `FeedFile` целы, задание уходит на повтор; когда хранилище снова исправно, тот же файл становится «чистым»."""
    from rq.job import Job

    w = _world()
    comment = fd.comment(w.post, w.writer.user, "Комментарий автора")
    item = _uploaded(w.writer, w.post, "файл.png", org.png_bytes(), django_capture_on_commit_callbacks, comment=comment)
    stored_id = item.file_id
    blocker = protected_root / "attachments"
    assert not blocker.exists()
    blocker.write_bytes(b"not a directory")
    org.scan_clean(monkeypatch)
    org.run_files_worker()
    done = _fresh(item)
    assert done.file.status == "pending" and done.thumb == ""
    assert (protected_root / "incoming" / str(stored_id)).is_file()
    assert model("feed.Post").objects.filter(pk=w.post.pk, text=w.post.text).exists()
    assert model("core.Comment").objects.filter(pk=comment.pk, text="Комментарий автора").exists()
    assert model("feed.FeedFile").objects.filter(pk=item.pk, comment_id=comment.pk).exists()
    queue = org.files_queue()
    (job_id,) = queue.scheduled_job_registry.get_job_ids()
    job = Job.fetch(job_id, connection=queue.connection)
    assert (job.func_name, job.args) == (SCAN, (str(stored_id),))
    blocker.unlink()
    _scan(item.file, django_capture_on_commit_callbacks)
    assert _fresh(item).file.status == "clean"
    assert (protected_root / "attachments" / str(stored_id)).is_file()


# --- 2. эскиз -------------------------------------------------------------------------------------------------

def test_thumb_built_for_jpeg_png_gif_webp_not_for_other_files(protected_root):
    """FR-634: `thumbs.build` строит эскиз для JPEG, PNG, GIF и WebP (по содержимому, не по имени) и возвращает путь
    `attachments/thumbs/<id>.jpg|webp` от корня тома; для текста, архива и PDF возвращает пустую строку и файла не
    пишет."""
    samples = {"jpeg": org.jpeg_bytes(200, 100), "png": org.png_bytes(200, 100), "gif": fd.images()["gif_frames"],
               "webp": _image(200, 100, fmt="WEBP")}
    for number, (label, data) in enumerate(samples.items(), start=9100):
        relative = _build(protected_root, data, number)
        assert relative.startswith(f"attachments/thumbs/{number}."), label
        assert relative.rsplit(".", 1)[1] in ("jpg", "webp"), label
        assert (protected_root / relative).is_file(), label
    for number, data in enumerate((b"just text, not an image", b"%PDF-1.4\n1 0 obj\n", org.fake_png()[:8] + b"plain"),
                                  start=9200):
        assert _build(protected_root, data, number) == ""
        thumbs_dir = protected_root / "attachments" / "thumbs"
        assert not list(thumbs_dir.glob(f"{number}.*")) if thumbs_dir.exists() else True


def test_thumb_at_most_1280_px_longer_side_saved_as_jpeg(protected_root):
    """FR-634: у большой картинки эскиз не больше 1280 px по большей стороне (ландшафт и портрет), пропорции
    сохранены, формат JPEG, расширение `.jpg`."""
    wide = _build(protected_root, _image(3000, 2000), 9301)
    tall = _build(protected_root, _image(2000, 3000), 9302)
    assert wide.endswith(".jpg") and tall.endswith(".jpg")
    wide_image = _thumb_image(protected_root, wide)
    tall_image = _thumb_image(protected_root, tall)
    assert wide_image.format == "JPEG" and tall_image.format == "JPEG"
    assert wide_image.size[0] == 1280 and abs(wide_image.size[1] - 853) <= 1
    assert tall_image.size[1] == 1280 and abs(tall_image.size[0] - 853) <= 1
    small = _thumb_image(protected_root, _build(protected_root, _image(400, 300), 9303))
    assert max(small.size) <= 1280


def test_thumb_png_with_transparency_saved_as_webp(protected_root):
    """FR-634: PNG с прозрачностью — эскиз WebP (`.webp`, прозрачность сохранена); PNG без прозрачности — JPEG."""
    alpha = _build(protected_root, fd.images()["png_alpha"], 9401)
    assert alpha.endswith(".webp")
    image = _thumb_image(protected_root, alpha)
    assert image.format == "WEBP" and "A" in image.convert("RGBA").getbands()
    assert image.convert("RGBA").getpixel((10, 10))[3] < 255, "прозрачность потеряна"
    opaque = _build(protected_root, org.png_bytes(64, 64), 9402)
    assert opaque.endswith(".jpg") and _thumb_image(protected_root, opaque).format == "JPEG"


def test_thumb_rotated_by_exif_and_saved_without_exif(protected_root):
    """FR-634: эскиз повёрнут по EXIF-ориентации (120×80 с ориентацией 6 → 80×120) и сохранён без EXIF (тега
    ориентации и блока `exif` нет)."""
    relative = _build(protected_root, fd.images()["jpeg_exif"], 9501)
    image = _thumb_image(protected_root, relative)
    assert image.size == (80, 120)
    assert 0x0112 not in image.getexif()
    assert "exif" not in image.info


def test_thumb_gif_uses_first_frame(protected_root):
    """FR-634: у GIF эскиз — первый кадр одним кадром (красный из красного, зелёного и синего), не анимация."""
    from PIL import Image

    frames = [Image.new("RGB", (40, 40), color).convert("P") for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    relative = _build(protected_root, out.getvalue(), 9601)
    image = _thumb_image(protected_root, relative)
    assert getattr(image, "n_frames", 1) == 1
    red, green, blue = image.convert("RGB").getpixel((20, 20))
    assert red > green + 100 and red > blue + 100, (red, green, blue)


def test_original_and_thumb_paths_under_protected_root_thumb_field_set(
        django_capture_on_commit_callbacks, protected_root, monkeypatch, settings):
    """FR-634, NFR-613: после проверки оригинал (`attachments/<id>`) и эскиз (`attachments/thumbs/<id>.*`) лежат под
    `PROTECTED_ROOT` (том `protected`, который берёт резервная копия); `FeedFile.thumb` — путь от корня тома без
    начальной косой черты."""
    w = _world()
    item = _pending(w.post, "схема.png", org.png_bytes(500, 400))
    org.scan_clean(monkeypatch)
    _scan(item.file, django_capture_on_commit_callbacks)
    done = _fresh(item)
    assert settings.PROTECTED_ROOT == protected_root
    original = protected_root / "attachments" / str(done.file_id)
    assert original.is_file() and original.resolve().is_relative_to(protected_root.resolve())
    assert done.thumb and not done.thumb.startswith("/")
    thumb = protected_root / done.thumb
    assert thumb.is_file() and thumb.resolve().is_relative_to((protected_root / "attachments" / "thumbs").resolve())
    assert thumb.stem == str(done.file_id)


def test_thumb_failure_file_clean_without_thumb_log_without_name_partial_removed(
        django_capture_on_commit_callbacks, protected_root, monkeypatch, caplog):
    """FR-634, NFR-614: сбой построения эскиза (`MemoryError`, `OSError` после частичной записи файла эскиза) не
    откладывает «чистый»: файл `clean` в `attachments/`, `thumb` пуст, частичный файл эскиза стёрт, проверка не
    падает; в журнале приложения (`apps.feed.services.files`) есть предупреждение без имени файла."""
    w = _world()
    names = {"тайный-отчёт.png": MemoryError, "ведомость-остатков.png": OSError}
    items = {name: _pending(w.post, name, org.png_bytes(80, 60)) for name in names}
    by_id = {item.file_id: names[name] for name, item in items.items()}

    def broken_build(source, stored_id):
        partial = protected_root / "attachments" / "thumbs" / f"{stored_id}.jpg"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"partial")
        raise by_id[int(stored_id)]("сбой эскиза (подмена теста)")

    monkeypatch.setattr("apps.feed.services.thumbs.build", broken_build)
    org.scan_clean(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=SCAN_LOGGER):
        for item in items.values():
            _scan(item.file, django_capture_on_commit_callbacks)
    for name, item in items.items():
        done = _fresh(item)
        assert done.file.status == "clean", name
        assert (protected_root / "attachments" / str(done.file_id)).is_file()
        assert done.thumb == ""
        assert not (protected_root / "attachments" / "thumbs" / f"{done.file_id}.jpg").exists(), "частичный эскиз стёрт"
    records = [record for record in caplog.records if record.name == SCAN_LOGGER and record.levelno >= logging.WARNING]
    assert records, "в журнале нет предупреждения о сбое эскиза"
    for record in records:
        text = " ".join([record.getMessage(), str(record.exc_text or ""), str(record.args)])
        assert not any(name in text for name in names), "имя файла в журнале"


# --- 3. выдача --------------------------------------------------------------------------------------------------

def test_download_clean_image_inline_other_as_attachment_via_x_accel_nosniff_no_store(protected_root):
    """FR-634: «чистая» картинка отдаётся показом (без `Content-Disposition`, тип `image/…`), прочий файл — вложением
    с именем в `filename*=UTF-8''…`; тело пустое, файл отдаёт nginx через `X-Accel-Redirect: /protected/attachments/<id>`;
    везде `X-Content-Type-Options: nosniff` и `Cache-Control: no-store`."""
    w = _world()
    image = fd.attach(w.post, "схема.png", write=True)
    other = fd.attach(w.post, "заметки.txt", b"notes", write=True)
    shown = _get(w.viewer, f"/feed/files/{image.pk}/")
    assert shown.status_code == 200 and shown.content == b""
    assert shown["X-Accel-Redirect"] == f"/protected/attachments/{image.file_id}"
    assert shown["Content-Type"].startswith("image/png")
    assert shown.get("Content-Disposition") is None
    saved = _get(w.viewer, f"/feed/files/{other.pk}/")
    assert saved.status_code == 200 and saved.content == b""
    assert saved["X-Accel-Redirect"] == f"/protected/attachments/{other.file_id}"
    assert saved["Content-Disposition"].startswith("attachment") and "filename*=UTF-8''" in saved["Content-Disposition"]
    assert saved["Content-Type"] == "application/octet-stream"
    for response in (shown, saved):
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Cache-Control"] == "no-store"


def test_thumb_response_x_accel_protected_thumbs_nosniff_no_store(protected_root):
    """FR-634: эскиз — свой ответ с `X-Accel-Redirect: /protected/attachments/thumbs/<имя>`, тип картинки,
    `nosniff`, `no-store`, тело пустое."""
    w = _world()
    item = fd.attach(w.post, "схема.png", write=True, thumb=True)
    response = _get(w.viewer, f"/feed/files/{item.pk}/thumb/")
    assert response.status_code == 200 and response.content == b""
    assert response["X-Accel-Redirect"] == f"/protected/{item.thumb}"
    assert response["X-Accel-Redirect"].startswith("/protected/attachments/thumbs/")
    assert response["Content-Type"].startswith("image/")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "no-store"


def test_thumb_of_clean_file_without_thumb_returns_404(protected_root):
    """FR-634 (решение 51 задач): «чистый» файл без эскиза — `/thumb/` отвечает 404 «Не найдено» (не «проверяется» и
    не «карантин»); оригинал при этом отдаётся."""
    w = _world()
    item = fd.attach(w.post, "схема.png", write=True)
    assert item.thumb == ""
    response = _get(w.viewer, f"/feed/files/{item.pk}/thumb/")
    assert response.status_code == 404
    body = response.content.decode("utf-8")
    assert TEXT_NOT_FOUND in body and TEXT_PENDING not in body and TEXT_QUARANTINE not in body
    assert response.get("X-Accel-Redirect") is None
    assert _get(w.viewer, f"/feed/files/{item.pk}/").status_code == 200


def test_pending_file_and_thumb_404_with_still_checking_text(protected_root):
    """FR-634, FR-642: пока файл «проверяется», и оригинал, и эскиз — 404 с текстом «Файл ещё проверяется»,
    без `X-Accel-Redirect`."""
    w = _world()
    item = _pending(w.post, "схема.png")
    for path in (f"/feed/files/{item.pk}/", f"/feed/files/{item.pk}/thumb/"):
        response = _get(w.viewer, path)
        assert response.status_code == 404, path
        assert TEXT_PENDING in response.content.decode("utf-8"), path
        assert response.get("X-Accel-Redirect") is None


def test_quarantined_file_by_direct_link_404_with_quarantine_text(protected_root):
    """FR-634, FR-642: файл в карантине по прямой ссылке — 404 с текстом «Файл в карантине» (оригинал и эскиз), даже
    автору записи."""
    w = _world()
    item = fd.attach(w.post, "заражён.txt", b"bad", status="quarantine", write=True)
    for session in (w.viewer, w.writer):
        for path in (f"/feed/files/{item.pk}/", f"/feed/files/{item.pk}/thumb/"):
            response = _get(session, path)
            assert response.status_code == 404, path
            assert TEXT_QUARANTINE in response.content.decode("utf-8"), path
            assert response.get("X-Accel-Redirect") is None


def test_invisible_post_file_and_thumb_not_found_like_missing_file(protected_root):
    """FR-606, FR-634: файл записи, которую сотрудник не видит, и его эскиз — 404 «Не найдено», неотличимый от
    несуществующего файла; адресат тот же файл получает."""
    w = _world()
    item = fd.attach(w.post, "схема.png", write=True, thumb=True)
    missing = item.pk + 1000
    for suffix in ("", "thumb/"):
        denied = _get(w.outsider, f"/feed/files/{item.pk}/{suffix}")
        absent = _get(w.outsider, f"/feed/files/{missing}/{suffix}")
        assert denied.status_code == 404 and TEXT_NOT_FOUND in denied.content.decode("utf-8")
        assert support.same_failure(denied, absent), suffix
        assert _get(w.viewer, f"/feed/files/{item.pk}/{suffix}").status_code == 200


def test_invisible_post_pending_file_not_found_not_still_checking(protected_root):
    """FR-606, FR-642: у невидимой записи файл «проверяется» и файл в карантине дают «Не найдено», а не «Файл ещё
    проверяется» и не «Файл в карантине» (видимость записи проверяется раньше состояния файла)."""
    w = _world()
    waiting = _pending(w.post, "ждёт.png")
    infected = fd.attach(w.post, "вирус.txt", b"bad", status="quarantine", write=True)
    for item in (waiting, infected):
        for suffix in ("", "thumb/"):
            response = _get(w.outsider, f"/feed/files/{item.pk}/{suffix}")
            body = response.content.decode("utf-8")
            assert response.status_code == 404
            assert TEXT_NOT_FOUND in body and TEXT_PENDING not in body and TEXT_QUARANTINE not in body
            assert support.same_failure(response, _get(w.outsider, f"/feed/files/{item.pk + 1000}/{suffix}"))


def test_unbound_file_served_only_to_uploader_others_404(protected_root):
    """FR-606, FR-634: непривязанный «чистый» файл отдаётся только загрузившему; остальным (адресату, модератору,
    постороннему) — 404 «Не найдено», как несуществующий."""
    w = _world()
    moderator = fd.as_moderator()
    item = fd.attach(None, "черновик.txt", b"draft", uploaded_by=w.writer.user, write=True)
    own = _get(w.writer, f"/feed/files/{item.pk}/")
    assert own.status_code == 200 and own["X-Accel-Redirect"] == f"/protected/attachments/{item.file_id}"
    for session in (w.viewer, w.outsider, moderator):
        response = _get(session, f"/feed/files/{item.pk}/")
        assert response.status_code == 404 and TEXT_NOT_FOUND in response.content.decode("utf-8")
        assert support.same_failure(response, _get(session, f"/feed/files/{item.pk + 1000}/"))


# --- 4. показ ---------------------------------------------------------------------------------------------------

def _card_with(w, make):
    """Карточка записи у читателя, записи и комментарий с файлами `make(target)`; возвращает (дерево, файлы)."""
    comment = fd.comment(w.post, w.writer.user, "Комментарий автора")
    on_post, on_comment = make(w.post), make(comment)
    response = _get(w.viewer, f"/feed/{w.post.pk}/")
    assert response.status_code == 200
    return _tree(response), on_post, on_comment


def _links_to(node: Node, item) -> list:
    return [link for link in _find(node, "a") if link.attrs.get("href", "").startswith(f"/feed/files/{item.pk}/")]


def test_display_pending_name_and_mark_without_link_in_post_and_comment(protected_root):
    """FR-634: «проверяется» — имя файла и пометка «проверяется» без ссылки, в записи и в комментарии."""
    w = _world()
    page, on_post, on_comment = _card_with(w, lambda target: fd.attach(target, "ждёт.txt", status="pending"))
    for item in (on_post, on_comment):
        node = _file_node(page, item)
        assert node.attrs["data-file-state"] == "pending"
        assert "ждёт.txt" in node.text() and "проверяется" in node.text()
        assert _links_to(node, item) == [] and _find(node, "img") == []
    assert [link for link in _find(page, "a") if "/feed/files/" in link.attrs.get("href", "")] == []


def test_display_quarantine_name_and_mark_without_link(protected_root):
    """FR-634: «карантин» — имя файла и пометка «карантин» без ссылки, в записи и в комментарии."""
    w = _world()
    page, on_post, on_comment = _card_with(
        w, lambda target: fd.attach(target, "вирус.txt", b"bad", status="quarantine", write=True))
    for item in (on_post, on_comment):
        node = _file_node(page, item)
        assert node.attrs["data-file-state"] == "quarantine"
        assert "вирус.txt" in node.text() and "карантин" in node.text()
        assert _links_to(node, item) == [] and _find(node, "img") == []


def test_display_clean_image_as_thumb_linking_original(protected_root):
    """FR-634: «чистая» картинка с эскизом — эскиз `img[src="/feed/files/<id>/thumb/"]` внутри ссылки на оригинал
    `a[href="/feed/files/<id>/"]`, в записи и в комментарии."""
    w = _world()
    page, on_post, on_comment = _card_with(
        w, lambda target: fd.attach(target, "схема.png", write=True, thumb=True))
    for item in (on_post, on_comment):
        node = _file_node(page, item)
        assert node.attrs["data-file-state"] == "clean"
        (picture,) = _find(node, "img", src=f"/feed/files/{item.pk}/thumb/")
        assert picture.parent.tag == "a" and picture.parent.attrs["href"] == f"/feed/files/{item.pk}/"


def test_display_clean_other_file_name_size_download(protected_root):
    """FR-634: «чистый» файл не картинка — имя, размер и ссылка «Скачать» на `/feed/files/<id>/`; картинки нет."""
    w = _world()
    page, on_post, on_comment = _card_with(
        w, lambda target: fd.attach(target, "заметки.txt", b"notes of the day", write=True))
    for item in (on_post, on_comment):
        node = _file_node(page, item)
        assert node.attrs["data-file-state"] == "clean"
        text = node.text()
        assert "заметки.txt" in text and "Скачать" in text
        assert text.replace("заметки.txt", "").replace("Скачать", "").strip() != "", "размер файла не показан"
        (link,) = [link for link in _links_to(node, item) if link.attrs["href"] == f"/feed/files/{item.pk}/"]
        assert "Скачать" in link.text()
        assert _find(node, "img") == []


def test_display_clean_image_without_thumb_shows_name_size_download(protected_root):
    """FR-634: «чистая» картинка без эскиза показывается как прочий файл — имя, размер, «Скачать»; эскиза-картинки
    нет."""
    w = _world()
    page, on_post, on_comment = _card_with(w, lambda target: fd.attach(target, "схема.png", write=True))
    for item in (on_post, on_comment):
        assert item.thumb == ""
        node = _file_node(page, item)
        text = node.text()
        assert "схема.png" in text and "Скачать" in text
        assert text.replace("схема.png", "").replace("Скачать", "").strip() != "", "размер файла не показан"
        assert [link.attrs["href"] for link in _links_to(node, item)] == [f"/feed/files/{item.pk}/"]
        assert _find(node, "img") == []


def test_display_file_state_data_attribute_for_each_state(protected_root):
    """FR-634: у каждого файла записи и комментария `data-file-state` равен `pending`, `clean` или `quarantine`
    по состоянию строки `StoredFile`."""
    w = _world()
    comment = fd.comment(w.post, w.writer.user, "Комментарий автора")
    expected = {}
    for target in (w.post, comment):
        for status in ("pending", "clean", "quarantine"):
            item = fd.attach(target, f"{status}.txt", b"data", status=status, write=True)
            expected[item.pk] = status
    page = _tree(_get(w.viewer, f"/feed/{w.post.pk}/"))
    found = {int(node.attrs["data-feed-file"]): node.attrs.get("data-file-state") for node in _find(page, data_feed_file=True)}
    assert found == expected
