"""T-5128: адреса поиска и строка в шапке (FR-439, FR-440, FR-442, FR-443, FR-444, FR-445, FR-446).

Сценарий 10 спеки среза 005 («Сквозной поиск»). Адреса — `/search/popup/`, `/search/`, `/search/count/`,
`/search/more/` (CONTRACT-005, 10.1, 10.6); зацепки — 11.1 и 11.9; службы `apps.search.services` — 9.2; запись
`TopBarItem` — 3.2 и 11.9; тексты — 12.1 и 12.2. Поставщики в тестах поиска — свои, собранные тут же и
зарегистрированные в точке `search_providers` (на время теста точка очищается помощником `support_kb`): так тест видит
число вызовов, `limit`, `offset` и сам ставит числа строк. Это не подмена чужой функции, а обычная регистрация записи
`SearchProvider` (раздел 3.1, тест T-5126 делает так же). Настоящие поставщики идут только в тестах «запрос не
хранится». Код среза на уровне модуля не импортируется: имена берутся внутри тестов (шапка контракта).
"""
import contextlib
import logging
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

import pytest

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

QUERY = "сеть"                 # слово запроса: сервер разбирает его в raw «сеть:*»
QUERY_RAW = "сеть:*"
MARKER = "маркерпоиска"        # метка-слово для проверок «запрос нигде не хранится» (FR-446)
POPUP = "/search/popup/"
PAGE = "/search/"
COUNT = "/search/count/"
MORE = "/search/more/"
SEARCH_PATHS = (POPUP, PAGE, COUNT, MORE)
SHORT_HINT = "Введите не меньше 2 знаков"   # дословно спека; CONTRACT-005, п. 17.25
LONG_HINT = "Запрос не длиннее 200 знаков"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

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

    def inside(self, **attrs) -> bool:
        """Есть ли среди предков узел с такими атрибутами (`_` в имени — дефис)."""
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        node = self.parent
        while node is not None:
            if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
                return True
            node = node.parent
        return False


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


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _html(response) -> str:
    return response.content.decode("utf-8")


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; `_` в имени атрибута — дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [node for node in scope.walk()
            if (tag is None or node.tag == tag)
            and all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items())]


def _sections(root) -> list:
    return _q(root, "section", data_search_group=True)


def _slugs(root) -> list[str]:
    return [node.attrs["data-search-group"] for node in _sections(root)]


def _section(root, slug):
    found = _q(root, "section", data_search_group=slug)
    assert len(found) == 1, f"группы {slug!r} в разметке {len(found)}, а нужна одна"
    return found[0]


def _rows(section) -> list:
    return [node for node in section.walk() if node.tag == "li" and "data-search-row" in node.attrs]


def _row_title(row) -> str:
    found = _q(row, data_field="title")
    assert found, "в строке выдачи нет [data-field=title]"
    return found[0].text()


def _row_titles(section) -> list[str]:
    return [_row_title(row) for row in _rows(section)]


def _heading(section) -> str:
    """Заголовок группы: [data-field=title] не внутри строки."""
    found = [node for node in _q(section, data_field="title") if not node.inside(data_search_row=True)]
    assert found, "у группы нет заголовка [data-field=title]"
    return found[0].text()


def _more_button(scope):
    found = _q(scope, "button", data_action="more")
    assert len(found) <= 1, "кнопок «Показать ещё» больше одной"
    return found[0] if found else None


def _hx(url: str):
    """Путь и параметры адреса из `hx-get`."""
    parts = urlsplit(url)
    return parts.path, parse_qs(parts.query)


# --- свои поставщики -------------------------------------------------------------------------------------

class _Log:
    """Вызовы поставщика: `search` — (limit, offset, raw), `count` — raw."""

    def __init__(self):
        self.search = []
        self.count = []


