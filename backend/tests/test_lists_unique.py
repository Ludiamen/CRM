"""T-6107: уникальность значений полей (FR-508, FR-509, FR-515, FR-534, FR-546). Сценарии 2 (п. 3) и 14 спеки.

Уникальность держит таблица `UniqueValue` с ограничением базы (`list`, `field`, `norm_value`): `unique.sync` пишет
строки во вложенной точке сохранения, повтор даёт отказ у поля `unique_taken` со ссылкой на запись-владельца.
Гонка двух сохранений проверяется без потоков: предварительная проверка `unique.find_owners` подменяется так, что
повтора не находит (решения 28 и 45 задач), и отказ даёт ограничение базы. Код среза на уровне модуля не
импортируется: службы берутся внутри тестов (CONTRACT-006, шапка).
"""
from html.parser import HTMLParser

import pytest
from django.db import IntegrityError, transaction

from tests import support
from tests import support_lists as lists

pytestmark = pytest.mark.django_db

TAKEN = "Такое значение уже есть в списке"
NO_OWNERS = lambda *args, **kwargs: {}  # noqa: E731  (обход предварительной проверки, раздел 5.8)


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


# --- данные теста ---------------------------------------------------------------------------------------

def _svc(name: str):
    import importlib

    return importlib.import_module(f"apps.lists.services.{name}")


def _errors():
    return _svc("errors")


def _setup(*, hidden: bool = False, number_field: bool = False):
    """Список с уникальным строковым полем `f1` (и при `number_field` — уникальным числовым `f2`) и правящим."""
    session = lists.as_editor(lst := lists.make_list())
    fields = [lists.add_field(lst, "string", "Инвентарный номер", unique=True, hidden=hidden)]
    if number_field:
        fields.append(lists.add_field(lst, "number", "Количество", unique=True))
    return lst, session, fields


def _create(lst, user, title="Запись", **data):
    return _svc("records").create(lst, {"title": title, **data}, user)


def _refusal(exc: BaseException, code_of_field: str):
    """Отказ у поля: служба поднимает либо `ListsError` поля, либо `ValuesInvalid` с отказом в `errors`."""
    errors = getattr(exc, "errors", None)
    if errors:
        assert code_of_field in errors, f"нет отказа у поля {code_of_field}: {sorted(errors)}"
        return errors[code_of_field]
    return exc


def _expect_taken(call, owner, field_code="f1", *, direct=False):
    """Вызов отклонён отказом `unique_taken` у поля со ссылкой на `owner`; возвращает отказ.

    Ответ Opus О2 (CONTRACT-006, 5.4, 15.3): `records.create/save` поднимают `ValuesInvalid`, у поля в `errors` —
    `ListsError` с кодом `unique_taken`; прямой вызов `unique.sync` (`direct=True`) — голый `ListsError("unique_taken")`.
    """
    errors = _errors()
    with pytest.raises(errors.ListsError) as raised:
        call()
    if direct:
        assert not isinstance(raised.value, errors.ValuesInvalid), "unique.sync поднимает голый ListsError"
        refusal = raised.value
    else:
        assert isinstance(raised.value, errors.ValuesInvalid), f"ждали ValuesInvalid, получено {raised.value!r}"
        assert field_code in raised.value.errors, f"нет отказа у поля {field_code}: {sorted(raised.value.errors)}"
        refusal = raised.value.errors[field_code]
    assert refusal.code == "unique_taken"
    assert refusal.field == field_code
    assert refusal.params["number"] == owner.number
    assert refusal.params["url"] == f"/lists/{owner.list_id}/{owner.number}/"
    return refusal


def _rows(lst, field=None):
    query = support.model("lists.UniqueValue").objects.filter(list=lst)
    if field is not None:
        query = query.filter(field=field)
    return sorted((row.field.code, row.norm_value, row.record.number) for row in query.select_related("field", "record"))


def _records(lst) -> int:
    return support.model("lists.Record").objects.filter(list=lst).count()


