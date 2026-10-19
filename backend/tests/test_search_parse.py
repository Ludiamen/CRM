"""T-5125: разбор запроса сквозного поиска (FR-440, FR-443, NFR-408). Сценарии «Сквозной поиск» спеки.

`search.parse.parse(q) -> ParsedQuery` (CONTRACT-005, 9.1, 3.2): порядок разбора, значения `hint`, примеры, `raw`
без служебных знаков `tsquery`, знаки запроса как обычный текст через всех поставщиков, порог в 2 знака на сервере.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка).
"""
import re

import pytest

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

MAX_NUMBER = 2_147_483_647


def parse(q):
    from apps.search.parse import parse as parse_query

    return parse_query(q)


def assert_empty(parsed, hint):
    """При непустом `hint` остальные поля пусты (контракт 9.1, «Значения `hint`»)."""
    assert parsed.hint == hint
    assert parsed.words == []
    assert parsed.number is None
    assert parsed.raw == ""


def body(response) -> str:
    return response.content.decode()


# --- короткий запрос ---------------------------------------------------------------------------------

def test_empty_query_gives_short_hint():
    """FR-443: пустой запрос — `hint="short"`, остальные поля пусты."""
    assert_empty(parse(""), "short")


def test_whitespace_only_query_gives_short_hint():
    """FR-443: только пробелы — после `strip` пусто, `hint="short"`."""
    assert_empty(parse("   "), "short")
    assert_empty(parse(" \t \n "), "short")


def test_single_char_query_gives_short_hint():
    """FR-440, FR-443: один знак — `hint="short"` (порог 2 знака), в том числе с пробелами вокруг."""
    assert_empty(parse("а"), "short")
    assert_empty(parse("  а  "), "short")
    assert_empty(parse("x"), "short")


def test_single_digit_without_hash_gives_short_hint():
    """FR-443: одна цифра без решётки — `hint="short"`, номера заявки нет."""
    assert_empty(parse("5"), "short")


def test_all_words_shorter_than_two_chars_give_short_hint():
    """FR-440, FR-443: длина строки достаточна, но все слова короче двух знаков и числа нет — `hint="short"` (п. 5)."""
    assert_empty(parse("а б"), "short")
    assert_empty(parse("a b c"), "short")


# --- номер заявки ------------------------------------------------------------------------------------

def test_hash_number_is_ticket_number():
    """FR-443: «#42» — номер заявки 42; слово «42» остаётся словом (контракт 9.1, примеры)."""
    parsed = parse("#42")
    assert parsed.hint == ""
    assert parsed.number == 42
    assert parsed.words == ["42"]
    assert parsed.raw == "42:*"


def test_hash_single_digit_is_ticket_number_without_hint():
    """FR-443: «#5» — номер 5 без подсказки; слово «5» короче двух знаков отброшено, слов и `raw` нет."""
    parsed = parse("#5")
    assert parsed.hint == ""
    assert parsed.number == 5
    assert parsed.words == []
    assert parsed.raw == ""


def test_bare_two_digit_number_is_ticket_number():
    """FR-443: «15» без решётки — номер 15 и слово «15» (поиск и по номеру, и по тексту)."""
    parsed = parse("15")
    assert parsed.hint == ""
    assert parsed.number == 15
    assert parsed.words == ["15"]
    assert parsed.raw == "15:*"
    # строка не целиком число — номера нет
    mixed = parse("15 сеть")
    assert mixed.number is None
    assert mixed.words == ["15", "сеть"]


def test_number_above_int_limit_is_not_a_number_and_no_error():
    """FR-443, NFR-408: число выше 2 147 483 647 — `number=None`, слово остаётся, ошибки нет; предел включительно."""
    big = str(MAX_NUMBER + 1)
    for q in (big, "#" + big, "9" * 40):
        parsed = parse(q)
        assert parsed.hint == ""
        assert parsed.number is None
        digits = q.lstrip("#")
        assert parsed.words == [digits]
        assert parsed.raw == f"{digits}:*"
    edge = parse(str(MAX_NUMBER))
    assert edge.number == MAX_NUMBER
    assert parse("#" + str(MAX_NUMBER)).number == MAX_NUMBER


