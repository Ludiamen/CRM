"""T-7129: файлы ленты — загрузка, пределы, привязка, «убрать» (FR-633, FR-642, NFR-604). Сценарии 4 и 10 спеки 007.

Адреса `POST /feed/files/` и `POST /feed/files/<id>/delete/`, правка `POST /feed/<id>/edit/` с `remove`, публикация и
комментарий с `files`; службы `files.upload`, `files.bind`, `files.remove_unbound`. Отказы — литералы раздела 13
(решение 19 задач). Гонок без потоков нет (решение 6): условный `UPDATE` привязки смотрится по SQL с параметрами
(`queries_with_params`), замок записи — `assert_for_update`, «после фиксации» — `django_capture_on_commit_callbacks`.
Все тесты с настоящей загрузкой или файлом на диске идут с фикстурой `protected_root`. Код среза на уровне модуля
не импортируется (CONTRACT-007, шапка).
"""
import importlib
import re
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.http import Http404

from tests import support
from tests import support_feed as fd
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MB = 1024 * 1024
SCAN = "apps.core.tasks.scan_file"
TEXT_TOO_BIG = "Файл больше 20 МБ"
TEXT_TYPE = "Файл такого типа не принимается"
TEXT_POST_LIMIT = "У записи уже 10 файлов"
TEXT_COMMENT_LIMIT = "У комментария уже 3 файла"
TEXT_UNBOUND = "Слишком много файлов без записи: опубликуйте запись или уберите лишние"
TEXT_MISSING = "Файл не найден"


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


def _refusals(response) -> list[tuple[str, str, str]]:
    """Отказы формы: (поле, код, текст) — `[data-error][data-code]` в ответе."""
    return [(node.attrs["data-error"], node.attrs.get("data-code", ""), node.text())
            for node in _tree(response).walk() if "data-error" in node.attrs]


def _refused(response, field: str, code: str, text: str) -> None:
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    assert (field, code, text) in _refusals(response), f"нет отказа {field}/{code}/{text!r}: {_refusals(response)}"
    assert text in response.content.decode("utf-8")


# --- помощники файла ---------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.feed.services.{name}")


def _upload(session, name: str, data: bytes, *, scope: str = "post", post=None, comment=None, have=()):
    fields = {"file": SimpleUploadedFile(name, data), "scope": scope, "have": [str(number) for number in have]}
    if post is not None:
        fields["post"] = post.pk
    if comment is not None:
        fields["comment"] = comment.pk
    return session.client.post("/feed/files/", fields, **HX)


def _counts() -> tuple[int, int]:
    """Число строк `FeedFile` и `StoredFile` назначения «вложение ленты»."""
    return model("feed.FeedFile").objects.count(), model("core.StoredFile").objects.filter(purpose="feed").count()


def _pill(response, file_id=None) -> Node:
    """Таблетка загруженного файла `[data-feed-file]` со скрытым `input[name=files]` и крестиком."""
    pills = _find(_tree(response), data_feed_file=True)
    assert len(pills) == 1, f"ждали одну таблетку, нашли {len(pills)}"
    pill = pills[0]
    if file_id is not None:
        assert pill.attrs["data-feed-file"] == str(file_id)
    return pill


def _writer_post(**extra):
    """Автор с правом «Писать всем» и его запись для всех."""
    writer = fd.as_writer()
    return writer, fd.make_post(writer.user, to=("all",), text="Запись автора", **extra)


def _unbound(user, count: int, prefix: str = "ждёт") -> list:
    return [fd.attach(None, f"{prefix}-{number}.txt", uploaded_by=user) for number in range(count)]


def _publish(session, files, text: str = "Запись с файлами", hx: bool = False):
    return session.client.post("/feed/posts/", {"kind": "post", "text": text, "to": ["all"], "files": list(files)},
                               **(HX if hx else {}))


def _edit(session, post, *, files=(), remove=(), text: str = "Новый текст записи"):
    return session.client.post(f"/feed/{post.pk}/edit/",
                               {"text": text, "to": ["all"], "files": list(files), "remove": list(remove)})


def _fresh(item):
    return model("feed.FeedFile").objects.get(pk=item.pk)


