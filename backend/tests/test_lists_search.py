"""T-6122: сквозной поиск и поиск внутри списка (FR-509, FR-540, FR-541, FR-543, FR-546, NFR-502, NFR-509).
Сценарии 12 и 13 спеки среза 006.

Разбор `ParsedQuery.text`, поставщик группы «Списки» (ключ, порядок 50, права внутри запроса, архив, скрытые поля,
точное совпадение по уникальным полям, словоформы и начало слова, порядок, предел `limit + 1`, точное число), вектор
записи (веса A и C, предел 100 000 знаков, пересчёт при создании, сохранении, архиве, возврате, загрузке, «Скрыть» и
«Показать»), строка поиска внутри списка (`search.parse_local`, подсказки, сочетание с отбором и фильтрами, отбор
«Архив»), текст запроса нигде не сохраняется. Код среза на уровне модуля не импортируется (CONTRACT-006, шапка);
тексты — литералы раздела 12. Гонок здесь нет. Раздел 9 контракта; места V14 и V15 — раздел 6.1.
Даты и часы тестам не нужны: время службы берут из `timezone.now()`.
"""
import dataclasses
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import connection
from django.http import QueryDict

from tests import factories, support
from tests import support_kb as kb
from tests import support_lists as sl
from tests.support_notify import run_jobs

pytestmark = pytest.mark.django_db

HINT_SHORT = "Введите не меньше 2 знаков"
HINT_LONG = "Запрос не длиннее 200 знаков"

_VOID = {"input", "br", "img", "meta", "link", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


# --- разметка (только для этого файла) --------------------------------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {name: (value if value is not None else "") for name, value in attrs},
                 self._stack[-1] if self._stack else None)
        self.elements.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, {name: (value if value is not None else "") for name, value in attrs},
                                 self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.raw += data


def _doc(response) -> _Doc:
    return _Doc(response.content.decode("utf-8"))


def _inside(el, ancestor) -> bool:
    node = el
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _all(doc, tag=None, attrs=None, within=None) -> list:
    """Элементы с тегом `tag` и атрибутами `attrs` (значение `True` — достаточно наличия); `within` — предок."""
    found = []
    for el in doc.elements:
        if tag and el.tag != tag:
            continue
        if any((name not in el.attrs) if value is True else (el.attrs.get(name) != value)
               for name, value in (attrs or {}).items()):
            continue
        if within is not None and not _inside(el, within):
            continue
        found.append(el)
    return found


# --- помощники только этого файла -------------------------------------------------------------------------

def _fresh(user):
    return support.model("core.User").objects.get(pk=user.pk)


def _author():
    return support.make_employee()


def _list(**over):
    return sl.make_list(created_by=_author(), **over)


def _url(lst, record) -> str:
    return f"/lists/{lst.pk}/{record.number}/"


def _parsed(query):
    from apps.search.parse import parse

    return parse(query)


def _provider():
    from apps.lists.services import search

    found = search.search_providers()
    assert len(found) == 1, found
    return found[0]


def _rows(user, query, limit: int = 50, offset: int = 0) -> list:
    return _provider().search(_fresh(user), _parsed(query), limit, offset)


def _urls(user, query, limit: int = 50, offset: int = 0) -> list[str]:
    return [row.url for row in _rows(user, query, limit, offset)]


def _count(user, query) -> tuple:
    return _provider().count(_fresh(user), _parsed(query))


def _group_keys(user) -> list[str]:
    from apps.search import services

    return [provider.key for provider in services.providers(_fresh(user))]


def _grid(client, lst, **params):
    response = client.get(f"/lists/{lst.pk}/", params)
    assert response.status_code == 200, response.status_code
    return _doc(response)


def _numbers(doc) -> list[int]:
    return [int(el.attrs["data-record-number"]) for el in _all(doc, "tr", {"data-record-number": True})]


def _found_number(doc) -> int:
    found = _all(doc, None, {"data-lists-found": True})
    assert found, "нет [data-lists-found]"
    match = re.search(r"Найдено:\s*(\d+)", found[0].text)
    assert match, found[0].text
    return int(match.group(1))


def _hint_texts(doc) -> list[str]:
    return [el.text for el in _all(doc, None, {"data-lists-search-hint": True})]


def _matches(record, word: str) -> bool:
    Record = support.model("lists.Record")
    return Record.objects.filter(pk=record.pk, search=SearchQuery(word, config="russian")).exists()


def _null_vector(record) -> None:
    assert support.model("lists.Record")._meta.db_table == "lists_record"
    with connection.cursor() as cursor:
        cursor.execute("UPDATE lists_record SET search = NULL WHERE id = %s", [record.pk])


