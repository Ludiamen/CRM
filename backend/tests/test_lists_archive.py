"""T-6110: архив и удаление навсегда (FR-523, FR-524, FR-542, FR-544, FR-546). Сценарий 5 спеки среза 006.

«В архив» и «Вернуть» (`archive.archive`, `archive.restore`, адреса `…/archive/` и `…/restore/`): флаги, событие
истории, пересчёт вектора, журнал; запись в архиве нигде не видна, кроме отбора «Архив» и прямой ссылки; правка и
файлы отклоняются. «Удалить навсегда» (`archive.purge`, адрес `…/purge/`): только управляющий и только из архива,
отказ при ссылках из полей «запись другого списка», каскад, стирание файлов с диска после фиксации, журнал.
Замки — по SQL (`list_locks`, `assert_for_update`), гонок без потоков (решение 6 задач). Код среза на уровне модуля
не импортируется: службы берутся внутри тестов (CONTRACT-006, шапка).
"""
import ast
import importlib
import json
import re
from datetime import date
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests import support_lists as lists

pytestmark = pytest.mark.django_db

ARCHIVED = "Запись в архиве"
REFERENCED = "Нельзя удалить: на запись ссылаются записи: "
AUDIT_FIELDS = {"list", "number", "title"}


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


# --- данные теста ---------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.lists.services.{name}")


def _m(label: str):
    return support.model(f"lists.{label}")


def _world(title="Ноутбук активный", values=None, *, archived=False, with_file=False):
    """Список со строковым полем `f1` (и при `with_file` — полем «файл»), правящий и запись автора-правящего."""
    lst = lists.make_list()
    session = lists.as_editor(lst)
    text_field = lists.add_field(lst, "string", "Модель", show_in_table=True)
    file_field = lists.add_field(lst, "file", "Акт") if with_file else None
    record = lists.make_record(lst, title, values or {text_field.code: "Серийный 12345"}, archived=archived,
                               created_by=session.user)
    return lst, session, record, text_field, file_field


def _file(record, field, *, status="clean", write=False, name="акт.pdf"):
    """Файл записи; id строки `RecordFile` приведён к id `StoredFile`, чтобы адреса `…/files/<file_id>/` работали
    при любом прочтении «file_id» (контракт его не уточняет)."""
    made = lists.attach_file(record, field, name, status=status, write=write)
    stored_id = made.file_id
    _m("RecordFile").objects.filter(pk=made.pk).update(id=stored_id)
    return _m("RecordFile").objects.get(pk=stored_id)


def _reload(record):
    return _m("Record").objects.get(pk=record.pk)


def _exists(record) -> bool:
    return _m("Record").objects.filter(pk=record.pk).exists()


def _audit(action: str, record):
    return list(support.model("core.AuditEvent").objects.filter(action=action, object_id=str(record.pk)))


def _assert_journal(action: str, record, lst, actor):
    events = _audit(action, record)
    assert len(events) == 1, f"одна запись журнала {action}, получено {len(events)}"
    event = events[0]
    assert event.actor == actor
    assert event.object_type == "lists.record"
    merged = {**event.before, **event.after}
    assert set(merged) <= AUDIT_FIELDS, f"в журнале только список, номер и название: {sorted(merged)}"
    assert str(merged["number"]) == str(record.number)
    assert merged["title"] == record.title
    assert merged["list"] == lst.name
    return event


def _changes(record, kind=None):
    rows = _m("Change").objects.filter(record=record)
    return rows.filter(kind=kind) if kind else rows


def _get(session, path, **extra):
    return session.client.get(path, **extra)


def _post(session, path, data=None, **extra):
    return session.client.post(path, data or {}, **extra)


def _grid_numbers(session, lst, **params) -> list[int]:
    response = _get(session, f"/lists/{lst.pk}/", params)
    assert response.status_code == 200
    return sorted(int(node.attrs["data-record-number"]) for node in q(tree(response), "tr", data_record_number=True))


def _pick_texts(session, path, **params) -> list[str]:
    response = _get(session, path, params)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    return [node.text() for node in q(tree(response), "li", data_pick_id=True)]


def _search_titles(session, text: str) -> list[str]:
    search = _svc("search")
    parsed = search.parse_local(text)
    return [row.title for row in search.search(session.user, parsed, 10, 0)]


def _vector_matches(record, prefix: str) -> bool:
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM lists_record WHERE id = %s AND search @@ to_tsquery('russian', %s)",
                       [record.pk, prefix + ":*"])
        return cursor.fetchone()[0] == 1


def _drop_vector(record):
    _m("Record").objects.filter(pk=record.pk).update(search=None)


def _alert(root, code):
    return q(root, role="alert", data_code=code)