def _disk(protected_root) -> list:
    return sorted(str(path.relative_to(protected_root)) for path in protected_root.rglob("*") if path.is_file())


def _posts_count() -> int:
    return model("feed.Post").objects.count()


# --- 1. загрузка: пределы и отказы по содержимому ----------------------------------------------------------

def test_upload_exactly_20_mb_accepted_returns_pill_with_hidden_files_id(protected_root):
    """FR-633, NFR-604: ровно 20 МБ принимается — 200, таблетка `[data-feed-file="<id>"]` со скрытым
    `input[name="files"][value="<id>"]` и крестиком `button[data-action="file-remove"]`, отказа нет."""
    writer = fd.as_writer()
    response = _upload(writer, "ровно.txt", b"a" * (20 * MB))
    assert response.status_code == 200
    assert _refusals(response) == []
    (made,) = model("feed.FeedFile").objects.filter(uploaded_by=writer.user)
    pill = _pill(response, made.pk)
    (hidden,) = _find(pill, "input", name="files")
    assert hidden.attrs["value"] == str(made.pk) and hidden.attrs.get("type") == "hidden"
    assert len(_find(pill, "button", data_action="file-remove")) == 1
    assert made.file.size == 20 * MB
    assert (protected_root / "incoming" / str(made.file_id)).stat().st_size == 20 * MB


def test_upload_20_mb_plus_one_byte_refused_file_over_20_mb(protected_root):
    """FR-633, FR-642, NFR-604: на байт больше 20 МБ — «Файл больше 20 МБ» у поля `file` (`file_too_big`), 200;
    строк `FeedFile` и `StoredFile` и файлов на диске не прибавилось."""
    writer = fd.as_writer()
    before = _counts()
    response = _upload(writer, "больше.txt", b"a" * (20 * MB + 1))
    _refused(response, "file", "file_too_big", TEXT_TOO_BIG)
    assert _find(_tree(response), data_feed_file=True) == []
    assert _counts() == before
    assert _disk(protected_root) == []


def test_upload_executable_by_content_refused_type_not_accepted(protected_root):
    """FR-633, FR-642: исполняемый файл по расширению, по строке `#!` и по содержимому (PE, ELF под именем картинки) —
    «Файл такого типа не принимается» (`file_type`), 200, ничего не сохранено."""
    writer = fd.as_writer()
    before = _counts()
    cases = (("программа.exe", b"not really a program"), ("запуск.txt", b"#!/bin/sh\necho hello\n"),
             ("photo.png", sd.sample("exe_pe.bin")), ("picture.jpg", sd.sample("exe_elf.bin")))
    for name, data in cases:
        _refused(_upload(writer, name, data), "file", "file_type", TEXT_TYPE)
        assert _counts() == before, name
    assert _disk(protected_root) == []


def test_upload_password_archive_refused_type_not_accepted(protected_root):
    """FR-633, FR-642: архивы с паролем (ZIP ZipCrypto и AES, RAR5) — «Файл такого типа не принимается»; архив без
    пароля принимается."""
    writer = fd.as_writer()
    before = _counts()
    for sample in ("enc_zip_zipcrypto.zip", "enc_zip_aes.zip", "enc_rar5_data.rar"):
        _refused(_upload(writer, "архив" + sample[sample.rindex("."):], sd.sample(sample)),
                 "file", "file_type", TEXT_TYPE)
        assert _counts() == before, sample
    accepted = _upload(writer, "обычный.zip", sd.sample("plain.zip"))
    assert accepted.status_code == 200 and _refusals(accepted) == []
    assert len(_find(_tree(accepted), data_feed_file=True)) == 1


def test_upload_image_over_40_megapixels_refused_type_not_accepted(protected_root):
    """FR-633, FR-642: картинка больше 40 млн точек при малом размере файла (`ImageTooLarge`) — тот же отказ типа,
    200, не 500, ничего не сохранено."""
    writer = fd.as_writer()
    before = _counts()
    huge = fd.images()["huge"]
    assert len(huge) < 5 * MB
    _refused(_upload(writer, "огромная.png", huge), "file", "file_type", TEXT_TYPE)
    assert _counts() == before
    assert _disk(protected_root) == []


