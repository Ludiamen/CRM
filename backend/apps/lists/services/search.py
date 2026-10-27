"""Сервис: поставщик поиска группы «Списки» (срез 006; PLAN-006, «Поиск»; CONTRACT-006, раздел 9).

Сначала точные совпадения (`UniqueValue` видимых уникальных полей читаемых списков, записи не в архиве), затем, без
повторов записей, `search @@ to_tsquery('russian', raw)` по читаемым спискам. Права — внутри запроса
(`list_id__in`), текст запроса нигде не сохраняется и не пишется в журналы. `apps.search` не импортируется: разбор
внутри списка (`parse_local`) — своя копия правил `apps.search.parse.parse` (К6).
"""
import re

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F

from apps.core.extensions import ParsedQuery, SearchProvider, SearchRow
from apps.lists.models import Field, List, Record, UniqueValue
from apps.lists.services import access, unique

CONFIG = "russian"
ORDER = 50
MAX_LENGTH = 200
MIN_LENGTH = 2
MAX_WORDS = 8
MIN_WORD = 2
MAX_NUMBER = 2_147_483_647

_WORD = re.compile(r"\w+")
_NUMBER = re.compile(r"#\d+|\d{2,}")


def _hint(name: str) -> ParsedQuery:
    """Запрос не разобран: подсказка есть, остальные поля пусты."""
    return ParsedQuery(words=[], number=None, raw="", hint=name)


def parse_local(q: str | None) -> ParsedQuery:
    """Разбор запроса внутри списка по правилам SPEC-005 FR-443 (копия `apps.search.parse.parse`, `apps.search`
    может быть выключен): 2…200 знаков, слова `\\w+` от 2 знаков, первые 8 слов, номер, `raw`, `text`, `hint`."""
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
    return ParsedQuery(words=words, number=number, raw=" & ".join(f"{word}:*" for word in words), hint="", text=text)


def _readable(user):
    """Отбор записей: не в архиве, список читается (управляющему — любой)."""
    records = Record.objects.filter(archived=False)
    current = access.scope(user)
    if current.manage:
        return records
    return records.filter(list_id__in=current.readable)


def _usable(parsed: ParsedQuery) -> bool:
    return not parsed.hint and bool(parsed.raw or parsed.text)


def _exact_ids(user, parsed: ParsedQuery) -> list[int]:
    """Записи с точным совпадением: запрос целиком равен нормализованному значению видимого уникального поля."""
    text = parsed.text
    if not text:
        return []
    by_type = {}
    for kind in ("string", "number"):
        norm = unique.normalize(Field(type=kind), text)
        if norm is not None:
            by_type[kind] = norm
    if not by_type:
        return []
    current = access.scope(user)
    ids: list[tuple[int, int, int]] = []
    seen: set[int] = set()
    for kind, norm in by_type.items():
        values = UniqueValue.objects.filter(
            field__type=kind, field__hidden=False, field__unique=True, norm_value=norm, record__archived=False)
        if not current.manage:
            values = values.filter(list_id__in=current.readable)
        for number, list_id, record_id in values.values_list("record__number", "list_id", "record_id"):
            if record_id not in seen:
                seen.add(record_id)
                ids.append((number, list_id, record_id))
    ids.sort()
    return [record_id for _number, _list, record_id in ids]


def _vector(user, parsed: ParsedQuery, skip: list[int]):
    """Записи читаемых списков, найденные по вектору, кроме `skip` (уже выданных точным совпадением)."""
    if not parsed.raw:
        return Record.objects.none()
    query = SearchQuery(parsed.raw, config=CONFIG, search_type="raw")
    return _readable(user).filter(search=query).exclude(pk__in=skip)


def _row(record: Record, names: dict) -> SearchRow:
    return SearchRow(title=record.title, subtitle=names[record.list_id], url=f"/lists/{record.list_id}/{record.number}/")


def _names(records) -> dict:
    return dict(List.objects.filter(pk__in={record.list_id for record in records}).values_list("pk", "name"))


def search(user, parsed: ParsedQuery, limit: int, offset: int) -> list[SearchRow]:
    """До `limit + 1` строк со смещения `offset`: точные совпадения, затем вектор (ранг вниз, номер вверх)."""
    if not _usable(parsed):
        return []
    want = limit + 1
    exact = _exact_ids(user, parsed)
    records: list[Record] = []
    if offset < len(exact):
        chosen = exact[offset:offset + want]
        by_id = Record.objects.in_bulk(chosen)
        records.extend(by_id[pk] for pk in chosen if pk in by_id)
    room = want - len(records)
    if room > 0:
        start = max(0, offset - len(exact))
        found = (_vector(user, parsed, exact)
                 .annotate(rank=SearchRank(F("search"), SearchQuery(parsed.raw, config=CONFIG, search_type="raw")))
                 .order_by("-rank", "number", "pk")[start:start + room])
        records.extend(found)
    names = _names(records)
    return [_row(record, names) for record in records]


def count(user, parsed: ParsedQuery) -> tuple[int, bool]:
    """`(число, False)`: точное число без потолка; запись из обоих источников считается один раз."""
    if not _usable(parsed):
        return 0, False
    exact = _exact_ids(user, parsed)
    return len(exact) + _vector(user, parsed, exact).count(), False


def search_providers() -> list[SearchProvider]:
    """Запись точки `search_providers`: группа «Списки»."""
    return [SearchProvider(key="lists", title="Списки", order=ORDER, search=search, count=count,
                           available=access.sees_section)]