def _assert_refusal_markup(response, lst, owner, field_code="f1"):
    assert response.status_code == 200
    root = tree(response)
    nodes = q(root, data_error=field_code, data_code="unique_taken")
    assert nodes, "нет [data-error=…][data-code=unique_taken] рядом с полем"
    around = nodes[0].parent
    assert TAKEN in around.text()
    links = q(around, "a", href=f"/lists/{lst.pk}/{owner.number}/")
    assert links, "рядом с отказом нет ссылки на запись-владельца"


# --- тесты ----------------------------------------------------------------------------------------------

def test_padded_lowercase_duplicate_of_uppercase_value_is_refused_at_field_with_text_and_link_to_owner_record():
    """FR-508, FR-515, FR-546: «ИН-100» уже есть; ввод « ин-100 » в новой записи — отказ у поля с текстом
    «Такое значение уже есть в списке» и ссылкой на запись-владельца; запись не создана, строка значения одна."""
    lst, session, (field,) = _setup()
    owner = lists.make_record(lst, "Ноутбук", {"f1": "ИН-100"}, created_by=session.user)

    response = session.client.post(f"/lists/{lst.pk}/add/", {"title": "Новый", "f1": " ин-100 "})

    _assert_refusal_markup(response, lst, owner)
    assert _records(lst) == 1
    assert _rows(lst) == [("f1", "ин-100", owner.number)]
    _expect_taken(lambda: _create(lst, session.user, f1=" ин-100 "), owner)
    assert _records(lst) == 1


def test_number_100_0_and_100_are_the_same_unique_value():
    """FR-508: у числового поля «100.0», «100» и «100.00» — одно значение: строка `UniqueValue` с `100`, повтор
    отклонён; пустое значение нормализуется в `None`."""
    lst, session, (_, number_field) = _setup(number_field=True)
    unique = _svc("unique")
    assert unique.normalize(number_field, "100") == "100"
    assert unique.normalize(number_field, "") is None
    assert unique.normalize(number_field, None) is None

    first = _create(lst, session.user, "Первая", f2="100.0")

    assert _rows(lst, number_field) == [("f2", "100", first.number)]
    _expect_taken(lambda: _create(lst, session.user, "Вторая", f2="100"), first, "f2")
    _expect_taken(lambda: _create(lst, session.user, "Третья", f2="100.00"), first, "f2")
    assert _records(lst) == 1
    other = _create(lst, session.user, "Другая", f2="100.5")
    assert _rows(lst, number_field) == [("f2", "100", first.number), ("f2", "100.5", other.number)]


def test_value_of_archived_record_still_blocks_duplicate():
    """FR-508, FR-515: значение записи в архиве занято; отказ у поля со ссылкой на архивную запись, строка осталась."""
    lst, session, (field,) = _setup()
    owner = lists.make_record(lst, "Старый ноутбук", {"f1": "ИН-200"}, archived=True, created_by=session.user)

    response = session.client.post(f"/lists/{lst.pk}/add/", {"title": "Новый", "f1": "ин-200"})

    _assert_refusal_markup(response, lst, owner)
    _expect_taken(lambda: _create(lst, session.user, f1="ИН-200"), owner)
    assert _records(lst) == 1
    assert _rows(lst) == [("f1", "ин-200", owner.number)]


def test_hidden_unique_field_still_blocks_duplicate():
    """FR-508: у скрытого уникального поля строки `UniqueValue` есть, повтор отклоняется (место A1 контракта:
    `unique.sync` берёт все поля, в том числе скрытые)."""
    lst, session, (field,) = _setup(hidden=True)
    owner = lists.make_record(lst, "Владелец", {"f1": "ИН-300"}, created_by=session.user)
    assert _rows(lst, field) == [("f1", "ин-300", owner.number)]
    other = lists.make_record(lst, "Другая", {}, created_by=session.user)
    other.values = {"f1": " ин-300"}
    other.save(update_fields=["values"])

    _expect_taken(lambda: _svc("unique").sync(other, [field]), owner, direct=True)

    assert _rows(lst, field) == [("f1", "ин-300", owner.number)]


