"""T-6102: права и видимость списков (FR-501, FR-512, FR-513, FR-514, FR-543). Сценарии 1 и 13 спеки.

Таблица «адрес × кто» (CONTRACT-006, 10.4; без адресов заявок — их проверяет T-6114, решение 31 задач): «нет»,
«читает», «правит», «управляет»; уволенный, заблокированный и приглашённый; подразделение и вложенное подразделение;
перевод сотрудника; пункт меню; подсказки людей и узлов; вход без пароля; выключенные `org` и `lists`.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-006, шапка).

Допущения писателя (см. отчёт): `<file_id>` в адресах файлов — номер строки `RecordFile`; службы без права отвечают
`PermissionDenied` или `Http404` (контракт называет исключение только у `archive.purge`).
"""
import re
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import quote, unquote

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import factories, support
from tests import support_lists as ll
from tests import support_org as org
from tests.support import HX
from tests.support_lists import Session

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _storage(protected_root, monkeypatch):
    """Файлы пишутся во временный том, проверка ClamAV отвечает «чисто» (подмена строкой, контракт 1.2)."""
    ll.scan_clean(monkeypatch)


# --- разбор разметки (помощник только этого файла) -----------------------------------------------------

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


def _html(response) -> str:
    return response.content.decode("utf-8")


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(_html(response))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; в имени атрибута `_` означает дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [node for node in scope.walk()
            if (tag is None or node.tag == tag)
            and all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items())]


def _model(label: str):
    return support.model(label)


def _fresh(user):
    """Сотрудник из базы с пустым кэшем прав и без `_lists_scope` (изменение в тесте не доходит до фиксации)."""
    from django.core.cache import cache

    from apps.core.services import permissions

    cache.delete(permissions._key(user.pk))
    return _model("core.User").objects.get(pk=user.pk)


def _session(user) -> Session:
    return Session(user, support.logged_in(user))


def _nobody() -> Session:
    """Действующий сотрудник без прав на списки."""
    return _session(support.make_employee())


def _member_of(unit) -> Session:
    user = support.make_employee()
    org.make_member(user, unit)
    return _session(user)


def _manage_role():
    """Роль с правом `lists.manage` (строка права создаётся, если её нет)."""
    Permission = _model("core.Permission")
    for code in ll.PERMISSIONS_006:
        Permission.objects.get_or_create(code=code, defaults={"title": ll.TITLES_006[code]})
    return factories.make_role(permissions=ll.PERMISSIONS_006)


def _login_redirect(response, path: str) -> bool:
    if response.status_code != 302 or not response["Location"].startswith("/login/") or "next=" not in response["Location"]:
        return False
    return unquote(response["Location"].split("next=", 1)[1]) == path


# --- мир теста: список с записями, файлами, заданием загрузки -----------------------------------------

def _world(user=None):
    """Список с полями (строка, список значений, файл, лишнее, пустое), записями на каждое действие и пустой список
    для удаления; `user` — автор заданий загрузки (по умолчанию новый сотрудник)."""
    lst = ll.make_list()
    f_str = ll.add_field(lst, "string", "Инвентарный номер", show_in_table=True)
    f_choice = ll.add_field(lst, "choice", "Статус", choices=("Новый", "В работе"))
    f_file = ll.add_field(lst, "file", "Акт")
    f_extra = ll.add_field(lst, "string", "Лишнее")
    f_empty = ll.add_field(lst, "string", "Пустое")
    author = support.make_employee()

    def record(title, **kw):
        return ll.make_record(lst, title, kw.pop("values", None), created_by=author, **kw)

    w = SimpleNamespace(lst=lst, f_str=f_str, f_choice=f_choice, f_file=f_file, f_extra=f_extra, f_empty=f_empty)
    w.card = record("Запись для проверки А", values={f_str.code: "INV-1"})
    w.shown = ll.attach_file(w.card, f_file, "акт-а.pdf", write=True)
    w.edit = record("Запись для правки")
    w.to_archive = record("Запись в архив")
    w.archived = record("Архивная запись", archived=True)
    w.to_purge = record("Запись на удаление", archived=True)
    w.bulk = record("Запись групповая")
    w.upload = record("Запись для файла")
    w.with_file = record("Запись с файлом")
    w.removable = ll.attach_file(w.with_file, f_file, "акт-б.pdf", write=True)
    w.empty_list = ll.make_list()
    w.titles = [r.title for r in (w.card, w.edit, w.to_archive, w.archived, w.to_purge, w.bulk, w.upload,
                                  w.with_file)] + [lst.name, w.empty_list.name, "акт-а.pdf", "акт-б.pdf"]
    owner = user or support.make_employee()
    Job = _model("lists.ImportJob")
    from django.utils import timezone

    row = {"row": 2, "cells": ["Из загрузки"], "result": "will_create", "reason": "", "number": None}
    w.job_map = Job.objects.create(
        list=lst, created_by=owner, created_at=timezone.now(), file_name="t.csv", file_format="csv", state="mapping",
        header=["Название"], mapping={}, rows=[dict(row)], summary={})
    w.job_prev = Job.objects.create(
        list=lst, created_by=owner, created_at=timezone.now(), file_name="t.csv", file_format="csv", state="preview",
        header=["Название"], mapping={"0": "title"}, rows=[dict(row)], summary={})
    return w


def _grant_both(w, role=None, unit=None, level="read"):
    for target in (w.lst, w.empty_list):
        ll.grant_list(target, role or unit, level)


def _actor(kind, w) -> Session:
    """Вошедший сотрудник вида «нет», «читает», «правит», «управляет»; наборы — на список и на пустой список."""
    if kind == "none":
        return _nobody()
    if kind == "manager":
        return ll.as_manager()
    role = factories.make_role()
    _grant_both(w, role, level="read" if kind == "reader" else "edit")
    return _session(support.make_employee(roles=[role]))


def _own_jobs(w, user):
    _model("lists.ImportJob").objects.filter(pk__in=[w.job_map.pk, w.job_prev.pk]).update(created_by=user)


def _upload(name="a.txt", data=b"hello"):
    return SimpleUploadedFile(name, data, content_type="text/plain")


# --- таблица «адрес × кто» (CONTRACT-006, 10.4) ---------------------------------------------------------
# строка: (подпись, кому открыто, успех для разрешённого, построитель (метод, путь, данные))

def _fields_order(w):
    Field = _model("lists.Field")
    return list(Field.objects.filter(list=w.lst).order_by("order").values_list("code", flat=True))


