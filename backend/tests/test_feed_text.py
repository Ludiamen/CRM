"""T-7109: вывод текста ленты и безопасный вывод на странице (FR-609, FR-611, NFR-605).

`text.render_plain(text, people, link_staff) -> SafeString` и `text.snippet(text, limit, people=None) -> str`
(контракт 5.3). Допустимые теги и атрибуты вывода — по плану («Текст и упоминания», «Вывод»): `a` (`href`, `target`,
`rel`, `data-mention`), `span` (`data-mention`), `p`, `br`. Служба импортируется внутри тестов; адреса почты
собираются из частей (решение 23 задач).
"""
import importlib
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as sf

pytestmark = pytest.mark.django_db

ALLOWED_TAGS = {"a", "span", "p", "br"}
ALLOWED_ATTRS = {"href", "target", "rel", "data-mention"}
PROBES = (
    "<script>alert(1)</script>",
    "<b>жирный</b>",
    "javascript:alert(1)",
    '"><img src=x onerror=alert(1)>',
)


def _text():
    return importlib.import_module("apps.feed.services.text")


def render(text: str, people: dict | None = None, link_staff: bool = False) -> str:
    return str(_text().render_plain(text, people or {}, link_staff))


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

    def raw_text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, Node) else parts.append(child)

        collect(self)
        return "".join(parts)

    def text(self) -> str:
        return " ".join(self.raw_text().split())


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


def tree_of(html: str) -> Node:
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def _links(html: str) -> list[Node]:
    return _find(tree_of(html), "a")


def _assert_only_allowed_markup(html: str, context: str) -> None:
    for node in tree_of(html).walk():
        assert node.tag in ALLOWED_TAGS, f"{context}: тег <{node.tag}> вне допустимых"
        assert set(node.attrs) <= ALLOWED_ATTRS, f"{context}: атрибуты {set(node.attrs) - ALLOWED_ATTRS}"
        href = node.attrs.get("href", "")
        assert not href.strip().lower().startswith(("javascript:", "data:", "vbscript:")), context


# --- 1. render_plain: безопасность ---------------------------------------------------------------------------

def test_render_plain_evil_inputs_leave_only_allowed_tags_and_attributes():
    """FR-609, NFR-605: на злых входах в выводе остаются только допустимые теги и атрибуты, ссылок на `javascript:` нет."""
    evil = list(PROBES) + [
        "<img src=x onerror=alert(1)>",
        "<svg/onload=alert(1)>",
        '<a href="javascript:alert(1)">нажми</a>',
        "<iframe src=//example.test></iframe>",
        '<p onclick="alert(1)">абзац</p>',
        "&#x6A;avascript:alert(1)",
        '" onmouseover="alert(1)',
        "'><script>alert(1)</script>",
        "https://example.test/\"onmouseover=\"alert(1)",
        "https://example.test/'><script>alert(1)</script>",
        "<<script>script>alert(1)<</script>/script>",
        "&lt;script&gt;alert(1)&lt;/script&gt;",
        "\n".join(PROBES),
    ]
    for text in evil:
        for link_staff in (False, True):
            _assert_only_allowed_markup(render(text, {7: "Иван"}, link_staff), repr(text))
    mixed = render("Смотри https://example.test/a?x=1 и @[7] <b>вот</b>", {7: "Иван"}, True)
    _assert_only_allowed_markup(mixed, "смесь")
    assert "<b>" not in mixed and "&lt;b&gt;" in mixed


def test_https_url_becomes_link_with_blank_target_and_noopener_noreferrer():
    """FR-609, NFR-605: адрес `http(s)://` — ссылка в новой вкладке с `rel="noopener noreferrer"`; `&` в адресе экранирован."""
    for url in ("https://example.test/path?a=1&b=2", "http://example.test/", "https://example.test:8443/x#part"):
        html = render(f"Смотри {url} тут")
        (link,) = _links(html)
        assert link.attrs["href"] == url
        assert link.attrs["target"] == "_blank"
        assert set(link.attrs["rel"].split()) == {"noopener", "noreferrer"}
        assert link.text() == url
    assert "a=1&amp;b=2" in render("https://example.test/path?a=1&b=2")