def _vector_text(record) -> str:
    return support.model("lists.Record").objects.filter(pk=record.pk).values_list("search", flat=True).get() or ""


def _weights_of(record, word: str) -> set[str]:
    """Веса, с которыми слово `word` (после стемминга `russian`) есть в векторе записи: `search @@ to_tsquery(
    'russian', 'слово:A')` по каждому весу — тем же приёмом `@@ to_tsquery`, что тесты векторов среза 005; лексемы
    вектора — основы слов, поэтому сравнение идёт через базу, а не по тексту вектора."""
    assert support.model("lists.Record")._meta.db_table == "lists_record"
    found = set()
    with connection.cursor() as cursor:
        for mark in "ABCD":
            cursor.execute("SELECT search @@ to_tsquery('russian', %s) FROM lists_record WHERE id = %s",
                           [word + ":" + mark, record.pk])
            if cursor.fetchone()[0]:
                found.add(mark)
    return found


def _refresh(*records) -> None:
    from apps.lists.services import vectors

    vectors.refresh([record.pk for record in records])


# --- ParsedQuery.text (FR-540) -----------------------------------------------------------------------------

def test_parse_fills_text_stripped_of_edge_spaces_and_empty_for_short_and_long_hints():
    """FR-540: `search.parse` заполняет `ParsedQuery.text` — запросом без крайних пробелов, с прежним регистром и
    внутренними пробелами; при подсказке `short` и `long` — пустой строкой; поле последнее, значение по умолчанию —
    пустая строка; остальные поля разбора не меняются."""
    from apps.core.extensions import ParsedQuery

    fields = dataclasses.fields(ParsedQuery)
    assert fields[-1].name == "text" and fields[-1].default == ""
    assert [item.name for item in fields[:4]] == ["words", "number", "raw", "hint"]

    for query, text in (("  Dell  ", "Dell"), ("ИН-100", "ИН-100"), ("  ABC 123  ", "ABC 123"), ("#42", "#42"),
                        (" " + "x" * 200 + " ", "x" * 200)):
        parsed = _parsed(query)
        assert parsed.hint == "" and parsed.text == text, (query, parsed)
    assert _parsed("  Dell  ").words == ["dell"] and _parsed("  Dell  ").raw == "dell:*"
    assert _parsed("#42").number == 42

    for query in ("д", "  д  ", "", None, "a b", "! ?"):
        parsed = _parsed(query)
        assert parsed.hint == "short" and parsed.text == "", (query, parsed)
        assert parsed.words == [] and parsed.raw == ""
    parsed = _parsed("x" * 201)
    assert parsed.hint == "long" and parsed.text == "" and parsed.words == [] and parsed.raw == ""


# --- поставщик в реестре (FR-540, FR-543) -------------------------------------------------------------------

def test_lists_provider_is_registered_with_key_title_order_50_after_units():
    """FR-540, FR-543: в точке `search_providers` одна запись `lists` из модуля `apps.lists`; поставщик с ключом
    `lists`, названием «Списки», порядком 50; в сборщике поиска группа идёт после «Подразделений» (40); `available` —
    сотрудник со списками; без списков — ложно."""
    from apps.core import extensions

    registered = [func for func in extensions.registered("search_providers") if func.__module__.startswith("apps.lists")]
    assert len(registered) == 1
    provider = _provider()
    assert (provider.key, provider.title, provider.order) == ("lists", "Списки", 50)
    assert callable(provider.search) and callable(provider.count) and callable(provider.available)

    lst = _list()
    staff_role = factories.make_role(permissions=("staff.view",))
    reader = sl.as_reader(lst, roles=[staff_role])
    outsider = support.make_employee(roles=[staff_role])
    assert provider.available(_fresh(reader.user))
    assert not provider.available(_fresh(outsider))
    found = _group_keys(reader.user)
    assert "articles" in found and "units" in found and "lists" in found
    assert found.index("articles") < found.index("units") < found.index("lists")
    assert "lists" not in _group_keys(outsider)


# --- строка выдачи (FR-540) ---------------------------------------------------------------------------------