def _rows():
    L = lambda w: f"/lists/{w.lst.pk}/"  # noqa: E731
    C = lambda w, rec: f"/lists/{w.lst.pk}/{rec.number}/"  # noqa: E731
    S = lambda w: f"/lists/{w.lst.pk}/settings/"  # noqa: E731
    return [
        ("главная", "read", 200, lambda w: ("GET", "/lists/", None)),
        ("новый список, форма", "manage", 200, lambda w: ("GET", "/lists/new/", None)),
        ("новый список, создание", "manage", 302, lambda w: ("POST", "/lists/new/", {"name": f"Новый {w.lst.pk}"})),
        ("таблица", "read", 200, lambda w: ("GET", L(w), None)),
        ("значения фильтра", "read", 200, lambda w: ("GET", L(w) + f"filter-values/{w.f_choice.code}/", None)),
        ("выгрузка", "read", 200, lambda w: ("GET", L(w) + "export/", None)),
        ("столбцы", "read", 302,
         lambda w: ("POST", L(w) + "columns/", {"columns": ["title", w.f_str.code]})),
        ("настройка, основное GET", "manage", 200, lambda w: ("GET", S(w), None)),
        ("настройка, основное POST", "manage", 302,
         lambda w: ("POST", S(w), {"name": w.lst.name, "description": "Описание"})),
        ("настройка, поля", "manage", 200, lambda w: ("GET", S(w) + "fields/", None)),
        ("настройка, новое поле GET", "manage", 200, lambda w: ("GET", S(w) + "fields/new/", None)),
        ("настройка, новое поле POST", "manage", 302,
         lambda w: ("POST", S(w) + "fields/new/", {"name": "Дополнительное", "type": "string"})),
        ("настройка, поле GET", "manage", 200, lambda w: ("GET", S(w) + f"fields/{w.f_extra.code}/", None)),
        ("настройка, поле POST", "manage", 302,
         lambda w: ("POST", S(w) + f"fields/{w.f_extra.code}/", {"name": "Лишнее поле"})),
        ("настройка, значения", "manage", 302,
         lambda w: ("POST", S(w) + f"fields/{w.f_choice.code}/choices/", {"id": "", "title": "Третье"})),
        ("настройка, вверх", "manage", 302, lambda w: ("POST", S(w) + f"fields/{w.f_choice.code}/up/", None)),
        ("настройка, вниз", "manage", 302, lambda w: ("POST", S(w) + f"fields/{w.f_str.code}/down/", None)),
        ("настройка, порядок", "manage", 302,
         lambda w: ("POST", S(w) + "fields/order/", {"codes": _fields_order(w)})),
        ("настройка, скрыть", "manage", 302, lambda w: ("POST", S(w) + f"fields/{w.f_extra.code}/hide/", None)),
        ("настройка, показать", "manage", 302, lambda w: ("POST", S(w) + f"fields/{w.f_extra.code}/show/", None)),
        ("настройка, удалить поле", "manage", 302, lambda w: ("POST", S(w) + f"fields/{w.f_empty.code}/delete/", None)),
        ("настройка, права GET", "manage", 200, lambda w: ("GET", S(w) + "access/", None)),
        ("настройка, права POST", "manage", 302,
         lambda w: ("POST", S(w) + "access/", {"readers": [], "editors": []})),
        ("удалить пустой список", "manage", 302,
         lambda w: ("POST", f"/lists/{w.empty_list.pk}/delete/", None)),
        ("добавить запись GET", "edit", 200, lambda w: ("GET", L(w) + "add/", None)),
        ("добавить запись POST", "edit", 302,
         lambda w: ("POST", L(w) + "add/", {"title": "Новая запись", w.f_str.code: "NEW-1"})),
        ("карточка", "read", 200, lambda w: ("GET", C(w, w.card), None)),
        ("история", "read", 200, lambda w: ("GET", C(w, w.card) + "history/", None)),
        ("этикетка", "read", 200, lambda w: ("GET", C(w, w.card) + "label/", None)),
        ("лист этикеток", "read", 200, lambda w: ("GET", L(w) + f"labels/?n={w.card.number}", None)),
        ("скачать файл", "read", 200, lambda w: ("GET", C(w, w.card) + f"files/{w.shown.pk}/", None)),
        ("подсказка записей", "read", 200, lambda w: ("GET", L(w) + f"pick/?q={quote('Запись')}", None)),
        ("правка GET", "edit", 200, lambda w: ("GET", C(w, w.edit) + "edit/", None)),
        ("правка POST", "edit", 302,
         lambda w: ("POST", C(w, w.edit) + "edit/",
                    {"title": "Запись после правки", w.f_str.code: "E-1", "base_version": str(w.edit.version)})),
        ("в архив", "edit", 302, lambda w: ("POST", C(w, w.to_archive) + "archive/", None)),
        ("вернуть", "edit", 302, lambda w: ("POST", C(w, w.archived) + "restore/", None)),
        ("групповое в архив", "edit", 200, lambda w: ("POST", L(w) + "bulk-archive/", {"n": [w.bulk.number]})),
        ("прикрепить файл", "edit", 302,
         lambda w: ("POST", C(w, w.upload) + "files/", {"field": w.f_file.code, "file": _upload()})),
        ("удалить файл", "edit", 302,
         lambda w: ("POST", C(w, w.with_file) + f"files/{w.removable.pk}/delete/", None)),
        ("удалить навсегда", "manage", 302, lambda w: ("POST", C(w, w.to_purge) + "purge/", None)),
        ("загрузка GET", "edit", 200, lambda w: ("GET", L(w) + "import/", None)),
        ("загрузка POST", "edit", 302,
         lambda w: ("POST", L(w) + "import/",
                    {"file": _upload("t.csv", ll.csv_of(["Название"], [["Икс"]]))})),
        ("задание GET", "edit", 200, lambda w: ("GET", L(w) + f"import/{w.job_map.pk}/", None)),
        ("задание POST", "edit", 200, lambda w: ("POST", L(w) + f"import/{w.job_map.pk}/", {"map.0": "title"})),
        ("подтвердить загрузку", "edit", 200, lambda w: ("POST", L(w) + f"import/{w.job_prev.pk}/confirm/", None)),
        ("образец", "edit", 200, lambda w: ("GET", L(w) + "sample/", None)),
        ("люди", "edits_any", 200, lambda w: ("GET", f"/lists/people/?q={quote('Тест')}", None)),
        ("узлы", "edits_any", 200, lambda w: ("GET", f"/lists/units/?q={quote('Узел')}", None)),
    ]


