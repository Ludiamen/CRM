"""T-6112: таблица записей — отборы, столбцы, групповые действия, пустая таблица, значения фильтра (FR-509, FR-514,
FR-518, FR-519, FR-520, FR-521, FR-523, FR-539, FR-546). Сценарии 1, 5, 6, 7 спеки 006.
Время — фикстурой `clock`, замки — по SQL (решение 6 задач), тексты — литералы раздела 12 контракта (решение 25)."""
import importlib
from datetime import date, timedelta, timezone
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_lists as ls

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}
HX_GRID = {"HX-Request": "true", "HX-Target": "lists-grid"}
# 11.03.2026 12:00 по Москве; сегодня по Москве — 11 марта
NOON = ls.moscow(2026, 3, 11, 12, 0)
TODAY = date(2026, 3, 11)
# 11.03.2026 00:30 по Москве = 10.03.2026 21:30 UTC: дата по UTC ещё 10 марта, по Москве уже 11 марта
LATE_UTC = ls.moscow(2026, 3, 11, 0, 30)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (свой, без чужих файлов) -------------------------------------------------------------

class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def text(self) -> str:
        parts = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return " ".join("".join(parts).split())

    def descendants(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.descendants()

    def inside(self, **attrs) -> bool:
        """Есть ли среди предков узел с атрибутами."""
        node = self.parent
        while node is not None:
            if _matches(node, None, attrs):
                return True
            node = node.parent
        return False


def _matches(node, tag, attrs) -> bool:
    if tag is not None and node.tag != tag:
        return False
    for name, want in attrs.items():
        name = name.replace("_", "-")
        if name not in node.attrs:
            return False
        if want is not True and node.attrs[name] != want:
            return False
    return True


class _Dom(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", {}, None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {name: (value or "") for name, value in attrs}, self.current)
        self.current.children.append(node)
        if tag not in _VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {name: (value or "") for name, value in attrs}, self.current)
        self.current.children.append(node)

    def handle_endtag(self, tag):
        node = self.current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def _dom(response_or_body) -> Node:
    body = response_or_body if isinstance(response_or_body, str) else response_or_body.content.decode()
    parser = _Dom()
    parser.feed(body)
    return parser.root


def _find(root, tag=None, **attrs) -> list:
    return [node for node in root.descendants() if _matches(node, tag, attrs)]


# --- помощники файла ------------------------------------------------------------------------------------

def _grid_service():
    return importlib.import_module("apps.lists.services.grid")


def _archive_service():
    return importlib.import_module("apps.lists.services.archive")


def _errors():
    return importlib.import_module("apps.lists.services.errors")


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _get(client, lst, headers=None, **params):
    return client.get(f"/lists/{lst.pk}/", params, headers=headers or {})


def _numbers(response) -> set[int]:
    """Номера записей в строках таблицы."""
    assert response.status_code == 200
    return {int(row.attrs["data-record-number"]) for row in _find(_dom(response), "tr", data_record_number=True)}


def _grid_numbers(client, lst, **params) -> set[int]:
    return _numbers(_get(client, lst, **params))


def _preset_links(response) -> dict:
    """Ссылки отборов: код отбора -> узел ссылки."""
    found = {}
    for block in _find(_dom(response), data_lists_presets=True):
        for link in _find(block, "a", data_preset=True):
            found[link.attrs["data-preset"]] = link
    return found


def _shown_columns(response) -> list[str]:
    """Коды столбцов первой строки таблицы, кроме системного «Названия», в порядке показа."""
    rows = _find(_dom(response), "tr", data_record_number=True)
    assert rows, "в таблице нет строк"
    return [cell.attrs["data-col"] for cell in _find(rows[0], "td", data_col=True) if cell.attrs["data-col"] != "title"]


def _post_bulk(client, lst, numbers, headers=None):
    return client.post(f"/lists/{lst.pk}/bulk-archive/", {"n": list(numbers)}, headers=headers or {})


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _events(action):
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _purge_row(record) -> None:
    """Запись удалена навсегда: строки нет, номер меньше `next_number`."""
    support.model("lists.Record").objects.filter(pk=record.pk).delete()


def _readable_by(session, lst) -> None:
    ls.grant_list(lst, session.user.roles.get(), "read")


# --- отборы (FR-520) ------------------------------------------------------------------------------------

def test_default_preset_all_shows_only_records_not_in_archive():
    """FR-520: без `preset`, с `preset=all` и с чужим значением — «Все»: записи не в архиве; текущий отбор отмечен
    `aria-current`, «Найдено» считает те же записи."""
    lst = ls.make_list()
    session = ls.as_reader(lst)
    first = ls.make_record(lst, "Первая", created_by=session.user)
    second = ls.make_record(lst, "Вторая", created_by=session.user)
    old = ls.make_record(lst, "Старая", archived=True, created_by=session.user)
    for params in ({}, {"preset": "all"}, {"preset": "nonsense"}):
        response = _get(session.client, lst, **params)
        assert _numbers(response) == {first.number, second.number}, params
        assert old.number not in _numbers(response)
        links = _preset_links(response)
        assert links["all"].attrs.get("aria-current") == "page"
        assert all(link.attrs.get("aria-current") != "page" for code, link in links.items() if code != "all")
        found = _find(_dom(response), data_lists_found=True)
        assert found and "Найдено: 2" in found[0].text()


def test_preset_archive_shows_only_archived_records():
    """FR-520: `preset=archive` — только записи в архиве; ссылка «Архив» отмечена текущей."""
    lst = ls.make_list()
    session = ls.as_reader(lst)
    live = ls.make_record(lst, "Живая", created_by=session.user)
    gone_one = ls.make_record(lst, "Архивная 1", archived=True, created_by=session.user)
    gone_two = ls.make_record(lst, "Архивная 2", archived=True, created_by=session.user)
    response = _get(session.client, lst, preset="archive")
    assert _numbers(response) == {gone_one.number, gone_two.number}
    assert live.number not in _numbers(response)
    assert _preset_links(response)["archive"].attrs.get("aria-current") == "page"


def test_preset_expiring_uses_largest_threshold_of_deadline_field(clock):
    """FR-520: «Истекает» — срок поля в ближайшие N дней, где N — наибольший порог поля (здесь 14, а не 30 и не 7),
    или уже прошёл; запись без значения не входит."""
    lst = ls.make_list()
    due = ls.add_field(lst, "date", "Гарантия до", deadline=True, thresholds=(3, 14, 7))
    session = ls.as_reader(lst)
    clock.set(NOON)
    days = {"today": 0, "in14": 14, "in15": 15, "in30": 30, "past": -3}
    made = {name: ls.make_record(lst, name, {due.code: _iso(shift)}, created_by=session.user)
            for name, shift in days.items()}
    empty = ls.make_record(lst, "без срока", created_by=session.user)
    numbers = _grid_numbers(session.client, lst, preset="expiring")
    assert numbers == {made["today"].number, made["in14"].number, made["past"].number}
    assert empty.number not in numbers
    assert _preset_links(_get(session.client, lst, preset="expiring"))["expiring"].attrs.get("aria-current") == "page"


def test_preset_expiring_without_thresholds_uses_30_days_includes_overdue_and_excludes_archived(clock):
    """FR-520: у поля-срока без порогов N = 30; просроченные входят; запись в архиве не входит."""
    lst = ls.make_list()
    due = ls.add_field(lst, "date", "Действует до", deadline=True)
    session = ls.as_reader(lst)
    clock.set(NOON)
    in30 = ls.make_record(lst, "через 30", {due.code: _iso(30)}, created_by=session.user)
    in31 = ls.make_record(lst, "через 31", {due.code: _iso(31)}, created_by=session.user)
    past = ls.make_record(lst, "вчера", {due.code: _iso(-1)}, created_by=session.user)
    old = ls.make_record(lst, "в архиве", {due.code: _iso(0)}, archived=True, created_by=session.user)
    numbers = _grid_numbers(session.client, lst, preset="expiring")
    assert numbers == {in30.number, past.number}
    assert in31.number not in numbers and old.number not in numbers


def test_preset_expiring_joins_visible_deadline_fields_with_or_and_ignores_hidden_ones(clock):
    """FR-520, FR-509: поля-сроки соединяются по «или», у каждого свой наибольший порог; скрытое поле-срок
    в отборе не учитывается."""
    lst = ls.make_list()
    first = ls.add_field(lst, "date", "Первый срок", deadline=True, thresholds=(10,))
    second = ls.add_field(lst, "date", "Второй срок", deadline=True, thresholds=(20,))
    hidden = ls.add_field(lst, "date", "Скрытый срок", deadline=True, thresholds=(30,), hidden=True)
    session = ls.as_reader(lst)
    clock.set(NOON)

    by_first = ls.make_record(lst, "по первому", {first.code: _iso(5)}, created_by=session.user)
    by_second = ls.make_record(lst, "по второму", {second.code: _iso(18)}, created_by=session.user)
    first_out = ls.make_record(lst, "первый вне", {first.code: _iso(15)}, created_by=session.user)
    second_out = ls.make_record(lst, "второй вне", {second.code: _iso(25)}, created_by=session.user)
    either = ls.make_record(lst, "по второму при первом вне",
                            {first.code: _iso(30), second.code: _iso(3)}, created_by=session.user)
    only_hidden = ls.make_record(lst, "только скрытое", {hidden.code: _iso(1)}, created_by=session.user)
    numbers = _grid_numbers(session.client, lst, preset="expiring")
    assert numbers == {by_first.number, by_second.number, either.number}
    assert not {first_out.number, second_out.number, only_hidden.number} & numbers


def test_preset_expiring_counts_from_moscow_today_when_clock_is_at_utc_midnight(clock):
    """FR-520: «сегодня» — по Москве. Часы на 10.03.2026 21:30 UTC (в Москве уже 11.03 00:30): граница при 30
    днях — 10.04.2026, а не 09.04 (по дате UTC). Контракт называет «полночь UTC», но в 00:00 UTC даты UTC и Москвы
    совпадают, поэтому взят момент, где они различаются (вопрос к Opus в отчёте)."""
    lst = ls.make_list()
    due = ls.add_field(lst, "date", "Срок", deadline=True)
    session = ls.as_reader(lst)
    clock.set(LATE_UTC)
    assert LATE_UTC.astimezone(timezone.utc).date() == date(2026, 3, 10)
    boundary = ls.make_record(lst, "граница", {due.code: "2026-04-10"}, created_by=session.user)
    beyond = ls.make_record(lst, "за границей", {due.code: "2026-04-11"}, created_by=session.user)
    numbers = _grid_numbers(session.client, lst, preset="expiring")
    assert boundary.number in numbers
    assert beyond.number not in numbers


def test_preset_mine_matches_any_visible_person_field_and_excludes_archived_and_hidden_fields():
    """FR-520, FR-509: «Закреплено за мной» — любое видимое поле «сотрудник» содержит самого сотрудника;
    записи в архиве и скрытые поля не учитываются."""
    lst = ls.make_list()
    first = ls.add_field(lst, "person", "Ответственный")
    second = ls.add_field(lst, "person", "Дублёр", multiple=True)
    hidden = ls.add_field(lst, "person", "Прежний", hidden=True)
    session = ls.as_reader(lst)
    other = support.make_employee()
    me = session.user.pk
    by_first = ls.make_record(lst, "по первому", {first.code: [me]}, created_by=other)
    by_second = ls.make_record(lst, "по второму", {second.code: [other.pk, me]}, created_by=other)
    only_hidden = ls.make_record(lst, "по скрытому", {hidden.code: [me]}, created_by=other)
    archived = ls.make_record(lst, "в архиве", {first.code: [me]}, archived=True, created_by=other)
    foreign = ls.make_record(lst, "чужая", {first.code: [other.pk]}, created_by=other)
    numbers = _grid_numbers(session.client, lst, preset="mine")
    assert numbers == {by_first.number, by_second.number}
    assert not {only_hidden.number, archived.number, foreign.number} & numbers
    assert _preset_links(_get(session.client, lst, preset="mine"))["mine"].attrs.get("aria-current") == "page"


def test_presets_expiring_and_mine_are_offered_only_with_visible_deadline_or_person_field():
    """FR-520, FR-509: ссылки «Истекает» и «Закреплено за мной» есть, только если у списка есть видимое поле-срок
    и видимое поле «сотрудник»; «Все» и «Архив» есть всегда; недоступный отбор в адресе равен «Все»."""
    lst = ls.make_list()
    ls.add_field(lst, "string", "Серийный номер")
    session = ls.as_reader(lst)
    record = ls.make_record(lst, "Запись", created_by=session.user)
    assert set(_preset_links(_get(session.client, lst))) == {"all", "archive"}
    for name in ("expiring", "mine"):
        response = _get(session.client, lst, preset=name)
        assert _numbers(response) == {record.number}
        assert _preset_links(response)["all"].attrs.get("aria-current") == "page"
    due = ls.add_field(lst, "date", "Срок", deadline=True, hidden=True)
    who = ls.add_field(lst, "person", "Ответственный", hidden=True)
    assert set(_preset_links(_get(session.client, lst))) == {"all", "archive"}
    support.model("lists.Field").objects.filter(pk__in=[due.pk, who.pk]).update(hidden=False)
    assert set(_preset_links(_get(session.client, lst))) == {"all", "expiring", "mine", "archive"}
    only_due = ls.make_list()
    ls.add_field(only_due, "date", "Срок", deadline=True)
    reader = ls.as_reader(only_due)
    assert set(_preset_links(_get(reader.client, only_due))) == {"all", "expiring", "archive"}
    plain_date = ls.make_list()
    ls.add_field(plain_date, "date", "Дата без срока")
    plain_reader = ls.as_reader(plain_date)
    assert "expiring" not in _preset_links(_get(plain_reader.client, plain_date))


def test_preset_filters_and_search_combine_with_and_and_archive_preset_searches_archive():
    """FR-520: отбор, фильтры и поиск сочетаются по «и»; при отборе «Архив» поиск идёт по записям архива."""
    lst = ls.make_list()
    serial = ls.add_field(lst, "string", "Серийный номер")
    session = ls.as_reader(lst)
    author = session.user
    laptop_dell = ls.make_record(lst, "Ноутбук Dell", {serial.code: "AB-1"}, created_by=author)
    laptop_hp = ls.make_record(lst, "Ноутбук HP", {serial.code: "AB-2"}, created_by=author)
    printer_dell = ls.make_record(lst, "Принтер Dell", {serial.code: "CD-3"}, created_by=author)
    old_dell = ls.make_record(lst, "Ноутбук Dell старый", {serial.code: "AB-4"}, archived=True, created_by=author)
    old_hp = ls.make_record(lst, "Сервер HP старый", {serial.code: "EF-5"}, archived=True, created_by=author)
    assert _grid_numbers(session.client, lst, q="dell") == {laptop_dell.number, printer_dell.number}
    both = {"q": "dell", "f.title": "ноутбук"}
    assert _grid_numbers(session.client, lst, **both) == {laptop_dell.number}
    assert _grid_numbers(session.client, lst, **{"f." + serial.code: "ab-", "q": "dell"}) == {laptop_dell.number}
    assert _grid_numbers(session.client, lst, preset="archive", q="dell") == {old_dell.number}
    assert _grid_numbers(session.client, lst, preset="archive", q="hp") == {old_hp.number}
    assert _grid_numbers(session.client, lst, preset="archive", **{"f.title": "ноутбук"}) == {old_dell.number}
    assert _grid_numbers(session.client, lst, preset="archive", q="принтер") == set()
    assert laptop_hp.number in _grid_numbers(session.client, lst, **{"f." + serial.code: "ab-"})


# --- столбцы (FR-518) -----------------------------------------------------------------------------------

def _columns_world():
    lst = ls.make_list()
    shown_first = ls.add_field(lst, "string", "Серийный номер", show_in_table=True)
    not_shown = ls.add_field(lst, "string", "Примечание")
    hidden_shown = ls.add_field(lst, "string", "Скрытое", show_in_table=True, hidden=True)
    shown_last = ls.add_field(lst, "number", "Количество", show_in_table=True)
    return lst, shown_first, not_shown, hidden_shown, shown_last


def test_default_columns_are_title_and_visible_fields_shown_in_table():
    """FR-518: по умолчанию — «Название» и видимые поля с «показывать в таблице» по порядку; скрытое и не
    отмеченное поле столбцами не становятся."""
    lst, shown_first, not_shown, hidden_shown, shown_last = _columns_world()
    session = ls.as_reader(lst)
    ls.make_record(lst, "Запись", {shown_first.code: "SN-1", not_shown.code: "заметка", shown_last.code: "3"},
                   created_by=session.user)
    assert _grid_service().columns(lst, session.user) == ["title", shown_first.code, shown_last.code]
    response = _get(session.client, lst)
    assert _shown_columns(response) == [shown_first.code, shown_last.code]
    assert _find(_dom(response), "a", data_field="title")


def test_columns_post_saves_choice_for_this_employee_and_list_only():
    """FR-518: выбор столбцов запоминается за сотрудником для этого списка: другой сотрудник и другой список своих
    столбцов не меняют; обычный POST — 302 на таблицу, НХ — фрагмент сетки; повторный POST обновляет ту же строку."""
    lst, shown_first, not_shown, _hidden, shown_last = _columns_world()
    session = ls.as_reader(lst)
    colleague = ls.as_reader(lst)
    other = ls.make_list()
    other_field = ls.add_field(other, "string", "Иное", show_in_table=True)
    _readable_by(session, other)
    ls.make_record(lst, "Запись", {shown_first.code: "SN-1", not_shown.code: "заметка", shown_last.code: "3"},
                   created_by=session.user)
    ls.make_record(other, "Иная запись", {other_field.code: "x"}, created_by=session.user)
    response = session.client.post(f"/lists/{lst.pk}/columns/",
                                   {"columns": [shown_last.code, "title", not_shown.code]})
    assert response.status_code == 302
    assert response["Location"] == f"/lists/{lst.pk}/"
    mine = _grid_service().columns(lst, session.user)
    assert sorted(mine) == sorted(["title", shown_last.code, not_shown.code])
    assert [code for code in mine if code != "title"] == [shown_last.code, not_shown.code]
    assert _shown_columns(_get(session.client, lst)) == [shown_last.code, not_shown.code]
    assert _grid_service().columns(lst, colleague.user) == ["title", shown_first.code, shown_last.code]
    assert _shown_columns(_get(colleague.client, lst)) == [shown_first.code, shown_last.code]
    assert _grid_service().columns(other, session.user) == ["title", other_field.code]
    views = support.model("lists.UserView").objects
    assert views.filter(user=session.user, list=lst).count() == 1
    assert views.filter(user=colleague.user).count() == 0 and views.filter(list=other).count() == 0
    again = session.client.post(f"/lists/{lst.pk}/columns/", {"columns": [shown_first.code]}, headers=HX_GRID)
    body = again.content.decode()
    assert again.status_code == 200 and "<html" not in body.lower()
    assert _find(_dom(body), id="lists-grid")
    assert views.filter(user=session.user, list=lst).count() == 1
    assert [code for code in _grid_service().columns(lst, session.user) if code != "title"] == [shown_first.code]


def test_saved_columns_drop_hidden_and_deleted_codes_on_read():
    """FR-518, FR-509: сохранённые столбцы при чтении теряют коды скрытых и удалённых полей; остальные остаются
    в сохранённом порядке; страница не показывает столбец скрытого поля."""
    lst = ls.make_list()
    first = ls.add_field(lst, "string", "Первое")
    second = ls.add_field(lst, "string", "Второе")
    hidden = ls.add_field(lst, "string", "Скрытое", hidden=True)
    doomed = ls.add_field(lst, "string", "Удалённое", code="gone")
    session = ls.as_reader(lst)
    ls.make_record(lst, "Запись", {first.code: "а", second.code: "б", hidden.code: "в"}, created_by=session.user)
    support.model("lists.UserView").objects.create(
        user=session.user, list=lst, columns=[first.code, hidden.code, doomed.code, "title", second.code])
    support.model("lists.Field").objects.filter(pk=doomed.pk).delete()
    assert _grid_service().columns(lst, session.user) == [first.code, "title", second.code]
    response = _get(session.client, lst)
    assert _shown_columns(response) == [first.code, second.code]
    assert hidden.code not in {cell.attrs["data-col"] for cell in _find(_dom(response), "td", data_col=True)}


def test_hidden_field_is_absent_from_column_and_filter_choices():
    """FR-509, FR-518: скрытое поле не предлагается ни в выборе столбцов, ни среди фильтров; после «Показать»
    предлагается."""
    lst = ls.make_list()
    visible = ls.add_field(lst, "string", "Видимое")
    hidden = ls.add_field(lst, "string", "Скрытое", hidden=True, show_in_table=True)
    session = ls.as_reader(lst)
    ls.make_record(lst, "Запись", {visible.code: "а", hidden.code: "б"}, created_by=session.user)

    def offered():
        doc = _dom(_get(session.client, lst))
        columns = {node.attrs["data-lists-column-choice"] for node in _find(doc, "input", data_lists_column_choice=True)}
        filters = {node.attrs["data-lists-filter"] for node in _find(doc, data_lists_filter=True)}
        return columns, filters

    columns, filters = offered()
    assert visible.code in columns and visible.code in filters
    assert hidden.code not in columns and hidden.code not in filters
    support.model("lists.Field").objects.filter(pk=hidden.pk).update(hidden=False)
    columns, filters = offered()
    assert hidden.code in columns and hidden.code in filters


# --- групповые действия (FR-521, FR-523, FR-539) --------------------------------------------------------

def test_bulk_archive_archives_only_checked_numbers_and_reports_archived_and_skipped_counts():
    """FR-521, FR-523: «В архив» переносит только отмеченные номера; пропущены уже в архиве и удалённые навсегда;
    итог «В архив: N, пропущено: M» в `[data-lists-notice="bulk-result"]`; служба возвращает те же числа."""
    lst = ls.make_list()
    session = ls.as_editor(lst)
    author = session.user
    checked_one = ls.make_record(lst, "Один", created_by=author)
    checked_two = ls.make_record(lst, "Два", created_by=author)
    already = ls.make_record(lst, "Уже в архиве", archived=True, created_by=author)
    purged = ls.make_record(lst, "Удалена навсегда", created_by=author)
    untouched_one = ls.make_record(lst, "Не отмечена 1", created_by=author)
    untouched_two = ls.make_record(lst, "Не отмечена 2", created_by=author)
    _purge_row(purged)
    response = _post_bulk(session.client, lst, [checked_one.number, checked_two.number, already.number, purged.number])
    assert response.status_code == 200
    notices = _find(_dom(response), data_lists_notice="bulk-result")
    assert len(notices) == 1 and "В архив: 2, пропущено: 2" in notices[0].text()
    for record in (checked_one, checked_two):
        fresh = _fresh(record)
        assert fresh.archived is True and fresh.archived_at is not None and fresh.archived_by_id == author.pk
    for record in (untouched_one, untouched_two):
        fresh = _fresh(record)
        assert fresh.archived is False and fresh.archived_at is None and fresh.archived_by_id is None
    assert {n for n in _numbers(_get(session.client, lst))} == {untouched_one.number, untouched_two.number}
    archived_kinds = support.model("lists.Change").objects.filter(kind="archived")
    assert set(archived_kinds.values_list("record_id", flat=True)) == {checked_one.pk, checked_two.pk}
    # служба: те же числа, пропуск не меняет записи
    other = ls.make_list()
    # служба перепроверяет право «правит» (решение Opus 2026-10-25, П3): автору выдаётся «правит» и на `other`
    ls.grant_list(other, author.roles.get(), "edit")
    live = ls.make_record(other, "Живая", created_by=author)
    in_archive = ls.make_record(other, "В архиве", archived=True, created_by=author)
    deleted = ls.make_record(other, "Удалена", created_by=author)
    _purge_row(deleted)
    result = _archive_service().bulk_archive(other, [live.number, in_archive.number, deleted.number], actor=author)
    assert (result.archived, result.skipped) == (1, 2)
    assert _fresh(live).archived is True


def test_bulk_archive_of_over_50_numbers_is_refused_whole_with_not_more_than_50_text():
    """FR-521, FR-546: 51 номер — отказ всего запроса «Не больше 50 записей за раз» (`bulk_too_many`), ничего не
    изменено, в журнале нет `lists.record_archived`; ровно 50 номеров проходят."""
    lst = ls.make_list()
    session = ls.as_editor(lst)
    records = [ls.make_record(lst, f"Запись {n}", created_by=session.user) for n in range(1, 52)]
    numbers = [record.number for record in records]
    response = _post_bulk(session.client, lst, numbers)
    assert response.status_code == 200
    alerts = _find(_dom(response), role="alert", data_code="bulk_too_many")
    assert len(alerts) == 1 and "Не больше 50 записей за раз" in alerts[0].text()
    assert not _find(_dom(response), data_lists_notice="bulk-result")
    support_records = support.model("lists.Record").objects
    assert support_records.filter(list=lst, archived=True).count() == 0
    assert _events("lists.record_archived") == []
    with pytest.raises(_errors().ListsError) as caught:
        _archive_service().bulk_archive(lst, numbers, actor=session.user)
    assert caught.value.code == "bulk_too_many"
    assert support_records.filter(list=lst, archived=True).count() == 0
    assert _events("lists.record_archived") == []
    ok = _post_bulk(session.client, lst, numbers[:50])
    assert ok.status_code == 200
    notice = _find(_dom(ok), data_lists_notice="bulk-result")
    assert notice and "В архив: 50, пропущено: 0" in notice[0].text()
    assert support_records.filter(list=lst, archived=True).count() == 50
    assert _fresh(records[50]).archived is False


def test_bulk_archive_takes_list_lock_then_record_lock_and_writes_journal_for_each_record():
    """FR-521, FR-523: на каждую запись — своя транзакция: разделяемый замок списка, затем `SELECT … FOR UPDATE`
    записи; журнал `lists.record_archived` на каждую запись (номер и название, без значений полей)."""
    lst = ls.make_list()
    field = ls.add_field(lst, "string", "Заметка")
    session = ls.as_editor(lst)
    marker = "значение-поля-не-для-журнала"
    records = [ls.make_record(lst, f"Название {n}", {field.code: marker}, created_by=session.user) for n in range(3)]
    sqls = ls.sql_of(_archive_service().bulk_archive, lst, [record.number for record in records],
                     actor=session.user)
    sequence = []
    for sql in sqls:
        if ls.list_locks([sql]):
            sequence.append(("lock", ls.list_locks([sql])))
        elif sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql.upper() and '"lists_record"' in sql:
            sequence.append(("record", None))
    assert [kind for kind, _ in sequence] == ["lock", "record"] * 3
    for kind, locks in sequence:
        if kind == "lock":
            assert locks == [ls.ListLock("shared", ls.list_no(lst.pk))]
    events = _events("lists.record_archived")
    assert [event.object_id for event in events] == [str(record.pk) for record in records]
    for event, record in zip(events, records):
        assert event.object_type == "lists.record" and event.actor_id == session.user.pk
        # ключи `record_archived` — только в `after` (CONTRACT-006, 8.1, К-12; решение Opus Р4)
        assert not event.before
        assert event.after["list"] == lst.name
        assert str(event.after["number"]) == str(record.number) and event.after["title"] == record.title
        assert marker not in str(event.before) + str(event.after)


def test_bulk_archive_button_is_absent_for_reader_and_post_gives_403():
    """FR-521, FR-523, FR-514: читающему кнопки «В архив» нет, правящему есть; POST читающего — 403 (и на НХ), записи
    не тронуты, журнал пуст."""
    lst = ls.make_list()
    reader = ls.as_reader(lst)
    editor = ls.as_editor(lst)
    record = ls.make_record(lst, "Запись", created_by=editor.user)
    assert not _find(_dom(_get(reader.client, lst)), "button", data_action="bulk-archive")
    assert _find(_dom(_get(editor.client, lst)), "button", data_action="bulk-archive")
    assert _post_bulk(reader.client, lst, [record.number]).status_code == 403
    assert _post_bulk(reader.client, lst, [record.number], headers=HX_GRID).status_code == 403
    assert _fresh(record).archived is False
    assert _events("lists.record_archived") == []
    assert support.model("lists.Change").objects.filter(record=record, kind="archived").count() == 0


def test_labels_action_is_offered_to_reader_and_leads_to_labels_page_with_checked_numbers():
    """FR-521, FR-539: читающему предлагаются флажки строк и действие «Этикетки»; страница
    `/lists/<id>/labels/?n=…` печатает этикетки только отмеченных номеров."""
    lst = ls.make_list()
    reader = ls.as_reader(lst)
    records = [ls.make_record(lst, f"Запись {n}", created_by=reader.user) for n in range(1, 4)]
    doc = _dom(_get(reader.client, lst))
    assert _find(doc, "button", data_action="bulk-labels")
    checks = _find(doc, "input", type="checkbox", name="n", data_lists_row_check=True)
    assert {int(node.attrs["value"]) for node in checks} == {record.number for record in records}
    response = reader.client.get(f"/lists/{lst.pk}/labels/", {"n": [records[0].number, records[2].number]})
    assert response.status_code == 200
    page = _dom(response)
    assert _find(page, data_lists_page="labels")
    labels = _find(page, data_lists_label=True)
    assert len(labels) == 2
    titles = {node.text() for label in labels for node in _find(label, data_field="title")}
    assert any("Запись 1" in text for text in titles) and any("Запись 3" in text for text in titles)
    assert not any("Запись 2" in text for text in titles)


# --- пустая таблица и разметка (FR-518, FR-521, FR-546) -------------------------------------------------

def test_empty_list_shows_no_records_text_and_add_and_import_buttons_to_editor():
    """FR-518, FR-546: пустой список — «В списке пока нет записей» и кнопки «Добавить запись» и «Загрузить из таблицы»
    правящему."""
    lst = ls.make_list()
    session = ls.as_editor(lst)
    doc = _dom(_get(session.client, lst))
    empty = _find(doc, data_empty_state="lists-grid")
    assert len(empty) == 1 and "В списке пока нет записей" in empty[0].text()
    add = _find(doc, "a", data_action="record-add")
    assert add and add[0].attrs["href"] == f"/lists/{lst.pk}/add/"
    load = _find(doc, "a", data_action="import")
    assert load and load[0].attrs["href"] == f"/lists/{lst.pk}/import/"


def test_empty_list_shows_no_add_and_import_buttons_to_reader():
    """FR-518: пустой список читающему — пояснение без кнопок «Добавить запись» и «Загрузить из таблицы»."""
    lst = ls.make_list()
    session = ls.as_reader(lst)
    doc = _dom(_get(session.client, lst))
    empty = _find(doc, data_empty_state="lists-grid")
    assert len(empty) == 1 and "В списке пока нет записей" in empty[0].text()
    assert not _find(doc, "a", data_action="record-add")
    assert not _find(doc, "a", data_action="import")


def test_grid_markup_has_narrow_cards_container_and_lists_grid_class():
    """FR-521: контейнер таблицы — `#lists-grid` с классом `lists-grid` и `data-narrow="cards"`; строки записей
    внутри него."""
    lst = ls.make_list()
    session = ls.as_reader(lst)
    records = [ls.make_record(lst, f"Запись {n}", created_by=session.user) for n in range(2)]
    containers = _find(_dom(_get(session.client, lst)), id="lists-grid")
    assert len(containers) == 1
    grid = containers[0]
    assert "lists-grid" in grid.attrs.get("class", "").split()
    assert grid.attrs.get("data-narrow") == "cards"
    rows = _find(grid, "tr", data_record_number=True)
    assert {int(row.attrs["data-record-number"]) for row in rows} == {record.number for record in records}


def test_grid_row_title_links_to_record_card_address_of_that_record():
    """FR-518: название в строке — ссылка на карточку именно этой записи `/lists/<id>/<n>/`; адрес открывается."""
    lst = ls.make_list()
    session = ls.as_reader(lst)
    records = [ls.make_record(lst, f"Запись номер {n}", created_by=session.user) for n in range(3)]
    rows = {int(row.attrs["data-record-number"]): row
            for row in _find(_dom(_get(session.client, lst)), "tr", data_record_number=True)}
    assert set(rows) == {record.number for record in records}
    for record in records:
        links = _find(rows[record.number], "a", data_field="title")
        assert len(links) == 1
        assert links[0].attrs["href"] == f"/lists/{lst.pk}/{record.number}/"
        assert record.title in links[0].text()
    assert session.client.get(f"/lists/{lst.pk}/{records[1].number}/").status_code == 200


# --- значения фильтра и скрытие несуществующего (FR-514, FR-519) ----------------------------------------

def _pick_ids(response) -> set[int]:
    assert response.status_code == 200
    doc = _dom(response)
    assert _find(doc, "ul", data_lists_pick=True)
    return {int(node.attrs["data-pick-id"]) for node in _find(doc, "li", data_pick_id=True)}


def test_filter_values_offer_only_values_visible_to_employee():
    """FR-519, FR-514: значения для выбора в фильтре — только то, что сотрудник вправе видеть: записи читаемого
    целевого списка (не другого списка), значения списка значений; целевой список, который сотрудник не читает, — 404."""
    target = ls.make_list("Оборудование Ф")
    foreign = ls.make_list("Чужие записи")
    closed = ls.make_list("Закрытый")
    lst = ls.make_list()
    link = ls.add_field(lst, "record", "Устройство", target=target)
    closed_link = ls.add_field(lst, "record", "Закрытое", target=closed)
    state = ls.add_field(lst, "choice", "Состояние", choices=("В работе", "В ремонте"))
    session = ls.as_reader(lst)
    _readable_by(session, target)
    author = session.user
    first = ls.make_record(target, "Ноутбук", created_by=author)
    second = ls.make_record(target, "Монитор", created_by=author)
    alien = ls.make_record(foreign, "Принтер", created_by=author)
    hidden_one = ls.make_record(closed, "Сейф", created_by=author)
    ids = _pick_ids(session.client.get(f"/lists/{lst.pk}/filter-values/{link.code}/"))
    assert {first.pk, second.pk} <= ids
    assert alien.pk not in ids and hidden_one.pk not in ids
    page = _dom(session.client.get(f"/lists/{lst.pk}/filter-values/{link.code}/"))
    texts = {node.text() for node in _find(page, "li", data_pick_id=True)}
    assert any("Ноутбук" in text and f"№{first.number}" in text for text in texts)
    assert session.client.get(f"/lists/{lst.pk}/filter-values/{closed_link.code}/").status_code == 404
    choice_ids = _pick_ids(session.client.get(f"/lists/{lst.pk}/filter-values/{state.code}/"))
    assert {ls.choice_id(state, "В работе"), ls.choice_id(state, "В ремонте")} <= choice_ids
    # `q` — подстрока строки показа без учёта регистра; до 20 строк (CONTRACT-006, 10.2, К-15)
    narrowed = _pick_ids(session.client.get(f"/lists/{lst.pk}/filter-values/{link.code}/", {"q": "НОУТ"}))
    assert first.pk in narrowed and second.pk not in narrowed
    narrowed_choice = _pick_ids(session.client.get(f"/lists/{lst.pk}/filter-values/{state.code}/", {"q": "ремонт"}))
    assert ls.choice_id(state, "В ремонте") in narrowed_choice and ls.choice_id(state, "В работе") not in narrowed_choice
    for index in range(22):
        ls.make_record(target, f"Кабель {index}", created_by=author)
    capped = _pick_ids(session.client.get(f"/lists/{lst.pk}/filter-values/{link.code}/", {"q": "абель"}))
    assert len(capped) == 20


def test_filter_values_give_404_to_non_reader_and_for_hidden_field():
    """FR-514, FR-509: у сотрудника без чтения списка и у скрытого поля адрес значений фильтра отвечает 404, как у
    несуществующего; у поля не ссылочного типа — тоже 404."""
    lst = ls.make_list()
    state = ls.add_field(lst, "choice", "Состояние", choices=("Новое",))
    hidden = ls.add_field(lst, "choice", "Прежнее", choices=("Старое",), hidden=True)
    plain = ls.add_field(lst, "string", "Заметка")
    person_field = ls.add_field(lst, "person", "Ответственный")
    unit_field = ls.add_field(lst, "unit", "Место")
    reader = ls.as_reader(lst)
    outsider = support.logged_in(support.make_employee())
    path = f"/lists/{lst.pk}/filter-values/"
    assert reader.client.get(f"{path}{state.code}/").status_code == 200
    # `person` и `unit` — ссылочные виды: фрагмент значений, а не 404 (CONTRACT-006, 10.2)
    _pick_ids(reader.client.get(f"{path}{person_field.code}/"))
    _pick_ids(reader.client.get(f"{path}{unit_field.code}/"))
    assert outsider.get(f"{path}{person_field.code}/").status_code == 404
    assert outsider.get(f"{path}{state.code}/").status_code == 404
    assert reader.client.get(f"{path}{hidden.code}/").status_code == 404
    assert reader.client.get(f"{path}{plain.code}/").status_code == 404
    assert reader.client.get(f"{path}f999/").status_code == 404
    assert support.same_failure(outsider.get(f"{path}{state.code}/"), outsider.get(f"{path}f999/"))


def test_grid_and_bulk_archive_of_unreadable_list_give_same_404_as_missing_list():
    """FR-514: таблица и групповое «В архив» списка, который сотрудник не читает, отвечают так же, как для
    несуществующего списка (статус 404, тот же вид ответа); запись не тронута."""
    closed = ls.make_list()
    record = ls.make_record(closed, "Закрытая запись")
    other = ls.make_list()
    outsider = support.logged_in(support.make_employee())
    stranger = ls.as_reader(other)
    missing = closed.pk + 100000
    for client in (outsider, stranger.client):
        unreadable = client.get(f"/lists/{closed.pk}/")
        absent = client.get(f"/lists/{missing}/")
        assert unreadable.status_code == 404 and absent.status_code == 404
        assert support.same_failure(unreadable, absent)
        post_unreadable = client.post(f"/lists/{closed.pk}/bulk-archive/", {"n": [record.number]})
        post_absent = client.post(f"/lists/{missing}/bulk-archive/", {"n": [1]})
        assert post_unreadable.status_code == 404 and post_absent.status_code == 404
        assert support.same_failure(post_unreadable, post_absent)
    assert _fresh(record).archived is False