def test_query_dell_finds_row_laptop_dell_dash_equipment_with_card_link():
    """FR-540: запрос «dell» находит запись «Ноутбук Dell» списка «Оборудование»; строка выдачи — название записи,
    название списка, ссылка на карточку; на странице `/search/` строка в группе `lists` читается «Название — Список»
    и ведёт на карточку записи; запись без слова не найдена."""
    sl.clear_seed()
    author = _author()
    lst = sl.make_list("Оборудование", created_by=author)
    sl.add_field(lst, "string", "Инвентарный номер", unique=True)
    sl.add_field(lst, "string", "Модель")
    laptop = sl.make_record(lst, "Ноутбук Dell")
    sl.make_record(lst, "Монитор Samsung")
    reader = sl.as_reader(lst)

    rows = _rows(reader.user, "dell")
    assert [(row.title, row.subtitle, row.url) for row in rows] == [("Ноутбук Dell", "Оборудование", _url(lst, laptop))]

    page = _doc(reader.client.get("/search/", {"q": "dell"}))
    groups = _all(page, "section", {"data-search-group": "lists"})
    assert len(groups) == 1
    assert "Списки" in [el.text for el in _all(page, "h2", {"data-field": "title"}, within=groups[0])][0]
    items = _all(page, "li", {"data-search-row": True}, within=groups[0])
    assert len(items) == 1
    link = _all(page, "a", {"href": _url(lst, laptop)}, within=items[0])
    assert len(link) == 1
    assert [el.text for el in _all(page, "span", {"data-field": "title"}, within=link[0])] == ["Ноутбук Dell"]
    assert [el.text for el in _all(page, "span", {"data-field": "subtitle"}, within=link[0])] == ["Оборудование"]
    assert reader.client.get(_url(lst, laptop)).status_code == 200


# --- слова: словоформы и начало слова (FR-540) --------------------------------------------------------------

def test_word_form_and_word_prefix_find_record_in_string_and_multiline_fields():
    """FR-540: слово запроса находит запись по словоформе и по началу слова — в поле «строка» и в «многострочном
    тексте» (во второй строке текста тоже); слово, которого нет в записи, не находит."""
    lst = _list()
    line = sl.add_field(lst, "string", "Модель")
    text = sl.add_field(lst, "text", "Примечание")
    record = sl.make_record(lst, "Запись", {line.code: "Принтеры лазерные", text.code: "Картриджи закончились\nзаменить барабан"})
    sl.make_record(lst, "Запись", {line.code: "Монитор", text.code: "Без замечаний"})
    reader = sl.as_reader(lst)
    target = [_url(lst, record)]
    for query in ("принтер", "принтеры", "принтера", "прин", "Принт", "лазерные", "барабан", "бараб", "барабана"):
        assert _urls(reader.user, query) == target, query
    for query in ("скрепка", "монитора принтер"):
        assert _urls(reader.user, query) == [], query


# --- точное совпадение с уникальным полем (FR-540) ----------------------------------------------------------

def test_whole_unique_number_with_hyphen_or_inner_space_is_found_by_exact_match_ignoring_case_and_edge_spaces():
    """FR-540: номер вида «ИН-100» и «ABC 123» находится запросом целиком — без учёта регистра и крайних пробелов,
    значением уникального поля целиком; похожий номер («ИН-1000») не находится; число группы совпадает."""
    lst = _list()
    inv = sl.add_field(lst, "string", "Инвентарный номер", unique=True)
    first = sl.make_record(lst, "Запись", {inv.code: "ИН-100"})
    second = sl.make_record(lst, "Запись", {inv.code: "ABC 123"})
    near = sl.make_record(lst, "Запись", {inv.code: "ИН-1000"})
    reader = sl.as_reader(lst)
    for query in ("ИН-100", "ин-100", "  ИН-100  ", "Ин-100"):
        assert _urls(reader.user, query) == [_url(lst, first)], query
        assert _count(reader.user, query) == (1, False), query
    for query in ("ABC 123", "abc 123", "  abc 123 "):
        assert _urls(reader.user, query) == [_url(lst, second)], query
    assert _url(lst, near) not in _urls(reader.user, "ИН-100")
    assert _urls(reader.user, "ин-1000") == [_url(lst, near)]


def test_middle_parts_of_serial_number_are_not_found_but_word_prefix_is():
    """FR-540: серийный номер «5CD1234XYZ» (уникальное поле) находится целиком и началом слова («5cd»), но не
    серединой и не концом («1234», «234», «xyz»)."""
    lst = _list()
    serial = sl.add_field(lst, "string", "Серийный номер", unique=True)
    record = sl.make_record(lst, "Запись", {serial.code: "5CD1234XYZ"})
    reader = sl.as_reader(lst)
    for query in ("5CD1234XYZ", "5cd1234xyz", "5cd", "5CD12"):
        assert _urls(reader.user, query) == [_url(lst, record)], query
    for query in ("1234", "234", "xyz", "34xyz"):
        assert _urls(reader.user, query) == [], query