def test_upload_stores_feed_purpose_pending_and_unbound_row_of_uploader(
        django_capture_on_commit_callbacks, protected_root):
    """FR-633, NFR-604: строка `StoredFile` назначения `feed`, `pending`, без владельца; файл в `incoming/<id>`;
    `FeedFile(post=NULL, comment=NULL, uploaded_by=я, name=<имя>)`; проверка ClamAV поставлена в очередь `files`
    после фиксации."""
    writer = fd.as_writer()
    body = b"client\nremote vpn.example.test 1194\n"
    with django_capture_on_commit_callbacks(execute=True):
        response = _upload(writer, "vpn.ovpn", body)
    assert response.status_code == 200
    (made,) = model("feed.FeedFile").objects.all()
    assert (made.post_id, made.comment_id, made.uploaded_by_id, made.name) == (None, None, writer.user.pk, "vpn.ovpn")
    assert made.thumb == ""
    stored = made.file
    assert (stored.purpose, stored.owner_id, stored.status, stored.size) == ("feed", None, "pending", len(body))
    assert (protected_root / "incoming" / str(stored.pk)).read_bytes() == body
    queued = [tuple(job.args) for job in org.files_jobs() if job.func_name == SCAN]
    assert queued == [(str(stored.pk),)]


# --- 2. ранний отказ по числу файлов -----------------------------------------------------------------------------

def test_upload_early_refusal_post_attached_plus_have_reaches_10(protected_root):
    """FR-633, FR-642: прикреплённые к записи плюс свои непривязанные из `have` в сумме 10 — «У записи уже 10
    файлов» (`post_files_limit`) у поля `file`; в сумме 9 — файл принят. Так же для новой записи (0 прикреплённых)."""
    writer, post = _writer_post()
    for number in range(7):
        fd.attach(post, f"прикреплён-{number}.txt", uploaded_by=writer.user)
    have = _unbound(writer.user, 3)
    before = _counts()
    refused = _upload(writer, "лишний.txt", b"data", post=post, have=[item.pk for item in have])
    _refused(refused, "file", "post_files_limit", TEXT_POST_LIMIT)
    assert _counts() == before
    accepted = _upload(writer, "десятый.txt", b"data", post=post, have=[item.pk for item in have[:2]])
    assert accepted.status_code == 200 and _refusals(accepted) == []
    assert _counts()[0] == before[0] + 1
    fresh_have = _unbound(writer.user, 10, "новая")
    _refused(_upload(writer, "ещё.txt", b"data", have=[item.pk for item in fresh_have]),
             "file", "post_files_limit", TEXT_POST_LIMIT)
    ok = _upload(writer, "ещё.txt", b"data", have=[item.pk for item in fresh_have[:9]])
    assert ok.status_code == 200 and _refusals(ok) == []


def test_upload_early_refusal_comment_attached_plus_have_reaches_3(protected_root):
    """FR-633, FR-642: прикреплённые к комментарию плюс свои непривязанные из `have` в сумме 3 — «У комментария уже
    3 файла» (`comment_files_limit`); в сумме 2 — файл принят. Так же для нового комментария."""
    writer, post = _writer_post()
    commenter = fd.as_plain()
    comment = fd.comment(post, commenter.user, "Комментарий")
    fd.attach(comment, "прикреплён.txt", uploaded_by=commenter.user)
    have = _unbound(commenter.user, 2)
    before = _counts()
    refused = _upload(commenter, "лишний.txt", b"data", scope="comment", comment=comment,
                      have=[item.pk for item in have])
    _refused(refused, "file", "comment_files_limit", TEXT_COMMENT_LIMIT)
    assert _counts() == before
    accepted = _upload(commenter, "третий.txt", b"data", scope="comment", comment=comment, have=[have[0].pk])
    assert accepted.status_code == 200 and _refusals(accepted) == []
    extra = _unbound(commenter.user, 3, "новый")
    _refused(_upload(commenter, "ещё.txt", b"data", scope="comment", have=[item.pk for item in extra]),
             "file", "comment_files_limit", TEXT_COMMENT_LIMIT)
    ok = _upload(commenter, "ещё.txt", b"data", scope="comment", have=[item.pk for item in extra[:2]])
    assert ok.status_code == 200 and _refusals(ok) == []


