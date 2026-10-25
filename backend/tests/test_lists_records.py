"""T-6108a: запись списка — создание, сохранение, одновременная правка (FR-504, FR-515, FR-517, FR-546, NFR-512).
Сценарии 1-3 спеки 006. Замки по SQL (решение 6 задач), отказы — литералы раздела 12 контракта (решение 25)."""
import importlib
from html.parser import HTMLParser

import pytest
from django.contrib.postgres.search import SearchQuery
from django.utils import timezone

from tests import support
from tests import support_lists as ls

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}
TYPED = "Введённое-значение-№7"


# --- помощники файла ------------------------------------------------------------------------------------

def _records():
    return importlib.import_module("apps.lists.services.records")


def _errors():
    return importlib.import_module("apps.lists.services.errors")


def _archive_service():
    return importlib.import_module("apps.lists.services.archive")


def _files_service():
    return importlib.import_module("apps.lists.services.files")


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list = []
        self._area = None

    def handle_starttag(self, tag, attrs):
        found = {name: (value or "") for name, value in attrs}
        found["_tag"] = tag
        found["_text"] = ""
        self.tags.append(found)
        if tag == "textarea":
            self._area = found

    def handle_endtag(self, tag):
        if tag == "textarea":
            self._area = None

    def handle_data(self, data):
        if self._area is not None:
            self._area["_text"] += data


def _find(body: str, tag: str | None = None, **attrs) -> list:
    """Атрибуты тегов разметки с заданными атрибутами (`data_code` -> `data-code`; без значения — `""`)."""
    parser = _Collect()
    parser.feed(body)
    want = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [found for found in parser.tags
            if (tag is None or found["_tag"] == tag) and all(found.get(k) == v for k, v in want.items())]


def _values(body: str, name: str) -> list[str]:
    """Значения элементов формы с именем `name`: `value` у `input`, содержимое у `textarea`."""
    out = []
    for found in _find(body, name=name):
        if found["_tag"] == "textarea":
            out.append(found["_text"].removeprefix("\r\n").removeprefix("\n"))
        elif found["_tag"] == "input":
            out.append(found.get("value", ""))
    return out


def _world():
    """Список со строкой и многострочным текстом."""
    lst = ls.make_list()
    f1 = ls.add_field(lst, "string", "Серийный номер")
    f2 = ls.add_field(lst, "text", "Заметка")
    return lst, f1, f2


def _readable_by(session, lst):
    """Тот же сотрудник читает ещё и `lst` (роль сотрудника получает набор «Читают»)."""
    ls.grant_list(lst, session.user.roles.get(), "read")


def _create(lst, data, actor):
    return _records().create(lst, data, actor)


def _save(lst, number, data, *, base_version, actor):
    return _records().save(lst, number, data, base_version=base_version, actor=actor)


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _changes(record, kind=None):
    rows = support.model("lists.Change").objects.filter(record=record)
    return rows.filter(kind=kind) if kind else rows


def _refused(call):
    """Вызов, который должен дать отказ службы `ListsError`; возвращает исключение."""
    with pytest.raises(_errors().ListsError) as caught:
        call()
    return caught.value


def _post_add(client, lst, data, hx=False):
    response = client.post(f"/lists/{lst.pk}/add/", data, headers=HX if hx else {})
    return response, response.content.decode()


def _post_edit(client, lst, number, data, *, base_version, hx=False):
    body = dict(data, base_version=base_version)
    response = client.post(f"/lists/{lst.pk}/{number}/edit/", body, headers=HX if hx else {})
    return response, response.content.decode()


def _first(sqls, predicate) -> int:
    for number, sql in enumerate(sqls):
        if predicate(sql):
            return number
    raise AssertionError("в перечне запросов нет нужного")


def _for_update_of(sqls, table: str):
    """Номер первого `SELECT … FROM "<table>" … FOR UPDATE` или `None`."""
    for number, sql in enumerate(sqls):
        text = sql.lstrip().upper()
        if text.startswith("SELECT") and "FOR UPDATE" in text and f'FROM "{table.upper()}"' in text.upper():
            return number
    return None