def test_hyphenated_number_in_non_unique_field_is_found_only_by_word_prefix():
    """FR-540: номер «ИН-100» в неуникальном поле «строка» целиком запросом не находится (точное совпадение — только
    у уникальных полей), находится началом слова «ин»; часть после дефиса («100») не находит."""
    lst = _list()
    plain = sl.add_field(lst, "string", "Заметка")
    record = sl.make_record(lst, "Запись", {plain.code: "ИН-100"})
    reader = sl.as_reader(lst)
    assert _urls(reader.user, "ИН-100") == []
    assert _urls(reader.user, "100") == []
    assert _urls(reader.user, "ин") == [_url(lst, record)]


def test_record_matched_exactly_and_by_tsquery_appears_once_in_results_and_count():
    """FR-540: запись, которую находят и точное совпадение, и `tsquery` («ABC 123» в уникальном поле «строка»),
    одна в выдаче и считается один раз в числе группы; рядом запись, найденная только `tsquery`, считается отдельно."""
    lst = _list()
    inv = sl.add_field(lst, "string", "Инвентарный номер", unique=True)
    note = sl.add_field(lst, "string", "Заметка")
    both = sl.make_record(lst, "Запись", {inv.code: "ABC 123"})
    only_vector = sl.make_record(lst, "Запись", {note.code: "abc 123 в заметке"})
    reader = sl.as_reader(lst)
    urls = _urls(reader.user, "abc 123")
    assert sorted(urls) == sorted([_url(lst, both), _url(lst, only_vector)])
    assert len(urls) == len(set(urls)) == 2
    assert urls[0] == _url(lst, both)
    assert _count(reader.user, "abc 123") == (2, False)
    assert _urls(reader.user, "ABC 123", limit=1)[:1] == [_url(lst, both)]


# --- предел, порядок (FR-540, NFR-502) -----------------------------------------------------------------------

def test_provider_returns_limit_plus_one_rows_and_exact_uncapped_count():
    """FR-540, NFR-502: на 7 совпадений поставщик при `limit=5` отдаёт 6 строк (лишняя — признак «есть ещё»), со
    смещения 5 — 2 строки, дальше — пусто; порции не пересекаются и вместе дают все записи; `count` — `(7, False)`
    (точное число, без потолка)."""
    lst = _list()
    records = [sl.make_record(lst, f"Кабель {n}") for n in range(1, 8)]
    reader = sl.as_reader(lst)
    first = _urls(reader.user, "кабель", limit=5, offset=0)
    second = _urls(reader.user, "кабель", limit=5, offset=5)
    assert len(first) == 6 and len(second) == 2
    assert _urls(reader.user, "кабель", limit=5, offset=7) == []
    assert sorted(first[:5] + second) == sorted(_url(lst, record) for record in records)
    assert _count(reader.user, "кабель") == (7, False)
    assert len(_urls(reader.user, "кабель", limit=7)) == 7


def test_results_order_exact_matches_first_then_rank_then_number():
    """FR-540: сначала точные совпадения (даже у записи с самым большим номером), затем по рангу (слово в названии
    весит больше слова в тексте), при равном ранге — по номеру."""
    lst = _list()
    inv = sl.add_field(lst, "string", "Инвентарный номер", unique=True)
    body = sl.add_field(lst, "text", "Описание")
    in_text_early = sl.make_record(lst, "Запись", {body.code: "рубин в тексте"})
    in_title = sl.make_record(lst, "Рубин камень", {})
    sl.make_record(lst, "Запись", {body.code: "сапфир в тексте"})
    in_text_late = sl.make_record(lst, "Запись", {body.code: "рубин в записи"})
    exact = sl.make_record(lst, "Запись", {inv.code: "рубин"})
    reader = sl.as_reader(lst)
    assert _urls(reader.user, "рубин") == [_url(lst, exact), _url(lst, in_title), _url(lst, in_text_early),
                                           _url(lst, in_text_late)]
    assert _count(reader.user, "рубин") == (4, False)


# --- права, архив, скрытые поля (FR-509, FR-540) --------------------------------------------------------------

def test_archived_record_and_unreadable_list_are_neither_found_nor_counted():
    """FR-540: запись в архиве (и по `tsquery`, и по точному совпадению) и запись списка, который сотрудник не читает,
    не находятся и не считаются; живая запись читаемого списка находится."""
    lst = _list()
    other = _list()
    code = sl.add_field(lst, "string", "Инвентарный номер", unique=True).code
    other_code = sl.add_field(other, "string", "Инвентарный номер", unique=True).code
    live = sl.make_record(lst, "Кабель живой", {code: "ИН-778"})
    sl.make_record(lst, "Кабель архивный", {code: "ИН-777"}, archived=True)
    sl.make_record(other, "Кабель чужого списка", {other_code: "ИН-779"})
    reader = sl.as_reader(lst)
    assert _urls(reader.user, "кабель") == [_url(lst, live)]
    assert _count(reader.user, "кабель") == (1, False)
    assert _urls(reader.user, "ИН-777") == [] and _count(reader.user, "ИН-777") == (0, False)
    assert _urls(reader.user, "ИН-779") == [] and _count(reader.user, "ИН-779") == (0, False)
    assert _urls(reader.user, "ИН-778") == [_url(lst, live)]


