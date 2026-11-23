"""Срез 010 «Поручения»: модели и изменения ядра (FR-700…723).

T-10002: назначение `instruction` в конце перечня и `core 0014`. Остальные тесты моделей добавляет T-10101.
"""
import ast
import datetime

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests import support
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def test_purpose_instruction_is_last():
    """NFR-722: `StoredFile.Purpose.INSTRUCTION = "instruction"` («вложение поручения») — последним; прежние
    семь значений и подписи те же; миграция `core 0014` — один `AlterField`, зависит от `0013`."""
    StoredFile = support.model("core.StoredFile")
    assert tuple(StoredFile.Purpose.values) == (
        "photo", "attachment", "knowledge", "lists", "feed", "messenger", "task", "instruction")
    assert StoredFile.Purpose.INSTRUCTION.label == "вложение поручения"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0014_storedfile_instruction_purpose.py"
    assert path.is_file(), "нет миграции core/0014_storedfile_instruction_purpose.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0013_tasks_permissions")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and operations[0].func.attr == "AlterField"


# --- модели и ограничения (T-10101; FR-700…709, FR-723, NFR-724, NFR-729) --------------------------------------

def _m(label):
    return support.model(label)


def _index_fields(model) -> list[tuple]:
    return [tuple(index.fields) for index in model._meta.indexes]


def _unique_sets(model) -> list[tuple]:
    """Уникальные наборы полей модели: `unique`, `unique_together` и `UniqueConstraint` без условия."""
    result = [(field.name,) for field in model._meta.fields if field.unique and not field.primary_key]
    result += [tuple(item) for item in (model._meta.unique_together or ())]
    for constraint in model._meta.constraints:
        fields = tuple(getattr(constraint, "fields", ()) or ())
        if fields and getattr(constraint, "condition", None) is None:
            result.append(fields)
    return result


def _constraint(model, **fields):
    """`UniqueConstraint`/`CheckConstraint` по именам полей (условие не важно)."""
    for constraint in model._meta.constraints:
        if tuple(getattr(constraint, "fields", ()) or ()) == tuple(fields):
            return constraint
    raise AssertionError(f"нет ограничения {fields}: {model._meta.constraints}")


def test_instruction_fields_limits_and_original_deadline():
    """FR-700: поля поручения и пределы; `original_deadline` — дата, `ladder` — JSON, `closed_at`/`deleted_at`
    пусты у живой; номер — `pk`, `__str__` — `#<pk> <название>` (CONTRACT-010, 2.1)."""
    Instruction = _m("instructions.Instruction")
    fields = {field.name: field for field in Instruction._meta.get_fields()}
    assert {"title", "text", "basis_kind", "basis_number", "basis_date", "author", "controller", "assignee",
            "deadline", "original_deadline", "ladder", "created_at", "updated_at", "closed_at",
            "deleted_at"} <= set(fields)
    assert fields["title"].max_length == 300
    assert fields["text"].max_length == 10_000
    assert fields["basis_number"].max_length == 100
    for name in ("basis_kind", "author", "controller", "assignee"):
        assert fields[name].many_to_one and fields[name].remote_field.on_delete.__name__ == "PROTECT"
    for name in ("basis_date", "deadline", "original_deadline"):
        assert fields[name].get_internal_type() == "DateField"
    assert not fields["original_deadline"].null
    assert fields["ladder"].get_internal_type() == "JSONField"
    assert fields["closed_at"].null and fields["deleted_at"].null
    assert Instruction._meta.pk.name == "id"

    row = ins.make_instruction(title="Проверить регламент")
    assert str(row) == f"#{row.pk} Проверить регламент"
    assert row.original_deadline == row.deadline


def test_instruction_indexes_match_plan():
    """FR-700, FR-713: индексы `(assignee, deadline)`, `controller`, `author`, `deadline`, `closed_at`,
    `basis_kind` (CONTRACT-010, 2.1)."""
    indexes = _index_fields(_m("instructions.Instruction"))
    for wanted in (("assignee", "deadline"), ("controller",), ("author",), ("deadline",), ("closed_at",),
                   ("basis_kind",)):
        assert wanted in indexes, f"нет индекса {wanted}: {indexes}"