def _fake(slug, title, order, total=0, *, available=True, count=None, fail_search=None, fail_count=None):
    """Поставщик, у которого `total` строк «<slug>-row-NN»; возвращает (запись, журнал вызовов)."""
    from apps.core.extensions import SearchProvider, SearchRow

    log = _Log()
    rows = [SearchRow(title=f"{slug}-row-{i:02d}", subtitle=f"Рубрика {slug}", url=f"/x/{slug}/{i}/") for i in range(total)]

    def search(user, parsed, limit, offset):
        log.search.append((limit, offset, parsed.raw))
        if fail_search is not None:
            raise fail_search
        return rows[offset:offset + limit + 1]   # п. 17.49: поставщик выбирает limit + 1 строк

    def counter(user, parsed):
        log.count.append(parsed.raw)
        if fail_count is not None:
            raise fail_count
        return count if count is not None else (total, False)

    provider = SearchProvider(key=slug, title=title, order=order, search=search, count=counter,
                              available=lambda user: available)
    return provider, log


@contextlib.contextmanager
def _only(*providers):
    """На время блока в точке `search_providers` стоят только эти поставщики (в порядке перечисления)."""
    from apps.core import extensions

    with kb.without_registrations("search_providers"):
        for provider in providers:
            extensions.register("search_providers", lambda p=provider: [p])
        yield


def _get(client, path, **params):
    return client.get(path, params)


# --- строка в шапке (FR-439) ----------------------------------------------------------------------------

def test_top_bar_has_search_item_order_5_before_bell():
    """FR-439: в точке `top_bar_items` есть запись `search` (порядок 5, шаблон `search/_bar.html`, пустой контекст),
    она стоит левее колокольчика (порядок 10), и на странице строка поиска идёт в разметке раньше колокольчика."""
    from django.test import RequestFactory

    from apps.core import extensions

    items = []
    for func in extensions.registered("top_bar_items"):
        items.extend(func())
    by_slug = {item.key: item for item in items}
    assert "search" in by_slug, "в `top_bar_items` нет записи `search`"
    item = by_slug["search"]
    assert item.order == 5
    assert item.template == "search/_bar.html"
    assert item.context(RequestFactory().get("/")) == {}
    assert by_slug["notify-bell"].order == 10
    ordered = [i.key for i in sorted(items, key=lambda i: i.order)]
    assert ordered.index("search") < ordered.index("notify-bell")
    html = _html(kb.as_reader().client.get("/"))
    assert "data-search-bar" in html and 'id="notify-bell"' in html
    assert html.index("data-search-bar") < html.index('id="notify-bell"')


def test_search_input_has_maxlength_200_and_htmx_attributes():
    """FR-439, FR-440: в `[data-search-bar]` поле `input[type=search][name=q]` с `maxlength=200` и атрибутами HTMX
    (адрес окна, пауза 300 мс, `hx-sync`), рядом `[data-search-popup]`; строка вне `#notify-bell`, без запрещённых
    атрибутов; других полей и выбора области в строке нет."""
    root = _tree(kb.as_reader().client.get("/"))
    bars = _q(root, data_search_bar=True)
    assert len(bars) == 1
    bar = bars[0]
    assert not bar.inside(id="notify-bell")
    inputs = _q(bar, "input", type="search", name="q")
    assert len(inputs) == 1
    field = inputs[0]
    assert field.attrs["maxlength"] == "200"
    assert field.attrs["hx-get"] == "/search/popup/"
    assert field.attrs["hx-trigger"] == "input changed delay:300ms, search"
    assert field.attrs["hx-sync"] == "this:replace"
    popups = _q(bar, data_search_popup=True)
    assert len(popups) == 1
    target = field.attrs.get("hx-target", "")
    assert target, "у поля нет hx-target"
    if target.startswith("#"):
        assert popups[0].attrs.get("id") == target[1:]
    else:
        assert "data-search-popup" in target
    for node in [bar, *bar.walk()]:
        for forbidden in ("role", "data-error", "data-warning", "ws-connect", "hx-ext"):
            assert forbidden not in node.attrs, f"в строке поиска запрещённый атрибут {forbidden}"


def test_search_bar_present_on_any_page_for_logged_in_user():
    """FR-439: у вошедшего строка поиска есть на каждой странице портала: главная, профиль, база знаний, страница
    результатов (с короткой и обычной строкой запроса)."""
    client = kb.as_reader().client
    for path in ("/", "/me/", "/kb/", "/search/?q=" + quote(QUERY), "/search/?q=" + quote("а")):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(_q(_tree(response), data_search_bar=True)) == 1, f"нет строки поиска на {path}"


