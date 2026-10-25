"""Общие помощники тестов среза 006 (T-6101): списки.

Имена и поведение — `tests/CONTRACT-006.md` (шапка «Правила для всех тестов среза», разделы 1.2, 2.2-2.4, 3.4,
5.2, 5.8, 5.9; решения задач 6, 12, 20, 21, 24, 35, 45; И1, И2; К24, К25). Кода `lists` ещё может не быть, поэтому
на уровне модуля нет импортов из `apps.lists`: модели берутся лениво (`support.model("lists.Record")`), службы среза
импортируются внутри функций. Сбор тестов (`pytest --collect-only`) проходит до появления кода.

Фикстур `@pytest.fixture` здесь нет (как в `support_kb.py`): подмены — обычные функции и контекстные менеджеры,
тест передаёт им `monkeypatch` параметром.

Гонки — без потоков (решение 6 задач): `django_db(transaction=True)` в проекте не работает, поэтому замки и порядок
запросов проверяются по SQL (`capture_sql`, `sql_of`, `assert_for_update`, `list_locks`), а «действие между выборкой
и замком» — подменой `reminders.select_candidates` (`act_between_select_and_lock`, решение 45).

Секреты и персональные данные (решение 12 задач): адреса и телефоны собираются из частей (`email_of`, `phone_of`);
в именах переменных нет слов `secret`, `token`, `key`, `password`.

Повторный экспорт из `support_kb` (раздел 5.9 разрешает «как в `support_kb`»): `Session`, `capture_sql`, `sql_of`,
`assert_for_update`, `moscow`, `moscow_text`, `email_of`, `phone_of`, `fail_file_write`, подмены ClamAV.
"""
import contextlib
import csv
import hashlib
import importlib
import io
import itertools
import mimetypes
import re
import secrets
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Callable, NamedTuple

from django.db import connection, connections
from django.utils import timezone

from tests import factories, support
from tests.support_kb import Session  # noqa: F401  («сотрудник и клиент», как в срезе 005)
from tests.support_kb import assert_for_update, capture_sql, sql_of  # noqa: F401  (проверка по SQL, раздел 5.9)
from tests.support_kb import email_of, phone_of  # noqa: F401  (адреса и телефоны из частей, решение 12)
from tests.support_kb import fail_file_write  # noqa: F401  (сбой `core.uploads.write_file`, раздел 5.8)
from tests.support_kb import moscow, moscow_text  # noqa: F401  (время по Москве, раздел 1.1)
from tests.support_org import scan_clean, scan_found, scan_unavailable  # noqa: F401  (подмена ClamAV, решение 44)

# --- права среза (решение 24 задач) -------------------------------------------------------------------

PERMISSIONS_006 = ("lists.manage",)
TITLES_006 = {"lists.manage": "Управление списками"}

# устойчивые коды стартовых списков миграции `lists 0002` (раздел 2.4)
_SEED_CODES = ("equipment", "licenses", "consumables", "signatures", "contracts", "sims")

# пределы и тексты загрузки (план, «Загрузка из таблицы»; контракт, раздел 12.2 — восемь ключей `table_file`)
_IMPORT_LIMITS = {"max_bytes": 5 * 1024 * 1024, "max_rows": 5000, "max_parts": 100, "max_unpacked": 50 * 1024 * 1024}
_FORMAT = "Формат не поддерживается"
_IMPORT_TEXTS = {
    "too_big": "Файл больше 5 МБ",
    "too_many_rows": "Строк больше 5 000",
    "bad_format": _FORMAT,
    "bad_format_archive": _FORMAT,
    "bad_format_csv": _FORMAT,
    "not_utf8": _FORMAT,
    "xml_bomb": _FORMAT,
    "zip_bomb": _FORMAT,
}

_ALLOWED_OFF = ("apps.servicedesk", "apps.notify", "apps.org")
_LEVELS = ("read", "edit")
_FILE_STATUSES = ("pending", "clean", "quarantine")
_list_counter = itertools.count(100000 + secrets.randbelow(800000))


# --- вход ролями (раздел 5.9; К25: «читает» и «правит» — свойство пары «сотрудник, список») ------------

def _employee_with_role(role, **extra):
    roles = list(extra.pop("roles", ())) + [role]
    return support.make_employee(roles=roles, **extra)