def _shared_lock_at(sqls, lst) -> int:
    locks = ls.list_locks(sqls)
    assert locks and locks[0] == ls.ListLock("shared", ls.list_no(lst.pk)), locks
    assert all(lock.kind == "shared" for lock in locks), "правка записи берёт только разделяемый замок списка"
    return _first(sqls, lambda sql: "pg_advisory_xact_lock_shared" in sql)


def _call_sqls(func, *args, **kwargs):
    box = {}
    with ls.capture_sql() as sqls:
        box["result"] = func(*args, **kwargs)
    return box["result"], sqls


# --- номер записи ---------------------------------------------------------------------------------------

def test_record_number_comes_from_next_number_under_for_update_of_list_row():
    """FR-504: номер новой записи — `next_number` списка, счётчик растёт; строка списка взята `FOR UPDATE`;
    адрес после создания через форму — по номеру."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    support.model("lists.List").objects.filter(pk=lst.pk).update(next_number=5)
    lst.refresh_from_db()

    record, sqls = _call_sqls(_create, lst, {"title": "Сервер", f1.code: "SN-1"}, editor.user)
    assert record.number == 5
    assert _fresh(lst).next_number == 6
    ls.assert_for_update(sqls, "lists_list")
    assert _fresh(record).version == 1

    response, _body = _post_add(editor.client, lst, {"title": "Принтер", f1.code: "SN-2"})
    assert response.status_code == 302 and response["Location"] == f"/lists/{lst.pk}/6/"
    assert _fresh(lst).next_number == 7
    assert support.model("lists.Record").objects.filter(list=lst).count() == 2


def test_record_number_is_not_reused_after_purge(django_capture_on_commit_callbacks):
    """FR-504: номер удалённой навсегда записи не выдаётся повторно, `next_number` не уменьшается."""
    lst, _f1, _f2 = _world()
    editor = ls.as_editor(lst)
    manager = ls.as_manager()
    records = [_create(lst, {"title": f"Запись {n}"}, editor.user) for n in (1, 2, 3)]
    assert [r.number for r in records] == [1, 2, 3]
    ls.archive(records[2])

    with django_capture_on_commit_callbacks(execute=True):
        _archive_service().purge(lst, 3, actor=manager.user)
    Record = support.model("lists.Record")
    assert not Record.objects.filter(list=lst, number=3).exists()
    assert _fresh(lst).next_number == 4

    fourth = _create(lst, {"title": "Запись 4"}, editor.user)
    assert fourth.number == 4
    assert sorted(Record.objects.filter(list=lst).values_list("number", flat=True)) == [1, 2, 4]


# --- название -------------------------------------------------------------------------------------------

def test_title_200_accepted_201_rejected_with_limit_text_and_input_kept():
    """FR-504, FR-515, FR-546: название в 200 знаков принимается, в 201 — отказ у поля «Название» «Предел: 200
    знаков», введённое остаётся в форме, записи нет."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    Record = support.model("lists.Record")
    ok, too_long = "а" * 200, "б" * 201

    response, _body = _post_add(editor.client, lst, {"title": ok, f1.code: "SN-1"})
    assert response.status_code == 302
    assert Record.objects.get(list=lst).title == ok

    error = _refused(lambda: _create(lst, {"title": too_long, f1.code: "SN-2"}, editor.user))
    assert isinstance(error, _errors().ValuesInvalid)
    assert error.errors["title"].code == "too_long"
    assert Record.objects.filter(list=lst).count() == 1

    response, body = _post_add(editor.client, lst, {"title": too_long, f1.code: "SN-2"})
    assert response.status_code == 200
    assert _find(body, data_error="title", data_code="too_long")
    assert "Предел: 200 знаков" in body
    assert _values(body, "title") == [too_long]
    assert _values(body, f1.code) == ["SN-2"]
    assert Record.objects.filter(list=lst).count() == 1
    assert _fresh(lst).next_number == 2


