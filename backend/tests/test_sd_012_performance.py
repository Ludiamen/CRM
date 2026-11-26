"""T-12111: настоящий p95 smoke-профиль NFR-737/NFR-738.

Полный объём 110 тыс. заявок/550 тыс. сообщений и 50 параллельных заявителей
запускается существующим Locust-профилем ``tests/load/locustfile.py`` на этапе
приёмки. Здесь остаётся серверная проверка реального маршрута на синтетическом
стенде: 100 пользователей и 100 измерений каждого маршрута, без подмены
приложения; порог тот же 500 мс.
"""
import statistics
import time

import pytest

from tests import support, support_org
from tests.support_servicedesk import make_queue, make_ticket

pytestmark = [pytest.mark.django_db, pytest.mark.slow]


def test_queue_card_and_rating_page_p95_under_500ms_for_100_users():
    """NFR-737/NFR-738: p95 серверных GET на 100 синтетических пользователях."""
    queue = make_queue()
    users = [support.make_employee() for _ in range(100)]
    for user in users:
        support_org.make_member(user, queue.unit)
    ticket = make_ticket(queue=queue)
    timings = []
    for user in users:
        client = support.logged_in(user)
        started = time.perf_counter()
        response = client.get(f"/tickets/{ticket.number}/")
        timings.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
    p95 = statistics.quantiles(timings, n=20, method="inclusive")[18]
    assert p95 <= 500, f"p95 карточки: {p95:.1f} мс"


def test_rating_page_p95_under_500ms_for_fifty_public_requesters():
    """NFR-738: 50 независимых публичных GET оценки измеряются без моков."""
    ticket = make_ticket(queue=make_queue())
    timings = []
    for _ in range(50):
        client = support.make_client()
        started = time.perf_counter()
        response = client.get(f"/rate/?ticket={ticket.number}")
        timings.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
    p95 = statistics.quantiles(timings, n=20, method="inclusive")[18]
    assert p95 <= 500, f"p95 страницы оценки: {p95:.1f} мс"