def test_basis_kind_title_unique_position_and_active():
    """FR-701: `InstructionBasisKind` — уникальное название, `position`, `active=True`; индекс `position`."""
    Kind = _m("instructions.InstructionBasisKind")
    assert Kind._meta.get_field("title").max_length == 100
    assert Kind._meta.get_field("active").default is True
    assert ("title",) in _unique_sets(Kind)
    assert ("position",) in _index_fields(Kind)

    ins.make_basis("Приказ")
    with pytest.raises(IntegrityError), transaction.atomic():
        Kind.objects.create(title="Приказ", position=5)


def test_member_coexecutor_unique_and_index():
    """FR-704: `InstructionMember` — роль `coexecutor`, уникальность `(instruction, user)`, индекс `user`."""
    Member = _m("instructions.InstructionMember")
    field = Member._meta.get_field("role")
    assert [value for value, _label in field.choices] == ["coexecutor"]
    assert field.default == "coexecutor"
    assert ("instruction", "user") in _unique_sets(Member)
    assert ("user",) in _index_fields(Member)

    row = ins.make_instruction()
    person = ins.staff_user()
    ins.add_coexecutor(row, person)
    with pytest.raises(IntegrityError), transaction.atomic():
        ins.add_coexecutor(row, person)


def test_report_date_states_unique_and_indexes():
    """FR-705, FR-717: `InstructionReportDate` — четыре состояния, по умолчанию `waiting`; уникальность
    `(instruction, due_date)`, индекс `(instruction, position)`."""
    ReportDate = _m("instructions.InstructionReportDate")
    field = ReportDate._meta.get_field("state")
    assert [value for value, _label in field.choices] == ["waiting", "review", "returned", "accepted"]
    assert field.default == "waiting"
    assert ("instruction", "due_date") in _unique_sets(ReportDate)
    assert ("instruction", "position") in _index_fields(ReportDate)

    row = ins.make_instruction()
    due = ins._today() + datetime.timedelta(days=7)
    ins.add_report_date(row, due)
    with pytest.raises(IntegrityError), transaction.atomic():
        ins.add_report_date(row, due, position=1)


def test_report_final_is_one_and_part_belongs_to_date():
    """FR-706, FR-723: итоговый отчёт (`date` пусто) один на автора; часть отчёта требует отчётную дату и
    уникальна `(date, author)`; `date` отчёта — CASCADE, части — CASCADE (CONTRACT-010, 2.1)."""
    Report, Part = _m("instructions.InstructionReport"), _m("instructions.InstructionReportPart")
    report_date_field = Report._meta.get_field("date")
    assert report_date_field.null and report_date_field.remote_field.on_delete.__name__ == "CASCADE"
    condition = _constraint(Report, "instruction", "author").condition
    assert condition is not None and "date__isnull" in str(condition)
    assert _m("instructions.InstructionReportPart")._meta.get_field("date").null is False
    assert ("date", "author") in _unique_sets(Part)
    assert ("date",) in _index_fields(Part)
    assert ("instruction", "submitted_at") in _index_fields(Report)

    row = ins.make_instruction()
    author = row.assignee
    Report.objects.create(instruction=row, date=None, author=author, text="Итог")
    with pytest.raises(IntegrityError), transaction.atomic():
        Report.objects.create(instruction=row, date=None, author=author, text="Ещё итог")

    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=3))
    Part.objects.create(date=due, author=author, text="Часть")
    with pytest.raises(IntegrityError), transaction.atomic():
        Part.objects.create(date=due, author=author, text="Ещё часть")