def test_search_bar_absent_for_anonymous():
    """FR-439: строка поиска — только для вошедших: на странице входа у анонима её нет, а у вошедшего на главной есть."""
    anonymous = support.make_client()
    response = anonymous.get("/login/")
    assert response.status_code == 200
    assert "data-search-bar" not in _html(response)
    assert "data-search-popup" not in _html(response)
    assert len(_q(_tree(kb.as_reader().client.get("/")), data_search_bar=True)) == 1


# --- всплывающая выдача (FR-440) ------------------------------------------------------------------------

def test_popup_shows_at_most_five_rows_per_group():
    """FR-440: в окне не больше 5 строк в группе (поставщику уходит limit=5, offset=0), группы идут по порядку,
    строка — со ссылкой, заголовком и подзаголовком."""
    from apps.search import services

    assert services.POPUP_LIMIT == 5 and services.PAGE_LIMIT == 20
    many, many_log = _fake("many", "Много", 10, 8)
    few, few_log = _fake("few", "Мало", 20, 3)
    session = kb.as_reader()
    with _only(many, few):
        response = _get(session.client, POPUP, q=QUERY)
    assert response.status_code == 200
    root = _tree(response)
    assert _slugs(root) == ["many", "few"]
    assert _row_titles(_section(root, "many")) == [f"many-row-{i:02d}" for i in range(5)]
    assert _row_titles(_section(root, "few")) == [f"few-row-{i:02d}" for i in range(3)]
    assert many_log.search == [(5, 0, QUERY_RAW)]
    assert few_log.search == [(5, 0, QUERY_RAW)]
    row = _rows(_section(root, "many"))[0]
    assert [a.attrs["href"] for a in _q(row, "a", href=True)][0] == "/x/many/0/"
    assert _q(row, data_field="subtitle")[0].text() == "Рубрика many"


def test_popup_has_no_counts_and_has_all_results_link():
    """FR-440: в окне чисел нет (счёт не вызывается, зацепок числа нет), внизу `a[data-action=search-all]`
    «Все результаты» ведёт на `/search/?q=<запрос>`."""
    provider, log = _fake("many", "Много", 10, 7)
    query = QUERY + " vpn"
    session = kb.as_reader()
    with _only(provider):
        response = _get(session.client, POPUP, q=query)
    assert response.status_code == 200
    root = _tree(response)
    assert log.count == []
    assert not _q(root, data_search_count=True) and not _q(root, data_search_count_value=True)
    assert not [n for n in root.walk() if "data-count" in n.attrs]
    links = _q(root, "a", data_action="search-all")
    assert len(links) == 1
    assert "Все результаты" in links[0].text()
    path, params = _hx(links[0].attrs["href"])
    assert path == "/search/" and params["q"] == [query]


def test_popup_hides_empty_groups_and_groups_without_access():
    """FR-440, FR-444: группа без строк и группа, недоступная пользователю, в окне не показываются и не отличаются
    от несуществующей (название не выводится, поиск недоступной группы не вызывается)."""
    shown, shown_log = _fake("shown", "Группа с ответом", 10, 3)
    empty, empty_log = _fake("empty", "Пустая группа", 20, 0)
    closed, closed_log = _fake("closed", "Закрытая группа", 30, 4, available=False)
    session = kb.as_reader()
    with _only(shown, empty, closed):
        response = _get(session.client, POPUP, q=QUERY)
    assert response.status_code == 200
    root = _tree(response)
    assert _slugs(root) == ["shown"]
    html = _html(response)
    assert "Пустая группа" not in html and "Закрытая группа" not in html
    assert "closed-row" not in html
    assert closed_log.search == []
    assert len(shown_log.search) == 1