_EXPECT = {
    "read": {"none": 404, "reader": "ok", "editor": "ok", "manager": "ok"},
    "edit": {"none": 404, "reader": 403, "editor": "ok", "manager": "ok"},
    "manage": {"none": 404, "reader": 403, "editor": 403, "manager": "ok"},
    "edits_any": {"none": 404, "reader": 404, "editor": "ok", "manager": "ok"},
}


def _send(client, method, path, data, **extra):
    if method == "GET":
        return client.get(path, **extra)
    return client.post(path, data or {}, **extra)


def _state(w):
    """Снимок того, что чужие действия менять не должны."""
    List, Field, Record = _model("lists.List"), _model("lists.Field"), _model("lists.Record")
    Access, RecordFile = _model("lists.Access"), _model("lists.RecordFile")
    Job = _model("lists.ImportJob")
    return {
        "lists": sorted(List.objects.values_list("pk", "name", "description")),
        "fields": sorted(Field.objects.filter(list=w.lst).values_list("code", "hidden", "order", "name")),
        "records": sorted(Record.objects.filter(list=w.lst).values_list("number", "title", "archived", "version")),
        "access": sorted(Access.objects.filter(list__in=[w.lst, w.empty_list]).values_list("list_id", "level", "role_id",
                                                                                           "unit_id")),
        "files": sorted(RecordFile.objects.filter(record__list=w.lst).values_list("pk", "record_id")),
        "jobs": sorted(Job.objects.filter(list=w.lst).values_list("pk", "state")),
    }


def test_access_matrix_contract_urls_by_actor_return_200_403_404_per_table():
    """FR-512, FR-513, FR-514: каждый адрес таблицы «адрес × кто» (10.4) отвечает «нет» — 404, «читает» — 200 или 403,
    «правит» — 200/302 или 403, «управляет» — 200/302; отказ не содержит названий списка, записей и файлов; у «нет»,
    «читает» и «правит» после всех запросов состояние базы прежнее."""
    for kind in ("none", "reader", "editor", "manager"):
        w = _world()
        actor = _actor(kind, w)
        _own_jobs(w, actor.user)
        before = _state(w)
        for label, need, ok, build in _rows():
            method, path, data = build(w)
            expected = _EXPECT[need][kind]
            expected = ok if expected == "ok" else expected
            response = _send(actor.client, method, path, data)
            assert response.status_code == expected, (
                f"{kind}: {label}: {method} {path}: ждали {expected}, получили {response.status_code}")
            if expected in (403, 404):
                body = _html(response)
                leaked = [text for text in w.titles if text in body]
                assert not leaked, f"{kind}: {label}: отказ выдал данные объекта: {leaked}"
        if kind != "manager":
            after = _state(w)
            # создание записи, правка и файл — только у «правит»; у остальных состояние не меняется
            if kind in ("none", "reader"):
                assert after == before, f"{kind}: состояние изменилось: " + ", ".join(k for k in before if before[k] != after[k])
            else:
                for part in ("lists", "fields", "access"):
                    assert after[part] == before[part], f"editor изменил {part}"
                assert any(row[1] == "Запись после правки" for row in after["records"])


def test_reader_via_role_gets_403_on_add_edit_archive_import_and_settings():
    """FR-513, FR-514: читающий через роль видит таблицу (200), но добавление, правка, «В архив», загрузка и настройка
    отвечают 403 и на GET, и на POST, и на HTMX; ни записи, ни задания, ни правки в базе не появляется."""
    w = _world()
    reader = ll.as_reader(w.lst)
    _own_jobs(w, reader.user)
    assert reader.client.get(f"/lists/{w.lst.pk}/").status_code == 200
    before = _state(w)
    base, card = f"/lists/{w.lst.pk}/", f"/lists/{w.lst.pk}/{w.edit.number}/"
    attempts = [
        ("GET", base + "add/", None), ("POST", base + "add/", {"title": "Чужая запись"}),
        ("GET", card + "edit/", None),
        ("POST", card + "edit/", {"title": "Чужая правка", "base_version": str(w.edit.version)}),
        ("POST", f"/lists/{w.lst.pk}/{w.to_archive.number}/archive/", None),
        ("POST", base + "bulk-archive/", {"n": [w.bulk.number]}),
        ("GET", base + "import/", None),
        ("POST", base + "import/", {"file": _upload("t.csv", ll.csv_of(["Название"], [["Икс"]]))}),
        ("GET", base + "settings/", None), ("POST", base + "settings/", {"name": "Чужое имя", "description": ""}),
        ("GET", base + "settings/fields/", None), ("GET", base + "settings/access/", None),
    ]
    for method, path, data in attempts:
        for extra in ({}, HX):
            if data and "file" in data:
                data = {"file": _upload("t.csv", ll.csv_of(["Название"], [["Икс"]]))}
            response = _send(reader.client, method, path, data, **extra)
            assert response.status_code == 403, f"{method} {path} {extra}: {response.status_code}"
    assert _state(w) == before


def test_member_of_child_unit_reads_list_granted_to_parent_unit():
    """FR-513: право подразделения действует для его сотрудников и для сотрудников вложенных подразделений; сотрудник
    соседнего подразделения список не видит (404); «Правят» подразделения открывают добавление записи."""
    parent, child, other = org.make_unit(), None, org.make_unit()
    child = org.make_unit(parent=parent)
    lst, editable = ll.make_list(), ll.make_list()
    ll.make_record(lst, "Запись подразделения")
    ll.grant_list(lst, parent, "read")
    ll.grant_list(editable, parent, "edit")
    in_child, in_parent, in_other = _member_of(child), _member_of(parent), _member_of(other)
    for who in (in_child, in_parent):
        assert who.client.get(f"/lists/{lst.pk}/").status_code == 200
        home = who.client.get("/lists/")
        assert home.status_code == 200
        assert {int(n.attrs["data-list-id"]) for n in _q(_tree(home), "li", data_list_id=True)} == {lst.pk, editable.pk}
        assert who.client.get(f"/lists/{lst.pk}/add/").status_code == 403
        assert who.client.get(f"/lists/{editable.pk}/add/").status_code == 200
    assert in_other.client.get(f"/lists/{lst.pk}/").status_code == 404
    assert in_other.client.get("/lists/").status_code == 404


