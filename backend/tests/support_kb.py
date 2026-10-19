"""Общие помощники тестов среза 005 (T-5101): база знаний и сквозной поиск.

Имена и поведение — `tests/CONTRACT-005.md` (шапка «Правила для всех тестов среза», разделы 1.2, 2.2-2.4, 3.1, 3.6,
5.7, 5.8, 16). Кода `knowledge` и `search` ещё может не быть, поэтому на уровне модуля нет импортов из
`apps.knowledge` и `apps.search`: модели берутся лениво (`support.model("knowledge.Article")`), всё остальное
импортируется внутри функций. Сбор тестов (`pytest --collect-only`) проходит до появления кода.

Фикстур `@pytest.fixture` здесь нет: подключение через `tests/conftest.py` в задание T-5101 не входило, поэтому
подмены — обычные функции и контекстные менеджеры (как `support_org.scan_clean`, `support_org.no_extensions`);
тест зовёт их, передавая `monkeypatch` параметром.

ОТСТУПЛЕНИЕ ОТ РЕШЕНИЯ 18 ЗАДАЧ (по указанию Opus): помощников двух потоков и удержания замка строки во втором
соединении здесь нет, потому что `django_db(transaction=True)` в проекте не работает (см. `tests/conftest.py`), а второй
поток не видит данных теста. Вместо них — проверка по SQL: `sql_of`, `capture_sql`, `assert_for_update`,
`assert_skip_locked`, `advisory_locks`.

Секреты и персональные данные (решение 17 задач): адреса и телефоны собираются из частей функциями `email_of`,
`phone_of`; в именах переменных нет слов `secret`, `token`, `key`, `password`.
"""
import contextlib
import html as html_lib
import importlib
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Callable, NamedTuple
from zoneinfo import ZoneInfo

from django.db import connection, connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support
from tests.support_org import eicar_bytes, jpeg_bytes, png_bytes  # noqa: F401  (картинки и EICAR для вложений)
from tests.support_org import scan_clean, scan_found, scan_unavailable  # noqa: F401  (подмена ClamAV строкой, раздел 1.2)

# --- права, названия и точки расширения среза 005 (раздел 3.6) ---------------------------------------

PERMISSIONS_005 = ("knowledge.edit", "knowledge.manage")
TITLES_005 = {"knowledge.edit": "Редактирование базы знаний", "knowledge.manage": "Управление базой знаний"}
POINTS_005 = ("search_providers", "ticket_card_parts")

MOSCOW = ZoneInfo("Europe/Moscow")

# пути, которые обходит тест «тексты по-русски» (NFR-409; раздел 1.2, T-5129)
RUSSIAN_PAGES = ("/kb/", "/kb/new/", "/kb/rubrics/", "/kb/trash/", "/kb/settings/", "/search/?q=" + "впн")


def article_pages(article) -> tuple[str, ...]:
    """Страницы одной статьи для «тексты по-русски»: чтение, правка, история, сравнение, просмотр версии."""
    base = f"/kb/{article.pk}/"
    return (base, base + "edit/", base + "history/", base + "compare/?v=1&v=2", base + "versions/1/")


# --- адреса и телефоны для проб ПДн (решение 17 задач) -----------------------------------------------

def email_of(local: str = "ivanov", domain: str = "example.test") -> str:
    """Тестовый адрес почты, собранный из частей."""
    return local + "@" + domain


def phone_of(*groups: str) -> str:
    """Тестовый телефон из групп цифр: `phone_of("+7", "900", "123", "45", "67")`."""
    groups = groups or ("+7", "900", "123", "45", "67")
    return groups[0] + " " + "-".join(groups[1:]) if len(groups) > 1 else groups[0]


# --- права и вход ролями (раздел 3.6, 5.7) -----------------------------------------------------------