def test_upload_early_refusal_counts_already_attached_on_edit(protected_root):
    """FR-633, FR-642: при правке уже прикреплённые считаются и без `have`: у записи 10 файлов — «У записи уже 10
    файлов», у комментария 3 — «У комментария уже 3 файла»; строк не прибавилось."""
    writer, post = _writer_post()
    for number in range(10):
        fd.attach(post, f"файл-{number}.txt", uploaded_by=writer.user)
    comment = fd.comment(post, writer.user, "Комментарий")
    for number in range(3):
        fd.attach(comment, f"к-{number}.txt", uploaded_by=writer.user)
    before = _counts()
    _refused(_upload(writer, "лишний.txt", b"data", post=post), "file", "post_files_limit", TEXT_POST_LIMIT)
    _refused(_upload(writer, "лишний.txt", b"data", scope="comment", comment=comment),
             "file", "comment_files_limit", TEXT_COMMENT_LIMIT)
    assert _counts() == before


def test_31st_unbound_upload_refused_too_many_files_without_post(protected_root):
    """FR-633: у сотрудника не больше 30 непривязанных файлов: 30-й принимается, 31-й — «Слишком много файлов без
    записи: опубликуйте запись или уберите лишние» (`too_many_unbound`) у поля `file`; записей не прибавилось; у
    другого сотрудника счёт свой."""
    writer = fd.as_writer()
    other = fd.as_plain()
    _unbound(writer.user, 29)
    thirtieth = _upload(writer, "тридцатый.txt", b"data")
    assert thirtieth.status_code == 200 and _refusals(thirtieth) == []
    before, posts = _counts(), _posts_count()
    _refused(_upload(writer, "тридцать-первый.txt", b"data"), "file", "too_many_unbound", TEXT_UNBOUND)
    assert _counts() == before and _posts_count() == posts
    elsewhere = _upload(other, "чужой-счёт.txt", b"data")
    assert elsewhere.status_code == 200 and _refusals(elsewhere) == []


# --- 3. привязка -----------------------------------------------------------------------------------------------

def test_publish_binds_files_by_conditional_update_with_uploader_parameter(django_capture_on_commit_callbacks):
    """FR-633: публикация привязывает файлы условным `UPDATE … WHERE id = ANY(%s) AND post_id IS NULL AND comment_id
    IS NULL AND uploaded_by_id = %s`; номер автора и номера файлов уходят параметрами, в тексте SQL их нет."""
    writer = fd.as_writer()
    items = _unbound(writer.user, 2)
    ids = [item.pk for item in items]
    with fd.queries_with_params() as pairs, django_capture_on_commit_callbacks(execute=True):
        response = _publish(writer, ids)
    assert response.status_code == 302
    updates = [(sql, params) for sql, params in pairs
               if sql.lstrip().upper().startswith("UPDATE") and "feed_feedfile" in sql]
    assert updates, "привязка файлов должна быть отдельным UPDATE таблицы feed_feedfile"
    sql, params = updates[0]
    lowered = " ".join(sql.lower().split())
    assert "post_id" in lowered and "is null" in lowered and "uploaded_by_id" in lowered
    assert "comment_id" in lowered
    flat = []
    for value in params or ():
        flat.extend(value if isinstance(value, (list, tuple, set)) else [value])
    assert writer.user.pk in flat and set(ids) <= set(flat), f"параметры: {params}"
    for number in [writer.user.pk, *ids]:
        assert re.search(rf"(?<![\w_]){number}(?![\w_])", sql) is None, f"{number} стоит в тексте SQL"
    (post,) = model("feed.Post").objects.all()
    assert sorted(_fresh(item).post_id for item in items) == [post.pk, post.pk]


