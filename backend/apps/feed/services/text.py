"""Безопасный HTML-вывод и обычные текстовые отрывки ленты."""

import html
import re
import unicodedata
from urllib.parse import urlsplit

from django.utils.safestring import SafeString, mark_safe

_MARKER = re.compile(r"@\[([1-9]\d{0,8})\]")
_TOKEN = re.compile(r"@\[([1-9]\d{0,8})\]|(?:https?://|mailto:)[^\s<>\"'`]+", re.IGNORECASE)
_URL_TRAILING = frozenset(".,;:!?")
_BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _clean(text: str) -> str:
    """Удалить управляющие и двунаправленные символы, сохранив обычные переводы строк."""
    return "".join(
        char for char in text
        if char not in _BIDI
        and (char in "\t\n\r" or unicodedata.category(char) != "Cc")
    )


def _mention_name(person_id: int, people: dict[int, str]) -> str | None:
    name = people.get(person_id)
    if not name:
        return None
    return _clean(str(name))


def _link_target(token: str) -> bool:
    try:
        parsed = urlsplit(token)
        if parsed.scheme.lower() in {"http", "https"}:
            return bool(parsed.hostname)
        return parsed.scheme.lower() == "mailto" and bool(parsed.path)
    except ValueError:
        return False


def _trim_url(token: str) -> tuple[str, str]:
    end = len(token)
    while end:
        if token[end - 1] in _URL_TRAILING:
            end -= 1
        elif token[end - 1] == ")" and token[:end].count(")") > token[:end].count("("):
            end -= 1
        else:
            break
    return token[:end], token[end:]


def _render_inline(text: str, people: dict[int, str], link_staff: bool) -> str:
    parts = []
    cursor = 0
    for match in _TOKEN.finditer(text):
        parts.append(html.escape(text[cursor:match.start()], quote=True))
        token = match.group(0)
        if match.group(1) is not None:
            person_id = int(match.group(1))
            name = _mention_name(person_id, people)
            if name is None:
                parts.append(html.escape(token, quote=True))
            else:
                safe_name = html.escape(name, quote=True)
                if link_staff:
                    parts.append(f'<a href="/staff/{person_id}/" data-mention="{person_id}">{safe_name}</a>')
                else:
                    parts.append(f'<span data-mention="{person_id}">{safe_name}</span>')
        else:
            url, suffix = _trim_url(token)
            if len(url) <= 2048 and _link_target(url):
                escaped_url = html.escape(url, quote=True)
                parts.append(
                    f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">'
                    f'{escaped_url}</a>{html.escape(suffix, quote=True)}'
                )
            else:
                parts.append(html.escape(token, quote=True))
        cursor = match.end()
    parts.append(html.escape(text[cursor:], quote=True))
    return "".join(parts)


def render_plain(text: str, people: dict[int, str], link_staff: bool) -> SafeString:
    """Безопасно вывести простой текст ленты с экранированием и разрешёнными ссылками/упоминаниями."""
    cleaned = _clean(text)
    paragraphs = re.split(r"\n(?:[ \t]*\n)+", cleaned)
    rendered = []
    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        rendered.append("<p>" + "<br>".join(_render_inline(line, people, link_staff) for line in lines) + "</p>")
    # Единственная граница доверия: здесь текст ленты помечается как безопасный HTML.
    return mark_safe("".join(rendered))


def snippet(text: str, limit: int, people: dict[int, str] | None = None) -> str:
    """Expand known mention names, collapse whitespace, and truncate on a word boundary."""
    cleaned = _clean(text)
    ids = list(dict.fromkeys(int(match.group(1)) for match in _MARKER.finditer(cleaned)))
    if people is None:
        people = {}
        if ids:
            from apps.core.models import User, UserState

            people = dict(User.objects.filter(pk__in=ids, state=UserState.ACTIVE).values_list("pk", "full_name"))

    def replace(match):
        name = _mention_name(int(match.group(1)), people)
        return "@" + name if name is not None else match.group(0)

    plain = " ".join(_MARKER.sub(replace, cleaned).split())
    if limit <= 0:
        return ""
    if len(plain) <= limit:
        return plain

    prefix = plain[:max(0, limit - 1)]
    if len(plain) > len(prefix) and plain[len(prefix)] == " ":
        return prefix + "…"
    boundary = prefix.rfind(" ")
    if boundary <= 0:
        return "…"
    return prefix[:boundary].rstrip() + "…"