def grant(user, *codes: str):
    """Выдаёт сотруднику права через отдельную роль, не меняя встроенные роли (раздел 3.6; решение T-5101).

    Строки прав создаются, если их ещё нет; кэш прав сотрудника сбрасывается сразу (сигнал ядра сбрасывает его
    только после фиксации, а внутри транзакции теста она не наступает). Возвращает созданную роль."""
    from django.core.cache import cache

    from apps.core.services import permissions

    Permission = support.model("core.Permission")
    for code in codes:
        Permission.objects.get_or_create(code=code, defaults={"title": TITLES_005.get(code, code)})
    role = factories.make_role(permissions=codes)
    user.roles.add(role)
    cache.delete(permissions._key(user.pk))
    return role


class Session(NamedTuple):
    """Сотрудник и вошедший клиент."""
    user: object
    client: object


def _session(*codes: str, **extra) -> Session:
    user = support.make_employee(**extra)
    if codes:
        grant(user, *codes)
    return Session(user, support.logged_in(user))


def as_reader(**extra) -> Session:
    """Читатель: вошёл, прав базы знаний нет."""
    return _session(**extra)


def as_editor(**extra) -> Session:
    """«Редактирование»: право `knowledge.edit`."""
    return _session("knowledge.edit", **extra)


def as_manager(**extra) -> Session:
    """«Управление»: право `knowledge.manage` (редактирования отдельно не выдаётся: управление включает его)."""
    return _session("knowledge.manage", **extra)


# --- фабрики: рубрики, теги (раздел 2.2) -------------------------------------------------------------

def general_rubric():
    """Рубрика «Общее»: её создала миграция `knowledge 0002` (раздел 2.4), здесь она только находится."""
    return support.model("knowledge.Rubric").objects.get(is_default=True)


def make_rubric(name: str | None = None, *, parent=None):
    """Рубрика; `depth` — глубина родителя плюс один."""
    import secrets

    return support.model("knowledge.Rubric").objects.create(
        name=name or f"Рубрика {secrets.token_hex(3)}", parent=parent, depth=(parent.depth + 1) if parent else 1)


def rubric_tree(spec: dict, parent=None) -> dict:
    """Дерево рубрик из словаря `{"Сети": {"VPN": {}}, "Почта": {}}`; возвращает `{название: рубрика}`."""
    made: dict = {}
    for name, children in spec.items():
        made[name] = make_rubric(name, parent=parent)
        made.update(rubric_tree(children or {}, made[name]))
    return made


def make_tag(name: str):
    """Тег; имя приводится к нижнему регистру, как это делает служба."""
    tag, _ = support.model("knowledge.Tag").objects.get_or_create(name=name.strip().lower())
    return tag


# --- фабрики: статьи и версии (раздел 2.2) -----------------------------------------------------------

def set_vectors(article) -> None:
    """Считает `search_head` (заголовок A, теги B) и `search_full` (плюс текст C, первые 100 000 знаков `plain`).

    Конфигурация `russian`, как в разделе 9.4; у черновика и статьи в корзине векторы остаются `NULL`."""
    Article = support.model("knowledge.Article")
    tags = " ".join(article.tags.values_list("name", flat=True))
    head = "setweight(to_tsvector('russian', %s), 'A') || setweight(to_tsvector('russian', %s), 'B')"
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {Article._meta.db_table} SET search_head = {head}, "
            f"search_full = {head} || setweight(to_tsvector('russian', left(%s, 100000)), 'C') WHERE id = %s",
            [article.title, tags, article.title, tags, article.plain, article.pk])
    article.refresh_from_db(fields=["search_head", "search_full"])


def _snapshot(article, number: int, author, comment: str, created_at):
    return support.model("knowledge.ArticleVersion").objects.create(
        article=article, number=number, author=author, created_at=created_at, comment=comment,
        title=article.title, text=article.text, html=article.html, rubric=article.rubric,
        rubric_name=article.rubric.name, tags=sorted(article.tags.values_list("name", flat=True)))


