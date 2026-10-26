"""T-6111: таблица записей — фильтры, сортировка, страницы, параметры и SQL (FR-518, FR-519, NFR-509).

Сценарии «Таблица записей» спеки. Страница `/lists/<id>/` проверяется по зацепкам раздела 11.3 контракта
(`tr[data-record-number]`, `th[data-sort]`, `[data-lists-found]`, `a[data-action="next-page"]`), разбор параметров и
запрос — службами `grid.read` и `grid.records` (раздел 5.6, только в тесте SQL). Код среза на уровне модуля не
импортируется. Смотрит таблицу сотрудник с правом `lists.manage` (читает все списки); читатель без доступа к целевому
списку — только в тестах сортировки по полю-ссылке.
"""
import html as html_lib
import re
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.http import QueryDict

from tests import support, support_org
from tests import support_lists as lp

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники только этого файла ------------------------------------------------------------------------

class _Dom(HTMLParser):
    """Плоский разбор разметки: узел — тег, атрибуты, текст внутри, предки."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list = []
        self._stack: list = []

    def _open(self, tag, attrs):
        node = SimpleNamespace(tag=tag, attrs={name: (val if val is not None else "") for name, val in attrs},
                               parts=[], ancestors=list(self._stack))
        self.nodes.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._open(tag, attrs)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        if any(n.tag == tag for n in self._stack):
            while self._stack:
                if self._stack.pop().tag == tag:
                    break

    def handle_data(self, data):
        for node in self._stack:
            node.parts.append(data)


def _dom(response) -> list:
    cached = getattr(response, "_grid_test_dom", None)
    if cached is not None:
        return cached
    parser = _Dom()
    parser.feed(response.content.decode())
    parser.close()
    for node in parser.nodes:
        node.text = "".join(node.parts)
    response._grid_test_dom = parser.nodes
    return parser.nodes


def _find(response, tag: str | None = None, **attrs) -> list:
    """Узлы с тегом `tag` (если задан) и атрибутами; в `attrs` дефис записывается подчёркиванием."""
    want = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [n for n in _dom(response)
            if (tag is None or n.tag == tag) and all(n.attrs.get(k) == v for k, v in want.items())]


def _env():
    """Управляющий (читает все списки) и пустой список его авторства."""
    manager = lp.as_manager()
    return manager, lp.make_list(created_by=manager.user)


def _records(lst, values_by_record, *, prefix: str = "Запись"):
    """Записи по порядку: у каждой — свои `values`; номера 1, 2, … по порядку создания."""
    return [lp.make_record(lst, f"{prefix} {index}", values)
            for index, values in enumerate(values_by_record, start=1)]


def _get(session, lst, params=None, *, hx: bool = False):
    extra = {"headers": {"HX-Request": "true", "HX-Target": "lists-grid"}} if hx else {}
    response = session.client.get(f"/lists/{lst.pk}/", params or {}, **extra)
    assert response.status_code == 200, f"таблица списка: ожидался 200, получен {response.status_code}"
    return response


def _numbers_of(response) -> list[int]:
    return [int(n.attrs["data-record-number"]) for n in _dom(response)
            if n.tag == "tr" and "data-record-number" in n.attrs]


def _numbers(session, lst, params=None) -> list[int]:
    """Номера записей строк таблицы по порядку."""
    return _numbers_of(_get(session, lst, params))


def _found(response) -> int:
    nodes = [n for n in _dom(response) if "data-lists-found" in n.attrs]
    assert len(nodes) == 1, "на странице должен быть один блок `[data-lists-found]`"
    text = html_lib.unescape(nodes[0].text)
    match = re.search(r"Найдено:\s*(\d+)", text)
    assert match, f"«Найдено: N» не найдено в блоке: {text!r}"
    return int(match.group(1))


def _qs_of(link: str) -> dict:
    return parse_qs(urlsplit(html_lib.unescape(link)).query)


# --- фильтры (FR-519) ------------------------------------------------------------------------------------

def test_string_and_text_filters_match_substring_case_insensitive():
    """FR-519: `f.<код>` у «строки», «многострочного текста» и `f.title` — подстрока без учёта регистра (не
    начало слова, символы `%` и `_` — обычные знаки); запись в архиве в отбор «Все» не попадает."""
    manager, lst = _env()
    lp.add_field(lst, "string", code="s")
    lp.add_field(lst, "text", code="t")
    first, second, third, fourth = [
        lp.make_record(lst, title, values) for title, values in (
            ("Склад A", {"s": "Ноутбук Dell", "t": "Серый корпус\nс царапиной"}),
            ("Склад б", {"s": "Принтер HP"}),
            ("Офис", {"s": "монитор DELL"}),
            ("Касса", {}))]
    lp.make_record(lst, "Склад архив", {"s": "dell в архиве"}, archived=True)
    nums = lambda params: _numbers(manager, lst, params)  # noqa: E731
    assert nums({"f.s": "dell"}) == [first.number, third.number]
    assert nums({"f.s": "DELL"}) == [first.number, third.number]
    assert nums({"f.s": "ell"}) == [first.number, third.number]
    assert nums({"f.s": "ПРИНТ"}) == [second.number]
    assert nums({"f.t": "ЦАРАП"}) == [first.number]
    assert nums({"f.title": "СКЛАД"}) == [first.number, second.number]
    assert nums({"f.s": "zzz"}) == []
    assert nums({"f.s": "%"}) == []
    assert nums({"f.s": "_"}) == []
    assert fourth.number not in nums({"f.s": "dell"})


def test_number_and_money_filters_from_to_compare_as_decimal():
    """FR-519: «число» и «деньги» — `f.<код>.from`/`.to` сравниваются как десятичные (не как текст), разделитель —
    точка или запятая; запись без значения в диапазон не входит. Границы не совпадают со значениями."""
    manager, lst = _env()
    lp.add_field(lst, "number", code="n")
    lp.add_field(lst, "money", code="m")
    nine, ten, hundred, thousand, minus, empty = _records(lst, [
        {"n": "9", "m": "5.00"}, {"n": "10", "m": "10.00"}, {"n": "100.5", "m": "100.50"},
        {"n": "1000", "m": "1234.50"}, {"n": "-3", "m": "0.50"}, {}])
    nums = lambda params: _numbers(manager, lst, params)  # noqa: E731
    assert nums({"f.n.from": "9.5", "f.n.to": "500"}) == [ten.number, hundred.number]
    assert nums({"f.n.from": "9,5", "f.n.to": "500,0"}) == [ten.number, hundred.number]
    assert nums({"f.n.from": "100"}) == [hundred.number, thousand.number]
    assert nums({"f.n.to": "9.5"}) == [nine.number, minus.number]
    assert nums({"f.n.from": "-5", "f.n.to": "0"}) == [minus.number]
    assert nums({"f.m.from": "6", "f.m.to": "200"}) == [ten.number, hundred.number]
    assert nums({"f.m.from": "6", "f.m.to": "150,5"}) == [ten.number, hundred.number]
    assert nums({"f.m.from": "1000"}) == [thousand.number]
    assert nums({"f.m.to": "1"}) == [minus.number]
    assert empty.number not in nums({"f.n.from": "-100"})
    assert empty.number not in nums({"f.m.to": "99999"})


def test_date_filter_from_to_includes_both_bounds():
    """FR-519: «дата» — `f.<код>.from`/`.to`, обе границы входят; граница — ДД.ММ.ГГГГ или ISO; запись без даты
    в диапазон не входит."""
    manager, lst = _env()
    lp.add_field(lst, "date", code="d")
    first, second, third, fourth, empty = _records(lst, [
        {"d": "2025-03-10"}, {"d": "2025-03-11"}, {"d": "2025-03-12"}, {"d": "2025-03-13"}, {}])
    nums = lambda params: _numbers(manager, lst, params)  # noqa: E731
    assert nums({"f.d.from": "11.03.2025", "f.d.to": "12.03.2025"}) == [second.number, third.number]
    assert nums({"f.d.from": "2025-03-11", "f.d.to": "2025-03-12"}) == [second.number, third.number]
    assert nums({"f.d.from": "12.03.2025"}) == [third.number, fourth.number]
    assert nums({"f.d.to": "10.03.2025"}) == [first.number]
    assert nums({"f.d.from": "13.03.2025", "f.d.to": "13.03.2025"}) == [fourth.number]
    assert empty.number not in nums({"f.d.from": "01.01.2000"})


def test_datetime_filter_bounds_are_moscow_time_converted_to_utc_and_to_is_inclusive_by_minute():
    """FR-519, NFR-509: «дата и время» — границы «ДД.ММ.ГГГГ ЧЧ:ММ» вводятся по Москве (UTC+3) и переводятся в
    UTC; «до» включительно по минуте; запись без значения в диапазон не входит."""
    manager, lst = _env()
    lp.add_field(lst, "datetime", code="dt")
    r_1159, r_1200, r_1230, r_1300, r_1301, r_none, r_midnight = _records(lst, [
        {"dt": "2025-03-10T08:59:00Z"}, {"dt": "2025-03-10T09:00:00Z"}, {"dt": "2025-03-10T09:30:00Z"},
        {"dt": "2025-03-10T10:00:00Z"}, {"dt": "2025-03-10T10:01:00Z"}, {}, {"dt": "2025-03-10T21:30:00Z"}])
    nums = lambda params: _numbers(manager, lst, params)  # noqa: E731
    assert nums({"f.dt.from": "10.03.2025 12:00", "f.dt.to": "10.03.2025 13:00"}) == [
        r_1200.number, r_1230.number, r_1300.number]
    assert nums({"f.dt.from": "10.03.2025 13:00", "f.dt.to": "10.03.2025 13:01"}) == [r_1300.number, r_1301.number]
    assert nums({"f.dt.to": "10.03.2025 11:59"}) == [r_1159.number]
    assert nums({"f.dt.from": "10.03.2025 12:30", "f.dt.to": "10.03.2025 12:45"}) == [r_1230.number]
    assert nums({"f.dt.from": "11.03.2025 00:00"}) == [r_midnight.number]
    assert r_none.number not in nums({"f.dt.from": "01.01.2000 00:00"})


def test_bool_filter_yes_matches_true_and_no_includes_records_without_value():
    """FR-519: «да/нет» — `f.<код>=yes` отбирает записи с `true`, `no` — все остальные, в том числе без ключа."""
    manager, lst = _env()
    lp.add_field(lst, "bool", code="b")
    lp.add_field(lst, "string", code="s")
    first, second, third, fourth = _records(lst, [{"b": True}, {}, {"b": True, "s": "x"}, {"s": "y"}])
    lp.make_record(lst, "В архиве", {"b": True}, archived=True)
    assert _numbers(manager, lst, {"f.b": "yes"}) == [first.number, third.number]
    assert _numbers(manager, lst, {"f.b": "no"}) == [second.number, fourth.number]


def test_choice_person_unit_and_record_filters_match_records_containing_the_value():
    """FR-519: `f.<код>=<id>` у «списка значений», «сотрудника», «подразделения», «записи другого списка» — записи,
    содержащие значение; повторяющийся параметр — все значения сразу; не использованное значение — пустой итог."""
    manager, lst = _env()
    target = lp.make_list(created_by=manager.user)
    targets = _records(target, [{}, {}], prefix="Цель")
    choice_field = lp.add_field(lst, "choice", code="c", multiple=True, choices=("Один", "Два", "Три"))
    lp.add_field(lst, "person", code="p", multiple=True)
    lp.add_field(lst, "unit", code="u", multiple=True)
    lp.add_field(lst, "record", code="r", multiple=True, target=target)
    people = [support.make_employee(), support.make_employee()]
    units = [support_org.make_unit(), support_org.make_unit()]
    choice_one, choice_two, choice_three = (lp.choice_id(choice_field, t) for t in ("Один", "Два", "Три"))
    only_first, only_second, both, none = _records(lst, [
        {"c": [choice_one], "p": [people[0].pk], "u": [units[0].pk], "r": [targets[0].pk]},
        {"c": [choice_two], "p": [people[1].pk], "u": [units[1].pk], "r": [targets[1].pk]},
        {"c": [choice_one, choice_two], "p": [people[0].pk, people[1].pk], "u": [units[0].pk, units[1].pk],
         "r": [targets[0].pk, targets[1].pk]},
        {}])
    cases = (("c", choice_one, choice_two), ("p", people[0].pk, people[1].pk), ("u", units[0].pk, units[1].pk),
             ("r", targets[0].pk, targets[1].pk))
    for code, first_id, second_id in cases:
        assert _numbers(manager, lst, {f"f.{code}": str(first_id)}) == [only_first.number, both.number], code
        assert _numbers(manager, lst, {f"f.{code}": str(second_id)}) == [only_second.number, both.number], code
        assert _numbers(manager, lst, {f"f.{code}": [str(first_id), str(second_id)]}) == [both.number], code
    assert _numbers(manager, lst, {"f.c": str(choice_three)}) == []
    assert none.number not in _numbers(manager, lst, {"f.c": str(choice_one)})


def test_file_filter_yes_and_no_by_presence_of_record_files():
    """FR-519: у поля «файл» `f.<код>.files=yes` — записи, у которых есть файлы поля, `no` — у которых нет."""
    manager, lst = _env()
    file_field = lp.add_field(lst, "file", code="fl", multiple=True)
    other_file_field = lp.add_field(lst, "file", code="fm")
    first, second, third, fourth = _records(lst, [{}, {}, {}, {}])
    lp.attach_file(first, file_field)
    lp.attach_file(second, file_field, name="счёт.pdf")
    lp.attach_file(second, file_field, name="акт.pdf")
    # у третьей записи файл только другого поля: для `f.fl.files` он не в счёт (CONTRACT-006, 10.3, К-15)
    lp.attach_file(third, other_file_field, name="схема.pdf")
    assert _numbers(manager, lst, {"f.fl.files": "yes"}) == [first.number, second.number]
    assert _numbers(manager, lst, {"f.fl.files": "no"}) == [third.number, fourth.number]
    assert _numbers(manager, lst, {"f.fm.files": "yes"}) == [third.number]
    assert _numbers(manager, lst, {"f.fm.files": "no"}) == [first.number, second.number, fourth.number]


def test_invalid_date_number_and_id_filter_values_are_dropped_without_server_error():
    """FR-519: неверное значение фильтра (дата, число, id, «да/нет») отбрасывается, а не пустит итог и не даёт 500;
    верное значение рядом с неверным действует."""
    manager, lst = _env()
    lp.add_field(lst, "date", code="d")
    lp.add_field(lst, "datetime", code="dt")
    lp.add_field(lst, "number", code="n")
    lp.add_field(lst, "money", code="m")
    lp.add_field(lst, "bool", code="b")
    lp.add_field(lst, "choice", code="c", choices=("Один",))
    lp.add_field(lst, "person", code="p")
    first, second, third = _records(lst, [
        {"d": "2025-03-10", "n": "5", "m": "5.00"}, {"d": "2025-03-11", "n": "50", "m": "50.00"},
        {"d": "2025-03-12", "n": "500", "m": "500.00"}])
    everything = [first.number, second.number, third.number]
    bad_values = (
        {"f.d.from": "32.13.2025"}, {"f.d.to": "вчера"}, {"f.dt.from": "99.99.2025 25:61"},
        {"f.dt.to": "не время"}, {"f.n.from": "abc"}, {"f.n.to": "1,2,3"}, {"f.m.from": "12 рублей"},
        {"f.m.to": "--"}, {"f.c": "abc"}, {"f.c": "1.5"}, {"f.p": "x"}, {"f.b": "maybe"})
    for params in bad_values:
        assert _numbers(manager, lst, params) == everything, params
    mixed = _numbers(manager, lst, {"f.n.from": "abc", "f.n.to": "100"})
    assert mixed == [first.number, second.number]
    assert mixed == _numbers(manager, lst, {"f.n.to": "100"})
    assert _numbers(manager, lst, {"f.d.from": "32.13.2025", "f.d.to": "10.03.2025"}) == [first.number]


def test_choice_equals_date_from_to_and_title_contains_combine_with_and_and_show_found_count():
    """FR-519, FR-518: фильтры «список значений = X», «дата от/до» и «название содержит» сочетаются по «и», число
    «Найдено: N» на странице равно числу строк итога; каждый фильтр сам по себе даёт больше."""
    manager, lst = _env()
    status = lp.add_field(lst, "choice", code="c", choices=("Новый", "Готов"))
    lp.add_field(lst, "date", code="d")
    new_id, ready_id = lp.choice_id(status, "Новый"), lp.choice_id(status, "Готов")
    rows = (
        ("Принтер офис", {"c": [new_id], "d": "2025-03-10"}),
        ("Принтер склад", {"c": [new_id], "d": "2025-03-20"}),
        ("Принтер цех", {"c": [ready_id], "d": "2025-03-10"}),
        ("Монитор офис", {"c": [new_id], "d": "2025-03-10"}),
        ("Принтер двор", {"c": [new_id], "d": "2025-03-11"}))
    records = [lp.make_record(lst, title, values) for title, values in rows]
    params = {"f.c": str(new_id), "f.d.from": "09.03.2025", "f.d.to": "15.03.2025", "f.title": "принтер"}
    response = _get(manager, lst, params)
    assert _numbers_of(response) == [records[0].number, records[4].number]
    assert _found(response) == 2
    for single in ({"f.c": str(new_id)}, {"f.d.from": "09.03.2025", "f.d.to": "15.03.2025"}, {"f.title": "принтер"}):
        assert len(_numbers(manager, lst, single)) > 2, single


# --- сортировка (FR-518) ---------------------------------------------------------------------------------

def _assert_sorted(manager, lst, code, ascending, descending):
    """Оба направления; пустое значение — в конце, как бы ни шло направление."""
    assert _numbers(manager, lst, {"sort": code, "dir": "asc"}) == ascending, f"{code} asc"
    assert _numbers(manager, lst, {"sort": code, "dir": "desc"}) == descending, f"{code} desc"


def test_sort_by_string_text_number_and_money_both_directions_with_empty_values_last():
    """FR-518: сортировка по «строке», «тексту», «числу», «деньгам» — по возрастанию и убыванию; число и деньги
    сравниваются как числа; запись без значения (первая по номеру) в конце в обоих направлениях; `sort=title`."""
    manager, lst = _env()
    lp.add_field(lst, "string", code="s")
    lp.add_field(lst, "text", code="t")
    lp.add_field(lst, "number", code="n")
    lp.add_field(lst, "money", code="m")
    empty, second, third, fourth = [
        lp.make_record(lst, title, values) for title, values in (
            ("Ягода", {}),
            ("Арбуз", {"s": "вишня", "t": "бета", "n": "9", "m": "100.00"}),
            ("Вишня", {"s": "арбуз", "t": "альфа", "n": "10", "m": "9.50"}),
            ("Банан", {"s": "банан", "t": "гамма", "n": "-3", "m": "1000.00"}))]
    a, b, c, e = second.number, third.number, fourth.number, empty.number
    _assert_sorted(manager, lst, "s", [b, c, a, e], [a, c, b, e])
    _assert_sorted(manager, lst, "t", [b, a, c, e], [c, a, b, e])
    _assert_sorted(manager, lst, "n", [c, a, b, e], [b, a, c, e])
    _assert_sorted(manager, lst, "m", [b, a, c, e], [c, a, b, e])
    _assert_sorted(manager, lst, "title", [a, c, b, e], [e, b, c, a])
    assert _numbers(manager, lst, {"sort": "number", "dir": "desc"}) == sorted([a, b, c, e], reverse=True)


def test_sort_by_date_datetime_and_bool_both_directions_with_empty_values_last():
    """FR-518: сортировка по «дате», «дате и времени» (по хранимому значению в UTC) и «да/нет»; пустое значение —
    в конце в обоих направлениях; у «да/нет» запись с `true` идёт раньше пустой в обоих направлениях."""
    manager, lst = _env()
    lp.add_field(lst, "date", code="d")
    lp.add_field(lst, "datetime", code="dt")
    empty, second, third, fourth = _records(lst, [
        {}, {"d": "2025-03-12", "dt": "2025-03-10T10:00:00Z"}, {"d": "2025-03-10", "dt": "2025-03-10T09:00:00Z"},
        {"d": "2025-03-11", "dt": "2025-03-09T23:00:00Z"}])
    a, b, c, e = second.number, third.number, fourth.number, empty.number
    _assert_sorted(manager, lst, "d", [b, c, a, e], [a, c, b, e])
    _assert_sorted(manager, lst, "dt", [c, b, a, e], [a, b, c, e])
    flags = lp.make_list(created_by=manager.user)
    lp.add_field(flags, "bool", code="b")
    without, with_true = _records(flags, [{}, {"b": True}])
    _assert_sorted(manager, flags, "b", [with_true.number, without.number], [with_true.number, without.number])


def test_sort_by_choice_follows_choice_order_of_first_value():
    """FR-518: сортировка по «списку значений» — по `Choice.order` первого значения (не по названию и не по id);
    пустое — в конце."""
    manager, lst = _env()
    field = lp.add_field(lst, "choice", code="c", multiple=True, choices=("Ремонт", "Склад", "Выдан"))
    Choice = support.model("lists.Choice")
    for title, order in (("Выдан", 1), ("Склад", 2), ("Ремонт", 3)):
        Choice.objects.filter(pk=lp.choice_id(field, title)).update(order=order)
    repair, store, issued = (lp.choice_id(field, t) for t in ("Ремонт", "Склад", "Выдан"))
    empty, with_issued, with_store_first, with_repair = _records(lst, [
        {}, {"c": [issued]}, {"c": [store, repair]}, {"c": [repair]}])
    _assert_sorted(manager, lst, "c",
                   [with_issued.number, with_store_first.number, with_repair.number, empty.number],
                   [with_repair.number, with_store_first.number, with_issued.number, empty.number])


def test_sort_by_person_uses_full_name_and_by_unit_uses_unit_name_of_first_value():
    """FR-518: сортировка по «сотруднику» — по ФИО первого значения, по «подразделению» — по названию узла первого
    значения (не по id); пустое — в конце."""
    manager, lst = _env()
    lp.add_field(lst, "person", code="p", multiple=True)
    lp.add_field(lst, "unit", code="u", multiple=True)
    yakovlev = support.make_employee(full_name="Яковлев Ян")
    andreev = support.make_employee(full_name="Андреев Антон")
    borisov = support.make_employee(full_name="Борисов Борис")
    yar = support_org.make_unit("Ярус")
    abc = support_org.make_unit("Абрис")
    bor = support_org.make_unit("Борт")
    empty, first, second, third = _records(lst, [
        {}, {"p": [yakovlev.pk], "u": [yar.pk]}, {"p": [borisov.pk, andreev.pk], "u": [bor.pk, abc.pk]},
        {"p": [andreev.pk], "u": [abc.pk]}])
    _assert_sorted(manager, lst, "p", [third.number, second.number, first.number, empty.number],
                   [first.number, second.number, third.number, empty.number])
    _assert_sorted(manager, lst, "u", [third.number, second.number, first.number, empty.number],
                   [first.number, second.number, third.number, empty.number])


def _record_fixture(manager):
    """Список с полем «запись» на целевой список: записи цели «Яблоко», «Борщ», «Арбуз»."""
    target = lp.make_list(created_by=manager.user)
    apple, borscht, melon = [lp.make_record(target, title) for title in ("Яблоко", "Борщ", "Арбуз")]
    lst = lp.make_list(created_by=manager.user)
    lp.add_field(lst, "record", code="r", multiple=True, target=target)
    empty, with_apple, with_borscht_first, with_melon = _records(lst, [
        {}, {"r": [apple.pk]}, {"r": [borscht.pk, melon.pk]}, {"r": [melon.pk]}])
    return target, lst, (empty, with_apple, with_borscht_first, with_melon)


def test_sort_by_record_uses_title_of_first_target_record_when_target_list_is_readable():
    """FR-518: сортировка по полю «запись другого списка» — по названию первой связанной записи, если целевой
    список читает смотрящий (управляющий и читатель обоих списков); пустое — в конце."""
    manager = lp.as_manager()
    target, lst, (empty, with_apple, with_borscht, with_melon) = _record_fixture(manager)
    ascending = [with_melon.number, with_borscht.number, with_apple.number, empty.number]
    descending = [with_apple.number, with_borscht.number, with_melon.number, empty.number]
    _assert_sorted(manager, lst, "r", ascending, descending)
    reader = lp.as_reader(lst)
    lp.grant_list(target, reader.user.roles.first(), "read")
    _assert_sorted(reader, lst, "r", ascending, descending)


def test_sort_by_record_field_of_unreadable_target_list_is_dropped():
    """FR-518, NFR-509: если целевой список смотрящему не доступен, сортировка по полю-ссылке отбрасывается
    (порядок по номеру, без ошибки и без раскрытия названий записей закрытого списка)."""
    manager = lp.as_manager()
    target, lst, (empty, with_apple, with_borscht, with_melon) = _record_fixture(manager)
    reader = lp.as_reader(lst)
    by_number = [empty.number, with_apple.number, with_borscht.number, with_melon.number]
    assert _numbers(reader, lst, {"sort": "r", "dir": "asc"}) == by_number
    assert _numbers(reader, lst, {"sort": "r", "dir": "desc"}) == by_number
    assert _numbers(manager, lst, {"sort": "r", "dir": "asc"}) != by_number


def test_sort_by_file_field_is_dropped():
    """FR-518: по полю «файл» не сортируется — параметр отбрасывается, порядок по номеру."""
    manager, lst = _env()
    file_field = lp.add_field(lst, "file", code="fl", multiple=True)
    lp.add_field(lst, "string", code="s")
    first, second, third = _records(lst, [{"s": "в"}, {"s": "б"}, {"s": "а"}])
    lp.attach_file(third, file_field)
    by_number = [first.number, second.number, third.number]
    assert _numbers(manager, lst, {"sort": "fl", "dir": "asc"}) == by_number
    assert _numbers(manager, lst, {"sort": "fl", "dir": "desc"}) == by_number
    assert _numbers(manager, lst, {"sort": "s", "dir": "asc"}) == [third.number, second.number, first.number]


def test_equal_sort_values_are_ordered_by_record_number_stably():
    """FR-518: при равных значениях порядок по номеру записи (последний ключ сортировки), повтор запроса даёт тот же
    порядок."""
    manager, lst = _env()
    lp.add_field(lst, "string", code="s")
    lp.add_field(lst, "number", code="n")
    first, second, third, fourth = _records(lst, [{"s": "а", "n": "5"}, {"s": "А", "n": "5"}, {"s": "б", "n": "5"},
                                                  {"s": " а", "n": "5"}])
    params = {"sort": "n", "dir": "asc"}
    assert _numbers(manager, lst, params) == [first.number, second.number, third.number, fourth.number]
    assert _numbers(manager, lst, params) == _numbers(manager, lst, params)
    # номер — последний ключ по возрастанию и при `desc` (CONTRACT-006, 5.6; 10.3, К-15)
    assert _numbers(manager, lst, {"sort": "n", "dir": "desc"}) == [first.number, second.number, third.number,
                                                                    fourth.number]
    same = lp.make_list(created_by=manager.user)
    lp.add_field(same, "string", code="s")
    one, two, three, four = _records(same, [{"s": "а"}, {"s": "а"}, {"s": "б"}, {"s": "а"}])
    assert _numbers(manager, same, {"sort": "s", "dir": "asc"}) == [one.number, two.number, four.number, three.number]
    assert _numbers(manager, same, {"sort": "s", "dir": "desc"}) == [three.number, one.number, two.number, four.number]


def test_column_header_link_toggles_dir_for_current_sort_column():
    """FR-518: ссылка в заголовке текущего столбца меняет направление (`asc` → `desc` → `asc`), текущий столбец
    помечен `data-dir`; у другого столбца пометки нет, его ссылка ведёт на свой `sort`."""
    manager, lst = _env()
    lp.add_field(lst, "string", code="s", show_in_table=True)
    lp.add_field(lst, "number", code="n", show_in_table=True)
    _records(lst, [{"s": "а", "n": "1"}, {"s": "б", "n": "2"}])

    def header(response, code):
        heads = _find(response, "th", data_sort=code)
        assert len(heads) == 1, f"заголовок th[data-sort={code!r}]"
        links = [n for n in _dom(response) if n.tag == "a" and any(a is heads[0] for a in n.ancestors)]
        assert links, f"в заголовке {code!r} нет ссылки"
        # `data-dir` — на `th[data-sort]` текущего столбца (ответ 27, CONTRACT-006, 11.3, 15.3)
        marks = {heads[0].attrs.get("data-dir")} - {None}
        return marks, _qs_of(links[0].attrs["href"])

    marks, link = header(_get(manager, lst, {"sort": "s", "dir": "asc"}), "s")
    assert marks == {"asc"} and link["sort"] == ["s"] and link["dir"] == ["desc"]
    marks, link = header(_get(manager, lst, {"sort": "s", "dir": "desc"}), "s")
    assert marks == {"desc"} and link["sort"] == ["s"] and link["dir"] == ["asc"]
    marks, link = header(_get(manager, lst, {"sort": "s"}), "s")
    assert marks == {"asc"} and link["dir"] == ["desc"]
    marks, link = header(_get(manager, lst, {"sort": "s", "dir": "desc"}), "n")
    assert marks == set() and link["sort"] == ["n"] and link.get("dir") != ["desc"]


# --- чужие коды (FR-518, FR-519, NFR-509) ----------------------------------------------------------------

def _hostile_env():
    """Список, где по номеру, названию, версии и скрытому полю порядок и отбор различаются."""
    manager, lst = _env()
    lp.add_field(lst, "string", code="s")
    lp.add_field(lst, "string", code="hs", hidden=True)
    other = lp.make_list(created_by=manager.user)
    lp.add_field(other, "string", code="ox")
    records = [lp.make_record(lst, title, values, version=version) for title, values, version in (
        ("Я", {"s": "г", "hs": "один"}, 4), ("Ю", {"s": "в", "hs": "два"}, 3),
        ("Э", {"s": "б", "hs": "три"}, 2), ("Ш", {"s": "а", "hs": "четыре"}, 1))]
    return manager, lst, [r.number for r in records]


def test_foreign_codes_in_sort_are_dropped_silently():
    """FR-518, NFR-509: `sort` с чужим кодом (нет в списке, скрытое поле, поле другого списка, имя столбца таблицы,
    выражение) отбрасывается молча: порядок по номеру, 200; верный код сортирует."""
    manager, lst, by_number = _hostile_env()
    assert _numbers(manager, lst) == by_number
    assert _numbers(manager, lst, {"sort": "s", "dir": "asc"}) == by_number[::-1]
    for foreign in ("zzz", "f999", "hs", "ox", "version", "values", "archived_by", "search", "pk",
                    'x" ; DROP TABLE lists_record; --', "s__icontains", "s'"):
        for direction in ("asc", "desc"):
            # `dir` без допустимого `sort` не действует: порядок по `number` по возрастанию (ответ 28, CONTRACT-006,
            # 10.3, 15.3)
            assert _numbers(manager, lst, {"sort": foreign, "dir": direction}) == by_number, foreign
        assert _numbers(manager, lst, {"sort": foreign}) == by_number, foreign


def test_foreign_codes_in_filters_are_dropped_silently():
    """FR-519, NFR-509: фильтры `f.<чужой код>` (нет в списке, скрытое поле, другого списка, столбец таблицы,
    выражение вида `s__icontains`) отбрасываются молча: итог — все записи, 200."""
    manager, lst, by_number = _hostile_env()
    assert _numbers(manager, lst, {"f.s": "в"}) == [by_number[1]]
    assert _numbers(manager, lst, {"f.hs": "два"}) == by_number
    foreign_filters = (
        {"f.zzz": "1"}, {"f.hs": "два"}, {"f.ox": "x"}, {"f.version": "1"}, {"f.id": "1"}, {"f.values": "x"},
        {"f.s__icontains": "яяя"}, {"f.s__regex": "^$"}, {"f.zzz.from": "1"}, {"f.hs.to": "а"},
        {"f.hs.files": "yes"}, {"f.x\"; DROP TABLE lists_record; --": "1"})
    for params in foreign_filters:
        assert _numbers(manager, lst, params) == by_number, params


def test_grid_queryset_sql_has_field_code_only_among_params_not_in_query_text():
    """NFR-509: код поля из схемы попадает в запрос параметром: в тексте SQL (`sql_with_params`) его нет, в
    параметрах есть — для фильтра и для сортировки каждого типа поля."""
    from apps.lists.services import grid

    manager, lst = _env()
    lp.add_field(lst, "string", code="zqtext")
    lp.add_field(lst, "number", code="zqnum")
    lp.add_field(lst, "money", code="zqmoney")
    lp.add_field(lst, "date", code="zqdate")
    lp.add_field(lst, "datetime", code="zqmoment")
    lp.add_field(lst, "bool", code="zqflag")
    lp.add_field(lst, "choice", code="zqpick", choices=("Один", "Два"))
    lp.add_field(lst, "person", code="zqwho")
    lp.make_record(lst, "Запись", {"zqtext": "x", "zqnum": "1", "zqdate": "2025-03-10"})
    pick_id = lp.choice_id(support.model("lists.Field").objects.get(list=lst, code="zqpick"), "Один")
    cases = (
        ("zqtext", {"f.zqtext": ["икс"]}), ("zqnum", {"f.zqnum.from": ["1"], "f.zqnum.to": ["5"]}),
        ("zqmoney", {"f.zqmoney.from": ["1"]}), ("zqdate", {"f.zqdate.from": ["10.03.2025"]}),
        ("zqmoment", {"f.zqmoment.to": ["10.03.2025 12:00"]}), ("zqflag", {"f.zqflag": ["yes"]}),
        ("zqpick", {"f.zqpick": [str(pick_id)]}), ("zqwho", {"f.zqwho": [str(manager.user.pk)]}))
    for code, filters in cases:
        for params in (filters, {"sort": [code], "dir": ["desc"]}):
            query = QueryDict(mutable=True)
            for name, values in params.items():
                query.setlist(name, values)
            gp = grid.read(query, lst, manager.user)
            sql, sql_params = grid.records(lst, manager.user, gp).query.sql_with_params()
            assert code not in sql, f"код поля {code} в тексте SQL ({params})"
            assert code in repr(sql_params), f"кода поля {code} нет среди параметров ({params})"


# --- страницы, число найденного, фрагмент (FR-518) --------------------------------------------------------

def test_page_holds_50_rows_51st_row_marks_next_page_and_page_param_opens_it():
    """FR-518: на странице 50 строк, 51-я запись даёт `a[data-action="next-page"]` с `page=2`, `page=2` открывает
    её; ровно 50 записей — ссылки нет; `page` не число или меньше 1 — первая страница."""
    manager, lst = _env()
    for index in range(1, 52):
        lp.make_record(lst, f"Р{index:02d}", created_by=manager.user)
    first_page = _get(manager, lst)
    assert _numbers_of(first_page) == list(range(1, 51))
    links = _find(first_page, "a", data_action="next-page")
    assert len(links) == 1 and _qs_of(links[0].attrs["href"])["page"] == ["2"]
    second_page = _get(manager, lst, {"page": "2"})
    assert _numbers_of(second_page) == [51]
    assert _find(second_page, "a", data_action="next-page") == []
    for bad in ("0", "-1", "abc", ""):
        assert _numbers(manager, lst, {"page": bad}) == list(range(1, 51)), bad
    support.model("lists.Record").objects.filter(list=lst, number=51).update(title="Ж51")
    exactly_fifty = _get(manager, lst, {"f.title": "Р"})
    assert _numbers_of(exactly_fifty) == list(range(1, 51))
    assert _find(exactly_fifty, "a", data_action="next-page") == []


def test_found_count_equals_count_of_same_filtered_queryset_and_is_always_shown():
    """FR-518: «Найдено: N» есть всегда (в том числе при пустом итоге, на второй странице и в архиве) и равно
    `count()` того же набора, а не числу строк страницы."""
    from apps.lists.services import grid

    manager, lst = _env()
    for index in range(1, 52):
        lp.make_record(lst, f"Альфа {index}", created_by=manager.user)
    lp.make_record(lst, "Бета", created_by=manager.user)
    lp.make_record(lst, "Альфа в архиве", archived=True, created_by=manager.user)
    cases = (({}, 52), ({"page": "2"}, 52), ({"f.title": "альфа"}, 51), ({"f.title": "альфа", "page": "2"}, 51),
             ({"f.title": "нет такого"}, 0), ({"preset": "archive"}, 1), ({"f.title": "бета"}, 1))
    for params, expected in cases:
        response = _get(manager, lst, params)
        assert _found(response) == expected, params
        query = QueryDict(urlencode({k: v for k, v in params.items() if k != "page"}))
        gp = grid.read(query, lst, manager.user)
        assert grid.records(lst, manager.user, gp).count() == expected, params
    assert len(_numbers(manager, lst)) == 50


def test_hx_target_lists_grid_returns_grid_fragment_with_vary_hx_request():
    """FR-518: запрос с `HX-Request` и `HX-Target: lists-grid` — фрагмент сетки без `<html>`, строки по тем же
    фильтрам; полная страница — с `<html>` и контейнером `#lists-grid`; у обоих ответов `Vary: HX-Request`."""
    manager, lst = _env()
    lp.add_field(lst, "string", code="s")
    first, second, third = _records(lst, [{"s": "альфа"}, {"s": "бета"}, {"s": "альфа два"}])
    full = _get(manager, lst, {"f.s": "альфа"})
    fragment = _get(manager, lst, {"f.s": "альфа"}, hx=True)
    for response in (full, fragment):
        assert "hx-request" in response.get("Vary", "").lower().replace(" ", "").split(","), response.get("Vary")
    body = fragment.content.decode().lower()
    assert "<html" not in body and "<body" not in body
    assert _numbers_of(fragment) == [first.number, third.number] == _numbers_of(full)
    assert "<html" in full.content.decode().lower()
    assert _find(full, id="lists-grid"), "на полной странице нет контейнера #lists-grid"