def test_mailto_becomes_link_and_ftp_and_javascript_stay_text():
    """FR-609, NFR-605: `mailto:` — ссылка; `ftp:`, `javascript:`, `data:`, `www.` и голый домен остаются текстом."""
    address = sf.email_of("kolleg", "example.test")
    (link,) = _links(render(f"Пишите mailto:{address} сюда"))
    assert link.attrs["href"] == f"mailto:{address}"
    assert link.attrs["target"] == "_blank" and set(link.attrs["rel"].split()) == {"noopener", "noreferrer"}
    for plain in ("ftp://example.test/file", "javascript:alert(1)", "data:text/html,привет", "www.example.test",
                  "example.test/page", "file:///etc/hosts", "vbscript:msgbox(1)"):
        html = render(f"до {plain} после")
        assert _links(html) == [], plain
        assert plain in html, plain


def test_html_markup_in_text_shown_escaped():
    """FR-609, NFR-605: разметка в тексте показывается как текст: знаки `<`, `>`, `&`, `\"` экранированы."""
    html = render('<b>жирный</b> & <i>курсив</i> "кавычки"')
    assert "&lt;b&gt;жирный&lt;/b&gt;" in html and "&lt;i&gt;курсив&lt;/i&gt;" in html
    assert "&amp;" in html
    assert "<b>" not in html and "<i>" not in html
    tree = tree_of(html)
    assert tree.text() == '<b>жирный</b> & <i>курсив</i> "кавычки"'


def test_brackets_and_trailing_punctuation_left_outside_link():
    """FR-609: хвостовая пунктуация и несбалансированная «)» остаются вне ссылки; парная скобка внутри адреса — в ссылке."""
    for tail in (".", ",", ";", ":", "!", "?", "...", "?!"):
        html = render(f"Смотри https://example.test/a{tail} Дальше")
        (link,) = _links(html)
        assert link.attrs["href"] == "https://example.test/a", tail
        assert link.text() == "https://example.test/a", tail
    html = render("(см. https://example.test/a).")
    (link,) = _links(html)
    assert link.attrs["href"] == "https://example.test/a"
    assert tree_of(html).text().endswith(").")
    html = render("(https://example.test/a)")
    (link,) = _links(html)
    assert link.attrs["href"] == "https://example.test/a"
    html = render("https://example.test/wiki/Тест_(слово)")
    (link,) = _links(html)
    assert link.attrs["href"] == "https://example.test/wiki/Тест_(слово)"


def test_link_longer_than_2048_rendered_as_text():
    """FR-609, NFR-605: адрес длиннее 2048 знаков — текстом; ровно 2048 — ещё ссылка."""
    prefix = "https://example.test/"
    long_url = prefix + "a" * (2049 - len(prefix))
    assert len(long_url) == 2049
    html = render(f"до {long_url} после")
    assert _links(html) == [] and long_url in html
    edge = prefix + "a" * (2048 - len(prefix))
    assert len(edge) == 2048
    (link,) = _links(render(f"до {edge} после"))
    assert link.attrs["href"] == edge


def test_control_and_bidi_characters_removed_tab_newline_cr_kept():
    """FR-609, NFR-605: управляющие и двунаправленные символы удаляются; табуляция, перевод строки и CR остаются."""
    removed = ["\x00", "\x01", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x7f", "‪", "‫", "‬",
               "‭", "‮", "⁦", "⁧", "⁨", "⁩"]
    for char in removed:
        html = render(f"до{char}после")
        assert "допосле" in html, repr(char)
        assert char not in html, repr(char)
    assert "\t" in render("а\tб")
    assert "\r" in render("а\rб")
    assert "<br>" in render("а\nб") or "<br/>" in render("а\nб") or "<br />" in render("а\nб")


def test_paragraphs_become_p_and_single_newline_becomes_br():
    """FR-609: абзацы (пустая строка между ними) — `<p>`, одиночный перевод строки — `<br>` внутри абзаца."""
    html = render("один\nдва\n\nтри\n  \n\nчетыре")
    paragraphs = _find(tree_of(html), "p")
    assert len(paragraphs) == 3
    assert [part.strip() for part in paragraphs[0].children if isinstance(part, str)] == ["один", "два"]
    assert [paragraphs[1].text(), paragraphs[2].text()] == ["три", "четыре"]
    assert len(_find(paragraphs[0], "br")) == 1
    assert _find(paragraphs[1], "br") == [] and _find(paragraphs[2], "br") == []