def test_transferred_employee_loses_unit_access_on_next_request():
    """FR-513: сотрудника перевели из подразделения с правом в другое — со следующего запроса список ему не открыт
    (список и главная — 404); перевод обратно возвращает доступ."""
    first, second = org.make_unit(), org.make_unit()
    lst = ll.make_list()
    ll.grant_list(lst, first, "read")
    who = _member_of(first)
    Membership = _model("org.Membership")
    assert who.client.get(f"/lists/{lst.pk}/").status_code == 200
    Membership.objects.filter(user=who.user).delete()
    org.make_member(who.user, second)
    assert who.client.get(f"/lists/{lst.pk}/").status_code == 404
    assert who.client.get("/lists/").status_code == 404
    Membership.objects.filter(user=who.user).delete()
    org.make_member(who.user, first)
    assert who.client.get(f"/lists/{lst.pk}/").status_code == 200


def test_editor_via_role_reads_and_edits_list_but_gets_403_on_settings_and_purge():
    """FR-513, FR-514: правящий через роль читает, добавляет и правит запись (302), но настройка списка и удаление
    навсегда — 403; запись в архиве после отказа остаётся."""
    w = _world()
    editor = ll.as_editor(w.lst)
    base = f"/lists/{w.lst.pk}/"
    assert editor.client.get(base).status_code == 200
    created = editor.client.post(base + "add/", {"title": "Запись правящего"})
    assert created.status_code == 302
    Record = _model("lists.Record")
    assert Record.objects.filter(list=w.lst, title="Запись правящего").exists()
    edited = editor.client.post(f"{base}{w.edit.number}/edit/",
                                {"title": "Правка правящего", "base_version": str(w.edit.version)})
    assert edited.status_code == 302
    assert Record.objects.get(pk=w.edit.pk).title == "Правка правящего"
    for path in (base + "settings/", base + "settings/fields/", base + "settings/access/"):
        assert editor.client.get(path).status_code == 403
    assert editor.client.post(base + "settings/", {"name": "Другое имя", "description": ""}).status_code == 403
    purge = editor.client.post(f"{base}{w.to_purge.number}/purge/")
    assert purge.status_code == 403
    assert Record.objects.filter(pk=w.to_purge.pk, archived=True).exists()
    assert _model("lists.List").objects.get(pk=w.lst.pk).name == w.lst.name


def test_manager_reads_edits_and_configures_every_list_outside_sets():
    """FR-512: управляющий (право `lists.manage`) без строк в наборах читает таблицу, добавляет и правит запись,
    меняет настройку списка и создаёт новый список; главная показывает все списки."""
    lst = ll.make_list()
    existing = ll.make_record(lst, "Запись управляемого списка")
    assert not _model("lists.Access").objects.filter(list=lst).exists()
    manager = ll.as_manager()
    base = f"/lists/{lst.pk}/"
    assert manager.client.get(base).status_code == 200
    home = manager.client.get("/lists/")
    assert home.status_code == 200
    assert lst.pk in {int(n.attrs["data-list-id"]) for n in _q(_tree(home), "li", data_list_id=True)}
    assert manager.client.post(base + "add/", {"title": "Запись управляющего"}).status_code == 302
    Record = _model("lists.Record")
    assert Record.objects.filter(list=lst, title="Запись управляющего").exists()
    assert manager.client.post(f"{base}{existing.number}/edit/",
                               {"title": "Правка управляющего", "base_version": str(existing.version)}).status_code == 302
    assert Record.objects.get(pk=existing.pk).title == "Правка управляющего"
    assert manager.client.post(base + "settings/", {"name": "Переименован управляющим", "description": "Новое"}
                               ).status_code == 302
    lst.refresh_from_db()
    assert lst.name == "Переименован управляющим" and lst.description == "Новое"
    assert manager.client.post("/lists/new/", {"name": "Создан управляющим", "description": ""}).status_code == 302
    assert _model("lists.List").objects.filter(name="Создан управляющим").exists()


def test_dismissed_blocked_and_invited_in_sets_get_empty_scope_and_404():
    """FR-513: уволенный, заблокированный и приглашённый, чья роль стоит в наборах (и даже у роли с правом
    `lists.manage`), получают пустой `Scope`, `access.get_list` отвечает `Http404`; действующий с той же ролью читает."""
    from django.http import Http404

    from apps.lists.services import access

    lst = ll.make_list()
    reader_role, manage_role = factories.make_role(), _manage_role()
    ll.grant_list(lst, reader_role, "edit")
    live = _fresh(support.make_employee(roles=[reader_role]))
    assert lst.pk in access.scope(live).readable
    assert access.get_list(live, lst.pk).pk == lst.pk
    for state in ("dismissed", "blocked", "invited"):
        for role in (reader_role, manage_role):
            user = _fresh(support.make_employee(roles=[role], state=state))
            scope = access.scope(user)
            assert scope.manage is False and scope.readable == frozenset() and scope.editable == frozenset(), (state, role)
            with pytest.raises(Http404):
                access.get_list(user, lst.pk)
            assert access.sees_section(user) is False
            assert access.can_read(user, lst) is False and access.can_edit(user, lst) is False


def test_unreadable_list_record_history_file_export_label_and_job_respond_as_nonexistent():
    """FR-514: список, который сотрудник не читает (он читает другой), — для него как несуществующий: таблица, запись,
    история, файл, выгрузка, этикетки, подсказка записей и задание загрузки отвечают 404 как у несуществующих
    номеров, в теле нет ни названия списка, ни записи, ни имени файла."""
    own, w = ll.make_list(), _world()
    ll.make_record(own, "Своя запись")
    who = ll.as_reader(own)
    assert who.client.get(f"/lists/{own.pk}/").status_code == 200
    ghost = max(w.lst.pk, own.pk) + 1000
    base, card = f"/lists/{w.lst.pk}/", f"/lists/{w.lst.pk}/{w.card.number}/"
    twin_base, twin_card = f"/lists/{ghost}/", f"/lists/{ghost}/{w.card.number}/"
    pairs = [
        ("GET", base, twin_base), ("GET", card, twin_card), ("GET", card + "history/", twin_card + "history/"),
        ("GET", card + f"files/{w.shown.pk}/", twin_card + f"files/{w.shown.pk}/"),
        ("GET", base + "export/", twin_base + "export/"), ("GET", card + "label/", twin_card + "label/"),
        ("GET", base + f"labels/?n={w.card.number}", twin_base + f"labels/?n={w.card.number}"),
        ("GET", base + f"pick/?q={quote('Запись')}", twin_base + f"pick/?q={quote('Запись')}"),
        ("GET", base + f"import/{w.job_map.pk}/", twin_base + f"import/{w.job_map.pk}/"),
        ("POST", base + f"import/{w.job_map.pk}/", twin_base + f"import/{w.job_map.pk}/"),
        ("POST", base + f"import/{w.job_prev.pk}/confirm/", twin_base + f"import/{w.job_prev.pk}/confirm/"),
    ]
    _own_jobs(w, who.user)
    before = _state(w)
    for method, path, twin in pairs:
        response = _send(who.client, method, path, {"map.0": "title"})
        ghost_response = _send(who.client, method, twin, {"map.0": "title"})
        assert ghost_response.status_code == 404, f"{twin}: ждали 404"
        assert response.status_code == 404, f"{method} {path}: {response.status_code}"
        body = _html(response)
        assert not [text for text in w.titles if text in body], f"{path}: в отказе есть данные объекта"
    assert _state(w) == before