def test_transfer_single_pending_and_states():
    """FR-708: `InstructionTransfer` — три состояния, один `pending` на поручение (частичный уникальный
    индекс), причина до 1 000 знаков, комментарий до 2 000; индекс `(instruction, state)`."""
    Transfer = _m("instructions.InstructionTransfer")
    assert [value for value, _label in Transfer._meta.get_field("state").choices] == [
        "pending", "approved", "rejected"]
    assert Transfer._meta.get_field("state").default == "pending"
    assert Transfer._meta.get_field("reason").max_length == 1_000
    assert Transfer._meta.get_field("comment").max_length == 2_000
    assert ("instruction", "state") in _index_fields(Transfer)
    constraint = _constraint(Transfer, "instruction")
    assert constraint.condition is not None and "state" in str(constraint.condition)

    row = ins.make_instruction()
    today = ins._today()
    Transfer.objects.create(instruction=row, old_deadline=row.deadline,
                            new_deadline=row.deadline + datetime.timedelta(days=5), reason="Причина",
                            requested_by=row.assignee)
    with pytest.raises(IntegrityError), transaction.atomic():
        Transfer.objects.create(instruction=row, old_deadline=row.deadline,
                                new_deadline=row.deadline + datetime.timedelta(days=6), reason="Вторая",
                                requested_by=row.assignee)


def test_reminder_stages_states_and_pending_unique_with_nulls():
    """FR-709: `InstructionReminder` — `stage` из девяти порогов, три состояния; уникальность
    `(instruction, date, user, kind, stage)` только для `pending` и с `nulls_distinct=False` (дата срока —
    пусто); индекс `(state, moment)`."""
    Reminder = _m("instructions.InstructionReminder")
    stages = [value for value, _label in Reminder._meta.get_field("stage").choices]
    assert stages == ["d30", "d14", "d7", "d3", "d1", "due", "overdue", "r3", "r1"]
    assert [value for value, _label in Reminder._meta.get_field("state").choices] == [
        "pending", "sent", "cancelled"]
    assert Reminder._meta.get_field("state").default == "pending"
    assert Reminder._meta.get_field("date").null
    assert ("state", "moment") in _index_fields(Reminder)
    constraint = _constraint(Reminder, "instruction", "date", "user", "kind", "stage")
    assert constraint.nulls_distinct is False
    assert constraint.condition is not None and "pending" in str(constraint.condition)

    row = ins.make_instruction()
    user, moment = row.assignee, timezone.now() + datetime.timedelta(days=1)
    Reminder.objects.create(instruction=row, date=None, user=user, kind="deadline", stage="d3", moment=moment)
    with pytest.raises(IntegrityError), transaction.atomic():
        Reminder.objects.create(instruction=row, date=None, user=user, kind="deadline", stage="d3",
                                moment=moment)


def test_settings_single_row_retention_default_and_check():
    """NFR-729: `InstructionSettings` — одна строка `pk=1`, срок хранения по умолчанию 3, `CheckConstraint`
    1–10; `default_ladder` — JSON (CONTRACT-010, 2.1)."""
    Settings = _m("instructions.InstructionSettings")
    assert Settings._meta.pk.name == "id"
    field = Settings._meta.get_field("retention_years")
    assert field.default == 3
    assert any("retention" in (getattr(item, "name", "") or "") or "retention_years" in str(item)
               for item in Settings._meta.constraints), Settings._meta.constraints
    row = Settings.objects.create(pk=1)
    assert row.retention_years == 3
    assert isinstance(row.default_ladder, dict)
    for bad in (0, 11):
        with pytest.raises(IntegrityError), transaction.atomic():
            Settings.objects.filter(pk=1).update(retention_years=bad)


def test_file_kinds_and_task_link():
    """NFR-722, FR-716: `InstructionFile` — три вида, `report`/`part` SET_NULL, `file` OneToOne PROTECT;
    `InstructionTask` — уникальность `(instruction, task)`, задача CASCADE, индекс `task`."""
    File = _m("instructions.InstructionFile")
    assert [value for value, _label in File._meta.get_field("kind").choices] == ["basis", "report", "part"]
    assert File._meta.get_field("file").one_to_one
    assert File._meta.get_field("file").remote_field.on_delete.__name__ == "PROTECT"
    for name in ("report", "part"):
        assert File._meta.get_field(name).null
        assert File._meta.get_field(name).remote_field.on_delete.__name__ == "SET_NULL"
    assert ("instruction",) in _index_fields(File)

    Link = _m("instructions.InstructionTask")
    assert ("instruction", "task") in _unique_sets(Link)
    assert ("task",) in _index_fields(Link)
    assert Link._meta.get_field("task").remote_field.on_delete.__name__ == "CASCADE"
