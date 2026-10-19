"""T-5102: рендер Markdown, безопасный вывод, предпросмотр, комментарии без разметки (FR-402, FR-403, FR-425,
NFR-403, NFR-405, NFR-406). Сценарии 1 и 5 спеки.

`render.render(text, files, article_id)` вызывается напрямую; белый список, пробы и условия строк — раздел 6.1 и 6.2
CONTRACT-005. Вывод разбирается `html.parser` в дерево (теги, атрибуты, вложенность), поэтому проверки не зависят от
порядка атрибутов и от точной записи. Предпросмотр — `POST /kb/preview/` (раздел 10.2), замок `kb:preview:<user_id>`
в Valkey (раздел 5.8). Код среза на уровне модуля не импортируется: имена берутся внутри тестов.
"""
import re
import time
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_kb as kb

TAGS = {"p", "br", "strong", "em", "del", "code", "pre", "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5",
        "h6", "hr", "a", "img", "table", "thead", "tbody", "tr", "th", "td", "div", "span"}
ATTRS = {"a": {"href", "title", "rel", "target"}, "img": {"src", "alt", "loading"}, "div": {"class"},
         "span": {"class"}, "th": {"class"}, "td": {"class"}}
VOID = {"br", "img", "hr", "input", "meta", "link"}
ARTICLE = 7
FILES = {1: ("схема", "png"), 2: ("рисунок", "jpeg"), 3: ("инструкция.pdf", "")}
NOIMG = "[вложение недоступно: {}]"


# --- разбор вывода рендера ----------------------------------------------------------------------------

class Node:
    def __init__(self, tag: str, attrs: dict, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def classes(self) -> set:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        """Текст внутри узла; `br` — перевод строки."""
        out = []
        for child in self.children:
            if isinstance(child, str):
                out.append(child)
            elif child.tag == "br":
                out.append("\n")
            else:
                out.append(child.text())
        return "".join(out)

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find_all(self, tag: str | None = None, cls: str | None = None, attr: str | None = None) -> list:
        return [n for n in self.walk()
                if (tag is None or n.tag == tag) and (cls is None or cls in n.classes())
                and (attr is None or attr in n.attrs)]

    def signature(self):
        return (self.tag, tuple(sorted(self.attrs.items())), _signature(self.children))


def _signature(children) -> tuple:
    out = []
    for child in children:
        if isinstance(child, str):
            if child.strip():
                out.append(child.strip())
        else:
            out.append(child.signature())
    return tuple(out)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.cur = self.root
        self.comments: list[str] = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {name: (value if value is not None else "") for name, value in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {name: (value if value is not None else "") for name, value in attrs}, self.cur)
        self.cur.children.append(node)

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)

    def handle_comment(self, data):
        self.comments.append(data)


def parse(html: str) -> Node:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    parser.root.comments = parser.comments
    return parser.root


def render(text: str, files=FILES, article_id=ARTICLE):
    from apps.knowledge.services import render as module

    return module.render(text, files, article_id)


def assert_safe(html: str, article_id: int = ARTICLE) -> Node:
    """Общие запреты раздела 6.2: теги и атрибуты только из белого списка, адреса по правилам, `rel` у внешних."""
    assert isinstance(html, str)
    tree = parse(html)
    assert not tree.comments, f"комментарий HTML в выводе: {tree.comments}"
    for node in tree.walk():
        assert node.tag in TAGS, f"тег {node.tag} вне белого списка: {html[:300]}"
        names = set(node.attrs)
        assert names <= ATTRS.get(node.tag, set()), f"атрибуты {names - ATTRS.get(node.tag, set())} у {node.tag}"
        assert not any(n.startswith("on") or n in ("style", "srcset") for n in names), names
        if "class" in node.attrs:
            words = node.attrs["class"].split()
            assert words and all(w.startswith("kb-") for w in words), f"класс вне kb-*: {node.attrs['class']}"
        if node.tag == "img":
            assert re.fullmatch(rf"/kb/{article_id}/images/\d+/", node.attrs.get("src", "")), node.attrs
        if node.tag == "a":
            _assert_link(node, article_id)
    return tree


def _assert_link(node: Node, article_id: int) -> None:
    href = node.attrs.get("href")
    assert href is not None, f"ссылка без href: {node.attrs}"
    rel = set((node.attrs.get("rel") or "").split())
    if re.fullmatch(rf"/kb/{article_id}/files/\d+/", href):
        assert "rel" not in node.attrs and "target" not in node.attrs, node.attrs
    elif href.lower().startswith(("http://", "https://", "mailto:")):
        assert {"noopener", "noreferrer"} <= rel, f"внешняя ссылка без rel: {node.attrs}"
        assert node.attrs.get("target") == "_blank", f"внешняя ссылка без target: {node.attrs}"
    elif href.startswith("/") and not href.startswith("//") and "\\" not in href \
            and not re.search(r"[\s\x00-\x1f]", href):
        assert "rel" not in node.attrs and "target" not in node.attrs, f"у внутренней ссылки rel/target: {node.attrs}"
    else:
        raise AssertionError(f"недопустимый href: {href!r}")