# --- длина -------------------------------------------------------------------------------------------

def test_query_over_200_chars_gives_long_hint():
    """FR-443: 201 знак — `hint="long"`, остальные поля пусты."""
    assert_empty(parse("а" * 201), "long")
    assert_empty(parse("сеть " * 41 + "а"), "long")


def test_query_of_exactly_200_chars_is_accepted():
    """FR-443: ровно 200 знаков принимается; длина считается после `strip`."""
    word = "а" * 200
    for q in (word, "  " + word + "  "):
        parsed = parse(q)
        assert parsed.hint == ""
        assert parsed.words == [word]
        assert parsed.raw == f"{word}:*"


def test_long_query_hint_wins_over_word_parsing():
    """FR-443: запрос длиннее 200 знаков из подходящих слов или числа — всё равно `long`, на слова не разбирается."""
    assert_empty(parse("сеть " * 50), "long")
    assert_empty(parse("1" * 201), "long")
    assert_empty(parse("#" + "1" * 200), "long")


# --- слова -------------------------------------------------------------------------------------------

def test_nine_words_keep_first_eight():
    """FR-443: девять слов — остаются первые восемь, `raw` из восьми термов."""
    parsed = parse("aa bb cc dd ee ff gg hh ii")
    assert parsed.hint == ""
    assert parsed.words == ["aa", "bb", "cc", "dd", "ee", "ff", "gg", "hh"]
    assert parsed.raw == " & ".join(f"{w}:*" for w in parsed.words)


def test_words_shorter_than_two_chars_are_dropped_number_kept():
    """FR-443: слова короче 2 знаков отбрасываются до отсечения по восьми; номер «#5» остаётся."""
    parsed = parse("я сеть б vpn")
    assert parsed.hint == ""
    assert parsed.words == ["сеть", "vpn"]
    assert parsed.raw == "сеть:* & vpn:*"
    counted = parse("a bb cc dd ee ff gg hh ii jj")
    assert counted.words == ["bb", "cc", "dd", "ee", "ff", "gg", "hh", "ii"]
    hashed = parse("#5")
    assert hashed.number == 5
    assert hashed.words == []


def test_words_are_lowercased():
    """FR-443: слова приводятся к нижнему регистру (кириллица и латиница); «Wi-Fi» — два слова."""
    parsed = parse("СЕТЬ VPN Wi-Fi")
    assert parsed.words == ["сеть", "vpn", "wi", "fi"]
    assert parsed.raw == "сеть:* & vpn:* & wi:* & fi:*"


def test_raw_is_prefix_terms_joined_with_and():
    """FR-443: `raw` — «слово1:* & слово2:*»."""
    one = parse("сеть")
    assert one.raw == "сеть:*"
    assert one.words == ["сеть"]
    two = parse("почта настройка")
    assert two.words == ["почта", "настройка"]
    assert two.raw == "почта:* & настройка:*"


def test_raw_has_no_tsquery_operators_for_any_word():
    """FR-443, NFR-408: в `raw` нет знаков `tsquery` кроме добавленных `:*` и ` & `; слова — только `\\w+`."""
    probes = ["foo & bar | !baz (qux) :* <-> quux'", "a:* b:* cc:dd", "!!!сеть((", "<->vpn<2>wifi", "ab'cd\"ef",
              "x|y|zz", "100% _ab_ \\cd", "q;--rr", "'; drop table users; --"]
    for q in probes:
        parsed = parse(q)
        assert parsed.hint == ""
        for word in parsed.words:
            assert re.fullmatch(r"\w{2,}", word), (q, word)
        terms = parsed.raw.split(" & ")
        assert terms == [f"{w}:*" for w in parsed.words], q
        stripped = parsed.raw.replace(":*", "").replace(" & ", "")
        assert not set("&|!()<>':*") & set(stripped), (q, parsed.raw)


