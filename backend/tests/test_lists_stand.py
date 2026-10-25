"""T-6124: сброс стенда `lists` и команда сдвига сроков `e2e_lists_shift` (FR-505, FR-530, FR-545). Сценарии «Данные
установки», «Сроки и напоминания» (команда стенда) спеки 006.

Контракт: CONTRACT-006 — 1.3 (сброс стенда), 2.4 (миграция данных, стартовые списки), 13.1 (команда стенда), решение
Opus при проверке контракта о подмене только названными точками. Сброс проверяется прямым вызовом
`apps.lists.stand.stand_reset()` (команда `e2e_reset_stand` здесь не запускается: она чистит все таблицы ядра); данные
сброса создаются и читаются через соединение `migrate`, как в `test_kb_deploy.py`. Тестовая база уже содержит шесть
стартовых списков (их создала миграция `lists 0002`, строки зафиксированы), поэтому «начальное состояние» берётся счётом
строк до теста. Команда сдвига работает на соединении `default`; даты и пороги проверены скриптом:
2026-03-10 → 2026-04-20 — 41 день, → 2026-04-05 — 26 дней.
"""
import contextlib
import re
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import support, support_lists as sl
from tests.support_kb import moscow

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
SHIFT_LINE = re.compile(r"lists_shift: days=(\d+) shifted=(\d+) notified=(\d+)\n")

# стартовые списки по контракту 2.4: код → (название, коды полей по порядку)
SEED_LISTS = {
    "equipment": ("Оборудование", ["kind", "inventory_number", "serial_number", "model", "state", "assignee", "unit",
                                   "place", "purchased", "warranty", "cost", "note", "files"]),
    "licenses": ("Лицензии", ["product", "kind", "seats", "license_number", "valid_until", "installed_on", "owner",
                              "cost", "files"]),
    "consumables": ("Картриджи и расходники", ["kind", "model", "printers", "stock", "note"]),
    "signatures": ("Сертификаты ЭП", ["holder", "issuer", "serial_number", "medium", "valid_until", "files"]),
    "contracts": ("Договоры", ["counterparty", "contract_number", "subject", "signed", "valid_until", "amount",
                               "owner", "files"]),
    "sims": ("SIM-карты и телефоны", ["phone", "operator", "tariff", "assignee", "device", "iccid", "note"]),
}


# --- помощники (свои: общие файлы тестов не правятся) -----------------------------------------------------------------

def _on(model_name: str):
    return support.model(model_name).objects.using("migrate")


def _owner():
    """Сотрудник, созданный через `migrate` (на `default` строка не видна: у соединений разные транзакции)."""
    from tests import factories

    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name="Автор Списков", state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _stored(purpose: str, status: str, data: bytes, *, write: bool = True):
    """`StoredFile` через `migrate` и путь его файла на диске (`incoming/`, `attachments/`, `quarantine/`)."""
    from apps.core.services import files as core_files

    stored = _on("core.StoredFile").create(
        purpose=purpose, owner=None, size=len(data), sha256="0" * 64, content_type="application/octet-stream",
        status=status, scanned_at=timezone.now() if status != "pending" else None)
    path = core_files.attachment_path(stored)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return stored, path


@contextlib.contextmanager
def _commit_callbacks(capture):
    """После фиксации: исполняет `on_commit` обоих соединений (какое из них выберет код, контракт не называет)."""
    with capture(using="default", execute=True) as on_default, capture(using="migrate", execute=True) as on_migrate:
        yield on_default, on_migrate


def _list_on_migrate(name: str, **extra):
    now = timezone.now()
    return _on("lists.List").create(name=name, description="", code="", created_by=None, next_number=1,
                                    next_field_no=1, created_at=now, updated_at=now, **extra)


def _field_on_migrate(lst, code: str, type: str, *, order: int = 1, target=None, unique: bool = False,
                      settings=None):
    return _on("lists.Field").create(
        list=lst, code=code, name=f"Поле {code}", hint="", type=type, required=False, multiple=False, unique=unique,
        show_in_table=False, hidden=False, default=None, order=order, target=target, settings=settings or {})