def noimg_texts(tree: Node) -> list[str]:
    return [n.text() for n in tree.find_all("span", cls="kb-noimg")]


def paragraph_texts(tree: Node) -> list[str]:
    return [n.text() for n in tree.find_all("p")]


def literal(tree: Node, expected: str) -> None:
    """Вход остался буквальным текстом: ссылки и картинки нет, строка есть в тексте вывода."""
    assert not tree.find_all("a"), "ссылка не должна появиться"
    assert not tree.find_all("img"), "картинка не должна появиться"
    assert expected in tree.text(), f"нет буквального текста {expected!r} в {tree.text()!r}"


def attrs_of(html: str, tag: str) -> list[dict]:
    return [n.attrs for n in parse(html).find_all(tag)]


# --- 36 проб (раздел 6.2) -----------------------------------------------------------------------------

def _escaped_text(source: str):
    def check(tree, html):
        assert not tree.find_all("a") and not tree.find_all("img")
        assert source in paragraph_texts(tree), f"{source!r} не остался текстом абзаца: {paragraph_texts(tree)!r}"
    return check


def _plain_text(source: str, *, exact: bool = True):
    def check(tree, html):
        literal(tree, source)
        if exact:
            assert tree.text().strip() == source, tree.text()
    return check


def _no_link_text(fragment: str):
    def check(tree, html):
        assert not tree.find_all("a"), "ссылки быть не должно"
        assert fragment in tree.text()
    return check


def _noimg(caption: str):
    def check(tree, html):
        assert not tree.find_all("img"), "картинки быть не должно"
        assert noimg_texts(tree) == [NOIMG.format(caption)], noimg_texts(tree)
    return check


def _p14(tree, html):
    links = tree.find_all("a")
    for link in links:
        href = link.attrs["href"]
        assert href.startswith("/") and not href.startswith("//") and "\\" not in href, href
    if not links:
        assert "evil.com" in tree.text()


def _p16(tree, html):
    (link,) = tree.find_all("a")
    assert link.attrs["href"] == "http://ok.example/a?b=1"
    assert set(link.attrs["rel"].split()) == {"noopener", "noreferrer"} and link.attrs["target"] == "_blank"


def _p19(tree, html):
    (link,) = tree.find_all("a")
    assert set(link.attrs) <= {"href", "title", "rel", "target"}, link.attrs
    assert link.attrs["title"] == 't" onmouseover="alert(1)', link.attrs


def _p20(tree, html):
    (link,) = tree.find_all("a")
    assert "%22" in link.attrs["href"] and '"' not in link.attrs["href"], link.attrs["href"]


def _p21(tree, html):
    assert "<script>alert(1)</script> <b>" in tree.text(), tree.text()
    assert not tree.find_all("script") and not tree.find_all("b")


def _p22(tree, html):
    (table,) = tree.find_all("table")
    assert table.parent.tag == "div" and "kb-scroll" in table.parent.classes()
    heads = [n.text().strip() for n in table.find_all("th")]
    cells = [n.text().strip() for n in table.find_all("td")]
    assert heads == ["a", "<b onclick=x>b</b>"], heads
    assert cells == ["<script>1</script>", "[y](javascript:1)"], cells
    assert not table.find_all("a") and not table.find_all("b") and not table.find_all("script")


def _p25(tree, html):
    assert not tree.find_all("img") and not noimg_texts(tree), "нет ни картинки, ни заглушки"
    assert "![x](data:image/svg+xml;base64,PHN2Zz4=)" in tree.text(), tree.text()


def _own_img(file_no: int, caption: str):
    def check(tree, html):
        (img,) = tree.find_all("img")
        assert img.attrs == {"src": f"/kb/{ARTICLE}/images/{file_no}/", "alt": caption, "loading": "lazy"}, img.attrs
        assert not noimg_texts(tree)
    return check


def _p31(tree, html):
    (img,) = tree.find_all("img")
    assert img.attrs["alt"] == 'a" onerror="x', img.attrs
    assert img.attrs["src"] == f"/kb/{ARTICLE}/images/1/"
    assert set(img.attrs) == {"src", "alt", "loading"}


def _p32(tree, html):
    (link,) = tree.find_all("a")
    assert link.attrs == {"href": f"/kb/{ARTICLE}/files/3/"}, link.attrs
    assert link.text() == "f"


def _p34(tree, html):
    (inline,) = [c for c in tree.find_all("code") if c.parent.tag != "pre"]
    assert inline.text() == "<b>"
    (pre,) = tree.find_all("pre")
    assert "<script>x</script>" in pre.text()
    assert pre.parent.tag == "div" and "kb-scroll" in pre.parent.classes()
    assert not tree.find_all("b") and not tree.find_all("script")