def as_reader(lst, **extra) -> Session:
    """Сотрудник с новой ролью без прав, которой выдан `grant_list(lst, role, "read")`; вошёл."""
    role = factories.make_role()
    grant_list(lst, role, "read")
    user = _employee_with_role(role, **extra)
    return Session(user, support.logged_in(user))


def as_editor(lst, **extra) -> Session:
    """То же с уровнем `"edit"`."""
    role = factories.make_role()
    grant_list(lst, role, "edit")
    user = _employee_with_role(role, **extra)
    return Session(user, support.logged_in(user))


def as_manager(**extra) -> Session:
    """Сотрудник с ролью, у которой право `lists.manage`; наборов списков («Читают», «Правят») у него нет.

    Строка права создаётся, если её ещё нет (например, после `clear_seed()`); кэш прав сотрудника сбрасывается сразу
    (сигнал ядра сбрасывает его только после фиксации)."""
    from django.core.cache import cache

    from apps.core.services import permissions

    Permission = support.model("core.Permission")
    for code in PERMISSIONS_006:
        Permission.objects.get_or_create(code=code, defaults={"title": TITLES_006[code]})
    role = factories.make_role(permissions=PERMISSIONS_006)
    user = _employee_with_role(role, **extra)
    cache.delete(permissions._key(user.pk))
    return Session(user, support.logged_in(user))


def grant_list(lst, who, level: str):
    """Строка `Access`: `who` — `core.Role` (поле `role`) или `org.Unit` (поле `unit_id`, без внешнего ключа);
    `level` — `"read"` или `"edit"`."""
    if level not in _LEVELS:
        raise ValueError(f"level: read или edit, получено {level!r}")
    label = who._meta.label_lower
    Access = support.model("lists.Access")
    if label == "core.role":
        return Access.objects.create(list=lst, level=level, role=who)
    if label == "org.unit":
        return Access.objects.create(list=lst, level=level, unit_id=who.pk)
    raise TypeError(f"who: core.Role или org.Unit, получено {label}")


# --- фабрики: список, поля, значения списка (раздел 2.2) -------------------------------------------------

def make_list(name: str | None = None, *, description: str = "", code: str = "", created_by=None):
    """Список прямой записью; имя по умолчанию — «Список <n>» с уникальным n; счётчики `next_number` и
    `next_field_no` — 1. Время — `timezone.now()` (с фикстурой `clock` — часы теста)."""
    now = timezone.now()
    return support.model("lists.List").objects.create(
        name=name or f"Список {next(_list_counter)}", description=description, code=code, created_by=created_by,
        next_number=1, next_field_no=1, created_at=now, updated_at=now)


def add_field(lst, type, name: str | None = None, *, required: bool = False, multiple: bool = False,
              unique: bool = False, show_in_table: bool = False, hidden: bool = False, default=None, hint: str = "",
              currency: str | None = None, target=None, deadline: bool = False, thresholds=(), choices=(),
              code: str | None = None):
    """Поле прямой записью, без проверок службы (чужое свойство помощник не отклоняет).

    `code` по умолчанию — `f<next_field_no>`, счётчик списка растёт (у переданного объекта тоже); с явным `code`
    счётчик не трогается. `order` — последний по всем полям списка (со скрытыми) плюс один. `choices` — названия
    значений, `Choice.order` с 1. `settings` собирается только из заданных свойств (выбор помощника: контракт называет
    ключи, но не форму пустого): у `money` — `{"currency": currency or "RUB"}`; у срока — `"deadline": True` и
    `"thresholds": [...]`, если пороги заданы; у прочих полей — `{}`. Имя по умолчанию — «Поле <код>»."""
    Field = support.model("lists.Field")
    type = str(getattr(type, "value", type))
    if code is None:
        lst.refresh_from_db(fields=["next_field_no"])
        code = f"f{lst.next_field_no}"
        lst.next_field_no += 1
        lst.save(update_fields=["next_field_no"])
    last = Field.objects.filter(list=lst).order_by("-order").values_list("order", flat=True).first()
    settings: dict = {}
    if type == "money" or currency is not None:
        settings["currency"] = currency or "RUB"
    if deadline:
        settings["deadline"] = True
    if thresholds:
        settings["thresholds"] = [int(days) for days in thresholds]
    field = Field.objects.create(
        list=lst, code=code, name=name or f"Поле {code}", hint=hint, type=type, required=required,
        multiple=multiple, unique=unique, show_in_table=show_in_table, hidden=hidden, default=default,
        order=(last or 0) + 1, target=target, settings=settings)
    Choice = support.model("lists.Choice")
    for order, title in enumerate(choices, start=1):
        Choice.objects.create(field=field, title=title, order=order, archived=False)
    return field