def test_hidden_text_field_and_hidden_unique_field_do_not_find_record():
    """FR-509, FR-540 (места V14 и V15): слово только из скрытого текстового поля и значение скрытого уникального
    поля не находят запись; те же слова из видимых полей находят."""
    lst = _list()
    visible_text = sl.add_field(lst, "text", "Видимый текст")
    hidden_text = sl.add_field(lst, "text", "Скрытый текст", hidden=True)
    visible_inv = sl.add_field(lst, "string", "Видимый номер", unique=True)
    hidden_inv = sl.add_field(lst, "string", "Скрытый номер", unique=True, hidden=True)
    from_hidden = sl.make_record(lst, "Запись", {hidden_text.code: "хризантема в скрытом", hidden_inv.code: "ИН-555"})
    from_visible = sl.make_record(lst, "Запись", {visible_text.code: "хризантема в видимом", visible_inv.code: "ИН-556"})
    _refresh(from_hidden, from_visible)
    reader = sl.as_reader(lst)
    assert _urls(reader.user, "хризантема") == [_url(lst, from_visible)]
    assert _urls(reader.user, "ИН-555") == []
    assert _urls(reader.user, "ИН-556") == [_url(lst, from_visible)]
    assert _count(reader.user, "хризантема") == (1, False)
    assert _count(reader.user, "ИН-555") == (0, False)


# --- модуль выключен или нет списков (FR-543) ------------------------------------------------------------------

def test_employee_without_lists_has_no_lists_group_and_same_group_set():
    """FR-540, FR-543: сотрудник без доступа к спискам не видит группы «Списки», а прочие группы у него те же, что у
    читающего (за вычетом `lists`); у читающего группа есть; без `lists` наборы групп обоих совпадают."""
    lst = _list()
    reader = sl.as_reader(lst)
    outsider = support.make_employee()
    with_reader = _group_keys(reader.user)
    with_outsider = _group_keys(outsider)
    assert "lists" in with_reader
    assert "lists" not in with_outsider
    assert [slug for slug in with_reader if slug != "lists"] == with_outsider
    with sl.without_lists():
        assert _group_keys(reader.user) == with_outsider
        assert _group_keys(outsider) == with_outsider


def test_provider_set_without_lists_has_no_lists_group_and_other_groups_return_results():
    """FR-543: при выключенном `lists` группа «Списки» из сборщика и со страницы `/search/` пропадает, группа
    «Статьи» работает и отдаёт строки; с включённым модулем на странице обе группы."""
    lst = _list()
    sl.make_record(lst, "Хризантема в списке")
    kb.make_published(title="Хризантема в статье")
    reader = sl.as_reader(lst)

    def group_slugs():
        page = _doc(reader.client.get("/search/", {"q": "хризантема"}))
        return [el.attrs["data-search-group"] for el in _all(page, "section", {"data-search-group": True})], page

    slugs, page = group_slugs()
    assert "lists" in slugs and "articles" in slugs
    with sl.without_lists():
        assert "lists" not in _group_keys(reader.user) and "articles" in _group_keys(reader.user)
        slugs, page = group_slugs()
        assert "lists" not in slugs and "articles" in slugs
        article_group = _all(page, "section", {"data-search-group": "articles"})[0]
        assert _all(page, "li", {"data-search-row": True}, within=article_group)
    assert "lists" in group_slugs()[0]


# --- текст запроса нигде не сохраняется (FR-540) -----------------------------------------------------------------