# --- замки при создании и сохранении ---------------------------------------------------------------------

def test_create_takes_shared_list_lock_before_for_update_of_list_row_and_reads_schema_after_lock():
    """FR-504: порядок — разделяемый замок списка, затем `FOR UPDATE` строки списка; схема (`lists_field`)
    читается уже под замком; `FOR UPDATE` записи при создании нет."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    fresh = _fresh(lst)

    _record, sqls = _call_sqls(_create, fresh, {"title": "Сервер", f1.code: "SN-1"}, editor.user)
    lock_at = _shared_lock_at(sqls, lst)
    list_at = _for_update_of(sqls, "lists_list")
    assert list_at is not None and lock_at < list_at
    schema_reads = [n for n, sql in enumerate(sqls) if sql.lstrip().upper().startswith("SELECT") and '"lists_field"' in sql]
    assert schema_reads and min(schema_reads) > lock_at
    assert _for_update_of(sqls, "lists_record") is None


def test_create_writes_created_history_event_and_fills_search_vector():
    """FR-504: создание пишет одно событие истории `created` с автором и заполняет вектор поиска (название и
    значения полей «строка» находят запись)."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    Record = support.model("lists.Record")

    record = _create(lst, {"title": "Ноутбук бухгалтерии", f1.code: "Лазурный корпус"}, editor.user)
    rows = list(_changes(record))
    assert [(row.kind, row.actor_id, row.via_import) for row in rows] == [("created", editor.user.pk, False)]
    stored = _fresh(record)
    assert stored.search is not None
    assert (stored.created_by_id, stored.updated_by_id) == (editor.user.pk, editor.user.pk)
    for word in ("бухгалтерия", "лазурный"):
        assert Record.objects.filter(pk=record.pk, search=SearchQuery(word, config="russian")).exists(), word
    assert not Record.objects.filter(pk=record.pk, search=SearchQuery("принтер", config="russian")).exists()


