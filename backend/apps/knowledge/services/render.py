"""Разметка статьи: Markdown в безопасный HTML и чистый текст для индекса (план 005, «Рендер Markdown»).

`render(text, files, article_id)` — единственная функция для сохранения, версии, предпросмотра и команды
`kb_rerender`; в базу она не ходит. Две линии защиты: разбор без сырого HTML и со своей проверкой адресов, затем
`sanitize` (белый список `nh3` и второй фильтр атрибутов).
"""
import html as html_lib
import re
from typing import NamedTuple

import nh3
from markdown_it import MarkdownIt
from markdown_it.token import Token

PLAIN_LIMIT = 100_000

TAGS = {"p", "br", "strong", "em", "del", "code", "pre", "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5",
        "h6", "hr", "a", "img", "table", "thead", "tbody", "tr", "th", "td", "div", "span"}
ATTRIBUTES = {
    "*": {"class"},
    "a": {"href", "title", "rel", "target"},
    "img": {"src", "alt", "loading"},
}
SCHEMES = {"http", "https", "mailto"}

_ATT = re.compile(r"att:(\d+)")
_ATTACHMENT_PATH = re.compile(r"/kb/(\d+)/(images|files)/\d+/")
_KB_CLASS = re.compile(r"kb-[a-z0-9-]+")
_UNSAFE_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")
_ALIGN = re.compile(r"text-align:\s*(left|center|right)\s*;?")
_EXTERNAL = ("http://", "https://", "mailto:")
_REL = "noopener noreferrer"


class Rendered(NamedTuple):
    """Результат рендера: готовый HTML и чистый текст для поискового индекса."""

    html: str
    plain: str


def _root_path(url: str) -> bool:
    """Путь от корня сайта: не `//хост`, не `/\\хост`, без пробелов и управляющих знаков."""
    return url.startswith("/") and not url.startswith("//") and not url.startswith("/\\") \
        and not _UNSAFE_CHARS.search(url)


def _validate_link(url: str) -> bool:
    """Адрес, который разбор вообще превращает в ссылку или картинку (FR-402)."""
    if _UNSAFE_CHARS.search(url):
        return False
    if _ATT.fullmatch(url):
        return True
    if url.lower().startswith(_EXTERNAL):
        return True
    return _root_path(url)


def _inline_text(children) -> str:
    """Видимый текст inline-токенов: текст, код, подписи картинок; переносы — пробелом."""
    parts = []
    for child in children or ():
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type == "image":
            parts.append(_inline_text(child.children))
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts)


_BLOCK_END = {"paragraph_close", "heading_close", "th_close", "td_close", "tr_close", "list_item_close",
              "blockquote_close", "hr"}


def _plain_text(tokens) -> str:
    """Чистый текст из токенов: блоки и ячейки разделены переводом строки, адресов ссылок нет."""
    parts: list[str] = []
    for token in tokens:
        if token.type == "inline":
            for child in token.children or ():
                if child.type in ("text", "code_inline"):
                    parts.append(child.content)
                elif child.type == "image":
                    parts.append(_inline_text(child.children))
                elif child.type in ("softbreak", "hardbreak"):
                    parts.append("\n")
        elif token.type in ("fence", "code_block"):
            parts.append(token.content)
            parts.append("\n")
        elif token.type in _BLOCK_END:
            parts.append("\n")
    return "".join(parts)


def _kb_core_rule(state) -> None:
    """После разбора: простой текст, выравнивание классами, ссылки и вложения статьи."""
    env = state.env
    files = env.get("files") or {}
    article_id = env.get("article_id")
    env["plain"] = _plain_text(state.tokens).strip("\n")[:PLAIN_LIMIT]
    for token in state.tokens:
        if token.type in ("th_open", "td_open"):
            style = token.attrGet("style")
            if style is not None:
                token.attrs.pop("style", None)
                found = _ALIGN.fullmatch(style.strip())
                if found:
                    token.attrSet("class", "kb-al-" + found.group(1))
        elif token.type == "inline" and token.children:
            token.children = _rewrite_links(token.children, files, article_id)