def choice_id(field, title: str) -> int:
    """id значения списка значений по названию (в том числе в архиве значений)."""
    return support.model("lists.Choice").objects.get(field=field, title=title).pk


# --- фабрики: записи, архив, файлы (разделы 2.2, 2.3) ---------------------------------------------------

def _canonical_number(value) -> str:
    """Каноническая десятичная строка раздела 2.3: «12.50» → «12.5», «100.0» → «100», «-3» → «-3»."""
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"не число: {value!r}") from None
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _norm_unique(field_type: str, value) -> str | None:
    """Нормализация `UniqueValue` (раздел 2.3): строка — `strip().lower()`, число — каноническая строка."""
    if value is None or value == "":
        return None
    if field_type == "string":
        return str(value).strip().lower()
    if field_type == "number":
        return _canonical_number(value)
    return None


def set_vectors(record) -> None:
    """Вектор записи своим SQL помощника: `title` с весом A и значения видимых полей «строка» и «многострочный
    текст» (по `order`, через пробел, первые 100 000 знаков) с весом C; конфигурация `russian` (план, «Поиск»).
    Строку собирает Python, в литерал SQL она уходит параметром (инвариант «sql-только-параметры»)."""
    Record = support.model("lists.Record")
    Field = support.model("lists.Field")
    assert Record._meta.db_table == "lists_record"
    codes = Field.objects.filter(list_id=record.list_id, hidden=False, type__in=("string", "text")).order_by(
        "order").values_list("code", flat=True)
    body = " ".join(str(record.values[code]) for code in codes if record.values.get(code) not in (None, ""))
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lists_record SET search = setweight(to_tsvector('russian', %s), 'A') || "
            "setweight(to_tsvector('russian', %s), 'C') WHERE id = %s",
            [record.title, body[:100000], record.pk])
    record.refresh_from_db(fields=["search"])


def make_record(lst, title: str = "Запись", values=None, *, archived: bool = False, created_by=None, updated_by=None,
                version: int = 1):
    """Запись прямой записью: номер из `next_number` (счётчик растёт, у переданного объекта тоже), `values` как есть
    (форма хранения раздела 2.3). Строки `UniqueValue` — у уникальных полей списка (видимых и скрытых) своей
    нормализацией помощника; вектор — `set_vectors(record)`. Автор по умолчанию — `lst.created_by` или новый
    сотрудник; `updated_by` по умолчанию — автор. `archived=True` — через `archive(record)`."""
    Record = support.model("lists.Record")
    lst.refresh_from_db(fields=["next_number"])
    number = lst.next_number
    lst.next_number += 1
    lst.save(update_fields=["next_number"])
    author = created_by or lst.created_by or support.make_employee()
    now = timezone.now()
    record = Record.objects.create(
        list=lst, number=number, title=title, values=dict(values or {}), archived=False, version=version,
        created_at=now, created_by=author, updated_at=now, updated_by=updated_by or author)
    UniqueValue = support.model("lists.UniqueValue")
    for field in support.model("lists.Field").objects.filter(list=lst, unique=True):
        norm = _norm_unique(field.type, record.values.get(field.code))
        if norm is not None:
            UniqueValue.objects.create(list=lst, field=field, norm_value=norm, record=record)
    set_vectors(record)
    if archived:
        archive(record)
    return record


def archive(record, *, by=None):
    """Перенос в архив прямой записью: `archived=True`, `archived_at=now`, `archived_by` — `by`, по умолчанию
    `record.updated_by` (без события истории и журнала)."""
    record.archived = True
    record.archived_at = timezone.now()
    record.archived_by = by if by is not None else record.updated_by
    record.save(update_fields=["archived", "archived_at", "archived_by"])
    return record