def _p35(tree, html):
    (table,) = tree.find_all("table")
    for row_tag in ("th", "td"):
        cells = table.find_all(row_tag)
        assert len(cells) == 2
        assert "kb-al-left" in cells[0].classes() and "kb-al-right" in cells[1].classes(), [c.attrs for c in cells]
    assert "style" not in html and "text-align" not in html


def _p36(tree, html):
    (quote,) = tree.find_all("blockquote")
    assert quote.find_all("strong")
    assert tree.find_all("h1") and tree.find_all("ol") and tree.find_all("ul")
    assert len(tree.find_all("ol")[0].find_all("li")) == 2 and len(tree.find_all("ul")[0].find_all("li")) == 1


def _p33_for(mail: str):
    def check(tree, html):
        links = {n.text(): n for n in tree.find_all("a")}
        assert set(links) == {"ok", "m", "h"}, set(links)
        assert links["ok"].attrs == {"href": "/kb/3/"}, links["ok"].attrs
        assert links["m"].attrs["href"] == "mailto:" + mail and links["h"].attrs["href"] == "https://e.example/"
        for name in ("m", "h"):
            assert set(links[name].attrs["rel"].split()) == {"noopener", "noreferrer"}
            assert links[name].attrs["target"] == "_blank"
    return check


def _p5(tree, html):
    assert '<div style="x" onclick="y">hi</div>' in paragraph_texts(tree), paragraph_texts(tree)
    assert "text" in paragraph_texts(tree) and not tree.find_all("div")


def _p17_for(mail: str):
    def check(tree, html):
        (link,) = tree.find_all("a")
        assert link.attrs["href"] == "mailto:" + mail, link.attrs
    return check


def _p23(tree, html):
    assert not tree.find_all("a")
    assert "[x][1]" in tree.text() and "[1]: javascript:alert(1)" in tree.text(), tree.text()


def probes() -> list[tuple[int, str, object]]:
    mail = kb.email_of("ivanov", "example.test")
    p = [
        (1, "<script>alert(1)</script>", _escaped_text("<script>alert(1)</script>")),
        (2, "<img src=x onerror=alert(1)>", _escaped_text("<img src=x onerror=alert(1)>")),
        (3, "<svg onload=alert(1)></svg>", _escaped_text("<svg onload=alert(1)></svg>")),
        (4, "<iframe src=//evil></iframe>", _escaped_text("<iframe src=//evil></iframe>")),
        (5, '<div style="x" onclick="y">hi</div>\n\ntext', _p5),
        (6, "<!-- x --> a", _escaped_text("<!-- x --> a")),
        (7, "[x](javascript:alert(1))", _plain_text("[x](javascript:alert(1))")),
        (8, "[x](JaVaScRiPt:alert(1))", _plain_text("[x](JaVaScRiPt:alert(1))")),
        (9, "[x](jav&#x61;script:alert(1))", _no_link_text("[x](")),
        (10, "[x](java\tscript:alert(1))", _no_link_text("[x](java")),
        (11, "[x](vbscript:msgbox(1))", _plain_text("[x](vbscript:msgbox(1))")),
        (12, "[x](data:text/html;base64,PHNjcmlwdD4=)", _plain_text("[x](data:text/html;base64,PHNjcmlwdD4=)")),
        (13, "[x](//evil.com/a)", _plain_text("[x](//evil.com/a)")),
        (14, "[x](/\\evil.com)", _p14),
        (15, "<javascript:alert(1)>", _no_link_text("javascript:alert(1)")),
        (16, "<http://ok.example/a?b=1>", _p16),
        (17, "<" + mail + ">", _p17_for(mail)),
        (18, "http://bare.example/x", _plain_text("http://bare.example/x")),
        (19, '[x](http://a.example "t\\" onmouseover=\\"alert(1)")', _p19),
        (20, '[x](http://a.example/"onmouseover="alert(1))', _p20),
        (21, "&lt;script&gt;alert(1)&lt;/script&gt; &#60;b&#62;", _p21),
        (22, "| a | <b onclick=x>b</b> |\n|---|---|\n| <script>1</script> | [y](javascript:1) |", _p22),
        (23, "[x][1]\n\n[1]: javascript:alert(1)", _p23),
        (24, "![x](http://evil.example/p.png)", _noimg("x")),
        (25, "![x](data:image/svg+xml;base64,PHN2Zz4=)", _p25),
        (26, "![x](/kb/8/files/1/)", _noimg("x")),
        (27, "![x](/kb/7/files/2/)", _noimg("x")),
        (28, "![x](att:99)", _noimg("x")),
        (29, "![схема](att:1)", _own_img(1, "схема")),
        (30, "![рисунок](att:2)", _own_img(2, "рисунок")),
        (31, '![a" onerror="x](att:1)', _p31),
        (32, "[f](att:3)", _p32),
        (33, f"[ok](/kb/3/) [m](mailto:{mail}) [h](https://e.example/)", _p33_for(mail)),
        (34, "`<b>` and\n\n```\n<script>x</script>\n```\n", _p34),
        (35, "|a|b|\n|:-|-:|\n|1|2|", _p35),
        (36, "> **q**\n\n# H\n\n1. a\n2. b\n\n- c", _p36),
    ]
    assert [row[0] for row in p] == list(range(1, 37))
    return p


