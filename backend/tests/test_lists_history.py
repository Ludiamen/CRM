"""T-6109: история записи (FR-509, FR-522). Сценарии 2 (п. 8), 10 (п. 7, 8), 11 и 14 (п. 2) спеки среза 006.

История — строки `Change` (`history.write` только добавляет, `history.page` отдаёт по 50 строк новыми сверху);
в карточке — фрагмент `/lists/<id>/<n>/history/` (зацепки CONTRACT-006, 11.6). Строки показа хранятся на момент
изменения, скрытые поля остаются в старых строках, изменение схемы строк не пишет, уволенный автор — с пометкой.
Код среза на уровне модуля не импортируется: службы берутся внутри тестов (CONTRACT-006, шапка).
"""
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pytest
from django.db import models

from tests import factories, support
from tests import support_lists as lists

pytestmark = pytest.mark.django_db

MOMENT = lists.moscow(2026, 3, 11, 0, 30)  # 10.03.2026 21:30 UTC: дата по Москве уже следующая


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


def tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- данные и вызовы ------------------------------------------------------------------------------------

def _svc(name: str):
    import importlib

    return importlib.import_module(f"apps.lists.services.{name}")


def _change():
    return support.model("lists.Change")


def _rows_of(record) -> list:
    return list(_change().objects.filter(record=record).order_by("pk"))


def _snapshot(record=None) -> list:
    query = _change().objects.order_by("pk")
    if record is not None:
        query = query.filter(record=record)
    return list(query.values_list("pk", "record_id", "kind", "changes", "at", "actor_id", "via_import"))


def _history(client, lst, record, query: str = ""):
    return client.get(f"/lists/{lst.pk}/{record.number}/history/{query}")


def _lis(response) -> list:
    assert response.status_code == 200, response.status_code
    return q(tree(response), "li", data_change_kind=True)


def _kinds(response) -> list[str]:
    return [li.attrs["data-change-kind"] for li in _lis(response)]


def _side(li, code: str, side: str) -> str:
    """Текст «было» или «стало» изменения поля `code` в строке истории."""
    entries = q(li, data_change_field=code)
    assert len(entries) == 1, f"в строке истории изменений поля {code}: {len(entries)}"
    found = q(entries[0], data_field=side)
    assert len(found) == 1, f"{code}: сторон {side}: {len(found)}"
    return found[0].text()


def _entries(change) -> dict:
    """Изменения строки `Change` по коду поля."""
    by_code = {}
    for entry in change.changes:
        assert entry["field"] not in by_code, f"поле {entry['field']} записано дважды"
        by_code[entry["field"]] = entry
    return by_code


def _create(lst, actor, title="Сервер", **data):
    return _svc("records").create(lst, {"title": title, **data}, actor)


def _save(lst, record, actor, **data):
    """Сохранение с полным набором данных: `data` — полные значения по кодам полей (и `title`)."""
    result = _svc("records").save(lst, record.number, data, base_version=record.version, actor=actor)
    record.refresh_from_db()
    return result


def _setup_strings(count=2):
    """Список со строковыми полями `f1`… и управляющий; возвращает (список, управляющий, поля)."""
    manager = lists.as_manager(full_name="Админ Списков")
    lst = lists.make_list()
    fields = [lists.add_field(lst, "string", f"Строка {n}") for n in range(1, count + 1)]
    return lst, manager, fields


# --- создание, изменение, строки показа -----------------------------------------------------------------

def test_created_record_history_first_row_is_created_with_author_and_moscow_time(clock):
    """FR-522: создание записи — одна строка `created` с автором и временем по Москве; в карточке — время «ДД.ММ.ГГГГ ЧЧ:ММ»."""
    lst, manager, (field,) = _setup_strings(1)
    clock.set(MOMENT)
    record = _create(lst, manager.user, **{field.code: "значение"})
    rows = _rows_of(record)
    assert [(row.kind, row.actor_id, row.via_import) for row in rows] == [("created", manager.user.pk, False)]
    assert rows[0].at == MOMENT
    lis = _lis(_history(manager.client, lst, record))
    assert [li.attrs["data-change-kind"] for li in lis] == ["created"]
    assert "Админ Списков" in lis[0].text()
    assert not q(lis[0], "span", data_dismissed="true")
    moments = q(lis[0], "time", data_at=True)
    assert len(moments) == 1
    assert moments[0].text() == "11.03.2026 00:30"
    assert moments[0].text() == lists.moscow_text(MOMENT)
    assert datetime.fromisoformat(moments[0].attrs["datetime"]) == MOMENT


