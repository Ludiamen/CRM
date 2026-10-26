"""T-6106: значения по типам и форма записи (FR-507, FR-508, FR-515, FR-546). Сценарии 2 и 3 спеки среза 006.

Разбор ввода `values.parse` по двенадцати типам (пределы, разделитель числа, деньги, дата, дата и время по Москве,
да/нет, выбор значений и правило «старое остаётся»), хранение массивов без повторов, код поля `f<номер>`, форма новой
записи (`/lists/<id>/add/`): поля по порядку, обязательные, умолчания, скрытые поля, отказы у полей с введённым, и
показ значений `values.display`. Код среза на уровне модуля не импортируется: имена берутся внутри тестов
(CONTRACT-006, шапка). Тексты — литералы раздела 12. Гонок здесь нет. Время — фикстурой `clock`.
"""
import re
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests import support_lists as sl
from tests import support_org
from tests.support import model

pytestmark = pytest.mark.django_db

REQUIRED = "Обязательное поле"
LIMIT_500 = "Предел: 500 знаков"
LIMIT_10000 = "Предел: 10 000 знаков"
LINE_BREAK = "Без переносов строк"
BAD_NUMBER = "Введите число"
NUMBER_DIGITS = "Не больше 15 значащих цифр, до и после запятой — не больше 15"
MONEY_DIGITS = "Не больше 13 цифр до запятой и двух после"
BAD_DATE = "Введите дату ДД.ММ.ГГГГ"
BAD_DATETIME = "Введите дату и время ДД.ММ.ГГГГ ЧЧ:ММ"
UNAVAILABLE = "Это значение выбрать нельзя"


# --- помощники только этого файла -------------------------------------------------------------------------

def _viewer():
    return support.make_employee()


def _parse(field, raw, *, old=None, viewer=None):
    from apps.lists.services import values

    return values.parse(field, raw, old=old, viewer=viewer or _viewer())


def _display(field, value, viewer=None):
    from apps.lists.services import values

    return values.display(field, value, viewer or _viewer())


def _accepts(field, raw, expected, *, old=None, viewer=None):
    parsed = _parse(field, raw, old=old, viewer=viewer)
    assert parsed.error is None, f"{field.type} {raw!r}: отказ {parsed.error.code}"
    assert parsed.value == expected, f"{field.type} {raw!r}: {parsed.value!r}, ожидалось {expected!r}"


def _rejects(field, raw, code, text, *, old=None, viewer=None):
    parsed = _parse(field, raw, old=old, viewer=viewer)
    assert parsed.error is not None, f"{field.type} {raw!r}: принято как {parsed.value!r}"
    assert parsed.error.code == code, f"{field.type} {raw!r}: код {parsed.error.code}, ожидался {code}"
    assert text in parsed.error.message, f"{field.type} {raw!r}: текст «{parsed.error.message}»"


def _ids(items) -> list[str]:
    return [str(item.pk) for item in items]


def _records(lst) -> list:
    return list(model("lists.Record").objects.filter(list=lst).order_by("number"))


def _add_url(lst) -> str:
    return f"/lists/{lst.pk}/add/"


def _post_add(session, lst, data):
    return session.client.post(_add_url(lst), data)


# --- разбор разметки (помощник только этого файла) ---------------------------------------------------------

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
    result = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            result.append(node)
    return result


def _form_of(response) -> Node:
    forms = _find(_tree(response), "form", data_lists_record_form=True)
    assert forms, f"нет form[data-lists-record-form] в ответе {response.status_code}"
    return forms[0]


def _containers(form) -> list:
    return _find(form, data_lists_field=True)


def _container(form, code: str) -> Node:
    found = _find(form, data_lists_field=code)
    assert found, f"нет [data-lists-field={code}] в форме"
    return found[0]


def _control(form, code: str, tag=None) -> Node:
    found = _find(_container(form, code), tag, name=code)
    assert found, f"нет [name={code}] внутри [data-lists-field={code}]"
    return found[0]


def _field_error(response, field: str, code: str, text: str) -> None:
    """Отказ у поля: `[data-error="<поле>"][data-code="<код>"]` с текстом раздела 12 (CONTRACT-006, 10.1)."""
    nodes = _find(_tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error={field}][data-code={code}] в ответе {response.status_code}"
    assert any(text in node.text() for node in nodes), f"нет текста «{text}» у отказа {code}"


def _moscow_to_utc(year, month, day, hour, minute) -> str:
    moment = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Europe/Moscow"))
    return moment.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:00Z")