def test_filter_values_of_unreadable_list_respond_as_nonexistent():
    """FR-514: значения фильтра чужого списка — 404; поле-ссылка на нечитаемый целевой список, скрытое поле и поле
    не ссылочного типа — 404; поле «список значений» читаемого списка — 200 с `ul[data-lists-pick]`."""
    own, hidden_target = ll.make_list(), ll.make_list()
    ll.make_record(hidden_target, "Запись недоступного списка-цели")
    choice = ll.add_field(own, "choice", "Статус", choices=("Новый", "Закрыт"))
    link = ll.add_field(own, "record", "Ссылка", target=hidden_target)
    plain = ll.add_field(own, "string", "Строка")
    hidden = ll.add_field(own, "choice", "Скрытый статус", choices=("Тайный",), hidden=True)
    foreign = ll.make_list()
    foreign_choice = ll.add_field(foreign, "choice", "Чужой статус", choices=("Чужой",))
    who = ll.as_reader(own)
    ok = who.client.get(f"/lists/{own.pk}/filter-values/{choice.code}/")
    assert ok.status_code == 200 and _q(_tree(ok), "ul", data_lists_pick=True)
    assert "Новый" in _html(ok)
    for lst, field in ((own, link), (own, plain), (own, hidden), (foreign, foreign_choice)):
        response = who.client.get(f"/lists/{lst.pk}/filter-values/{field.code}/?q=")
        assert response.status_code == 404, (lst.pk, field.code, response.status_code)
        body = _html(response)
        assert "Запись недоступного списка-цели" not in body and "Тайный" not in body and "Чужой" not in body


def test_forbidden_buttons_are_absent_from_markup_per_actor():
    """FR-514: кнопки, которых нельзя, не выводятся: добавить, загрузить, групповое «В архив», правка, «В архив»,
    «Вернуть», прикрепить и удалить файл — только правящему и управляющему; выгрузка, этикетки и скачивание — всем
    читающим; «Удалить навсегда» — только управляющему и только у записи в архиве; «Создать список» — управляющему."""
    w = _world()
    reader, editor, manager = ll.as_reader(w.lst), ll.as_editor(w.lst), ll.as_manager()
    base = f"/lists/{w.lst.pk}/"
    card, archived = f"{base}{w.card.number}/", f"{base}{w.to_purge.number}/"

    def present(session, path, tag, **attrs) -> bool:
        response = session.client.get(path)
        assert response.status_code == 200, f"{path}: {response.status_code}"
        return bool(_q(_tree(response), tag, **attrs))

    grid = {"record-add": "a", "import": "a", "bulk-archive": "button", "export": "a", "bulk-labels": "button"}
    grid_rights = {"record-add": "edit", "import": "edit", "bulk-archive": "edit", "export": "read", "bulk-labels": "read"}
    wanted = lambda who, level: level == "read" or who is not reader  # noqa: E731
    for who in (reader, editor, manager):
        for action, tag in grid.items():
            assert present(who, base, tag, data_action=action) == wanted(who, grid_rights[action]), (who.user.pk, action)
        assert present(who, card, "a", data_action="record-label") is True
        assert present(who, card, "a", data_action="record-edit") == (who is not reader)
        assert present(who, card, "button", data_action="record-archive") == (who is not reader)
        assert present(who, card, "form", data_action="file-attach") == (who is not reader)
        assert present(who, card, "a", data_action="file-download") is True
        assert present(who, card, "button", data_action="record-purge") is False
        assert present(who, archived, "button", data_action="record-restore") == (who is not reader)
        assert present(who, archived, "button", data_action="record-purge") == (who is manager)
        assert present(who, f"{base}{w.with_file.number}/", "button", data_action="file-delete") == (who is not reader)
        assert present(who, "/lists/", "a", data_action="lists-create") == (who is manager)


def test_right_revoked_between_get_and_post_is_rejected_by_service_recheck():
    """FR-514: правящий открыл форму правки, затем право отозвали: POST правки — 403 (читает по-прежнему) или 404
    (не читает), запись не изменилась, истории не прибавилось; службы `records.save` без права тоже не пишут."""
    from django.core.exceptions import PermissionDenied
    from django.http import Http404

    from apps.lists.services import records

    lst = ll.make_list()
    f_str = ll.add_field(lst, "string", "Номер")
    record = ll.make_record(lst, "Запись до отзыва", {f_str.code: "A"})
    role = factories.make_role()
    edit_grant = ll.grant_list(lst, role, "edit")
    user = support.make_employee(roles=[role])
    who = _session(user)
    page = who.client.get(f"/lists/{lst.pk}/{record.number}/edit/")
    assert page.status_code == 200
    version = re.search(r'name="base_version"[^>]*value="(\d+)"', _html(page)) or re.search(
        r'value="(\d+)"[^>]*name="base_version"', _html(page))
    assert version, "в форме правки нет скрытого поля base_version"
    form = {"title": "Запись после отзыва", f_str.code: "B", "base_version": version.group(1)}
    Change, Record = _model("lists.Change"), _model("lists.Record")
    history = Change.objects.filter(record=record).count()
    edit_grant.delete()
    ll.grant_list(lst, role, "read")
    refused = who.client.post(f"/lists/{lst.pk}/{record.number}/edit/", form)
    assert refused.status_code == 403
    _model("lists.Access").objects.filter(list=lst).delete()
    gone = who.client.post(f"/lists/{lst.pk}/{record.number}/edit/", form)
    assert gone.status_code == 404
    saved = Record.objects.get(pk=record.pk)
    assert (saved.title, saved.values, saved.version) == ("Запись до отзыва", {f_str.code: "A"}, 1)
    assert Change.objects.filter(record=record).count() == history
    with pytest.raises((PermissionDenied, Http404)):
        records.save(lst, record.number, {"title": "Из службы", f_str.code: "C"}, base_version=1, actor=_fresh(user))
    saved = Record.objects.get(pk=record.pk)
    assert (saved.title, saved.version) == ("Запись до отзыва", 1)
    assert Change.objects.filter(record=record).count() == history