def test_change_of_two_fields_writes_one_change_row_with_two_field_entries():
    """FR-522: правка двух полей одним сохранением — одна строка `changed` с двумя записями «поле, было, стало»."""
    lst, manager, (first, second, third) = _setup_strings(3)
    record = _create(lst, manager.user, **{first.code: "а1", second.code: "б1", third.code: "в1"})
    before = len(_rows_of(record))
    result = _save(lst, record, manager.user, title="Сервер", **{first.code: "а2", second.code: "б2", third.code: "в1"})
    assert result.changed is True
    rows = _rows_of(record)
    assert len(rows) == before + 1
    row = rows[-1]
    assert (row.kind, row.actor_id) == ("changed", manager.user.pk)
    entries = _entries(row)
    assert set(entries) == {first.code, second.code}
    assert (entries[first.code]["name"], entries[first.code]["before"], entries[first.code]["after"]) == (
        first.name, "а1", "а2")
    assert (entries[second.code]["name"], entries[second.code]["before"], entries[second.code]["after"]) == (
        second.name, "б1", "б2")
    lis = _lis(_history(manager.client, lst, record))
    assert [li.attrs["data-change-kind"] for li in lis] == ["changed", "created"]
    assert _side(lis[0], first.code, "before") == "а1"
    assert _side(lis[0], first.code, "after") == "а2"
    assert _side(lis[0], second.code, "before") == "б1"
    assert _side(lis[0], second.code, "after") == "б2"
    assert not q(lis[0], data_change_field=third.code)


def test_change_entries_store_display_strings_person_name_choice_title_record_title_number_money_and_date():
    """FR-522: «было» и «стало» — строки показа: сотрудник — ФИО, значение списка — название, запись — «Название — №N», число, деньги, дата."""
    manager = lists.as_manager(full_name="Админ Списков")
    lst = lists.make_list()
    person = lists.add_field(lst, "person", "Ответственный")
    kind = lists.add_field(lst, "choice", "Вид", choices=("Компьютер", "Ноутбук"))
    link = lists.add_field(lst, "record", "Связь", target=lst)
    number = lists.add_field(lst, "number", "Количество")
    money = lists.add_field(lst, "money", "Стоимость")
    date = lists.add_field(lst, "date", "Куплено")
    anna = support.make_employee(full_name="Анна Первая")
    boris = support.make_employee(full_name="Борис Второй")
    first = lists.make_record(lst, "Сервер", created_by=manager.user)
    second = lists.make_record(lst, "Принтер", created_by=manager.user)
    record = _create(lst, manager.user, **{
        person.code: [str(anna.pk)], kind.code: [str(lists.choice_id(kind, "Компьютер"))],
        link.code: [str(first.pk)], number.code: "7", money.code: "100", date.code: "10.03.2026"})
    _save(lst, record, manager.user, title="Сервер", **{
        person.code: [str(boris.pk)], kind.code: [str(lists.choice_id(kind, "Ноутбук"))],
        link.code: [str(second.pk)], number.code: "12.5", money.code: "1234,5", date.code: "15.03.2026"})
    row = _rows_of(record)[-1]
    assert row.kind == "changed"
    entries = _entries(row)
    assert set(entries) == {person.code, kind.code, link.code, number.code, money.code, date.code}
    expected = {
        person.code: ("Анна Первая", "Борис Второй"),
        kind.code: ("Компьютер", "Ноутбук"),
        link.code: ("Сервер — №1", "Принтер — №2"),
        number.code: ("7", "12,5"),
        money.code: ("100,00 ₽", "1 234,50 ₽"),
        date.code: ("10.03.2026", "15.03.2026"),
    }
    for code, (was, now) in expected.items():
        assert (entries[code]["before"], entries[code]["after"]) == (was, now), code
    li = _lis(_history(manager.client, lst, record))[0]
    for code, (was, now) in expected.items():
        assert _side(li, code, "before") == was, code
        assert _side(li, code, "after") == now, code