def make_article(*, title: str | None = None, text: str = "Текст статьи", rubric=None, tags=(), author=None,
                 state: str = "draft", state_before_trash: str = "published", from_ticket: int | None = None,
                 deleted_by=None, comment: str = "", vectors: bool = True):
    """Статья с версией 1 (прямой записью в базу, без служб).

    `state`: `draft`, `published`, `trash`. Выдерживаются инварианты раздела 2.2: опубликованная — `published_at`;
    в корзине — `deleted_at`, `deleted_by`, `state_before_trash` (по умолчанию `published`; у `draft` статья
    остаётся без `published_at`); векторы — только у опубликованной (`vectors=False` оставляет `NULL`).
    Время — `timezone.now()`, поэтому с фикстурой `clock` статья получает «часы теста»."""
    import secrets

    if state not in ("draft", "published", "trash"):
        raise ValueError(f"state: draft, published или trash, получено {state!r}")
    if author is None:
        author = support.make_employee()
        grant(author, "knowledge.edit")
    rubric = rubric or general_rubric()
    now = timezone.now()
    was_published = state == "published" or (state == "trash" and state_before_trash == "published")
    article = support.model("knowledge.Article").objects.create(
        title=title or f"Статья {secrets.token_hex(3)}", text=text, html=f"<p>{html_lib.escape(text)}</p>", plain=text,
        rubric=rubric, state=state, state_before_trash=state_before_trash if state == "trash" else "",
        author=author, created_at=now, updated_by=author, updated_at=now, version_no=1,
        published_at=now if was_published else None,
        deleted_at=now if state == "trash" else None,
        deleted_by=(deleted_by or author) if state == "trash" else None,
        from_ticket=from_ticket)
    if tags:
        article.tags.set([make_tag(name) for name in tags])
    _snapshot(article, 1, author, comment, now)
    if state == "published" and vectors:
        set_vectors(article)
    return article


def make_draft(**over):
    """Черновик (раздел 2.3, `Article.State.DRAFT`)."""
    return make_article(state="draft", **over)


def make_published(**over):
    """Опубликованная статья: `published_at` и векторы заполнены."""
    return make_article(state="published", **over)


def make_trashed(*, was: str = "published", **over):
    """Статья в корзине; `was` — состояние до корзины (`state_before_trash`)."""
    return make_article(state="trash", state_before_trash=was, **over)


def add_version(article, *, author=None, text: str | None = None, title: str | None = None, comment: str = "",
                tags=None, rubric=None, created_at=None):
    """Следующая версия: номер `version_no + 1`, поля статьи обновляются по версии (как после сохранения)."""
    author = author or article.updated_by
    article.title = title if title is not None else article.title
    article.text = text if text is not None else article.text
    article.html, article.plain = f"<p>{html_lib.escape(article.text)}</p>", article.text
    article.rubric = rubric or article.rubric
    article.version_no += 1
    article.updated_by, article.updated_at = author, created_at or timezone.now()
    article.save()
    if tags is not None:
        article.tags.set([make_tag(name) for name in tags])
    return _snapshot(article, article.version_no, author, comment, article.updated_at)


# --- фабрики: вложения, связи, подписки, комментарии ----------------------------------------------------

