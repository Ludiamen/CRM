"""T-117: ёмкость и скорость (NFR-001, NFR-002).

Проверка p95 ≤ 500 мс на 100 пользователях — нагрузочный прогон `tests/load/locustfile.py` (Этап 4, T-304),
здесь — то, что видно в тестах: 100 сессий держатся, а число запросов к базе у списков не растёт с выборкой.
"""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db


def test_hundred_users_hold_hundred_sessions():
    """NFR-001: 100 учётных записей входят одновременно, 100 сессий живут рядом и каждая работает."""
    users = [support.make_employee() for _ in range(100)]
    clients = [support.logged_in(u, ip=f"203.0.{i // 200}.{i % 200 + 1}") for i, u in enumerate(users)]
    assert model("core.UserSession").objects.count() == 100
    assert len({s.session_key for s in model("core.UserSession").objects.all()}) == 100
    for _ in range(2):
        assert all(c.get("/me/").status_code == 200 for c in clients)
    assert model("core.UserSession").objects.count() == 100, "запросы не плодят и не теряют сессии"
    assert model("core.LoginAttempt").objects.filter(result="success").count() == 100


def queries(client, path) -> int:
    client.get(path)  # прогрев: кэш прав, статика
    with CaptureQueriesContext(connection) as captured:
        got = client.get(path)
    assert got.status_code == 200, path
    return len(captured)


def test_list_pages_query_count_constant_for_staff_audit_and_history():
    """NFR-002: число запросов к базе у списка сотрудников, журнала и истории входов не зависит от размера выборки (нет N+1)."""
    from apps.core.services.audit import record

    Attempt = model("core.LoginAttempt")
    role = factories.make_role(name="Нагрузочная", permissions=("audit.view",))
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user, ip="198.51.100.190")
    target = support.make_employee(roles=[role])
    paths = ("/staff/", "/audit/", f"/staff/{target.pk}/logins/", "/me/security/history/")

    def add_attempts(n):
        Attempt.objects.bulk_create([Attempt(user=admin_user, ip=f"192.0.2.{i % 250}", browser="Firefox", platform="Linux",
                                             result="bad_password", at=timezone.now() - timedelta(minutes=i))
                                     for i in range(n)] +
                                    [Attempt(user=target, ip=f"192.0.2.{i % 250}", browser="Firefox", platform="Linux",
                                             result="bad_password", at=timezone.now() - timedelta(minutes=i))
                                     for i in range(n)])

    for i in range(2):
        support.make_employee(roles=[role])
        record("probe.small", actor=admin_user, object_type="probe", object_id=str(i))
    add_attempts(3)
    small = {path: queries(admin, path) for path in paths}
    for i in range(30):
        support.make_employee(roles=[role])
    for i in range(300):
        record("probe.large", actor=admin_user, object_type="probe", object_id=str(i))
    add_attempts(120)
    large = {path: queries(admin, path) for path in paths}
    assert large == small, f"число запросов растёт с выборкой: было {small}, стало {large}"
    assert all(n <= 25 for n in large.values()), f"слишком много запросов на страницу: {large}"