def test_bind_fewer_rows_than_sent_rolls_back_with_missing_id_refusal(protected_root):
    """FR-633: привязано строк меньше, чем прислано (несуществующий номер или файл, уже привязанный к другой записи) —
    откат всей публикации и отказ «Файл не найден» (`file_missing`) у поля `files`; записи нет, свой свободный файл
    остался непривязанным; служба поднимает `FeedError("file_missing", "files")`."""
    writer, other_post = _writer_post()
    free = fd.attach(None, "свободный.txt", uploaded_by=writer.user)
    taken = fd.attach(other_post, "занят.txt", uploaded_by=writer.user)
    posts = _posts_count()
    for ids in ([free.pk, 99999999], [free.pk, taken.pk]):
        response = _publish(writer, ids, hx=True)
        _refused(response, "files", "file_missing", TEXT_MISSING)
        assert _posts_count() == posts
        assert _fresh(free).post_id is None
        assert _fresh(taken).post_id == other_post.pk
    errors = importlib.import_module("apps.feed.services.errors")
    with pytest.raises(errors.FeedError) as caught:
        with transaction.atomic():
            _svc("posts").publish(writer.user, {"kind": "post", "text": "Текст", "to": ["all"],
                                                "files": [free.pk, 99999999]})
    assert (caught.value.code, caught.value.field) == ("file_missing", "files")
    assert _posts_count() == posts and _fresh(free).post_id is None


def test_foreign_unbound_file_id_in_files_refused_nothing_bound(protected_root):
    """FR-633: чужой непривязанный номер в `files` — тот же отказ «Файл не найден», что у несуществующего; ничего не
    привязано, в том числе свой файл из того же запроса; чужой файл остался непривязанным у своего хозяина."""
    writer = fd.as_writer()
    stranger = fd.as_plain()
    own = fd.attach(None, "свой.txt", uploaded_by=writer.user)
    foreign = fd.attach(None, "чужой.txt", uploaded_by=stranger.user)
    posts = _posts_count()
    response = _publish(writer, [own.pk, foreign.pk], hx=True)
    _refused(response, "files", "file_missing", TEXT_MISSING)
    missing = _publish(writer, [own.pk, 99999999], hx=True)
    assert [item[1:] for item in _refusals(response)] == [item[1:] for item in _refusals(missing)]
    assert _posts_count() == posts
    assert (_fresh(own).post_id, _fresh(own).uploaded_by_id) == (None, writer.user.pk)
    assert (_fresh(foreign).post_id, _fresh(foreign).uploaded_by_id) == (None, stranger.user.pk)


def test_binding_same_file_twice_in_a_row_second_refused_bound_once(protected_root):
    """FR-633: два запроса подряд с одним файлом — первый привязывает, второй получает «Файл не найден»; файл
    привязан один раз к первой записи, второй записи нет."""
    writer = fd.as_writer()
    item = fd.attach(None, "один.txt", uploaded_by=writer.user)
    first = _publish(writer, [item.pk], "Первая запись")
    assert first.status_code == 302
    (first_post,) = model("feed.Post").objects.all()
    second = _publish(writer, [item.pk], "Вторая запись", hx=True)
    _refused(second, "files", "file_missing", TEXT_MISSING)
    assert model("feed.Post").objects.count() == 1
    assert _fresh(item).post_id == first_post.pk
    assert model("feed.FeedFile").objects.filter(file=item.file).count() == 1


def test_bind_11th_file_to_post_refused_counting_attached(protected_root):
    """FR-633, FR-642: одиннадцатый файл записи — «У записи уже 10 файлов» (`post_files_limit`) у поля `files`,
    считая уже прикреплённые: правка с одним новым к записи с 10 файлами и публикация с 11 файлами; новые файлы
    остались непривязанными."""
    writer, post = _writer_post()
    for number in range(10):
        fd.attach(post, f"файл-{number}.txt", uploaded_by=writer.user)
    extra = fd.attach(None, "лишний.txt", uploaded_by=writer.user)
    refused = _edit(writer, post, files=[extra.pk])
    _refused(refused, "files", "post_files_limit", TEXT_POST_LIMIT)
    assert model("feed.FeedFile").objects.filter(post=post).count() == 10
    assert _fresh(extra).post_id is None
    eleven = _unbound(writer.user, 11, "пачка")
    posts = _posts_count()
    _refused(_publish(writer, [item.pk for item in eleven], hx=True), "files", "post_files_limit", TEXT_POST_LIMIT)
    assert _posts_count() == posts
    assert all(_fresh(item).post_id is None for item in eleven)