def attach_file(record, field, name: str = "акт.pdf", data: bytes | None = None, *, status: str = "clean",
                uploaded_by=None, write: bool = False):
    """Строки `StoredFile(purpose="lists", owner=None)` и `RecordFile`.

    `status` — `"pending"` («проверяется»), `"clean"` («чистый»), `"quarantine"` («карантин»); `scanned_at` — только
    у проверенного. С `write=True` байты пишутся на диск по `files.attachment_path` (`incoming/`, `attachments/`,
    `quarantine/` под `PROTECTED_ROOT`; нужна фикстура `protected_root`). ClamAV подменяют `scan_clean`,
    `scan_found`, `scan_unavailable`."""
    if status not in _FILE_STATUSES:
        raise ValueError(f"status: pending, clean или quarantine, получено {status!r}")
    if data is None:
        data = b"%PDF-1.4\n% test body\n"
    now = timezone.now()
    stored = support.model("core.StoredFile").objects.create(
        purpose="lists", owner=None, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream", status=status,
        scanned_at=now if status != "pending" else None)
    if write:
        from apps.core.services import files

        path = files.attachment_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return support.model("lists.RecordFile").objects.create(
        record=record, field=field, file=stored, name=name, uploaded_by=uploaded_by or record.created_by,
        uploaded_at=now)


# --- выключение модулей (раздел 3.4, решение 21 задач) ----------------------------------------------------

@contextlib.contextmanager
def without_lists():
    """«Без `lists`»: из всех точек реестра на время блока снимаются функции, у которых `__module__` начинается
    с `apps.lists`; прочие регистрации остаются; `INSTALLED_APPS` не перезагружается."""
    from apps.core import extensions

    saved = {point: list(funcs) for point, funcs in extensions._registry.items()}
    for point, funcs in extensions._registry.items():
        funcs[:] = [f for f in funcs if not getattr(f, "__module__", "").startswith("apps.lists")]
    try:
        yield
    finally:
        for point, funcs in saved.items():
            extensions._registry[point][:] = funcs


def without_app(monkeypatch, name: str) -> None:
    """«Без `servicedesk`/`notify`/`org`»: `django.apps.apps.is_installed(name)` ложен, для прочих — как был.
    Подмена снимается вместе с `monkeypatch`."""
    from django.apps import apps as registry

    if name not in _ALLOWED_OFF:
        raise ValueError(f"name: одно из {_ALLOWED_OFF}, получено {name!r}")
    real = registry.is_installed

    def is_installed(app_name: str) -> bool:
        return False if app_name == name else real(app_name)

    monkeypatch.setattr(registry, "is_installed", is_installed)


# --- миграция данных lists 0002 (раздел 2.4; решения 20 и 35 задач) ----------------------------------------

def _alias(using: str | None) -> str:
    if using is None:
        return "migrate" if "migrate" in connections.databases else "default"
    return using


def _seed_module():
    return importlib.import_module("apps.lists.migrations.0002_initial_data")


def run_seed(using: str | None = None) -> None:
    """`seed(django.apps.apps, SimpleNamespace(connection=…))` миграции `lists 0002`; `using` по умолчанию —
    `migrate`, если он настроен, иначе `default` (как `support_kb.run_seed`)."""
    from django.apps import apps

    _seed_module().seed(apps, SimpleNamespace(connection=connections[_alias(using)]))


def run_unseed(using: str | None = None) -> None:
    """`unseed(django.apps.apps, SimpleNamespace(connection=…))` миграции `lists 0002`."""
    from django.apps import apps

    _seed_module().unseed(apps, SimpleNamespace(connection=connections[_alias(using)]))


def clear_seed() -> None:
    """Снимает стартовые данные перед «первым вызовом» `run_seed()` и тестом пустой главной (решение 35 задач):
    строки `Access` всех стартовых списков; стартовые списки без записей (в том числе в архиве) — по кодам;
    право `lists.manage` с его выдачей ролям.

    `Field.target` — RESTRICT (`licenses`, `consumables`, `sims` ссылаются на `equipment`), поэтому стартовый список
    без записей, на который ссылается поле оставшегося списка, тоже остаётся — без ошибки. Поля удаляемых списков
    стираются раньше самих списков. Соединение — `default`."""
    from django.core.cache import cache

    from apps.core.services import permissions

    List, Field = support.model("lists.List"), support.model("lists.Field")
    Record = support.model("lists.Record")
    seeded = List.objects.filter(code__in=_SEED_CODES)
    support.model("lists.Access").objects.filter(list__in=seeded).delete()
    with_records = set(Record.objects.filter(list__in=seeded).values_list("list_id", flat=True))
    doomed = set(seeded.exclude(pk__in=with_records).values_list("pk", flat=True))
    while True:
        kept_targets = set(Field.objects.filter(target_id__in=doomed).exclude(list_id__in=doomed)
                           .values_list("target_id", flat=True))
        if not kept_targets:
            break
        doomed -= kept_targets
    Field.objects.filter(list_id__in=doomed).delete()
    List.objects.filter(pk__in=doomed).delete()
    Permission, User = support.model("core.Permission"), support.model("core.User")
    holders = list(User.objects.filter(roles__permissions__code__in=PERMISSIONS_006).values_list("pk", flat=True))
    Permission.objects.filter(code__in=PERMISSIONS_006).delete()
    for user_id in holders:
        cache.delete(permissions._key(user_id))