def attach_file(article, name: str = "схема.png", data: bytes | None = None, *, status: str = "clean",
                image_format: str | None = None, uploaded_by=None, write: bool = False):
    """Строка `ArticleFile` со строкой `StoredFile` (`purpose="knowledge"`, `owner=None`).

    `status` — `pending`, `clean`, `quarantine`; `image_format` по умолчанию определяется по расширению имени
    (`png`, `jpeg`, `gif`, `webp`, иначе пусто). С `write=True` байты пишутся на диск по `files.attachment_path`
    (нужна фикстура `protected_root`). ClamAV подменяют `scan_clean`, `scan_found`, `scan_unavailable`
    (строка `apps.integrations.clamav.services.scan`, раздел 1.2)."""
    if data is None:
        data = png_bytes() if name.lower().endswith(".png") else b"file body"
    if image_format is None:
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        image_format = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "webp": "webp"}.get(ext, "")
    uploaded_by = uploaded_by or article.author
    stored = support.model("core.StoredFile").objects.create(
        purpose="knowledge", owner=None, size=len(data), sha256=_sha256(data),
        content_type="image/" + image_format if image_format else "application/octet-stream", status=status,
        scanned_at=timezone.now() if status != "pending" else None)
    if write:
        from apps.core.services import files

        path = files.attachment_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return support.model("knowledge.ArticleFile").objects.create(
        article=article, file=stored, name=name, image_format=image_format, uploaded_by=uploaded_by,
        uploaded_at=timezone.now())


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def link_ticket(article, ticket_number: int, *, user=None, from_resolution: bool = False):
    """Связь статьи с заявкой (`TicketLink`, без внешнего ключа на заявку)."""
    return support.model("knowledge.TicketLink").objects.create(
        article=article, ticket_number=ticket_number, linked_by=user or article.author, linked_at=timezone.now(),
        from_resolution=from_resolution)


def subscribe(user, rubric):
    """Подписка сотрудника на рубрику (`RubricSubscription`)."""
    return support.model("knowledge.RubricSubscription").objects.create(
        user=user, rubric=rubric, created_at=timezone.now())


def make_comment(article, author=None, text: str = "Комментарий", *, created_at=None):
    """Комментарий ядра к статье: `core.Comment` с `object_ref="knowledge.article:<id>"` (раздел 3.4)."""
    return support.model("core.Comment").objects.create(
        object_ref=f"knowledge.article:{article.pk}", author=author or article.author, text=text,
        created_at=created_at or timezone.now())


# --- время по Москве (раздел 1.2, NFR-409) ----------------------------------------------------------------

