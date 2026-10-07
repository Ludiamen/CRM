"""Публичный интерфейс сервис-деска: поиск по заявкам (PLAN-003, «Список, поиск и счётчик»; CONTRACT-003, 6.21).

Столбец `Ticket.search` ведёт эта служба, а не триггер базы: `index` собирает его при создании заявки и дописывает
новые сообщения, `rebuild` пересобирает целиком. Запрос поиска уходит параметром (`SearchQuery`, тип `raw`),
SQL-строк здесь нет. Модели `org` не импортируются.
"""
import re
from dataclasses import dataclass

from django.contrib.postgres.search import SearchQuery, SearchVector, SearchVectorField
from django.db import DataError, transaction
from django.db.models import F, Q, TextField, Value
from django.db.models.expressions import CombinedExpression
from django.db.models.functions import Coalesce

from ..models import Ticket
from . import access

MAX_WORDS = 8
MIN_WORD = 2
LIMIT_MESSAGE = 100_000
LIMIT_TICKET = 300_000
CONFIG = "russian"
_MAX_NUMBER = 2_147_483_647     # выше номер не бывает: для базы это переполнение целого
_ADDRESS_SEPARATORS = re.compile(r"[@._/\-]")


@dataclass(frozen=True)
class Parsed:
    """Разбор строки поиска: слова, номер, запрос `to_tsquery` и подсказка (`""` или `"short"`)."""

    words: list[str]
    number: int | None
    raw: str
    hint: str


@dataclass(frozen=True)
class SearchResult:
    """Найденные заявки и подсказка разбора."""

    tickets: list[Ticket]
    hint: str


def parse(query: str) -> Parsed:
    """Разобрать строку: слова не короче `MIN_WORD`, не больше `MAX_WORDS`; `123` и `#123` — ещё и номер."""
    text = (query or "").strip()
    found = re.findall(r"\w+", text.lower())
    words = [word for word in found if len(word) >= MIN_WORD][:MAX_WORDS]
    number = None
    match = re.fullmatch(r"#?(\d+)", text)
    if match and int(match.group(1)) <= _MAX_NUMBER:
        number = int(match.group(1))
    raw = " & ".join(f"{word}:*" for word in words)
    hint = "short" if found and not words and number is None else ""
    return Parsed(words=words, number=number, raw=raw, hint=hint)


def apply(queryset, query: str):
    """Добавить к `queryset` условия поиска; нет годных слов и номера — набор не меняется."""
    parsed = parse(query)
    condition = Q()
    if parsed.raw:
        condition |= Q(search=SearchQuery(parsed.raw, config=CONFIG, search_type="raw"))
    if parsed.number is not None:
        condition |= Q(number=parsed.number)
    return queryset.filter(condition) if condition else queryset


def search(user, query: str, limit: int) -> SearchResult:
    """Видимые `user` заявки по строке `query`, по номеру вниз, не больше `limit`."""
    parsed = parse(query)
    found = apply(access.visible_tickets(user), query).order_by("-number")[:limit]
    return SearchResult(tickets=list(found), hint=parsed.hint)


def write_vector(ticket_id: int, parts: list[str]) -> None:
    """Дописать к столбцу вектор заявки из текстов `parts` (пустой столбец считается пустым вектором).

    Ошибки базы не ловит. Точка подмены: `index` и `rebuild` зовут её через имя модуля.
    """
    vector = SearchVector(Value(" ".join(parts), output_field=TextField()), config=CONFIG)
    empty = SearchVector(Value("", output_field=TextField()), config=CONFIG)
    appended = CombinedExpression(Coalesce(F("search"), empty, output_field=SearchVectorField()), "||", vector,
                                  output_field=SearchVectorField())
    Ticket.objects.filter(pk=ticket_id).update(search=appended)


def _spaced(text: str) -> str:
    """Адрес или имя с пробелами вместо `@ . _ / -`: чтобы адрес находился по части."""
    return _ADDRESS_SEPARATORS.sub(" ", text)


def _header(ticket: Ticket) -> list[str]:
    """Номер, тема, адрес и ФИО заявителя; адрес и ФИО — как есть и с заменой разделителей."""
    parts = [str(ticket.number), ticket.subject]
    for value in (ticket.requester_email, ticket.requester_name):
        if value:
            parts.extend([value, _spaced(value)])
    return [part for part in parts if part]


def _take(text: str, used: int) -> str:
    """Часть `text`, что войдёт в поиск: не больше `LIMIT_MESSAGE` и остатка предела на заявку."""
    return text[:LIMIT_MESSAGE][:max(LIMIT_TICKET - used, 0)]


def _set_length(ticket: Ticket, length: int) -> None:
    Ticket.objects.filter(pk=ticket.pk).update(search_len=length)
    ticket.search_len = length


def _reset(ticket: Ticket) -> None:
    """Сбросить столбец поиска и его длину перед полной записью."""
    Ticket.objects.filter(pk=ticket.pk).update(search=None, search_len=0)


def _write_whole(ticket: Ticket, header: list[str], texts: list[str]) -> None:
    """Заменить столбец целиком: шапка и тексты (уже обрезанные); `DataError` — только шапка, предел достигнут."""
    used = sum(len(text) for text in texts)
    try:
        with transaction.atomic():
            _reset(ticket)
            write_vector(ticket.pk, header + texts)
    except DataError:
        _reset(ticket)
        write_vector(ticket.pk, header)
        used = LIMIT_TICKET
    _set_length(ticket, used)


def index(ticket: Ticket, entry=None) -> None:
    """Без `entry` — собрать столбец после создания заявки (шапка и первый элемент); с `entry` — дописать его текст."""
    if entry is None:
        first = ticket.entries.exclude(text="").order_by("at", "id").first()
        texts = [_take(first.text, 0)] if first else []
        _write_whole(ticket, _header(ticket), texts)
        return
    used = Ticket.objects.filter(pk=ticket.pk).values_list("search_len", flat=True).get()
    chunk = _take(entry.text, used) if used < LIMIT_TICKET else ""
    if not chunk:
        ticket.search_len = used
        return
    try:
        with transaction.atomic():
            write_vector(ticket.pk, [chunk])
    except DataError:
        _set_length(ticket, LIMIT_TICKET)
        return
    _set_length(ticket, used + len(chunk))


def rebuild(ticket: Ticket, *, anonymized: bool = False) -> None:
    """Пересобрать столбец целиком; `anonymized=True` — только из номера и темы."""
    if anonymized:
        _write_whole(ticket, [str(ticket.number), ticket.subject], [])
        _set_length(ticket, 0)
        return
    texts, used = [], 0
    for text in ticket.entries.exclude(text="").order_by("at", "id").values_list("text", flat=True):
        chunk = _take(text, used)
        if chunk:
            texts.append(chunk)
            used += len(chunk)
    _write_whole(ticket, _header(ticket), texts)
