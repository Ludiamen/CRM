"""Поставщик сквозного поиска «Подразделения» (PLAN-005, «Сквозной поиск» → поставщики; FR-441, FR-443, FR-444).

Название подразделения ищется по началу слова (`to_tsvector('russian', name) @@ to_tsquery('russian', raw)`),
группа доступна с правом `staff.view`. Запрос уходит параметром (`SearchQuery`, тип `raw`).
"""
from django.contrib.postgres.search import SearchQuery, SearchVector

from apps.core.extensions import ParsedQuery, SearchProvider, SearchRow
from apps.core.services.permissions import has_permission
from apps.org.models import Unit

CONFIG = "russian"


def available(user) -> bool:
    """Группа показывается сотруднику с правом `staff.view`."""
    return has_permission(user, "staff.view")


def _found(parsed: ParsedQuery):
    """Подразделения, чьё название подходит под запрос; без слов (только номер) — пусто."""
    if not parsed.raw:
        return Unit.objects.none()
    query = SearchQuery(parsed.raw, config=CONFIG, search_type="raw")
    return Unit.objects.annotate(name_vector=SearchVector("name", config=CONFIG)).filter(name_vector=query)


def _chain(path: str) -> list[int]:
    """Номера узлов цепочки по `path`, от корня к узлу."""
    return [int(part) for part in path.split("/") if part]


def search(user, parsed: ParsedQuery, limit: int, offset: int) -> list[SearchRow]:
    """Строки группы: название, путь (названия предков через « / », у корня пусто), адрес `/structure/<id>/`.

    Выбирается `limit + 1` строк: лишняя строка говорит странице, что есть ещё (CONTRACT-005, 9.2, п. 49 раздела 17).
    Названия предков всех строк берутся одним запросом.
    """
    units = list(_found(parsed).order_by("name", "id")[offset:offset + limit + 1])
    ancestor_ids = {pk for unit in units for pk in _chain(unit.path)[:-1]}
    names = dict(Unit.objects.filter(pk__in=ancestor_ids).values_list("pk", "name")) if ancestor_ids else {}
    return [
        SearchRow(
            title=unit.name,
            subtitle=" / ".join(names[pk] for pk in _chain(unit.path)[:-1] if pk in names),
            url=f"/structure/{unit.pk}/",
        )
        for unit in units
    ]


def count(user, parsed: ParsedQuery) -> tuple[int, bool]:
    """Точное число найденных подразделений: `(число, False)`."""
    return _found(parsed).count(), False


def search_providers() -> list[SearchProvider]:
    """Запись точки расширения `search_providers`: группа «Подразделения» (ключ `units`, порядок 40)."""
    return [SearchProvider(key="units", title="Подразделения", order=40, search=search, count=count,
                           available=available)]
