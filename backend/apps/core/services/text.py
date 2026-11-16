"""Безопасный HTML-вывод пользовательского текста и обычные текстовые отрывки (срез 008, T-8004).

Единственное место `mark_safe` для пользовательского текста: вызывающие модули передают свои шаблоны
маркеров (`pieces`), а экранирование, ссылки `http`/`https`/`mailto`, абзацы и переносы делает этот
модуль. Выражения перенесены из прежней службы ленты без изменения поведения.
"""

import html
import re
import unicodedata
from urllib.parse import urlsplit

from django.utils.safestring import SafeString, mark_safe

__all__ = ["clean", "render_plain", "snippet"]

_BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_URL_TRAILING = frozenset(".,;:!?")
_URL_TOKEN = r"(?:https?://|mailto:)[^\s<>\"'`]+"
_URL_LIMIT = 2048


def clean(text: str) -> str:
    """Удалить управляющие и двунаправленные символы, сохранив обычные переводы строк."""
    return "".join(
        char for char in text
        if char not in _BIDI
        and (char in "\t\n\r" or unicodedata.category(char) != "Cc")
    )


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


class _PieceMatch:
    """Совпадение одной части `pieces`: группы считаются от шаблона самой части, а не от общего.

    `group(0)` — совпавший текст (маркер целиком), `group(1…n)` — группы шаблона части. Так обработчик
    любой части читает свой номер как `group(1)` и не знает о частях, стоящих в общем шаблоне раньше.
    """

    __slots__ = ("_match", "_base", "_count")

    def __init__(self, match: re.Match, base: int, count: int) -> None:
        self._match = match
        self._base = base
        self._count = count

    @property
    def string(self) -> str:
        return self._match.string

    def group(self, *numbers):
        if not numbers:
            return self._match.group(0)
        picked = [
            self._match.group(0) if number == 0 else self._match.group(self._base + number)
            for number in numbers
        ]
        return picked[0] if len(picked) == 1 else tuple(picked)

    def __getitem__(self, number):
        return self.group(number)

    def groups(self, default=None) -> tuple:
        return tuple(
            self.group(number) if self.group(number) is not None else default
            for number in range(1, self._count + 1)
        )

    def start(self) -> int:
        return self._match.start()

    def end(self) -> int:
        return self._match.end()

    def span(self) -> tuple[int, int]:
        return self._match.span()


class _Tokens:
    """Общий шаблон поиска: части `pieces` по порядку, последним — ссылка `http`/`https`/`mailto`."""

    def __init__(self, pieces) -> None:
        self.pieces = list(pieces or ())
        alternatives = []
        self._bases = []
        self._counts = []
        offset = 0
        for pattern, _handler in self.pieces:
            source = getattr(pattern, "pattern", pattern)
            count = re.compile(source).groups
            alternatives.append(f"(?:{source})")
            self._bases.append(offset)
            self._counts.append(count)
            offset += count
        alternatives.append(f"(?i:{_URL_TOKEN})")
        self.regex = re.compile("|".join(alternatives))

    def piece_of(self, match: re.Match) -> int | None:
        """Номер совпавшей части `pieces`; `None` — совпал адрес. У части должна быть группа 1."""
        for index, (base, count) in enumerate(zip(self._bases, self._counts)):
            if count and match.group(base + 1) is not None:
                return index
        return None

    def piece_match(self, match: re.Match, index: int) -> _PieceMatch:
        return _PieceMatch(match, self._bases[index], self._counts[index])


def _render_inline(text: str, tokens: _Tokens, link_staff: bool) -> str:
    parts = []
    cursor = 0
    for match in tokens.regex.finditer(text):
        parts.append(html.escape(text[cursor:match.start()], quote=True))
        index = tokens.piece_of(match)
        if index is not None:
            handler = tokens.pieces[index][1]
            parts.append(handler(tokens.piece_match(match, index), link_staff))
        else:
            token = match.group(0)
            url, suffix = _trim_url(token)
            if len(url) <= _URL_LIMIT and _link_target(url):
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


def render_plain(text: str, pieces=(), *, link_staff: bool) -> SafeString:
    """Безопасно вывести простой текст с экранированием, разрешёнными ссылками и шаблонами `pieces`.

    `pieces` — пары «шаблон маркера» и «обработчик»: у шаблона есть группа номера (первая), обработчик
    `handler(match, link_staff) -> str` возвращает готовый экранированный HTML и читает свой номер как
    `match.group(1)`. Маркеры, которых нет в `pieces`, остаются текстом.
    """
    tokens = _Tokens(pieces)
    cleaned = clean(text)
    paragraphs = re.split(r"\n(?:[ \t]*\n)+", cleaned)
    rendered = []
    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        rendered.append("<p>" + "<br>".join(_render_inline(line, tokens, link_staff) for line in lines) + "</p>")
    # Единственная граница доверия: здесь текст пользователя помечается как безопасный HTML.
    return mark_safe("".join(rendered))


def snippet(text: str, limit: int, *, expand=None) -> str:
    """Очистить текст, схлопнуть пробелы и обрезать отрывок по границе слова.

    `expand(cleaned) -> str` — преобразователь маркеров в имена (лента передаёт свой); `None` — маркеры
    остаются как есть. Отрывок — простой текст, без разметки.
    """
    cleaned = clean(text)
    expanded = cleaned if expand is None else str(expand(cleaned))
    plain = " ".join(expanded.split())
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
