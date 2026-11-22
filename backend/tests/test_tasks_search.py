"""T-9119: поиск задач — группа «Задачи» (FR-697, NFR-712; CONTRACT-009, 11).

План «Поиск, карточка сотрудника»: провайдер `tasks` (order 62) после «Мессенджера» (61), видимость как в
списке, слова — параметрами, `ILIKE` по названию, описанию и тексту комментариев, потолок 300 строк; строка —
номер, название, исполнитель, срок, статус, отрывок, адрес `/tasks/<id>/`. Контракт: 3 (`search_providers`),
5.1 (`services.search.search_providers`), 6.1 (коды ответов), 11, 12.2 (подписи статусов), 15 (К8, К9).

Код среза на уровне модуля не импортируется: модели — через `support.model(...)`, службы и провайдер —
ленивыми импортами внутри тестов, поэтому `pytest --collect-only` проходит до появления кода. Секретов и ПДн
нет: ФИО вымышленные, адресов и телефонов тест не создаёт.
"""
import importlib
import re
from datetime import date

import pytest
from django.utils import timezone

from tests import support
from tests import support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db

TITLE = "Задачи"
WORD = "коммутатор"
DEADLINE = date(2026, 12, 31)
DEADLINE_TEXT = "31.12.2026"
NEW_LABEL = "Новая"


# --- помощники файла --------------------------------------------------------------------------------------

def _service():
    return importlib.import_module("apps.tasks.services.search")


def _provider():
    found = _service().search_providers()
    assert len(found) == 1, f"групп поиска задач: {len(found)}"
    return found[0]


def _parsed(query: str):
    from apps.search.parse import parse

    return parse(query)


def _fresh(user):
    return support.model("core.User").objects.get(pk=user.pk)


def _rows(user, query: str, limit: int = 50, offset: int = 0) -> list:
    return _provider().search(_fresh(user), _parsed(query), limit, offset)


def _count(user, query: str) -> tuple:
    return _provider().count(_fresh(user), _parsed(query))


def _urls(user, query: str) -> list[str]:
    return [row.url for row in _rows(user, query)]


def _group_keys(user) -> list[str]:
    from apps.search import services

    return [provider.key for provider in services.providers(_fresh(user))]


def _row_text(row) -> str:
    """Все видимые части строки выдачи одной строкой: заголовок, подзаголовок и контекст своего шаблона."""
    parts = [row.title, row.subtitle]

    def add(value):
        if isinstance(value, dict):
            for item in value.values():
                add(item)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                add(item)
        elif value is not None:
            parts.append(str(value))

    add(row.context)
    return " ".join(parts)


def _values(params) -> list:
    out = []
    for value in params or ():
        out.extend(value if isinstance(value, (list, tuple, set, frozenset)) else [value])
    return out


def _with_permission(code: str = "tasks.use", **extra):
    return support.make_with_permissions(code, **extra)


# --- 1. провайдер и порядок групп -------------------------------------------------------------------------

def test_provider_tasks_title_order_62_and_available_by_permission():
    """FR-697: `services.search.search_providers()` — одна запись `SearchProvider(key="tasks", title="Задачи",
    order=62, …)`; она зарегистрирована в точке `search_providers`; группа доступна держателю `tasks.use` и
    недоступна сотруднику без права; в сборщике поиска «Задачи» идут после «Мессенджера» (61)."""
    from apps.core import extensions

    owner = support_tasks.viewer(full_name="Держатель Прав")
    without = _with_permission("settings.portal", full_name="Без Прав Задач")
    provider = _provider()
    assert (provider.key, provider.title, provider.order) == ("tasks", TITLE, 62)
    for name in ("search", "count", "available"):
        assert callable(getattr(provider, name)), f"поле {name} не функция"

    registered = [func for func in extensions.registered("search_providers")
                  if func.__module__.startswith("apps.tasks")]
    assert len(registered) == 1, f"записей задач в search_providers: {len(registered)}"
    assert provider.available(_fresh(owner.user)) is True
    assert provider.available(_fresh(without.user)) is False

    keys = _group_keys(owner.user)
    assert "tasks" in keys and "messenger" in keys, f"группы поиска: {keys}"
    assert keys.index("messenger") < keys.index("tasks"), f"порядок групп: {keys}"


# --- 2. название, описание и комментарий -------------------------------------------------------------------