# --- сохранение статьи и предпросмотр: помощники ---------------------------------------------------------

def _saved_article_with_file(author, text_with_image):
    """Статья, сохранённая службами: создание, вложение, правка с текстом, который ссылается на вложение."""
    from apps.knowledge.services import articles

    article = articles.create(
        author, articles.ArticleForm(title="Образец", text="пусто", rubric_id=kb.general_rubric().pk, tags=""))
    attached = kb.attach_file(article, "схема.png", status="clean")
    text = text_with_image.format(n=attached.pk)
    result = articles.save(
        author, article.pk, 1, articles.ArticleForm(
            title="Образец", text=text, rubric_id=kb.general_rubric().pk, tags=""))
    assert result.kind == "saved", result.kind
    article.refresh_from_db()
    return article, attached, text


def _preview(client, text: str, article=None):
    data = {"text": text}
    if article is not None:
        data["article"] = article.pk
    return client.post("/kb/preview/", data)


def _preview_nodes(response, attr: str) -> list[Node]:
    return parse(response.content.decode()).find_all(attr=attr)


def _contains_signature(tree: Node, wanted: tuple) -> bool:
    """В дереве есть узел, чьи дети (без пустых строк) в точности равны `wanted`."""
    return any(_signature(node.children) == wanted for node in [tree, *tree.walk()])


# --- 36 проб и общие запреты ------------------------------------------------------------------------------

def test_render_36_probes_output_has_no_tags_or_attributes_outside_whitelist():
    """FR-402, NFR-405: все 36 проб F1 Ф5 (раздел 6.2) — общие запреты и условие каждой строки."""
    rows = probes()
    assert len(rows) == 36
    for number, source, check in rows:
        result = render(source)
        assert isinstance(result.html, str) and isinstance(result.plain, str), number
        try:
            tree = assert_safe(result.html)
            check(tree, result.html)
        except AssertionError as exc:
            raise AssertionError(f"проба {number} {source!r}: {exc}\nвывод: {result.html}") from exc


def test_render_script_tag_and_javascript_link_are_inert_text_not_executable():
    """FR-402, NFR-405: тег script и ссылка javascript: остаются текстом; сырой `<a href=javascript:…>` не оживает."""
    source = '<script>alert(1)</script>\n\n[клик](javascript:alert(1))\n\n<a href="javascript:alert(2)">z</a>'
    html = render(source).html
    tree = assert_safe(html)
    assert "<script" not in html.lower()
    assert not tree.find_all("script") and not tree.find_all("a")
    texts = paragraph_texts(tree)
    assert "<script>alert(1)</script>" in texts
    assert "[клик](javascript:alert(1))" in texts
    assert '<a href="javascript:alert(2)">z</a>' in texts


def test_render_data_vbscript_and_scheme_relative_links_are_not_links():
    """FR-402, NFR-405: data:, vbscript:, //хост и /\\хост не дают ссылки; запись остаётся буквальным текстом."""
    for source in ("[a](data:text/html,x)", "[b](vbscript:x)", "[c](//evil.example/x)"):
        tree = assert_safe(render(source).html)
        literal(tree, source)
    tree = assert_safe(render("[d](/\\evil.example)").html)
    for link in tree.find_all("a"):
        assert "\\" not in link.attrs["href"] and not link.attrs["href"].startswith("//"), link.attrs
    combined = assert_safe(render("[a](data:text/html,x) [b](vbscript:x) [c](//evil.example/x)").html)
    assert not combined.find_all("a")


def test_render_quotes_in_link_title_and_image_alt_do_not_break_out_of_attributes():
    """NFR-405: кавычки в title ссылки и alt картинки остаются внутри значения, лишних атрибутов нет."""
    html = render('[t](http://a.example "x\\" onfocus=\\"y") ![q" onerror="z](att:1) [u](http://a.example/\'x)').html
    tree = assert_safe(html)
    links = tree.find_all("a")
    assert links[0].attrs["title"] == 'x" onfocus="y', links[0].attrs
    (img,) = tree.find_all("img")
    assert img.attrs["alt"] == 'q" onerror="z' and set(img.attrs) == {"src", "alt", "loading"}, img.attrs
    for node in tree.walk():
        assert not any(name.startswith("on") for name in node.attrs), node.attrs