def test_direct_post_of_every_action_without_button_is_checked_on_server():
    """FR-514: действие без кнопки по прямому POST (в том числе HTMX) проверяется на сервере: у читающего — «Вернуть»,
    файлы, «Удалить навсегда», настройка полей и прав, создание и удаление списка, подтверждение загрузки; у
    правящего — удаление навсегда, настройка и удаление списка; ответ 403, база без изменений, истории не прибавилось."""
    w = _world()
    base = f"/lists/{w.lst.pk}/"
    card = lambda rec: f"{base}{rec.number}/"  # noqa: E731
    Change = _model("lists.Change")
    common = [
        ("POST", card(w.to_purge) + "purge/", None),
        ("POST", f"/lists/{w.empty_list.pk}/delete/", None),
        ("POST", base + f"settings/fields/{w.f_extra.code}/hide/", None),
        ("POST", base + f"settings/fields/{w.f_empty.code}/delete/", None),
        ("POST", base + "settings/access/", {"readers": [], "editors": []}),
        ("POST", base + "settings/", {"name": "Чужое имя", "description": ""}),
        ("POST", "/lists/new/", {"name": "Чужой список"}),
    ]
    reader_only = [
        ("POST", card(w.archived) + "restore/", None),
        ("POST", card(w.upload) + "files/", {"field": w.f_file.code, "file": _upload()}),
        ("POST", card(w.with_file) + f"files/{w.removable.pk}/delete/", None),
        ("POST", base + "settings/fields/new/", {"name": "Чужое поле", "type": "string"}),
        ("POST", base + f"import/{w.job_prev.pk}/confirm/", None),
    ]
    for kind, attempts in (("reader", reader_only + common), ("editor", common)):
        actor = _actor(kind, w)
        _own_jobs(w, actor.user)
        before, history = _state(w), Change.objects.count()
        for method, path, data in attempts:
            for extra in ({}, HX):
                if data and "file" in data:
                    data = {"field": w.f_file.code, "file": _upload()}
                response = _send(actor.client, method, path, data, **extra)
                assert response.status_code == 403, f"{kind}: {path} {extra}: {response.status_code}"
        assert _state(w) == before, kind
        assert Change.objects.count() == history, kind
    manager = _actor("manager", w)
    assert manager.client.post(card(w.to_purge) + "purge/").status_code == 302


def test_edit_set_lists_are_included_in_readable_set():
    """FR-513: «Правят» читают тоже: у списка только с набором «Правят» (роль или подразделение) `scope.readable`
    содержит его, `editable` тоже; у списка только с «Читают» `editable` его не содержит; таблица открывается."""
    from apps.lists.services import access

    by_role, by_unit, read_only = ll.make_list(), ll.make_list(), ll.make_list()
    role, unit = factories.make_role(), org.make_unit()
    ll.grant_list(by_role, role, "edit")
    ll.grant_list(by_unit, unit, "edit")
    ll.grant_list(read_only, role, "read")
    user = support.make_employee(roles=[role])
    org.make_member(user, unit)
    scope = access.scope(_fresh(user))
    assert scope.manage is False
    assert scope.readable == frozenset({by_role.pk, by_unit.pk, read_only.pk})
    assert scope.editable == frozenset({by_role.pk, by_unit.pk})
    client = support.logged_in(user)
    for lst in (by_role, by_unit, read_only):
        assert client.get(f"/lists/{lst.pk}/").status_code == 200
    assert client.get(f"/lists/{read_only.pk}/add/").status_code == 403
    assert client.get(f"/lists/{by_unit.pk}/add/").status_code == 200


def test_in_edit_set_ignores_manager_right():
    """FR-512, FR-513: `in_edit_set` смотрит только набор «Правят»: управляющий без набора — `can_edit` истинно,
    `in_edit_set` ложно; правящий по роли и по подразделению — истинно; читающий — оба ложны."""
    from apps.lists.services import access

    lst = ll.make_list()
    unit, role = org.make_unit(), factories.make_role()
    ll.grant_list(lst, unit, "edit")
    manager = _fresh(ll.as_manager().user)
    assert access.can_manage(manager) is True and access.can_edit(manager, lst) is True
    assert access.can_read(manager, lst) is True
    assert access.in_edit_set(manager, lst) is False
    by_role = _fresh(ll.as_editor(lst).user)
    assert access.in_edit_set(by_role, lst) is True and access.can_manage(by_role) is False
    in_unit = support.make_employee()
    org.make_member(in_unit, unit)
    assert access.in_edit_set(_fresh(in_unit), lst) is True
    reader = _fresh(ll.as_reader(lst).user)
    assert access.can_read(reader, lst) is True
    assert access.can_edit(reader, lst) is False and access.in_edit_set(reader, lst) is False
    both = _fresh(support.make_employee(roles=[_manage_role()]))
    ll.grant_list(lst, both.roles.first(), "edit")
    assert access.in_edit_set(_fresh(both), lst) is True


def test_unit_role_from_role_sources_grants_list_access_via_role_ids():
    """FR-513: роль, выданная узлу (точка `role_sources` модуля `org`), попадает в `permissions.role_ids(user)` и даёт
    сотруднику узла доступ по набору списка; у сотрудника без ролей и узлов `role_ids` — пустое множество."""
    from apps.core.services import permissions
    from apps.lists.services import access

    lst = ll.make_list()
    unit_role, personal = factories.make_role(), factories.make_role()
    ll.grant_list(lst, unit_role, "read")
    unit = org.make_unit()
    org.make_unit_role(unit, unit_role)
    via_unit = support.make_employee()
    org.make_member(via_unit, unit)
    both = support.make_employee(roles=[personal])
    org.make_member(both, unit)
    plain = support.make_employee()
    assert permissions.role_ids(_fresh(plain)) == frozenset()
    assert permissions.role_ids(_fresh(via_unit)) == frozenset({unit_role.pk})
    assert permissions.role_ids(_fresh(both)) == frozenset({unit_role.pk, personal.pk})
    assert access.can_read(_fresh(via_unit), lst) is True
    assert access.can_read(_fresh(plain), lst) is False
    assert support.logged_in(via_unit).get(f"/lists/{lst.pk}/").status_code == 200
    assert support.logged_in(plain).get(f"/lists/{lst.pk}/").status_code == 404