def _presence(session, lst, record):
    """Где видна запись: отбор «Все», отбор «Архив», подсказка поля-ссылки, поиск провайдера."""
    word = record.title.split()[0]
    return {
        "all": record.number in _grid_numbers(session, lst, preset="all"),
        "default": record.number in _grid_numbers(session, lst),
        "archive": record.number in _grid_numbers(session, lst, preset="archive"),
        "pick": any(record.title in text for text in _pick_texts(session, f"/lists/{lst.pk}/pick/", q=word)),
        "search": record.title in _search_titles(session, word),
    }


def _locks_before_record_update(sqls, lst):
    locks = lists.list_locks(sqls)
    assert locks, "замок списка не взят"
    assert all(lock.kind == "shared" for lock in locks), f"замок списка разделяемый, получено {locks}"
    assert all(lock.list_no == lists.list_no(lst.pk) for lock in locks)
    update = lists.assert_for_update(sqls, "lists_record")
    first_lock = next(i for i, sql in enumerate(sqls) if lists.list_locks([sql]))
    assert first_lock < sqls.index(update), "замок списка раньше FOR UPDATE записи"


def _referrer(lst, field, target, title="Ссылающаяся", **record_args):
    return lists.make_record(lst, title, {field.code: [target.pk]}, **record_args)


def _ticket_for(session):
    queue = sd.make_queue()
    ticket = sd.make_ticket(queue=queue, subject="Заявка про ноутбук")
    org.make_member(session.user, queue.unit)
    return ticket


# --- FR-523: в архив ------------------------------------------------------------------------------------

def test_archive_by_editor_sets_flags_writes_history_refreshes_vector_and_journal_with_number_and_title(
        clock, django_capture_on_commit_callbacks):
    """FR-523, FR-542: правящий нажимает «В архив»: `archived`, `archived_at`, `archived_by`; одна строка истории
    `archived` с автором; вектор пересчитан; журнал `lists.record_archived` с номером и названием (без значений);
    повтор — без второй строки истории и без второй записи журнала."""
    when = lists.moscow(2026, 10, 20, 10, 0)
    clock.set(when)
    lst, session, record, _, _ = _world("Ноутбук Dell")
    _drop_vector(record)

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(session, f"/lists/{lst.pk}/{record.number}/archive/")

    assert response.status_code == 302
    assert response["Location"] == f"/lists/{lst.pk}/{record.number}/"
    fresh = _reload(record)
    assert fresh.archived is True
    assert fresh.archived_at == when
    assert fresh.archived_by == session.user
    rows = list(_changes(record, "archived"))
    assert len(rows) == 1 and rows[0].actor == session.user
    assert fresh.search is not None and _vector_matches(fresh, "ноутбук")
    _assert_journal("lists.record_archived", record, lst, session.user)

    clock.advance(hours=3)
    with django_capture_on_commit_callbacks(execute=True):
        _svc("archive").archive(lst, record.number, actor=session.user)
    assert _reload(record).archived_at == when
    assert _changes(record, "archived").count() == 1
    assert len(_audit("lists.record_archived", record)) == 1


def test_archived_record_absent_from_all_preset_search_and_record_field_picker_and_present_in_archive_preset():
    """FR-523: запись в архиве не видна в отборе «Все» (и в отборе по умолчанию), в поиске и в подсказке поля-ссылки,
    но есть в отборе «Архив»; не архивная запись той же выборки видна везде, кроме «Архива»."""
    lst, session, first, _, _ = _world("Ноутбук активный")
    active = lists.make_record(lst, "Ноутбук рабочий", {}, created_by=session.user)
    old = lists.make_record(lst, "Ноутбук архивный", {}, created_by=session.user, archived=True)

    seen_old = _presence(session, lst, old)
    seen_active = _presence(session, lst, active)

    assert seen_old == {"all": False, "default": False, "archive": True, "pick": False, "search": False}
    assert seen_active == {"all": True, "default": True, "archive": False, "pick": True, "search": True}
    local = _get(session, f"/lists/{lst.pk}/", {"q": "Ноутбук", "preset": "all"})
    assert sorted(int(n.attrs["data-record-number"]) for n in q(tree(local), "tr", data_record_number=True)) \
        == sorted([first.number, active.number])


def test_archived_record_absent_from_ticket_link_picker():
    """FR-523: в подсказке привязки к заявке запись в архиве не предлагается, а такая же не архивная — предлагается."""
    lst, session, _, _, _ = _world("Ноутбук активный")
    old = lists.make_record(lst, "Ноутбук архивный", {}, created_by=session.user, archived=True)
    ticket = _ticket_for(session)

    response = _get(session, "/lists/ticket-pick/", {"ticket": ticket.number, "q": "Ноутбук"})

    assert response.status_code == 200
    texts = [node.text() for node in q(tree(response), "li", data_pick_id=True)]
    assert any("Ноутбук активный" in text for text in texts), f"не архивная запись предложена: {texts}"
    assert not any("Ноутбук архивный" in text for text in texts), f"запись в архиве не предлагается: {texts}"
    assert not q(tree(response), "li", data_pick_id=str(old.pk))