def test_bind_4th_file_to_comment_refused_counting_attached(protected_root):
    """FR-633, FR-642: четвёртый файл комментария — «У комментария уже 3 файла» (`comment_files_limit`) у поля
    `files`, считая прикреплённые: новый комментарий с 4 файлами и правка комментария с 1 файлом и 3 новыми;
    комментария нет, файлы остались непривязанными."""
    writer, post = _writer_post()
    commenter = fd.as_plain()
    four = _unbound(commenter.user, 4)
    comments_before = model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}").count()
    response = commenter.client.post(f"/feed/{post.pk}/comments/", {"text": "Комментарий", "files": [i.pk for i in four]},
                                     **HX)
    _refused(response, "files", "comment_files_limit", TEXT_COMMENT_LIMIT)
    assert model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}").count() == comments_before
    assert all(_fresh(item).comment_id is None for item in four)
    comment = fd.comment(post, commenter.user, "Свой комментарий")
    fd.attach(comment, "прикреплён.txt", uploaded_by=commenter.user)
    new = _unbound(commenter.user, 3, "новый")
    edited = commenter.client.post(f"/feed/comments/{comment.pk}/edit/",
                                   {"text": "Свой комментарий", "files": [i.pk for i in new]})
    _refused(edited, "files", "comment_files_limit", TEXT_COMMENT_LIMIT)
    assert model("feed.FeedFile").objects.filter(comment_id=comment.pk).count() == 1
    assert all(_fresh(item).comment_id is None for item in new)


def test_bind_limits_checked_under_post_select_for_update(protected_root):
    """FR-633: пределы привязки проверяются под `SELECT … FOR UPDATE` строки записи `feed_post`: замок стоит раньше
    условного `UPDATE` файлов (правка записи с файлами)."""
    writer, post = _writer_post()
    item = fd.attach(None, "новый.txt", uploaded_by=writer.user)
    data = {"text": "Новый текст", "to": ["all"], "files": [item.pk]}
    with fd.capture_sql() as sqls:
        _svc("posts").edit(writer.user, post.pk, data)
    locking = fd.assert_for_update(sqls, "feed_post")
    update_at = next(index for index, sql in enumerate(sqls)
                     if sql.lstrip().upper().startswith("UPDATE") and "feed_feedfile" in sql)
    assert sqls.index(locking) < update_at
    assert _fresh(item).post_id == post.pk


# --- 4. «убрать» ----------------------------------------------------------------------------------------------

def test_remove_before_publish_only_own_unbound_file(django_capture_on_commit_callbacks, protected_root):
    """FR-633: `POST /feed/files/<id>/delete/` убирает только свой непривязанный файл (200, пустое тело, строки и
    файл на диске стёрты); чужой, привязанный и несуществующий — 404 одним и тем же ответом, ничего не удалено;
    служба `files.remove_unbound` — `Http404`."""
    writer, post = _writer_post()
    stranger = fd.as_plain()
    mine = fd.attach(None, "мой.txt", uploaded_by=writer.user, write=True)
    foreign = fd.attach(None, "чужой.txt", uploaded_by=stranger.user, write=True)
    bound = fd.attach(post, "привязан.txt", uploaded_by=writer.user, write=True)
    before = _counts()
    answers = []
    for number in (foreign.pk, bound.pk, 99999999):
        answers.append(writer.client.post(f"/feed/files/{number}/delete/", **HX))
    assert [response.status_code for response in answers] == [404, 404, 404]
    assert support.same_failure(*answers)
    assert _counts() == before
    with pytest.raises(Http404):
        _svc("files").remove_unbound(writer.user, foreign.pk)
    with pytest.raises(Http404):
        _svc("files").remove_unbound(writer.user, bound.pk)
    stored_id = mine.file_id
    assert (protected_root / "attachments" / str(stored_id)).is_file()
    with django_capture_on_commit_callbacks(execute=True):
        response = writer.client.post(f"/feed/files/{mine.pk}/delete/", **HX)
    assert response.status_code == 200 and response.content.strip() == b""
    assert not model("feed.FeedFile").objects.filter(pk=mine.pk).exists()
    assert not model("core.StoredFile").objects.filter(pk=stored_id).exists()
    for folder in ("incoming", "attachments"):
        assert not (protected_root / folder / str(stored_id)).exists(), folder
    assert model("feed.FeedFile").objects.filter(pk__in=[foreign.pk, bound.pk]).count() == 2