# --- 1. строка и многострочный текст -----------------------------------------------------------------------

def test_string_probes_500_accepted_501_and_line_break_rejected_with_limit_text():
    """FR-507, FR-546: строка — 500 знаков принимаются, 501 — «Предел: 500 знаков» (`too_long`), перенос — `line_break`; и форма."""
    lst = sl.make_list()
    field = sl.add_field(lst, "string", "Модель")
    _accepts(field, "я" * 500, "я" * 500)
    _rejects(field, "я" * 501, "too_long", LIMIT_500)
    _rejects(field, "первая\nвторая", "line_break", LINE_BREAK)
    _rejects(field, "первая\rвторая", "line_break", LINE_BREAK)
    editor = sl.as_editor(lst)
    response = _post_add(editor, lst, {"title": "Одна", field.code: "первая\nвторая"})
    assert response.status_code == 200
    _field_error(response, field.code, "line_break", LINE_BREAK)
    response = _post_add(editor, lst, {"title": "Две", field.code: "я" * 501})
    _field_error(response, field.code, "too_long", LIMIT_500)
    assert _records(lst) == []
    response = _post_add(editor, lst, {"title": "Три", field.code: "я" * 500})
    assert response.status_code == 302
    assert _records(lst)[0].values[field.code] == "я" * 500


def test_text_probes_10000_accepted_10001_rejected_and_markup_kept_as_plain_text():
    """FR-507, FR-546: текст — 10 000 знаков принимаются, 10 001 — «Предел: 10 000 знаков»; переносы — `\\n`, разметка остаётся текстом."""
    lst = sl.make_list()
    field = sl.add_field(lst, "text", "Описание")
    _accepts(field, "я" * 10000, "я" * 10000)
    _rejects(field, "я" * 10001, "too_long", LIMIT_10000)
    _accepts(field, "первая\nвторая", "первая\nвторая")
    _accepts(field, "первая\r\nвторая\rтретья", "первая\nвторая\nтретья")
    markup = "<b>жирный</b>\n<script>alert(1)</script>"
    _accepts(field, markup, markup)
    reader = sl.as_reader(lst)
    record = sl.make_record(lst, "С разметкой", {field.code: markup})
    html = reader.client.get(f"/lists/{lst.pk}/{record.number}/").content.decode("utf-8")
    assert "&lt;b&gt;жирный&lt;/b&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>жирный</b>" not in html
    assert "<script>alert(1)</script>" not in html


# --- 2. число и деньги -------------------------------------------------------------------------------------

def test_number_comma_and_dot_both_give_canonical_12_5_and_letters_rejected():
    """FR-507: число — «12,5» и «12.5» дают «12.5», «100.0» — «100»; буквы — `bad_number` «Введите число»."""
    lst = sl.make_list()
    field = sl.add_field(lst, "number", "Количество")
    _accepts(field, "12,5", "12.5")
    _accepts(field, "12.5", "12.5")
    _accepts(field, "12.50", "12.5")
    _accepts(field, "100.0", "100")
    _accepts(field, "-3", "-3")
    _rejects(field, "12abc", "bad_number", BAD_NUMBER)
    _rejects(field, "abc", "bad_number", BAD_NUMBER)
    editor = sl.as_editor(lst)
    response = _post_add(editor, lst, {"title": "Запятая", field.code: "12,5"})
    assert response.status_code == 302
    assert _records(lst)[0].values[field.code] == "12.5"
    response = _post_add(editor, lst, {"title": "Буквы", field.code: "12abc"})
    assert response.status_code == 200
    _field_error(response, field.code, "bad_number", BAD_NUMBER)
    assert len(_records(lst)) == 1


def test_number_15_significant_digits_accepted_16_significant_16_integer_or_16_fraction_digits_rejected():
    """FR-507: число — 15 значащих цифр принимаются; 16 значащих, 16 целых или 16 дробных — `number_digits`."""
    lst = sl.make_list()
    field = sl.add_field(lst, "number", "Показание")
    _accepts(field, "123456789012345", "123456789012345")
    _accepts(field, "1234567890.12345", "1234567890.12345")
    _accepts(field, "0.123456789012345", "0.123456789012345")
    _rejects(field, "1234567890.123456", "number_digits", NUMBER_DIGITS)
    _rejects(field, "1234567890123456", "number_digits", NUMBER_DIGITS)
    _rejects(field, "0.0000000000000001", "number_digits", NUMBER_DIGITS)