# --- 2. render_plain: упоминания ----------------------------------------------------------------------------

def test_mention_marker_renders_staff_link_with_data_mention_for_staff_viewer():
    """FR-611: читателю с просмотром карточек сотрудников маркер даёт ссылку на `/staff/<id>/` с `data-mention`."""
    html = render("Привет @[7] и ещё раз @[7].", {7: "Иванов Иван"}, link_staff=True)
    links = _find(tree_of(html), "a", data_mention="7")
    assert len(links) == 2
    for link in links:
        assert link.attrs["href"] == "/staff/7/"
        assert link.text() == "Иванов Иван"
    assert "@[7]" not in html


def test_mention_marker_renders_span_for_reader_without_staff_view():
    """FR-611: читателю без права просмотра сотрудников маркер даёт `<span data-mention>` без ссылки."""
    html = render("Привет @[7]!", {7: "Иванов Иван"}, link_staff=False)
    (span,) = _find(tree_of(html), "span", data_mention="7")
    assert span.text() == "Иванов Иван"
    assert _find(tree_of(html), "a") == []
    assert "/staff/" not in html and "@[7]" not in html


def test_mention_name_with_markup_escaped_in_link_text():
    """FR-611, NFR-605: имя из словаря с разметкой экранируется и в ссылке, и в `<span>`."""
    name = '<b>Иван</b> "x" & <script>alert(1)</script>'
    for link_staff, tag in ((True, "a"), (False, "span")):
        html = render("до @[7] после", {7: name}, link_staff)
        _assert_only_allowed_markup(html, f"link_staff={link_staff}")
        (node,) = _find(tree_of(html), tag, data_mention="7")
        assert node.text() == name
        assert "<b>" not in html and "<script>" not in html and "&lt;b&gt;" in html


def test_unknown_mention_id_rendered_as_text():
    """FR-611: номер, которого нет в словаре, и неверные маркеры выводятся текстом."""
    html = render("до @[99] после", {7: "Иванов Иван"}, True)
    assert "@[99]" in html
    assert _find(tree_of(html), data_mention=True) == []
    for marker in ("@[0]", "@[01]", "@[1234567890]", "@[-5]", "@[abc]", "@[]"):
        html = render(f"до {marker} после", {0: "Ноль", 1: "Один", 1234567890: "Много"}, True)
        assert marker in html, marker
        assert _find(tree_of(html), data_mention=True) == [], marker


# --- 3. отрывок ----------------------------------------------------------------------------------------------

def test_snippet_replaces_marker_with_at_name_collapses_spaces_without_markup():
    """FR-609, FR-611: в отрывке маркер — «@ФИО», пробелы и переводы строк схлопнуты, разметки не создаётся."""
    feed_text = _text()
    result = feed_text.snippet("Привет  @[7]   вот\n\nтекст\tдальше", 100, {7: "Иванов Иван"})
    assert result == "Привет @Иванов Иван вот текст дальше"
    assert "<a" not in result and "<span" not in result and "@[7]" not in result
    assert feed_text.snippet("Ссылка https://example.test/a тут", 100) == "Ссылка https://example.test/a тут"
    # без словаря ФИО берутся из базы: один запрос на все маркеры
    first = support.make_employee(totp=False, full_name="Первый Сотрудник")
    second = support.make_employee(totp=False, full_name="Второй Сотрудник")
    with sf.capture_sql() as sqls:
        result = feed_text.snippet(f"@[{first.pk}] и @[{second.pk}] и снова @[{first.pk}]", 100)
    assert result == "@Первый Сотрудник и @Второй Сотрудник и снова @Первый Сотрудник"
    assert len([sql for sql in sqls if "core_user" in sql]) == 1


def test_snippet_cuts_by_word_with_ellipsis_at_100_60_and_300():
    """FR-609: отрывок обрезается по слову с «…» при 100, 60 и 300 знаках; короткий текст — без изменений."""
    feed_text = _text()
    words = ["слово", "длинноеслово", "а", "ещё", "пятнадцатибуквенное"]
    long_text = " ".join(words[number % len(words)] for number in range(400))
    for limit in (100, 60, 300):
        result = feed_text.snippet(long_text, limit)
        assert result.endswith("…"), limit
        cut = result[:-1].rstrip()
        assert len(cut) <= limit, limit
        assert len(cut) > limit - 25, f"{limit}: обрезано слишком рано"
        assert long_text.startswith(cut), limit
        assert long_text[len(cut)] == " ", f"{limit}: обрезка посреди слова"
    exact = "ж" * 60
    assert feed_text.snippet(exact, 60) == exact
    short = "Короткий текст"
    assert feed_text.snippet(short, 100) == short


