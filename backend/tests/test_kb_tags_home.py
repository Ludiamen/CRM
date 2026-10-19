"""T-5112: теги и главная базы знаний (FR-406, FR-420, FR-421, NFR-408). Сценарии «Рубрики, теги, главная» спеки.

Службы `tags` вызываются напрямую (коды отказов по разделу 5.4 контракта), страницы — по путям разделов 10.2 и 10.4,
разметка — по зацепкам разделов 11.1-11.3, тексты — по разделу 12. Код среза на уровне модуля не импортируется:
имена берутся внутри тестов.
"""
import html as html_lib
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
HTMX = {"headers": {"HX-Request": "true"}}


# --- помощники только этого файла ------------------------------------------------------------------------

class _Dom(HTMLParser):
    """Плоский разбор разметки: узел — тег, атрибуты, текст внутри, предки."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list = []
        self._stack: list = []

    def _open(self, tag, attrs):
        node = SimpleNamespace(tag=tag, attrs={k: (v if v is not None else "") for k, v in attrs}, parts=[],
                               ancestors=list(self._stack))
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
    parser = _Dom()
    parser.feed(response.content.decode())
    parser.close()
    for node in parser.nodes:
        node.text = "".join(node.parts)
    return parser.nodes


def _find(response, tag: str | None = None, **attrs) -> list:
    """Узлы с тегом `tag` (если задан) и атрибутами; в `attrs` дефис записывается подчёркиванием: `data_error`."""
    want = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [n for n in _dom(response)
            if (tag is None or n.tag == tag) and all(n.attrs.get(k) == v for k, v in want.items())]


def _text(response) -> str:
    return html_lib.unescape(response.content.decode())


def _has(response, marker: str) -> bool:
    """Есть ли на странице узел с атрибутом `marker` (например, `data-kb-my-drafts`)."""
    return any(marker in n.attrs for n in _dom(response))


def _rows(response, marker: str) -> list:
    """Строки `li[data-article-id]` внутри узла с атрибутом `marker`."""
    return [n for n in _dom(response)
            if n.tag == "li" and "data-article-id" in n.attrs and any(marker in a.attrs for a in n.ancestors)]


def _ids(rows) -> list[int]:
    return [int(n.attrs["data-article-id"]) for n in rows]


def _list_ids(response) -> list[int]:
    """Номера статей в строках списка `[data-kb-list]` по порядку (у фрагмента без обёртки — все строки)."""
    nodes = _dom(response)
    scoped = any("data-kb-list" in n.attrs for n in nodes)
    return [int(n.attrs["data-article-id"]) for n in nodes
            if n.tag == "li" and "data-article-id" in n.attrs
            and (not scoped or any("data-kb-list" in a.attrs for a in n.ancestors))]


def _inside(node, container) -> bool:
    return any(a is container for a in node.ancestors)


def _more_buttons(response) -> list:
    return _find(response, "button", data_action="more")


def _tags():
    from apps.knowledge.services import tags

    return tags


def _refused(call, code: str, field: str = "tags"):
    """Служба отказывает (`TagError`) с кодом и полем."""
    from apps.knowledge.services import TagError

    with pytest.raises(TagError) as caught:
        call()
    assert caught.value.code == code, f"ждали {code}, получили {caught.value.code}: {caught.value}"
    assert caught.value.field == field
    return caught.value


def _published_of(count: int, clock, author, *, tags=(), rubric=None, title_prefix: str = "Статья"):
    """`count` опубликованных статей; каждая следующая правилась позже предыдущей (часы фикстуры)."""
    made = []
    for number in range(count):
        clock.advance(seconds=1)
        made.append(kb.make_published(rubric=rubric, author=author, tags=tags, vectors=False,
                                      title=f"{title_prefix} {number}"))
    return made


def _suggest(session, q: str):
    return session.client.get("/kb/tags/suggest/", {"q": q})


def _suggested(response) -> list[str]:
    assert response.status_code == 200
    items = [n for n in _dom(response) if n.tag == "li" and "data-tag" in n.attrs]
    if items:
        assert _has(response, "data-kb-tag-suggest"), "непустой список подсказок лежит в `ul[data-kb-tag-suggest]`"
    return [n.attrs["data-tag"] for n in _dom(response) if n.tag == "li" and "data-tag" in n.attrs]


def _post_new(session, rubric, tags_raw: str, title: str = "Новая статья про теги"):
    return session.client.post("/kb/new/", {"title": title, "text": "Текст", "rubric": rubric.pk, "tags": tags_raw,
                                            "comment": "", "action": "save"})


def _tag_page(session, name: str, **extra):
    return session.client.get("/kb/tags/", {"name": name, **extra})


# --- нормализация (FR-420) -----------------------------------------------------------------------------------

def test_normalize_trims_lowercases_collapses_inner_spaces():
    """FR-420: тег — без пробелов по краям, внутренние пробелы в один, строчные буквы (в том числе кириллица);
    порядок ввода сохраняется."""
    got = _tags().normalize("  VPN ,  Wi   Fi  ,ПОЧТА\t,  Двух   Факторная   Защита ")

    assert got == ["vpn", "wi fi", "почта", "двух факторная защита"]


def test_normalize_drops_empty_and_merges_duplicates_vpn_case():
    """FR-420: пустые теги выбрасываются, повторы (в том числе «VPN, vpn, Vpn») склеиваются в один; остаётся первое
    вхождение, порядок ввода сохраняется."""
    tags = _tags()

    assert tags.normalize("VPN, vpn, Vpn") == ["vpn"]
    assert tags.normalize(",, ,почта, ,сети,,  ПОЧТА ,vpn,Сети") == ["почта", "сети", "vpn"]
    assert tags.normalize("") == []
    assert tags.normalize(" , ,, ") == []


def test_eleventh_tag_refused_at_field_input_kept():
    """FR-420: больше 10 тегов — отказ `tags_too_many` у поля `tags` («Не больше 10 тегов»); проверка идёт после
    склейки повторов (11 записей с повтором — это 10 тегов); на форме статьи введённое остаётся, статья не создаётся."""
    tags = _tags()
    ten = ", ".join(f"тег{n}" for n in range(1, 11))
    eleven = ten + ", тег11"

    assert len(tags.normalize(ten)) == 10
    assert len(tags.normalize(ten + ", ТЕГ3")) == 10, "повтор склеивается до проверки предела"
    _refused(lambda: tags.normalize(eleven), "tags_too_many")

    editor = kb.as_editor()
    Article = support.model("knowledge.Article")
    before = Article.objects.count()
    response = _post_new(editor, kb.general_rubric(), eleven)
    assert response.status_code == 200
    assert _find(response, data_error="tags", data_code="tags_too_many")
    assert "Не больше 10 тегов" in _text(response)
    fields = _find(response, "input", name="tags")
    assert fields and fields[0].attrs.get("value") == eleven, "введённая строка тегов остаётся в поле"
    assert Article.objects.count() == before, "при отказе статья не создаётся"
    assert not support.model("knowledge.Tag").objects.filter(name="тег1").exists()


def test_tag_40_chars_accepted_41_refused():
    """FR-420: тег в 40 знаков принимается (пробелы по краям не считаются), в 41 знак — отказ `tag_too_long`
    у поля `tags` («Тег не длиннее 40 знаков»); на форме статьи введённое остаётся."""
    tags = _tags()
    exactly = "в" * 40
    too_long = "в" * 41

    assert tags.normalize(exactly) == [exactly]
    assert tags.normalize("  " + exactly + "  , почта") == [exactly, "почта"]
    _refused(lambda: tags.normalize(too_long), "tag_too_long")
    _refused(lambda: tags.normalize("почта, " + too_long), "tag_too_long")

    editor = kb.as_editor()
    Article = support.model("knowledge.Article")
    before = Article.objects.count()
    response = _post_new(editor, kb.general_rubric(), "почта, " + too_long)
    assert response.status_code == 200
    assert _find(response, data_error="tags", data_code="tag_too_long")
    assert "Тег не длиннее 40 знаков" in _text(response)
    assert _find(response, "input", name="tags")[0].attrs.get("value") == "почта, " + too_long
    assert Article.objects.count() == before
    accepted = _post_new(editor, kb.general_rubric(), exactly)
    assert accepted.status_code in (302, 200)
    assert Article.objects.count() == before + 1


# --- подсказка (FR-420) --------------------------------------------------------------------------------------

def test_suggest_published_tags_by_prefix_istartswith():
    """FR-420: подсказка — теги опубликованных статей, начинающиеся с введённого без учёта регистра (не «содержащие»);
    пустой запрос — пустой список. Служба и адрес `/kb/tags/suggest/?q=`."""
    author = kb.as_editor()
    kb.make_published(author=author.user, tags=["vpn", "vpn-клиент", "wifi", "ovpn", "почта"])
    tags = _tags()

    assert sorted(tags.suggest("vp")) == ["vpn", "vpn-клиент"]
    assert sorted(tags.suggest("VP")) == ["vpn", "vpn-клиент"], "сравнение без учёта регистра"
    assert tags.suggest("wi") == ["wifi"]
    assert tags.suggest("по") == ["почта"]
    assert tags.suggest("zzz") == []
    assert "ovpn" not in tags.suggest("vpn"), "середина слова не совпадает"

    response = _suggest(author, "Vp")
    assert sorted(_suggested(response)) == ["vpn", "vpn-клиент"]
    assert _suggested(_suggest(author, "")) == []


def test_suggest_limited_to_10():
    """FR-420: подсказка отдаёт не больше 10 тегов (служба и фрагмент `ul[data-kb-tag-suggest]`)."""
    author = kb.as_editor()
    names = [f"сеть{n:02d}" for n in range(15)]
    kb.make_published(author=author.user, tags=names[:8])
    kb.make_published(author=author.user, tags=names[8:])

    got = _tags().suggest("сеть")
    assert len(got) == 10 and set(got) <= set(names)
    over_http = _suggested(_suggest(author, "сеть"))
    assert len(over_http) == 10 and set(over_http) <= set(names)
    assert len(_suggested(_suggest(author, "сеть1"))) == 5, "пять тегов `сеть10`…`сеть14` — меньше предела"


def test_suggest_excludes_draft_and_trashed_tags():
    """FR-420: тег, который есть только у черновика или у статьи в корзине (опубликованной или нет), не подсказывается;
    тег, который есть и у опубликованной, подсказывается один раз."""
    author = kb.as_editor()
    kb.make_draft(author=author.user, tags=["только-черновик", "общий-тег"])
    kb.make_trashed(was="published", author=author.user, tags=["только-корзина", "общий-тег"])
    kb.make_trashed(was="draft", author=author.user, tags=["корзина-из-черновика"])
    kb.make_published(author=author.user, tags=["общий-тег", "опубликованный"])

    assert _tags().suggest("только") == []
    assert _tags().suggest("корзина") == []
    assert _tags().suggest("общий") == ["общий-тег"]
    assert _suggested(_suggest(author, "только")) == []
    assert _suggested(_suggest(author, "корзина")) == []
    assert _suggested(_suggest(author, "общий")) == ["общий-тег"]
    assert _suggested(_suggest(author, "опубл")) == ["опубликованный"]


def test_suggest_requires_edit_right():
    """FR-420: подсказка — только при праве править: читатель получает 403 и список тегов не видит; редактор и
    управляющий — 200; без входа — переход на вход."""
    kb.make_published(author=kb.as_editor().user, tags=["секретная-тема"])
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()

    denied = _suggest(reader, "сек")
    assert denied.status_code == 403
    assert "секретная-тема" not in denied.content.decode()
    assert _suggested(_suggest(editor, "сек")) == ["секретная-тема"]
    assert _suggested(_suggest(manager, "сек")) == ["секретная-тема"]
    anonymous = support.make_client().get("/kb/tags/suggest/", {"q": "сек"})
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/")


# --- страница тега (FR-420, FR-421) --------------------------------------------------------------------------

def test_tag_page_lists_published_by_updated_at_desc(clock):
    """FR-420, FR-421: страница тега — опубликованные статьи с тегом по времени правки вниз; изменённая позже
    встаёт первой; статьи без тега не показываются."""
    author = kb.as_editor().user
    reader = kb.as_reader()
    made = _published_of(3, clock, author, tags=["vpn"])
    other = _published_of(1, clock, author, tags=["почта"])[0]
    clock.advance(minutes=5)
    kb.add_version(made[0], author=author, text="Правка позже всех")

    response = _tag_page(reader, "vpn")

    assert response.status_code == 200
    assert _list_ids(response) == [made[0].pk, made[2].pk, made[1].pk]
    assert other.pk not in _list_ids(response)


def test_tag_page_excludes_drafts_and_trash():
    """FR-420, FR-421: черновиков и статей из корзины на странице тега нет — ни у читателя, ни у управляющего."""
    author = kb.as_editor().user
    published = kb.make_published(author=author, tags=["vpn"])
    draft = kb.make_draft(author=author, tags=["vpn"])
    trashed = kb.make_trashed(was="published", author=author, tags=["vpn"])
    trashed_draft = kb.make_trashed(was="draft", author=author, tags=["vpn"])

    for session in (kb.as_reader(), kb.as_editor(), kb.as_manager()):
        response = _tag_page(session, "vpn")
        assert response.status_code == 200
        assert _list_ids(response) == [published.pk]
        body = response.content.decode()
        for hidden in (draft, trashed, trashed_draft):
            assert hidden.title not in body


def test_tag_page_paginates_20_with_offset(clock):
    """FR-420, FR-421: по 20 статей, «Показать ещё» (`data-action="more"`, `data-next-offset`) отдаёт следующие 20
    фрагментом и пропадает на последней порции; ошибочный `offset` читается как 0."""
    author = kb.as_editor().user
    reader = kb.as_reader()
    made = _published_of(45, clock, author, tags=["vpn"])
    newest_first = [a.pk for a in reversed(made)]

    first = _tag_page(reader, "vpn")
    assert first.status_code == 200
    assert _list_ids(first) == newest_first[:20]
    assert [b.attrs.get("data-next-offset") for b in _more_buttons(first)] == ["20"]

    second = reader.client.get("/kb/tags/", {"name": "vpn", "offset": 20}, **HTMX)
    assert second.status_code == 200 and "<html" not in second.content.decode()
    assert _list_ids(second) == newest_first[20:40]
    assert [b.attrs.get("data-next-offset") for b in _more_buttons(second)] == ["40"]

    third = reader.client.get("/kb/tags/", {"name": "vpn", "offset": 40}, **HTMX)
    assert third.status_code == 200
    assert _list_ids(third) == newest_first[40:]
    assert _more_buttons(third) == []

    for bad in ("-5", "abc", ""):
        again = _tag_page(reader, "vpn", offset=bad)
        assert again.status_code == 200
        assert _list_ids(again) == newest_first[:20], f"offset={bad!r} должен читаться как 0"


def test_tag_names_with_slash_question_hash_cyrillic_have_own_page():
    """FR-420: имя тега идёт параметром запроса, поэтому теги со знаками `/`, `?`, `#`, кириллицей и пробелом имеют
    свою страницу, и она показывает только свои статьи."""
    author = kb.as_editor().user
    reader = kb.as_reader()
    names = ["ci/cd", "что? где#", "привет мир", "c#", "a/b/c", "a"]
    articles = {name: kb.make_published(author=author, tags=[name]) for name in names}

    for name in names:
        response = _tag_page(reader, name)
        assert response.status_code == 200, f"страница тега {name!r}"
        assert _list_ids(response) == [articles[name].pk], f"страница тега {name!r} показывает только свои статьи"
    address = "/kb/tags/?name=" + quote("ci/cd", safe="")
    assert reader.client.get(address).status_code == 200
    assert _list_ids(reader.client.get(address)) == [articles["ci/cd"].pk]


def test_tag_without_published_articles_is_404():
    """FR-420: тег без опубликованных статей (есть только у черновика, у статьи в корзине, нет вовсе, имя пусто или не
    задано) — 404; в ответе нет данных статей."""
    author = kb.as_editor().user
    draft = kb.make_draft(author=author, tags=["черновой"])
    trashed = kb.make_trashed(was="published", author=author, tags=["удалённый"])
    reader = kb.as_reader()
    manager = kb.as_manager()

    for session in (reader, manager):
        for name in ("черновой", "удалённый", "нет-такого"):
            response = _tag_page(session, name)
            assert response.status_code == 404, f"тег {name!r}"
            assert draft.title not in response.content.decode()
            assert trashed.title not in response.content.decode()
        assert _tag_page(session, "").status_code == 404
        assert session.client.get("/kb/tags/").status_code == 404


def test_tag_disappears_when_last_article_loses_it():
    """FR-420: когда у последней опубликованной статьи тег убрали, страница тега отвечает 404, подсказка его не
    предлагает; пока тег держит другая статья, страница жива."""
    from apps.knowledge.services import articles

    author = kb.as_editor()
    first = kb.make_published(author=author.user, tags=["временный"])
    second = kb.make_published(author=author.user, tags=["временный", "постоянный"])
    reader = kb.as_reader()

    def drop_tag(article, keep: str):
        form = articles.ArticleForm(title=article.title, text=article.text, rubric_id=article.rubric_id, tags=keep)
        result = articles.save(author.user, article.pk, article.version_no, form)
        assert result.kind == "saved"
        article.refresh_from_db()

    assert _tag_page(reader, "временный").status_code == 200
    drop_tag(first, "")
    page = _tag_page(reader, "временный")
    assert page.status_code == 200
    assert _list_ids(page) == [second.pk]
    assert _suggested(_suggest(author, "врем")) == ["временный"]

    drop_tag(second, "постоянный")
    assert _tag_page(reader, "временный").status_code == 404
    assert _suggested(_suggest(author, "врем")) == []
    assert _tag_page(reader, "постоянный").status_code == 200


def test_article_page_tag_links_to_tag_page_with_name_parameter():
    """FR-420, FR-421: на странице статьи тег — ссылка `a[data-tag]` на `/kb/tags/?name=<имя>` (имя в процентной
    записи: `/`, `?`, `#`, пробел и кириллица не ломают адрес); переход по ссылке открывает страницу тега со
    статьёй."""
    author = kb.as_editor().user
    names = ["vpn", "ci/cd", "что? где#", "привет мир"]
    article = kb.make_published(author=author, tags=names)
    reader = kb.as_reader()

    response = reader.client.get(f"/kb/{article.pk}/")

    assert response.status_code == 200
    links = {n.attrs["data-tag"]: n for n in _find(response, "a") if "data-tag" in n.attrs}
    assert sorted(links) == sorted(names)
    for name in names:
        href = links[name].attrs["href"]
        parts = urlsplit(href)
        assert parts.path == "/kb/tags/" and parts.fragment == "", f"{name!r}: `#` в имени должен быть записан как %23"
        assert parse_qs(parts.query) == {"name": [name]}, f"{name!r}: адрес {href!r}"
        followed = reader.client.get(href)
        assert followed.status_code == 200
        assert _list_ids(followed) == [article.pk]


def test_no_tag_cloud_on_home_or_tag_page():
    """FR-420: облака тегов нет ни на главной, ни на странице тега: на главной нет ссылок на теги (строки главной
    без тегов, раздел 17 п. 43), на странице тега ссылки на теги есть только в строках статей списка (п. 12)."""
    author = kb.as_editor().user
    kb.make_published(author=author, tags=["vpn", "почта"])
    kb.make_published(author=author, tags=["vpn", "сети"])
    kb.make_published(author=author, tags=["одинокий"])
    reader = kb.as_reader()

    home = reader.client.get("/kb/")
    assert home.status_code == 200
    assert not [n for n in _dom(home) if "data-tag" in n.attrs]
    assert "/kb/tags/?name=" not in home.content.decode()
    assert "облако тегов" not in _text(home).lower()

    page = _tag_page(reader, "vpn")
    assert page.status_code == 200
    for node in _dom(page):
        if "data-tag" in node.attrs:
            assert any(a.tag == "li" and "data-article-id" in a.attrs for a in node.ancestors), \
                "ссылка на тег вне строки статьи — это облако"
    assert "одинокий" not in page.content.decode(), "тег чужой статьи не показывается на странице тега"


# --- главная (FR-421) ----------------------------------------------------------------------------------------

def _count_texts(response) -> dict[int, str]:
    """Для каждой рубрики дерева главной — текст её `[data-field=count]` (в строке `li` этой рубрики, не вложенной)."""
    found: dict[int, str] = {}
    for node in _dom(response):
        if node.attrs.get("data-field") != "count":
            continue
        rows = [a for a in node.ancestors if a.tag == "li" and "data-rubric-id" in a.attrs]
        assert rows, "число статей вне строки рубрики"
        found[int(rows[-1].attrs["data-rubric-id"])] = " ".join(node.text.split())
    return found


def test_home_tree_counts_published_with_subrubrics_in_three_russian_forms():
    """FR-421: дерево рубрик главной — число опубликованных статей рубрики вместе с подрубриками словом по склонению:
    1 «статья», 2–4 «статьи», 0 и 5–20 «статей», далее по последней цифре (21, 22, 25), 111 «статей»; у строки
    `data-depth` — уровень, ссылка названия — `/kb/rubrics/<id>/`."""
    author = kb.as_editor().user
    reader = kb.as_reader()
    chain = kb.rubric_tree({"Сети": {"VPN": {"Клиенты": {}}}})
    for rubric in chain.values():
        kb.make_published(rubric=rubric, author=author, vectors=False)
    expected = {chain["Клиенты"].pk: "1 статья", chain["VPN"].pk: "2 статьи", chain["Сети"].pk: "3 статьи"}
    sizes = {0: "0 статей", 1: "1 статья", 2: "2 статьи", 4: "4 статьи", 5: "5 статей", 11: "11 статей",
             12: "12 статей", 20: "20 статей", 21: "21 статья", 22: "22 статьи", 25: "25 статей", 111: "111 статей"}
    for size, word in sizes.items():
        rubric = kb.make_rubric(f"Тема {size}")
        for _ in range(size):
            kb.make_published(rubric=rubric, author=author, vectors=False)
        expected[rubric.pk] = word
    expected[kb.general_rubric().pk] = "0 статей"

    response = reader.client.get("/kb/")

    assert response.status_code == 200
    assert _has(response, "data-kb-tree")
    assert _count_texts(response) == expected
    rows = {int(n.attrs["data-rubric-id"]): n for n in _dom(response)
            if n.tag == "li" and "data-rubric-id" in n.attrs and any("data-kb-tree" in a.attrs for a in n.ancestors)}
    assert set(rows) == set(expected), "в дереве все рубрики"
    assert [rows[chain[name].pk].attrs["data-depth"] for name in ("Сети", "VPN", "Клиенты")] == ["1", "2", "3"]
    for rubric_id in (chain["Сети"].pk, chain["Клиенты"].pk):
        links = [n for n in _dom(response) if n.tag == "a" and n.attrs.get("data-field") == "name"
                 and n.attrs.get("href") == f"/kb/rubrics/{rubric_id}/"]
        assert len(links) == 1, f"ссылка названия рубрики {rubric_id}"


def test_home_counts_exclude_drafts_and_trash():
    """FR-421: в числе рубрики на главной нет черновиков и статей из корзины (у читателя, редактора и управляющего)."""
    author = kb.as_editor().user
    tree = kb.rubric_tree({"Сети": {"VPN": {}}})
    kb.make_published(rubric=tree["Сети"], author=author)
    kb.make_published(rubric=tree["VPN"], author=author)
    for _ in range(3):
        kb.make_draft(rubric=tree["VPN"], author=author)
    kb.make_trashed(was="published", rubric=tree["VPN"], author=author)
    kb.make_trashed(was="draft", rubric=tree["Сети"], author=author)

    for session in (kb.as_reader(), kb.as_editor(), kb.as_manager()):
        counts = _count_texts(session.client.get("/kb/"))
        assert counts[tree["VPN"].pk] == "1 статья"
        assert counts[tree["Сети"].pk] == "2 статьи"


def test_home_new_and_changed_10_by_updated_at(clock):
    """FR-421: «Новые и изменённые» — 10 опубликованных статей по `updated_at` вниз (без черновиков и корзины); у строки
    заголовок, рубрика и время; статья, изменённая позже, встаёт первой."""
    author = kb.as_editor().user
    reader = kb.as_reader()
    rubric = kb.make_rubric("Сети")
    made = _published_of(12, clock, author, rubric=rubric, tags=["vpn"])
    clock.advance(seconds=1)
    draft = kb.make_draft(author=author, rubric=rubric, tags=["vpn"])
    clock.advance(seconds=1)
    trashed = kb.make_trashed(was="published", author=author, rubric=rubric)

    response = reader.client.get("/kb/")
    assert response.status_code == 200
    rows = _rows(response, "data-kb-new-and-changed")
    assert _ids(rows) == [a.pk for a in reversed(made)][:10]
    assert draft.pk not in _ids(rows) and trashed.pk not in _ids(rows)
    first = rows[0]
    title = [n for n in _dom(response) if n.tag == "a" and n.attrs.get("data-field") == "title"
             and _inside(n, first)]
    assert title and title[0].text.strip() == made[-1].title
    assert title[0].attrs["href"] == f"/kb/{made[-1].pk}/"
    assert any(n.attrs.get("data-field") == "rubric" and "Сети" in n.text
               for n in _dom(response) if _inside(n, first))
    assert any(n.tag == "time" and "data-at" in n.attrs for n in _dom(response) if _inside(n, first))
    assert "Новые и изменённые" in _text(response)
    assert not [n for n in _dom(response) if "data-tag" in n.attrs], "теги в строках главной не показываются (п. 43)"

    clock.advance(minutes=10)
    kb.add_version(made[0], author=author, text="Свежая правка")
    again = _rows(reader.client.get("/kb/"), "data-kb-new-and-changed")
    assert _ids(again) == [made[0].pk] + [a.pk for a in reversed(made)][:9]


def test_home_reader_without_rights_sees_no_new_button_or_my_drafts():
    """FR-421, FR-406: читатель без прав видит опубликованное, но не видит кнопку «Новая статья», «Мои черновики»,
    «Черновики» всех и ссылку «Корзина»; названий чужих черновиков в ответе нет."""
    author = kb.as_editor().user
    published = kb.make_published(author=author)
    draft = kb.make_draft(author=author, title="Секретный черновик редактора")
    reader = kb.as_reader()

    response = reader.client.get("/kb/")

    assert response.status_code == 200
    assert _ids(_rows(response, "data-kb-new-and-changed")) == [published.pk]
    assert not _find(response, "a", data_action="kb-new-article")
    assert not _find(response, "a", data_action="kb-trash-link")
    assert not _has(response, "data-kb-my-drafts")
    assert not _has(response, "data-kb-all-drafts")
    body = _text(response)
    assert draft.title not in body
    assert "Мои черновики" not in body
    assert "Новая статья" not in body


def test_home_editor_sees_my_drafts_only_own_and_new_button():
    """FR-421: редактор видит «Мои черновики» — только свои (чужих и опубликованных в списке нет), кнопку «Новая
    статья» (`/kb/new/`); «Черновики» всех и «Корзины» у него нет."""
    me = kb.as_editor()
    colleague = kb.as_editor()
    mine = [kb.make_draft(author=me.user, title=f"Мой черновик {n}") for n in range(2)]
    foreign = kb.make_draft(author=colleague.user, title="Чужой черновик")
    kb.make_published(author=me.user, title="Моя опубликованная")
    kb.make_trashed(was="draft", author=me.user, title="Мой черновик в корзине")

    response = me.client.get("/kb/")

    assert response.status_code == 200
    assert sorted(_ids(_rows(response, "data-kb-my-drafts"))) == sorted(a.pk for a in mine)
    assert foreign.title not in _text(response)
    buttons = _find(response, "a", data_action="kb-new-article")
    assert buttons and buttons[0].attrs["href"] == "/kb/new/"
    assert not _has(response, "data-kb-all-drafts")
    assert not _find(response, "a", data_action="kb-trash-link")
    body = _text(response)
    assert "Мои черновики" in body and "Новая статья" in body


def test_home_manager_sees_all_drafts_and_trash_link():
    """FR-421: управляющий видит «Черновики» всех (свои и чужие; без опубликованных и корзины), ссылку «Корзина»
    (`/kb/trash/`) и кнопку «Новая статья»."""
    manager = kb.as_manager()
    first, second = kb.as_editor(), kb.as_editor()
    drafts = [kb.make_draft(author=first.user, tags=["vpn"]), kb.make_draft(author=second.user),
              kb.make_draft(author=manager.user)]
    published = kb.make_published(author=first.user)
    trashed = kb.make_trashed(was="draft", author=second.user)

    response = manager.client.get("/kb/")

    assert response.status_code == 200
    listed = _ids(_rows(response, "data-kb-all-drafts"))
    assert sorted(listed) == sorted(a.pk for a in drafts)
    assert sorted(_ids(_rows(response, "data-kb-my-drafts"))) == [drafts[2].pk], \
        "управляющий видит и «Мои черновики» (свои), и «Черновики» (все) — п. 14"
    assert published.pk not in listed and trashed.pk not in listed
    assert not [n for n in _dom(response) if "data-tag" in n.attrs], "теги в строках черновиков главной не показываются (п. 43)"
    trash = _find(response, "a", data_action="kb-trash-link")
    assert trash and trash[0].attrs["href"] == "/kb/trash/"
    assert _find(response, "a", data_action="kb-new-article")
    body = _text(response)
    assert "Черновики" in body and "Корзина" in body


def test_home_empty_base_explanation_and_new_button_by_right():
    """FR-421: пустая база (нет ни одной опубликованной статьи, п. 15) — пояснение «В базе знаний пока нет статей»
    (`[data-empty-state="kb"]`); ссылка «Новая статья» внутри пояснения есть у редактора и управляющего и нет у
    читателя (п. 13); пояснение есть и при одних черновиках; в непустой базе пояснения нет."""
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()

    def new_links(page):
        containers = _find(page, data_empty_state="kb")
        assert len(containers) == 1
        return [n for n in _find(page, "a", data_action="kb-new-article") if _inside(n, containers[0])]

    reader_page = reader.client.get("/kb/")
    assert reader_page.status_code == 200
    assert _find(reader_page, data_empty_state="kb")
    assert "В базе знаний пока нет статей" in _text(reader_page)
    assert not _find(reader_page, "a", data_action="kb-new-article")
    for session in (editor, manager):
        page = session.client.get("/kb/")
        assert "В базе знаний пока нет статей" in _text(page)
        links = new_links(page)
        assert links and links[0].attrs["href"] == "/kb/new/"

    kb.make_draft(author=editor.user)
    kb.make_trashed(was="published", author=editor.user)
    for session in (reader, editor, manager):
        assert _find(session.client.get("/kb/"), data_empty_state="kb"), \
            "есть только черновик и корзина — опубликованных нет, пояснение показывается (п. 15)"
    assert new_links(editor.client.get("/kb/"))
    assert not _find(reader.client.get("/kb/"), "a", data_action="kb-new-article")

    kb.make_published(author=editor.user)
    assert not _find(reader.client.get("/kb/"), data_empty_state="kb")
    assert not _find(editor.client.get("/kb/"), data_empty_state="kb")


def test_home_query_count_does_not_grow_with_rubrics():
    """FR-421: число запросов главной не растёт с числом рубрик и статей (число статей по рубрикам — один запрос с
    группировкой): при 3 и при 33 рубриках запросов не больше, чем было."""
    author = kb.as_editor().user
    reader = kb.as_reader()
    tree = kb.rubric_tree({"Сети": {"VPN": {}}, "Почта": {}})
    for rubric in tree.values():
        kb.make_published(rubric=rubric, author=author, vectors=False)
    reader.client.get("/kb/")  # прогрев: сессия, права, кэши

    def measure() -> tuple[int, object]:
        with CaptureQueriesContext(connection) as context:
            response = reader.client.get("/kb/")
        assert response.status_code == 200
        return len(context), response

    small, _ = measure()
    for number in range(30):
        parent = tree["Сети"] if number % 3 == 0 else (tree["VPN"] if number % 3 == 1 else None)
        rubric = kb.make_rubric(f"Новая рубрика {number}", parent=parent)
        for _ in range(2):
            kb.make_published(rubric=rubric, author=author, vectors=False)
    large, response = measure()

    rows = [n for n in _dom(response) if n.tag == "li" and "data-rubric-id" in n.attrs]
    assert len(rows) >= 33, "на главной все рубрики"
    assert large <= small, f"запросов главной: было {small}, стало {large} при росте числа рубрик"


# --- ввод только параметрами (NFR-408) -----------------------------------------------------------------------

def test_tag_with_quote_percent_underscore_backslash_semicolon_dashes_is_plain_text_in_normalize_suggest_and_tag_page():
    """FR-420, NFR-408: теги с `'`, `"`, `%`, `_`, `\\`, `;`, `--` — обычный текст: `normalize` их не меняет (кроме
    регистра), подсказка не принимает `%` и `_` за шаблон, страница тега находит ровно свою статью, таблицы целы."""
    author = kb.as_editor()
    reader = kb.as_reader()
    tricky = ["o'brien", 'say "hi"', "100%", "a_b", "back\\slash", "semi;colon", "--dash", "x'; drop table knowledge_tag; --"]
    decoys = ["1000x", "axb", "backXslash", "semiXcolon"]
    articles = {name: kb.make_published(author=author.user, tags=[name]) for name in tricky}
    kb.make_published(author=author.user, tags=decoys)
    Tag = support.model("knowledge.Tag")
    tags = _tags()

    assert tags.normalize(", ".join(n.upper() for n in tricky if "," not in n)) == [n.lower() for n in tricky]
    total = Tag.objects.count()

    assert tags.suggest("100%") == ["100%"], "знак % — часть имени, не шаблон"
    assert tags.suggest("a_") == ["a_b"], "знак _ — часть имени, не шаблон"
    assert tags.suggest("back\\") == ["back\\slash"]
    assert tags.suggest("x'; drop") == ["x'; drop table knowledge_tag; --"]
    assert tags.suggest("%") == [], "ни один тег не начинается со знака %"
    assert tags.suggest("'") == [], "ни один тег не начинается с апострофа"
    for name in tricky:
        got = _suggested(_suggest(author, name[:6]))
        assert name in got, f"подсказка {name[:6]!r} должна найти {name!r}"
        page = _tag_page(reader, name)
        assert page.status_code == 200, f"страница тега {name!r}"
        assert _list_ids(page) == [articles[name].pk]
    assert _suggested(_suggest(author, "100%")) == ["100%"]
    assert _suggested(_suggest(author, "a_")) == ["a_b"]
    assert Tag.objects.count() == total, "запросы не меняют таблицу тегов"