def test_remove_on_edit_foreign_unbound_or_missing_id_same_refusal_nothing_deleted(protected_root):
    """FR-633: «убрать» при правке отбирает номера только среди файлов этой записи: чужой непривязанный, файл другой
    записи, файл комментария этой записи и несуществующий номер — один и тот же отказ «Файл не найден»; ничего не
    удалено, свой файл записи цел."""
    writer, post = _writer_post()
    other_post = fd.make_post(writer.user, to=("all",), text="Другая запись")
    stranger = fd.as_plain()
    kept = fd.attach(post, "остаётся.txt", uploaded_by=writer.user, write=True)
    comment = fd.comment(post, writer.user, "Комментарий")
    in_comment = fd.attach(comment, "в-комментарии.txt", uploaded_by=writer.user, write=True)
    foreign = fd.attach(None, "чужой.txt", uploaded_by=stranger.user, write=True)
    elsewhere = fd.attach(other_post, "другая.txt", uploaded_by=writer.user, write=True)
    before = _counts()
    shapes = []
    for number in (foreign.pk, elsewhere.pk, in_comment.pk, 99999999):
        response = _edit(writer, post, remove=[number])
        _refused(response, "files", "file_missing", TEXT_MISSING)
        shapes.append([item for item in _refusals(response)])
        assert _counts() == before, number
    assert all(shape == shapes[0] for shape in shapes)
    assert model("feed.FeedFile").objects.filter(pk__in=[kept.pk, in_comment.pk, foreign.pk, elsewhere.pk]).count() == 4
    assert _fresh(kept).post_id == post.pk


def test_remove_on_edit_deletes_row_and_stored_file_in_transaction_disk_after_commit(
        django_capture_on_commit_callbacks, protected_root):
    """FR-633: отмеченный при правке файл удаляется при сохранении: строки `FeedFile` и `StoredFile` — в транзакции,
    файлы (оригинал и эскиз) с диска — только после фиксации; неотмеченный файл остаётся."""
    from django.conf import settings

    writer, post = _writer_post()
    gone = fd.attach(post, "уходит.png", uploaded_by=writer.user, write=True, thumb=True)
    kept = fd.attach(post, "остаётся.txt", uploaded_by=writer.user, write=True)
    paths = [protected_root / "attachments" / str(gone.file_id), protected_root / gone.thumb]
    assert settings.PROTECTED_ROOT == protected_root and all(path.is_file() for path in paths)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = _edit(writer, post, remove=[gone.pk])
    assert response.status_code == 302
    assert not model("feed.FeedFile").objects.filter(pk=gone.pk).exists()
    assert not model("core.StoredFile").objects.filter(pk=gone.file_id).exists()
    assert all(path.is_file() for path in paths), "до фиксации диск трогать нельзя"
    assert callbacks, "стирание поставлено на фиксацию"
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in paths)
    assert _fresh(kept).post_id == post.pk and (protected_root / "attachments" / str(kept.file_id)).is_file()


# --- 5. ограничение базы ------------------------------------------------------------------------------------------

def test_db_check_comment_set_implies_post_set(protected_root):
    """FR-633: ограничение `feed_feedfile_comment_needs_post`: строка с комментарием и без записи не вставляется и не
    обновляется (`IntegrityError`); комментарий вместе с записью и одна запись допустимы."""
    writer, post = _writer_post()
    comment = fd.comment(post, writer.user, "Комментарий")
    loose = fd.attach(None, "без-записи.txt", uploaded_by=writer.user)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            model("feed.FeedFile").objects.filter(pk=loose.pk).update(comment=comment)
    stored = model("core.StoredFile").objects.create(purpose="feed", owner=None, size=1, sha256="0" * 64,
                                                     content_type="text/plain", status="pending")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            model("feed.FeedFile").objects.create(post=None, comment=comment, file=stored, name="сирота.txt",
                                                  uploaded_by=writer.user, uploaded_at=post.published_at)
    assert _fresh(loose).comment_id is None
    both = fd.attach(comment, "оба.txt", uploaded_by=writer.user)
    only_post = fd.attach(post, "запись.txt", uploaded_by=writer.user)
    assert (both.post_id, both.comment_id) == (post.pk, comment.pk)
    assert (only_post.post_id, only_post.comment_id) == (post.pk, None)