def test_money_1234_5_and_1234_stored_as_1234_50_and_1234_00_with_comma_or_dot():
    """FR-507: деньги — «1234,5» и «1234.5» хранятся «1234.50», «1234» — «1234.00»; буквы — `bad_number`."""
    lst = sl.make_list()
    field = sl.add_field(lst, "money", "Стоимость")
    _accepts(field, "1234,5", "1234.50")
    _accepts(field, "1234.5", "1234.50")
    _accepts(field, "1234", "1234.00")
    _accepts(field, "1234,50", "1234.50")
    _rejects(field, "дорого", "bad_number", BAD_NUMBER)
    editor = sl.as_editor(lst)
    assert _post_add(editor, lst, {"title": "Запятая", field.code: "1234,5"}).status_code == 302
    assert _post_add(editor, lst, {"title": "Целое", field.code: "1234"}).status_code == 302
    assert [record.values[field.code] for record in _records(lst)] == ["1234.50", "1234.00"]


def test_money_three_decimals_and_14_integer_digits_rejected_13_integer_digits_accepted():
    """FR-507: деньги — три знака после запятой и 14 цифр до неё — `money_digits`; 13 цифр до запятой принимаются."""
    lst = sl.make_list()
    field = sl.add_field(lst, "money", "Сумма")
    _rejects(field, "1.234", "money_digits", MONEY_DIGITS)
    _rejects(field, "1,234", "money_digits", MONEY_DIGITS)
    _rejects(field, "12345678901234", "money_digits", MONEY_DIGITS)
    _rejects(field, "12345678901234,50", "money_digits", MONEY_DIGITS)
    _accepts(field, "1234567890123,45", "1234567890123.45")
    _accepts(field, "1234567890123", "1234567890123.00")


# --- 3. дата, дата и время, да/нет -------------------------------------------------------------------------

def test_date_ddmmyyyy_and_iso_give_2026_03_14_and_31_02_2026_rejected():
    """FR-507: дата — «14.03.2026» и «2026-03-14» дают «2026-03-14»; «31.02.2026» — `bad_date` «Введите дату ДД.ММ.ГГГГ»."""
    lst = sl.make_list()
    field = sl.add_field(lst, "date", "Куплено")
    _accepts(field, "14.03.2026", "2026-03-14")
    _accepts(field, "2026-03-14", "2026-03-14")
    _rejects(field, "31.02.2026", "bad_date", BAD_DATE)
    _rejects(field, "14/03/2026", "bad_date", BAD_DATE)
    _rejects(field, "вчера", "bad_date", BAD_DATE)
    editor = sl.as_editor(lst)
    assert _post_add(editor, lst, {"title": "Точка", field.code: "14.03.2026"}).status_code == 302
    assert _records(lst)[0].values[field.code] == "2026-03-14"
    response = _post_add(editor, lst, {"title": "Нет", field.code: "31.02.2026"})
    assert response.status_code == 200
    _field_error(response, field.code, "bad_date", BAD_DATE)
    assert len(_records(lst)) == 1


def test_datetime_moscow_input_stored_as_utc_minute_iso_across_utc_day_boundary():
    """FR-507: дата и время — ввод по Москве хранится в UTC `ГГГГ-ММ-ДДTЧЧ:ММ:00Z`, в том числе со сменой суток."""
    lst = sl.make_list()
    field = sl.add_field(lst, "datetime", "Принято")
    assert _moscow_to_utc(2026, 3, 14, 1, 30) == "2026-03-13T22:30:00Z"
    assert _moscow_to_utc(2026, 3, 14, 3, 0) == "2026-03-14T00:00:00Z"
    assert _moscow_to_utc(2026, 3, 14, 23, 59) == "2026-03-14T20:59:00Z"
    _accepts(field, "14.03.2026 01:30", "2026-03-13T22:30:00Z")
    _accepts(field, "14.03.2026 03:00", "2026-03-14T00:00:00Z")
    _accepts(field, "14.03.2026 23:59", "2026-03-14T20:59:00Z")
    _rejects(field, "14.03.2026", "bad_datetime", BAD_DATETIME)
    _rejects(field, "14.03.2026 25:00", "bad_datetime", BAD_DATETIME)
    _rejects(field, "31.02.2026 10:00", "bad_datetime", BAD_DATETIME)
    editor = sl.as_editor(lst)
    assert _post_add(editor, lst, {"title": "Ночь", field.code: "14.03.2026 01:30"}).status_code == 302
    assert _records(lst)[0].values[field.code] == "2026-03-13T22:30:00Z"