def test_later_choice_rename_does_not_change_old_history_row():
    """FR-522: переименование значения списка позже не меняет старую строку истории: она хранит название на момент изменения."""
    manager = lists.as_manager()
    lst = lists.make_list()
    kind = lists.add_field(lst, "choice", "Вид", choices=("Компьютер", "Ноутбук"))
    computer, laptop = lists.choice_id(kind, "Компьютер"), lists.choice_id(kind, "Ноутбук")
    record = _create(lst, manager.user, **{kind.code: [str(laptop)]})
    _save(lst, record, manager.user, title="Сервер", **{kind.code: [str(computer)]})
    before = _snapshot(record)
    _svc("schema").save_choices(kind, [(computer, "Компьютер"), (laptop, "Портативный компьютер")],
                                actor=manager.user)
    assert support.model("lists.Choice").objects.get(pk=laptop).title == "Портативный компьютер"
    assert _snapshot(record) == before
    row = _rows_of(record)[-1]
    assert (_entries(row)[kind.code]["before"], _entries(row)[kind.code]["after"]) == ("Ноутбук", "Компьютер")
    response = _history(manager.client, lst, record)
    li = _lis(response)[0]
    assert _side(li, kind.code, "before") == "Ноутбук"
    assert "Портативный компьютер" not in response.content.decode("utf-8")


def test_file_added_and_removed_rows_name_file_and_field_code_and_name(protected_root):
    """FR-522: файл добавлен и удалён — отдельные строки `file_added` и `file_removed` с именем файла, кодом и названием поля; сохранения формы не нужно."""
    manager = lists.as_manager()
    lst = lists.make_list()
    files_field = lists.add_field(lst, "file", "Акты", multiple=True)
    record = _create(lst, manager.user)
    version = record.version
    attached = _svc("files").attach(lst, record.number, field_code=files_field.code, name="акт.pdf",
                                    data=b"%PDF-1.4\n% test body\n", actor=manager.user)
    _svc("files").remove(lst, record.number, attached.pk, actor=manager.user)
    rows = _rows_of(record)
    assert [row.kind for row in rows] == ["created", "file_added", "file_removed"]
    assert all(row.actor_id == manager.user.pk for row in rows)
    added, removed = _entries(rows[1]), _entries(rows[2])
    assert list(added) == [files_field.code] and list(removed) == [files_field.code]
    assert (added[files_field.code]["name"], added[files_field.code]["after"]) == ("Акты", "акт.pdf")
    assert (removed[files_field.code]["name"], removed[files_field.code]["before"]) == ("Акты", "акт.pdf")
    record.refresh_from_db()
    assert record.version == version
    lis = _lis(_history(manager.client, lst, record))
    assert [li.attrs["data-change-kind"] for li in lis] == ["file_removed", "file_added", "created"]
    assert "Удалён файл акт.pdf" in lis[0].text() and "Акты" in lis[0].text()
    assert "Добавлен файл акт.pdf" in lis[1].text() and "Акты" in lis[1].text()


def test_archive_and_restore_write_archived_and_restored_rows():
    """FR-522: «в архив» и «вернуть» — строки `archived` и `restored` с автором; в карточке — «Перенесена в архив» и «Возвращена из архива»."""
    manager = lists.as_manager()
    lst = lists.make_list()
    record = _create(lst, manager.user)
    _svc("archive").archive(lst, record.number, actor=manager.user)
    _svc("archive").restore(lst, record.number, actor=manager.user)
    rows = _rows_of(record)
    assert [(row.kind, row.actor_id) for row in rows] == [
        ("created", manager.user.pk), ("archived", manager.user.pk), ("restored", manager.user.pk)]
    lis = _lis(_history(manager.client, lst, record))
    assert [li.attrs["data-change-kind"] for li in lis] == ["restored", "archived", "created"]
    assert "Возвращена из архива" in lis[0].text()
    assert "Перенесена в архив" in lis[1].text()