def _record_on_migrate(lst, author, number: int, title: str = "Запись", values=None):
    now = timezone.now()
    return _on("lists.Record").create(
        list=lst, number=number, title=title, values=dict(values or {}), archived=False, version=1, created_at=now,
        created_by=author, updated_at=now, updated_by=author)


def _counts(*names: str) -> dict[str, int]:
    return {name: _on(f"lists.{name}").count() for name in names}


def _everything_on_migrate(author):
    """По одной строке во всех таблицах среза через `migrate` (кроме `RecordFile`): список со ссылкой на другой список,
    поля с уникальностью и значениями, записи, значения уникальности, история, права, выбор столбцов, связь с заявкой,
    отметка напоминания, задание загрузки; а также права и запись в стартовом списке `equipment`. Возвращает словарь."""
    now = timezone.now()
    role = _on("core.Role").create(name=f"роль-{now.timestamp()}", is_builtin=False)
    target = _list_on_migrate("Целевой список стенда")
    main = _list_on_migrate("Список стенда", description="Описание")
    title_target = _field_on_migrate(target, "f1", "string", order=1)
    ref = _field_on_migrate(main, "f1", "record", order=1, target=target)
    unique_field = _field_on_migrate(main, "f2", "string", order=2, unique=True)
    deadline = _field_on_migrate(main, "f3", "date", order=3, settings={"deadline": True, "thresholds": [7]})
    choice_field = _field_on_migrate(main, "f4", "choice", order=4)
    choice = _on("lists.Choice").create(field=choice_field, title="Значение", order=1, archived=False)
    # поле записи стартового списка, ссылающееся на `equipment` (RESTRICT)
    equipment = _on("lists.List").get(code="equipment")
    seed_ref = _field_on_migrate(main, "f5", "record", order=5, target=equipment)
    target_record = _record_on_migrate(target, author, 1, "Целевая запись", {"f1": "x"})
    record = _record_on_migrate(main, author, 1, "Запись стенда",
                                {"f1": [target_record.pk], "f2": "Один", "f3": "2026-06-10"})
    equipment_record = _record_on_migrate(equipment, author, 1, "Запись оборудования")
    unique = _on("lists.UniqueValue").create(list=main, field=unique_field, norm_value="один", record=record)
    change = _on("lists.Change").create(record=record, at=now, actor=author, kind="created", changes=[],
                                        via_import=False)
    access = _on("lists.Access").create(list=main, level="read", role=role)
    seed_access = _on("lists.Access").create(list=equipment, level="edit", role=role)
    view = _on("lists.UserView").create(user=author, list=main, columns=["title", "f2"])
    link = _on("lists.TicketLink").create(record=record, ticket_number=7, linked_by=author, linked_at=now)
    reminder = _on("lists.ReminderSent").create(record=record, field=deadline, threshold_days=7,
                                                due_date=date(2026, 6, 10), notified=True, created_at=now)
    job = _on("lists.ImportJob").create(
        list=main, created_by=author, created_at=now, file_name="a.csv", file_format="csv", state="preview",
        header=["a"], mapping={"0": "f2"}, rows=[], summary={})
    return {"role": role, "target": target, "main": main, "equipment_record": equipment_record,
            "rows": {"Choice": [choice], "UniqueValue": [unique], "Change": [change], "Access": [access, seed_access],
                     "UserView": [view], "TicketLink": [link], "ReminderSent": [reminder], "ImportJob": [job],
                     "Record": [record, target_record, equipment_record],
                     "Field": [title_target, ref, unique_field, deadline, choice_field, seed_ref],
                     "List": [target, main]}}


# --- сброс стенда (прямой вызов функции точки, контракт 1.3) --------------------------------------------------------------

