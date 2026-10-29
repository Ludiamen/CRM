"""T-6310: скорость подтверждения загрузки (решение 63 задач, FR-534). Первый замер T-6304: подтверждение 5 000 строк
шло ~97 с (около 14 запросов на строку: права, поля, замок и `FOR UPDATE` списка на каждую строку), по HTTP — 504, а
строка списка всё это время заблокирована. Тесты задают границы, а не время: прирост запросов на строку, один замок и
одна блокировка строки списка на подтверждение, точки сохранения порциями с повтором по одной строке.

Задания собираются службами `imports.upload` и `imports.preview` (CONTRACT-006, 5.7), подтверждение — `imports.confirm`;
SQL — `sql_of` (5.9), замки — `list_locks` (5.2). Порция — 250 строк (T-6312). Код среза на уровне модуля не
импортируется.
"""
import importlib

import pytest

from tests import support
from tests import support_lists as ls

pytestmark = pytest.mark.django_db

HEADER = ["Название", "Серийный номер", "Кабинет"]
PER_ROW_LIMIT = 4
CHUNK = 250


def _imports():
    return importlib.import_module("apps.lists.services.imports")


def _world():
    """Список с уникальной строкой «Серийный номер» и строкой «Кабинет»; правящий сотрудник."""
    lst = ls.make_list()
    uniq = ls.add_field(lst, "string", "Серийный номер", unique=True)
    room = ls.add_field(lst, "string", "Кабинет")
    return lst, uniq, room, ls.as_editor(lst)


def _job(lst, actor, rows, uniq, room):
    imp = _imports()
    job = imp.upload(lst, actor, name="перечень.xlsx", content=ls.xlsx_of(HEADER, rows))
    return imp.preview(job, {"0": "title", "1": uniq.code, "2": room.code}, actor)


def _rows(prefix: str, count: int, room: str = "101") -> list[list[str]]:
    return [[f"{prefix} {n}", f"{prefix}-{n:05d}", room] for n in range(count)]


def _records(lst):
    return support.model("lists.Record").objects.filter(list=lst)


def _confirm_sqls(lst, job, actor) -> list[str]:
    return ls.sql_of(_imports().confirm, lst, job.pk, actor)


def _per_row(small: list[str], large: list[str], rows: int) -> float:
    return (len(large) - len(small)) / rows


def _savepoints(sqls) -> int:
    return sum(1 for sql in sqls if sql.lstrip().upper().startswith("SAVEPOINT"))


def test_confirm_queries_per_row_bounded():
    """FR-534, решение 63: прирост запросов подтверждения на строку — не больше 4 и при создании записей, и при
    обновлении по уникальному полю (100 и 200 строк в разных списках; разность делится на 100 строк). На коде db956a2
    прирост ~14: права, поля, замок и `FOR UPDATE` списка заново на каждую строку."""
    measured = {}
    for size in (100, 200):
        lst, uniq, room, author = _world()
        created = _confirm_sqls(lst, _job(lst, author.user, _rows("Узел", size), uniq, room), author.user)
        assert _records(lst).count() == size
        updated = _confirm_sqls(lst, _job(lst, author.user, _rows("Узел", size, room="202"), uniq, room), author.user)
        assert _records(lst).count() == size
        assert set(_records(lst).values_list(f"values__{room.code}", flat=True)) == {"202"}
        measured[size] = (created, updated)
    create_rate = _per_row(measured[100][0], measured[200][0], 100)
    update_rate = _per_row(measured[100][1], measured[200][1], 100)
    assert create_rate <= PER_ROW_LIMIT, f"создание: {create_rate:.1f} запроса на строку"
    assert update_rate <= PER_ROW_LIMIT, f"обновление: {update_rate:.1f} запроса на строку"


def test_confirm_locks_list_once():
    """FR-534, решение 63, CONTRACT-006 5.2: на всё подтверждение 30 строк — один разделяемый замок списка и один
    `SELECT … FOR UPDATE` строки списка; порядок «замок → задание → строка списка» прежний (его проверяет
    `test_lists_imports_2.py`)."""
    lst, uniq, room, author = _world()
    job = _job(lst, author.user, _rows("Узел", 30), uniq, room)

    sqls = _confirm_sqls(lst, job, author.user)

    assert ls.list_locks(sqls) == [ls.ListLock("shared", ls.list_no(lst.pk))], ls.list_locks(sqls)
    list_rows = [sql for sql in sqls if sql.lstrip().upper().startswith("SELECT") and "FOR UPDATE" in sql.upper()
                 and 'FROM "LISTS_LIST"' in sql.upper()]
    assert len(list_rows) == 1, f"FOR UPDATE строки списка: {len(list_rows)}"
    assert _records(lst).count() == 30


def test_confirm_chunk_with_failing_row_loads_the_rest(monkeypatch):
    """FR-534, решение 63: 600 строк; строка в середине первой порции падает на ограничении уникальности при записи
    (предварительная проверка обойдена подменой `unique.find_owners`, как в `test_lists_imports_2.py`). Итог — ошибка
    этой строки, остальные 599 загружены; номера без пропусков (владелец значения — №1, загруженные — №2…600),
    история «создана загрузкой» у 599; точек сохранения не больше числа порций плюс строк одной повторённой порции и
    одной точки самого подтверждения (тест идёт внутри транзакции, поэтому `atomic` подтверждения — тоже точка
    сохранения) — на коде db956a2 по нескольку точек на строку (1 797)."""
    lst, uniq, room, author = _world()
    rows = _rows("Узел", 600)
    job = _job(lst, author.user, rows, uniq, room)
    assert _imports().counts(job)["will_create"] == 600
    owner = ls.make_record(lst, "Владелец", {uniq.code: rows[100][1]}, created_by=author.user)
    assert owner.number == 1
    monkeypatch.setattr("apps.lists.services.unique.find_owners", lambda *args, **kwargs: {})

    with ls.capture_sql() as sqls:
        result = _imports().confirm(lst, job.pk, author.user)

    assert result == {"created": 599, "updated": 0, "errors": 1}
    assert sorted(_records(lst).values_list("number", flat=True)) == list(range(1, 601))
    lst.refresh_from_db()
    assert lst.next_number == 601
    assert not _records(lst).filter(title=rows[100][0]).exists()
    changes = support.model("lists.Change").objects.filter(record__list=lst, kind="created", via_import=True)
    assert changes.count() == 599
    values = support.model("lists.UniqueValue").objects.filter(field=uniq)
    assert values.count() == 600 and values.filter(record=owner).count() == 1
    chunks = -(-600 // CHUNK)
    assert _savepoints(sqls) <= chunks + CHUNK + 1, f"точек сохранения {_savepoints(sqls)}"