def test_popup_short_query_is_empty_without_hint():
    """FR-440, FR-443: на короткий запрос окно пустое и подсказки в нём нет (решение 45 задач): 200, групп и строк нет,
    ни «Все результаты», ни текста подсказки, поставщики не вызываются."""
    provider, log = _fake("many", "Много", 10, 6)
    session = kb.as_reader()
    with _only(provider):
        for query in ("", " ", "а", "5", "а б", " ф "):
            response = _get(session.client, POPUP, q=query)
            assert response.status_code == 200, repr(query)
            root = _tree(response)
            html = _html(response)
            assert _sections(root) == [] and _q(root, "li") == [], repr(query)
            assert not _q(root, data_search_hint=True) and not _q(root, "a", data_action="search-all"), repr(query)
            assert SHORT_HINT not in html and LONG_HINT not in html, repr(query)
    assert log.search == [] and log.count == []


def test_popup_has_no_area_selector():
    """FR-440: выбора области «Искать в» нет ни в строке поиска, ни в окне выдачи: в строке одно поле `q`,
    ни `select`, ни переключателей."""
    provider, log = _fake("many", "Много", 10, 3)
    session = kb.as_reader()
    root = _tree(session.client.get("/"))
    bars = _q(root, data_search_bar=True)
    assert len(bars) == 1
    assert [n.attrs.get("name") for n in _q(bars[0], "input")] == ["q"]
    assert not _q(bars[0], "select") and "Искать в" not in bars[0].text()
    with _only(provider):
        popup = _get(session.client, POPUP, q=QUERY)
    popup_root = _tree(popup)
    assert not _q(popup_root, "select") and not _q(popup_root, "input")
    assert "Искать в" not in _html(popup)


# --- страница результатов (FR-442, FR-443) --------------------------------------------------------------

def test_results_page_twenty_rows_per_group_and_show_more_button():
    """FR-442: страница показывает по 20 строк в группе (limit=20, offset=0); у большой группы кнопка «Показать ещё»
    со следующим смещением 20 и адресом `/search/more/`, у малой кнопки нет; число группы подгружается отдельным
    запросом `/search/count/` (на странице счёт не вызывается)."""
    big, big_log = _fake("big", "Большая", 10, 45)
    small, small_log = _fake("small", "Малая", 20, 12)
    exact, exact_log = _fake("exact", "Ровная", 30, 20)     # п. 17.49: ровно 20 строк — кнопки нет
    session = kb.as_reader()
    with _only(big, small, exact):
        response = _get(session.client, PAGE, q=QUERY)
    assert response.status_code == 200
    root = _tree(response)
    assert len(_q(root, data_search_page=True)) == 1
    assert _slugs(root) == ["big", "small", "exact"]
    big_section, small_section = _section(root, "big"), _section(root, "small")
    exact_section = _section(root, "exact")
    assert _row_titles(big_section) == [f"big-row-{i:02d}" for i in range(20)]
    assert len(_rows(small_section)) == 12
    assert _row_titles(exact_section) == [f"exact-row-{i:02d}" for i in range(20)]
    assert big_log.search == [(20, 0, QUERY_RAW)] and small_log.search == [(20, 0, QUERY_RAW)]
    assert exact_log.search == [(20, 0, QUERY_RAW)]
    assert big_log.count == [] and small_log.count == [] and exact_log.count == []
    button = _more_button(big_section)
    assert button is not None and button.attrs["data-next-offset"] == "20"
    assert button.attrs["hx-target"] == "this" and button.attrs["hx-swap"] == "outerHTML"
    path, params = _hx(button.attrs["hx-get"])
    assert path == "/search/more/" and params["q"] == [QUERY] and params["group"] == ["big"] and params["offset"] == ["20"]
    assert _more_button(small_section) is None and _more_button(exact_section) is None
    for slug in ("big", "small", "exact"):
        holders = _q(_section(root, slug), data_search_count=True)
        assert len(holders) == 1 and holders[0].attrs["hx-trigger"] == "load"
        path, params = _hx(holders[0].attrs["hx-get"])
        assert path == "/search/count/" and params["q"] == [QUERY] and params["group"] == [slug]