@MIGRATE
def test_lists_stand_reset_runs_in_transaction_under_migrate_alias(django_capture_on_commit_callbacks):
    """FR-545: весь сброс (стирание и `seed`) идёт под алиасом `migrate` внутри одной `transaction.atomic`: в SQL
    соединения `migrate` стоит `SAVEPOINT` (вложенная в тестовую транзакцию `atomic`) раньше первого `DELETE` и
    `RELEASE SAVEPOINT` позже последнего `INSERT`, откатов нет; на соединении `default` нет ни одного запроса к
    таблицам `lists_*` (раздел 1.3)."""
    from apps.lists.stand import stand_reset

    _everything_on_migrate(_owner())
    with CaptureQueriesContext(connections["migrate"]) as migrate_log, \
            CaptureQueriesContext(connections["default"]) as default_log:
        with _commit_callbacks(django_capture_on_commit_callbacks):
            stand_reset()
    sqls = [q["sql"] for q in migrate_log.captured_queries]
    deletes = [i for i, sql in enumerate(sqls) if sql.startswith('DELETE FROM "lists_')]
    inserts = [i for i, sql in enumerate(sqls) if sql.startswith('INSERT INTO "lists_list"')]
    assert deletes, "сброс ничего не стёр на соединении migrate"
    assert inserts, "seed не создал стартовые списки на соединении migrate"
    opened = [i for i, sql in enumerate(sqls) if sql.startswith("SAVEPOINT")]
    released = [i for i, sql in enumerate(sqls) if sql.startswith("RELEASE SAVEPOINT")]
    assert opened and released, "стирание и seed не завёрнуты в transaction.atomic(using=migrate)"
    assert opened[0] < deletes[0], "первое стирание раньше входа в транзакцию"
    assert released[-1] > max(inserts), "seed выполнен после выхода из транзакции"
    assert not [sql for sql in sqls if sql.startswith("ROLLBACK")], "сброс откатывался"
    on_default = [q["sql"] for q in default_log.captured_queries if "lists_" in q["sql"]]
    assert not on_default, f"запросы к таблицам lists на соединении default: {on_default[:2]}"


@MIGRATE
def test_lists_stand_reset_wipes_record_files_rows_stored_files_and_disk_after_commit(
        protected_root, django_capture_on_commit_callbacks):
    """FR-545: файлы записей во всех состояниях (`pending` — `incoming/`, `clean` — `attachments/`, `quarantine` —
    `quarantine/`, а также без файла на диске) стираются: строки `RecordFile` и их `StoredFile` — сразу, файл на диске —
    только после фиксации (`on_commit`): пока обратные вызовы не исполнены, файл на месте (раздел 1.3)."""
    from apps.lists.stand import stand_reset

    author = _owner()
    lst = _list_on_migrate("Список с файлами")
    files_field = _field_on_migrate(lst, "f1", "file")
    record = _record_on_migrate(lst, author, 1)
    made = []
    for status, name, write in (("pending", "a.txt", True), ("clean", "b.txt", True), ("quarantine", "c.txt", True),
                                ("clean", "d.txt", False)):
        stored, path = _stored("lists", status, name.encode(), write=write)
        _on("lists.RecordFile").create(record=record, field=files_field, file=stored, name=name,
                                       uploaded_by=author, uploaded_at=timezone.now())
        made.append((stored, path, write))
    assert [path.exists() for _, path, _ in made] == [True, True, True, False]

    with _commit_callbacks(django_capture_on_commit_callbacks) as (on_default, on_migrate):
        stand_reset()
        for stored, path, write in made:
            assert not _on("core.StoredFile").filter(pk=stored.pk).exists(), "StoredFile записи остался"
            assert path.exists() == write, "файл на диске тронут до фиксации"
        assert on_default or on_migrate, "стирание файлов с диска не поставлено в on_commit"

    assert _on("lists.RecordFile").count() == 0
    for stored, path, _ in made:
        assert not path.exists(), f"файл записи остался на диске: {path.parent.name}"