def test_empty_value_creates_no_unique_row_and_two_empty_values_coexist():
    """FR-508: пустое значение уникальности не нарушает: две записи без значения создаются, строк `UniqueValue`
    нет; следующее непустое значение получает свою строку."""
    lst, session, (text_field, number_field) = _setup(number_field=True)

    first = _create(lst, session.user, "Первая", f1="", f2="")
    second = _create(lst, session.user, "Вторая")

    assert {first.number, second.number} == {1, 2}
    assert _records(lst) == 2
    assert _rows(lst) == []
    third = _create(lst, session.user, "Третья", f1="а-1", f2="5")
    assert _rows(lst) == [("f1", "а-1", third.number), ("f2", "5", third.number)]


def test_same_value_in_other_field_or_other_list_is_allowed():
    """FR-508: уникальность действует в паре «список, поле»: то же значение в другом уникальном поле того же списка
    и в таком же поле другого списка допустимо."""
    lst, session, (first_field,) = _setup()
    second_field = lists.add_field(lst, "string", "Серийный номер", unique=True)
    other_lst, other_session, (other_field,) = _setup()

    a = _create(lst, session.user, "А", f1="Х-1")
    b = _create(lst, session.user, "Б", **{second_field.code: "х-1"})
    c = _create(other_lst, other_session.user, "В", f1="х-1")

    assert _rows(lst) == sorted([("f1", "х-1", a.number), (second_field.code, "х-1", b.number)])
    assert _rows(other_lst) == [("f1", "х-1", c.number)]
    _expect_taken(lambda: _create(lst, session.user, "Г", **{second_field.code: " Х-1 "}), b, second_field.code)


def test_saving_record_with_its_own_unique_value_is_not_a_conflict():
    """FR-508, FR-515: запись сохраняется со своим же значением (в другом написании) без отказа: строка одна, её
    запись — та же; правка из формы проходит тем же путём."""
    lst, session, (field,) = _setup()
    record = lists.make_record(lst, "Ноутбук", {"f1": "ИН-100"}, created_by=session.user)

    result = _svc("records").save(
        lst, record.number, {"title": "Ноутбук Lenovo", "f1": " ин-100 "}, base_version=record.version,
        actor=session.user)

    assert result.changed is True
    assert _rows(lst) == [("f1", "ин-100", record.number)]
    record.refresh_from_db()
    response = session.client.post(
        f"/lists/{lst.pk}/{record.number}/edit/", {"title": "Ещё раз", "f1": "ИН-100", "base_version": record.version})
    assert response.status_code == 302
    assert _rows(lst) == [("f1", "ин-100", record.number)]
    record.refresh_from_db()
    assert record.title == "Ещё раз"


def test_changing_value_frees_previous_value_for_other_record():
    """FR-508: после смены значения прежнее свободно для другой записи, новое занято."""
    lst, session, (field,) = _setup()
    a = _create(lst, session.user, "А", f1="а-1")

    _svc("records").save(lst, a.number, {"title": "А", "f1": "б-2"}, base_version=a.version, actor=session.user)

    assert _rows(lst) == [("f1", "б-2", a.number)]
    b = _create(lst, session.user, "Б", f1="А-1")
    _expect_taken(lambda: _create(lst, session.user, "В", f1="б-2"), a)
    assert _rows(lst) == [("f1", "а-1", b.number), ("f1", "б-2", a.number)]


def test_race_with_bypassed_precheck_hits_db_constraint_in_savepoint_and_gives_field_refusal(monkeypatch):
    """FR-508, FR-515, FR-546: предварительная проверка не нашла повтора (подмена `unique.find_owners`); вставку
    останавливает ограничение базы, служба превращает его в отказ у поля со ссылкой на владельца, а страница
    показывает отказ; сама база дубль не примет."""
    lst, session, (field,) = _setup()
    owner = lists.make_record(lst, "Владелец", {"f1": "ИН-400"}, created_by=session.user)
    monkeypatch.setattr("apps.lists.services.unique.find_owners", NO_OWNERS)

    _expect_taken(lambda: _create(lst, session.user, "Гонка", f1="ин-400"), owner)
    response = session.client.post(f"/lists/{lst.pk}/add/", {"title": "Гонка 2", "f1": "ИН-400 "})

    _assert_refusal_markup(response, lst, owner)
    assert _records(lst) == 1
    UniqueValue = support.model("lists.UniqueValue")
    with pytest.raises(IntegrityError), transaction.atomic():
        UniqueValue.objects.create(list=lst, field=field, norm_value="ин-400", record=owner)
    assert _rows(lst) == [("f1", "ин-400", owner.number)]