def test_render_external_link_has_rel_noopener_noreferrer_and_target_blank():
    """FR-402: внешняя ссылка (https, http, mailto, автоссылка) — rel="noopener noreferrer" и target="_blank"."""
    mail = kb.email_of("petrov", "example.test")
    source = f"[a](https://e.example/x) [b](http://e.example/) [m](mailto:{mail}) <https://auto.example/>"
    tree = assert_safe(render(source).html)
    links = tree.find_all("a")
    assert [n.attrs["href"] for n in links] == [
        "https://e.example/x", "http://e.example/", "mailto:" + mail, "https://auto.example/"]
    for link in links:
        assert set(link.attrs["rel"].split()) == {"noopener", "noreferrer"}, link.attrs
        assert link.attrs["target"] == "_blank", link.attrs


def test_render_root_path_and_https_links_are_kept():
    """FR-402: путь от корня и https сохраняются; внутренняя ссылка — без rel и target."""
    tree = assert_safe(render("[a](/kb/3/) [b](/tickets/5/?x=1) [c](https://e.example/p?q=1&r=2)").html)
    links = tree.find_all("a")
    assert [n.attrs["href"] for n in links] == ["/kb/3/", "/tickets/5/?x=1", "https://e.example/p?q=1&r=2"]
    for link in links[:2]:
        assert "rel" not in link.attrs and "target" not in link.attrs, link.attrs
    assert links[2].attrs["target"] == "_blank"


def test_render_att_link_of_own_article_becomes_files_url():
    """FR-402: `[имя](att:N)` своей статьи — ссылка на `/kb/<id>/files/N/` без rel и target."""
    tree = assert_safe(render("[инструкция](att:3) и [схема](att:1)").html)
    links = tree.find_all("a")
    assert [(n.text(), n.attrs) for n in links] == [
        ("инструкция", {"href": f"/kb/{ARTICLE}/files/3/"}), ("схема", {"href": f"/kb/{ARTICLE}/files/1/"})]
    other = assert_safe(render("[инструкция](att:3)", FILES, 12).html, 12)
    assert other.find_all("a")[0].attrs == {"href": "/kb/12/files/3/"}


def test_render_att_image_of_own_article_becomes_images_url_with_lazy_loading():
    """FR-402: `![имя](att:N)` своей статьи — img на `/kb/<id>/images/N/` с alt и loading="lazy", без /files/."""
    html = render("![схема](att:1)\n\n![рисунок](att:2)").html
    tree = assert_safe(html)
    assert [n.attrs for n in tree.find_all("img")] == [
        {"src": f"/kb/{ARTICLE}/images/1/", "alt": "схема", "loading": "lazy"},
        {"src": f"/kb/{ARTICLE}/images/2/", "alt": "рисунок", "loading": "lazy"}]
    assert not noimg_texts(tree) and "/files/" not in html
    other = render("![схема](att:1)", FILES, 12).html
    assert attrs_of(other, "img")[0]["src"] == "/kb/12/images/1/"


def test_render_att_of_foreign_article_gives_unavailable_placeholder():
    """FR-402, NFR-405: att:N вне files (чужое, удалённое, без номера статьи) — заглушка в span.kb-noimg."""
    tree = assert_safe(render("![рис](att:99)\n\n[имя](att:99)").html)
    assert not tree.find_all("img") and not tree.find_all("a")
    assert noimg_texts(tree) == [NOIMG.format("рис"), NOIMG.format("имя")]
    assert all(n.tag == "span" for n in tree.find_all(cls="kb-noimg"))
    empty = assert_safe(render("![рис](att:1)", {}).html)
    assert noimg_texts(empty) == [NOIMG.format("рис")] and not empty.find_all("img")
    unsaved = assert_safe(render("![рис](att:1)", FILES, None).html)
    assert noimg_texts(unsaved) == [NOIMG.format("рис")] and not unsaved.find_all("img")
    escaped = assert_safe(render("![<b>х](att:99)").html)
    assert not escaped.find_all("b") and noimg_texts(escaped) == [NOIMG.format("<b>х")]


def test_render_direct_kb_path_and_external_image_give_unavailable_placeholder():
    """FR-402, NFR-405: прямой путь /kb/…, чужой путь и внешний адрес картинки — заглушка, img нет."""
    cases = {"а": "/kb/8/files/1/", "б": "/kb/7/files/2/", "в": "/kb/7/images/1/", "г": "https://e.example/p.png",
             "д": "http://e.example/p.png"}
    for caption, address in cases.items():
        tree = assert_safe(render(f"![{caption}]({address})").html)
        assert not tree.find_all("img"), address
        assert noimg_texts(tree) == [NOIMG.format(caption)], (address, noimg_texts(tree))