def test_archive_keeps_unique_rows_ticket_links_files_and_history(protected_root):
    """FR-523: после «В архив» остаются строки `UniqueValue` (значение занято: повтор отклоняется), связь с заявкой,
    файл (строки и байты на диске) и вся прежняя история."""
    lst = lists.make_list()
    session = lists.as_editor(lst)
    unique_field = lists.add_field(lst, "string", "Инвентарный номер", unique=True)
    file_field = lists.add_field(lst, "file", "Акт")
    record = lists.make_record(lst, "Принтер", {unique_field.code: "ИН-500"}, created_by=session.user)
    link = _m("TicketLink").objects.create(record=record, ticket_number=7001, linked_by=session.user)
    attached = _file(record, file_field, write=True)
    path = _svc_files_path(attached)
    old_change = _m("Change").objects.create(
        record=record, kind="changed", actor=session.user,
        changes=[{"field": unique_field.code, "name": "Инвентарный номер", "before": "ИН-1", "after": "ИН-500"}])
    unique_before = _unique_rows(lst)
    assert unique_before and path.exists()

    _svc("archive").archive(lst, record.number, actor=session.user)

    assert _unique_rows(lst) == unique_before
    assert _m("TicketLink").objects.filter(pk=link.pk).exists()
    assert _m("RecordFile").objects.filter(pk=attached.pk).exists()
    assert support.model("core.StoredFile").objects.filter(pk=attached.file_id).exists()
    assert path.exists()
    kept = _m("Change").objects.get(pk=old_change.pk)
    assert kept.changes == old_change.changes and kept.kind == "changed"
    errors = _svc("errors")
    with pytest.raises(errors.ListsError) as refused:
        _svc("records").create(lst, {"title": "Двойник", unique_field.code: " ин-500 "}, session.user)
    inner = getattr(refused.value, "errors", None) or {unique_field.code: refused.value}
    assert inner[unique_field.code].code == "unique_taken"


def _unique_rows(lst):
    rows = _m("UniqueValue").objects.filter(list=lst).select_related("field", "record")
    return sorted((row.field.code, row.norm_value, row.record.number) for row in rows)


def _svc_files_path(record_file):
    from apps.core.services import files

    return files.attachment_path(record_file.file)


# --- FR-523: вернуть ------------------------------------------------------------------------------------

def test_restore_returns_record_to_all_preset_search_and_pickers_and_writes_journal_restored(
        clock, django_capture_on_commit_callbacks):
    """FR-523, FR-542: «Вернуть» снимает флаги, запись снова в отборе «Все», в поиске и подсказках (поля-ссылки,
    заявки), её нет в «Архиве»; строка истории `restored`, пересчёт вектора, журнал `lists.record_restored`;
    возврат не архивной записи — без второй строки и записи."""
    clock.set(lists.moscow(2026, 10, 21, 9, 0))
    lst, session, _, _, _ = _world("Ноутбук активный")
    record = lists.make_record(lst, "Ноутбук Lenovo", {}, created_by=session.user, archived=True)
    ticket = _ticket_for(session)
    before = _presence(session, lst, record)
    assert before == {"all": False, "default": False, "archive": True, "pick": False, "search": False}
    _drop_vector(record)

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(session, f"/lists/{lst.pk}/{record.number}/restore/")

    assert response.status_code == 302
    assert response["Location"] == f"/lists/{lst.pk}/{record.number}/"
    fresh = _reload(record)
    assert fresh.archived is False and fresh.archived_at is None
    assert _presence(session, lst, fresh) == {"all": True, "default": True, "archive": False, "pick": True,
                                              "search": True}
    picked = _pick_texts(session, "/lists/ticket-pick/", ticket=ticket.number, q="Lenovo")
    assert any("Ноутбук Lenovo" in text for text in picked)
    rows = list(_changes(record, "restored"))
    assert len(rows) == 1 and rows[0].actor == session.user
    assert fresh.search is not None and _vector_matches(fresh, "lenovo")
    _assert_journal("lists.record_restored", record, lst, session.user)

    with django_capture_on_commit_callbacks(execute=True):
        _svc("archive").restore(lst, record.number, actor=session.user)
    assert _changes(record, "restored").count() == 1
    assert len(_audit("lists.record_restored", record)) == 1