def test_unit_chain_ids_contains_unit_and_ancestors_so_unit_right_covers_nested_units():
    """FR-513: `unit_chain_ids` — узлы членства и все предки включая корень; без членства пусто; право узла покрывает
    сотрудников вложенных узлов, но не родителей и не соседей."""
    from apps.lists.services import access
    from apps.org.services import structure

    root = org.root_unit()
    top = org.make_unit()
    middle = org.make_unit(parent=top)
    leaf = org.make_unit(parent=middle)
    sibling = org.make_unit(parent=top)
    in_leaf, in_top, in_sibling, nowhere = (support.make_employee() for _ in range(4))
    org.make_member(in_leaf, leaf)
    org.make_member(in_top, top)
    org.make_member(in_sibling, sibling)
    assert structure.unit_chain_ids(in_leaf) == frozenset({root.pk, top.pk, middle.pk, leaf.pk})
    assert structure.unit_chain_ids(in_top) == frozenset({root.pk, top.pk})
    assert structure.unit_chain_ids(nowhere) == frozenset()
    org.make_member(in_leaf, sibling)
    assert structure.unit_chain_ids(in_leaf) == frozenset({root.pk, top.pk, middle.pk, leaf.pk, sibling.pk})
    lst = ll.make_list()
    ll.grant_list(lst, middle, "read")
    assert access.can_read(_fresh(in_leaf), lst) is True
    assert access.can_read(_fresh(in_top), lst) is False
    assert access.can_read(_fresh(in_sibling), lst) is False
    assert access.can_read(_fresh(nowhere), lst) is False


def test_access_change_takes_effect_on_next_request_because_scope_lives_in_request():
    """FR-513: `Scope` считается один раз и хранится в `user._lists_scope` на время запроса: на том же объекте
    пользователя он не меняется, на следующем запросе (новый объект) — меняется; смена набора и роли действует сразу."""
    from apps.lists.services import access

    lst = ll.make_list()
    role = factories.make_role()
    grant = ll.grant_list(lst, role, "read")
    user = support.make_employee(roles=[role])
    same = _fresh(user)
    first = access.scope(same)
    assert lst.pk in first.readable and same._lists_scope is first
    grant.delete()
    assert access.scope(same) is first, "в пределах запроса Scope не пересчитывается"
    assert lst.pk not in access.scope(_fresh(user)).readable
    client = support.logged_in(user)
    assert client.get(f"/lists/{lst.pk}/").status_code == 404
    ll.grant_list(lst, role, "read")
    assert client.get(f"/lists/{lst.pk}/").status_code == 200
    _model("lists.Access").objects.filter(list=lst).delete()
    assert client.get(f"/lists/{lst.pk}/").status_code == 404


def test_without_org_unit_rights_do_not_apply_and_role_rights_stay(monkeypatch):
    """FR-513, FR-543: без `org` права подразделений не действуют (сотрудник узла — 404), права ролей остаются;
    подсказка узлов `/lists/units/` — 404 даже правящему и управляющему, подсказка людей работает."""
    from apps.lists.services import access

    unit = org.make_unit()
    by_unit, by_role = ll.make_list(), ll.make_list()
    role = factories.make_role()
    ll.grant_list(by_unit, unit, "read")
    ll.grant_list(by_role, role, "edit")
    in_unit = _member_of(unit)
    editor = ll.as_editor(by_role)
    manager = ll.as_manager()
    both = support.make_employee(roles=[role])
    org.make_member(both, unit)
    assert in_unit.client.get(f"/lists/{by_unit.pk}/").status_code == 200
    assert editor.client.get("/lists/units/?q=").status_code == 200
    ll.without_app(monkeypatch, "apps.org")
    assert access.can_read(_fresh(in_unit.user), by_unit) is False
    assert access.scope(_fresh(in_unit.user)).readable == frozenset()
    assert in_unit.client.get(f"/lists/{by_unit.pk}/").status_code == 404
    assert in_unit.client.get("/lists/").status_code == 404
    scope = access.scope(_fresh(both))
    assert scope.readable == frozenset({by_role.pk}) and scope.editable == frozenset({by_role.pk})
    assert editor.client.get(f"/lists/{by_role.pk}/add/").status_code == 200
    assert editor.client.get("/lists/units/?q=").status_code == 404
    assert manager.client.get("/lists/units/?q=").status_code == 404
    assert editor.client.get("/lists/people/?q=").status_code == 200


def test_menu_item_lists_has_order_8_empty_permissions_and_is_visible_by_sees_section():
    """FR-501, FR-543: пункт «Списки» — `menu_items` с пустыми `permissions`, `/lists/`, `icons/lists.html`, `order`
    8, без `badge`; видим читающему и управляющему, не виден сотруднику без прав; у администратора меню из
    двенадцати пунктов, «Списки» между «Базой знаний» и «Сотрудниками»; в левом меню страницы есть ссылка."""
    from apps.core import extensions
    from apps.core.services import permissions

    described = [item for func in extensions.registered("menu_items") for item in func() if item.get("title") == "Списки"]
    assert len(described) == 1, f"ждали одно описание пункта «Списки», нашли {len(described)}"
    item = described[0]
    assert tuple(item["permissions"]) == () and item["url"] == "/lists/" and item["order"] == 8
    assert item["icon"] == "icons/lists.html" and "badge" not in item
    lst = ll.make_list()
    reader, manager, nobody = ll.as_reader(lst), ll.as_manager(), _nobody()
    assert callable(item["visible"])
    assert item["visible"](_fresh(reader.user)) is True and item["visible"](_fresh(manager.user)) is True
    assert item["visible"](_fresh(nobody.user)) is False
    for who in (reader, manager):
        entries = [e for e in permissions.menu_for(_fresh(who.user)) if e["title"] == "Списки"]
        assert len(entries) == 1 and entries[0]["url"] == "/lists/" and entries[0]["order"] == 8
        assert "badge" not in entries[0]
        page = who.client.get("/lists/")
        assert page.status_code == 200
        nav = re.search(r'<nav[^>]*id="main-menu".*?</nav>', _html(page), re.S)
        assert nav and 'href="/lists/"' in nav.group(0), "в левом меню нет ссылки на /lists/"
    assert not [e for e in permissions.menu_for(_fresh(nobody.user)) if e["title"] == "Списки"]
    titles = [e["title"] for e in permissions.menu_for(_fresh(support.make_admin()))]
    assert len(titles) == 12, titles
    assert titles.index("База знаний") < titles.index("Списки") < titles.index("Сотрудники")


