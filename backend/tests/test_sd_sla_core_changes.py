"""T-11112: изменения ядра среза 011 (FR-755, FR-756)."""
import ast
from types import SimpleNamespace

import pytest

from tests import support

pytestmark = pytest.mark.django_db

PERMISSIONS = ("servicedesk.sla", "servicedesk.reports", "servicedesk.answers")
TITLES = {
    "servicedesk.sla": "Уровни обслуживания заявок",
    "servicedesk.reports": "Отчёт по заявкам",
    "servicedesk.answers": "Общие частые ответы",
}


@pytest.fixture
def reset_env(monkeypatch, settings, protected_root):
    """Окружение прямого сброса стенда на соединении `migrate`."""
    monkeypatch.setenv("E2E_STAND", "1")
    settings.IMAP_HOST = ""
    return protected_root


def test_sla_permissions_and_initial_role_grants():
    """FR-756: права и русские названия совпадают с core 0016; выдачи ролям корректны."""
    Permission = support.model("core.Permission")
    Role = support.model("core.Role")

    assert dict(Permission.objects.filter(code__in=PERMISSIONS).values_list("code", "title")) == TITLES
    admin = Role.objects.get(name="Администратор портала", is_builtin=True)
    manager = Role.objects.get(name="Руководитель", is_builtin=True)
    assert len(admin.permissions.all()) == 24
    assert "servicedesk.reports" not in admin.permissions.values_list("code", flat=True)
    assert "servicedesk.reports" in manager.permissions.values_list("code", flat=True)

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0016_servicedesk_sla_permissions.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    migration = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {
        target.id: node.value
        for node in migration.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0015_instructions_permissions")]


def test_core_0016_permission_seed_is_idempotent():
    """FR-756: повторный seed core 0016 не создаёт дубликатов и не меняет выдачи."""
    import importlib
    from django.apps import apps as django_apps
    from django.db import connections, migrations

    module = importlib.import_module("apps.core.migrations.0016_servicedesk_sla_permissions")
    operation = next(item for item in module.Migration.operations if isinstance(item, migrations.RunPython))
    Permission = support.model("core.Permission")
    Role = support.model("core.Role")
    before = (
        Permission.objects.count(),
        Permission.objects.filter(code__in=PERMISSIONS).count(),
        Role.objects.get(name="Администратор портала", is_builtin=True).permissions.count(),
        Role.objects.get(name="Руководитель", is_builtin=True).permissions.count(),
    )
    editor = SimpleNamespace(connection=connections["default"])
    operation.code(django_apps, editor)
    operation.code(django_apps, editor)
    after = (
        Permission.objects.count(),
        Permission.objects.filter(code__in=PERMISSIONS).count(),
        Role.objects.get(name="Администратор портала", is_builtin=True).permissions.count(),
        Role.objects.get(name="Руководитель", is_builtin=True).permissions.count(),
    )
    assert after == before


def test_servicedesk_menu_has_four_items_with_sla_orders():
    """FR-756: сервис-деск регистрирует четыре пункта, уровни имеют order 6, отчёт — order 7."""
    from apps.servicedesk.services import listing

    items = listing.menu_items()
    assert len(items) == 4
    by_title = {item["title"]: item for item in items}
    assert by_title["Уровни обслуживания"]["order"] == 6
    assert by_title["Уровни обслуживания"]["url"] == "/servicedesk/sla/"
    assert by_title["Отчёт по заявкам"]["order"] == 7
    assert by_title["Отчёт по заявкам"]["url"] == "/servicedesk/reports/"


def test_sla_audit_labels_are_registered():
    """FR-755: все события среза и русские подписи полей зарегистрированы."""
    from apps.core import extensions
    from apps.servicedesk import audit_labels

    labels = audit_labels.audit_labels()
    expected = {
        "ticket.assignee_skipped": "Ответственный по уровню не назначен",
        "servicedesk.sla_level_created": "Уровень обслуживания создан",
        "servicedesk.sla_level_changed": "Уровень обслуживания изменён",
        "servicedesk.sla_level_archived": "Уровень обслуживания архивирован",
        "servicedesk.binding_changed": "Привязка уровня изменена",
        "servicedesk.answer_created": "Шаблон ответа создан",
        "servicedesk.answer_changed": "Шаблон ответа изменён",
        "servicedesk.answer_archived": "Шаблон ответа архивирован",
        "servicedesk.report_exported": "Отчёт выгружен",
    }
    assert {code: labels["actions"].get(code) for code in expected} == expected
    assert labels["fields"]["cycle"] == "номер цикла"
    assert labels["fields"]["level"] == "уровень обслуживания"
    assert labels["fields"]["reaction_due"] == "срок реакции"
    assert labels["fields"]["solution_due"] == "срок решения"
    assert labels["fields"]["verdicts"] == "вердикты сроков"
    assert labels["values"]["reason"]["not_participant"] == "больше не участник очереди"
    assert audit_labels.audit_labels in extensions.registered("audit_labels")


@pytest.mark.django_db(databases=["default", "migrate"])
def test_stand_reset_clears_sla_rows_and_valkey_keys(reset_env):
    """FR-755, FR-756: stand_reset удаляет данные SLA и ключи среза, оставляя стендовые справочники."""
    from apps.core.services import valkey
    from apps.servicedesk import stand
    from tests import factories
    from tests.support_servicedesk import make_answer, make_category, make_cycle, make_level, make_queue, make_ticket

    User = support.model("core.User")
    owner = User(email=factories.new_email(), full_name="Владелец стенда", state="active")
    owner.set_password(factories.new_password())
    owner.save(using="migrate")
    queue = make_queue(created_by=owner, using="migrate")
    category = make_category(queue=queue, using="migrate")
    level = make_level(using="migrate")
    from tests.support_servicedesk import bind_level
    bind_level(level, category=category, using="migrate")
    make_answer(owner=owner, using="migrate")
    ticket = make_ticket(queue=queue, using="migrate")
    cycle = make_cycle(ticket, level=level, using="migrate")
    SlaNotice = support.model("servicedesk.SlaNotice")
    SlaDigest = support.model("servicedesk.SlaDigest")
    SlaNotice.objects.using("migrate").create(
        cycle=cycle, deadline="reaction", kind="due_soon", due_at=cycle.reaction_due, recipient=owner
    )
    SlaDigest.objects.using("migrate").create(recipient=owner, day=cycle.cycle_started_at.date())

    conn = valkey.conn()
    for key in ("sla:tick", "servicedesk:sla:notice", "servicedesk:digest:2026-11-24"):
        conn.set(key, "1")

    stand.stand_reset()

    for name in ("SlaCycle", "SlaNotice", "SlaDigest", "SlaLevel", "SlaBinding", "AnswerTemplate"):
        assert support.model(f"servicedesk.{name}").objects.using("migrate").count() == 0, name
    assert all(conn.exists(key) == 0 for key in ("sla:tick", "servicedesk:sla:notice",
                                                  "servicedesk:digest:2026-11-24"))


def test_installed_apps_tail_keeps_instructions_last():
    """FR-756: хвост INSTALLED_APPS не сдвинут: apps.instructions остаётся последним."""
    from django.conf import settings

    installed = list(settings.INSTALLED_APPS)
    assert installed[-1] == "apps.instructions"
    assert installed[-2] == "apps.tasks"


def test_servicedesk_0004_depends_on_core_0016():
    """FR-756: миграция моделей сервис-деска строится после данных прав core 0016."""
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(connection)
    node = loader.graph.node_map[("servicedesk", "0004_sla_answers")]
    assert ("core", "0016_servicedesk_sla_permissions") in node.parents