# --- обход сроков (раздел 5.6) и подмена «между выборкой и замком» (раздел 5.8, решение 45) ----------------

def run_reminders(today):
    """`apps.lists.services.reminders.run(today)` синхронно; возвращает `RunResult(notified, failed)`."""
    from apps.lists.services import reminders

    return reminders.run(today)


def act_between_select_and_lock(monkeypatch, action: Callable[[list], None]) -> list:
    """Оборачивает `reminders.select_candidates`: после настоящей выборки зовёт `action(кандидаты)` и возвращает
    выборку как была. Возвращает список выданных выборок."""
    from apps.lists.services import reminders

    selections, real = [], reminders.select_candidates

    def wrapper(*args, **kwargs):
        candidates = real(*args, **kwargs)
        selections.append(list(candidates))
        action(candidates)
        return candidates

    monkeypatch.setattr(reminders, "select_candidates", wrapper)
    return selections


# --- замок списка по SQL (раздел 5.2, И1) ------------------------------------------------------------------

class ListLock(NamedTuple):
    """Вызов замка списка: `kind` — `"shared"` (`pg_advisory_xact_lock_shared`) или `"exclusive"`
    (`pg_advisory_xact_lock`), `list_no` — второе число ключа (`list_id % 2147483648`)."""
    kind: str
    list_no: int


_LIST_LOCK_RE = re.compile(
    r"pg_advisory_xact_lock(_shared)?\s*\(\s*hashtext\s*\(\s*'lists\.list'\s*\)\s*,\s*'?(-?\d+)'?(?:\s*::\s*\w+)?\s*\)",
    re.I)


def list_no(list_id: int) -> int:
    """Второе число ключа замка списка (И1): остаток `list_id % 2147483648` (3 000 000 000 → 852516352)."""
    return int(list_id) % 2147483648


def list_locks(sqls) -> list[ListLock]:
    """Вызовы `pg_advisory_xact_lock[_shared](hashtext('lists.list'), N)` в порядке выполнения.

    Число берётся из подставленного текста запроса (`CaptureQueriesContext` показывает параметры подставленными)."""
    found = []
    for sql in sqls:
        for match in _LIST_LOCK_RE.finditer(sql):
            found.append(ListLock("shared" if match.group(1) else "exclusive", int(match.group(2))))
    return found


# --- таблицы загрузки и выгрузки в памяти (разделы 5.7, 5.9) -----------------------------------------------

def xlsx_of(header, rows, *, sheet_title: str = "Лист1") -> bytes:
    """Книга XLSX (`openpyxl`): первая строка — `header`, дальше — `rows`."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = sheet_title
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def csv_of(header, rows, *, delimiter: str = ";") -> bytes:
    """CSV в UTF-8 без BOM: первая строка — `header`, дальше — `rows`."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=delimiter)
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
    return out.getvalue().encode("utf-8")


def read_xlsx(content: bytes) -> list[list]:
    """Значения первого листа книги (`openpyxl.load_workbook`), строка за строкой."""
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(content))
    sheet = book.worksheets[0]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def read_back(content: bytes):
    """То же через `core.table_file.read` с пределами плана (5 МБ, 5 000 строк, 100 частей, 50 МБ распакованного);
    возвращает `TableFile(file_format, header, rows)`. Пустые ячейки в конце строки `read` отбрасывает (факт T-6005)."""
    from apps.core.services import table_file

    return table_file.read(content, texts=_IMPORT_TEXTS, **_IMPORT_LIMITS)


# --- страницы среза для проверок «по-русски» и «без style=» (раздел 1.1) -------------------------------------

def list_pages(lst, record) -> tuple[str, ...]:
    """Адреса страниц среза для списка `lst` и его записи `record`."""
    base, card = f"/lists/{lst.pk}/", f"/lists/{lst.pk}/{record.number}/"
    return (
        "/lists/", base, base + "settings/", base + "settings/fields/", base + "settings/access/", base + "add/",
        card, card + "edit/", card + "history/", base + "import/", card + "label/", base + f"labels/?n={record.number}",
    )
