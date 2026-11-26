"""T-12109: красные серверные тесты HTTP/data-* контрактов среза 012."""
import pytest

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _queue_and_users():
    tree = org.make_tree({"ИТ": {}})
    manager = support.make_with_permissions("servicedesk.manage", "tasks.use")
    org.make_member(manager, tree["ИТ"], mark="head")
    sd.make_queue(tree["ИТ"])
    observer = support.make_employee(full_name="Наблюдатель")
    return tree["ИТ"], manager, observer


def _body(response):
    return response.content.decode("utf-8", "replace")


def test_rule_route_has_page_form_exact_modes_and_htmx_contract():
    queue, manager, _ = _queue_and_users()
    client = support.logged_in(manager)
    response = client.get(f"/servicedesk/queues/{queue.pk}/rule/")
    body = _body(response)
    assert response.status_code == 200
    assert "data-queue-rule-page" in body
    assert f'data-queue-rule="{queue.pk}"' in body
    assert 'data-form="queue-rule"' in body
    assert 'data-queue-rule-field="mode"' in body
    for mode in ("off", "evenly", "strictly", "all"):
        assert f'value="{mode}"' in body

    fragment = client.get(f"/servicedesk/queues/{queue.pk}/rule/", HTTP_HX_REQUEST="true")
    assert fragment.status_code == 200 and "data-queue-rule" in _body(fragment)


def test_rule_post_has_csrf_and_normal_redirect_or_htmx_fragment():
    queue, manager, _ = _queue_and_users()
    client = support.logged_in(manager)
    response = client.post(f"/servicedesk/queues/{queue.pk}/rule/", {"mode": "evenly"})
    assert response.status_code == 302
    fragment = client.post(f"/servicedesk/queues/{queue.pk}/rule/", {"mode": "strictly"},
                           HTTP_HX_REQUEST="true")
    assert fragment.status_code == 200
    invalid = client.post(f"/servicedesk/queues/{queue.pk}/rule/", {"mode": "bad"})
    assert invalid.status_code == 400
    assert 'data-error="mode"' in _body(invalid)
    assert 'data-code="queue_rule_mode"' in _body(invalid)


def test_observer_route_exposes_list_forms_and_mutation_does_not_change_members():
    queue, manager, observer = _queue_and_users()
    client = support.logged_in(manager)
    response = client.get(f"/servicedesk/queues/{queue.pk}/observers/")
    body = _body(response)
    assert response.status_code == 200
    assert "data-observers-page" in body
    assert "data-observer-list" in body
    assert 'data-form="observer-add"' in body
    added = client.post(f"/servicedesk/queues/{queue.pk}/observers/",
                        {"user": observer.pk}, HTTP_HX_REQUEST="true")
    assert added.status_code == 200
    assert f'data-user-id="{observer.pk}"' in _body(added)
    assert 'data-form="observer-remove"' in _body(added)
    assert not support.model("org.Membership").objects.filter(user=observer, unit=queue).exists()


def test_queue_settings_are_forbidden_outside_managed_scope():
    queue, _, _ = _queue_and_users()
    outsider = support.make_employee()
    client = support.logged_in(outsider)
    for suffix in ("rule/", "observers/"):
        response = client.get(f"/servicedesk/queues/{queue.pk}/{suffix}")
        assert response.status_code == 403
        assert "нет доступа" in _body(response)


def test_public_rating_get_post_and_csrf_contract():
    _, _, _ = _queue_and_users()
    ticket = sd.make_ticket(queue=sd.make_queue())
    rating = sd.make_rating(ticket, code="0123456789AB")
    client = support.make_client()
    response = client.get("/rate/", {"ticket": ticket.number})
    body = _body(response)
    assert response.status_code == 200
    assert 'data-rating-page' in body
    assert 'data-form="rating"' in body
    assert 'data-rating-field="code"' in body
    assert 'data-rating-field="score"' in body
    assert rating.test_code not in body
    for score in range(1, 6):
        assert f'value="{score}"' in body
    csrf_client = support.make_client(enforce_csrf_checks=True)
    denied = csrf_client.post("/rate/", {"ticket": ticket.number, "code": rating.test_code, "score": 5})
    assert denied.status_code == 403


def test_tasks_new_requires_queue_member_and_tasks_use_and_preserves_ticket_number():
    queue, manager, _ = _queue_and_users()
    ticket = sd.make_ticket(queue=queue)
    response = support.logged_in(manager).get("/tasks/new/", {"ticket": ticket.number})
    assert response.status_code == 200
    body = _body(response)
    assert 'data-task-ticket' in body or "Заявка" in body
    assert str(ticket.number) in body
    outsider = support.make_employee()
    denied = support.logged_in(outsider).get("/tasks/new/", {"ticket": ticket.number})
    assert denied.status_code in (403, 404)


def test_hidden_rating_failures_have_one_message_and_do_not_reveal_ticket():
    queue, _, _ = _queue_and_users()
    ticket = sd.make_ticket(queue=queue, subject="Скрытая тема")
    client = support.make_client()
    wrong = client.post("/rate/", {"ticket": ticket.number, "code": "000000000000", "score": 5})
    missing = client.post("/rate/", {"ticket": ticket.number + 999999, "code": "000000000000", "score": 5})
    assert wrong.status_code == missing.status_code == 400
    assert support.same_failure(wrong, missing)
    assert "Скрытая тема" not in _body(wrong)


def test_ticket_card_exposes_audit_hook_and_rating_event_signature():
    queue, manager, _ = _queue_and_users()
    ticket = sd.make_ticket(queue=queue)
    sd.make_rating(ticket, score=5)
    response = support.logged_in(manager).get(f"/tickets/{ticket.number}/")
    body = _body(response)
    assert response.status_code == 200
    assert 'data-field="rating"' in body
    assert "5/5" in body