def test_home_without_readable_lists_and_without_manage_right_is_404():
    """FR-501, FR-514: сотрудник, который не читает ни одного списка и не управляет, получает на `/lists/` 404 (и на
    запрос HTMX); читающий хотя бы один список — 200; наборы чужого подразделения его не открывают."""
    lst = ll.make_list()
    ll.grant_list(lst, org.make_unit(), "read")
    assert ll.as_reader(lst).client.get("/lists/").status_code == 200
    nobody = _nobody()
    for extra in ({}, HX):
        response = nobody.client.get("/lists/", **extra)
        assert response.status_code == 404
        assert lst.name not in _html(response)
    from apps.lists.services import access

    assert access.sees_section(_fresh(nobody.user)) is False


def test_home_shows_only_readable_lists_with_description_and_count_without_archive_manager_sees_all():
    """FR-501, FR-512, FR-513: главная читающего — только читаемые списки (в том числе по набору «Правят») с названием,
    описанием и числом записей без архива; чужой список в разметке не упоминается; управляющему видны все списки и
    кнопка «Создать список»."""
    shown, edited, hidden = ll.make_list(description="Описание первого"), ll.make_list(description="Описание второго"), \
        ll.make_list(description="Описание скрытого")
    for number in range(3):
        ll.make_record(shown, f"Запись {number}")
    ll.make_record(shown, "Архивная запись", archived=True)
    ll.make_record(edited, "Единственная запись")
    ll.make_record(hidden, "Запись скрытого списка")
    role = factories.make_role()
    ll.grant_list(shown, role, "read")
    ll.grant_list(edited, role, "edit")
    reader = _session(support.make_employee(roles=[role]))
    page = reader.client.get("/lists/")
    assert page.status_code == 200
    rows = {int(n.attrs["data-list-id"]): n for n in _q(_tree(page), "li", data_list_id=True)}
    assert set(rows) == {shown.pk, edited.pk}
    name = _q(rows[shown.pk], "a", data_field="name")[0]
    assert name.attrs["href"] == f"/lists/{shown.pk}/" and name.text() == shown.name
    assert _q(rows[shown.pk], None, data_field="description")[0].text() == "Описание первого"
    assert _q(rows[shown.pk], None, data_field="count")[0].text() == "3"
    assert _q(rows[edited.pk], None, data_field="count")[0].text() == "1"
    assert hidden.name not in _html(page) and "Описание скрытого" not in _html(page)
    assert not _q(_tree(page), "a", data_action="lists-create")
    manager = ll.as_manager()
    page = manager.client.get("/lists/")
    ids = {int(n.attrs["data-list-id"]) for n in _q(_tree(page), "li", data_list_id=True)}
    assert ids == set(_model("lists.List").objects.values_list("pk", flat=True)) and hidden.pk in ids
    assert _q(_tree(page), "a", data_action="lists-create")


def test_people_and_units_pickers_are_404_for_who_neither_edits_nor_manages():
    """FR-514: подсказки людей и узлов — 404 тому, кто не правит ни одного списка и не управляет (в том числе
    читающему, на запрос HTMX и с непустым `q`), и 200 правящему и управляющему."""
    lst = ll.make_list()
    editor, manager = ll.as_editor(lst), ll.as_manager()
    reader, nobody = ll.as_reader(lst), _nobody()
    for who in (editor, manager):
        for path in ("/lists/people/?q=" + quote("Тест"), "/lists/units/?q=" + quote("Узел")):
            response = who.client.get(path, **HX)
            assert response.status_code == 200, path
            assert _q(_tree(response), "ul", data_lists_pick=True), path
    for who in (reader, nobody):
        for path in ("/lists/people/", "/lists/people/?q=" + quote("Тест"), "/lists/units/", "/lists/units/?q=" + quote("Узел")):
            for extra in ({}, HX):
                assert who.client.get(path, **extra).status_code == 404, path


def test_people_picker_returns_only_active_with_full_name_and_position_without_email():
    """FR-514: подсказка людей — только действующие сотрудники: ФИО и должность; приглашённые, заблокированные и
    уволенные не возвращаются; почты, телефона в ответе нет."""
    lst = ll.make_list()
    editor = ll.as_editor(lst)
    mail, phone = ll.email_of("ivanov-pick"), ll.phone_of("+7", "999", "000", "11", "22")
    active = support.make_employee(full_name="Иванов Активный", position="Инженер связи", email=mail, phone=phone)
    states = {state: support.make_employee(full_name=f"Иванов {state}", position="Должность", state=state)
              for state in ("invited", "blocked", "dismissed")}
    response = editor.client.get("/lists/people/?q=" + quote("Иванов"))
    assert response.status_code == 200
    body = _html(response)
    ids = {int(n.attrs["data-pick-id"]) for n in _q(_tree(response), "li", data_pick_id=True)}
    assert ids == {active.pk}, ids
    assert "Иванов Активный" in body and "Инженер связи" in body
    assert mail not in body and "ivanov-pick" not in body and phone not in body
    for state, user in states.items():
        assert f"Иванов {state}" not in body


def test_anonymous_is_redirected_to_login_with_next_on_all_list_urls():
    """FR-514: без входа GET и POST на любой адрес раздела — 302 на `/login/?next=<путь>`, и ничего не меняется."""
    w = _world()
    manager = _actor("manager", w)
    _own_jobs(w, manager.user)
    before = _state(w)
    anonymous = support.make_client()
    count = 0
    for label, _need, _ok, build in _rows():
        method, path, data = build(w)
        response = _send(anonymous, method, path, data)
        assert _login_redirect(response, path), f"{label}: {method} {path}: {response.status_code} {response.get('Location')}"
        count += 1
    assert count >= 40
    assert _state(w) == before


def test_without_lists_menu_has_no_lists_item():
    """FR-543: без регистраций `lists` в меню нет пункта «Списки» (`/lists/`), прежние пункты на месте; с ними пункт
    есть и в `menu_for`, и в левом меню страницы."""
    from apps.core.services import permissions

    admin = _fresh(support.make_admin())
    with_lists = permissions.menu_for(admin)
    assert [m for m in with_lists if m["title"] == "Списки" and m["url"] == "/lists/"], "пункта «Списки» нет и с модулем"
    page = support.logged_in(admin).get("/lists/")
    assert page.status_code == 200
    with ll.without_lists():
        menu = permissions.menu_for(_fresh(admin))
        html = _html(support.logged_in(admin).get("/staff/"))
    assert [m for m in menu if m["title"] == "Списки" or m["url"].startswith("/lists/")] == []
    assert len(menu) == len(with_lists) - 1
    assert any(m["url"] == "/staff/" for m in menu), "пропали прежние пункты меню"
    nav = html.split('id="main-menu"', 1)[-1].split("</nav>", 1)[0]
    assert 'href="/lists/"' not in nav and "Списки" not in nav
