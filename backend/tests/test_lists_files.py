"""T-6121: файлы записи списка — прикрепление, пределы, проверка ClamAV, выдача, удаление (FR-509, FR-514, FR-536,
FR-537, FR-546, NFR-505, NFR-512). Сценарий 10 спеки 006 (серверная часть: решение 19 задач).

Прикрепить `POST /lists/<id>/<n>/files/`, скачать `GET …/files/<file_id>/`, удалить `POST …/files/<file_id>/delete/`;
службы `apps.lists.services.files` (`attach`, `remove`, `still_waiting`, `clean`, `found`) и запись
`FilePurpose("lists")` точки `file_purposes`. ClamAV подменяется только помощниками `scan_clean`, `scan_found`,
`scan_unavailable`, запись файла — `fail_file_write`; том `protected` настоящий (`protected_root`). Замки — по SQL
(решение 6 задач). Код среза на уровне модуля не импортируется (CONTRACT-006, шапка). Тексты отказов — литералы раздела 12.

`<file_id>` в адресах, в `files.remove` и в `li[data-file-id]` — `RecordFile.pk` (ответ Opus О1, CONTRACT-006, 15.3).
У файлов, которые тест создаёт помощником, номер строки `RecordFile` уводится от номера её `StoredFile` (`_distinct`),
чтобы реализация на `StoredFile.pk` не прошла случайно.
"""
import datetime
import hashlib
import importlib
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.utils import timezone

from tests import support
from tests import support_lists as ls
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX

pytestmark = pytest.mark.django_db

MB = 1024 * 1024
SCAN = "apps.core.tasks.scan_file"
TEXT_TOO_BIG = "Файл больше 20 МБ"
TEXT_REFUSED = "Файл такого типа не принимается"
TEXT_LIMIT = "У записи уже 20 файлов"
TEXT_HAS_FILE = "В поле уже есть файл"
TEXT_ARCHIVED = "Запись в архиве"
TEXT_WRITE_FAILED = "Не удалось сохранить файл"


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

def _files():
    return importlib.import_module("apps.lists.services.files")


def _errors():
    return importlib.import_module("apps.lists.services.errors")


def _m(name: str):
    return support.model(f"lists.{name}")


def _world(*, multiple: bool = True, extra_field: bool = False):
    """Список со строкой и полем «файл», правящий и сохранённая запись."""
    lst = ls.make_list()
    text = ls.add_field(lst, "string", "Серийный номер")
    field = ls.add_field(lst, "file", "Акт", multiple=multiple)
    other = ls.add_field(lst, "file", "Фото", multiple=True) if extra_field else None
    editor = ls.as_editor(lst)
    record = ls.make_record(lst, "Сервер", {text.code: "SN-1"}, created_by=editor.user)
    return SimpleNamespace(lst=lst, text=text, field=field, other=other, editor=editor, record=record)


def _base(lst, record) -> str:
    return f"/lists/{lst.pk}/{record.number}/"


def _upload(name: str, data: bytes):
    return SimpleUploadedFile(name, data)


def _post_file(client, lst, record, field, name: str, data: bytes, *, hx: bool = True):
    return client.post(_base(lst, record) + "files/", {"field": field.code, "file": _upload(name, data)},
                       **(HX if hx else {}))


def _distinct(made):
    """Номер строки `RecordFile` уводится от номера её `StoredFile`: `<file_id>` — `RecordFile.pk` (ответ Opus О1),
    и при совпавших номерах тест не отличил бы реализацию на `StoredFile.pk`."""
    distinct_id = made.pk + 7919  # от `RecordFile.pk`: `file_id` — UUID `StoredFile` (поправка Opus при исполнении)
    _m("RecordFile").objects.filter(pk=made.pk).update(id=distinct_id)
    return _m("RecordFile").objects.get(pk=distinct_id)


def _file(record, field, *, status="clean", write=False, name="акт.pdf", data=None, uploaded_by=None):
    return _distinct(ls.attach_file(record, field, name, data, status=status, write=write, uploaded_by=uploaded_by))


def _counts() -> tuple[int, int]:
    """Число строк `RecordFile` и `StoredFile` назначения «файл записи списка»."""
    return (_m("RecordFile").objects.count(), support.model("core.StoredFile").objects.filter(purpose="lists").count())


def _disk(protected_root) -> list:
    return sorted(str(p.relative_to(protected_root)) for p in protected_root.rglob("*") if p.is_file())


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _block(response, field) -> Node:
    """Блок `[data-lists-files=<код поля>]` из ответа (фрагмент или страница)."""
    return q1(tree(response), data_lists_files=field.code)


def _rows(block) -> list:
    return q(block, "li", data_file_id=True)


def _row_of(block, made) -> Node:
    found = [row for row in _rows(block) if row.attrs["data-file-id"] == str(made.pk)]
    assert len(found) == 1, f"в блоке нет строки файла с data-file-id={made.pk} (RecordFile.pk)"
    return found[0]


def _refused(response, code: str, text: str, *, where: str = "file") -> None:
    """Отказ по контракту (10.1, 10.2): 200, `[data-error=<где>][data-code=<код>]`, текст раздела 12."""
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    assert q(tree(response), data_error=where, data_code=code), f"нет [data-error={where}][data-code={code}]"
    assert text in response.content.decode("utf-8"), f"в ответе нет текста {text!r}"


def _scan(stored, capture):
    """Исполняет проверку файла диспетчером ядра внутри фиксации (стирание файлов идёт после неё)."""
    from apps.core import tasks

    with capture(execute=True):
        tasks.scan_file(str(stored.pk))


def _attach_via_service(world, name, data, capture, field=None):
    with capture(execute=True):
        return _files().attach(world.lst, world.record.number, field_code=(field or world.field).code,
                               name=name, data=data, actor=world.editor.user)


def _state(record) -> tuple:
    row = _fresh(record)
    return row.version, row.values, row.title