def test_save_takes_shared_list_lock_then_for_update_of_record_in_that_order():
    """FR-517: сохранение — разделяемый замок списка, затем `FOR UPDATE` записи; строку списка не блокирует;
    схему читает после замка."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "SN-1"}, editor.user)

    result, sqls = _call_sqls(_save, _fresh(lst), record.number, {"title": "Сервер", f1.code: "SN-2"},
                              base_version=1, actor=editor.user)
    assert result.changed is True
    lock_at = _shared_lock_at(sqls, lst)
    record_at = _for_update_of(sqls, "lists_record")
    assert record_at is not None and lock_at < record_at
    assert _for_update_of(sqls, "lists_list") is None
    schema_reads = [n for n, sql in enumerate(sqls) if sql.lstrip().upper().startswith("SELECT") and '"lists_field"' in sql]
    assert schema_reads and min(schema_reads) > lock_at


# --- одновременная правка ---------------------------------------------------------------------------------

def _stale_world():
    """Анна и Борис правят запись; Борис сохранил первым (версия 2, время правки — 10.03.2026 14:35 по Москве)."""
    lst, f1, f2 = _world()
    anna = ls.as_editor(lst, full_name="Анна Первая")
    boris = ls.as_editor(lst, full_name="Борис Редакторов")
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, anna.user)
    assert _save(lst, record.number, {"title": "Сервер", f1.code: "правка Бориса"}, base_version=1,
                 actor=boris.user).changed
    moment = ls.moscow(2026, 3, 10, 14, 35)
    support.model("lists.Record").objects.filter(pk=record.pk).update(updated_at=moment)
    return lst, f1, anna, boris, record, moment


def test_second_save_from_same_base_version_is_refused_with_who_and_moscow_time_as_200_form_with_input():
    """FR-517, FR-546, NFR-512: второе сохранение с той же базовой версии — отказ «Запись уже изменил <имя> в
    <время по Москве>», ответ 200 с формой и введённым."""
    lst, f1, anna, boris, record, moment = _stale_world()

    error = _refused(lambda: _save(lst, record.number, {"title": "Сервер", f1.code: TYPED}, base_version=1,
                                   actor=anna.user))
    assert isinstance(error, _errors().VersionConflict)
    assert error.code == "version_conflict"
    assert error.who.pk == boris.user.pk and error.when == moment

    response, body = _post_edit(anna.client, lst, record.number, {"title": "Сервер", f1.code: TYPED}, base_version=1)
    assert response.status_code == 200
    assert _find(body, role="alert", data_code="version_conflict")
    assert f"Запись уже изменил Борис Редакторов в {ls.moscow_text(moment)}" in body
    assert "10.03.2026 14:35" in body
    assert _find(body, "form", data_lists_record_form="")
    assert _values(body, f1.code) == [TYPED]


def test_refused_stale_save_does_not_overwrite_first_save():
    """FR-517, NFR-512: отклонённое сохранение не затирает правку Бориса: значения, версия, автор правки и
    история прежние."""
    lst, f1, anna, boris, record, _moment = _stale_world()
    before = _changes(record).count()

    response, _body = _post_edit(anna.client, lst, record.number, {"title": "Сервер Анны", f1.code: TYPED},
                                 base_version=1)
    assert response.status_code == 200
    stored = _fresh(record)
    assert (stored.title, stored.values[f1.code], stored.version, stored.updated_by_id) == (
        "Сервер", "правка Бориса", 2, boris.user.pk)
    assert _changes(record).count() == before == 2
    assert _changes(record, "changed").count() == 1


def test_retry_with_new_base_version_after_conflict_is_saved():
    """FR-517: форма после отказа несёт текущую версию в скрытом `base_version`; повторная отправка с ней
    проходит и даёт версию 3."""
    lst, f1, anna, _boris, record, _moment = _stale_world()
    data = {"title": "Сервер", f1.code: TYPED}

    response, body = _post_edit(anna.client, lst, record.number, data, base_version=1)
    assert response.status_code == 200
    hidden = _find(body, "input", name="base_version")
    assert len(hidden) == 1 and hidden[0]["value"] == "2"

    response, _body = _post_edit(anna.client, lst, record.number, data, base_version=int(hidden[0]["value"]))
    assert response.status_code == 302 and response["Location"] == f"/lists/{lst.pk}/{record.number}/"
    stored = _fresh(record)
    assert (stored.version, stored.values[f1.code], stored.updated_by_id) == (3, TYPED, anna.user.pk)


def test_save_of_record_archived_during_edit_gives_record_archived_and_keeps_input():
    """FR-517, FR-546, NFR-512: запись ушла в архив за время правки — отказ «Запись в архиве», введённое
    остаётся, запись не изменена."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, editor.user)
    opened = editor.client.get(f"/lists/{lst.pk}/{record.number}/edit/")
    assert opened.status_code == 200

    ls.archive(record)
    error = _refused(lambda: _save(lst, record.number, {"title": "Сервер", f1.code: TYPED}, base_version=1,
                                   actor=editor.user))
    assert isinstance(error, _errors().RecordArchived) and error.code == "record_archived"

    response, body = _post_edit(editor.client, lst, record.number, {"title": "Сервер", f1.code: TYPED}, base_version=1)
    assert response.status_code == 200
    assert _find(body, role="alert", data_code="record_archived")
    assert "Запись в архиве" in body
    assert TYPED in body
    stored = _fresh(record)
    assert (stored.values[f1.code], stored.version, stored.archived) == ("старое", 1, True)


def test_save_of_record_purged_during_edit_gives_200_form_with_record_deleted_not_404():
    """FR-517, FR-546, NFR-512: запись удалена навсегда за время правки — 200 с формой и «Запись удалена», а не
    404; введённое остаётся."""
    lst, f1, _f2 = _world()
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, editor.user)
    support.model("lists.Record").objects.filter(pk=record.pk).delete()
    assert _fresh(lst).next_number > record.number

    error = _refused(lambda: _save(lst, record.number, {"title": "Сервер", f1.code: TYPED}, base_version=1,
                                   actor=editor.user))
    assert isinstance(error, _errors().RecordGone) and error.code == "record_gone"

    response, body = _post_edit(editor.client, lst, record.number, {"title": "Сервер", f1.code: TYPED}, base_version=1)
    assert response.status_code == 200
    assert _find(body, role="alert", data_code="record_gone")
    assert "Запись удалена" in body
    assert _find(body, "form", data_lists_record_form="")
    assert _values(body, f1.code) == [TYPED]