def test_query_text_marker_is_absent_in_database_audit_and_app_log(caplog):
    """FR-540 (SPEC-005 FR-446): после запросов ко всем адресам поиска и к таблице списка с `q` метки-слова нет ни в
    одной строке моделей базы, ни в журнале событий (он и не растёт), ни в журнале приложения."""
    from django.apps import apps as registry

    marker = "zqxmarkerlst"
    lst = _list()
    sl.add_field(lst, "string", "Заметка")
    sl.make_record(lst, "Запись", {})
    reader = sl.as_reader(lst)
    Event = support.model("core.AuditEvent")
    before = Event.objects.count()
    caplog.set_level(logging.DEBUG)
    client = reader.client
    pages = [("/search/popup/", {"q": marker}), ("/search/", {"q": marker}),
             ("/search/count/", {"q": marker, "group": "lists"}),
             ("/search/more/", {"q": marker, "group": "lists", "offset": "0"}),
             (f"/lists/{lst.pk}/", {"q": marker}), (f"/lists/{lst.pk}/", {"q": marker, "preset": "archive"})]
    for path, params in pages:
        assert client.get(path, params).status_code == 200, path
    assert client.get(f"/lists/{lst.pk}/", {"q": marker}, headers={"HX-Request": "true", "HX-Target": "lists-grid"}
                      ).status_code == 200
    assert _urls(reader.user, marker) == []
    assert Event.objects.count() == before
    for values in Event.objects.values():
        assert marker not in str(values)
    holders = []
    for model_class in registry.get_models():
        if not model_class._meta.managed:  # без таблицы (`django_rq.Dashboard`) — поправка Opus при исполнении
            continue
        for row in model_class._default_manager.values():
            if marker in str(row):
                holders.append(model_class._meta.label)
                break
    assert holders == [], f"запрос найден в моделях: {holders}"
    for record in caplog.records:
        if record.name.startswith("django.db"):
            continue
        text = " ".join([record.getMessage(), str(record.exc_text or ""), str(record.args),
                         str(record.__dict__.get("request", ""))])
        assert marker not in text, f"запрос в записи логгера {record.name}"


def test_tsquery_special_characters_in_query_do_not_raise():
    """NFR-509, FR-540: запросы со знаками `'`, `&`, `|`, `!`, `:`, `*`, `(` не дают ошибки ни у поставщика, ни на
    странице поиска, ни в таблице списка; запросы, из которых остаются слова, находят запись по этим словам."""
    lst = _list()
    sl.add_field(lst, "string", "Заметка")
    sl.make_record(lst, "dell hp lenovo", {})
    sl.make_record(lst, "ноут бук dell hp", {})
    reader = sl.as_reader(lst)
    queries = ["a'b & c | !d :* (e)", "'", "&", "|", "!", ":", "*", "(", "ноут'бук & (dell | hp)!",
               "dell:* & !hp | (lenovo)", "''", "*:", "o'reilly", "!dell", "ин:100", "ноут*", "(dell"]
    provider = _provider()
    user = _fresh(reader.user)
    for query in queries:
        parsed = _parsed(query)
        rows = provider.search(user, parsed, 20, 0)
        if parsed.hint:
            assert rows == [], query
        else:
            provider.count(user, parsed)
        assert reader.client.get("/search/", {"q": query}).status_code == 200, query
        assert reader.client.get(f"/lists/{lst.pk}/", {"q": query}).status_code == 200, query
    assert len(_urls(reader.user, "dell:* & !hp | (lenovo)")) == 1
    assert len(_urls(reader.user, "ноут'бук & (dell | hp)!")) == 1


# --- поиск внутри списка (FR-541, FR-546) -----------------------------------------------------------------------

def test_parse_local_matches_search_parse_on_query_table():
    """FR-541, NFR-502: `search.parse_local` возвращает ту же запись ядра `ParsedQuery` и на таблице запросов раздела 9
    (подсказки, слова, номер, `raw`, `text`) равен `search.parse`."""
    from apps.core.extensions import ParsedQuery
    from apps.lists.services import search

    queries = ["dell", "  Dell  ", "д", "", "ин-100", "ИН-100", "#42", "42", "5CD1234XYZ",
               "один два три четыре пять шесть семь восемь девять", "x" * 201, "x" * 200, "a'b & c | !d :* (e)"]
    for query in queries:
        local = search.parse_local(query)
        assert isinstance(local, ParsedQuery), query
        assert local == _parsed(query), query
    assert search.parse_local("  Dell  ").text == "Dell"
    assert search.parse_local("x" * 201).hint == "long"
    assert search.parse_local("д").hint == "short"


def test_single_character_local_query_shows_enter_at_least_two_chars():
    """FR-541, FR-546: запрос из одного знака в таблице списка показывает подсказку «Введите не меньше 2 знаков» в
    `[data-lists-search-hint]`, условие поиска не применяется (видны все записи); у годного запроса подсказки нет;
    строка поиска — `form[data-lists-search]` с полем `q`."""
    lst = _list()
    sl.add_field(lst, "string", "Заметка")
    records = [sl.make_record(lst, f"Запись {n}") for n in range(1, 4)]
    reader = sl.as_reader(lst)
    page = _grid(reader.client, lst, q="д")
    assert HINT_SHORT in _hint_texts(page)
    assert _numbers(page) == [record.number for record in records]
    assert _found_number(page) == 3
    forms = _all(page, "form", {"data-lists-search": True})
    assert len(forms) == 1 and _all(page, "input", {"name": "q"}, within=forms[0])
    assert [t for t in _hint_texts(_grid(reader.client, lst, q="запись")) if t.strip()] == []
    assert [t for t in _hint_texts(_grid(reader.client, lst)) if t.strip()] == []


