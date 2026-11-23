"""T-10008: сброс стенда поручений и проверка стенда (CONTRACT-010, 1.3).

Каркас Этапа 1: точка `stand_reset` регистрируется последней (и идёт первой при общем сбросе), `require_stand`
отказывает без `E2E_STAND=1`, `stand_reset()` до моделей T-10201 не падает. Полные проверки очистки, файлов и
данных установки добавляет T-10123 (Этап 2).
"""
import io

import pytest
from django.core.management.base import CommandError

from tests import support

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."


@pytest.mark.django_db
def test_instructions_stand_reset_is_registered_last_after_tasks():
    """Решение 12 задач: `apps.instructions.stand.stand_reset` — последняя регистрация точки, сразу после задач;
    общий сброс (`e2e_reset_stand`) вызывает функции в обратном порядке, значит поручения идут первыми."""
    from apps.core import extensions
    from apps.instructions import stand as instructions_stand
    from apps.tasks import stand as tasks_stand

    funcs = extensions.registered("stand_reset")
    assert funcs, "нет зарегистрированных функций сброса стенда"
    assert funcs[-1] is instructions_stand.stand_reset
    assert funcs[-2] is tasks_stand.stand_reset


@pytest.mark.django_db
def test_stand_command_refused_without_e2e_stand(monkeypatch, django_assert_num_queries):
    """`require_stand()` без `E2E_STAND=1` (нет переменной, «0», пусто) бросает `CommandError(REFUSAL)` раньше
    любого запроса к базе; `REFUSAL` — текст контракта, своя копия; с `E2E_STAND=1` отказа нет."""
    from apps.instructions import stand

    assert stand.REFUSAL == REFUSAL
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


@pytest.mark.django_db
def test_seed_command_refused_without_e2e_stand(monkeypatch):
    """Команда `e2e_instructions_seed` проверяет стенд первой строкой: без `E2E_STAND=1` — отказ, вывод пуст."""
    from django.core.management import call_command

    monkeypatch.delenv("E2E_STAND", raising=False)
    out = io.StringIO()
    with pytest.raises(CommandError) as refused:
        call_command("e2e_instructions_seed", stdout=out)
    assert str(refused.value) == REFUSAL
    assert out.getvalue() == ""


@pytest.mark.django_db(databases=["default", "migrate"])
def test_stand_reset_is_safe_before_models():
    """Каркас T-10008 живёт до моделей T-10201: `stand_reset()` без таблиц поручений не падает и ничего не меняет."""
    from apps.instructions.stand import stand_reset

    assert stand_reset() is None

# --- T-10123: полный сброс и данные установки -----------------------------------------------------

import contextlib
import datetime

from django.db import connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
TABLES = ("InstructionReminder", "InstructionTransfer", "InstructionFile", "InstructionReportPart",
          "InstructionReport", "InstructionReportDate", "InstructionMember", "InstructionTask", "Instruction",
          "InstructionBasisKind", "InstructionSettings")
BASIS = ("Приказ", "Протокол совещания", "Письмо", "Устное указание")


def _on(label):
    return support.model(label).objects.using("migrate")


def _person(name):
    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name=name, state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _stored(status, data, *, purpose="instruction", write=True):
    from apps.core.services import files as core_files

    row = _on("core.StoredFile").create(
        purpose=purpose, owner=None, size=len(data), sha256="0" * 64, content_type="application/octet-stream",
        status=status, scanned_at=timezone.now() if status != "pending" else None)
    path = core_files.attachment_path(row)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return row, path