def test_race_refusal_leaves_no_duplicate_row_and_outer_save_transaction_usable(monkeypatch):
    """FR-508: после отказа ограничения нет второй строки значения, запись не изменена, а внешняя транзакция
    остаётся рабочей: дальше в ней идут запросы и записи (вложенная точка сохранения откатилась одна)."""
    lst, session, (field,) = _setup()
    owner = lists.make_record(lst, "Владелец", {"f1": "ИН-500"}, created_by=session.user)
    mine = lists.make_record(lst, "Моя", {"f1": "ИН-501"}, created_by=session.user)
    monkeypatch.setattr("apps.lists.services.unique.find_owners", NO_OWNERS)
    Record = support.model("lists.Record")

    _expect_taken(
        lambda: _svc("records").save(
            lst, mine.number, {"title": "Моя", "f1": "ин-500"}, base_version=mine.version, actor=session.user),
        owner)

    mine.refresh_from_db()
    assert mine.values == {"f1": "ИН-501"}
    assert mine.version == 1
    assert _rows(lst) == [("f1", "ин-500", owner.number), ("f1", "ин-501", mine.number)]
    Record.objects.filter(pk=mine.pk).update(title="Моя 2")
    assert Record.objects.get(pk=mine.pk).title == "Моя 2"

    third = lists.make_record(lst, "Третья", {}, created_by=session.user)
    third.values = {"f1": "ИН-500"}
    third.save(update_fields=["values"])
    with transaction.atomic():
        refusal = _expect_taken(lambda: _svc("unique").sync(third, [field]), owner, direct=True)
        assert refusal.message.startswith(TAKEN)
        Record.objects.filter(pk=third.pk).update(title="Третья 2")
        assert Record.objects.get(pk=third.pk).title == "Третья 2"
        assert _create(lst, session.user, "Четвёртая", f1="ИН-502").title == "Четвёртая"
    assert [row for row in _rows(lst) if row[1] == "ин-500"] == [("f1", "ин-500", owner.number)]


def test_enable_unique_and_duplicate_save_in_both_orders_leave_no_duplicate_and_one_side_refused():
    """FR-509, FR-515: включение «Уникального» и сохранение повтора в обеих очерёдностях: если включили первым —
    повтор отклонён при сохранении; если сохранили повтор первым — отклонено включение (`unique_repeats` у «unique»
    с номерами записей); дубля в `UniqueValue` нет, отказывает ровно одна сторона."""
    manager = lists.as_manager().user
    editor_session = lists.as_editor(lst := lists.make_list())
    user = editor_session.user
    schema = _svc("schema")
    ListsError = _errors().ListsError

    # очерёдность 1: «Уникальное» включено до повтора
    field = lists.add_field(lst, "string", "Инвентарный номер")
    a = lists.make_record(lst, "А", {field.code: "х-1"}, created_by=user)
    schema.update_field(field, actor=manager, unique=True)
    _expect_taken(lambda: _create(lst, user, "Б", **{field.code: " Х-1"}), a, field.code)
    assert _records(lst) == 1
    assert _rows(lst) == [(field.code, "х-1", a.number)]

    # очерёдность 2: повтор сохранён до включения
    other = lists.make_list()
    # служба перепроверяет право «правит» (решение Opus 2026-10-25, П3): правящему `lst` выдаётся «правит» и на `other`;
    # объект сотрудника берётся заново — `access.scope` хранится на объекте (`user._lists_scope`, 5.5)
    lists.grant_list(other, user.roles.get(), "edit")
    user = type(user).objects.get(pk=user.pk)
    second = lists.add_field(other, "string", "Инвентарный номер")
    c = lists.make_record(other, "В", {second.code: "у-1"}, created_by=user)
    d = _svc("records").create(other, {"title": "Г", second.code: "У-1"}, user)
    with pytest.raises(ListsError) as raised:
        schema.update_field(second, actor=manager, unique=True)
    refusal = _refusal(raised.value, "unique")
    assert refusal.code == "unique_repeats"
    assert refusal.field == "unique"
    assert f"№{c.number}" in refusal.message and f"№{d.number}" in refusal.message
    second.refresh_from_db()
    assert second.unique is False
    assert _records(other) == 2
    assert _rows(other) == []