def test_created_via_import_and_changed_by_import_rows_are_shown_as_import_events():
    """FR-522: «создана загрузкой» (`created` с `via_import`) и «изменено загрузкой» (`imported`) — отдельные подписи; обычное создание — «Создана»."""
    lst, manager, (field,) = _setup_strings(1)
    imported = _svc("records").create(lst, {"title": "Из файла", field.code: "а1"}, manager.user, via_import=True)
    plain = _create(lst, manager.user, title="Вручную", **{field.code: "а1"})
    changes = [{"field": field.code, "name": field.name, "before": "а1", "after": "а2"}]
    _svc("history").write(imported, "imported", changes, manager.user, via_import=True)
    rows = _rows_of(imported)
    assert [(row.kind, row.via_import) for row in rows][0] == ("created", True)
    assert rows[1].kind == "imported"
    lis = _lis(_history(manager.client, lst, imported))
    assert [li.attrs["data-change-kind"] for li in lis] == ["imported", "created"]
    assert "Изменено загрузкой" in lis[0].text()
    assert (_side(lis[0], field.code, "before"), _side(lis[0], field.code, "after")) == ("а1", "а2")
    assert "data-via-import" in lis[1].attrs  # зацепка — на самой строке `li` (решение Opus S2-А)
    assert "Создана загрузкой" in lis[1].text()
    plain_row = _lis(_history(manager.client, lst, plain))[0]
    assert plain_row.attrs["data-change-kind"] == "created"
    assert "data-via-import" not in plain_row.attrs and not q(plain_row, data_via_import=True)
    assert "загрузкой" not in plain_row.text()
    assert "Создана" in plain_row.text()


# --- скрытые поля и схема -------------------------------------------------------------------------------

def _hidden_setup():
    lst, manager, (field,) = _setup_strings(1)
    record = _create(lst, manager.user, **{field.code: "А"})
    _save(lst, record, manager.user, title="Сервер", **{field.code: "Б"})
    return lst, manager, field, record


def test_old_rows_of_hidden_field_remain_and_are_shown_in_history():
    """FR-509, FR-522: после «Скрыть» старые строки истории по полю остаются и показываются («было → стало»)."""
    lst, manager, field, record = _hidden_setup()
    before = _snapshot(record)
    _svc("schema").hide_field(field, actor=manager.user)
    field.refresh_from_db()
    assert field.hidden is True
    assert _snapshot(record) == before
    reader = lists.as_reader(lst)
    lis = _lis(_history(reader.client, lst, record))
    assert [li.attrs["data-change-kind"] for li in lis] == ["changed", "created"]
    assert _side(lis[0], field.code, "before") == "А"
    assert _side(lis[0], field.code, "after") == "Б"


def test_show_after_hide_returns_field_and_keeps_its_history_rows_unchanged():
    """FR-509: «Показать» возвращает поле со значением в форму правки; строки истории по нему не изменились."""
    lst, manager, field, record = _hidden_setup()
    before = _snapshot(record)
    _svc("schema").hide_field(field, actor=manager.user)
    _svc("schema").show_field(field, actor=manager.user)
    field.refresh_from_db()
    assert field.hidden is False
    assert _snapshot(record) == before
    editor = lists.as_editor(lst)
    form = tree(editor.client.get(f"/lists/{lst.pk}/{record.number}/edit/"))
    containers = q(form, data_lists_field=field.code)
    assert len(containers) == 1
    inputs = q(containers[0], name=field.code)
    assert len(inputs) == 1 and inputs[0].attrs.get("value") == "Б"
    lis = _lis(_history(editor.client, lst, record))
    assert (_side(lis[0], field.code, "before"), _side(lis[0], field.code, "after")) == ("А", "Б")


def test_schema_change_writes_no_history_row():
    """FR-522: изменение схемы списка (поля, порядок, значения, права, описание) не пишет строк истории записей."""
    manager = lists.as_manager()
    lst = lists.make_list()
    kind = lists.add_field(lst, "choice", "Вид", choices=("Компьютер", "Ноутбук"))
    other = lists.add_field(lst, "string", "Модель")
    record = _create(lst, manager.user)
    before = _snapshot()
    assert before, "у созданной записи есть строка истории"
    schema = _svc("schema")
    added = schema.add_field(lst, name="Новое", type="string", actor=manager.user)
    schema.update_field(other, actor=manager.user, name="Модель устройства")
    schema.hide_field(other, actor=manager.user)
    schema.show_field(other, actor=manager.user)
    schema.move_field(other, "up", actor=manager.user)
    schema.save_choices(kind, [(lists.choice_id(kind, "Ноутбук"), "Ноутбук"),
                               (lists.choice_id(kind, "Компьютер"), "Компьютер"), (None, "Планшет")],
                        actor=manager.user)
    schema.delete_field(added, actor=manager.user)
    schema.save_access(lst, readers=[("role", factories.make_role().pk)], editors=[], actor=manager.user)
    schema.update_list(lst, name="Другое имя", description="Описание", actor=manager.user)
    assert _snapshot() == before
    assert len(_lis(_history(manager.client, lst, record))) == 1


