"""Права на журнал: у роли приложения только SELECT и INSERT (FR-045, NFR-008).

Остальным таблицам crm_app получает SELECT/INSERT/UPDATE/DELETE через ALTER DEFAULT
PRIVILEGES (deploy/postgres-init/01-roles.sh), поэтому здесь права отзываются
(REVOKE ALL), затем выдаются нужные и USAGE на последовательность — иначе INSERT не
пройдёт. Владелец таблицы (crm_owner) обходит эти права, а crm_app ничем не владеет.
Единственное место, где в срезе есть сырой SQL. Если роли crm_app в базе нет (разовая
база без ролей), миграция ничего не делает.
"""
from django.db import migrations

APPLY = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN
        REVOKE ALL ON TABLE core_auditevent FROM crm_app;
        GRANT SELECT, INSERT ON TABLE core_auditevent TO crm_app;
        GRANT USAGE ON SEQUENCE core_auditevent_id_seq TO crm_app;
    END IF;
END
$$;
"""

REVERT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crm_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE core_auditevent TO crm_app;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0002_initial_data")]
    operations = [migrations.RunSQL(APPLY, REVERT)]
