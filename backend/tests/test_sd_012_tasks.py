"""T-12106: красные серверные тесты связи заявки с задачей.

Тесты намеренно вызывают публичные сервисы, а не обходят их ORM-фикстурами:
каркас T-12009 содержит только заглушки, поэтому весь файл должен быть красным
до реализации T-12214--T-12218.
"""
import pytest
from django.utils import timezone

from tests import support, support_org
from tests.support_servicedesk import add_observer, make_queue, make_task_link, make_ticket

pytestmark = pytest.mark.django_db


def _world(*, with_tasks_use=True):
    queue = make_queue()
    roles = ("tasks.use",) if with_tasks_use else ()
    member = support.make_with_permissions(*roles)
    assignee = support.make_employee()
    observer = support.make_employee()
    outsider = support.make_employee()
    for user in (member, assignee):
        support_org.make_member(user, queue.unit)
    add_observer(queue, observer)
    ticket = make_ticket(queue=queue, subject="Настроить доступ", requester_name="Заявитель теста")
    return queue, member, assignee, observer, outsider, ticket


def _task_service():
    from apps.servicedesk.services import task_links
    return task_links


def _link_service():
    from apps.tasks.services import task_links
    return task_links


def test_task_seed_requires_can_work_and_tasks_use():
    """FR-773: observer, неучастник и сотрудник без tasks.use не получают seed."""
    _, member, _, observer, outsider, ticket = _world()
    no_use, _ = _world(with_tasks_use=False)[1:3]
    for actor in (observer, outsider, no_use):
        assert _task_service().task_seed(actor, ticket.number) is None
    assert _task_service().task_seed(member, ticket.number)["title"] == ticket.subject


def test_create_from_ticket_rechecks_access_for_direct_service_call():
    """FR-773: прямой вызов службы не может обойти can_work/tasks.use."""
    _, _, _, observer, _, ticket = _world()
    with pytest.raises(Exception):
        _link_service().create_from_ticket(observer, ticket.number)


def test_create_from_ticket_prefills_subject_link_last_requester_message_and_assignee():
    """FR-774: форма получает тему, ссылку, последнее сообщение и активного ответственного."""
    _, member, assignee, _, _, ticket = _world()
    ticket.assignee = assignee
    ticket.save(update_fields=["assignee"])
    seed = _task_service().task_seed(member, ticket.number)
    assert seed["title"] == "Настроить доступ"
    assert f"/tickets/{ticket.number}/" in seed["description"]
    assert seed["assignee"] == assignee
    task = _link_service().create_from_ticket(member, ticket.number)
    assert task.ticket_number == ticket.number
    assert task.assignee_id == assignee.pk


def test_assignee_exception_is_only_for_ticket_assignee():
    """FR-775: ответственный заявки допускается без tasks.assign, другой — нет."""
    _, member, assignee, _, outsider, ticket = _world()
    ticket.assignee = assignee
    ticket.save(update_fields=["assignee"])
    task = _link_service().create_from_ticket(member, ticket.number, assignee=assignee)
    assert task.assignee_id == assignee.pk
    with pytest.raises(Exception):
        _link_service().create_from_ticket(member, ticket.number, assignee=outsider)


def test_link_is_visible_from_both_sides_and_reads_fresh_ticket_state():
    """FR-776/NFR-740: обе стороны читают свежие тему и статус, а не снимок."""
    _, member, _, _, _, ticket = _world()
    task = _link_service().create_from_ticket(member, ticket.number)
    ticket.subject = "Новая тема"
    ticket.kind = "in_progress"
    ticket.save(update_fields=["subject", "kind"])
    assert _task_service().tasks_for(member, ticket.number)[0]["title"] == task.title
    brief = _link_service().ticket_for_task(member, task)
    assert brief["subject"] == "Новая тема"
    assert brief["kind"] == "in_progress"


def test_soft_deleted_task_disappears_without_removing_ticket_number():
    """FR-776/NFR-740: мягко удалённая задача не показывается в блоке заявки."""
    _, member, _, _, _, ticket = _world()
    task = _link_service().create_from_ticket(member, ticket.number)
    task.deleted_at = timezone.now()
    task.save(update_fields=["deleted_at"])
    assert _task_service().tasks_for(member, ticket.number) == []


def test_no_reverse_sync_and_requester_never_sees_link():
    """FR-777/FR-778: нет обратного создания/синхронизации, заявитель не видит связь."""
    _, member, _, _, _, ticket = _world()
    task = _link_service().create_from_ticket(member, ticket.number)
    task.status = "completed"
    task.save(update_fields=["status"])
    ticket.kind = "closed"
    ticket.save(update_fields=["kind"])
    assert ticket.kind == "closed" and task.status == "completed"
    assert _task_service().tasks_for(ticket.requester, ticket.number) == []
    assert not hasattr(_link_service(), "create_ticket_from_task")