def _world(protected_root):
    author, assignee = _person("Автор Стенда Поручений"), _person("Исполнитель Стенда Поручений")
    basis = _on("instructions.InstructionBasisKind").create(title="Приказ", position=0)
    row = _on("instructions.Instruction").create(
        title="Поручение стенда", text="Текст стенда", basis_kind=basis, basis_number="1",
        basis_date=timezone.localdate(), author=author, controller=author, assignee=assignee,
        deadline=timezone.localdate() + datetime.timedelta(days=5),
        original_deadline=timezone.localdate() + datetime.timedelta(days=5))
    _on("instructions.InstructionSettings").update_or_create(pk=1, defaults={"retention_years": 7})
    _on("instructions.InstructionMember").create(instruction=row, user=author, role="coexecutor")
    due = _on("instructions.InstructionReportDate").create(instruction=row, due_date=timezone.localdate(),
                                                           position=0, state="review")
    report = _on("instructions.InstructionReport").create(instruction=row, date=due, author=assignee, text="Отчёт")
    _on("instructions.InstructionReportPart").create(date=due, author=author, text="Часть")
    stored, path = _stored("clean", b"instruction body")
    _on("instructions.InstructionFile").create(instruction=row, kind="report", report=report, file=stored,
                                               name="отчёт.txt", uploaded_by=author)
    _on("instructions.InstructionTransfer").create(
        instruction=row, old_deadline=row.deadline, new_deadline=row.deadline + datetime.timedelta(days=3),
        reason="Причина", requested_by=assignee, state="approved", decided_by=author, decided_at=timezone.now())
    _on("instructions.InstructionReminder").create(instruction=row, date=None, user=assignee, kind="deadline",
                                                   stage="d3", moment=timezone.now(), state="pending")
    task = _on("tasks.Task").create(title="Задача стенда", author=author, assignee=assignee, status="new")
    _on("instructions.InstructionTask").create(instruction=row, task=task, created_by=author)
    kept, kept_path = _stored("clean", b"other", purpose="attachment")
    kept_path.parent.mkdir(parents=True, exist_ok=True)
    kept_path.write_bytes(b"other")
    return {"instruction": row, "task": task, "file_path": path, "kept": kept, "kept_path": kept_path}


def _counts():
    return {name: _on(f"instructions.{name}").count() for name in TABLES}


@MIGRATE
def test_stand_reset_wipes_all_instruction_tables_and_restores_install(protected_root,
                                                                      django_capture_on_commit_callbacks):
    """NFR-729, CONTRACT-010, 1.3: сброс стирает все таблицы поручений и файлы `instruction`, возвращает настройки
    (3 года, лестница) и четыре вида основания; таблицы задач не трогаются."""
    from apps.instructions.stand import stand_reset

    world = _world(protected_root)
    assert all(_counts().values())
    with django_capture_on_commit_callbacks(execute=True):
        stand_reset()

    assert all(value == 0 for value in _counts().values()), _counts()
    settings_row = _on("instructions.InstructionSettings").get(pk=1)
    assert settings_row.retention_years == 3
    assert settings_row.default_ladder == {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}
    assert [item.title for item in _on("instructions.InstructionBasisKind").order_by("position")] == list(BASIS)
    assert _on("tasks.Task").filter(pk=world["task"].pk).exists()


@MIGRATE
def test_stand_reset_removes_instruction_files_but_keeps_other_purposes(protected_root,
                                                                        django_capture_on_commit_callbacks):
    """CONTRACT-010, 1.3: файлы назначения `instruction` удаляются с диска после фиксации; файлы других назначений
    остаются."""
    from apps.instructions.stand import stand_reset

    world = _world(protected_root)
    assert world["file_path"].is_file() and world["kept_path"].is_file()
    with django_capture_on_commit_callbacks(execute=True):
        stand_reset()
    assert not world["file_path"].exists(), "файл поручения остался на диске"
    assert world["kept_path"].is_file(), "файл другого назначения удалён"
    assert not _on("core.StoredFile").filter(purpose="instruction").exists()
    assert _on("core.StoredFile").filter(purpose="attachment").exists()


@pytest.mark.django_db
def test_seed_command_creates_three_and_is_idempotent(monkeypatch):
    """CONTRACT-010, 13.1: `e2e_instructions_seed` создаёт четыре вида и три поручения, повтор не дублирует,
    строка итога — `e2e_instructions_seed: instructions=3 basis=4`."""
    import io
    from django.core.management import call_command

    for index in range(4):
        support.make_employee(full_name=f"Стенд Поручений {index}")
    monkeypatch.setenv("E2E_STAND", "1")
    first = io.StringIO()
    call_command("e2e_instructions_seed", stdout=first)
    assert first.getvalue() == "e2e_instructions_seed: instructions=3 basis=4\n"
    Instruction = support.model("instructions.Instruction")
    assert Instruction.objects.count() == 3
    assert support.model("instructions.InstructionBasisKind").objects.count() == 4

    second = io.StringIO()
    call_command("e2e_instructions_seed", stdout=second)
    assert second.getvalue() == "e2e_instructions_seed: instructions=3 basis=4\n"
    assert Instruction.objects.count() == 3
    assert support.model("instructions.InstructionBasisKind").objects.count() == 4
    assert support.model("instructions.InstructionReportDate").objects.count() >= 1
    assert support.model("instructions.InstructionTransfer").objects.filter(state="pending").count() >= 1