def test_archive_and_restore_keep_unique_rows_and_restore_has_no_conflict():
    """FR-508: «В архив» и «Вернуть» строк значений не трогают: значение занято и в архиве, возврат проходит без
    конфликта, строка остаётся одна."""
    lst, session, (field,) = _setup()
    user = session.user
    record = lists.make_record(lst, "Ноутбук", {"f1": "ИН-600"}, created_by=user)
    archive = _svc("archive")

    archive.archive(lst, record.number, actor=user)

    record.refresh_from_db()
    assert record.archived is True
    assert _rows(lst) == [("f1", "ин-600", record.number)]
    _expect_taken(lambda: _create(lst, user, "Двойник", f1="ин-600"), record)

    archive.restore(lst, record.number, actor=user)

    record.refresh_from_db()
    assert record.archived is False
    assert _rows(lst) == [("f1", "ин-600", record.number)]
    _expect_taken(lambda: _create(lst, user, "Двойник 2", f1="ИН-600"), record)
    assert _records(lst) == 1


def test_purge_deletes_unique_rows_by_cascade_and_frees_value(django_capture_on_commit_callbacks):
    """FR-508: «Удалить навсегда» стирает строки значений записи каскадом (строки других записей целы) и
    освобождает значение для новой записи."""
    lst, session, (field,) = _setup()
    user = session.user
    gone = lists.make_record(lst, "Списанный", {"f1": "ИН-700"}, archived=True, created_by=user)
    kept = lists.make_record(lst, "Рабочий", {"f1": "ИН-701"}, created_by=user)
    assert len(_rows(lst)) == 2

    with django_capture_on_commit_callbacks(execute=True):
        _svc("archive").purge(lst, gone.number, actor=user)

    assert not support.model("lists.Record").objects.filter(pk=gone.pk).exists()
    assert _rows(lst) == [("f1", "ин-701", kept.number)]
    fresh = _create(lst, user, "Новый", f1="ин-700")
    assert _rows(lst) == [("f1", "ин-700", fresh.number), ("f1", "ин-701", kept.number)]


def test_every_value_write_path_calls_unique_sync(django_capture_on_commit_callbacks):
    """FR-508, FR-534: все пути записи значений ведут `UniqueValue`: создание и сохранение службой записи,
    создание и обновление загрузкой — строки значений совпадают со значениями записей (подмены `sync` нет, смотрим
    следствие в базе)."""
    lst, session, (field,) = _setup()
    serial = lists.add_field(lst, "string", "Серийный номер", unique=True)
    user = session.user
    records = _svc("records")
    imports = _svc("imports")

    # создание и сохранение
    a = records.create(lst, {"title": "А", "f1": " Ab-1 "}, user)
    assert _rows(lst) == [("f1", "ab-1", a.number)]
    records.save(lst, a.number, {"title": "А", "f1": "cd-2", serial.code: "S-1"}, base_version=a.version, actor=user)
    assert _rows(lst) == [("f1", "cd-2", a.number), (serial.code, "s-1", a.number)]

    # загрузка: создание новой записи
    header = ["Название", "Инвентарный номер", "Серийный номер"]
    job = imports.upload(lst, user, name="новые.csv", content=lists.csv_of(header, [["Б", "Ef-3", "S-2"]]))
    imports.preview(job, {"0": "title", "1": "f1", "2": serial.code}, user)
    with django_capture_on_commit_callbacks(execute=True):
        summary = imports.confirm(lst, job.pk, user)
    assert (summary["created"], summary["updated"], summary["errors"]) == (1, 0, 0)
    b = support.model("lists.Record").objects.get(list=lst, title="Б")
    assert _rows(lst) == [("f1", "cd-2", a.number), ("f1", "ef-3", b.number), (serial.code, "s-1", a.number),
                          (serial.code, "s-2", b.number)]

    # загрузка: обновление записи по уникальному полю меняет значение другого уникального поля
    job = imports.upload(lst, user, name="правка.csv",
                         content=lists.csv_of(["Инвентарный номер", "Серийный номер"], [["CD-2", "S-9"]]))
    imports.preview(job, {"0": "f1", "1": serial.code}, user)
    with django_capture_on_commit_callbacks(execute=True):
        summary = imports.confirm(lst, job.pk, user)
    assert (summary["created"], summary["updated"], summary["errors"]) == (0, 1, 0)
    assert _rows(lst) == [("f1", "cd-2", a.number), ("f1", "ef-3", b.number), (serial.code, "s-2", b.number),
                          (serial.code, "s-9", a.number)]