# --- значения, ставшие недоступными, и скрытое поле ---------------------------------------------------------

def _choice_and_record_world():
    """Список с полями «значение» и «запись» (цель — читаемый список); запись создана с первым значением."""
    lst, f1, _f2 = _world()
    status = ls.add_field(lst, "choice", "Состояние", choices=("В работе", "Списано"))
    target_list = ls.make_list()
    target = ls.add_field(lst, "record", "Связанное", target=target_list)
    editor = ls.as_editor(lst)
    _readable_by(editor, target_list)
    owner = ls.make_record(target_list, "Стойка", created_by=editor.user)
    record = _create(lst, {"title": "Сервер", f1.code: "SN-1", status.code: [str(ls.choice_id(status, "В работе"))]},
                     editor.user)
    return lst, f1, status, target, editor, record, target_list, owner


def test_value_made_unavailable_during_edit_is_refused_at_its_field():
    """FR-517, FR-515: значение, выбранное в форме, но ставшее недоступным за время правки (значение в архиве
    значений, запись другого списка в архиве), — отказ у своего поля; сохранения нет."""
    lst, f1, status, target, editor, record, _target_list, owner = _choice_and_record_world()
    chosen = ls.choice_id(status, "Списано")
    support.model("lists.Choice").objects.filter(pk=chosen).update(archived=True)
    ls.archive(owner)
    data = {"title": "Сервер", f1.code: "SN-9", status.code: [str(chosen)], target.code: [str(owner.pk)]}

    error = _refused(lambda: _save(lst, record.number, data, base_version=1, actor=editor.user))
    assert isinstance(error, _errors().ValuesInvalid)
    assert {code: err.code for code, err in error.errors.items()} == {
        status.code: "value_unavailable", target.code: "value_unavailable"}

    response, body = _post_edit(editor.client, lst, record.number, data, base_version=1)
    assert response.status_code == 200
    assert _find(body, data_error=status.code, data_code="value_unavailable")
    assert _find(body, data_error=target.code, data_code="value_unavailable")
    assert "Это значение выбрать нельзя" in body
    assert _values(body, f1.code) == ["SN-9"]
    stored = _fresh(record)
    assert (stored.version, stored.values[f1.code]) == (1, "SN-1")


def test_field_hidden_during_edit_with_nonempty_value_is_refused_with_hidden_mark_and_shown_read_only():
    """FR-517, FR-515: поле скрыто за время правки, а форма прислала в нём непустое значение — отказ
    «Поле скрыто администратором, значение не сохранится» у поля, поле только для чтения, записи не изменены."""
    lst, f1, f2 = _world()
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое", f2.code: "заметка"}, editor.user)
    support.model("lists.Field").objects.filter(pk=f1.pk).update(hidden=True)
    data = {"title": "Сервер", f1.code: TYPED, f2.code: "новая заметка"}

    error = _refused(lambda: _save(lst, record.number, data, base_version=1, actor=editor.user))
    assert isinstance(error, _errors().ValuesInvalid)
    assert error.errors[f1.code].code == "field_hidden_meanwhile"

    response, body = _post_edit(editor.client, lst, record.number, data, base_version=1)
    assert response.status_code == 200
    assert _find(body, data_error=f1.code, data_code="field_hidden_meanwhile")
    assert "Поле скрыто администратором, значение не сохранится" in body
    assert _find(body, data_lists_field=f1.code, data_hidden_meanwhile="")
    # значение показывается текстом, без элемента с `name="<код>"` (ответ 15, CONTRACT-006, 11.4, 15.3)
    assert _find(body, name=f1.code) == []
    stored = _fresh(record)
    assert (stored.version, stored.values[f1.code], stored.values[f2.code]) == (1, "старое", "заметка")


