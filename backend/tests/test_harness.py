"""Каркасные тесты Этапа 1: стенд тестов работает (PostgreSQL, роли, Valkey, RQ).

Тесты требований среза — Этап 2 (T-100…). Здесь только проверка, что есть на
чём их писать.
"""
import importlib

import django_rq
import pytest
from django.db import connection, connections, transaction
from django.db.utils import ProgrammingError

from tests import factories

pytestmark = pytest.mark.django_db(databases=["default", "migrate"])


def test_harness_database_is_postgres_17_under_crm_app():
    with connection.cursor() as cur:
        cur.execute("SELECT current_user, current_database(), current_setting('server_version_num')::int")
        user, name, version = cur.fetchone()
    assert connection.vendor == "postgresql"
    assert version >= 170000
    assert user == "crm_app"
    assert name.startswith("test_")


def test_harness_schema_is_made_by_crm_owner():
    with connections["migrate"].cursor() as cur:
        cur.execute("SELECT current_user")
        assert cur.fetchone()[0] == "crm_owner"
        cur.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'django_migrations'")
        assert cur.fetchone()[0] == "crm_owner"


def test_harness_crm_app_cannot_create_tables():
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE harness_probe (id integer)")


def test_harness_default_privileges_reach_crm_app():
    # DDL владельца и проверка прав идут на одном соединении: таблица ещё не зафиксирована
    with connections["migrate"].cursor() as cur:
        cur.execute("CREATE TABLE harness_probe (id serial PRIMARY KEY)")
        cur.execute(
            "SELECT has_table_privilege('crm_app', 'harness_probe', 'SELECT, INSERT, UPDATE, DELETE'), "
            "has_table_privilege('crm_app', 'harness_probe', 'TRUNCATE'), "
            "has_sequence_privilege('crm_app', 'harness_probe_id_seq', 'USAGE')"
        )
        select_insert_update_delete, truncate, usage = cur.fetchone()
    assert select_insert_update_delete and usage and not truncate


def test_harness_valkey_is_real_and_cleaned_between_tests_part_1(valkey_clean):
    valkey_clean.set("harness:probe", "1")
    assert valkey_clean.get("harness:probe") == b"1"


def test_harness_valkey_is_real_and_cleaned_between_tests_part_2(valkey_clean):
    # идёт сразу после part_1: ключ из прошлого теста обязан исчезнуть
    assert valkey_clean.get("harness:probe") is None


def test_harness_rq_job_is_enqueued_on_commit_to_real_valkey(valkey_clean, django_capture_on_commit_callbacks):
    # django-rq 4.x: внутри транзакции задание ставится в очередь по фиксации (on_db_commit)
    queue = django_rq.get_queue("mail")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        queue.enqueue(len, "abc")
    assert len(callbacks) == 1
    assert queue.count == 1


def test_harness_totp_matches_rfc6238_vector():
    # RFC 6238, приложение B: ключ из ASCII "12345678901234567890", момент 59 с, 8 знаков
    assert factories.totp_code(b"12345678901234567890", at=59, digits=8) == "94287082"


def test_harness_passwords_are_random_and_long():
    assert factories.new_password() != factories.new_password()
    assert len(factories.new_password()) >= 12


def test_harness_clock_sets_now():
    from datetime import datetime, timezone as tz

    from django.utils import timezone

    moment = datetime(2030, 1, 2, 3, 4, tzinfo=tz.utc)
    c = factories.Clock().start()
    try:
        c.set(moment)
        assert timezone.now() == moment
        c.advance(hours=1)
        assert timezone.now().hour == 4
    finally:
        c.stop()


def test_harness_settings_derive_hosts_from_portal_url():
    from django.conf import settings

    module = importlib.import_module("config.settings")
    host = module.PORTAL_URL.split("://", 1)[1].split(":")[0]
    assert module.ALLOWED_HOSTS == [host]
    assert module.CSRF_TRUSTED_ORIGINS == [module.PORTAL_URL]
    assert host in settings.ALLOWED_HOSTS