# --- автор, неизменяемость ------------------------------------------------------------------------------

def test_dismissed_author_is_shown_with_dismissed_mark():
    """FR-522: уволенный автор строки — «ФИО (уволен)» в `span[data-dismissed="true"]`, у действующего пометки нет."""
    lst, manager, (field,) = _setup_strings(1)
    gone = support.make_employee(full_name="Иван Уволенов", state="dismissed")
    record = _create(lst, manager.user, **{field.code: "а1"})
    _svc("history").write(record, "changed", [{"field": field.code, "name": field.name, "before": "а1",
                                                "after": "а2"}], gone)
    lis = _lis(_history(manager.client, lst, record))
    assert [li.attrs["data-change-kind"] for li in lis] == ["changed", "created"]
    marks = q(lis[0], "span", data_dismissed="true")
    assert len(marks) == 1
    assert "Иван Уволенов" in marks[0].text() and "(уволен)" in marks[0].text()
    assert "Админ" not in lis[0].text()
    assert not q(lis[1], "span", data_dismissed="true")


def test_no_lists_route_edits_or_deletes_history_rows():
    """FR-522: адресов правки и удаления истории нет — единственный адрес с `history` отдаёт фрагмент, прочие методы строк не меняют."""
    import importlib

    patterns = importlib.import_module("apps.lists.urls").urlpatterns
    with_history = [p for p in patterns if "history" in str(p.pattern) or "history" in (p.name or "")]
    assert [p.name for p in with_history] == ["history"]
    assert str(with_history[0].pattern).endswith("history/")
    lst, manager, (field,) = _setup_strings(1)
    record = _create(lst, manager.user, **{field.code: "а1"})
    _save(lst, record, manager.user, title="Сервер", **{field.code: "а2"})
    before = _snapshot()
    url = f"/lists/{lst.pk}/{record.number}/history/"
    change_id = _rows_of(record)[0].pk
    for method in ("post", "put", "patch", "delete"):
        response = getattr(manager.client, method)(url)
        assert response.status_code < 500, (method, response.status_code)
    for tail in (f"{change_id}/", f"{change_id}/delete/", f"{change_id}/edit/"):
        for method in ("get", "post", "delete"):
            response = getattr(manager.client, method)(url + tail)
            assert response.status_code in (404, 405), (method, tail, response.status_code)
    assert _snapshot() == before
    assert len(_lis(manager.client.get(url))) == 2


def test_history_service_only_appends_rows(protected_root):
    """FR-522: `history.write` только вставляет строку; действия над записью не выполняют UPDATE и DELETE по `lists_change`."""
    import inspect

    assert _change()._meta.db_table == "lists_change"
    history = _svc("history")
    names = {name for name, member in inspect.getmembers(history, inspect.isfunction)
             if member.__module__ == history.__name__ and not name.startswith("_")}
    assert {"write", "page"} <= names
    lst, manager, (field,) = _setup_strings(1)
    files_field = lists.add_field(lst, "file", "Акты", multiple=True)
    record = _create(lst, manager.user, **{field.code: "а1"})
    old = _snapshot(record)
    with lists.capture_sql() as sqls:
        written = history.write(record, "changed", [{"field": field.code, "name": field.name, "before": "а1",
                                                      "after": "а2"}], manager.user)
        history.page(record, 0)
    touching = [sql for sql in sqls if "lists_change" in sql]
    assert any(sql.lstrip().upper().startswith("INSERT") for sql in touching)
    assert not [sql for sql in touching if sql.lstrip().upper().startswith(("UPDATE", "DELETE"))]
    assert written.pk and written.kind == "changed" and written.record_id == record.pk
    assert _snapshot(record)[:len(old)] == old and len(_snapshot(record)) == len(old) + 1
    with lists.capture_sql() as sqls:
        _save(lst, record, manager.user, title="Сервер", **{field.code: "а3"})
        _svc("archive").archive(lst, record.number, actor=manager.user)
        _svc("archive").restore(lst, record.number, actor=manager.user)
        attached = _svc("files").attach(lst, record.number, field_code=files_field.code, name="акт.pdf",
                                        data=b"%PDF-1.4\n% test body\n", actor=manager.user)
        _svc("files").remove(lst, record.number, attached.pk, actor=manager.user)
    touching = [sql for sql in sqls if "lists_change" in sql]
    assert len([sql for sql in touching if sql.lstrip().upper().startswith("INSERT")]) >= 5
    assert not [sql for sql in touching if sql.lstrip().upper().startswith(("UPDATE", "DELETE"))]