def test_results_page_short_query_shows_hint_and_calls_no_provider():
    """FR-442, FR-443: короткий запрос («а», «5», «а б», пустой) — подсказка `[data-search-hint=short]`
    «Введите не меньше 2 знаков», групп нет, поставщики не вызываются."""
    provider, log = _fake("many", "Много", 10, 6)
    session = kb.as_reader()
    with _only(provider):
        for query in ("а", "5", "а б", " ", ""):
            response = _get(session.client, PAGE, q=query)
            assert response.status_code == 200, repr(query)
            root = _tree(response)
            hints = _q(root, data_search_hint="short")
            assert len(hints) == 1, repr(query)
            assert SHORT_HINT in hints[0].text(), repr(query)
            assert _sections(root) == [] and not _q(root, data_search_hint="long"), repr(query)
    assert log.search == [] and log.count == []


def test_results_page_long_query_shows_hint_and_calls_no_provider():
    """FR-442, FR-443: запрос длиннее 200 знаков — подсказка `[data-search-hint=long]` «Запрос не длиннее 200 знаков»,
    поставщики не вызываются; ровно 200 знаков принимается (поиск идёт, подсказки нет)."""
    provider, log = _fake("many", "Много", 10, 6)
    session = kb.as_reader()
    with _only(provider):
        response = _get(session.client, PAGE, q="а" * 201)
        assert response.status_code == 200
        root = _tree(response)
        hints = _q(root, data_search_hint="long")
        assert len(hints) == 1 and LONG_HINT in hints[0].text()
        assert _sections(root) == [] and not _q(root, data_search_hint="short")
        assert log.search == [] and log.count == []
        accepted = _get(session.client, PAGE, q="а" * 200)
    assert accepted.status_code == 200
    accepted_root = _tree(accepted)
    assert not _q(accepted_root, data_search_hint=True)
    assert _slugs(accepted_root) == ["many"]
    assert len(log.search) == 1


def test_results_page_nothing_found_text():
    """FR-442: если строк нет ни в одной группе — `[data-empty-state=search]` «Ничего не найдено», групп и подсказок
    нет; когда строки есть, этого блока нет."""
    empty, _ = _fake("empty", "Пустая группа", 10, 0)
    other, _ = _fake("other", "Другая пустая", 20, 0)
    session = kb.as_reader()
    with _only(empty, other):
        response = _get(session.client, PAGE, q=QUERY)
    assert response.status_code == 200
    root = _tree(response)
    states = _q(root, data_empty_state="search")
    assert len(states) == 1 and "Ничего не найдено" in states[0].text()
    assert _sections(root) == [] and not _q(root, data_search_hint=True)
    full, _ = _fake("full", "С ответом", 10, 2)
    with _only(full):
        found = _tree(_get(session.client, PAGE, q=QUERY))
    assert not _q(found, data_empty_state="search") and _slugs(found) == ["full"]


def test_results_page_group_titles_in_provider_order():
    """FR-442, FR-445: группы идут по `order` поставщика, а не по порядку регистрации (при равном `order` — по порядку
    регистрации), у каждой в заголовке её название; так в окне и на странице."""
    third, _ = _fake("third", "Третья группа", 30, 2)
    first, _ = _fake("first", "Первая группа", 10, 2)
    second, _ = _fake("second", "Вторая группа", 20, 2)
    tie_a, _ = _fake("tie_a", "Ничья А", 40, 1)
    tie_b, _ = _fake("tie_b", "Ничья Б", 40, 1)
    titles = {"first": "Первая группа", "second": "Вторая группа", "third": "Третья группа",
              "tie_a": "Ничья А", "tie_b": "Ничья Б"}
    session = kb.as_reader()
    with _only(third, tie_a, first, tie_b, second):
        for path in (PAGE, POPUP):
            response = _get(session.client, path, q=QUERY)
            assert response.status_code == 200
            root = _tree(response)
            assert _slugs(root) == ["first", "second", "third", "tie_a", "tie_b"], path
            for slug, title in titles.items():
                assert title in _heading(_section(root, slug)), (path, slug)


# --- число группы и «Показать ещё» (FR-442) -------------------------------------------------------------

