"""Поставщик группы «Статьи» сквозного поиска (PLAN-005, «Сквозной поиск» → «Статьи — два шага»; CONTRACT-005, 9.4).

Шаг 1 — `search_head @@ q` (все слова в заголовке и тегах), порядок: ранг `ts_rank_cd` вниз, `updated_at` вниз, `id` вниз.
Шаг 2 — `search_full @@ q` и не `search_head @@ q`: 300 самых новых кандидатов (`updated_at DESC, id DESC`, раздел 17
п. 28), порядок тот же. Выдача — шаг 1, затем шаг 2; граница — `head_count`. Запрос уходит параметром (`SearchQuery`,
тип `raw`). Состояние `published` держат сами векторы: у черновиков и статей в корзине они пусты, но отбор стоит и в
запросе. Права на чтение статей не нужны — группа доступна всем вошедшим.
"""
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F

from apps.core.extensions import ParsedQuery, SearchProvider, SearchRow

from ..models import Article

CONFIG = "russian"
STEP2_CAP = 300
ORDER = 20


def _query(parsed: ParsedQuery) -> SearchQuery:
    return SearchQuery(parsed.raw, config=CONFIG, search_type="raw")


def _published():
    return Article.objects.filter(state=Article.State.PUBLISHED)


def _step1(parsed: ParsedQuery):
    """Шаг 1: опубликованные статьи, у которых все слова в малом векторе."""
    query = _query(parsed)
    return _published().filter(search_head__isnull=False, search_head=query)


def _step2(parsed: ParsedQuery):
    """Шаг 2: слова есть в полном векторе, но не все в малом (порядок — по новизне, без среза)."""
    query = _query(parsed)
    return (_published().filter(search_full__isnull=False, search_full=query)
            .exclude(search_head=query).order_by("-updated_at", "-id"))


def _row(article: Article) -> SearchRow:
    return SearchRow(title=article.title, subtitle=article.rubric.name, url=f"/kb/{article.pk}/")


def available(user) -> bool:
    """Читать статьи может любой вошедший: группа показывается всем."""
    return True


def head_count(parsed: ParsedQuery) -> int:
    """Точный счёт шага 1 — отдельный дешёвый запрос по `search_head`."""
    if parsed.hint or not parsed.raw:
        return 0
    return _step1(parsed).count()


def search(user, parsed: ParsedQuery, limit: int, offset: int) -> list[SearchRow]:
    """`limit + 1` строк со смещением `offset` по склейке шагов (лишнюю отрезает сборка, раздел 17 п. 49)."""
    if parsed.hint or not parsed.raw:
        return []
    want = limit + 1
    boundary = head_count(parsed)
    rows: list[SearchRow] = []
    if offset < boundary:
        step1 = (_step1(parsed).select_related("rubric")
                 .annotate(rank=SearchRank(F("search_head"), _query(parsed), cover_density=True))
                 .order_by("-rank", "-updated_at", "-id")[offset:offset + want])
        rows.extend(_row(article) for article in step1)
        start2 = 0
    else:
        start2 = offset - boundary
    room = want - len(rows)
    if room > 0 and start2 < STEP2_CAP:
        candidates = _step2(parsed).select_related("rubric")[:STEP2_CAP]
        rows.extend(_row(article) for article in candidates[start2:start2 + room])
    return rows


def count(user, parsed: ParsedQuery) -> tuple[int, bool]:
    """`(шаг 1 + шаг 2, потолок)`: шаг 2 считается с `LIMIT 301`; упёрлись — `(h + 300, True)` («N+»)."""
    if parsed.hint or not parsed.raw:
        return 0, False
    head = head_count(parsed)
    ids = list(_step2(parsed).values_list("pk", flat=True)[:STEP2_CAP + 1])
    if len(ids) > STEP2_CAP:
        return head + STEP2_CAP, True
    return head + len(ids), False


def search_providers() -> list[SearchProvider]:
    """Запись точки `search_providers`: группа «Статьи»."""
    return [SearchProvider(key="articles", title="Статьи", order=ORDER, search=search, count=count,
                           available=available)]