def test_render_table_alignment_uses_kb_al_class_and_no_style_attribute():
    """FR-402, NFR-405: выравнивание столбцов — классы kb-al-left, kb-al-center, kb-al-right; `style` нигде нет."""
    html = render("| a | b | c |\n|:-|:-:|-:|\n| 1 | 2 | 3 |").html
    tree = assert_safe(html)
    (table,) = tree.find_all("table")
    for tag in ("th", "td"):
        cells = table.find_all(tag)
        assert [sorted(c.classes()) for c in cells] == [["kb-al-left"], ["kb-al-center"], ["kb-al-right"]], tag
    assert "style" not in html and "text-align" not in html


def test_render_table_and_code_block_are_wrapped_in_kb_scroll():
    """NFR-406: таблица и блок кода — в div.kb-scroll; абзац, цитата, список и встроенный код — без оболочки."""
    source = "Абзац `inline`\n\n| a | b |\n|-|-|\n| 1 | 2 |\n\n```\nблок\n```\n\n> цитата\n\n- пункт"
    tree = assert_safe(render(source).html)
    divs = tree.find_all("div")
    assert len(divs) == 2 and all("kb-scroll" in d.classes() for d in divs), [d.attrs for d in divs]
    assert sorted(child.tag for d in divs for child in d.children if isinstance(child, Node)) == ["pre", "table"]
    (table,) = tree.find_all("table")
    (pre,) = tree.find_all("pre")
    assert table.parent in divs and pre.parent in divs
    for tag in ("p", "blockquote", "ul"):
        assert all(n.parent.tag != "div" for n in tree.find_all(tag)), tag


def test_render_deep_nesting_does_not_crash_and_output_stays_safe():
    """FR-402, NFR-405: 200 вложенных цитат и скобок не роняют рендер (maxNesting=20) и не дают небезопасного вывода."""
    inputs = [
        "> " * 200 + "текст",
        "> " * 200 + "<script>alert(1)</script>",
        "[" * 200 + "a" + "]" * 200 + "(javascript:alert(1))",
        "(" * 200 + "[x](javascript:alert(1))" + ")" * 200,
        "*" * 200 + "a" + "*" * 200,
    ]
    for source in inputs:
        result = render(source)
        tree = assert_safe(result.html)
        assert not tree.find_all("script") and not tree.find_all("a"), source[:40]
        assert isinstance(result.plain, str)


def test_render_second_nh3_filter_strips_foreign_src_href_and_non_kb_class():
    """NFR-405: второй фильтр (`render.sanitize`, п. 32 раздела 17) вырезает чужой src, чужое вложение в href и класс вне kb-*."""
    from apps.knowledge.services import render as module

    html = (
        '<p class="evil kb-ok" onclick="x" style="color:red">'
        '<span class="evil">s</span> <img src="/kb/8/images/1/" class="evil" alt="чужая"> '
        '<img src="https://e.example/x.png" alt="внешняя"> <img src="/kb/7/images/1/" alt="своя" loading="lazy"> '
        '<a href="/kb/8/files/1/" class="evil">чужой</a> <a href="/kb/7/files/2/">свой</a> '
        '<a href="javascript:alert(1)">js</a> <a href="//e.example/x">схема</a> '
        '<a href="https://e.example/y" rel="noopener noreferrer" target="_blank">внешний</a>'
        '<div class="kb-scroll evil">d</div></p><script>alert(1)</script>'
    )
    out = module.sanitize(html, ARTICLE)
    assert isinstance(out, str)
    tree = parse(out)
    nodes = list(tree.walk())
    assert not tree.find_all("script") and "alert(1)" not in out
    for node in nodes:
        assert node.tag in TAGS, node.tag
        assert not any(n.startswith("on") or n in ("style", "srcset") for n in node.attrs), node.attrs
        if "class" in node.attrs:
            words = node.attrs["class"].split()
            assert words and all(w.startswith("kb-") for w in words), node.attrs["class"]
    assert "evil" not in " ".join(" ".join(n.classes()) for n in nodes)
    assert any("kb-ok" in n.classes() for n in nodes if n.tag == "p"), "класс kb-* вырезан"
    assert any("kb-scroll" in n.classes() for n in nodes if n.tag == "div"), "класс kb-scroll вырезан"
    assert "/kb/8/" not in out, "чужой номер статьи остался в выводе"
    assert [n.attrs["src"] for n in tree.find_all("img") if "src" in n.attrs] == [f"/kb/{ARTICLE}/images/1/"]
    hrefs = [n.attrs["href"] for n in tree.find_all("a") if "href" in n.attrs]
    assert sorted(hrefs) == sorted([f"/kb/{ARTICLE}/files/2/", "https://e.example/y"]), hrefs