def test_enabling_unique_creates_rows_for_existing_values_and_disabling_deletes_them():
    """FR-508: включение «Уникального» создаёт строки по значениям существующих записей (в том числе в архиве, пустые
    значения строк не дают), выключение удаляет строки только этого поля."""
    manager = lists.as_manager().user
    lst = lists.make_list()
    user = lists.as_editor(lst).user
    text_field = lists.add_field(lst, "string", "Инвентарный номер")
    number_field = lists.add_field(lst, "number", "Количество", unique=True)
    a = lists.make_record(lst, "А", {text_field.code: "Х-1", number_field.code: "100"}, created_by=user)
    b = lists.make_record(lst, "Б", {text_field.code: " у-2 ", number_field.code: "100.5"}, archived=True,
                          created_by=user)
    lists.make_record(lst, "В", {}, created_by=user)
    schema = _svc("schema")
    assert _rows(lst, text_field) == []

    schema.update_field(text_field, actor=manager, unique=True)

    assert _rows(lst, text_field) == [(text_field.code, "у-2", b.number), (text_field.code, "х-1", a.number)]
    assert len(_rows(lst, number_field)) == 2

    text_field.refresh_from_db()
    schema.update_field(text_field, actor=manager, unique=False)

    assert _rows(lst, text_field) == []
    assert _rows(lst, number_field) == [(number_field.code, "100", a.number), (number_field.code, "100.5", b.number)]


def test_precheck_reports_owner_record_including_archived_for_import_preview():
    """FR-534: `unique.find_owners` отдаёт запись-владельца по нормализованному значению, в том числе запись в архиве,
    и не знает чужих списков; предпросмотр загрузки по ней различает «будет обновлена» (запись не в архиве) и ошибку
    (запись в архиве), ничего не меняя в базе."""
    lst, session, (field,) = _setup()
    user = session.user
    active = lists.make_record(lst, "Рабочий", {"f1": "А-1"}, created_by=user)
    archived = lists.make_record(lst, "Старый", {"f1": "Б-1"}, archived=True, created_by=user)
    other_lst, other_session, _ = _setup()
    lists.make_record(other_lst, "Чужой", {"f1": "В-1"}, created_by=other_session.user)
    unique = _svc("unique")

    owners = unique.find_owners(lst, field, ["а-1", "б-1", "в-1", "г-1"])

    assert set(owners) == {"а-1", "б-1"}
    assert owners["а-1"].pk == active.pk and owners["а-1"].archived is False
    assert owners["б-1"].pk == archived.pk and owners["б-1"].archived is True
    assert unique.find_owners(lst, field, []) == {}

    imports = _svc("imports")
    content = lists.csv_of(["Название", "Инвентарный номер"], [["Новое имя", "а-1"], ["Старое имя", "Б-1"]])
    job = imports.upload(lst, user, name="проверка.csv", content=content)
    job = imports.preview(job, {"0": "title", "1": "f1"}, user)
    job.refresh_from_db()
    results = {row["row"]: row for row in job.rows}
    assert results[2]["result"] == "will_update" and results[2]["number"] == active.number
    assert results[3]["result"] == "error" and results[3]["reason"]
    assert imports.counts(job) == {"will_create": 0, "will_update": 1, "error": 1}
    assert _records(lst) == 2
    active.refresh_from_db()
    assert active.title == "Рабочий" and active.version == 1