def test_count_endpoint_returns_group_count():
    """FR-442: `/search/count/?q=&group=` отдаёт `span[data-search-count-value]` с `data-count`, `data-capped` и текстом
    `N`; у группы, упёршейся в потолок, — `N+` и `data-capped=true`; поставщику уходит разобранный запрос."""
    exact, exact_log = _fake("exact", "Точная", 10, 7)
    capped, capped_log = _fake("capped", "С потолком", 20, 3, count=(1000, True))
    session = kb.as_reader()
    with _only(exact, capped):
        first = _get(session.client, COUNT, q=QUERY, group="exact")
        second = _get(session.client, COUNT, q=QUERY, group="capped")
    assert first.status_code == 200 and second.status_code == 200
    spans = _q(_tree(first), "span", data_search_count_value=True)
    assert len(spans) == 1
    assert spans[0].attrs["data-count"] == "7" and spans[0].attrs["data-capped"] == "false"
    assert spans[0].text() == "7"
    spans = _q(_tree(second), "span", data_search_count_value=True)
    assert len(spans) == 1
    assert spans[0].attrs["data-count"] == "1000" and spans[0].attrs["data-capped"] == "true"
    assert spans[0].text() == "1000+"
    assert exact_log.count == [QUERY_RAW] and capped_log.count == [QUERY_RAW]
    assert exact_log.search == [] and capped_log.search == []


def test_count_endpoint_unknown_or_unavailable_group_gives_nothing():
    """FR-442, FR-444: неизвестная, недоступная, упавшая и не названная группа — 200 с пустым телом, без ошибки;
    ответ на недоступную не отличается от ответа на несуществующую; счёт недоступной не вызывается."""
    open_one, open_log = _fake("open", "Открытая", 10, 5)
    closed, closed_log = _fake("closed", "Закрытая", 20, 5, available=False)
    broken, broken_log = _fake("broken", "Сломанная", 30, 5, fail_count=RuntimeError("сбой счёта"))
    session = kb.as_reader()
    with _only(open_one, closed, broken):
        bodies = {}
        for name, params in (("unknown", {"group": "nothing"}), ("closed", {"group": "closed"}),
                             ("broken", {"group": "broken"}), ("none", {})):
            response = _get(session.client, COUNT, q=QUERY, **params)
            assert response.status_code == 200, name
            bodies[name] = response.content.strip()
        short = _get(session.client, COUNT, q="а", group="open")
    assert set(bodies.values()) == {b""}
    assert closed_log.count == [] and len(broken_log.count) == 1
    assert short.status_code == 200 and short.content.strip() == b""
    assert open_log.count == []


def test_more_endpoint_returns_next_twenty_rows():
    """FR-442: `/search/more/?offset=20` отдаёт следующие 20 строк группы (поставщику уходит limit=20, offset=20) и
    новую кнопку со смещением 40; последняя порция (10 строк) — без кнопки; нечисловое и отрицательное смещение — 0."""
    provider, log = _fake("long", "Длинная", 10, 50)
    session = kb.as_reader()
    with _only(provider):
        second = _get(session.client, MORE, q=QUERY, group="long", offset=20)
        third = _get(session.client, MORE, q=QUERY, group="long", offset=40)
        starts = [_get(session.client, MORE, q=QUERY, group="long", offset=value) for value in ("-5", "abc", "")]
    assert second.status_code == 200
    root = _tree(second)
    rows = [n for n in root.walk() if n.tag == "li" and "data-search-row" in n.attrs]
    assert [_row_title(r) for r in rows] == [f"long-row-{i:02d}" for i in range(20, 40)]
    button = _more_button(root)
    assert button is not None and button.attrs["data-next-offset"] == "40"
    assert button.attrs["hx-target"] == "this" and button.attrs["hx-swap"] == "outerHTML"
    path, params = _hx(button.attrs["hx-get"])
    assert path == "/search/more/" and params["group"] == ["long"] and params["offset"] == ["40"]
    last = _tree(third)
    assert [_row_title(r) for r in last.walk() if r.tag == "li" and "data-search-row" in r.attrs] == \
        [f"long-row-{i:02d}" for i in range(40, 50)]
    assert _more_button(last) is None
    for response in starts:
        assert response.status_code == 200
        titles = [_row_title(r) for r in _tree(response).walk() if r.tag == "li" and "data-search-row" in r.attrs]
        assert titles == [f"long-row-{i:02d}" for i in range(20)]
    assert log.search[:2] == [(20, 20, QUERY_RAW), (20, 40, QUERY_RAW)]
    assert [call[:2] for call in log.search[2:]] == [(20, 0)] * 3