def test_edit_and_file_actions_on_archived_record_are_refused_with_record_archived(protected_root, monkeypatch):
    """FR-523, FR-546: у записи в архиве правка и файлы отклоняются текстом «Запись в архиве»: GET правки — страница
    без формы, POST правки и загрузки файла — 200 с общим отказом `record_archived`; удаление файла по адресу не
    выполняется; службы поднимают `RecordArchived`; значения, версия и файлы не меняются."""
    lists.scan_clean(monkeypatch)
    lst, session, record, text_field, file_field = _world("Принтер", archived=True, with_file=True)
    attached = _file(record, file_field, write=True)
    base = f"/lists/{lst.pk}/{record.number}/"
    values_before, version_before = dict(record.values), record.version

    page = _get(session, base + "edit/")
    assert page.status_code == 200
    root = tree(page)
    assert q(root, data_lists_page="archived-edit")
    assert ARCHIVED in root.text()
    assert not q(root, "form", data_lists_record_form=True)

    edited = _post(session, base + "edit/", {"title": "Новое имя", text_field.code: "Другое", "base_version": version_before})
    assert edited.status_code == 200
    assert _alert(tree(edited), "record_archived")
    assert ARCHIVED in tree(edited).text()

    upload = _post(session, base + "files/", {"field": file_field.code,
                                              "file": SimpleUploadedFile("новый.pdf", b"%PDF-1.4\n% x\n")})
    assert upload.status_code == 200
    assert _alert(tree(upload), "record_archived")

    _post(session, base + f"files/{attached.pk}/delete/")

    errors = _svc("errors")
    with pytest.raises(errors.RecordArchived):
        _svc("records").save(lst, record.number, {"title": "Новое имя"}, base_version=version_before,
                             actor=session.user)
    with pytest.raises(errors.RecordArchived):
        _svc("files").attach(lst, record.number, field_code=file_field.code, name="новый.pdf",
                             data=b"%PDF-1.4\n% x\n", actor=session.user)
    with pytest.raises(errors.RecordArchived):
        _svc("files").remove(lst, record.number, attached.pk, actor=session.user)

    fresh = _reload(record)
    assert (fresh.title, fresh.values, fresh.version) == ("Принтер", values_before, version_before)
    assert list(_m("RecordFile").objects.filter(record=record).values_list("pk", flat=True)) == [attached.pk]
    assert _svc_files_path(attached).exists()


def test_card_of_archived_record_by_direct_link_opens_with_archived_mark():
    """FR-523: карточка записи в архиве открывается по прямой ссылке правящему и читающему, с пометкой «в архиве»
    и значениями; у не архивной записи пометки нет."""
    lst, editor, record, text_field, _ = _world("Сканер", {"f1": "Серийный 777"}, archived=True)
    active = lists.make_record(lst, "Монитор", {}, created_by=editor.user)
    reader = lists.as_reader(lst)

    for session in (editor, reader):
        response = _get(session, f"/lists/{lst.pk}/{record.number}/")
        assert response.status_code == 200
        root = tree(response)
        card = q1(root, data_lists_record=True)
        assert q(root, data_lists_archived=True) and "в архиве" in q(root, data_lists_archived=True)[0].text()
        assert "Сканер" in root.text()
        assert "Серийный 777" in q1(card, data_lists_value=text_field.code).text()
    plain = tree(_get(editor, f"/lists/{lst.pk}/{active.number}/"))
    assert q(plain, data_lists_record=True) and not q(plain, data_lists_archived=True)


def test_reader_sees_no_archive_or_restore_buttons_and_post_is_403():
    """FR-523: читающий не видит кнопок «В архив» (карточка, групповое действие) и «Вернуть», а POST на `…/archive/`
    и `…/restore/` — 403 без изменений, строки истории и записи журнала; правящему кнопки показаны."""
    lst, editor, active, _, _ = _world("Ноутбук активный")
    archived = lists.make_record(lst, "Ноутбук в архиве", {}, created_by=editor.user, archived=True)
    reader = lists.as_reader(lst)

    reader_active = tree(_get(reader, f"/lists/{lst.pk}/{active.number}/"))
    reader_archived = tree(_get(reader, f"/lists/{lst.pk}/{archived.number}/"))
    assert q(reader_active, data_lists_record=True) and q(reader_archived, data_lists_record=True)
    assert not q(reader_active, "button", data_action="record-archive")
    assert not q(reader_archived, "button", data_action="record-restore")
    assert not q(tree(_get(reader, f"/lists/{lst.pk}/")), "button", data_action="bulk-archive")
    assert q(tree(_get(editor, f"/lists/{lst.pk}/{active.number}/")), "button", data_action="record-archive")
    assert q(tree(_get(editor, f"/lists/{lst.pk}/{archived.number}/")), "button", data_action="record-restore")
    assert q(tree(_get(editor, f"/lists/{lst.pk}/")), "button", data_action="bulk-archive")

    assert _post(reader, f"/lists/{lst.pk}/{active.number}/archive/").status_code == 403
    assert _post(reader, f"/lists/{lst.pk}/{archived.number}/restore/").status_code == 403

    assert _reload(active).archived is False and _reload(archived).archived is True
    assert not _m("Change").objects.filter(kind__in=("archived", "restored")).exists()
    assert not support.model("core.AuditEvent").objects.filter(
        action__in=("lists.record_archived", "lists.record_restored")).exists()