def _first_sql(sqls, predicate):
    for number, sql in enumerate(sqls):
        if predicate(sql):
            return number
    return None


def _is_lock(sql: str) -> bool:
    return "pg_advisory_xact_lock" in sql


def _is_select_of(sql: str, table: str) -> bool:
    return sql.lstrip().upper().startswith("SELECT") and f'"{table}"' in sql


def _assert_shared_lock_then_record_for_update(sqls, lst, *, schema_read: bool):
    locks = ls.list_locks(sqls)
    assert locks, "замка списка нет"
    assert locks[0] == ls.ListLock("shared", ls.list_no(lst.pk)), locks
    assert all(lock.kind == "shared" for lock in locks), "файлы берут только разделяемый замок списка"
    lock_at = _first_sql(sqls, _is_lock)
    locked = _first_sql(sqls, lambda sql: _is_select_of(sql, "lists_record") and "FOR UPDATE" in sql.upper())
    assert locked is not None, "запись не взята `SELECT … FOR UPDATE`"
    assert lock_at < locked, "замок списка раньше `FOR UPDATE` записи"
    early = _first_sql(sqls[:lock_at], lambda sql: _is_select_of(sql, "lists_record"))
    assert early is None, "запись читается только после замка списка"
    field_read = _first_sql(sqls, lambda sql: _is_select_of(sql, "lists_field"))
    if schema_read:
        assert field_read is not None and field_read > lock_at, "схема читается после замка"
    else:
        assert field_read is None or field_read > lock_at


# --- 1. прикрепление --------------------------------------------------------------------------------------