def test_resubmit_without_hidden_field_after_refusal_is_saved():
    """FR-517: повторная отправка формы без скрытого поля проходит: изменения других полей сохранены, значение
    скрытого поля не тронуто."""
    lst, f1, f2 = _world()
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое", f2.code: "заметка"}, editor.user)
    support.model("lists.Field").objects.filter(pk=f1.pk).update(hidden=True)

    response, _body = _post_edit(editor.client, lst, record.number,
                                 {"title": "Сервер", f1.code: TYPED, f2.code: "новая заметка"}, base_version=1)
    assert response.status_code == 200 and _fresh(record).version == 1

    response, _body = _post_edit(editor.client, lst, record.number, {"title": "Сервер", f2.code: "новая заметка"},
                                 base_version=1)
    assert response.status_code == 302 and response["Location"] == f"/lists/{lst.pk}/{record.number}/"
    stored = _fresh(record)
    assert (stored.version, stored.values[f2.code], stored.values[f1.code]) == (2, "новая заметка", "старое")


# --- версия и история ----------------------------------------------------------------------------------------

def test_save_without_changes_creates_no_version_and_no_history_event():
    """FR-517: сохранение без изменений не меняет версию, автора и время правки и не пишет событие истории
    (служба — `changed=False`, форма — всё равно переход на карточку)."""
    lst, f1, f2 = _world()
    editor = ls.as_editor(lst)
    other = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "SN-1", f2.code: "строка 1\nстрока 2"}, editor.user)
    before = _fresh(record)
    events = _changes(record).count()
    data = {"title": "Сервер", f1.code: "SN-1", f2.code: "строка 1\nстрока 2"}

    result = _save(lst, record.number, data, base_version=1, actor=other.user)
    assert result.changed is False
    response, _body = _post_edit(other.client, lst, record.number, data, base_version=1)
    assert response.status_code == 302 and response["Location"] == f"/lists/{lst.pk}/{record.number}/"
    after = _fresh(record)
    assert (after.version, after.updated_by_id, after.updated_at) == (1, editor.user.pk, before.updated_at)
    assert after.values == before.values
    assert _changes(record).count() == events == 1


def test_save_with_changes_increments_version_and_sets_updated_by():
    """FR-517: сохранение с изменением поднимает версию на 1, ставит `updated_by` и время правки, автор записи
    прежний; в истории одно событие `changed` с названным полем, было и стало."""
    lst, f1, _f2 = _world()
    author = ls.as_editor(lst)
    other = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, author.user)
    started = timezone.now()

    result = _save(lst, record.number, {"title": "Сервер", f1.code: "новое"}, base_version=1, actor=other.user)
    assert result.changed is True and result.record.version == 2
    stored = _fresh(record)
    assert (stored.version, stored.updated_by_id, stored.created_by_id) == (2, other.user.pk, author.user.pk)
    assert started <= stored.updated_at <= timezone.now()
    assert stored.values[f1.code] == "новое"
    rows = list(_changes(record, "changed"))
    assert len(rows) == 1 and rows[0].actor_id == other.user.pk
    entry = [item for item in rows[0].changes if item["field"] == f1.code]
    assert len(entry) == 1 and (entry[0]["before"], entry[0]["after"]) == ("старое", "новое")


def test_adding_file_does_not_change_record_version(protected_root):
    """FR-517: добавление файла — отдельное действие, версию записи не меняет: форма, открытая до добавления,
    сохраняется с прежней базовой версией без конфликта."""
    lst, f1, _f2 = _world()
    attachments = ls.add_field(lst, "file", "Акты")
    editor = ls.as_editor(lst)
    other = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, editor.user)
    assert editor.client.get(f"/lists/{lst.pk}/{record.number}/edit/").status_code == 200

    _files_service().attach(lst, record.number, field_code=attachments.code, name="акт.pdf",
                            data=b"%PDF-1.4\n% test body\n", actor=other.user)
    stored = _fresh(record)
    assert (stored.version, stored.updated_by_id) == (1, editor.user.pk)
    assert _changes(record, "file_added").count() == 1

    response, _body = _post_edit(editor.client, lst, record.number, {"title": "Сервер", f1.code: "новое"},
                                 base_version=1)
    assert response.status_code == 302
    stored = _fresh(record)
    assert (stored.version, stored.values[f1.code]) == (2, "новое")