def test_archive_and_restore_take_shared_list_lock_then_for_update_of_record():
    """FR-523: «В архив» и «Вернуть» берут разделяемый замок списка и только затем `SELECT … FOR UPDATE` записи;
    исключительного замка нет."""
    lst, session, record, _, _ = _world("Ноутбук")
    archived = lists.make_record(lst, "Монитор", {}, created_by=session.user, archived=True)
    archive = _svc("archive")

    _locks_before_record_update(lists.sql_of(archive.archive, lst, record.number, actor=session.user), lst)
    _locks_before_record_update(lists.sql_of(archive.restore, lst, archived.number, actor=session.user), lst)


# --- FR-524: удалить навсегда ----------------------------------------------------------------------------

def test_purge_button_absent_and_post_403_for_record_not_in_archive():
    """FR-524: у записи не в архиве кнопки «Удалить навсегда» нет даже управляющему, POST — 403 (служба —
    `PermissionDenied`); запись цела, записи журнала нет."""
    from django.core.exceptions import PermissionDenied

    lst, editor, record, _, _ = _world("Ноутбук")
    manager = lists.as_manager()

    card = tree(_get(manager, f"/lists/{lst.pk}/{record.number}/"))
    assert q(card, data_lists_record=True)
    assert not q(card, "button", data_action="record-purge")
    assert _post(manager, f"/lists/{lst.pk}/{record.number}/purge/").status_code == 403
    with pytest.raises(PermissionDenied):
        _svc("archive").purge(lst, record.number, actor=manager.user)

    assert _exists(record)
    assert not _audit("lists.record_purged", record)


def test_purge_by_editor_without_manage_right_is_403():
    """FR-524: правящий без права «Управление списками» (и читающий) не видит кнопки «Удалить навсегда» у записи в
    архиве, POST — 403, запись цела; управляющему кнопка показана, а POST — 302 на отбор «Архив»."""
    lst, editor, record, _, _ = _world("Ноутбук", archived=True)
    reader = lists.as_reader(lst)
    manager = lists.as_manager()

    for session in (editor, reader):
        card = tree(_get(session, f"/lists/{lst.pk}/{record.number}/"))
        assert q(card, data_lists_record=True)
        assert not q(card, "button", data_action="record-purge")
        assert _post(session, f"/lists/{lst.pk}/{record.number}/purge/").status_code == 403
        assert _exists(record)
    assert q(tree(_get(manager, f"/lists/{lst.pk}/{record.number}/")), "button", data_action="record-purge")

    response = _post(manager, f"/lists/{lst.pk}/{record.number}/purge/")

    assert response.status_code == 302
    assert response["Location"] == f"/lists/{lst.pk}/?preset=archive"
    assert not _exists(record)


def test_purge_takes_shared_list_lock_then_for_update_of_record():
    """FR-524: удаление навсегда берёт разделяемый замок списка и затем `SELECT … FOR UPDATE` записи."""
    lst, editor, record, _, _ = _world("Ноутбук", archived=True)
    manager = lists.as_manager()

    sqls = lists.sql_of(_svc("archive").purge, lst, record.number, actor=manager.user)

    _locks_before_record_update(sqls, lst)
    assert not _exists(record)


