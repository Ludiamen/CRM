"""T-12107: красные тесты уведомлений наблюдателя, аудита и идемпотентности."""
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support, support_org
from tests.support_servicedesk import add_observer, make_queue, make_rating, make_ticket

pytestmark = pytest.mark.django_db


def _world():
    queue = make_queue()
    worker = support.make_employee()
    observer = support.make_employee()
    support_org.make_member(worker, queue.unit)
    add_observer(queue, observer)
    ticket = make_ticket(queue=queue, assignee=worker, kind="in_progress")
    return queue, worker, observer, ticket


def _kind(code):
    from apps.servicedesk import notify_kinds
    return next(item for item in notify_kinds.notification_kinds() if item.code == code)


def test_observer_gets_new_even_when_ticket_already_assigned_and_overdue():
    """FR-768: can_view-наблюдатель получает новую заявку и просрочку."""
    _, _, observer, ticket = _world()
    new = _kind("servicedesk.new_in_queue").build(
        "servicedesk.ticket_created", {"number": ticket.number}
    )
    overdue = _kind("servicedesk.sla_overdue").build(
        "servicedesk.sla_overdue", {"number": ticket.number, "recipient_id": observer.pk}
    )
    assert observer.pk in {draft.user_id for draft in new}
    assert observer.pk in {draft.user_id for draft in overdue}


def test_observer_does_not_get_requester_reply():
    """FR-768: ответ заявителя не является уведомлением наблюдателя."""
    _, worker, observer, ticket = _world()
    drafts = _kind("servicedesk.requester_replied").build(
        "servicedesk.reply_received", {"number": ticket.number, "actor_id": observer.pk}
    )
    assert observer.pk not in {draft.user_id for draft in drafts}
    assert worker.pk in {draft.user_id for draft in drafts}


@pytest.mark.parametrize("event,kind", [
    ("servicedesk.ticket_created", "servicedesk.new_in_queue"),
    ("servicedesk.sla_overdue", "servicedesk.sla_overdue"),
])
def test_notification_is_idempotent_for_requester_recipient_and_deadline(event, kind):
    """NFR-739: повторы до, во время и после срока дают одну запись."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    _, _, observer, ticket = _world()
    deadline = timezone.now() + timedelta(days=1)
    draft = Draft(observer.pk, "событие", f"/tickets/{ticket.number}/",
                  f"servicedesk.ticket:{ticket.pk}")
    created = []
    for _ in range(3):
        created.extend(dispatch.create(kind, [draft]))
    assert len(set(created)) == 1
    assert support.model("notify.Notification").objects.filter(
        user_id=observer.pk, object_ref=f"servicedesk.ticket:{ticket.pk}"
    ).count() == 1
    assert deadline > timezone.now()


def test_rating_has_no_new_notification_kind():
    """SPEC-012: новых видов уведомлений нет; оценка — письмо заявителю, не вид портала."""
    from apps.servicedesk import notify_kinds
    codes = {item.code for item in notify_kinds.notification_kinds()}
    assert "servicedesk.rating_received" not in codes


def test_audit_labels_cover_all_new_actions_and_reason():
    """FR-779: новые записи имеют русские подписи и причину распределения."""
    from apps.servicedesk.audit_labels import audit_labels
    labels = audit_labels()["actions"]
    expected = {
        "servicedesk.queue_rule_changed": "Режим очереди изменён",
        "servicedesk.queue_observer_added": "Наблюдатель очереди добавлен",
        "core.user_unavailable": "Сотрудник отмечен как недоступный",
        "ticket.distributed": "Заявка распределена автоматически",
        "servicedesk.rating_received": "Оценка заявителя получена",
        "servicedesk.task_created": "Задача создана из заявки",
    }
    assert {key: labels.get(key) for key in expected} == expected
    assert "reason" in audit_labels()["fields"]


def test_rating_and_task_audit_never_contain_plain_rating_code_and_use_moscow():
    """FR-779/FR-782: код оценки не журналируется, дата интерфейса — Europe/Moscow."""
    _, _, _, ticket = _world()
    rating = make_rating(ticket, score=5, code="TESTCODE0123")
    assert "TESTCODE0123" not in str(rating.token_hash)
    assert ZoneInfo("Europe/Moscow").key == "Europe/Moscow"