def test_bool_checked_stores_true_and_unchecked_leaves_no_key():
    """FR-507: да/нет — флажок хранит `true`, снятый — ключа в `values` нет (в том числе при правке записи)."""
    lst = sl.make_list()
    field = sl.add_field(lst, "bool", "На гарантии")
    _accepts(field, "on", True)
    assert _parse(field, "").value is None
    editor = sl.as_editor(lst)
    assert _post_add(editor, lst, {"title": "С флажком", field.code: "on"}).status_code == 302
    assert _post_add(editor, lst, {"title": "Без флажка"}).status_code == 302
    checked, unchecked = _records(lst)
    assert checked.values == {field.code: True}
    assert unchecked.values == {}
    response = editor.client.post(
        f"/lists/{lst.pk}/{checked.number}/edit/", {"title": "С флажком", "base_version": checked.version})
    assert response.status_code == 302
    checked.refresh_from_db()
    assert field.code not in checked.values


# --- 4. выбор значений и правило «старое остаётся» ---------------------------------------------------------

def test_choice_archived_value_or_value_of_other_field_rejected_but_old_archived_value_kept():
    """FR-507, FR-515: значение из архива значений и значение другого поля — `value_unavailable`; старое сохранённое остаётся."""
    lst = sl.make_list()
    field = sl.add_field(lst, "choice", "Состояние", choices=["В работе", "Списано"])
    other = sl.add_field(lst, "choice", "Тип", choices=["Ноутбук"])
    working, retired = sl.choice_id(field, "В работе"), sl.choice_id(field, "Списано")
    foreign = sl.choice_id(other, "Ноутбук")
    model("lists.Choice").objects.filter(pk=retired).update(archived=True)
    _accepts(field, [str(working)], [working])
    _rejects(field, [str(retired)], "value_unavailable", UNAVAILABLE)
    _rejects(field, [str(foreign)], "value_unavailable", UNAVAILABLE)
    _rejects(field, [str(working), str(retired)], "value_unavailable", UNAVAILABLE)
    _accepts(field, [str(retired)], [retired], old=[retired])
    _rejects(field, [str(foreign)], "value_unavailable", UNAVAILABLE, old=[retired])


def test_person_dismissed_blocked_or_invited_rejected_but_old_dismissed_value_kept():
    """FR-507, FR-515: сотрудник — уволенный, заблокированный и приглашённый — `value_unavailable`; старый уволенный остаётся."""
    lst = sl.make_list()
    field = sl.add_field(lst, "person", "Ответственный", multiple=True)
    active = support.make_employee()
    dismissed = support.make_employee(state="dismissed")
    blocked = support.make_employee(state="blocked")
    invited = support.make_employee(state="invited")
    _accepts(field, [str(active.pk)], [active.pk])
    for candidate in (dismissed, blocked, invited):
        _rejects(field, [str(candidate.pk)], "value_unavailable", UNAVAILABLE)
        _rejects(field, [str(active.pk), str(candidate.pk)], "value_unavailable", UNAVAILABLE)
    _accepts(field, [str(dismissed.pk)], [dismissed.pk], old=[dismissed.pk])
    _accepts(field, [str(dismissed.pk), str(active.pk)], [dismissed.pk, active.pk], old=[dismissed.pk])
    _rejects(field, [str(blocked.pk)], "value_unavailable", UNAVAILABLE, old=[dismissed.pk])


def test_unit_nonexistent_node_rejected():
    """FR-507, FR-515: подразделение — несуществующий узел — `value_unavailable`; существующий принимается."""
    lst = sl.make_list()
    field = sl.add_field(lst, "unit", "Подразделение", multiple=True)
    unit = support_org.make_unit()
    missing = model("org.Unit").objects.order_by("-pk").values_list("pk", flat=True).first() + 1000
    _accepts(field, [str(unit.pk)], [unit.pk])
    _rejects(field, [str(missing)], "value_unavailable", UNAVAILABLE)
    _rejects(field, [str(unit.pk), str(missing)], "value_unavailable", UNAVAILABLE)