def test_local_query_longer_than_200_chars_shows_hint():
    """FR-541: запрос длиннее 200 знаков показывает подсказку «Запрос не длиннее 200 знаков», условие поиска не
    применяется; запрос из 200 знаков подсказки не даёт и условие применяется (записей нет)."""
    lst = _list()
    sl.make_record(lst, "Запись один")
    sl.make_record(lst, "Запись два")
    reader = sl.as_reader(lst)
    long_page = _grid(reader.client, lst, q="а" * 201)
    assert HINT_LONG in _hint_texts(long_page)
    assert _found_number(long_page) == 2 and len(_numbers(long_page)) == 2
    edge = _grid(reader.client, lst, q="а" * 200)
    assert [t for t in _hint_texts(edge) if t.strip()] == []
    assert _numbers(edge) == [] and _found_number(edge) == 0


def test_local_nine_word_query_finds_record_matching_first_eight_words():
    """FR-541: в запросе из девяти слов учитываются первые восемь: запись с первыми восемью словами находится, запись
    только с девятым и запись без восьмого слова — нет."""
    from apps.lists.services import search

    words = ["ромашка", "тюльпан", "роза", "пион", "лилия", "астра", "гвоздика", "сирень", "орхидея"]
    lst = _list()
    body = sl.add_field(lst, "text", "Описание")
    first_eight = sl.make_record(lst, "Запись", {body.code: " ".join(words[:8])})
    sl.make_record(lst, "Запись", {body.code: words[8]})
    sl.make_record(lst, "Запись", {body.code: " ".join(words[:7] + words[8:])})
    reader = sl.as_reader(lst)
    assert search.parse_local(" ".join(words)).words == words[:8]
    page = _grid(reader.client, lst, q=" ".join(words))
    assert _numbers(page) == [first_eight.number]
    assert _found_number(page) == 1


def test_local_query_combines_with_preset_and_state_in_repair_filter():
    """FR-541: поиск сочетается по «и» с отбором «Закреплено за мной» и фильтром по значению «В ремонте»: из четырёх
    записей остаётся одна — со словом, моя и в ремонте; страница и `grid.records` дают одно и то же."""
    from apps.lists.services import grid

    lst = _list()
    state = sl.add_field(lst, "choice", "Состояние", choices=("В работе", "В ремонте"))
    assignee = sl.add_field(lst, "person", "За кем закреплено")
    reader = sl.as_reader(lst)
    other = support.make_employee()
    repair, working = sl.choice_id(state, "В ремонте"), sl.choice_id(state, "В работе")
    target = sl.make_record(lst, "Принтер мой", {assignee.code: [reader.user.pk], state.code: [repair]})
    sl.make_record(lst, "Принтер чужой", {assignee.code: [other.pk], state.code: [repair]})
    sl.make_record(lst, "Принтер мой в работе", {assignee.code: [reader.user.pk], state.code: [working]})
    sl.make_record(lst, "Монитор мой", {assignee.code: [reader.user.pk], state.code: [repair]})
    params = {"q": "принтер", "preset": "mine", f"f.{state.code}": str(repair)}
    page = _grid(reader.client, lst, **params)
    assert _numbers(page) == [target.number] and _found_number(page) == 1
    user = _fresh(reader.user)
    queryset = grid.records(lst, user, grid.read(QueryDict(urlencode(params)), lst, user))
    assert [record.number for record in queryset] == [target.number]
    assert len(_numbers(_grid(reader.client, lst, q="принтер", preset="mine"))) == 2


def test_local_query_with_archive_preset_searches_archived_records():
    """FR-541: при отборе «Архив» поиск идёт по записям архива (по вектору и по точному совпадению с уникальным
    полем), а при отборе «Все» — по живым записям."""
    lst = _list()
    inv = sl.add_field(lst, "string", "Инвентарный номер", unique=True)
    body = sl.add_field(lst, "text", "Описание")
    live = sl.make_record(lst, "Запись", {body.code: "договор подписан", inv.code: "ИН-901"})
    old = sl.make_record(lst, "Запись", {body.code: "договор расторгнут", inv.code: "ИН-900"}, archived=True)
    reader = sl.as_reader(lst)
    assert _numbers(_grid(reader.client, lst, q="договор", preset="archive")) == [old.number]
    assert _numbers(_grid(reader.client, lst, q="договор", preset="all")) == [live.number]
    assert _numbers(_grid(reader.client, lst, q="ИН-900", preset="archive")) == [old.number]
    assert _numbers(_grid(reader.client, lst, q="ИН-900", preset="all")) == []
    assert _numbers(_grid(reader.client, lst, preset="archive")) == [old.number]