@MIGRATE
def test_lists_stand_reset_wipes_links_reminders_history_unique_values_records_views_imports_access_choices_fields_lists(
        django_capture_on_commit_callbacks):
    """FR-545: стираются связи с заявками, отметки напоминаний, история, значения уникальности, записи (в том числе в
    стартовом списке), выбор столбцов, задания загрузки, права (в том числе на стартовом списке), значения, поля (в
    том числе с RESTRICT-ссылкой на стартовый список) и созданные вручную списки; остаются ровно стартовые
    (счёт строк `List`, `Field`, `Choice`, `Access` такой же, как до теста); сотрудники не стираются (раздел 1.3)."""
    from apps.lists.stand import stand_reset

    author = _owner()
    baseline = _counts("List", "Field", "Choice", "Access")
    data = _everything_on_migrate(author)
    assert _counts("List")["List"] == baseline["List"] + 2

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    for name in ("TicketLink", "ReminderSent", "Change", "UniqueValue", "Record", "UserView", "ImportJob",
                 "RecordFile"):
        assert _counts(name)[name] == 0, f"после сброса остались строки {name}"
    for name, rows in data["rows"].items():
        assert not _on(f"lists.{name}").filter(pk__in=[row.pk for row in rows]).exists(), f"{name}: строка осталась"
    assert _counts("List", "Field", "Choice", "Access") == baseline, "после сброса не только стартовые данные"
    assert not _on("lists.List").filter(code="").exists(), "остался список, созданный вручную"
    assert _on("core.User").filter(pk=author.pk).exists(), "сотрудник стёрт"
    assert _on("core.Role").filter(pk=data["role"].pk).exists(), "роль стёрта (её стирает команда e2e_reset_stand)"


@MIGRATE
def test_lists_stand_reset_then_seeds_six_starting_lists_with_fields_permission_and_access(
        django_capture_on_commit_callbacks):
    """FR-545, FR-505: если стартовых данных нет (снесены через `migrate`: списки, поля, право и его выдача), после
    `stand_reset()` есть шесть стартовых списков с названиями и полями контракта 2.4, право `lists.manage`
    («Управление списками») у «Администратора портала» и только у него, строки `Access` «читают» и «правят» роли
    «Сотрудник ИТ» на каждом списке; обработчик `m2m_changed` прав ядра снова подключён (раздел 1.3)."""
    from django.db.models.signals import m2m_changed

    from apps.lists.stand import stand_reset

    _on("lists.Access").all().delete()
    _on("lists.Field").all().delete()
    _on("lists.List").all().delete()
    _on("core.Permission").filter(code="lists.manage").delete()
    assert _counts("List", "Field", "Access") == {"List": 0, "Field": 0, "Access": 0}

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    lists = {row.code: row for row in _on("lists.List").all()}
    assert sorted(lists) == sorted(SEED_LISTS), "стартовых списков не шесть или коды другие"
    for code, (title, field_codes) in SEED_LISTS.items():
        assert lists[code].name == title, code
        assert list(_on("lists.Field").filter(list=lists[code]).order_by("order").values_list("code", flat=True)) \
            == field_codes, f"поля списка {code}"
    permission = _on("core.Permission").get(code="lists.manage")
    assert permission.title == "Управление списками"

    def holds(role_name: str) -> bool:
        role = _on("core.Role").get(name=role_name, is_builtin=True)
        return role.permissions.using("migrate").filter(code="lists.manage").exists()

    assert holds(support.ADMIN_ROLE) and not holds(support.STAFF_ROLE) and not holds(support.MANAGER_ROLE)
    staff = _on("core.Role").get(name=support.STAFF_ROLE, is_builtin=True)
    rows = sorted(_on("lists.Access").filter(role=staff).values_list("list__code", "level"))
    assert rows == sorted((code, level) for code in SEED_LISTS for level in ("read", "edit")), \
        "права «Сотрудника ИТ» на стартовые списки"
    assert _counts("Access")["Access"] == 12, "лишние строки Access"
    assert m2m_changed.has_listeners(sender=support.model("core.Role").permissions.through), \
        "обработчик m2m_changed прав ядра не подключён обратно"


