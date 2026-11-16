"""T-8110: вывод текста мессенджера (FR-653, FR-655, NFR-703, NFR-705).

Источники: PLAN-008 «Отправка, правка, удаление, цитата» → «Вывод» (обёртка над `core.services.text` с шаблонами
`@[u<id>]`/`@[c<id>]`, ссылки только `http`/`https`/`mailto`, абзацы и переносы, разметка не выполняется) и
«Безопасный вывод» (CONTRACT-008: 5.2 — `text.render_plain(text, *, link_staff)` и `text.snippet(text, limit, *,
expand=None)`; 13 — тексты; 11.3 — кадры; 12.3/12.6 — зацепки `article#m<id>`, `[data-mention]`). Ядро — единственное
место `mark_safe`: тест проверяет, что обёртка мессенджера зовёт `core.services.text.render_plain` со своими частями
`pieces`, а `snippet` — с `expand`; обёртка ленты (`feed.services.text`) после переноса в ядро даёт тот же вывод.

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): службы берутся
ленивыми импортами внутри тестов, модели и сотрудники — через `support`/`support_messenger`. Секретов и ПДн нет:
адрес почты собирается из частей `support_messenger.email_of`; в тексте — только `***`.

Допущения писателя: (1) маркер `@[u<id>]`/`@[c<id>]` раскрывается по базе, поэтому известный номер даёт имя или
название, а неизвестный (нет строки, номер вне формы `[1-9]\\d{0,8}`) остаётся текстом; (2) при `link_staff=False`
контракт не называет тег узла упоминания, поэтому тест требует имени и `data-mention`, но не запрещает ссылку;
(3) уведомление проверяется через настоящую отправку, а не через `notify_rules.decide`, чтобы не задавать служебное
слово действия; (4) порядок атрибутов и пробелы разметки не сверяются — сравниваются текст и ссылки.
"""
import importlib
import re
from html.parser import HTMLParser

import pytest
from django.utils.safestring import SafeString

from tests import support
from tests import support_messenger as messenger

pytestmark = pytest.mark.django_db

