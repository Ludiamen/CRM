"""Поставщик «Сотрудники» сквозного поиска (PLAN-005, «Сквозной поиск» → «Сотрудники»; FR-441, FR-443…FR-445).

Вектор полей справочника строится в запросе, без хранимого столбца. Каждое слово ищется отдельным условием
«вектор @@ слово:* или условие записи `staff_directory.search(слово)`»; все слова — И. Слова, дающие пустой запрос
`to_tsquery` (стоп-слова), отбрасываются заранее одним запросом. Строка запроса уходит в базу только параметрами.
"""
from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db import connection
from django.db.models import F, Func, Q, Value
from django.template.loader import render_to_string

from apps.core import extensions
from apps.core.models import User, UserState
from apps.core.services import files, permissions
from apps.core.services.accounts import fold

CONFIG = "russian"
PERMISSION = "staff.view"


def _vector() -> SearchVector:
    """ФИО, должность, почта как есть и по частям, телефон как есть и цифрами (и с `8` вместо `7`), внутренний
    телефон, место работы."""
    parts = Func(F("email"), Value("@._/-"), Value("     "), function="translate")
    digits = Func(F("phone"), Value(r"\D"), Value(""), Value("g"), function="regexp_replace")
    eight = Func(digits, Value("^7"), Value("8"), function="regexp_replace")
    return SearchVector("full_name", "position", "email", parts, "phone", digits, eight, "internal_phone",
                        "workplace", config=CONFIG)


def _useful_words(words) -> list[str]:
    """Слова без стоп-слов: `numnode(to_tsquery('russian', слово:*)) = 0` проверяется одним запросом."""
    words = list(dict.fromkeys(words))
    if not words:
        return []
    with connection.cursor() as cursor:
        cursor.execute("SELECT w FROM unnest(%s::text[]) AS w WHERE numnode(to_tsquery('russian', w || ':*')) > 0",
                       [words])
        kept = {row[0] for row in cursor.fetchall()}
    return [word for word in words if word in kept]


def _directory(user):
    """Условия поиска и колонка «unit» записей `staff_directory` (без `org` их нет)."""
    searches, unit_templates = [], []
    for func in extensions.registered("staff_directory"):
        found = func(user)
        if found.search is not None:
            searches.append(found.search)
        unit_templates += [column.template for column in found.columns if column.key == "unit"]
    return searches, unit_templates


def _queryset(user, parsed):
    """Активные сотрудники, подошедшие под все слова запроса; порядок `full_name`, `pk`."""
    qs = User.objects.filter(state=UserState.ACTIVE)
    if parsed.hint:
        return qs.none()
    words = _useful_words(parsed.words)
    if not words:
        return qs.none()
    searches, _ = _directory(user)
    qs = qs.annotate(_staff_vector=_vector())
    for word in words:
        condition = Q(_staff_vector=SearchQuery(f"{word}:*", config=CONFIG, search_type="raw"))
        for search in searches:
            condition |= search(fold(word))
        qs = qs.filter(condition)
    return qs.order_by("full_name", "pk")


class _Page(list):
    """Страница людей: колонка «Подразделение» кладёт в неё названия узлов всей страницы одним запросом."""


def search(user, parsed, limit: int, offset: int) -> list[extensions.SearchRow]:
    """Строки группы: ФИО, должность, подразделение (колонка `unit`), фото, карточка `/staff/<id>/`.

    Выбирает `limit + 1` строк (CONTRACT-005, раздел 17 п. 49, 73): лишняя нужна сборке выдачи для признака «есть ещё»,
    она отрезает её по `> limit`.
    """
    people = _Page(_queryset(user, parsed).select_related("photo")[offset:offset + limit + 1])
    _, unit_templates = _directory(user)
    rows = []
    for person in people:
        unit = "".join(render_to_string(template, {"person": person, "page": people}).strip()
                       for template in unit_templates)
        rows.append(extensions.SearchRow(
            title=person.full_name, subtitle=person.position, url=f"/staff/{person.pk}/",
            template="search/rows/_staff.html",
            context={"unit": unit, "photo": files.photo_url(person, 96)}))
    return rows


def count(user, parsed) -> tuple[int, bool]:
    """Точное число сотрудников группы."""
    return _queryset(user, parsed).count(), False


def available(user) -> bool:
    """Группа видна только с правом `staff.view` (одно `accounts.manage` её не даёт)."""
    return permissions.has_permission(user, PERMISSION)


def search_providers() -> list[extensions.SearchProvider]:
    """Функция точки `search_providers`: одна запись «Сотрудники» (порядок 30)."""
    return [extensions.SearchProvider(key="staff", title="Сотрудники", order=30, search=search, count=count,
                                      available=available)]