def test_render_plain_has_no_link_urls_no_title_and_keeps_code_and_image_captions():
    """FR-402: plain — текст, код и подписи картинок; без адресов ссылок, title и att:; блоки и ячейки по строкам."""
    source = ("# Раздел\n\nТекст [ссылка](https://e.example/path \"подсказка\") и `встроенный`\n\n"
              "![подпись](att:1)\n\n| яч1 | яч2 |\n|-|-|\n| яч3 | яч4 |\n\n```\nблок кода\n```\n")
    plain = render(source).plain
    assert isinstance(plain, str)
    for wanted in ("ссылка", "встроенный", "подпись", "блок кода", "Текст"):
        assert wanted in plain, wanted
    for banned in ("e.example", "https", "подсказка", "att:", "](", "http"):
        assert banned not in plain, banned
    lines = [line.strip() for line in plain.splitlines()]
    for cell in ("яч1", "яч2", "яч3", "яч4"):
        assert cell in lines, f"ячейка {cell} не на своей строке: {lines}"
    assert "блок кода" in lines and "подпись" in lines


def test_render_plain_is_truncated_to_100000_characters():
    """FR-402: plain обрезается до 100 000 знаков: ровно 100 000 остаётся, 100 001 даёт 100 000."""
    assert render("a" * 100_000).plain == "a" * 100_000
    assert render("a" * 100_001).plain == "a" * 100_000
    assert len(render("a" * 99_999).plain) <= 100_000
    assert render("b" * 150_000).plain == "b" * 100_000


# --- предпросмотр -----------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_preview_is_post_only_and_requires_edit_right():
    """FR-403: POST /kb/preview/ — аноним 302 на вход, читатель 403, редактор и менеджер 200; GET — 405."""
    anonymous = support.make_client()
    response = anonymous.post("/kb/preview/", {"text": "x"})
    assert response.status_code == 302 and response["Location"].startswith("/login/"), response.status_code
    assert kb.as_reader().client.post("/kb/preview/", {"text": "**x**"}).status_code == 403
    for session in (kb.as_editor(), kb.as_manager()):
        ok = session.client.post("/kb/preview/", {"text": "**жирный**"})
        assert ok.status_code == 200
        (box,) = _preview_nodes(ok, "data-kb-preview")
        assert [n.text() for n in box.find_all("strong")] == ["жирный"]
        assert session.client.get("/kb/preview/").status_code == 405


@pytest.mark.django_db
def test_preview_html_equals_html_of_saved_article_for_same_text_and_files():
    """FR-403: html предпросмотра для того же текста и тех же вложений равен html сохранённой статьи."""
    editor = kb.as_editor()
    body = ("# Заголовок\n\nТекст **жирный** [сайт](https://e.example/x) <b>сырой</b>\n\n![схема](att:{n})\n\n"
            "[файл](att:{n})\n\n| a | b |\n|:-|-:|\n| 1 | 2 |\n\n```\nкод\n```")
    article, attached, text = _saved_article_with_file(editor.user, body)
    assert article.html and f"/kb/{article.pk}/images/{attached.pk}/" in article.html
    response = _preview(editor.client, text, article)
    assert response.status_code == 200
    (box,) = _preview_nodes(response, "data-kb-preview")
    wanted = _signature(parse(article.html).children)
    assert wanted and _contains_signature(box, wanted), (
        f"html предпросмотра не равен html статьи.\nстатья: {article.html}\nпредпросмотр: {response.content.decode()}")
    without = _preview(editor.client, text)
    (plain_box,) = _preview_nodes(without, "data-kb-preview")
    assert not plain_box.find_all("img") and noimg_texts(plain_box), "без статьи вложений нет: картинка — заглушка"


@pytest.mark.django_db
def test_preview_does_not_save_article_or_create_version_so_typed_text_stays_with_author():
    """FR-403: предпросмотр ничего не пишет (ни статьи, ни версии, ни журнала) и не заменяет форму с введённым."""
    editor = kb.as_editor()
    article = kb.make_draft(author=editor.user, text="Старый текст")
    Article, Version = support.model("knowledge.Article"), support.model("knowledge.ArticleVersion")
    before = (Article.objects.count(), Version.objects.count(), support.audit_actions())
    response = _preview(editor.client, "Новый текст, ещё не сохранённый", article)
    assert response.status_code == 200 and _preview_nodes(response, "data-kb-preview")
    assert "Новый текст, ещё не сохранённый" in response.content.decode()
    assert 'data-form="kb-article"' not in response.content.decode(), "форму правки предпросмотр не заменяет"
    article.refresh_from_db()
    assert (article.text, article.version_no, article.updated_by_id) == ("Старый текст", 1, editor.user.pk)
    assert (Article.objects.count(), Version.objects.count(), support.audit_actions()) == before
    new_only = _preview(editor.client, "Текст без статьи")
    assert new_only.status_code == 200
    assert (Article.objects.count(), Version.objects.count()) == before[:2]


