"""T-102: роли базы и неизменяемость журнала на уровне PostgreSQL (FR-044, FR-045, NFR-008).

Схема создана под crm_owner, запросы теста идут под crm_app (conftest.py);
журнал `core_auditevent` для crm_app — только SELECT и INSERT.
"""
import pytest
from django.db import connection, connections, transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from tests.support import model

pytestmark = pytest.mark.django_db(databases=["default", "migrate"])


def _insert_event(action="probe.created"):
    return model("core.AuditEvent").objects.create(
        at=timezone.now(), action=action, object_type="probe", object_id="1", before={}, after={"k": "v"}, ip="203.0.113.1")


def test_crm_app_owns_nothing():
    """FR-045: crm_app не владеет ни таблицами, ни последовательностями; владелец — crm_owner."""
    with connection.cursor() as cur:
        cur.execute("SELECT c.relname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
                    "WHERE r.rolname = 'crm_app' AND c.relnamespace = 'public'::regnamespace")
        owned = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'core_auditevent'")
        owner = cur.fetchall()
    assert owned == []
    assert owner == [("crm_owner",)], "таблицы журнала нет или у неё не тот владелец"


def test_crm_app_cannot_update_audit_table():
    """FR-045, NFR-008: UPDATE журнала под crm_app отклонён и на уровне прав, и на уровне запроса."""
    event = _insert_event()
    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE')")
        assert cur.fetchone()[0] is False
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("UPDATE core_auditevent SET action = %s WHERE id = %s", ["tampered", event.pk])
    with pytest.raises(ProgrammingError), transaction.atomic():
        model("core.AuditEvent").objects.filter(pk=event.pk).update(action="tampered")
    event.refresh_from_db()
    assert event.action == "probe.created"


def test_crm_app_cannot_delete_from_audit_table():
    """FR-045, NFR-008: DELETE и TRUNCATE журнала под crm_app отклонены."""
    event = _insert_event()
    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE id = %s", [event.pk])
    with pytest.raises(ProgrammingError), transaction.atomic():
        event.delete()
    assert model("core.AuditEvent").objects.filter(pk=event.pk).exists()


def test_crm_app_can_insert_and_select_audit():
    """FR-044: crm_app пишет в журнал и читает его; последовательность доступна; запись из сервиса проходит."""
    from apps.core.services import audit

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'SELECT'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'INSERT'), "
                    "has_sequence_privilege('crm_app', pg_get_serial_sequence('core_auditevent', 'id'), 'USAGE')")
        assert cur.fetchone() == (True, True, True)
    event = _insert_event("probe.direct")
    audit.record("probe.service", object_type="probe", object_id="2", after={"k": "v"}, ip="203.0.113.2")
    stored = list(model("core.AuditEvent").objects.order_by("id").values_list("action", flat=True))
    assert stored == ["probe.direct", "probe.service"]
    assert model("core.AuditEvent").objects.get(pk=event.pk).after == {"k": "v"}


def test_suite_runs_on_postgres():
    """NFR-008: тесты идут на PostgreSQL 17; схема — под crm_owner, запросы — под crm_app."""
    assert connection.vendor == "postgresql"
    with connection.cursor() as cur:
        cur.execute("SELECT current_user, current_setting('server_version_num')::int")
        user, version = cur.fetchone()
    assert user == "crm_app" and version >= 170000
    with connections["migrate"].cursor() as cur:
        cur.execute("SELECT current_user")
        assert cur.fetchone()[0] == "crm_owner"
        cur.execute("SELECT count(*) FROM pg_tables WHERE tablename IN ('core_user', 'core_auditevent', 'core_role')")
        assert cur.fetchone()[0] == 3, "таблицы среза ещё не созданы миграциями"