def test_record_value_archived_unreadable_list_or_other_target_list_rejected_but_old_value_kept():
    """FR-507, FR-515: запись — в архиве, нечитаемого списка и не из целевого списка — `value_unavailable`; старая остаётся."""
    target = sl.make_list("Оборудование для ссылок")
    other = sl.make_list("Договоры для проверки")
    holder = sl.make_list("Лицензии для ссылок")
    field = sl.add_field(holder, "record", "Устройство", target=target, multiple=True)
    live = sl.make_record(target, "Ноутбук")
    archived = sl.make_record(target, "Старый ноутбук", archived=True)
    foreign = sl.make_record(other, "Договор")
    reader = sl.as_reader(target).user
    _accepts(field, [str(live.pk)], [live.pk], viewer=reader)
    _rejects(field, [str(archived.pk)], "value_unavailable", UNAVAILABLE, viewer=reader)
    _rejects(field, [str(foreign.pk)], "value_unavailable", UNAVAILABLE, viewer=reader)
    _accepts(field, [str(archived.pk)], [archived.pk], viewer=reader, old=[archived.pk])
    stranger = support.make_employee()
    _rejects(field, [str(live.pk)], "value_unavailable", UNAVAILABLE, viewer=stranger)
    _accepts(field, [str(live.pk)], [live.pk], viewer=stranger, old=[live.pk])


# --- 5. массивы и повторы ----------------------------------------------------------------------------------

def _reference_cases():
    """Для каждого из четырёх ссылочных типов: функция создания поля `(multiple) -> Field`, три id и читающий."""
    target = sl.make_list("Цель")
    reader = sl.as_reader(target).user
    users = [support.make_employee() for _ in range(3)]
    units = [support_org.make_unit() for _ in range(3)]
    records = [sl.make_record(target, f"Запись {number}") for number in range(3)]
    holder = sl.make_list("Хозяин")
    choice_field = sl.add_field(holder, "choice", "Значения", choices=["Один", "Два", "Три"])
    choice_ids = [sl.choice_id(choice_field, title) for title in ("Один", "Два", "Три")]

    def make(type_, multiple):
        if type_ == "choice":
            return sl.add_field(holder, "choice", f"Значения {multiple}", multiple=multiple,
                                choices=["Один", "Два", "Три"])
        if type_ == "record":
            return sl.add_field(holder, "record", f"Записи {multiple}", multiple=multiple, target=target)
        return sl.add_field(holder, type_, f"{type_} {multiple}", multiple=multiple)

    def ids_of(type_, field):
        if type_ == "choice":
            return [sl.choice_id(field, title) for title in ("Один", "Два", "Три")]
        return {"person": [u.pk for u in users], "unit": [u.pk for u in units],
                "record": [r.pk for r in records]}[type_]

    assert len(choice_ids) == 3
    return reader, make, ids_of


def test_multi_value_types_store_array_and_without_multiple_hold_at_most_one_id():
    """FR-508: сотрудник, подразделение, запись, значение — всегда массив id; без «несколько» один id, с «несколько» — набор в порядке выбора."""
    reader, make, ids_of = _reference_cases()
    for type_ in ("person", "unit", "record", "choice"):
        single = make(type_, False)
        one = ids_of(type_, single)[0]
        _accepts(single, [str(one)], [one], viewer=reader)
        assert isinstance(_parse(single, [str(one)], viewer=reader).value, list), type_
        # Без «несколько» два действующих id — отказ `value_unavailable`, без обрезки (5.4, `values.parse`).
        a, b = ids_of(type_, single)[:2]
        _rejects(single, [str(a), str(b)], "value_unavailable", UNAVAILABLE, viewer=reader)
        many = make(type_, True)
        first, second, third = ids_of(type_, many)
        _accepts(many, [str(second), str(first), str(third)], [second, first, third], viewer=reader)
        assert _parse(many, [], viewer=reader).value is None, type_


def test_multiple_person_and_choice_values_are_saved_as_set_without_repeats():
    """FR-508: у нескольких значений поля «сотрудник» и «список значений» повторы убираются — при разборе и при сохранении формы."""
    lst = sl.make_list()
    people = sl.add_field(lst, "person", "Ответственные", multiple=True)
    kinds = sl.add_field(lst, "choice", "Виды", multiple=True, choices=["Один", "Два", "Три"])
    first, second = support.make_employee(), support.make_employee()
    one, two = sl.choice_id(kinds, "Один"), sl.choice_id(kinds, "Два")
    _accepts(people, _ids([first, second, first, second, first]), [first.pk, second.pk])
    _accepts(kinds, [str(two), str(one), str(two)], [two, one])
    editor = sl.as_editor(lst)
    response = _post_add(editor, lst, {
        "title": "Набор", people.code: _ids([first, second, first]), kinds.code: [str(two), str(one), str(two)]})
    assert response.status_code == 302
    record = _records(lst)[0]
    assert record.values[people.code] == [first.pk, second.pk]
    assert record.values[kinds.code] == [two, one]