@pytest.mark.django_db
def test_preview_200000_chars_of_ordinary_text_renders_within_one_second():
    """NFR-403, FR-403: 200 000 знаков обычного текста — предпросмотр не дольше 1 с (прогрев — до замера)."""
    editor = kb.as_editor()
    unit = ("Обычный абзац про **VPN** и почту: перечень шагов, ссылка [портал](https://e.example/a) и `код`.\n\n"
            "- пункт один\n- пункт два\n\n")
    text = (unit * (200_000 // len(unit) + 1))[:200_000]
    assert len(text) == 200_000
    assert _preview(editor.client, "прогрев **текст**").status_code == 200
    # предел — на самом рендере, лучшее из трёх запусков (решение 38 задач); запрос целиком — без предела времени
    render(text)
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        result = render(text)
        timings.append(time.perf_counter() - started)
    assert len(parse(result.html).find_all("li")) > 1000, "текст не отрисован"
    assert min(timings) <= 1.0, f"render.render на 200 000 знаков: {min(timings):.2f} с (предел NFR-403 — 1 с)"
    response = _preview(editor.client, text)
    assert response.status_code == 200
    (box,) = _preview_nodes(response, "data-kb-preview")
    assert len(box.find_all("li")) > 1000, "текст не отрисован в предпросмотре"


@pytest.mark.django_db
def test_second_concurrent_preview_of_same_user_gets_already_preparing_message():
    """FR-403: пока замок kb:preview:<user_id> занят, второй предпросмотр — 200 «Предпросмотр уже готовится»."""
    from apps.core.services import valkey

    editor = kb.as_editor()
    with kb.preview_lock_busy(editor.user) as name:
        response = _preview(editor.client, "**жирный**")
        assert response.status_code == 200
        (busy,) = _preview_nodes(response, "data-kb-preview-busy")
        assert "Предпросмотр уже готовится" in busy.text()
        assert not _preview_nodes(response, "data-kb-preview") and "<strong>" not in response.content.decode()
        assert valkey.conn().exists(name), "проигравший запрос не снимает чужой замок"
    after = _preview(editor.client, "**жирный**")
    assert after.status_code == 200 and _preview_nodes(after, "data-kb-preview")


@pytest.mark.django_db
def test_preview_lock_is_released_after_response_and_next_preview_passes_at_once():
    """FR-403: после ответа ключ kb:preview:<user_id> снят; следующий предпросмотр проходит сразу."""
    from apps.core.services import valkey

    editor = kb.as_editor()
    name = f"kb:preview:{editor.user.pk}"
    first = _preview(editor.client, "первый")
    assert first.status_code == 200 and _preview_nodes(first, "data-kb-preview")
    assert not valkey.conn().exists(name), "замок остался после ответа"
    second = _preview(editor.client, "второй")
    assert second.status_code == 200
    assert _preview_nodes(second, "data-kb-preview") and not _preview_nodes(second, "data-kb-preview-busy")
    assert not valkey.conn().exists(name)


@pytest.mark.django_db
def test_preview_lock_is_released_when_render_raises(monkeypatch):
    """FR-403: если render.render поднял исключение, замок снят (finally) и следующий предпросмотр проходит."""
    from apps.core.services import valkey
    from apps.knowledge.services import render as render_module

    editor = kb.as_editor()
    name = f"kb:preview:{editor.user.pk}"
    real = render_module.render

    def boom(*args, **kwargs):
        raise RuntimeError("сбой рендера (тест)")

    monkeypatch.setattr(render_module, "render", boom)
    editor.client.raise_request_exception = False
    failed = _preview(editor.client, "любой текст")
    assert not valkey.conn().exists(name), "замок остался после сбоя рендера"
    monkeypatch.setattr(render_module, "render", real)
    again = _preview(editor.client, "любой текст")
    assert again.status_code == 200 and _preview_nodes(again, "data-kb-preview")
    assert not _preview_nodes(again, "data-kb-preview-busy")


# --- комментарии ---------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_comment_text_is_escaped_with_line_breaks_and_links_stay_plain_text():
    """FR-425, NFR-405: текст комментария экранирован, переносы строк — br, ссылки и разметка остаются текстом."""
    article = kb.make_published(title="Со своими комментариями")
    text = ("Первая <b>строка</b>\nВторая https://e.example/path и [x](https://e.example/y)\n"
            "<script>alert(1)</script>")
    comment = kb.make_comment(article, text=text)
    page = kb.as_reader().client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200
    tree = parse(page.content.decode())
    (row,) = [n for n in tree.find_all("li") if n.attrs.get("data-comment-id") == str(comment.pk)]
    (field,) = [n for n in row.find_all(attr="data-field") if n.attrs["data-field"] == "text"]
    assert not [n for n in field.walk() if n.tag != "br"], "в тексте комментария нет тегов, кроме br"
    assert len(field.find_all("br")) == 2, "две строки перевода → два br"
    shown = field.text()
    for wanted in ("Первая <b>строка</b>", "https://e.example/path", "[x](https://e.example/y)",
                   "<script>alert(1)</script>"):
        assert wanted in shown, wanted
    assert "<script>alert(1)</script>" not in page.content.decode()
