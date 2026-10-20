"""Разбор поискового запроса (PLAN-005, «Сквозной поиск» → «Разбор»; CONTRACT-005, 9.1).

Свой разбор поиска: разбор списка заявок срез 005 не меняет. Строку `raw` поставщики отдают в `to_tsquery('russian', %s)`
параметром (`SearchQuery(…, search_type="raw")`); в словах `\\w+` служебных знаков `tsquery` нет.
"""
import re

from apps.core.extensions import ParsedQuery

MAX_LENGTH = 200
MIN_LENGTH = 2
MAX_WORDS = 8
MIN_WORD = 2
MAX_NUMBER = 2_147_483_647  # как `_MAX_NUMBER` в `servicedesk/services/search.py`

_WORD = re.compile(r"\w+")
_NUMBER = re.compile(r"#\d+|\d{2,}")


def _hint(name: str) -> ParsedQuery:
    """Запрос не разобран: подсказка есть, остальные поля пусты (CONTRACT-005, 9.1)."""
    return ParsedQuery(words=[], number=None, raw="", hint=name)


def parse(q: str | None) -> ParsedQuery:
    """Разбирает строку запроса: слова, номер заявки, строка `to_tsquery`, подсказка."""
    text = (q or "").strip()
    if len(text) > MAX_LENGTH:
        return _hint("long")
    if len(text) < MIN_LENGTH:
        return _hint("short")
    number = None
    if _NUMBER.fullmatch(text):
        value = int(text.lstrip("#"))
        if value <= MAX_NUMBER:
            number = value
    words = [word for word in _WORD.findall(text.lower()) if len(word) >= MIN_WORD][:MAX_WORDS]
    if not words and number is None:
        return _hint("short")
    return ParsedQuery(words=words, number=number, raw=" & ".join(f"{word}:*" for word in words), hint="")