def test_special_characters_are_plain_text_without_error():
    """FR-443, NFR-408: кавычки, `%`, `_`, обратная косая, `;`, `--` — обычный текст: слова выделяются, ошибки нет."""
    parsed = parse("100% sale_item \\path; it's \"quoted\" -- end")
    assert parsed.hint == ""
    assert parsed.number is None
    assert "100" in parsed.words and "quoted" in parsed.words and "end" in parsed.words
    assert parsed.raw == " & ".join(f"{w}:*" for w in parsed.words)
    # только знаки: слов нет — подсказка «short», а не ошибка
    assert_empty(parse(r"%_;'\"--"), "short")


def test_special_characters_query_runs_through_all_providers_without_error():
    """FR-443, NFR-408: запрос со знаками проходит через четыре группы (страница, окно, число, «ещё») без ошибки."""
    article = kb.make_published(title="drop table quoted", text="foo bar baz")
    user = support.make_employee()
    kb.grant(user, "staff.view")
    client = support.logged_in(user)
    queries = ["'; DROP TABLE; --", "foo & bar | !baz (qux) :* <-> quux'", "100% \\ _ \"quoted\" ;", "!!!(("]
    from apps.search import services

    for q in queries:
        parsed = parse(q)
        groups = services.page(user, parsed)
        assert isinstance(groups, list)
        services.popup(user, parsed)
        for key in ("tickets", "articles", "staff", "units"):
            assert isinstance(services.more(user, parsed, key, 0), list)
            services.count(user, parsed, key)
            for path in ("/search/", "/search/popup/", "/search/count/", "/search/more/"):
                extra = {"group": key, "offset": 0} if path in ("/search/count/", "/search/more/") else {}
                response = client.get(path, {"q": q, **extra})
                assert response.status_code == 200, (path, q, key)
    # запрос со знаками находит статью по обычным словам: SQL получил его параметром
    found = services.page(user, parse("'; DROP TABLE; --"))
    articles = [g for g in found if g.key == "articles"]
    assert articles and [row.url for row in articles[0].rows] == [f"/kb/{article.pk}/"]
    assert "data-search-group=\"articles\"" in body(client.get("/search/", {"q": "'; DROP TABLE; --"}))


# --- границы -----------------------------------------------------------------------------------------

def test_parse_trims_surrounding_spaces():
    """FR-443: пробелы вокруг запроса отбрасываются до разбора."""
    parsed = parse("  сеть ")
    assert parsed.hint == ""
    assert parsed.words == ["сеть"]
    assert parsed.raw == "сеть:*"
    assert parse("\t#42\n").number == 42


def test_server_rejects_short_query_regardless_of_browser():
    """FR-440, FR-443: порог 2 знака проверяет сервер; запрос в 1 знак (в обход `maxlength`/браузера) — подсказка
    «short» на странице, пустое окно, поставщики не вызываются (статья с таким словом не выдаётся)."""
    kb.make_published(title="x server", text="x")
    user = support.make_employee()
    client = support.logged_in(user)
    for q in ("x", " x ", "", "   "):
        page = client.get("/search/", {"q": q})
        assert page.status_code == 200
        text = body(page)
        assert re.search(r"""<[^>]*\sdata-search-hint=["']short["']""", text), q
        assert "Введите не меньше 2 знаков" in text
        assert "data-search-group=" not in text
        popup = client.get("/search/popup/", {"q": q})
        assert popup.status_code == 200
        assert "data-search-group=" not in body(popup)
        assert "data-search-hint" not in body(popup)
    long_page = client.get("/search/", {"q": "а" * 201})
    assert long_page.status_code == 200
    assert re.search(r"""<[^>]*\sdata-search-hint=["']long["']""", body(long_page))
    assert "data-search-group=" not in body(long_page)