def test_editor_attaches_file_to_saved_record_and_file_is_listed_as_checking(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536, NFR-505: правящий прикрепляет файл к сохранённой записи: в блоке поля строка «проверяется» без ссылки, в базе `RecordFile` и `StoredFile` ждущий, файл в `incoming/`, проверка поставлена; обычный запрос — 302 на карточку."""
    world = _world()
    page = world.editor.client.get(_base(world.lst, world.record))
    assert page.status_code == 200
    root = tree(page)
    form = q1(root, "form", data_action="file-attach")
    q1(form, "input", name="file")
    assert q(form, name="field"), "в форме есть поле `field` (код поля «файл»)"
    data = b"client config for the new server\n"
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_file(world.editor.client, world.lst, world.record, world.field, "акт приёмки.txt", data)
    assert response.status_code == 200
    (attached,) = _m("RecordFile").objects.filter(record=world.record)
    assert (attached.field_id, attached.name, attached.uploaded_by_id) == (
        world.field.pk, "акт приёмки.txt", world.editor.user.pk)
    stored = attached.file
    assert (stored.purpose, stored.owner_id, stored.status, stored.size) == ("lists", None, "pending", len(data))
    assert (protected_root / "incoming" / str(stored.pk)).read_bytes() == data
    (row,) = _rows(_block(response, world.field))
    assert row.attrs["data-file-id"] == str(attached.pk)
    assert row.attrs["data-scan"] == "pending" and "проверяется" in row.text()
    assert "акт приёмки.txt" in row.text()
    assert q(row, "a", data_action="file-download") == [], "до проверки ссылки нет"
    queued = {tuple(job.args) for job in org.files_jobs() if job.func_name == SCAN}
    assert queued == {(str(stored.pk),)}, "проверка ставится после фиксации"
    # обычный запрос: 302 на карточку записи, файл виден и на странице
    with django_capture_on_commit_callbacks(execute=True):
        plain = _post_file(world.editor.client, world.lst, world.record, world.field, "второй.txt", b"two", hx=False)
    assert plain.status_code == 302 and plain["Location"] == _base(world.lst, world.record)
    rows = _rows(_block(world.editor.client.get(_base(world.lst, world.record)), world.field))
    assert len(rows) == 2 and {row.attrs["data-scan"] for row in rows} == {"pending"}


def test_attach_by_reader_is_403_and_by_non_reader_is_404(django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-514: читающий список получает 403, не читающий — 404 (и на НХ, и на обычном запросе; в службах отказ без записи в базу); файл не принят, на диске пусто."""
    world = _world()
    reader = ls.as_reader(world.lst)
    outsider_user = support.make_employee()
    outsider = support.logged_in(outsider_user)
    before = _counts()
    for client, expected in ((reader.client, 403), (outsider, 404)):
        for hx in (True, False):
            with django_capture_on_commit_callbacks(execute=True):
                response = _post_file(client, world.lst, world.record, world.field, "акт.txt", b"data", hx=hx)
            assert response.status_code == expected, (expected, hx)
    assert _counts() == before
    assert _disk(protected_root) == []
    assert org.files_jobs() == []
    # одна и та же картина у «нет» и у запроса к несуществующей записи
    missing = _post_file(outsider, world.lst, world.record, world.field, "акт.txt", b"data")
    absent = outsider.post(f"/lists/{world.lst.pk}/9999/files/", {"field": world.field.code, "file": _upload("а.txt", b"d")}, **HX)
    assert support.same_failure(missing, absent)
    editor_response = _post_file(world.editor.client, world.lst, world.record, world.field, "правит.txt", b"ok")
    assert editor_response.status_code == 200 and _counts()[0] == 1


def test_attach_to_missing_record_number_is_404_and_to_archived_record_refused_record_archived(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-546: нет записи с таким номером (в том числе удалённой навсегда) — 404 и в службе `Http404`; запись в архиве — 200 `[role=alert][data-code=record_archived]` «Запись в архиве», в службе `RecordArchived`; в обоих случаях ничего не записано."""
    from django.http import Http404

    world = _world()
    archived = ls.make_record(world.lst, "Старая запись", created_by=world.editor.user, archived=True)
    purged = ls.make_record(world.lst, "Удалена навсегда", created_by=world.editor.user)
    purged_number = purged.number
    _m("Record").objects.filter(pk=purged.pk).delete()
    assert purged_number < _fresh(world.lst).next_number
    before = _counts()
    for number in (purged_number, _fresh(world.lst).next_number + 40):
        for hx in (True, False):
            response = world.editor.client.post(
                f"/lists/{world.lst.pk}/{number}/files/", {"field": world.field.code, "file": _upload("а.txt", b"d")},
                **(HX if hx else {}))
            assert response.status_code == 404, (number, hx)
        with pytest.raises(Http404):
            _files().attach(world.lst, number, field_code=world.field.code, name="а.txt", data=b"d",
                            actor=world.editor.user)
    response = _post_file(world.editor.client, world.lst, archived, world.field, "поздно.txt", b"data")
    assert response.status_code == 200
    assert q(tree(response), role="alert", data_code="record_archived")
    assert TEXT_ARCHIVED in response.content.decode("utf-8")
    with pytest.raises(_errors().RecordArchived):
        _files().attach(world.lst, archived.number, field_code=world.field.code, name="поздно.txt", data=b"data",
                        actor=world.editor.user)
    assert _counts() == before
    assert _disk(protected_root) == [] and org.files_jobs() == []


def test_attach_and_delete_take_shared_list_lock_then_record_for_update(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536: и прикрепление, и удаление берут разделяемый замок списка (ключ — остаток от деления номера на 2^31), только потом `SELECT … FOR UPDATE` записи; запись и схема читаются после замка; исключительного замка нет."""
    world = _world()
    with ls.capture_sql() as attach_sqls:
        made = _files().attach(world.lst, world.record.number, field_code=world.field.code, name="акт.txt",
                               data=b"data", actor=world.editor.user)
    _assert_shared_lock_then_record_for_update(attach_sqls, world.lst, schema_read=True)
    made = _distinct(made)
    with ls.capture_sql() as remove_sqls:
        _files().remove(world.lst, world.record.number, made.pk, actor=world.editor.user)
    _assert_shared_lock_then_record_for_update(remove_sqls, world.lst, schema_read=False)
    assert _counts() == (0, 0)


# --- 2. пределы и отказы по содержимому ---------------------------------------------------------------------

def test_file_of_exactly_20_mb_is_accepted(django_capture_on_commit_callbacks, protected_root):
    """FR-536, NFR-505: файл ровно 20 МБ принимается: строки в базе, размер, файл в `incoming/`, отказа в ответе нет."""
    world = _world()
    response = _post_file(world.editor.client, world.lst, world.record, world.field, "ровно.txt", b"a" * (20 * MB))
    assert response.status_code == 200
    assert q(tree(response), data_error=True) == [] and q(tree(response), role="alert") == []
    (attached,) = _m("RecordFile").objects.filter(record=world.record)
    assert attached.file.size == 20 * MB
    assert (protected_root / "incoming" / str(attached.file_id)).stat().st_size == 20 * MB
    (row,) = _rows(_block(response, world.field))
    assert row.attrs["data-scan"] == "pending"


def test_file_of_20_mb_plus_one_byte_is_refused_file_over_20_mb(django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-546, NFR-505: файл на байт больше 20 МБ — 200 с `[data-error=file][data-code=file_too_big]` «Файл больше 20 МБ»; в службе `ListsError` с кодом `file_too_big`; список файлов прежний, на диске и в базе новых строк нет."""
    world = _world()
    kept = _file(world.record, world.field, write=True)
    before, disk = _counts(), _disk(protected_root)
    response = _post_file(world.editor.client, world.lst, world.record, world.field, "больше.txt", b"a" * (20 * MB + 1))
    _refused(response, "file_too_big", TEXT_TOO_BIG)
    assert [row.attrs["data-file-id"] for row in _rows(_block(response, world.field))] == [str(kept.pk)]
    with pytest.raises(_errors().ListsError) as caught:
        _files().attach(world.lst, world.record.number, field_code=world.field.code, name="больше.txt",
                        data=b"a" * (20 * MB + 1), actor=world.editor.user)
    assert caught.value.code == "file_too_big" and caught.value.field == "file"
    assert _counts() == before and _disk(protected_root) == disk
    assert org.files_jobs() == []


def test_twenty_first_file_across_all_file_fields_is_refused_record_has_20_files(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-546: двадцать файлов считаются по всем полям «файл» записи вместе (и ждущие, и в карантине): двадцатый принимается, двадцать первый в любое из полей — `[data-error=file][data-code=files_limit]` «У записи уже 20 файлов», строк не прибавилось."""
    world = _world(extra_field=True)
    statuses = ("clean", "pending", "quarantine")
    for number in range(10):
        ls.attach_file(world.record, world.field, f"а{number}.txt", status=statuses[number % 3])
    for number in range(9):
        ls.attach_file(world.record, world.other, f"б{number}.txt", status=statuses[number % 3])
    assert _counts()[0] == 19
    twentieth = _post_file(world.editor.client, world.lst, world.record, world.other, "двадцатый.txt", b"data")
    assert twentieth.status_code == 200 and q(tree(twentieth), data_error=True) == []
    assert _counts()[0] == 20
    before, disk = _counts(), _disk(protected_root)
    for field in (world.field, world.other):
        for hx in (True, False):
            response = _post_file(world.editor.client, world.lst, world.record, field, "лишний.txt", b"data", hx=hx)
            _refused(response, "files_limit", TEXT_LIMIT)
    with pytest.raises(_errors().ListsError) as caught:
        _files().attach(world.lst, world.record.number, field_code=world.field.code, name="лишний.txt", data=b"data",
                        actor=world.editor.user)
    assert caught.value.code == "files_limit" and caught.value.field == "file"
    assert _counts() == before and _disk(protected_root) == disk


def test_second_file_in_field_without_multiple_is_refused_field_already_has_file(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-546: в поле без «несколько» второй файл — `[data-error=file][data-code=field_has_file]` «В поле уже есть файл»; в соседнем поле «несколько» принимаются два; после удаления первого файла в одиночное поле снова можно прикрепить."""
    world = _world(multiple=False, extra_field=True)
    first = _post_file(world.editor.client, world.lst, world.record, world.field, "первый.txt", b"one")
    assert first.status_code == 200 and q(tree(first), data_error=True) == []
    (attached,) = _m("RecordFile").objects.filter(record=world.record, field=world.field)
    before, disk = _counts(), _disk(protected_root)
    for hx in (True, False):
        _refused(_post_file(world.editor.client, world.lst, world.record, world.field, "второй.txt", b"two", hx=hx),
                 "field_has_file", TEXT_HAS_FILE)
    with pytest.raises(_errors().ListsError) as caught:
        _files().attach(world.lst, world.record.number, field_code=world.field.code, name="второй.txt", data=b"two",
                        actor=world.editor.user)
    assert caught.value.code == "field_has_file" and caught.value.field == "file"
    assert _counts() == before and _disk(protected_root) == disk
    for name in ("фото1.txt", "фото2.txt"):
        response = _post_file(world.editor.client, world.lst, world.record, world.other, name, b"photo")
        assert response.status_code == 200 and q(tree(response), data_error=True) == [], name
    assert _m("RecordFile").objects.filter(record=world.record, field=world.other).count() == 2
    attached = _distinct(attached)
    with django_capture_on_commit_callbacks(execute=True):
        removed = world.editor.client.post(_base(world.lst, world.record) + f"files/{attached.pk}/delete/", **HX)
    assert removed.status_code == 200
    again = _post_file(world.editor.client, world.lst, world.record, world.field, "третий.txt", b"three")
    assert again.status_code == 200 and q(tree(again), data_error=True) == []
    assert list(_m("RecordFile").objects.filter(record=world.record, field=world.field).values_list("name", flat=True)) == [
        "третий.txt"]


def test_executable_with_foreign_extension_and_encrypted_archive_are_refused_by_content_type_not_accepted(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-546: исполняемые файлы под чужим расширением (скрипт под `.txt`, PE под `.png`, ELF под `.jpg`) и архивы с паролем (ZIP ZipCrypto и AES, RAR5) отказываются по содержимому: `[data-error=file][data-code=file_type_refused]` «Файл такого типа не принимается», ничего не сохранено; обычный архив принимается."""
    world = _world()
    before = _counts()
    cases = [("заметки.txt", b"#!/bin/sh\necho hello\n"), ("photo.png", sd.sample("exe_pe.bin")),
             ("picture.jpg", sd.sample("exe_elf.bin")), ("архив.zip", sd.sample("enc_zip_zipcrypto.zip")),
             ("данные.dat", sd.sample("enc_zip_aes.zip")), ("архив.rar", sd.sample("enc_rar5_data.rar"))]
    for name, data in cases:
        response = _post_file(world.editor.client, world.lst, world.record, world.field, name, data)
        _refused(response, "file_type_refused", TEXT_REFUSED)
        assert _counts() == before, name
        with pytest.raises(_errors().ListsError) as caught:
            _files().attach(world.lst, world.record.number, field_code=world.field.code, name=name, data=data,
                            actor=world.editor.user)
        assert caught.value.code == "file_type_refused" and caught.value.field == "file", name
    assert _counts() == before and _disk(protected_root) == [] and org.files_jobs() == []
    plain = _post_file(world.editor.client, world.lst, world.record, world.field, "обычный.zip", sd.sample("plain.zip"))
    assert plain.status_code == 200 and q(tree(plain), data_error=True) == []
    assert _counts()[0] == 1


def test_attach_stores_file_through_uploads_store_with_lists_purpose(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536: файл записи хранится через `uploads.store` с назначением «файл записи списка» (`StoredFile.Purpose.LISTS`, значение `lists`): `owner` пусто, `pending`, размер и `sha256` по содержимому, байты в `incoming/<id>`, задание проверки в очереди `files` после фиксации."""
    world = _world()
    purpose = support.model("core.StoredFile").Purpose.LISTS
    assert purpose == "lists" and purpose.label == "файл записи списка"
    data = b"report body \x00\x01 binary tail"
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        made = _files().attach(world.lst, world.record.number, field_code=world.field.code, name="отчёт.dat",
                               data=data, actor=world.editor.user)
        assert org.files_jobs() == [], "проверка ставится только после фиксации"
    assert callbacks, "постановка проверки — на фиксацию"
    for callback in callbacks:
        callback()
    stored = _fresh(made.file)
    assert (stored.purpose, stored.owner_id, stored.status, stored.size) == ("lists", None, "pending", len(data))
    assert stored.sha256 == hashlib.sha256(data).hexdigest() and stored.scanned_at is None
    assert (protected_root / "incoming" / str(stored.pk)).read_bytes() == data
    assert (made.record_id, made.field_id, made.name, made.uploaded_by_id) == (
        world.record.pk, world.field.pk, "отчёт.dat", world.editor.user.pk)
    assert {tuple(job.args) for job in org.files_jobs() if job.func_name == SCAN} == {(str(stored.pk),)}
    assert support.model("core.StoredFile").objects.exclude(pk=stored.pk).filter(purpose="lists").count() == 0


# --- 3. итог проверки антивирусом (запись `FilePurpose("lists")`) ----------------------------------------------

def test_clean_scan_moves_file_to_attachments_and_file_becomes_downloadable(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-536, FR-537, NFR-505: чисто — файл из `incoming/` в `attachments/<id>`, статус `clean`, `scanned_at` стоит, прежний путь стёрт, в блоке ссылка скачивания; до проверки адрес файла отвечает 404, после — 200."""
    world = _world()
    data = b"clean document body"
    made = _distinct(_attach_via_service(world, "чистый.txt", data, django_capture_on_commit_callbacks))
    stored = made.file
    incoming = protected_root / "incoming" / str(stored.pk)
    url = _base(world.lst, world.record) + f"files/{made.pk}/"
    assert incoming.read_bytes() == data and world.editor.client.get(url).status_code == 404
    calls = org.scan_clean(monkeypatch)
    _scan(stored, django_capture_on_commit_callbacks)
    assert calls == [str(incoming)], "антивирусу ушёл путь из `incoming/`"
    _fresh(stored)
    assert stored.status == "clean" and stored.scanned_at is not None
    assert (protected_root / "attachments" / str(stored.pk)).read_bytes() == data
    assert not incoming.exists()
    assert _m("RecordFile").objects.filter(pk=made.pk).exists()
    row = _row_of(_block(world.editor.client.get(_base(world.lst, world.record)), world.field), made)
    assert row.attrs["data-scan"] == "clean"
    assert q1(row, "a", data_action="file-download").attrs["href"] == url
    assert world.editor.client.get(url).status_code == 200


def test_found_scan_puts_file_to_quarantine(django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-536, NFR-505: найден вирус — файл в `quarantine/<id>` с подписью, строки остались, в блоке «в карантине» без ссылки, адрес файла отвечает 404."""
    world = _world()
    made = _distinct(_attach_via_service(world, "заражён.txt", org.eicar_bytes(), django_capture_on_commit_callbacks))
    stored = made.file
    org.scan_found(monkeypatch, "Eicar-Signature")
    _scan(stored, django_capture_on_commit_callbacks)
    _fresh(stored)
    assert stored.status == "quarantine" and stored.signature == "Eicar-Signature" and stored.scanned_at is not None
    assert (protected_root / "quarantine" / str(stored.pk)).is_file()
    assert not (protected_root / "incoming" / str(stored.pk)).exists()
    assert not (protected_root / "attachments" / str(stored.pk)).exists()
    assert _m("RecordFile").objects.filter(pk=made.pk).exists()
    row = _row_of(_block(world.editor.client.get(_base(world.lst, world.record)), world.field), made)
    assert row.attrs["data-scan"] == "quarantine" and "в карантине" in row.text()
    assert q(row, "a", data_action="file-download") == []
    assert world.editor.client.get(_base(world.lst, world.record) + f"files/{made.pk}/").status_code == 404


def test_encrypted_heuristic_scan_removes_record_file_row(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-536, NFR-505: подпись `Heuristics.Encrypted.*` — не вирус: строки `RecordFile` и `StoredFile` удалены, файл стёрт из всех папок, в карантин не уходит, запись цела."""
    world = _world()
    state = _state(world.record)
    made = _attach_via_service(world, "архив.dat", sd.sample("nested_enc_zip.zip"), django_capture_on_commit_callbacks)
    stored_id = made.file_id
    assert (protected_root / "incoming" / str(stored_id)).is_file()
    org.scan_found(monkeypatch, "Heuristics.Encrypted.Zip")
    _scan(made.file, django_capture_on_commit_callbacks)
    assert not _m("RecordFile").objects.filter(pk=made.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=stored_id).exists()
    for folder in ("incoming", "attachments", "quarantine"):
        assert not (protected_root / folder / str(stored_id)).exists(), folder
    assert _rows(_block(world.editor.client.get(_base(world.lst, world.record)), world.field)) == []
    assert _state(world.record) == state


def test_clamav_unavailable_keeps_record_and_file_checking_and_requeue_pending_scans_retries(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """NFR-512, FR-536: ClamAV недоступен — файл остаётся «проверяется», запись, её значения и версия целы, страницы работают, файл не скачивается, задание уходит на повтор; потерянное задание ставит заново ежечасное `requeue_pending_scans`, после чего файл проходит проверку."""
    from apps.core import tasks

    world = _world()
    state = _state(world.record)
    made = _distinct(_attach_via_service(world, "ждёт.txt", b"waiting data", django_capture_on_commit_callbacks))
    stored = made.file
    calls = org.scan_unavailable(monkeypatch)
    org.run_files_worker()
    assert calls, "антивирус вызывали"
    _fresh(stored)
    assert stored.status == "pending" and stored.attempts == 1 and stored.last_error
    assert str(protected_root) not in stored.last_error
    assert (protected_root / "incoming" / str(stored.pk)).is_file()
    assert _m("RecordFile").objects.filter(pk=made.pk).exists() and _state(world.record) == state
    page = world.editor.client.get(_base(world.lst, world.record))
    assert page.status_code == 200
    row = _row_of(_block(page, world.field), made)
    assert row.attrs["data-scan"] == "pending" and "проверяется" in row.text()
    assert world.editor.client.get(_base(world.lst, world.record) + f"files/{made.pk}/").status_code == 404
    # второй файл: задание потеряно (постановка не исполнена), ждёт дольше часа — повтор ставит ежечасное задание
    with django_capture_on_commit_callbacks(execute=False):
        lost = _distinct(_files().attach(world.lst, world.record.number, field_code=world.field.code, name="потерян.txt",
                                      data=b"lost job", actor=world.editor.user))
    assert [job for job in org.files_jobs() if tuple(job.args) == (str(lost.file_id),)] == []
    support.model("core.StoredFile").objects.filter(pk=lost.file_id).update(
        created_at=timezone.now() - datetime.timedelta(hours=2))
    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.requeue_pending_scans() == 1
    assert [tuple(job.args) for job in org.files_jobs() if job.func_name == SCAN] == [(str(lost.file_id),)]
    org.scan_clean(monkeypatch)
    org.run_files_worker()
    assert _fresh(lost.file).status == "clean"
    assert world.editor.client.get(_base(world.lst, world.record) + f"files/{lost.pk}/").status_code == 200
    assert _fresh(stored).status == "pending"
    assert _state(world.record) == state


def test_storage_write_failure_rolls_back_removes_paths_and_does_not_return_500(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """NFR-512, FR-536: `OSError` записи файла (`uploads.write_file`) — не 500: 200, строки `RecordFile` и `StoredFile` откатились, на диске файлов нет, проверка не поставлена, запись, её значения и версия целы."""
    world = _world()
    state = _state(world.record)
    before = _counts()
    client = support.logged_in(world.editor.user, raise_request_exception=False)
    calls = ls.fail_file_write(monkeypatch)
    for hx in (True, False):
        with django_capture_on_commit_callbacks(execute=True):
            response = _post_file(client, world.lst, world.record, world.field, "схема.txt", b"data", hx=hx)
        assert response.status_code == 200, f"сбой записи файла: ждали 200 (не 500), получили {response.status_code}"
        # ответ 53 (CONTRACT-006, 12.3, 15.3): отказ у поля `file` с кодом `write_failed` и его текстом
        _refused(response, "write_failed", TEXT_WRITE_FAILED)
    assert calls, "запись файла была вызвана через `uploads.write_file`"
    assert _counts() == before, "ни `RecordFile`, ни `StoredFile` не осталось"
    assert _disk(protected_root) == []
    assert org.files_jobs() == []
    assert _state(world.record) == state
    assert _m("Change").objects.filter(record=world.record, kind="file_added").count() == 0


# --- 4. версия и история ------------------------------------------------------------------------------------

def test_attach_and_delete_do_not_change_record_version(django_capture_on_commit_callbacks, protected_root):
    """FR-536: прикрепление и удаление файла не меняют версию записи, её значения и название (версия формы — FR-517); следующее сохранение формы с прежней версией не получает конфликта."""
    records = importlib.import_module("apps.lists.services.records")
    world = _world()
    record = ls.make_record(world.lst, "Версия 3", {world.text.code: "SN-9"}, created_by=world.editor.user, version=3)
    state = _state(record)
    with django_capture_on_commit_callbacks(execute=True):
        response = _post_file(world.editor.client, world.lst, record, world.field, "акт.txt", b"data")
    assert response.status_code == 200
    (made,) = _m("RecordFile").objects.filter(record=record)
    assert _state(record) == state and _fresh(record).version == 3
    made = _distinct(made)
    with django_capture_on_commit_callbacks(execute=True):
        removed = world.editor.client.post(_base(world.lst, record) + f"files/{made.pk}/delete/", **HX)
    assert removed.status_code == 200
    assert _state(record) == state and _fresh(record).version == 3
    saved = records.save(world.lst, record.number, {"title": "Версия 3", world.text.code: "SN-10"},
                         base_version=3, actor=world.editor.user)
    assert saved.changed is True and saved.record.version == 4 and _fresh(record).version == 4
    assert _fresh(record).values[world.text.code] == "SN-10"


def test_attach_and_delete_write_file_added_and_file_removed_history(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536: прикрепление пишет в историю `file_added`, удаление — `file_removed`: одна строка `Change` на действие, автор, в `changes` код и название поля и имя файла; фрагмент истории показывает «Добавлен файл <имя>» и «Удалён файл <имя>»; журнал событий не пишется."""
    world = _world()
    audit_before = support.model("core.AuditEvent").objects.count()
    before = _m("Change").objects.filter(record=world.record).count()
    with django_capture_on_commit_callbacks(execute=True):
        _post_file(world.editor.client, world.lst, world.record, world.field, "акт приёмки.pdf", b"%PDF-1.4 body")
    (added,) = _m("Change").objects.filter(record=world.record, kind="file_added")
    assert added.actor_id == world.editor.user.pk and added.via_import is False
    (item,) = added.changes
    assert item["field"] == world.field.code and item["name"] == world.field.name
    assert "акт приёмки.pdf" in (item.get("before"), item.get("after"))
    made = _distinct(_m("RecordFile").objects.get(record=world.record))
    with django_capture_on_commit_callbacks(execute=True):
        world.editor.client.post(_base(world.lst, world.record) + f"files/{made.pk}/delete/", **HX)
    (removed,) = _m("Change").objects.filter(record=world.record, kind="file_removed")
    assert removed.actor_id == world.editor.user.pk
    (item,) = removed.changes
    assert item["field"] == world.field.code and item["name"] == world.field.name
    assert "акт приёмки.pdf" in (item.get("before"), item.get("after"))
    assert _m("Change").objects.filter(record=world.record).count() == before + 2
    history = world.editor.client.get(_base(world.lst, world.record) + "history/", **HX)
    assert history.status_code == 200
    root = tree(history)
    for kind, phrase in (("file_added", "Добавлен файл акт приёмки.pdf"), ("file_removed", "Удалён файл акт приёмки.pdf")):
        line = q1(root, "li", data_change_kind=kind)
        assert phrase in line.text(), kind
        assert q(line, data_change_field=world.field.code), kind
    assert support.model("core.AuditEvent").objects.count() == audit_before, "файлы журнал событий не пишут"


# --- 5. выдача файла и список файлов -------------------------------------------------------------------------

def test_clean_file_download_sends_x_accel_redirect_attachment_filename_star_and_nosniff(protected_root):
    """FR-537: «чистый» файл отдаёт читающий список (и правящий): 200 с пустым телом, `X-Accel-Redirect` на `attachments/<id>`, `Content-Disposition: attachment; filename*=UTF-8''…` с именем файла, `X-Content-Type-Options: nosniff`."""
    world = _world()
    made = _file(world.record, world.field, name="акт приёмки №1.pdf", write=True)
    reader = ls.as_reader(world.lst)
    for session in (reader, world.editor):
        response = session.client.get(_base(world.lst, world.record) + f"files/{made.pk}/")
        assert response.status_code == 200 and response.content == b""
        redirect = response["X-Accel-Redirect"]
        assert redirect.startswith("/protected/attachments/") and redirect.endswith(str(made.file_id))
        disposition = response["Content-Disposition"]
        prefix = "attachment; filename*=UTF-8''"
        assert disposition.startswith(prefix) and unquote(disposition[len(prefix):]) == "акт приёмки №1.pdf"
        assert disposition.isascii() and " " not in disposition[len(prefix):]
        assert response["X-Content-Type-Options"] == "nosniff"


def test_checking_and_quarantined_files_are_listed_to_reader_with_mark_but_download_is_404(protected_root):
    """FR-537, NFR-505: читающему в блоке видны «проверяется» и «в карантине» с пометкой и без ссылки, у «чистого» ссылка на адрес файла; адрес ждущего и карантинного файла — 404 без `X-Accel-Redirect`; кнопок «прикрепить» и «удалить» у читающего нет, у правящего есть, а у записи в архиве нет ни у кого."""
    world = _world()
    pending = _file(world.record, world.field, status="pending", name="ждёт.pdf", write=True)
    clean = _file(world.record, world.field, status="clean", name="чистый.pdf", write=True)
    quarantined = _file(world.record, world.field, status="quarantine", name="вирус.pdf", write=True)
    reader = ls.as_reader(world.lst)
    base = _base(world.lst, world.record)
    page = reader.client.get(base)
    assert page.status_code == 200
    rows = _rows(_block(page, world.field))
    assert len(rows) == 3
    row = _row_of(_block(page, world.field), pending)
    assert row.attrs["data-scan"] == "pending" and "проверяется" in row.text() and "ждёт.pdf" in row.text()
    assert q(row, "a", data_action="file-download") == []
    row = _row_of(_block(page, world.field), quarantined)
    assert row.attrs["data-scan"] == "quarantine" and "в карантине" in row.text() and "вирус.pdf" in row.text()
    assert q(row, "a", data_action="file-download") == []
    row = _row_of(_block(page, world.field), clean)
    assert row.attrs["data-scan"] == "clean" and "чистый.pdf" in row.text()
    assert q1(row, "a", data_action="file-download").attrs["href"] == base + f"files/{clean.pk}/"
    for hidden in (pending, quarantined):
        response = reader.client.get(base + f"files/{hidden.pk}/")
        assert response.status_code == 404 and "X-Accel-Redirect" not in response
    assert reader.client.get(base + f"files/{clean.pk}/").status_code == 200
    root = tree(page)
    assert q(root, "form", data_action="file-attach") == [] and q(root, "button", data_action="file-delete") == []
    editor_page = tree(world.editor.client.get(base))
    q1(editor_page, "form", data_action="file-attach")
    assert len(q(editor_page, "button", data_action="file-delete")) == 3
    # запись в архиве: файлы видны, кнопок нет
    archived = ls.make_record(world.lst, "Архивная", created_by=world.editor.user, archived=True)
    kept = _file(archived, world.field, name="архивный акт.pdf", write=True)
    archived_page = world.editor.client.get(_base(world.lst, archived))
    assert archived_page.status_code == 200
    (row,) = _rows(_block(archived_page, world.field))
    assert row.attrs["data-file-id"] == str(kept.pk) and "архивный акт.pdf" in row.text()
    root = tree(archived_page)
    assert q(root, "form", data_action="file-attach") == [] and q(root, "button", data_action="file-delete") == []


def test_non_reader_gets_same_404_on_file_download_as_for_missing_file(protected_root):
    """FR-537, FR-514: не читающий список получает на чистый файл тот же 404, что на несуществующий (статус и тело неотличимы), без `X-Accel-Redirect`; читающий тот же адрес открывает."""
    world = _world()
    made = _file(world.record, world.field, name="тайна.pdf", write=True)
    outsider = support.logged_in(support.make_employee())
    base = _base(world.lst, world.record)
    real = outsider.get(base + f"files/{made.pk}/")
    absent = outsider.get(base + f"files/{made.pk + 900000}/")
    assert real.status_code == 404 and absent.status_code == 404
    assert "X-Accel-Redirect" not in real and "тайна" not in real.content.decode("utf-8")
    assert support.same_failure(real, absent)
    assert ls.as_reader(world.lst).client.get(base + f"files/{made.pk}/").status_code == 200


def _two_lists_world():
    """Два списка с «файл»-полем; сотрудник, который читает и правит оба; в первом — две записи."""
    first, second = ls.make_list(), ls.make_list()
    field_a, field_b = ls.add_field(first, "file", "Акт", multiple=True), ls.add_field(second, "file", "Акт", multiple=True)
    from tests import factories

    role = factories.make_role()
    for lst in (first, second):
        ls.grant_list(lst, role, "read")
        ls.grant_list(lst, role, "edit")
    user = support.make_employee(roles=[role])
    client = support.logged_in(user)
    author = support.make_employee()
    record_a1 = ls.make_record(first, "А1", created_by=author)
    record_a2 = ls.make_record(first, "А2", created_by=author)
    record_b1 = ls.make_record(second, "Б1", created_by=author)
    file_a1 = _file(record_a1, field_a, name="а1.pdf", write=True)
    return SimpleNamespace(first=first, second=second, client=client, user=user, a1=record_a1, a2=record_a2,
                           b1=record_b1, file=file_a1, field_a=field_a, field_b=field_b)


def test_file_of_other_record_or_other_list_by_substituted_ids_is_404_on_download(protected_root):
    """FR-514, FR-537: чистый файл записи 1 не отдаётся по адресу другой записи того же списка, записи с тем же номером в другом списке и несуществующей записи — везде 404 без `X-Accel-Redirect`, хотя сотрудник читает оба списка; по верному адресу — 200."""
    world = _two_lists_world()
    assert world.b1.number == world.a1.number, "номера записей в разных списках совпадают"
    right = _base(world.first, world.a1) + f"files/{world.file.pk}/"
    assert world.client.get(right).status_code == 200
    for wrong in (_base(world.first, world.a2), _base(world.second, world.b1), f"/lists/{world.first.pk}/9999/",
                  f"/lists/{world.second.pk}/9999/"):
        response = world.client.get(wrong + f"files/{world.file.pk}/")
        assert response.status_code == 404, wrong
        assert "X-Accel-Redirect" not in response, wrong


def test_file_of_other_record_or_other_list_by_substituted_ids_is_404_on_delete(
        django_capture_on_commit_callbacks, protected_root):
    """FR-514, FR-536: удаление файла записи 1 по адресу другой записи того же списка, записи с тем же номером в другом списке или несуществующей записи — 404, строки и файл на месте (в службе `Http404`); по верному адресу файл удаляется."""
    from django.http import Http404

    world = _two_lists_world()
    stored_id = world.file.file_id
    path = protected_root / "attachments" / str(stored_id)
    assert path.is_file()
    before = _counts()
    for wrong in (_base(world.first, world.a2), _base(world.second, world.b1), f"/lists/{world.first.pk}/9999/"):
        with django_capture_on_commit_callbacks(execute=True):
            response = world.client.post(wrong + f"files/{world.file.pk}/delete/", **HX)
        assert response.status_code == 404, wrong
        assert _counts() == before and path.is_file(), wrong
    with pytest.raises(Http404):
        _files().remove(world.first, world.a2.number, world.file.pk, actor=world.user)
    with pytest.raises(Http404):
        _files().remove(world.second, world.b1.number, world.file.pk, actor=world.user)
    assert _counts() == before and path.is_file()
    with django_capture_on_commit_callbacks(execute=True):
        response = world.client.post(_base(world.first, world.a1) + f"files/{world.file.pk}/delete/", **HX)
    assert response.status_code == 200
    assert _counts() == (0, 0) and not path.exists()


# --- 6. удаление ---------------------------------------------------------------------------------------------

def test_delete_by_reader_is_403_and_on_archived_record_refused_record_archived(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536, FR-514, FR-546: читающий получает на удаление 403, не читающий — 404 (файл цел); правящий на запись в архиве — 200 `[role=alert][data-code=record_archived]` «Запись в архиве» и в службе `RecordArchived`: строки и файл на месте."""
    world = _world()
    kept = _file(world.record, world.field, write=True)
    archived = ls.make_record(world.lst, "Архивная", created_by=world.editor.user, archived=True)
    in_archive = _file(archived, world.field, name="архивный.pdf", write=True)
    reader = ls.as_reader(world.lst)
    outsider = support.logged_in(support.make_employee())
    before, disk = _counts(), _disk(protected_root)
    url = _base(world.lst, world.record) + f"files/{kept.pk}/delete/"
    for hx in (True, False):
        for client, expected in ((reader.client, 403), (outsider, 404)):
            with django_capture_on_commit_callbacks(execute=True):
                response = client.post(url, **(HX if hx else {}))
            assert response.status_code == expected, (expected, hx)
    with django_capture_on_commit_callbacks(execute=True):
        refused = world.editor.client.post(_base(world.lst, archived) + f"files/{in_archive.pk}/delete/", **HX)
    assert refused.status_code == 200
    assert q(tree(refused), role="alert", data_code="record_archived")
    assert TEXT_ARCHIVED in refused.content.decode("utf-8")
    with pytest.raises(_errors().RecordArchived):
        _files().remove(world.lst, archived.number, in_archive.pk, actor=world.editor.user)
    assert _counts() == before and _disk(protected_root) == disk


def test_delete_removes_row_and_stored_file_in_transaction_and_disk_after_commit(
        django_capture_on_commit_callbacks, protected_root):
    """FR-536: строки `RecordFile` и `StoredFile` удаляются в транзакции, а файлы стираются с диска только после фиксации — и чистый из `attachments/`, и карантинный из `quarantine/`, и ждущий из `incoming/`; соседний файл остаётся."""
    world = _world()
    victims = [_file(world.record, world.field, status=status, name=f"{status}.txt", write=True)
               for status in ("clean", "quarantine", "pending")]
    neighbour = _file(world.record, world.field, name="сосед.txt", write=True)
    folders = {"clean": "attachments", "quarantine": "quarantine", "pending": "incoming"}
    paths = [protected_root / folders[made.file.status] / str(made.file_id) for made in victims]
    neighbour_path = protected_root / "attachments" / str(neighbour.file_id)
    assert all(path.is_file() for path in paths)
    stored_ids = [made.file_id for made in victims]
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        for made in victims:
            _files().remove(world.lst, world.record.number, made.pk, actor=world.editor.user)
        assert not _m("RecordFile").objects.filter(pk__in=[made.pk for made in victims]).exists()
        assert not support.model("core.StoredFile").objects.filter(pk__in=stored_ids).exists()
        assert all(path.is_file() for path in paths), "до фиксации файлы на месте"
    assert callbacks, "стирание поставлено на фиксацию"
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in paths)
    assert neighbour_path.is_file() and _m("RecordFile").objects.filter(pk=neighbour.pk).exists()


def test_field_with_files_cannot_be_deleted_protect(django_capture_on_commit_callbacks, protected_root):
    """FR-509, FR-536: поле с файлами не удаляется: на уровне базы `RecordFile.field` и `RecordFile.file` — `PROTECT` (`ProtectedError`), в службе `schema.delete_field` — отказ `field_has_data`; строки остаются; когда файлов не осталось, пустое поле удаляется."""
    schema = importlib.import_module("apps.lists.services.schema")
    world = _world()
    made = _file(world.record, world.field, name="акт.pdf", write=True)
    manager = ls.as_manager()
    with pytest.raises(ProtectedError):
        _fresh(world.field).delete()
    with pytest.raises(ProtectedError):
        _fresh(made.file).delete()
    with pytest.raises(_errors().ListsError) as caught:
        schema.delete_field(_fresh(world.field), actor=manager.user)
    assert caught.value.code == "field_has_data"
    assert _m("Field").objects.filter(pk=world.field.pk).exists() and _m("RecordFile").objects.filter(pk=made.pk).exists()
    assert (protected_root / "attachments" / str(made.file_id)).is_file()
    _m("RecordFile").objects.filter(pk=made.pk).delete()
    schema.delete_field(_fresh(world.field), actor=manager.user)
    assert not _m("Field").objects.filter(pk=world.field.pk).exists()