def test_word_in_title_description_and_comment_found_with_row_parts():
    """FR-697: слово из названия, описания и текста комментария своей задачи находится; строка содержит номер
    `#<pk>`, название, ФИО исполнителя, срок «ДД.ММ.ГГГГ», статус «Новая» и отрывок; адрес — `/tasks/<id>/`."""
    author = support_tasks.staff_user(full_name="Автор Поиска")
    assignee = support_tasks.staff_user(full_name="Исполнитель Поиска")
    task = support_tasks.make_task(f"Проверить {WORD}", author=author, assignee=assignee, deadline=DEADLINE,
                                   description="Описание про запасной кабель")
    second = support_tasks.make_task("Вторая задача", author=author, assignee=assignee,
                                     description=f"В описании тоже {WORD}")
    third = support_tasks.make_task("Третья задача", author=author, assignee=assignee)
    support.model("tasks.TaskComment").objects.create(task=third, author=author,
                                                      text=f"Комментарий про {WORD} в серверной")

    found = _rows(author, WORD)
    assert {row.url for row in found} == {f"/tasks/{task.pk}/", f"/tasks/{second.pk}/",
                                         f"/tasks/{third.pk}/"}, [row.url for row in found]
    row = next(row for row in found if row.url == f"/tasks/{task.pk}/")
    text = _row_text(row)
    assert f"#{task.pk}" in text, text
    assert WORD in text, text
    assert "Исполнитель Поиска" in text, text
    assert DEADLINE_TEXT in text, text
    assert NEW_LABEL in text, text
    assert row.title.strip(), "у строки нет названия"
    assert _count(author, WORD) == (3, False)


# --- 3. поиск по номеру -----------------------------------------------------------------------------------

def test_number_finds_task_by_pk():
    """FR-697: номер задачи (её `pk`) находит ровно эту задачу — номер стоит в строке выдачи и в адресе."""
    author = support_tasks.staff_user(full_name="Автор Номера")
    task = support_tasks.make_task("Задача с номером", author=author, assignee=author)
    support_tasks.make_task("Соседняя задача", author=author, assignee=author)
    rows = _rows(author, str(task.pk))
    assert [row.url for row in rows] == [f"/tasks/{task.pk}/"], [row.url for row in rows]
    assert f"#{task.pk}" in _row_text(rows[0])


# --- 4. видимость -------------------------------------------------------------------------------------------

def test_only_visible_and_not_deleted_tasks_are_found():
    """FR-697, FR-677: находят автор, исполнитель, соисполнитель, наблюдатель и руководитель узла; чужая задача не
    находится и не считается, удалённая (`deleted_at`) — тоже; администратор чужих задач не видит."""
    unit = support_org.make_unit("Отдел Поиска Задач")
    head = support_tasks.head_of(unit, full_name="Руководитель Поиска")
    author = support.make_employee(full_name="Автор В Узле")
    support_org.make_member(author, unit)
    assignee = support.make_employee(full_name="Исполнитель В Узле")
    support_org.make_member(assignee, unit)
    coexecutor = support_tasks.staff_user(full_name="Соисполнитель Поиска")
    observer = support_tasks.staff_user(full_name="Наблюдатель Поиска")
    task = support_tasks.make_task(f"Секретная {WORD}", author=author, assignee=assignee)
    support_tasks.add_member(task, coexecutor, role="coexecutor")
    support_tasks.add_member(task, observer, role="observer")

    for person in (author, assignee, coexecutor, observer, head):
        assert _urls(person, WORD) == [f"/tasks/{task.pk}/"], person.full_name
    outsider = _with_permission("tasks.use", full_name="Посторонний Сотрудник")
    assert _urls(outsider, WORD) == []
    assert _count(outsider, WORD) == (0, False)
    admin = support.make_admin(full_name="Администратор Портала")
    assert _urls(admin, WORD) == [], "администратор видит чужую задачу"

    removed = support_tasks.make_task(f"Удалённая {WORD}", author=author, assignee=assignee)
    support.model("tasks.Task").objects.filter(pk=removed.pk).update(deleted_at=timezone.now())
    assert f"/tasks/{removed.pk}/" not in _urls(author, WORD), "удалённая задача находится"
    assert _count(author, WORD) == (1, False)


# --- 5. потолок 300 ----------------------------------------------------------------------------------------