def test_purge_refused_while_record_field_of_any_list_refers_including_hidden_field_and_archived_referrer():
    """FR-524, FR-546: пока на запись ссылается запись другого списка — по видимому полю, по скрытому полю, из
    записи в архиве или запись того же списка — удаление отклонено `record_referenced` (на адресе — 200 с общим
    отказом), запись цела; со снятием ссылки удаление проходит."""
    target_list, editor, _, _, _ = _world("Цель")
    manager = lists.as_manager()
    other = lists.make_list()

    def visible(target):
        return _referrer(other, lists.add_field(other, "record", "Ссылка", target=target_list), target)

    def hidden(target):
        field = lists.add_field(other, "record", "Скрытая ссылка", hidden=True, target=target_list)
        return _referrer(other, field, target)

    def from_archive(target):
        field = lists.add_field(other, "record", "Ссылка из архива", target=target_list)
        return _referrer(other, field, target, archived=True)

    def same_list(target):
        return _referrer(target_list, lists.add_field(target_list, "record", "Родитель", target=target_list), target)

    first = True
    for name, make_referrer in (("видимое поле", visible), ("скрытое поле", hidden),
                                ("запись в архиве", from_archive), ("тот же список", same_list)):
        target = lists.make_record(target_list, f"Цель {name}", {}, created_by=editor.user, archived=True)
        referrer = make_referrer(target)

        with pytest.raises(_svc("errors").ListsError) as refused:
            _svc("archive").purge(target_list, target.number, actor=manager.user)
        assert refused.value.code == "record_referenced", name
        assert _exists(target), name
        if first:
            response = _post(manager, f"/lists/{target_list.pk}/{target.number}/purge/")
            assert response.status_code == 200
            assert _alert(tree(response), "record_referenced"), "общий отказ на странице"
            assert REFERENCED in tree(response).text()
            assert _exists(target)
            first = False

        _m("Record").objects.filter(pk=referrer.pk).delete()
        _svc("archive").purge(target_list, target.number, actor=manager.user)
        assert not _exists(target), name


def test_purge_refusal_links_referrers_of_readable_lists_and_counts_the_rest(monkeypatch):
    """FR-524, FR-546: отказ показывает ссылки «Название — №N» на ссылающиеся записи читаемых списков, остальные —
    числом («и ещё K», а без ссылок — одно число); название записи нечитаемого списка не раскрывается. Подмена
    `access.can_read` — решение 37 задач."""
    target_list, editor, _, _, _ = _world("Цель")
    manager = lists.as_manager()
    readable, unreadable = lists.make_list("Читаемый список"), lists.make_list("Закрытый список")
    field_ok = lists.add_field(readable, "record", "Ссылка", target=target_list)
    field_bad = lists.add_field(unreadable, "record", "Ссылка", target=target_list)
    first = lists.make_record(target_list, "Цель с двумя", {}, created_by=editor.user, archived=True)
    second = lists.make_record(target_list, "Цель с одной", {}, created_by=editor.user, archived=True)
    shown = _referrer(readable, field_ok, first, "Видимая ссылка", created_by=editor.user)
    _referrer(unreadable, field_bad, first, "Скрытая ссылка", created_by=editor.user)
    _referrer(unreadable, field_bad, second, "Скрытая единственная", created_by=editor.user)
    access = _svc("access")
    real = access.can_read
    monkeypatch.setattr(access, "can_read", lambda user, lst: False if lst.pk == unreadable.pk else real(user, lst))

    both = _svc("links").referrers(first, None)
    assert len(both.rows) == 2 and both.hidden == 0
    seen = _svc("links").referrers(first, manager.user)
    assert [row.pk for row in seen.rows] == [shown.pk] and seen.hidden == 1

    with pytest.raises(_svc("errors").ListsError) as refused:
        _svc("archive").purge(target_list, first.number, actor=manager.user)
    assert refused.value.code == "record_referenced" and refused.value.params["hidden"] == 1
    page = _post(manager, f"/lists/{target_list.pk}/{first.number}/purge/")
    alert = q1(tree(page), role="alert", data_code="record_referenced")
    assert page.status_code == 200
    assert REFERENCED in alert.text() and f"Видимая ссылка — №{shown.number}" in alert.text()
    assert "и ещё 1" in alert.text()
    assert q(alert, "a", href=f"/lists/{readable.pk}/{shown.number}/")
    assert "Скрытая ссылка" not in page.content.decode("utf-8")

    only_hidden = _post(manager, f"/lists/{target_list.pk}/{second.number}/purge/")
    text = q1(tree(only_hidden), role="alert", data_code="record_referenced").text()
    assert only_hidden.status_code == 200
    assert REFERENCED + "1" in text and "ещё" not in text
    assert "Скрытая единственная" not in only_hidden.content.decode("utf-8")
    assert _exists(first) and _exists(second)