@MIGRATE
def test_lists_stand_reset_returns_deleted_and_renamed_starting_list(django_capture_on_commit_callbacks):
    """FR-545, FR-505: удалённый стартовый список (`sims`) возвращается ровно один раз, переименованный (`equipment`)
    и его переименованное и удалённое поле — с прежними названиями и полями (стирание идёт до `seed`, поэтому
    правки администратора не переживают сброс; раздел 1.3)."""
    from apps.lists.stand import stand_reset

    sims = _on("lists.List").get(code="sims")
    _on("lists.Access").filter(list=sims).delete()
    _on("lists.Field").filter(list=sims).delete()
    sims.delete()
    equipment = _on("lists.List").get(code="equipment")
    _on("lists.List").filter(pk=equipment.pk).update(name="Моё оборудование", description="Правка")
    _on("lists.Field").filter(list=equipment, code="kind").update(name="Тип")
    _on("lists.Field").filter(list=equipment, code="place").delete()
    assert not _on("lists.List").filter(code="sims").exists()

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    for code, (title, field_codes) in SEED_LISTS.items():
        rows = list(_on("lists.List").filter(code=code))
        assert len(rows) == 1, f"список {code}: строк {len(rows)}"
        assert rows[0].name == title, f"{code}: название после сброса"
        assert list(_on("lists.Field").filter(list=rows[0]).order_by("order").values_list("code", flat=True)) \
            == field_codes, f"поля списка {code}"
    restored = _on("lists.List").get(code="equipment")
    assert restored.description == ""
    assert _on("lists.Field").get(list=restored, code="kind").name == "Вид"
    assert _on("lists.Field").filter(list=restored, code="place").exists()
    assert _on("lists.List").get(code="sims").name == "SIM-карты и телефоны"
    staff = _on("core.Role").get(name=support.STAFF_ROLE, is_builtin=True)
    assert _on("lists.Access").filter(role=staff, list__code="sims").count() == 2


@MIGRATE
def test_lists_stand_reset_keeps_ticket_and_article_files(protected_root, django_capture_on_commit_callbacks):
    """FR-545: `stand_reset()` не трогает `StoredFile` вложений заявок (`purpose="attachment"`) и файлов статей
    (`purpose="knowledge"`) во всех состояниях и их файлы на диске, а файл записи (`purpose="lists"`) стирает
    (раздел 1.3)."""
    from apps.lists.stand import stand_reset

    author = _owner()
    lst = _list_on_migrate("Список с файлом")
    files_field = _field_on_migrate(lst, "f1", "file")
    record = _record_on_migrate(lst, author, 1)
    own, own_path = _stored("lists", "clean", b"list file")
    _on("lists.RecordFile").create(record=record, field=files_field, file=own, name="a.pdf", uploaded_by=author,
                                   uploaded_at=timezone.now())
    kept = [_stored(purpose, status, f"{purpose} {status}".encode())
            for purpose in ("attachment", "knowledge") for status in ("pending", "clean", "quarantine")]

    with _commit_callbacks(django_capture_on_commit_callbacks):
        stand_reset()

    assert not _on("core.StoredFile").filter(pk=own.pk).exists() and not own_path.exists()
    for stored, path in kept:
        assert _on("core.StoredFile").filter(pk=stored.pk).exists(), f"StoredFile {stored.purpose} стёрт"
        assert path.read_bytes() == f"{stored.purpose} {stored.status}".encode(), f"файл {stored.purpose} тронут"


def test_lists_stand_reset_is_registered_after_knowledge_and_runs_before_it():
    """FR-545: в точке `stand_reset` функция `apps.lists.stand.stand_reset` зарегистрирована последней, сразу после
    `apps.knowledge.stand.stand_reset`; команда зовёт функции в обратном порядке, поэтому `lists` стирается раньше
    `knowledge` (раздел 1.3)."""
    from apps.core import extensions
    from apps.lists.stand import stand_reset

    registered = list(extensions.registered("stand_reset"))
    names = [func.__module__ for func in registered]
    assert registered.count(stand_reset) == 1, "stand_reset модуля lists не зарегистрирован ровно один раз"
    assert registered[-1] is stand_reset, "stand_reset модуля lists не последний"
    assert names[-2] == "apps.knowledge.stand", f"перед lists стоит {names[-2]}, а не knowledge"
    call_order = [func.__module__ for func in reversed(registered)]
    assert call_order.index("apps.lists.stand") < call_order.index("apps.knowledge.stand")
    assert call_order[0] == "apps.lists.stand", "lists вызывается не первым"