def test_count_ceiling_300():
    """FR-697: число группы — с потолком 300: ровно 300 задач дают `(300, False)`, 301-я — `(300, True)`; выдача
    тоже не длиннее 300 строк."""
    author = support_tasks.staff_user(full_name="Автор Потолка")
    Task = support.model("tasks.Task")
    Task.objects.bulk_create([
        Task(title=f"Потолочная {WORD} {number}", author=author, assignee=author, status="new")
        for number in range(300)])
    assert _count(author, WORD) == (300, False)
    Task.objects.create(title=f"Потолочная {WORD} 301", author=author, assignee=author, status="new")
    assert _count(author, WORD) == (300, True)
    assert len(_rows(author, WORD, limit=1000)) == 300


# --- 6. SQL: слова параметрами, ILIKE, удалённые -----------------------------------------------------------

def test_search_sql_passes_words_as_parameters_and_filters_deleted():
    """NFR-712: слово запроса уходит параметром (в тексте SQL его нет), поиск идёт `ILIKE` по названию, описанию и
    тексту комментариев; в SQL стоит условие `deleted_at IS NULL`; кавычки и знаки `%` не ломают выдачу и не
    меняют таблицы."""
    author = support_tasks.staff_user(full_name="Автор SQL")
    task = support_tasks.make_task(f"Метка {WORD}", author=author, assignee=author)
    marker = "zqxtaskword"
    support_tasks.make_task(f"Метка {marker}", author=author, assignee=author)

    with support_tasks.queries_with_params() as pairs:
        _rows(author, marker)
        _count(author, marker)
    task_pairs = [(sql, params) for sql, params in pairs if "tasks_" in sql]
    assert task_pairs, "запросов к таблицам задач не было"
    sql_text = "\n".join(sql for sql, _ in task_pairs)
    assert marker not in sql_text, "слово запроса попало в текст SQL"
    assert marker in [str(value) for _, params in task_pairs for value in _values(params)], (
        "слова запроса нет среди параметров")
    assert re.search(r"\bILIKE\b", sql_text, re.I), "поиск идёт не через ILIKE"
    assert re.search(r"deleted_at\s+IS\s+NULL", sql_text, re.I), "в SQL нет условия «не удалена»"
    assert re.search(r"tasks_taskcomment|comment", sql_text, re.I), "SQL не заглядывает в комментарии"

    for hostile in ("o'reilly", "100% & _", "'; drop table tasks_task; --", "проценты%подчёрк_а"):
        _rows(author, hostile)
        _count(author, hostile)
    assert support.model("tasks.Task").objects.filter(pk=task.pk).exists()


# --- 7. страница поиска ------------------------------------------------------------------------------------

def test_search_page_has_tasks_group_with_title_and_links():
    """FR-697: на `/search/?q=` видна группа `section[data-search-group="tasks"]` с заголовком «Задачи» и ссылкой
    на найденную задачу; сотруднику без `tasks.use` группы нет."""
    author = support_tasks.staff_user(full_name="Автор Страницы")
    task = support_tasks.make_task(f"Страничная {WORD}", author=author, assignee=author)
    client = support.logged_in(author)
    response = client.get("/search/", {"q": WORD})
    assert response.status_code == 200, f"/search/: {response.status_code}"
    html = response.content.decode("utf-8")
    assert 'data-search-group="tasks"' in html, "на странице поиска нет группы «Задачи»"
    start = html.index('data-search-group="tasks"')
    window = html[start:start + 4000]
    assert TITLE in window, "в группе нет заголовка «Задачи»"
    assert f"/tasks/{task.pk}/" in window, "в группе нет ссылки на задачу"

    without = _with_permission("settings.portal", full_name="Без Прав Страницы")
    page = support.logged_in(without).get("/search/", {"q": WORD}).content.decode("utf-8")
    assert 'data-search-group="tasks"' not in page, "группа задач видна без tasks.use"


# --- 8. без права и без приложения -------------------------------------------------------------------------

def test_provider_unavailable_without_permission_and_group_absent():
    """FR-697: без `tasks.use` провайдер отвечает `available=False`, в сборщике поиска группы нет, страница поиска
    открывается без ошибки; с правом группа возвращается."""
    owner = support_tasks.viewer(full_name="Держатель Группы")
    without = _with_permission("settings.portal", full_name="Без Группы")
    assert "tasks" in _group_keys(owner.user)
    assert "tasks" not in _group_keys(without.user)
    response = support.logged_in(without).get("/search/", {"q": WORD})
    assert response.status_code == 200
    assert _provider().available(_fresh(owner.user)) is True
    assert _provider().available(_fresh(without.user)) is False