# --- 4. страница ---------------------------------------------------------------------------------------------

def _evil_world():
    author = sf.as_writer(full_name="Злой Автор")
    attack = "".join(PROBES[:1]) + " " + PROBES[1] + " " + PROBES[2] + " " + PROBES[3]
    start = timezone.now() + timedelta(days=3)
    post = sf.make_event(author.user, start=start, title="<script>alert(1)</script>", place=PROBES[3], text=attack)
    file_name = '"><img src=x onerror=alert(1)>.txt'
    sf.attach(post, name=file_name)
    sf.comment(post, author.user, attack)
    return author, post, file_name


def _assert_page_safe(html: str, context: str) -> None:
    tree = tree_of(html)
    for node in tree.walk():
        assert not any(name.startswith("on") for name in node.attrs), f"{context}: атрибут {set(node.attrs)}"
        if node.tag == "script":
            assert "alert(1)" not in node.raw_text(), f"{context}: исполняемый скрипт с пробой"
        if node.tag == "img":
            assert node.attrs.get("src") != "x", f"{context}: картинка из пробы"
        if node.tag == "a":
            assert not node.attrs.get("href", "").strip().lower().startswith("javascript:"), context


def test_page_escapes_script_markup_javascript_and_attribute_break_in_text_title_place_and_file_name():
    """NFR-605: пробы `<script>`, `<b>`, `javascript:`, `\"><img onerror>` в тексте, названии, месте и имени файла —
    на ленте, карточке и форме правки показаны текстом и не создают тегов и атрибутов."""
    author, post, file_name = _evil_world()
    pages = {"/": None, f"/feed/{post.pk}/": None, f"/feed/{post.pk}/edit/": None}
    for path in pages:
        response = author.client.get(path)
        assert response.status_code == 200, path
        html = response.content.decode("utf-8")
        _assert_page_safe(html, path)
        pages[path] = html
    for path in ("/", f"/feed/{post.pk}/"):
        article = _find(tree_of(pages[path]), "article", id=f"feed-post-{post.pk}")[0]
        shown = article.text()
        assert "<script>alert(1)</script>" in shown, f"{path}: название и текст показаны текстом"
        assert PROBES[3] in shown, f"{path}: место показано текстом"
        assert PROBES[1] in shown, f"{path}: «<b>» показан текстом"
        assert file_name in shown, f"{path}: имя файла показано текстом"
        assert _find(article, "b") == [], path
    card_comments = _find(tree_of(pages[f"/feed/{post.pk}/"]), data_comment_id=True)
    assert card_comments and PROBES[3] in card_comments[0].text()


def test_page_builds_links_only_from_http_https_and_mailto():
    """FR-609, NFR-605: на странице ссылками в тексте записи становятся только `http`, `https`, `mailto`."""
    author = sf.as_writer()
    mail = "mailto:" + sf.email_of("ssylka", "example.test")
    allowed = ["https://ok.example.test/a", "http://ok2.example.test/b", mail]
    forbidden = ["ftp://x.example.test/f", "javascript:alert(1)", "data:text/html,xx", "www.example.test",
                 "file:///etc/passwd", "vbscript:x", "//evil.example.test/p"]
    text = "Ссылки: " + " ".join(allowed + forbidden)
    post = sf.make_post(author.user, to=["all"], text=text)
    for path in ("/", f"/feed/{post.pk}/"):
        html = author.client.get(path).content.decode("utf-8")
        _assert_page_safe(html, path)
        (body,) = _find(tree_of(html), id=f"feed-post-{post.pk}-body")
        links = _find(body, "a")
        assert [link.attrs["href"] for link in links] == allowed, path
        for link in links:
            assert link.attrs.get("target") == "_blank", path
            assert set(link.attrs.get("rel", "").split()) == {"noopener", "noreferrer"}, path
        for item in forbidden:
            assert item in body.text(), f"{path}: {item} остался текстом"