ALLOWED_TAGS = {"a", "span", "p", "br"}
ALLOWED_ATTRS = {"href", "target", "rel", "data-mention"}
PROBES = (
    "<script>alert(1)</script>",
    "<b>жирный</b>",
    "javascript:alert(1)",
    '"><img src=x onerror=alert(1)>',
)

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_feed_text.py) -------------------------------

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

    def raw_text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return "".join(parts)

    def text(self) -> str:
        return " ".join(self.raw_text().split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
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


def _html(value) -> str:
    """Тело ответа или готовая строка разметки."""
    if hasattr(value, "content"):
        return value.content.decode("utf-8", "replace")
    return value


def _tree(value) -> _Node:
    parser = _Parser()
    parser.feed(_html(value))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; `_` в имени атрибута — дефис, `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


def _q1(scope, tag=None, **attrs) -> _Node:
    found = _q(scope, tag, **attrs)
    assert len(found) == 1, f"узлов {tag or '*'}: {len(found)} (ожидали один)"
    return found[0]


def _links(value) -> list:
    return _q(_tree(value), "a")


def _link_signature(node) -> list:
    """Ссылки узла в виде «адрес, метка упоминания, текст» — для сверки страницы и кадра."""
    return [(link.attrs.get("href"), link.attrs.get("data-mention"), link.text()) for link in _q(node, "a")]


def _assert_only_allowed(value, context: str) -> None:
    """В выводе только разрешённые теги и атрибуты; ссылок `javascript:`/`data:`/`vbscript:` нет."""
    for node in _tree(value).walk():
        assert node.tag in ALLOWED_TAGS, f"{context}: тег <{node.tag}> вне допустимых"
        assert set(node.attrs) <= ALLOWED_ATTRS, f"{context}: атрибуты {set(node.attrs) - ALLOWED_ATTRS}"
        href = node.attrs.get("href", "").strip().lower()
        assert not href.startswith(("javascript:", "data:", "vbscript:")), context


def _assert_page_safe(value, context: str) -> None:
    """Проба на странице: нет обработчиков `on…=`, исполняемого скрипта и картинки из пробы."""
    for node in _tree(value).walk():
        assert not any(name.startswith("on") for name in node.attrs), f"{context}: атрибут {set(node.attrs)}"
        if node.tag == "script":
            assert "alert(1)" not in node.raw_text(), f"{context}: исполняемый скрипт с пробой"
        if node.tag == "img":
            assert node.attrs.get("src") != "x", f"{context}: картинка из пробы"


# --- служба текста и обёртка ленты -----------------------------------------------------------------------------

def _service():
    return importlib.import_module("apps.messenger.services.text")


def _core():
    return importlib.import_module("apps.core.services.text")


def _feed():
    return importlib.import_module("apps.feed.services.text")


def render(text: str, *, link_staff: bool = True):
    return _service().render_plain(text, link_staff=link_staff)


def snippet(text: str, limit: int, *, expand=None) -> str:
    return _service().snippet(text, limit, expand=expand)


# --- 1. экранирование ------------------------------------------------------------------------------------------

def test_plain_text_escaped_and_script_not_executed():
    """FR-653, NFR-703: разметка в тексте показывается текстом, исполняемых тегов и атрибутов не появляется.

    Тот же вход после переноса `render_plain` в ядро даёт у обёртки ленты прежний вывод: ядро — единственное место
    `mark_safe`, обе обёртки передают ему свои `pieces`, а на тексте без их маркеров вывод совпадает.
    """
    for text in PROBES + ("<svg/onload=alert(1)>", "<iframe src=//example.test></iframe>",
                          "<<script>script>alert(1)<</script>/script>", "&lt;script&gt;alert(1)&lt;/script&gt;"):
        for link_staff in (True, False):
            html = render(text, link_staff=link_staff)
            assert isinstance(html, SafeString), repr(text)
            _assert_only_allowed(html, repr(text))
            assert _q(_tree(html), "script") == [], repr(text)
            assert _q(_tree(html), "b") == [] and _q(_tree(html), "img") == [], repr(text)
            assert _tree(html).text() == text, repr(text)

    mixed = render("Смотри https://example.test/a и <b>вот</b>")
    assert "<b>" not in mixed and "&lt;b&gt;" in mixed
    assert "<script>" not in mixed and "&lt;script&gt;" in render("<script>alert(1)</script>")

    # лента после переноса выражений в ядро: на тексте без её маркеров вывод прежний и такой же, как у мессенджера
    for text in PROBES + ("абзац\n\nвторой <i>курсив</i>",):
        assert str(_feed().render_plain(text, {}, True)) == render(text, link_staff=True), repr(text)


# --- 2. ссылки -------------------------------------------------------------------------------------------------

def test_only_http_https_mailto_become_links_and_javascript_stays_text():
    """FR-653: ссылками становятся только `http`, `https`, `mailto`; прочие схемы и голые домены — текстом.

    Ссылка открывается в новой вкладке и несёт `rel="noopener noreferrer"`.
    """
    address = messenger.email_of("ssylka", "example.test")
    allowed = ["https://example.test/path?a=1&b=2", "http://example.test/", f"mailto:{address}"]
    forbidden = ["ftp://example.test/file", "javascript:alert(1)", "data:text/html,привет",
                 "vbscript:msgbox(1)", "file:///etc/hosts", "www.example.test", "example.test/page",
                 "//evil.example.test/p"]

    html = render("Ссылки: " + " ".join(allowed + forbidden))
    _assert_only_allowed(html, "ссылки")
    links = _links(html)
    assert [link.attrs["href"] for link in links] == allowed
    for link in links:
        assert link.attrs["target"] == "_blank"
        assert set(link.attrs["rel"].split()) == {"noopener", "noreferrer"}
        assert link.text() == link.attrs["href"]
    assert "a=1&amp;b=2" in html, "`&` в адресе не экранирован"

    shown = _tree(html).text()
    for item in forbidden:
        assert item in shown, f"{item} перестал быть текстом"
        assert item not in [link.attrs["href"] for link in links], item


# --- 3. абзацы и переносы --------------------------------------------------------------------------------------

def test_paragraphs_and_line_breaks_kept():
    """FR-653: пустая строка делит абзацы на `<p>`, одиночный перевод строки — `<br>` внутри абзаца."""
    html = render("один\nдва\n\nтри\n  \n\nчетыре")
    _assert_only_allowed(html, "абзацы")
    paragraphs = _q(_tree(html), "p")
    assert len(paragraphs) == 3
    assert [part.strip() for part in paragraphs[0].children if isinstance(part, str)] == ["один", "два"]
    assert [paragraph.text() for paragraph in paragraphs[1:]] == ["три", "четыре"]
    assert len(_q(paragraphs[0], "br")) == 1
    assert _q(paragraphs[1], "br") == [] and _q(paragraphs[2], "br") == []


# --- 4. упоминания ---------------------------------------------------------------------------------------------

def test_mention_markers_render_name_link_and_chat_link(monkeypatch):
    """FR-653, FR-655: `@[u<id>]` — ФИО ссылкой на карточку, `@[c<id>]` — название ссылкой на беседу.

    Обёртка мессенджера зовёт ядро `render_plain` со своими двумя частями `pieces` (человек и чат) и передаёт
    `link_staff`; сама она разметку не строит и `mark_safe` не зовёт.
    """
    author = messenger.make_user(full_name="Автор Упоминаний")
    person = messenger.make_user(full_name="Пётр Упомянутый")
    chat = messenger.group(author, [person], title="Чат упоминаний")

    text = f"Привет @[u{person.user.pk}] и @[c{chat.pk}], смотри https://example.test/a"
    core_text = _core()
    calls = []
    original = core_text.render_plain

    def spy(source, pieces=(), *, link_staff):
        calls.append((source, tuple(pieces), link_staff))
        return original(source, pieces, link_staff=link_staff)

    monkeypatch.setattr(core_text, "render_plain", spy)
    html = render(text, link_staff=True)

    assert len(calls) == 1, "обёртка не позвала ядро ровно один раз"
    called_text, pieces, called_link_staff = calls[0]
    assert called_text == text and called_link_staff is True
    assert len(pieces) == 2, f"частей `pieces`: {len(pieces)}"
    patterns = [re.compile(getattr(pattern, "pattern", pattern)) for pattern, _handler in pieces]
    assert patterns[0].search(f"@[u{person.user.pk}]") and not patterns[0].search(f"@[c{chat.pk}]")
    assert patterns[1].search(f"@[c{chat.pk}]") and not patterns[1].search(f"@[u{person.user.pk}]")
    assert all(callable(handler) for _pattern, handler in pieces)

    _assert_only_allowed(html, "упоминания")
    (person_link,) = _q(_tree(html), "a", data_mention=str(person.user.pk))
    assert person_link.attrs["href"] == f"/staff/{person.user.pk}/"
    assert person_link.text() == "Пётр Упомянутый"
    (chat_link,) = _q(_tree(html), "a", data_mention=f"c{chat.pk}")
    assert chat_link.attrs["href"] == f"/messenger/chats/{chat.pk}/"
    assert "Чат упоминаний" in chat_link.text()
    (url_link,) = [link for link in _links(html) if link.attrs.get("href") == "https://example.test/a"]
    assert set(url_link.attrs["rel"].split()) == {"noopener", "noreferrer"}
    assert f"@[u{person.user.pk}]" not in _tree(html).text() and f"@[c{chat.pk}]" not in _tree(html).text()

    plain = render(text, link_staff=False)
    _assert_only_allowed(plain, "упоминания без права")
    shown = _tree(plain).text()
    assert "Пётр Упомянутый" in shown and "Чат упоминаний" in shown
    assert f"@[u{person.user.pk}]" not in shown and f"@[c{chat.pk}]" not in shown
    assert _q(_tree(plain), data_mention=str(person.user.pk)), "метка упоминания человека пропала"
    assert _q(_tree(plain), data_mention=f"c{chat.pk}"), "метка упоминания чата пропала"


# --- 5. неизвестный маркер -------------------------------------------------------------------------------------

def test_unknown_marker_stays_text():
    """FR-655: маркер без строки в базе и маркер вне формы `@[u| c][1-9]\\d{0,8}` остаются текстом."""
    author = messenger.make_user(full_name="Автор Без Упоминаний")
    chat = messenger.group(author, [], title="Чат без упоминаний")
    markers = (
        "@[u999999999]", "@[c999999999]", "@[u0]", "@[u01]", "@[u-5]", "@[uabc]", "@[u]",
        "@[]", "@[x7]", "@[u1234567890]", "@Иван", "@[u1e3]",
    )
    for marker in markers:
        html = render(f"до {marker} после")
        _assert_only_allowed(html, marker)
        assert _q(_tree(html), data_mention=True) == [], f"{marker}: маркер стал ссылкой"
        assert marker in _tree(html).text(), f"{marker}: маркер пропал"
        assert marker in html, marker
    assert _q(_tree(render(f"@[c{chat.pk}]")), data_mention=True), "известный маркер чата перестал раскрываться"


# --- 6. управляющие и bidi -------------------------------------------------------------------------------------

def test_bidi_and_control_characters_removed():
    """NFR-703: управляющие и двунаправленные символы удаляются; табуляция, `CR` и перевод строки остаются."""
    removed = ["\x00", "\x01", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x7f",
               "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2066", "\u2067", "\u2068", "\u2069"]
    for char in removed:
        html = render(f"до{char}после")
        assert "допосле" in _tree(html).text(), repr(char)
        assert char not in html, repr(char)
    assert "\t" in render("а\tб")
    assert "\r" in render("а\rб")
    assert "<br>" in render("а\nб") or "<br/>" in render("а\nб") or "<br />" in render("а\nб")


# --- 7. отрывок ------------------------------------------------------------------------------------------------

def test_snippet_100_without_markup_and_with_mention_expand(monkeypatch):
    """FR-653: отрывок — простой текст без разметки, обрезка по границе слова на 100 знаках.

    `expand` превращает маркер в имя до обрезки; обёртка передаёт его ядру `snippet` и очищает текст от
    управляющих символов до `expand`. Без `expand` маркеры остаются как есть (CONTRACT-008 5.2).
    """
    marker = "@[u7]"

    def expand(cleaned: str) -> str:
        return cleaned.replace(marker, "@Иван Иванов")

    # передача в ядро: обёртка зовёт `core.services.text.snippet(..., expand=...)`
    core_text = _core()
    seen = {}
    original = core_text.snippet

    def spy(source, limit, *, expand=None):
        seen["text"], seen["limit"], seen["expand"] = source, limit, expand
        return original(source, limit, expand=expand)

    monkeypatch.setattr(core_text, "snippet", spy)
    result = snippet("Привет  @[u7]   вот\n\nтекст\tдальше", 100, expand=expand)
    assert seen["limit"] == 100 and seen["expand"] is expand, "ядро получило не тот предел или не тот `expand`"
    assert result == "Привет @Иван Иванов вот текст дальше"
    assert "<" not in result and "data-mention" not in result and "@[u7]" not in result

    # очистка до `expand`: в преобразователь не попадают управляющие и bidi-символы
    cleaned_inputs = []

    def recording(cleaned: str) -> str:
        cleaned_inputs.append(cleaned)
        return cleaned

    snippet("Привет\x00 @[u7]\u202e мир", 100, expand=recording)
    assert cleaned_inputs and "\x00" not in cleaned_inputs[0] and "\u202e" not in cleaned_inputs[0]

    # без `expand` маркеры остаются текстом
    assert "@[u7]" in snippet("Привет @[u7] мир", 100)

    # обрезка на 100 знаках по границе слова
    words = ["слово", "длинноеслово", "а", "ещё", "пятнадцатибуквенное"]
    long_text = " ".join(words[number % len(words)] for number in range(400))
    cut = snippet(long_text, 100)
    assert cut.endswith("…")
    body = cut[:-1].rstrip()
    assert len(body) <= 100 and len(body) > 75
    assert long_text.startswith(body)
    assert long_text[len(body)] == " ", "обрезка посреди слова"

    exact = "ж" * 100
    assert snippet(exact, 100) == exact
    assert snippet("Короткий текст", 100) == "Короткий текст"


# --- 8. страница, кадр и текст уведомления -------------------------------------------------------------------

def test_same_output_on_page_frame_and_notification_text():
    """FR-653, NFR-705: в беседе и в живом кадре сообщение выведено одинаково; в тексте уведомления его нет.

    Страница и кадр собираются одним выводом (`render_plain`): тот же текст, те же ссылки и упоминания, те же
    экранированные пробы. Уведомление получает только «<ФИО> упомянул(а) вас в чате «<название>»» и ссылку на
    сообщение: ни текста сообщения, ни адресов, ни маркеров в нём нет (NFR-705).
    """
    author = messenger.make_user(full_name="Автор Вывода")
    reader = messenger.make_user(full_name="Читатель Вывода")
    chat = messenger.group(author, [reader], title="Чат вывода")
    attack = " ".join(PROBES)
    text = f"Привет @[u{reader.user.pk}]! @[c{chat.pk}] Смотри https://example.test/a {attack}"

    response = author.client.post(f"/messenger/chats/{chat.pk}/messages/", {"text": text})
    assert response.status_code == 302, f"отправка: {response.status_code}"
    message = support.model("messenger.Message").objects.get(chat=chat)

    page = reader.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200, f"беседа: {page.status_code}"
    _assert_page_safe(page, "беседа")
    article = _q1(_tree(page), id=f"m{message.pk}")
    assert article.tag == "article", f"сообщение — <{article.tag}>, а не <article>"
    assert article.attrs.get("data-own") == "0"
    assert _q(article, "script") == [] and _q(article, "img") == [] and _q(article, "b") == [], (
        "на странице появился тег из пробы")

    # живой кадр: рассылка той же службой, что и после отправки (получатель — читатель, автор исключён)
    live = importlib.import_module("apps.messenger.services.live")
    with messenger.layer_spy() as spy:
        live.publish(chat, "new", message, owner=author.user.pk)
    events = [payload for _group, payload in spy.calls
              if isinstance(payload, dict) and payload.get("type") == "messenger.event"]
    assert events, "рассылка не отправила сообщение `messenger.event`"
    variants = events[0]["variants"]
    assert set(variants) == {"reader:0"}, f"варианты кадра: {set(variants)}"
    frame_article = _q1(_tree(variants["reader:0"]), id=f"m{message.pk}")
    assert frame_article.tag == "article", f"кадр: сообщение — <{frame_article.tag}>"
    assert frame_article.attrs.get("data-own") == "0"
    assert _q(frame_article, "script") == [] and _q(frame_article, "img") == [], (
        "в кадре появился тег из пробы")

    # одинаковый вывод: текст, ссылки и упоминания совпадают
    assert article.text() == frame_article.text(), "текст сообщения на странице и в кадре разный"
    assert _link_signature(article) == _link_signature(frame_article), "ссылки страницы и кадра различаются"
    for node, context in ((article, "страница"), (frame_article, "кадр")):
        shown = node.text()
        assert "<script>alert(1)</script>" in shown, f"{context}: скрипт не показан текстом"
        assert '"><img src=x onerror=alert(1)>' in shown, f"{context}: проба атрибута не показана текстом"
        assert "javascript:alert(1)" in shown, f"{context}: `javascript:` не остался текстом"
        assert _q(node, data_mention=str(reader.user.pk)), f"{context}: нет упоминания человека"
        (chat_link,) = _q(node, "a", data_mention=f"c{chat.pk}")
        assert chat_link.attrs["href"] == f"/messenger/chats/{chat.pk}/", f"{context}: упоминание чата без ссылки"
        url_links = [link for link in _q(node, "a") if link.attrs.get("href") == "https://example.test/a"]
        assert len(url_links) == 1, f"{context}: ссылка на адрес не одна"
        assert set(url_links[0].attrs["rel"].split()) == {"noopener", "noreferrer"}

    # уведомление: только событие и ссылка, без текста сообщения, адресов и маркеров
    notes = support.model("notify.Notification").objects.filter(user=reader.user, kind="messenger.mention")
    assert notes.count() == 1, f"уведомлений упомянутому: {notes.count()}"
    note = notes.get()
    assert "Автор Вывода" in note.text and "Чат вывода" in note.text, note.text
    for forbidden in ("<script>", "javascript:", "https://example.test/a", "@[u", "@[c", "img src"):
        assert forbidden not in note.text, f"в тексте уведомления осталось: {forbidden}"
    assert note.url == f"/messenger/chats/{chat.pk}/#m{message.pk}"
    assert note.object_ref == f"messenger.chat:{chat.pk}"
    assert support.model("notify.Notification").objects.filter(
        user=author.user, kind__startswith="messenger.").count() == 0, "автор получил уведомление о своём сообщении"