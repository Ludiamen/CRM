"""T-9124: данные установки задач и команда стенда `e2e_tasks_seed` (FR-674…FR-699; CONTRACT-009, 1.3, 13.1).

План: «Настройки задач» (`TaskSettings` создаётся лениво, `pk=1`, 3 года), «Проверка» → «данные установки и стенд»,
«Нагрузка» (данные сценариев). Контракт: 1.3 (данные установки: `TaskSettings(pk=1, retention_years=3)`; категории —
данные администратора и установкой не создаются), 2.1 (`TaskSettings`), 5.1 (`services.settings.get/save`), 13.1
(`e2e_tasks_seed`: две категории, три задачи, повтор без дублей, строка
`e2e_tasks_seed: tasks=3 categories=2`).

Код среза на уровне модуля не импортируется; модели — `support.model(...)`, службы и команда — внутри тестов, поэтому
`pytest --collect-only` проходит до появления кода. Секретов и ПДн нет: сотрудники вымышленные.
"""
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from tests import support
from tests import support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
LINE = "e2e_tasks_seed: tasks=3 categories=2\n"
CATEGORIES = {"Работа", "Личное"}


# --- помощники файла --------------------------------------------------------------------------------------

def _settings():
    return support.model("tasks.TaskSettings")


def _categories():
    return support.model("tasks.TaskCategory")


def _tasks():
    return support.model("tasks.Task")


def _members():
    return support.model("tasks.TaskMember")


def _row():
    return _settings().objects.get(pk=1)


def _seed(*args) -> str:
    out = StringIO()
    call_command("e2e_tasks_seed", *args, stdout=out)
    return out.getvalue()


def _people():
    """Руководитель узла, подчинённый ему сотрудник, соисполнитель и наблюдатель — четыре действующих сотрудника."""
    unit = support_org.make_unit("Отдел Стенда Задач")
    head = support_tasks.head_of(unit, full_name="Руководитель Стенда")
    subordinate = support.make_employee(full_name="Подчинённый Стенда")
    support_org.make_member(subordinate, unit)
    coexecutor = support.make_employee(full_name="Соисполнитель Стенда")
    observer = support.make_employee(full_name="Наблюдатель Стенда")
    return head, subordinate, coexecutor, observer


# --- данные установки: TaskSettings -----------------------------------------------------------------------

def test_settings_get_creates_single_row_with_three_years():
    """FR-696 (CONTRACT-009, 1.3, 5.1): строки настроек нет — `services.settings.get()` создаёт ровно одну строку
    `TaskSettings(pk=1, retention_years=3)` без «кто и когда менял»; повторный вызов отдаёт её же."""
    from apps.tasks.services import settings as tasks_settings

    assert not _settings().objects.exists(), "установка уже создала строку настроек (ожидается ленивое создание)"
    row = tasks_settings.get()
    assert (row.pk, row.retention_years, row.updated_by_id, row.updated_at) == (1, 3, None, None)
    assert _settings().objects.count() == 1
    again = tasks_settings.get()
    assert again.pk == row.pk and _settings().objects.count() == 1


def test_settings_get_keeps_existing_values():
    """FR-696: `get()` не перезаписывает уже стоящие значения — срок 7 лет и менявший администратор читаются как есть,
    второй строки не появляется; `save(actor, years)` меняет ту же строку."""
    from apps.tasks.services import settings as tasks_settings

    admin = support.make_admin(full_name="Администратор Настроек")
    tasks_settings.get()
    _settings().objects.filter(pk=1).update(retention_years=7, updated_by=admin, updated_at=timezone.now())
    kept = tasks_settings.get()
    assert (kept.pk, kept.retention_years, kept.updated_by_id) == (1, 7, admin.pk)
    assert _settings().objects.count() == 1

    saved = tasks_settings.save(admin, 5)
    assert (saved.pk, saved.retention_years) == (1, 5)
    assert _settings().objects.count() == 1
    assert _settings().objects.get(pk=1).updated_by_id == admin.pk


def test_installation_does_not_create_categories():
    """FR-683, FR-696 (CONTRACT-009, 1.3): категории — данные администратора, а не установки: на свежей базе
    справочник пуст, `settings.get()` его не наполняет; после удаления категорий повторный `get()` их не возвращает."""
    from apps.tasks.services import settings as tasks_settings

    assert _categories().objects.count() == 0, "установка создала категории"
    tasks_settings.get()
    assert _categories().objects.count() == 0
    support_tasks.make_category("Работа")
    _categories().objects.all().delete()
    tasks_settings.get()
    assert _categories().objects.count() == 0