def test_more_endpoint_offset_beyond_end_is_empty():
    """FR-442: смещение за концом группы, неизвестная и недоступная группа — 200 без строк и без кнопки, без ошибки."""
    provider, log = _fake("long", "Длинная", 10, 30)
    closed, closed_log = _fake("closed", "Закрытая", 20, 30, available=False)
    session = kb.as_reader()
    with _only(provider, closed):
        responses = {
            "beyond": _get(session.client, MORE, q=QUERY, group="long", offset=500),
            "unknown": _get(session.client, MORE, q=QUERY, group="nothing", offset=20),
            "closed": _get(session.client, MORE, q=QUERY, group="closed", offset=20),
        }
    for name, response in responses.items():
        assert response.status_code == 200, name
        root = _tree(response)
        assert _q(root, "li") == [] and _more_button(root) is None, name
    assert closed_log.search == []
    assert [call[:2] for call in log.search] == [(20, 500)]


# --- ошибка поставщика (FR-445, FR-446) -----------------------------------------------------------------

def test_provider_error_hides_group_and_others_work(caplog):
    """FR-445, FR-446: исключение поставщика не роняет выдачу: в окне и на странице остальные группы работают,
    группы упавшего нет, текст исключения не выводится; в журнале приложения запись `ERROR`; в журнал событий
    ничего не пишется."""
    bad, _ = _fake("bad", "Упавшая группа", 10, 3, fail_search=RuntimeError("текст сбоя поставщика"))
    good, good_log = _fake("good", "Рабочая группа", 20, 2)
    session = kb.as_reader()
    audit_before = support.model("core.AuditEvent").objects.count()
    caplog.set_level(logging.INFO)
    with _only(bad, good):
        popup = _get(session.client, POPUP, q=QUERY)
        page = _get(session.client, PAGE, q=QUERY)
    for response in (popup, page):
        assert response.status_code == 200
        root = _tree(response)
        assert _slugs(root) == ["good"]
        assert len(_rows(_section(root, "good"))) == 2
        assert "Упавшая группа" not in _html(response) and "текст сбоя поставщика" not in _html(response)
    errors = [r for r in caplog.records if r.name == "apps.search.services" and r.levelno >= logging.ERROR]
    assert len(errors) >= 2
    assert len(good_log.search) == 2
    assert support.model("core.AuditEvent").objects.count() == audit_before


def test_provider_error_logs_only_key_and_exception_class(caplog):
    """FR-446: запись об ошибке поставщика — логгер `apps.search.services`, уровень `ERROR`, в ней ключ группы и класс
    исключения; текста исключения, запроса и трассировки нет (ни в `search`, ни в `count`)."""
    leak = "утечка" + "текста"
    bad, _ = _fake("bad", "Упавшая группа", 10, 3, fail_search=ValueError(leak + " " + MARKER),
                   fail_count=KeyError(leak + " " + MARKER))
    session = kb.as_reader()
    caplog.set_level(logging.DEBUG)
    with _only(bad):
        assert _get(session.client, POPUP, q=MARKER).status_code == 200
        assert _get(session.client, COUNT, q=MARKER, group="bad").status_code == 200
    errors = [r for r in caplog.records if r.name == "apps.search.services" and r.levelno == logging.ERROR]
    assert len(errors) == 2
    assert "ValueError" in errors[0].getMessage() and "KeyError" in errors[1].getMessage()
    for record in errors:
        message = record.getMessage()
        assert "bad" in message
        assert not record.exc_info and not record.exc_text
    for record in caplog.records:
        if record.name.startswith("django.db"):
            continue
        text = " ".join([record.getMessage(), str(record.exc_text or ""), str(record.args)])
        assert leak not in text and MARKER not in text, record.name


# --- запрос нигде не хранится (FR-446) ------------------------------------------------------------------