def test_purge_deletes_record_history_unique_rows_ticket_links_and_reminder_marks_by_cascade(
        protected_root, django_capture_on_commit_callbacks):
    """FR-524: «Удалить навсегда» удаляет запись, её историю, строки уникальности, связи с заявками, отметки
    напоминаний, файлы (строки `RecordFile` и `StoredFile`); соседняя запись и её строки остаются."""
    lst = lists.make_list()
    editor = lists.as_editor(lst)
    manager = lists.as_manager()
    unique_field = lists.add_field(lst, "string", "Инвентарный номер", unique=True)
    due = lists.add_field(lst, "date", "Срок поверки", deadline=True, thresholds=(7,))
    file_field = lists.add_field(lst, "file", "Акт")
    doomed = lists.make_record(lst, "Удаляемая", {unique_field.code: "ИН-1", due.code: "2026-12-01"},
                               created_by=editor.user, archived=True)
    kept = lists.make_record(lst, "Остающаяся", {unique_field.code: "ИН-2", due.code: "2026-12-01"},
                             created_by=editor.user, archived=True)
    for record in (doomed, kept):
        _m("Change").objects.create(record=record, kind="created", actor=editor.user, changes=[])
        _m("TicketLink").objects.create(record=record, ticket_number=7100 + record.number, linked_by=editor.user)
        _m("ReminderSent").objects.create(record=record, field=due, threshold_days=7, due_date=date(2026, 12, 1),
                                          notified=True)
        _file(record, file_field)

    def footprint(record):
        return {name: _m(name).objects.filter(record=record).count()
                for name in ("Change", "UniqueValue", "TicketLink", "ReminderSent", "RecordFile")}

    stored_ids = list(_m("RecordFile").objects.filter(record=doomed).values_list("file_id", flat=True))
    assert footprint(doomed) == {"Change": 1, "UniqueValue": 1, "TicketLink": 1, "ReminderSent": 1, "RecordFile": 1}
    kept_before = footprint(kept)

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(manager, f"/lists/{lst.pk}/{doomed.number}/purge/")

    assert response.status_code == 302
    assert not _exists(doomed)
    assert footprint(doomed) == dict.fromkeys(kept_before, 0)
    assert not support.model("core.StoredFile").objects.filter(pk__in=stored_ids).exists()
    assert _exists(kept) and footprint(kept) == kept_before


def test_purge_removes_files_of_all_scan_states_from_disk_after_commit_and_missing_file_is_not_an_error(
        protected_root, django_capture_on_commit_callbacks):
    """FR-524: файлы в состояниях «проверяется», «чистый», «карантин» стираются с диска только после фиксации
    транзакции (до неё лежат на месте), отсутствующий на диске файл — не ошибка; строки `RecordFile` и `StoredFile`
    удалены в той же транзакции."""
    lst, editor, record, _, file_field = _world("Ноутбук", archived=True, with_file=True)
    manager = lists.as_manager()
    written = [_file(record, file_field, status=status, write=True, name=f"{status}.pdf")
               for status in ("pending", "clean", "quarantine")]
    missing = _file(record, file_field, status="clean", write=False, name="нет-на-диске.pdf")
    paths = [_svc_files_path(item) for item in written]
    missing_path = _svc_files_path(missing)
    stored_ids = [item.file_id for item in written + [missing]]
    assert all(path.exists() for path in paths) and not missing_path.exists()
    assert len({path.parent.name for path in paths}) == 3, "три разных каталога: incoming, attachments, quarantine"

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        _svc("archive").purge(lst, record.number, actor=manager.user)

    assert not _exists(record)
    assert not _m("RecordFile").objects.filter(record_id=record.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk__in=stored_ids).exists()
    assert all(path.exists() for path in paths), "до фиксации файлы на диске остаются"
    assert callbacks, "стирание поставлено на фиксацию"

    for callback in callbacks:
        callback()

    assert not any(path.exists() for path in paths)


def test_purge_writes_journal_record_purged_with_number_and_title_without_field_values():
    """FR-524, FR-542: журнал `lists.record_purged`: номер и название записи, исполнитель — управляющий, значений
    полей нет (в записи журнала только список, номер, название)."""
    lst, editor, record, text_field, _ = _world("Ноутбук для журнала", {"f1": "Маркер-значения-17"}, archived=True)
    manager = lists.as_manager()

    _svc("archive").purge(lst, record.number, actor=manager.user)

    event = _assert_journal("lists.record_purged", record, lst, manager.user)
    dump = json.dumps([event.before, event.after], ensure_ascii=False)
    assert "Маркер-значения-17" not in dump and "Серийный" not in dump
    assert not _exists(record)


def test_purge_keeps_display_strings_of_purged_record_in_other_records_history():
    """FR-524: строка показа «Название — №N» удалённой записи в истории другой записи остаётся (история
    неизменяема): после снятия ссылки и удаления цели строки `Change` другой записи не изменились."""
    target_list, editor, _, _, _ = _world("Цель")
    manager = lists.as_manager()
    other = lists.make_list()
    field = lists.add_field(other, "record", "Ссылка", target=target_list)
    target = lists.make_record(target_list, "Цель истории", {}, created_by=editor.user, archived=True)
    holder = lists.make_record(other, "Держатель", {}, created_by=editor.user)
    display = f"Цель истории — №{target.number}"
    _m("Change").objects.create(record=holder, kind="changed", actor=editor.user,
                                changes=[{"field": field.code, "name": "Ссылка", "before": "", "after": display}])
    _m("Change").objects.create(record=holder, kind="changed", actor=editor.user,
                                changes=[{"field": field.code, "name": "Ссылка", "before": display, "after": ""}])
    snapshot = list(_m("Change").objects.filter(record=holder).order_by("pk").values_list("pk", "kind", "changes"))

    _svc("archive").purge(target_list, target.number, actor=manager.user)

    assert not _exists(target)
    assert list(_m("Change").objects.filter(record=holder).order_by("pk").values_list("pk", "kind", "changes")) \
        == snapshot
    assert display in json.dumps([row[2] for row in snapshot], ensure_ascii=False)
    shown = _get(lists.as_editor(other), f"/lists/{other.pk}/{holder.number}/history/")
    assert shown.status_code == 200 and display in tree(shown).text()