def test_field_code_is_f_number_so_values_key_never_consists_of_digits():
    """FR-507: код созданного службой поля — `f<номер>` (не из одних цифр), и именно он ключ в `values` записи."""
    from apps.lists.services import records, schema

    lst = sl.make_list()
    actor = sl.as_manager().user
    created = [schema.add_field(lst, name=f"Поле {number}", type="string", actor=actor) for number in range(3)]
    codes = [field.code for field in created]
    assert all(re.fullmatch(r"f[1-9][0-9]*", code) for code in codes), codes
    assert len(set(codes)) == 3
    record = records.create(lst, {"title": "Запись", **{code: f"значение {code}" for code in codes}}, actor)
    record.refresh_from_db()
    assert set(record.values) == set(codes)
    assert not any(name.isdigit() for name in record.values)


# --- 6. форма новой записи ---------------------------------------------------------------------------------

def test_new_record_form_shows_visible_fields_by_order_marks_required_and_fills_defaults():
    """FR-515, FR-508: форма — «Название» и видимые поля по порядку, обязательные отмечены `[data-required]`, умолчания подставлены."""
    lst = sl.make_list()
    target_choice = sl.add_field(lst, "choice", "Состояние", required=True, choices=["Новый", "Старый"])
    text = sl.add_field(lst, "text", "Описание")
    number = sl.add_field(lst, "number", "Количество", default="12.5")
    money = sl.add_field(lst, "money", "Стоимость", default="1234.50")
    date = sl.add_field(lst, "date", "Куплено", default="2026-03-14")
    flag = sl.add_field(lst, "bool", "На гарантии", default=True)
    string = sl.add_field(lst, "string", "Модель", required=True, default="Лаптоп")
    many = sl.add_field(lst, "choice", "Виды", multiple=True, choices=["А", "Б"])
    target_choice.default = [sl.choice_id(target_choice, "Старый")]
    target_choice.save(update_fields=["default"])
    many.default = [sl.choice_id(many, "Б")]
    many.save(update_fields=["default"])
    editor = sl.as_editor(lst)
    response = editor.client.get(_add_url(lst))
    assert response.status_code == 200
    form = _form_of(response)
    order = [node.attrs["data-lists-field"] for node in _containers(form)]
    assert order == ["title", target_choice.code, text.code, number.code, money.code, date.code, flag.code,
                     string.code, many.code]
    required = {node.attrs["data-lists-field"] for node in _containers(form) if "data-required" in node.attrs}
    assert required == {"title", target_choice.code, string.code}
    assert _control(form, number.code).attrs["value"] == "12,5"
    assert _control(form, money.code).attrs["value"] == "1234,50"
    assert _control(form, date.code).attrs["value"] == "14.03.2026"
    assert _control(form, string.code).attrs["value"] == "Лаптоп"
    assert "checked" in _control(form, flag.code, "input").attrs
    selected = [option.attrs["value"] for option in _find(_container(form, target_choice.code), "option")
                if "selected" in option.attrs]
    assert selected == [str(sl.choice_id(target_choice, "Старый"))]
    boxes = {node.attrs["value"]: "checked" in node.attrs
             for node in _find(_container(form, many.code), "input", type="checkbox", name=many.code)}
    assert boxes == {str(sl.choice_id(many, "А")): False, str(sl.choice_id(many, "Б")): True}


def test_new_record_form_date_default_today_is_moscow_date_when_clock_at_utc_midnight(clock):
    """FR-508: умолчание «сегодня» у даты — дата по Москве: в 22:00 UTC 13 марта по Москве уже 14 марта."""
    lst = sl.make_list()
    date = sl.add_field(lst, "date", "Куплено", default={"today": True})
    editor = sl.as_editor(lst)
    moment = datetime(2026, 3, 13, 22, 0, tzinfo=ZoneInfo("UTC"))
    assert moment.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y") == "14.03.2026"
    clock.set(moment)
    form = _form_of(editor.client.get(_add_url(lst)))
    assert _control(form, date.code).attrs["value"] == "14.03.2026"
    response = _post_add(editor, lst, {"title": "Сегодня", date.code: "14.03.2026"})
    assert response.status_code == 302
    assert _records(lst)[0].values[date.code] == "2026-03-14"