# --- команда e2e_tasks_seed -------------------------------------------------------------------------------

def test_e2e_tasks_seed_creates_categories_three_tasks_and_line(monkeypatch):
    """FR-674, FR-675, FR-683 (CONTRACT-009, 13.1): `e2e_tasks_seed` с `E2E_STAND=1` создаёт две категории
    («Работа», «Личное») и три задачи — свою, подчинённому, с соисполнителем и наблюдателем; вывод — ровно одна
    строка `e2e_tasks_seed: tasks=3 categories=2`."""
    monkeypatch.setenv("E2E_STAND", "1")
    head, subordinate, coexecutor, observer = _people()
    out = _seed()

    assert out == LINE, repr(out)
    assert set(_categories().objects.values_list("title", flat=True)) == CATEGORIES
    assert _categories().objects.count() == 2
    tasks = list(_tasks().objects.all())
    assert len(tasks) == 3, f"задач создано: {len(tasks)}"
    authors = {task.author_id for task in tasks}
    assignees = {task.assignee_id for task in tasks}
    assert head.pk in authors and head.pk in assignees, "нет своей задачи руководителя"
    assert subordinate.pk in assignees, "нет задачи подчинённому"
    assert any(task.assignee_id != task.author_id for task in tasks), "все три задачи поставлены себе"

    with_members = [task for task in tasks if _members().objects.filter(task=task).exists()]
    assert with_members, "нет задачи с соисполнителем и наблюдателем"
    roles = set(_members().objects.filter(task=with_members[0]).values_list("user_id", "role"))
    assert (coexecutor.pk, "coexecutor") in roles, "нет соисполнителя"
    assert (observer.pk, "observer") in roles, "нет наблюдателя"


def test_e2e_tasks_seed_twice_does_not_duplicate(monkeypatch):
    """FR-674 (CONTRACT-009, 13.1): повторный запуск `e2e_tasks_seed` не дублирует ни категории, ни задачи, ни
    участников; строка итога та же, номера строк прежние."""
    monkeypatch.setenv("E2E_STAND", "1")
    _people()
    assert _seed() == LINE
    categories = list(_categories().objects.order_by("pk").values_list("pk", flat=True))
    tasks = list(_tasks().objects.order_by("pk").values_list("pk", flat=True))
    members = list(_members().objects.order_by("pk").values_list("pk", flat=True))
    assert len(categories) == 2 and len(tasks) == 3

    assert _seed() == LINE
    assert list(_categories().objects.order_by("pk").values_list("pk", flat=True)) == categories
    assert list(_tasks().objects.order_by("pk").values_list("pk", flat=True)) == tasks
    assert list(_members().objects.order_by("pk").values_list("pk", flat=True)) == members


def test_e2e_tasks_seed_refuses_without_e2e_stand(monkeypatch):
    """FR-674 (CONTRACT-009, 13.1): без `E2E_STAND=1` (нет переменной, «0», пусто) команда бросает
    `CommandError` с текстом контракта раньше любого запроса к базе; категорий, задач и участников не появляется;
    с `E2E_STAND=1` команда работает."""
    _people()
    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        with pytest.raises(CommandError) as refused:
            _seed()
        assert str(refused.value) == REFUSAL, repr(value)
        assert _categories().objects.count() == 0
        assert _tasks().objects.count() == 0
        assert _members().objects.count() == 0
    monkeypatch.setenv("E2E_STAND", "1")
    assert _seed() == LINE


def test_e2e_tasks_seed_checks_stand_first_in_handle():
    """FR-674 (CONTRACT-009, 1.3, 13.1): проверка стенда — первая строка `handle` команды: `require_stand()` стоит
    до импорта моделей и любых чтений базы; `REFUSAL` команды — копия текста контракта, а не импорт чужого."""
    import ast
    import inspect
    import textwrap

    from apps.tasks.management.commands import e2e_tasks_seed

    source = textwrap.dedent(inspect.getsource(e2e_tasks_seed.Command.handle))
    tree = ast.parse(source)
    body = [node for node in tree.body[0].body if not (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))]
    first = body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert ast.unparse(first.value.func) == "require_stand", f"первая строка handle: {ast.unparse(first)}"
    assert e2e_tasks_seed.Command.help.strip(), "у команды нет описания"