def test_ticket_card_has_no_link_to_purged_record():
    """FR-524: связь с заявкой исчезает вместе с записью: до удаления в карточке заявки строка связи с пометкой
    «в архиве» есть, после — строки, ссылки и названия записи нет, строки `TicketLink` тоже."""
    lst, editor, record, _, _ = _world("Ноутбук в заявке", archived=True)
    manager = lists.as_manager()
    ticket = _ticket_for(editor)
    link = _m("TicketLink").objects.create(record=record, ticket_number=ticket.number, linked_by=editor.user)
    href = f"/lists/{lst.pk}/{record.number}/"

    def section():
        page = _get(editor, f"/tickets/{ticket.number}/")
        assert page.status_code == 200
        return tree(page), page.content.decode("utf-8")

    root, html = section()
    part = q1(root, "div", data_card_part="lists-records")
    row = q1(part, "li", data_ticket_link_id=str(link.pk))
    assert q(row, "a", href=href) and q(row, data_lists_archived=True)

    _svc("archive").purge(lst, record.number, actor=manager.user)

    root, html = section()
    assert not q(root, "li", data_ticket_link_id=True)
    assert href not in html and "Ноутбук в заявке" not in html
    assert not _m("TicketLink").objects.filter(pk=link.pk).exists()


# --- FR-544: бессрочное хранение --------------------------------------------------------------------------

def test_archived_record_history_and_files_remain_after_nightly_lists_job_years_later(
        clock, protected_root):
    """FR-544: через годы запись в архиве, её история и файлы на месте после ночного задания списков
    (`remind_deadlines`, обход сроков); напоминаний по записи в архиве нет; задания очистки записей нет — в
    расписании у `lists` только `remind_deadlines`, в `apps/lists/tasks.py` нет функций очистки и обезличивания."""
    clock.set(lists.moscow(2021, 10, 20, 12, 0))
    lst = lists.make_list()
    session = lists.as_editor(lst)
    lists.as_reader(lst)
    due = lists.add_field(lst, "date", "Срок поверки", deadline=True, thresholds=(7, 1))
    file_field = lists.add_field(lst, "file", "Акт")
    record = lists.make_record(lst, "Архивный прибор", {due.code: "2030-10-28"}, created_by=session.user,
                               archived=True)
    attached = _file(record, file_field, write=True)
    path = _svc_files_path(attached)
    body = path.read_bytes()
    history = _m("Change").objects.create(record=record, kind="changed", actor=session.user,
                                          changes=[{"field": due.code, "name": "Срок поверки", "before": "",
                                                    "after": "28.10.2030"}])
    archived_at = _reload(record).archived_at
    notifications = support.model("notify.Notification").objects.count()

    clock.set(lists.moscow(2030, 10, 25, 12, 0))
    from apps.lists import tasks

    result = lists.run_reminders(date(2030, 10, 25))
    tasks.remind_deadlines()

    fresh = _reload(record)
    assert fresh.archived is True and fresh.archived_at == archived_at and fresh.title == "Архивный прибор"
    assert _m("Change").objects.filter(pk=history.pk, record=record).exists()
    assert _m("RecordFile").objects.filter(pk=attached.pk, record=record).exists()
    assert support.model("core.StoredFile").objects.filter(pk=attached.file_id).exists()
    assert path.exists() and path.read_bytes() == body
    assert result.notified == 0 and not _m("ReminderSent").objects.filter(record=record).exists()
    assert support.model("notify.Notification").objects.count() == notifications

    cron = ast.parse((support.BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(cron) if isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("apps.lists") for alias in node.names}
    assert imported == {"remind_deadlines"}, f"в расписании у списков только напоминания: {sorted(imported)}"
    module = ast.parse((support.BACKEND_DIR / "apps" / "lists" / "tasks.py").read_text(encoding="utf-8"))
    names = [node.name for node in ast.walk(module) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert not [name for name in names if re.search(r"purge|clean|retention|anonym|delete", name, re.I)], names