def moscow(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Момент по московскому времени (с часовым поясом)."""
    return datetime(year, month, day, hour, minute, tzinfo=MOSCOW)


def moscow_text(moment: datetime) -> str:
    """Текст «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве, как его выводят страницы среза (раздел 11, `time[data-at]`)."""
    return moment.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")


def utc_midnight(clock, year: int = 2026, month: int = 3, day: int = 10) -> datetime:
    """Ставит часы теста на полночь UTC (в Москве — 03:00 того же дня) и возвращает этот момент."""
    moment = datetime(year, month, day, 0, 0, tzinfo=ZoneInfo("UTC"))
    clock.set(moment)
    return moment


# --- ночная очистка корзины (раздел 5.7, решение 5 задач) -------------------------------------------------

def run_purge():
    """`apps.knowledge.tasks.purge_trash()` синхронно, без очереди и расписания, внутри исполнения обработчиков
    «после фиксации» (стирание файлов идёт в `transaction.on_commit`). `PurgeFailed` пробрасывается."""
    from django.db import DEFAULT_DB_ALIAS
    from django.test import TestCase

    from apps.knowledge import tasks

    with TestCase.captureOnCommitCallbacks(using=DEFAULT_DB_ALIAS, execute=True):
        return tasks.purge_trash()


# --- подмены для тестов сбоев (раздел 5.8, решения 32 и 41) -----------------------------------------------

def fail_purge_for(monkeypatch, numbers, exc: Exception | None = None) -> list:
    """Сбой удаления для статей с заданными номерами: подменяет атрибут модуля `articles.purge`; для остальных
    зовётся настоящая функция. Возвращает список номеров, с которыми `purge` вызывали."""
    from apps.knowledge.services import articles

    numbers, calls, real = set(numbers), [], articles.purge

    def wrapper(article, *args, **kwargs):
        calls.append(article.pk)
        if article.pk in numbers:
            raise exc or RuntimeError("сбой удаления (тест)")
        return real(article, *args, **kwargs)

    monkeypatch.setattr(articles, "purge", wrapper)
    return calls


def act_between_batch_and_lock(monkeypatch, action: Callable[[list], None]) -> list:
    """Действие между выборкой порции и замком строки: после настоящей `retention.next_batch` зовёт
    `action(порция)` и возвращает порцию как была. Возвращает список выданных порций."""
    from apps.knowledge.services import retention

    batches, real = [], retention.next_batch

    def wrapper(*args, **kwargs):
        batch = real(*args, **kwargs)
        batches.append(list(batch))
        action(batch)
        return batch

    monkeypatch.setattr(retention, "next_batch", wrapper)
    return batches


@contextlib.contextmanager
def preview_lock_busy(user, seconds: int = 10):
    """Занятый замок предпросмотра: ключ `kb:preview:<user_id>` в Valkey на `seconds` секунд; при выходе снимается."""
    from apps.core.services import valkey

    name = f"kb:preview:{user.pk}"
    valkey.conn().set(name, "1", ex=seconds)
    try:
        yield name
    finally:
        valkey.conn().delete(name)


def fail_version_creation(monkeypatch, exc: Exception | None = None) -> None:
    """Сбой версии при первом сохранении: подмена `articles._create_version` (решение Opus по З21)."""
    from apps.knowledge.services import articles

    def boom(*args, **kwargs):
        raise exc or RuntimeError("сбой версии (тест)")

    monkeypatch.setattr(articles, "_create_version", boom)


def fail_file_write(monkeypatch, message: str = "disk error") -> list:
    """Сбой записи файла (решение 41): `uploads.write_file` поднимает `OSError`. Возвращает пути вызовов."""
    from apps.core.services import uploads

    calls: list = []

    def boom(path, data):
        calls.append(str(path))
        raise OSError(message)

    monkeypatch.setattr(uploads, "write_file", boom)
    return calls


@contextlib.contextmanager
def without_knowledge():
    """«Модуль выключен» (раздел 3.1, 5.8): из всех точек реестра на время блока снимаются функции модулей
    `apps.knowledge` и `apps.search`; прочие регистрации остаются; `INSTALLED_APPS` не перезагружается."""
    from apps.core import extensions

    saved = {point: list(funcs) for point, funcs in extensions._registry.items()}
    for point, funcs in extensions._registry.items():
        funcs[:] = [f for f in funcs if not getattr(f, "__module__", "").startswith(("apps.knowledge", "apps.search"))]
    try:
        yield
    finally:
        for point, funcs in saved.items():
            extensions._registry[point][:] = funcs


@contextlib.contextmanager
def without_registrations(*points: str):
    """Выключает записи только названных точек (например `without_registrations("staff_directory")`);
    остальные точки остаются как были (раздел 5.8, пункт г)."""
    from apps.core import extensions

    for point in points:
        if point not in extensions._registry:
            raise ValueError(f"нет точки расширения {point!r}")
    saved = {point: list(extensions._registry[point]) for point in points}
    for point in points:
        extensions._registry[point][:] = []
    try:
        yield
    finally:
        for point, funcs in saved.items():
            extensions._registry[point][:] = funcs


# --- миграция данных knowledge 0002 (раздел 2.4, решение 40) -----------------------------------------------

def run_seed(using: str | None = None) -> None:
    """Вызывает `seed(django.apps.apps, SimpleNamespace(connection=…))` из `knowledge 0002_initial_data`.

    `using` — алиас базы; по умолчанию `migrate`, если он настроен, иначе `default` (уточнение A-4)."""
    from django.apps import apps

    if using is None:
        using = "migrate" if "migrate" in connections.databases else "default"
    module = importlib.import_module("apps.knowledge.migrations.0002_initial_data")
    module.seed(apps, SimpleNamespace(connection=connections[using]))


# --- проверка по SQL вместо гонок (по указанию Opus) ---------------------------------------------------------

@contextlib.contextmanager
def capture_sql():
    """Контекст: список SQL выполненных запросов соединения `default` (`CaptureQueriesContext`)."""
    sqls: list[str] = []
    with CaptureQueriesContext(connection) as ctx:
        yield sqls
    sqls.extend(q["sql"] for q in ctx.captured_queries)


def sql_of(func: Callable, *args, **kwargs) -> list[str]:
    """Выполняет `func(*args, **kwargs)` и возвращает список SQL выполненных запросов по порядку."""
    with capture_sql() as sqls:
        func(*args, **kwargs)
    return sqls


def _mentions(sql: str, table: str) -> bool:
    return f'"{table}"' in sql or re.search(rf"\b{re.escape(table)}\b", sql) is not None


def assert_for_update(sqls, table: str) -> str:
    """Среди запросов есть `SELECT … FOR UPDATE` по таблице; возвращает найденный запрос."""
    for sql in sqls:
        if sql.lstrip().upper().startswith("SELECT") and re.search(r"\bFOR UPDATE\b", sql, re.I) and _mentions(sql, table):
            return sql
    raise AssertionError(f"нет SELECT … FOR UPDATE по таблице {table}: {len(sqls)} запросов")


def assert_skip_locked(sqls, table: str) -> str:
    """Среди запросов есть `FOR UPDATE SKIP LOCKED` по таблице; возвращает найденный запрос."""
    for sql in sqls:
        if re.search(r"\bFOR UPDATE\b.*\bSKIP LOCKED\b", sql, re.I | re.S) and _mentions(sql, table):
            return sql
    raise AssertionError(f"нет FOR UPDATE SKIP LOCKED по таблице {table}: {len(sqls)} запросов")


class AdvisoryLock(NamedTuple):
    """Вызов замка: `kind` — `"exclusive"` (`pg_advisory_xact_lock`) или `"shared"` (`…_shared`), `key` — строка
    ключа из `hashtextextended('<ключ>', 0)` либо число, если замок взят по числу."""
    kind: str
    key: str


_LOCK_RE = re.compile(
    r"pg_advisory_xact_lock(_shared)?\s*\(\s*(?:hashtextextended\s*\(\s*'((?:[^']|'')*)'\s*,\s*0\s*\)|(-?\d+))\s*\)",
    re.I)


def advisory_locks(sqls) -> list[AdvisoryLock]:
    """Вызовы `pg_advisory_xact_lock` и `pg_advisory_xact_lock_shared` в порядке выполнения.

    Ключ берётся из подставленного текста запроса (`CaptureQueriesContext` показывает параметры подставленными)."""
    found = []
    for sql in sqls:
        for match in _LOCK_RE.finditer(sql):
            key = match.group(2).replace("''", "'") if match.group(2) is not None else match.group(3)
            found.append(AdvisoryLock("shared" if match.group(1) else "exclusive", key))
    return found


# --- очистка таблиц среза (для тестов, создающих данные через соединение `migrate`) ------------------------

def wipe_kb_tables(using: str = "default") -> None:
    """Стирает данные среза: связи, подписки, версии, статьи, теги, рубрики кроме «Общее», файлы статей,
    комментарии с префиксом `knowledge.article:` (порядок учитывает `PROTECT`)."""
    ArticleFile = support.model("knowledge.ArticleFile")
    ids = list(ArticleFile.objects.using(using).values_list("file_id", flat=True))
    support.model("knowledge.TicketLink").objects.using(using).all().delete()
    support.model("knowledge.RubricSubscription").objects.using(using).all().delete()
    ArticleFile.objects.using(using).all().delete()
    support.model("core.StoredFile").objects.using(using).filter(pk__in=ids).delete()
    support.model("core.Comment").objects.using(using).filter(object_ref__startswith="knowledge.article:").delete()
    support.model("knowledge.Article").objects.using(using).all().delete()
    support.model("knowledge.Tag").objects.using(using).all().delete()
    Rubric = support.model("knowledge.Rubric")
    for rubric in Rubric.objects.using(using).filter(is_default=False).order_by("-depth"):
        rubric.delete()