def test_new_record_form_does_not_fill_default_of_hidden_field():
    """FR-508: у скрытого поля умолчание новой записи не ставится — ни в форме, ни в `values`, ни в `UniqueValue` уникального."""
    lst = sl.make_list()
    shown = sl.add_field(lst, "string", "Видимое", default="видно")
    hidden = sl.add_field(lst, "string", "Скрытое", unique=True, hidden=True, default="скрыто")
    editor = sl.as_editor(lst)
    form = _form_of(editor.client.get(_add_url(lst)))
    assert _find(form, data_lists_field=hidden.code) == []
    assert _control(form, shown.code).attrs["value"] == "видно"
    response = _post_add(editor, lst, {"title": "Запись", shown.code: "видно"})
    assert response.status_code == 302
    record = _records(lst)[0]
    assert record.values == {shown.code: "видно"}
    assert not model("lists.UniqueValue").objects.filter(list=lst, field=hidden).exists()


def test_empty_required_field_or_title_gives_required_text_at_field_and_keeps_other_input():
    """FR-515, FR-546: пустое обязательное поле и пустое «Название» — «Обязательное поле» у поля, остальное введённое остаётся."""
    lst = sl.make_list()
    must = sl.add_field(lst, "string", "Модель", required=True)
    other = sl.add_field(lst, "string", "Заметка")
    editor = sl.as_editor(lst)
    response = _post_add(editor, lst, {"title": "Ноутбук", must.code: "", other.code: "сохранить это"})
    assert response.status_code == 200
    _field_error(response, must.code, "required", REQUIRED)
    assert _find(_tree(response), data_error="title") == []
    form = _form_of(response)
    assert _control(form, "title").attrs["value"] == "Ноутбук"
    assert _control(form, other.code).attrs["value"] == "сохранить это"
    response = _post_add(editor, lst, {"title": "", must.code: "Модель X", other.code: "и это"})
    assert response.status_code == 200
    _field_error(response, "title", "required", REQUIRED)
    assert _find(_tree(response), data_error=must.code) == []
    form = _form_of(response)
    assert _control(form, must.code).attrs["value"] == "Модель X"
    assert _control(form, other.code).attrs["value"] == "и это"
    assert _records(lst) == []


def test_hidden_required_field_is_not_checked_when_adding_record():
    """FR-515: скрытое обязательное поле при добавлении записи не проверяется и в форме не показано."""
    lst = sl.make_list()
    hidden = sl.add_field(lst, "string", "Скрытое", required=True, hidden=True)
    shown = sl.add_field(lst, "string", "Видимое")
    editor = sl.as_editor(lst)
    form = _form_of(editor.client.get(_add_url(lst)))
    assert _find(form, data_lists_field=hidden.code) == []
    response = _post_add(editor, lst, {"title": "Запись", shown.code: "х"})
    assert response.status_code == 302
    record = _records(lst)[0]
    assert record.values == {shown.code: "х"}


def test_invalid_number_date_money_and_overlong_string_on_form_give_reason_at_each_field_and_save_nothing():
    """FR-507, FR-515, FR-546: число с буквами, неверная дата, три знака денег, строка длиннее предела — причина у каждого поля, записи нет."""
    lst = sl.make_list()
    number = sl.add_field(lst, "number", "Количество")
    date = sl.add_field(lst, "date", "Куплено")
    money = sl.add_field(lst, "money", "Стоимость")
    string = sl.add_field(lst, "string", "Модель")
    editor = sl.as_editor(lst)
    response = _post_add(editor, lst, {
        "title": "Запись", number.code: "12abc", date.code: "31.02.2026", money.code: "1,234", string.code: "я" * 501})
    assert response.status_code == 200
    _field_error(response, number.code, "bad_number", BAD_NUMBER)
    _field_error(response, date.code, "bad_date", BAD_DATE)
    _field_error(response, money.code, "money_digits", MONEY_DIGITS)
    _field_error(response, string.code, "too_long", LIMIT_500)
    form = _form_of(response)
    assert _control(form, number.code).attrs["value"] == "12abc"
    assert _control(form, date.code).attrs["value"] == "31.02.2026"
    assert _control(form, "title").attrs["value"] == "Запись"
    assert _records(lst) == []
    lst.refresh_from_db()
    assert lst.next_number == 1