def _run_all_endpoints(client, query):
    """Все четыре адреса поиска с настоящими поставщиками: окно, страница, число и порция каждой группы."""
    assert _get(client, POPUP, q=query).status_code == 200
    assert _get(client, PAGE, q=query).status_code == 200
    for slug in ("tickets", "articles", "staff", "units"):
        assert _get(client, COUNT, q=query, group=slug).status_code == 200
        assert _get(client, MORE, q=query, group=slug, offset=20).status_code == 200


def _run_with_error_path(client, query):
    """То же с упавшим поставщиком: ветка ошибки тоже не должна оставлять запрос."""
    bad, _ = _fake("bad", "Упавшая группа", 10, 3, fail_search=RuntimeError("сбой"), fail_count=RuntimeError("сбой"))
    good, _ = _fake("good", "Рабочая группа", 20, 3)
    with _only(bad, good):
        assert _get(client, POPUP, q=query).status_code == 200
        assert _get(client, PAGE, q=query).status_code == 200
        assert _get(client, COUNT, q=query, group="bad").status_code == 200


def _searcher():
    """Сотрудник с правом «Просмотр сотрудников и структуры» и вошедший клиент (видны все четыре группы)."""
    user = support.make_with_permissions("staff.view")
    return user, support.logged_in(user)


def test_query_not_stored_in_any_database_table():
    """FR-446: после обращений ко всем адресам поиска (в том числе с ошибкой поставщика) метки-слова запроса нет ни в
    одной строке ни одной таблицы базы."""
    from django.db import connection

    user, client = _searcher()
    _run_all_endpoints(client, MARKER)
    _run_with_error_path(client, MARKER)
    pattern = "%" + MARKER + "%"
    holders = []
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names():
            # имя из интроспекции базы — только через quote_name; значение — параметром
            cursor.execute("SELECT count(*) FROM " + connection.ops.quote_name(table) + " AS t WHERE t::text ILIKE %s",
                           [pattern])
            if cursor.fetchone()[0]:
                holders.append(table)
    assert holders == [], f"запрос найден в таблицах: {holders}"


def test_query_not_in_audit_log():
    """FR-446: журнал событий после поиска не растёт, и метки-слова запроса нет ни в одном его поле."""
    Event = support.model("core.AuditEvent")
    user, client = _searcher()
    before = Event.objects.count()
    _run_all_endpoints(client, MARKER)
    _run_with_error_path(client, MARKER)
    assert Event.objects.count() == before
    for values in Event.objects.values():
        assert MARKER not in str(values)


def test_query_not_in_application_log_marker_word(caplog):
    """FR-446: метки-слова запроса нет ни в одной записи журнала приложения (все логгеры, от уровня DEBUG; отладочный
    журнал SQL самой Django не считается), в том числе в ветке ошибки поставщика."""
    user, client = _searcher()
    caplog.set_level(logging.DEBUG)
    _run_all_endpoints(client, MARKER)
    _run_with_error_path(client, MARKER)
    assert caplog.records, "журнал пуст: проверка ничего не доказывает"
    for record in caplog.records:
        if record.name.startswith("django.db"):
            continue
        text = " ".join([record.getMessage(), str(record.exc_text or ""), str(record.args), str(record.__dict__.get("request", ""))])
        assert MARKER not in text, f"запрос в записи логгера {record.name}"


# --- вход (FR-439, FR-442) ------------------------------------------------------------------------------

def test_search_endpoints_require_login():
    """FR-439, FR-442: все четыре адреса поиска без входа — 302 на `/login/` с `next`, поставщики не вызываются; тот же
    запрос вошедшего — 200; другой метод — 405 (контракт 10.1)."""
    provider, log = _fake("many", "Много", 10, 25)
    anonymous = support.make_client()
    params = {"q": QUERY, "group": "many", "offset": "0"}
    session = kb.as_reader()
    with _only(provider):
        for path in SEARCH_PATHS:
            for extra in ({}, {"headers": {"HX-Request": "true"}}):
                response = anonymous.get(path, params, **extra)
                assert response.status_code == 302, path
                assert response["Location"].startswith("/login/") and "next=" in response["Location"], path
        assert log.search == [] and log.count == []
        for path in SEARCH_PATHS:
            assert session.client.get(path, params).status_code == 200, path
            assert session.client.post(path, params).status_code == 405, path