# --- постраничный показ, доступ, удаление ---------------------------------------------------------------

def test_history_fragment_pages_by_50_newest_first_with_show_more_offset():
    """FR-522: 50 строк на странице, новые сверху (`at`, `id` по убыванию), «Показать ещё» с `data-next-offset`; неверный `offset` — как 0."""
    lst, manager, (field,) = _setup_strings(1)
    record = lists.make_record(lst, "Сервер", created_by=manager.user)
    base = lists.moscow(2026, 3, 1)
    rows = []
    for number in range(1, 61):
        moment = base + timedelta(minutes=30 if number == 31 else number)  # у 30 и 31 время совпадает: решает `id`
        rows.append(_change()(record=record, kind="changed", actor=manager.user, at=moment, changes=[
            {"field": field.code, "name": field.name, "before": f"v{number - 1}", "after": f"v{number}"}]))
    _change().objects.bulk_create(rows)
    history = _svc("history")
    first, second = history.page(record, 0), history.page(record, 50)
    first_rows, second_rows = list(first.rows), list(second.rows)
    assert (len(first_rows), first.next_offset) == (50, 50)
    assert (len(second_rows), second.next_offset) == (10, None)
    assert [row.changes[0]["after"] for row in first_rows + second_rows] == [f"v{n}" for n in range(60, 0, -1)]
    response = _history(manager.client, lst, record)
    lis = _lis(response)
    assert [_side(li, field.code, "after") for li in lis] == [f"v{n}" for n in range(60, 10, -1)]
    more = q(tree(response), "button", data_action="more")
    assert len(more) == 1
    assert more[0].attrs["data-next-offset"] == "50"
    assert more[0].attrs["hx-get"].endswith(f"/lists/{lst.pk}/{record.number}/history/?offset=50")
    assert more[0].attrs["hx-swap"] == "outerHTML"
    rest = _history(manager.client, lst, record, "?offset=50")
    assert [_side(li, field.code, "after") for li in _lis(rest)] == [f"v{n}" for n in range(10, 0, -1)]
    assert not q(tree(rest), "button", data_action="more")
    for bad in ("?offset=abc", "?offset=-5", "?offset="):
        again = _history(manager.client, lst, record, bad)
        assert [_side(li, field.code, "after") for li in _lis(again)] == [f"v{n}" for n in range(60, 10, -1)], bad


def test_history_of_record_of_unreadable_list_is_404_like_missing_record():
    """FR-522: историю записи нечитаемого списка не отдают: 404, как у несуществующего списка, без данных записи."""
    lst, manager, (field,) = _setup_strings(1)
    record = _create(lst, manager.user, title="Служебная запись А", **{field.code: "а1"})
    author = support.make_employee(full_name="Пётр Невидимов")
    _svc("history").write(record, "changed", [{"field": field.code, "name": field.name, "before": "а1",
                                                "after": "а2"}], author)
    other = lists.make_list()
    outsider = lists.as_reader(other)
    nobody = support.make_employee()
    nobody_client = support.logged_in(nobody)
    missing_list = support.model("lists.List").objects.order_by("-pk").first().pk + 1000
    # Ответы разных сотрудников различаются меню оболочки: несуществующий список запрашивает тот же клиент
    # (CONTRACT-006, раздел 15.3, К-10).
    for client in (outsider.client, nobody_client):
        absent = client.get(f"/lists/{missing_list}/1/history/")
        assert absent.status_code == 404
        response = _history(client, lst, record)
        assert response.status_code == 404
        assert support.same_failure(response, absent)
        body = response.content.decode("utf-8")
        assert "Пётр Невидимов" not in body and "Служебная запись А" not in body and field.name not in body
    assert _history(manager.client, lst, record).status_code == 200