# --- 7. показ значений -------------------------------------------------------------------------------------

def test_display_dismissed_person_with_dismissed_mark_and_archived_choice_by_title():
    """FR-507, FR-515: уволенный сотрудник — «ФИО (уволен)» (и `span[data-dismissed]` в карточке), значение из архива — по названию."""
    lst = sl.make_list()
    people = sl.add_field(lst, "person", "Ответственные", multiple=True)
    kinds = sl.add_field(lst, "choice", "Состояние", choices=["В работе", "Списано"])
    active = support.make_employee(full_name="Петров Пётр Петрович")
    dismissed = support.make_employee(full_name="Сидоров Семён Семёнович", state="dismissed")
    retired = sl.choice_id(kinds, "Списано")
    model("lists.Choice").objects.filter(pk=retired).update(archived=True)
    assert _display(people, [dismissed.pk]) == "Сидоров Семён Семёнович (уволен)"
    assert _display(people, [active.pk]) == "Петров Пётр Петрович"
    assert _display(people, [active.pk, dismissed.pk]) == "Петров Пётр Петрович; Сидоров Семён Семёнович (уволен)"
    assert _display(kinds, [retired]) == "Списано"
    record = sl.make_record(lst, "Запись", {people.code: [active.pk, dismissed.pk], kinds.code: [retired]})
    reader = sl.as_reader(lst)
    response = reader.client.get(f"/lists/{lst.pk}/{record.number}/")
    assert response.status_code == 200
    cell = _find(_tree(response), data_lists_value=people.code)[0]
    marks = _find(cell, "span", data_dismissed="true")
    assert len(marks) == 1
    assert "Сидоров Семён Семёнович" in marks[0].text()
    assert "(уволен)" in marks[0].text()
    assert "Петров Пётр Петрович" in cell.text()
    assert "Списано" in _find(_tree(response), data_lists_value=kinds.code)[0].text()


def test_display_record_of_unreadable_list_as_unavailable_and_archived_record_with_archived_mark():
    """FR-507: запись — «Название — №N», в архиве — с « (в архиве)», нечитаемого списка — «запись недоступного списка» без названия."""
    target = sl.make_list("Оборудование для ссылок")
    holder = sl.make_list("Лицензии для ссылок")
    field = sl.add_field(holder, "record", "Устройство", target=target, multiple=True)
    live = sl.make_record(target, "Ноутбук Альфа")
    archived = sl.make_record(target, "Ноутбук Бета", archived=True)
    reader = sl.as_reader(target).user
    stranger = support.make_employee()
    assert _display(field, [live.pk], reader) == f"Ноутбук Альфа — №{live.number}"
    assert _display(field, [archived.pk], reader) == f"Ноутбук Бета — №{archived.number} (в архиве)"
    assert _display(field, [live.pk, archived.pk], reader) == (
        f"Ноутбук Альфа — №{live.number}; Ноутбук Бета — №{archived.number} (в архиве)")
    hidden_text = _display(field, [live.pk], stranger)
    assert hidden_text == "запись недоступного списка"
    assert "Ноутбук Альфа" not in hidden_text


def test_display_money_and_dates_in_russian_format():
    """FR-507: деньги — «1 234,50 ₽ / $ / €», число с запятой, дата «ДД.ММ.ГГГГ», дата и время по Москве, да/нет — «Да»."""
    lst = sl.make_list()
    rub = sl.add_field(lst, "money", "Рубли", currency="RUB")
    usd = sl.add_field(lst, "money", "Доллары", currency="USD")
    eur = sl.add_field(lst, "money", "Евро", currency="EUR")
    number = sl.add_field(lst, "number", "Количество")
    date = sl.add_field(lst, "date", "Куплено")
    moment = sl.add_field(lst, "datetime", "Принято")
    flag = sl.add_field(lst, "bool", "На гарантии")
    assert _display(rub, "1234.50") == "1 234,50 ₽"
    assert _display(usd, "1234.50") == "1 234,50 $"
    assert _display(eur, "1234.50") == "1 234,50 €"
    assert _display(rub, "1234567.00") == "1 234 567,00 ₽"
    assert _display(rub, "0.50") == "0,50 ₽"
    assert _display(number, "12.5") == "12,5"
    assert _display(date, "2026-03-14") == "14.03.2026"
    assert _display(moment, "2026-03-13T22:30:00Z") == "14.03.2026 01:30"
    assert _display(flag, True) == "Да"