@PLAIN
def test_lists_require_stand_refuses_without_e2e_stand_flag(monkeypatch, django_assert_num_queries):
    """FR-545: `require_stand()` без `E2E_STAND=1` (нет переменной, «0», пусто) бросает `CommandError(REFUSAL)` раньше
    любого запроса к базе; с `E2E_STAND=1` не бросает; `REFUSAL` — текст контракта (раздел 1.3)."""
    from apps.lists import stand

    assert stand.REFUSAL == REFUSAL
    monkeypatch.delenv("E2E_STAND", raising=False)
    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                stand.require_stand()
        assert str(refused.value) == REFUSAL, repr(value)
    monkeypatch.setenv("E2E_STAND", "1")
    assert stand.require_stand() is None


# --- команда стенда e2e_lists_shift (контракт 13.1) -------------------------------------------------------------------

def _run(*args) -> str:
    out = StringIO()
    call_command("e2e_lists_shift", *args, stdout=out)
    return out.getvalue()


def _values(record):
    return type(record).objects.get(pk=record.pk).values


def _shift_data():
    """Список со срочными полями (видимое `d1`, скрытое `d2`), обычной датой `bought` и строкой `serial`; записи:
    `both` (`d1`, `d2`, `bought`), `hidden_only` (только `d2`), `archived` (`d1`, в архиве), `empty` (без дат);
    запись другого списка без срочных полей; отметка напоминания записи `both` по `d1`."""
    lst = sl.make_list("Сдвиг")
    d1 = sl.add_field(lst, "date", "Срок один", deadline=True, thresholds=(30, 7), show_in_table=True)
    d2 = sl.add_field(lst, "date", "Срок два", deadline=True, hidden=True)
    bought = sl.add_field(lst, "date", "Куплено")
    serial = sl.add_field(lst, "string", "Серия")
    both = sl.make_record(lst, "Обе даты", {d1.code: "2026-04-20", d2.code: "2026-09-01", bought.code: "2026-05-05",
                                            serial.code: "С-1"})
    hidden_only = sl.make_record(lst, "Только скрытая", {d2.code: "2026-07-01"})
    archived = sl.make_record(lst, "В архиве", {d1.code: "2026-05-01"}, archived=True)
    empty = sl.make_record(lst, "Без дат", {serial.code: "С-2"})
    other = sl.make_list("Без сроков")
    note = sl.add_field(other, "date", "Просто дата")
    other_record = sl.make_record(other, "Другой список", {note.code: "2026-04-20"})
    return {"list": lst, "d1": d1, "d2": d2, "bought": bought, "serial": serial, "both": both,
            "hidden_only": hidden_only, "archived": archived, "empty": empty, "other_record": other_record,
            "note": note}


def _shifted(text: str, days: int) -> str:
    return (date.fromisoformat(text) - timedelta(days=days)).isoformat()