# --- чужие значения и скрытые обязательные -----------------------------------------------------------------

def test_save_with_foreign_field_choice_id_or_non_target_record_id_is_refused_at_field():
    """FR-515: значение списка значений другого поля и запись не из целевого списка — отказ у поля
    «Это значение выбрать нельзя»; запись не меняется."""
    lst, f1, status, target, editor, record, _target_list, _owner = _choice_and_record_world()
    other_field = ls.add_field(lst, "choice", "Площадка", choices=("Москва",))
    foreign_choice = ls.choice_id(other_field, "Москва")
    other_list = ls.make_list()
    _readable_by(editor, other_list)
    stranger = ls.make_record(other_list, "Чужая запись", created_by=editor.user)
    data = {"title": "Сервер", f1.code: "SN-1", status.code: [str(foreign_choice)], target.code: [str(stranger.pk)]}

    error = _refused(lambda: _save(lst, record.number, data, base_version=1, actor=editor.user))
    assert isinstance(error, _errors().ValuesInvalid)
    assert {code: err.code for code, err in error.errors.items()} == {
        status.code: "value_unavailable", target.code: "value_unavailable"}

    response, body = _post_edit(editor.client, lst, record.number, data, base_version=1)
    assert response.status_code == 200
    assert _find(body, data_error=status.code, data_code="value_unavailable")
    assert _find(body, data_error=target.code, data_code="value_unavailable")
    stored = _fresh(record)
    assert stored.version == 1 and stored.values.get(target.code) in (None, [])


def test_edit_of_record_with_empty_hidden_required_field_is_saved():
    """FR-515: скрытое обязательное поле на обязательность не проверяется — запись с пустым скрытым обязательным
    полем правится."""
    lst, f1, f2 = _world()
    hidden_required = ls.add_field(lst, "string", "Инвентарный номер", required=True, hidden=True)
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, editor.user)
    assert hidden_required.code not in _fresh(record).values

    response, _body = _post_edit(editor.client, lst, record.number, {"title": "Сервер", f1.code: "новое"},
                                 base_version=1)
    assert response.status_code == 302
    stored = _fresh(record)
    assert (stored.version, stored.values[f1.code]) == (2, "новое")
    assert hidden_required.code not in stored.values


# --- ответ на отказ -------------------------------------------------------------------------------------------

def test_refusal_returns_200_full_form_with_typed_values_and_fragment_for_htmx_request():
    """FR-515, NFR-512: отказ — всегда 200 с полной формой и введённым; обычный запрос — страница целиком, запрос
    HTMX — фрагмент без `<html>`; у «Названия» отказ «Обязательное поле»."""
    lst, f1, f2 = _world()
    editor = ls.as_editor(lst)
    record = _create(lst, {"title": "Сервер", f1.code: "старое"}, editor.user)
    data = {"title": "", f1.code: "введённый-номер", f2.code: "строка 1\nстрока 2"}

    for hx in (False, True):
        response, body = _post_edit(editor.client, lst, record.number, data, base_version=1, hx=hx)
        assert response.status_code == 200, hx
        assert ("<html" in body.lower()) is (not hx), hx
        assert _find(body, "form", data_lists_record_form="")
        assert _find(body, data_error="title", data_code="required")
        assert "Обязательное поле" in body
        assert _values(body, f1.code) == ["введённый-номер"]
        assert _values(body, f2.code) == ["строка 1\nстрока 2"]
        assert _find(body, "input", name="base_version")[0]["value"] == "1"
    assert _fresh(record).version == 1