def _rewrite_links(children, files, article_id):
    """Внешним ссылкам — `rel` и `target`; `att:N` — адрес файла статьи или заглушка."""
    out = []
    index = 0
    while index < len(children):
        token = children[index]
        index += 1
        if token.type != "link_open":
            out.append(token)
            continue
        href = token.attrGet("href") or ""
        attached = _ATT.fullmatch(href)
        if attached:
            number = int(attached.group(1))
            if article_id is not None and number in files:
                token.attrSet("href", f"/kb/{article_id}/files/{number}/")
                out.append(token)
                continue
            end = index
            while end < len(children) and children[end].type != "link_close":
                end += 1
            label = _inline_text(children[index:end])
            stub = Token("html_inline", "", 0)
            stub.content = f'<span class="kb-noimg">[вложение недоступно: {html_lib.escape(label)}]</span>'
            out.append(stub)
            index = end + 1
            continue
        if href.lower().startswith(_EXTERNAL):
            token.attrSet("rel", _REL)
            token.attrSet("target", "_blank")
        out.append(token)
    return out


def _wrap(name: str, md: MarkdownIt, before: str, after: str) -> None:
    """Оборачивает вывод правила рендера `name` в `before`…`after`."""
    original = md.renderer.rules.get(name) or md.renderer.renderToken

    def rule(tokens, idx, options, env):
        return before + original(tokens, idx, options, env) + after

    md.renderer.rules[name] = rule


def _image_rule(md: MarkdownIt):
    def image(tokens, idx, options, env):
        token = tokens[idx]
        src = token.attrGet("src") or ""
        alt = md.renderer.renderInlineAsText(token.children or [], options, env)
        found = _ATT.fullmatch(src)
        files = env.get("files") or {}
        article_id = env.get("article_id")
        if found and article_id is not None and int(found.group(1)) in files:
            return (f'<img src="/kb/{article_id}/images/{int(found.group(1))}/" '
                    f'alt="{html_lib.escape(alt)}" loading="lazy">')
        return f'<span class="kb-noimg">[вложение недоступно: {html_lib.escape(alt)}]</span>'

    return image


def _build(with_rules: bool) -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "maxNesting": 20}).enable("table")
    md.validateLink = _validate_link
    if with_rules:
        md.core.ruler.push("kb_post", _kb_core_rule)
        md.renderer.rules["image"] = _image_rule(md)
        _wrap("fence", md, '<div class="kb-scroll">', "</div>")
        _wrap("code_block", md, '<div class="kb-scroll">', "</div>")
        md.renderer.rules["table_open"] = _table_open(md)
        _wrap("table_close", md, "", "</div>")
    return md


def _table_open(md: MarkdownIt):
    original = md.renderer.rules.get("table_open") or md.renderer.renderToken

    def table_open(tokens, idx, options, env):
        return '<div class="kb-scroll">' + original(tokens, idx, options, env)

    return table_open


_MD = _build(True)
_BASE = _build(False)


def parse(text: str):
    """Токены того же разбора без правил вывода: для поиска ПДн (`pdn.find`)."""
    return _BASE.parse(text, {})


def sanitize(html: str, article_id: int | None) -> str:
    """Белый список `nh3` и второй фильтр атрибутов: `class` только `kb-*`, `src` и `href` по правилам."""
    own = str(article_id) if article_id is not None else None

    def attribute_filter(tag: str, attribute: str, value: str):
        if attribute == "class":
            words = [w for w in value.split() if _KB_CLASS.fullmatch(w)]
            return " ".join(words) or None
        if attribute == "src":
            found = _ATTACHMENT_PATH.fullmatch(value)
            if found and found.group(2) == "images" and found.group(1) == own:
                return value
            return None
        if attribute == "href":
            found = _ATTACHMENT_PATH.fullmatch(value)
            if found:
                return value if found.group(1) == own else None
            if value.lower().startswith(_EXTERNAL) and not _UNSAFE_CHARS.search(value) or _root_path(value):
                return value
            return None
        if attribute == "rel":
            return value if value == _REL else None
        if attribute == "target":
            return value if value == "_blank" else None
        if attribute == "loading":
            return value if value == "lazy" else None
        return value

    return nh3.clean(html, tags=TAGS, attributes=ATTRIBUTES, url_schemes=SCHEMES, link_rel=None,
                     attribute_filter=attribute_filter)


def render(text: str, files: dict[int, tuple[str, str]], article_id: int | None = None) -> Rendered:
    """Markdown → `Rendered(html, plain)`; `files` — `{N: (имя, формат картинки)}` вложений этой статьи."""
    env = {"files": files, "article_id": article_id}
    try:
        raw = _MD.render(text, env)
    except RecursionError:
        raw = "<p>" + html_lib.escape(text) + "</p>"
        env["plain"] = text.strip("\n")[:PLAIN_LIMIT]
    plain = env.get("plain", "")
    return Rendered(sanitize(raw, article_id), plain)