@PLAIN
def test_e2e_lists_shift_accepts_1_and_3650_days(monkeypatch, clock):
    """FR-530: `--days 1` и `--days 3650` принимаются: значения полей-сроков сдвигаются ровно на 1 и 3650 суток назад,
    вывод — одна строка с этими числами (раздел 13.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(moscow(2026, 1, 5, 12))
    data = _shift_data()
    d1, both = data["d1"].code, data["both"]
    assert _run("--days", "1") == "lists_shift: days=1 shifted=3 notified=0\n"
    assert _values(both)[d1] == "2026-04-19"
    assert _run("--days", "3650") == "lists_shift: days=3650 shifted=3 notified=0\n"
    assert _values(both)[d1] == _shifted("2026-04-20", 3651)


@PLAIN
def test_e2e_lists_shift_rejects_0_and_3651_days_with_command_error(monkeypatch, clock):
    """FR-530: `--days 0` и `--days 3651` — `CommandError("Число вне пределов от 1 до 3650: N")`, данные не
    меняются; без `--days` и с нечисловым значением — тоже `CommandError` (разбор аргументов; раздел 13.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(moscow(2026, 1, 5, 12))
    data = _shift_data()
    before = {name: _values(data[name]) for name in ("both", "hidden_only", "archived", "empty", "other_record")}
    for number in ("0", "3651"):
        with pytest.raises(CommandError) as refused:
            _run("--days", number)
        assert str(refused.value) == f"Число вне пределов от 1 до 3650: {number}"
    for args in ((), ("--days", "много")):
        with pytest.raises(CommandError):
            _run(*args)
    assert {name: _values(data[name]) for name in before} == before, "отклонённая команда изменила данные"


@PLAIN
def test_e2e_lists_shift_refuses_without_e2e_stand_flag(monkeypatch, clock, django_assert_num_queries):
    """FR-530: без `E2E_STAND=1` команда падает `CommandError(REFUSAL)` раньше любого запроса к базе (даже при
    `--days 0`: проверка стенда — первая строка `handle`); значения, отметки и уведомления не меняются
    (раздел 13.1)."""
    monkeypatch.delenv("E2E_STAND", raising=False)
    clock.set(moscow(2026, 3, 10, 12))
    data = _shift_data()
    sent = support.model("lists.ReminderSent").objects.create(
        record=data["both"], field=data["d1"], threshold_days=30, due_date=date(2026, 4, 20), notified=True)
    before = {name: _values(data[name]) for name in ("both", "hidden_only", "archived")}
    for number in ("1", "100", "0"):
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                _run("--days", number)
        assert str(refused.value) == REFUSAL, number
    assert {name: _values(data[name]) for name in before} == before, "отказавшая команда сдвинула значения"
    sent.refresh_from_db()
    assert sent.due_date == date(2026, 4, 20)
    assert not support.model("notify.Notification").objects.filter(kind="lists.deadline").exists()


@PLAIN
def test_e2e_lists_shift_moves_deadline_values_and_reminder_due_dates_back_without_save(monkeypatch, clock):
    """FR-530: значения всех полей-сроков (видимых и скрытых, у записей и в архиве) и `ReminderSent.due_date`
    сдвинуты на N суток назад; обычная дата, строка, пустые значения, записи без срочных полей и записи других
    списков не тронуты; `version`, `updated_at`, `updated_by` записей те же (прямая запись без `save()`;
    раздел 13.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(moscow(2026, 3, 1, 12))
    data = _shift_data()
    d1, d2, bought, serial = (data[name].code for name in ("d1", "d2", "bought", "serial"))
    sent = support.model("lists.ReminderSent").objects.create(
        record=data["both"], field=data["d1"], threshold_days=30, due_date=date(2026, 4, 20), notified=True)
    Record = type(data["both"])
    states = {name: Record.objects.filter(pk=data[name].pk).values("version", "updated_at", "updated_by_id").get()
              for name in ("both", "hidden_only", "archived", "empty", "other_record")}
    before = {name: _values(data[name]) for name in states}
    clock.set(moscow(2026, 3, 1, 18))  # время идёт: `save()` обновил бы `updated_at`

    assert _run("--days", "5") == "lists_shift: days=5 shifted=3 notified=0\n"

    assert _values(data["both"]) == {d1: "2026-04-15", d2: "2026-08-27", bought: "2026-05-05", serial: "С-1"}
    assert _values(data["hidden_only"]) == {d2: "2026-06-26"}
    assert _values(data["archived"]) == {d1: "2026-04-26"}
    assert _values(data["empty"]) == before["empty"] == {serial: "С-2"}
    assert _values(data["other_record"]) == before["other_record"], "сдвинута дата поля без срока"
    sent.refresh_from_db()
    assert sent.due_date == date(2026, 4, 15) and sent.threshold_days == 30
    for name, state in states.items():
        now = Record.objects.filter(pk=data[name].pk).values("version", "updated_at", "updated_by_id").get()
        assert now == state, f"{name}: изменились version, updated_at или updated_by"


@PLAIN
def test_e2e_lists_shift_keeps_history_audit_and_version_untouched(monkeypatch, clock):
    """FR-530: после сдвига строки истории `Change` (число, `at`, `changes`), события журнала `AuditEvent` (число и
    последний номер) и `version` записи те же; новых строк истории и журнала команда не пишет (раздел 13.1)."""
    from apps.core.services import audit

    monkeypatch.setenv("E2E_STAND", "1")
    clock.set(moscow(2026, 3, 1, 12))
    data = _shift_data()
    Change, Event = support.model("lists.Change"), support.model("core.AuditEvent")
    Change.objects.create(record=data["both"], at=timezone.now(), actor=data["both"].created_by, kind="created",
                          changes=[{"field": data["d1"].code, "name": "Срок один", "before": "",
                                    "after": "20.04.2026"}])
    audit.record("lists.list_created", object_type="lists.list", object_id=data["list"].pk,
                 after={"name": data["list"].name})
    history = list(Change.objects.order_by("id").values_list("id", "record_id", "at", "kind", "changes", "actor_id"))
    events = list(Event.objects.order_by("id").values_list("id", "action", "after"))
    version = type(data["both"]).objects.get(pk=data["both"].pk).version
    clock.set(moscow(2026, 3, 1, 18))

    assert _run("--days", "10") == "lists_shift: days=10 shifted=3 notified=0\n"

    assert list(Change.objects.order_by("id").values_list("id", "record_id", "at", "kind", "changes",
                                                          "actor_id")) == history
    assert list(Event.objects.order_by("id").values_list("id", "action", "after")) == events
    assert type(data["both"]).objects.get(pk=data["both"].pk).version == version
    assert _values(data["both"])[data["d1"].code] == "2026-04-10"


def _deadline_setup(clock):
    """Сегодня 2026-03-10 (Москва). Срок `d1` записи `both` — 2026-04-20 (через 41 день, порог 30 не наступил);
    после сдвига на 15 суток — 2026-04-05 (через 26 дней: порог 30 наступил). Единственный получатель — сотрудник
    с правом «Правят» (создателю записи уведомление не идёт)."""
    clock.set(moscow(2026, 3, 10, 12))
    data = _shift_data()
    data["editor"] = sl.as_editor(data["list"]).user
    return data


@PLAIN
def test_e2e_lists_shift_runs_remind_deadlines_after_shift(monkeypatch, clock):
    """FR-530: после сдвига команда в своём процессе выполняет обход сроков за «сегодня» по Москве: без сдвига у записи
    уведомлений нет (до срока 41 день), после сдвига на 15 суток наступил порог 30 — создано одно уведомление
    `lists.deadline` единственному получателю («Правят») и отметка `ReminderSent(30, 2026-04-05, notified=True)`;
    скрытое поле-срок и запись в архиве уведомлений не дают (раздел 13.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    data = _deadline_setup(clock)
    Notification, Sent = support.model("notify.Notification"), support.model("lists.ReminderSent")
    sl.run_reminders(moscow(2026, 3, 10, 12).date())
    assert not Notification.objects.filter(kind="lists.deadline").exists(), "уведомление до сдвига"

    assert _run("--days", "15") == "lists_shift: days=15 shifted=3 notified=1\n"

    sent = Notification.objects.filter(kind="lists.deadline")
    assert [row.user_id for row in sent] == [data["editor"].pk]
    assert sent[0].object_ref == f"lists.record:{data['both'].pk}:{data['d1'].pk}:30"
    marks = list(Sent.objects.filter(record=data["both"]).values_list("field_id", "threshold_days", "due_date",
                                                                       "notified"))
    assert marks == [(data["d1"].pk, 30, date(2026, 4, 5), True)]
    assert not Sent.objects.filter(record__in=[data["hidden_only"], data["archived"]]).exists()


@PLAIN
def test_e2e_lists_shift_prints_single_line_with_days_shifted_and_notified(monkeypatch, clock):
    """FR-530: вывод — ровно одна строка `lists_shift: days=<N> shifted=<записей> notified=<уведомлений>`: `shifted` —
    число записей, у которых изменено хотя бы одно значение (запись с двумя сроками считается один раз, запись без
    срочных значений и запись другого списка — нет), `notified` — число созданных уведомлений (раздел 13.1)."""
    monkeypatch.setenv("E2E_STAND", "1")
    _deadline_setup(clock)
    out = StringIO()
    call_command("e2e_lists_shift", "--days", "15", stdout=out)
    text = out.getvalue()
    assert text.count("\n") == 1, repr(text)
    found = SHIFT_LINE.fullmatch(text)
    assert found, repr(text)
    assert found.groups() == ("15", "3", "1"), "обе даты, только скрытая, в архиве — три записи; уведомление одно"