def test_purge_deletes_history_rows_by_cascade(django_capture_on_commit_callbacks):
    """FR-522: удаление записи навсегда стирает её историю каскадом; история других записей и их строки показа остаются."""
    assert _change()._meta.get_field("record").remote_field.on_delete is models.CASCADE
    manager = lists.as_manager()
    lst = lists.make_list()
    field = lists.add_field(lst, "string", "Модель")
    link = lists.add_field(lst, "record", "Связь", target=lst)
    target = _create(lst, manager.user, title="Сервер", **{field.code: "а1"})
    _save(lst, target, manager.user, title="Сервер", **{field.code: "а2"})
    holder = _create(lst, manager.user, title="Стойка", **{link.code: [str(target.pk)]})
    _save(lst, holder, manager.user, title="Стойка", **{link.code: []})
    holder_before = _snapshot(holder)
    assert len(holder_before) == 2  # `created` и `changed` (сброс ссылки)
    assert any(entry["after"] == "Сервер — №1" or entry["before"] == "Сервер — №1"
               for row in _rows_of(holder) for entry in row.changes)
    _svc("archive").archive(lst, target.number, actor=manager.user)
    assert len(_rows_of(target)) == 3
    with django_capture_on_commit_callbacks(execute=True):
        _svc("archive").purge(lst, target.number, actor=manager.user)
    assert not support.model("lists.Record").objects.filter(pk=target.pk).exists()
    assert not _change().objects.filter(record_id=target.pk).exists()
    assert _snapshot(holder) == holder_before


# --- сохранение без изменений и по одной строке на сохранение -------------------------------------------

def test_history_fragment_shows_no_new_row_after_save_without_changes():
    """FR-522: сохранение без изменений (службой и формой) не создаёт события: версия и число строк те же."""
    lst, manager, (first, second) = _setup_strings(2)
    record = _create(lst, manager.user, **{first.code: "а1", second.code: "б1"})
    editor = lists.as_editor(lst)
    before, version = _snapshot(record), record.version
    result = _save(lst, record, manager.user, title="Сервер", **{first.code: "а1", second.code: "б1"})
    assert result.changed is False
    assert (record.version, _snapshot(record)) == (version, before)
    response = editor.client.post(f"/lists/{lst.pk}/{record.number}/edit/", {
        "title": "Сервер", first.code: "а1", second.code: "б1", "base_version": str(record.version)})
    assert response.status_code == 302
    record.refresh_from_db()
    assert (record.version, _snapshot(record)) == (version, before)
    assert _kinds(_history(editor.client, lst, record)) == ["created"]


def test_each_saved_change_adds_exactly_one_history_row():
    """FR-522: каждое сохранение с изменениями (службой и формой) добавляет ровно одну строку `changed`, сколько бы полей ни менялось."""
    lst, manager, (first, second, third) = _setup_strings(3)
    editor = lists.as_editor(lst)
    record = _create(lst, manager.user, **{first.code: "1", second.code: "1", third.code: "1"})
    steps = [{first.code: "2", second.code: "1", third.code: "1"},
             {first.code: "2", second.code: "2", third.code: "1"},
             {first.code: "3", second.code: "3", third.code: "3"}]
    for number, data in enumerate(steps, start=1):
        count = len(_rows_of(record))
        assert _save(lst, record, manager.user, title="Сервер", **data).changed is True
        rows = _rows_of(record)
        assert len(rows) == count + 1, f"шаг {number}"
        assert rows[-1].kind == "changed"
    assert [len(_rows_of(record)[i].changes) for i in (1, 2, 3)] == [1, 1, 3]
    count = len(_rows_of(record))
    response = editor.client.post(f"/lists/{lst.pk}/{record.number}/edit/", {
        "title": "Сервер", first.code: "4", second.code: "3", third.code: "3", "base_version": str(record.version)})
    assert response.status_code == 302
    rows = _rows_of(record)
    assert len(rows) == count + 1
    assert (rows[-1].kind, rows[-1].actor_id) == ("changed", editor.user.pk)
    assert list(_entries(rows[-1])) == [first.code]
    assert _kinds(_history(editor.client, lst, record)) == ["changed"] * 4 + ["created"]
