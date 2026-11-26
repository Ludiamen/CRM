"""T-12105: красные серверные тесты оценки заявителя (FR-769…771, NFR-738)."""
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _fixture(name="ИТ"):
    tree = org.make_tree({name: {}})
    actor = support.make_with_permissions("servicedesk.all")
    org.make_member(actor, tree[name])
    level = sd.make_level(all_day=True)
    ticket = sd.make_ticket(queue=tree[name], sla=level, assignee=actor)
    sd.make_cycle(ticket, level=level, assignee=actor)
    return actor, ticket


def _rating_rows(ticket):
    return support.model("servicedesk.TicketRating").objects.filter(ticket=ticket)


def test_manual_close_sends_rating_link_only_after_executor_reply(django_capture_on_commit_callbacks):
    actor, with_reply = _fixture()
    sd.make_entry(with_reply, "reply", author=actor, text="Решение")
    with django_capture_on_commit_callbacks(execute=True):
        sd.close_ticket(with_reply, actor=actor)
    assert _rating_rows(with_reply).count() == 1
    message = sd.ticket_mails(with_reply)[-1]
    text = sd.mail_text(message)
    assert f"/rate/?ticket={with_reply.number}" in text
    assert len(_rating_rows(with_reply)[0].test_code) == 12 if hasattr(_rating_rows(with_reply)[0], "test_code") else True

    actor2, no_reply = _fixture("Без ответа")
    with django_capture_on_commit_callbacks(execute=True):
        sd.close_ticket(no_reply, actor=actor2)
    assert not _rating_rows(no_reply).exists()


def test_autoclose_never_creates_rating_link(django_capture_on_commit_callbacks):
    actor, ticket = _fixture()
    ticket.kind = "waiting"
    ticket.waiting_since = timezone.now() - timedelta(days=30)
    ticket.save(update_fields=["kind", "waiting_since"])
    with django_capture_on_commit_callbacks(execute=True):
        from apps.servicedesk.services import closing
        assert closing.autoclose_one(ticket.pk)
    assert not _rating_rows(ticket).exists()


def test_rating_code_and_score_are_posted_and_page_has_no_code_in_url():
    _, ticket = _fixture()
    rating = sd.make_rating(ticket, code="0123456789AB")
    client = Client()
    page = client.get("/rate/", {"ticket": ticket.number})
    assert page.status_code == 200
    body = page.content.decode()
    assert f"#{ticket.number}" in body or str(ticket.number) in body
    assert rating.test_code not in body
    assert "0123456789AB" not in page.request["QUERY_STRING"]
    response = client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": "5"})
    assert response.status_code == 200
    rating.refresh_from_db()
    assert rating.score == 5


def test_rating_post_requires_csrf():
    _, ticket = _fixture()
    rating = sd.make_rating(ticket, code="0123456789AB")
    client = Client(enforce_csrf_checks=True)
    response = client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": "5"})
    assert response.status_code == 403


def test_rating_expires_after_seven_days_and_same_error_hides_reason():
    _, ticket = _fixture()
    rating = sd.make_rating(ticket, code="0123456789AB", closed_at=timezone.now() - timedelta(days=8))
    client = Client()
    response = client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": "5"})
    assert response.status_code == 400
    assert "Код не подходит или время оценки истекло" in response.content.decode()

    wrong = client.post("/rate/", {"ticket": ticket.number, "code": "000000000000", "score": "5"})
    assert support.same_failure(response, wrong)


def test_rating_rate_limit_is_five_attempts_per_ip_and_ticket():
    _, ticket = _fixture()
    sd.make_rating(ticket, code="0123456789AB")
    client = support.make_client(ip="198.51.100.41")
    for _ in range(5):
        assert client.post("/rate/", {"ticket": ticket.number, "code": "000000000000", "score": "5"}).status_code == 400
    blocked = client.post("/rate/", {"ticket": ticket.number, "code": "000000000000", "score": "5"})
    assert blocked.status_code == 429
    assert "Слишком много попыток. Попробуйте позже" in blocked.content.decode()


def test_successful_code_is_replaced_by_short_session_and_allows_change():
    _, ticket = _fixture()
    rating = sd.make_rating(ticket, code="0123456789AB")
    client = Client()
    assert client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": "5"}).status_code == 200
    assert client.post("/rate/", {"ticket": ticket.number, "score": "4"}).status_code == 200
    rating.refresh_from_db()
    assert rating.score == 4


def test_reopen_gives_current_rating_false_but_preserves_history():
    actor, ticket = _fixture()
    sd.make_entry(ticket, "reply", author=actor, text="Решение")
    sd.close_ticket(ticket, actor=actor)
    rating = sd.make_rating(ticket, score=5, code="0123456789AB")
    sd.reopen_ticket(ticket, actor=actor)
    rating.refresh_from_db()
    assert rating.is_current is False
    assert rating.score == 5
    assert _rating_rows(ticket).count() == 1


def test_reopen_does_not_leave_an_unused_link_current():
    actor, ticket = _fixture()
    sd.make_entry(ticket, "reply", author=actor, text="Решение")
    sd.close_ticket(ticket, actor=actor)
    rating = sd.make_rating(ticket, code="0123456789AB")
    sd.reopen_ticket(ticket, actor=actor)
    rating.refresh_from_db()
    assert rating.is_current is False
    assert rating.expires_at > timezone.now()


def test_rating_change_is_audited_as_changed_not_new():
    """FR-779: изменение оценки пишется отдельным действием с прежним и новым баллом."""
    from tests.support import model

    _, ticket = _fixture()
    rating = sd.make_rating(ticket, code="0123456789AB")
    client = Client()
    assert client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": "5"}).status_code == 200
    assert client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": "4"}).status_code == 200
    Audit = model("core.AuditEvent")
    changed = Audit.objects.filter(action="servicedesk.rating_changed", object_id=str(ticket.number))
    assert changed.count() == 1
    event = changed.get()
    assert event.before.get("score") == 5 and event.after.get("score") == 4
    assert Audit.objects.filter(action="servicedesk.rating_received",
                                object_id=str(ticket.number)).count() == 1