# --- вектор записи (FR-509, FR-540, FR-541) ----------------------------------------------------------------------

def test_vector_has_title_weight_a_and_visible_text_fields_weight_c_capped_at_100000_chars():
    """FR-540: `vectors.refresh` строит вектор: название — вес A, значения видимых полей «строка» и «многострочный
    текст» — вес C; скрытое поле, число и иные типы в вектор не входят; текст длиннее 100 000 знаков обрезается."""
    lst = _list()
    line = sl.add_field(lst, "string", "Строка")
    text = sl.add_field(lst, "text", "Текст")
    hidden = sl.add_field(lst, "string", "Скрытое", hidden=True)
    number = sl.add_field(lst, "number", "Число")
    record = sl.make_record(lst, "Titlefox", {line.code: "Stringfox", text.code: "Textfox\nsecondline",
                                              hidden.code: "Hiddenfox", number.code: "12345"})
    _null_vector(record)
    assert _vector_text(record) == ""
    _refresh(record)
    assert _weights_of(record, "titlefox") == {"A"}
    for word in ("stringfox", "textfox", "secondline"):
        assert _weights_of(record, word) == {"C"}, word
    assert _weights_of(record, "hiddenfox") == set() and _weights_of(record, "12345") == set()

    big_list = _list()
    big = sl.add_field(big_list, "text", "Большой текст")
    long_record = sl.make_record(big_list, "Короткое", {big.code: "начало " + "слово " * 20000 + "завершение"})
    _null_vector(long_record)
    _refresh(long_record)
    assert _weights_of(long_record, "начало") == {"C"} and _weights_of(long_record, "слово") == {"C"}
    assert _weights_of(long_record, "завершение") == set(), "текст после 100 000 знаков попал в вектор"
    assert _weights_of(long_record, "короткое") == {"A"}


def test_vector_is_refreshed_on_create_save_archive_restore_import_hide_and_show(
        django_capture_on_commit_callbacks):
    """FR-540, FR-541, FR-509: настоящая служба пересчитывает вектор при создании, сохранении, переносе в архив,
    возврате, загрузке из таблицы, «Скрыть» и «Показать» (две последние — заданием `refresh_vectors` после
    фиксации); перед каждым действием вектор обнулён."""
    from apps.lists.services import archive, imports, records, schema

    manager = sl.as_manager()
    actor = manager.user
    lst = sl.make_list(created_by=actor)
    line = sl.add_field(lst, "string", "Строка")

    created = records.create(lst, {"title": "Астероид", line.code: "хризантема"}, actor)
    assert _matches(created, "астероид") and _matches(created, "хризантема")

    _null_vector(created)
    records.save(lst, created.number, {"title": "Метеорит", line.code: "гладиолус"}, base_version=created.version,
                 actor=actor)
    assert _matches(created, "метеорит") and _matches(created, "гладиолус") and not _matches(created, "хризантема")

    _null_vector(created)
    archive.archive(lst, created.number, actor=actor)
    assert _matches(created, "метеорит") and _matches(created, "гладиолус")

    _null_vector(created)
    archive.restore(lst, created.number, actor=actor)
    assert _matches(created, "метеорит") and _matches(created, "гладиолус")

    content = sl.csv_of(["Название", "Цветок"], [["Импорт один", "фиалка"]])
    job = imports.upload(lst, actor, name="цветы.csv", content=content)
    imports.preview(job, {"0": "title", "1": line.code}, actor)
    summary = imports.confirm(lst, job.pk, actor)
    assert summary["created"] == 1
    imported = support.model("lists.Record").objects.get(list=lst, title="Импорт один")
    assert _matches(imported, "фиалка") and _matches(imported, "импорт")

    with django_capture_on_commit_callbacks(execute=True):
        schema.hide_field(line, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        run_jobs("maintenance")
    assert not _matches(created, "гладиолус") and not _matches(imported, "фиалка")
    assert _matches(created, "метеорит") and _matches(imported, "импорт")

    _null_vector(created)
    _null_vector(imported)
    with django_capture_on_commit_callbacks(execute=True):
        schema.show_field(line, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        run_jobs("maintenance")
    assert _matches(created, "гладиолус") and _matches(created, "метеорит")
    assert _matches(imported, "фиалка") and _matches(imported, "импорт")
