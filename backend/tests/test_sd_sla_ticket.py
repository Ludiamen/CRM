"""T-11103: применение уровня SLA к заявке (FR-734…737, сценарий 2).

Тесты намеренно вызывают ещё не реализованный SLA-сервис через публичные
интерфейсы сервис-деска. До этапа 3 они должны быть красными.
"""
from secrets import token_hex

import pytest
from django.utils import timezone

from tests import support, support_org, support_servicedesk as sd


pytestmark = pytest.mark.django_db


def _priority(name: str):
    Priority = support.model("servicedesk.Priority")
    unique = f"{name} SLA {token_hex(3)}"
    return Priority.objects.create(name=unique, name_key=support_org.name_key(unique))


def _actor():
    return support.make_with_permissions("servicedesk.all")


def _create(*, queue, category=None, priority=None, at=None):
    from apps.servicedesk.services import tickets

    sd.configure_servicedesk(default_queue=queue)
    kwargs = {
        "channel": tickets.FORM,
        "subject": "Проверка SLA",
        "text": "Текст заявки",
        "requester_email": f"sla-{token_hex(6)}@corp.test",
        "category": category,
        "consent_at": at or timezone.now(),
    }
    if priority is not None:
        kwargs["priority"] = priority
    return tickets.create(**kwargs, at=at).ticket


def _cycle(ticket):
    return support.model("servicedesk.SlaCycle").objects.get(ticket=ticket, is_current=True)


def test_ticket_gets_sla_deadlines_and_first_cycle_from_priority_binding():
    """Критичность выбирает уровень, оба срока записываются, создаётся цикл 1."""
    priority = _priority("Критичная")
    queue = sd.make_queue()
    level = sd.make_level(reaction_minutes=60, solution_minutes=240, all_day=True)
    sd.bind_level(level, priority=priority)

    ticket = _create(queue=queue, priority=priority)

    ticket.refresh_from_db()
    cycle = _cycle(ticket)
    assert ticket.sla_id == level.pk
    assert ticket.sla_reaction_due is not None and ticket.sla_solution_due is not None
    assert cycle.number == 1 and cycle.level_id == level.pk
    assert cycle.reaction_due == ticket.sla_reaction_due
    assert cycle.solution_due == ticket.sla_solution_due


def test_ticket_uses_category_binding_when_priority_has_no_binding():
    """При отсутствии привязки критичности уровень находится по категории."""
    queue = sd.make_queue()
    category = sd.make_category(queue=queue)
    level = sd.make_level(all_day=True)
    sd.bind_level(level, category=category)

    ticket = _create(queue=queue, category=category)

    assert ticket.sla_id == level.pk
    assert ticket.sla_reaction_due is not None and ticket.sla_solution_due is not None


def test_priority_binding_wins_over_conflicting_category_binding():
    """При конфликте привязок критичность имеет приоритет над категорией."""
    queue = sd.make_queue()
    category = sd.make_category(queue=queue)
    priority = _priority("Высокая")
    category_level = sd.make_level(title="Категорийный", priority=10, all_day=True)
    priority_level = sd.make_level(title="Критичный", priority=20, all_day=True)
    sd.bind_level(category_level, category=category)
    sd.bind_level(priority_level, priority=priority)

    ticket = _create(queue=queue, category=category, priority=priority)

    assert ticket.sla_id == priority_level.pk


def test_ticket_without_binding_has_no_sla_or_deadlines():
    """Без привязки заявка остаётся без уровня и сроков."""
    queue = sd.make_queue()
    ticket = _create(queue=queue)

    ticket.refresh_from_db()
    assert ticket.sla_id is None
    assert ticket.sla_cycle_started_at is None
    assert ticket.sla_reaction_due is None and ticket.sla_solution_due is None


def test_category_change_before_first_response_recalculates_cycle_snapshot_and_due():
    """Смена категории до ответа пересчитывает уровень, снимок и оба срока."""
    queue = sd.make_queue()
    old = sd.make_category("Сеть", queue=queue)
    new = sd.make_category("Серверы", queue=queue)
    first = sd.make_level(title="Первый", reaction_minutes=60, solution_minutes=120, all_day=True)
    second = sd.make_level(title="Второй", reaction_minutes=180, solution_minutes=300, all_day=True)
    sd.bind_level(first, category=old)
    sd.bind_level(second, category=new)
    ticket = _create(queue=queue, category=old)
    actor = _actor()

    from apps.servicedesk.services import transfer

    transfer.change_category(ticket, new, actor=actor)
    ticket.refresh_from_db()
    cycle = _cycle(ticket)
    assert ticket.sla_id == second.pk and cycle.level_id == second.pk
    assert cycle.category_id == new.pk
    assert ticket.sla_reaction_due == cycle.reaction_due


def test_priority_change_before_first_response_recalculates_deadlines():
    """Смена критичности до ответа выбирает новый уровень и пересчитывает сроки."""
    queue = sd.make_queue()
    old = _priority("Обычная")
    new = _priority("Критичная")
    first = sd.make_level(title="Обычный SLA", all_day=True)
    second = sd.make_level(title="Критичный SLA", reaction_minutes=180, solution_minutes=300, all_day=True)
    sd.bind_level(first, priority=old)
    sd.bind_level(second, priority=new)
    ticket = _create(queue=queue, priority=old)
    actor = _actor()

    from apps.servicedesk.services import tickets

    tickets.update_fields(ticket, actor=actor, priority=new)
    ticket.refresh_from_db()
    assert ticket.priority_id == new.pk
    assert ticket.sla_id == second.pk and _cycle(ticket).level_id == second.pk


def test_queue_transfer_before_first_response_updates_queue_snapshot_and_deadlines():
    """Передача в другую очередь до ответа обновляет снимок очереди и сроки."""
    old_queue = sd.make_queue()
    new_queue = sd.make_queue()
    category = sd.make_category(queue=old_queue)
    level = sd.make_level(all_day=True)
    sd.bind_level(level, category=category)
    ticket = _create(queue=old_queue, category=category)
    actor = _actor()

    from apps.servicedesk.services import transfer

    transfer.transfer(ticket, new_queue.unit_id, actor=actor, reason="Передача")
    ticket.refresh_from_db()
    cycle = _cycle(ticket)
    assert ticket.queue_id == new_queue.unit_id
    assert cycle.queue_id == new_queue.unit_id
    assert cycle.reaction_due == ticket.sla_reaction_due


def test_category_change_can_create_cycle_for_ticket_created_without_sla():
    """Если уровень появился после создания, смена категории до ответа создаёт цикл 1."""
    queue = sd.make_queue()
    old = sd.make_category("Без SLA", queue=queue)
    new = sd.make_category("С SLA", queue=queue)
    ticket = _create(queue=queue, category=old)
    level = sd.make_level(all_day=True)
    sd.bind_level(level, category=new)
    actor = _actor()

    from apps.servicedesk.services import transfer

    transfer.change_category(ticket, new, actor=actor)
    ticket.refresh_from_db()
    cycle = _cycle(ticket)
    assert ticket.sla_id == level.pk
    assert cycle.number == 1 and cycle.is_current is True


def test_level_default_assignee_is_used_when_category_has_none():
    """Ответственный уровня назначается, если он участник очереди и категория без своего."""
    queue = sd.make_queue()
    assignee = support.make_employee(full_name="Исполнитель SLA")
    support_org.make_member(assignee, queue.unit)
    category = sd.make_category(queue=queue)
    level = sd.make_level(default_assignee=assignee, all_day=True)
    sd.bind_level(level, category=category)

    ticket = _create(queue=queue, category=category)

    ticket.refresh_from_db()
    assert ticket.assignee_id == assignee.pk


def test_category_default_assignee_has_priority_over_level_default():
    """Свой ответственный категории важнее ответственного уровня."""
    queue = sd.make_queue()
    category_assignee = support.make_employee(full_name="Категорийный")
    level_assignee = support.make_employee(full_name="Уровень")
    support_org.make_member(category_assignee, queue.unit)
    support_org.make_member(level_assignee, queue.unit)
    category = sd.make_category(queue=queue, default_assignee=category_assignee)
    level = sd.make_level(default_assignee=level_assignee, all_day=True)
    sd.bind_level(level, category=category)

    ticket = _create(queue=queue, category=category)

    ticket.refresh_from_db()
    assert ticket.assignee_id == category_assignee.pk


def test_nonparticipant_level_assignee_is_skipped_and_logged():
    """Ответственный уровня вне очереди не назначается, пишется not_participant."""
    queue = sd.make_queue()
    outsider = support.make_employee(full_name="Не участник")
    category = sd.make_category(queue=queue)
    level = sd.make_level(default_assignee=outsider, all_day=True)
    sd.bind_level(level, category=category)

    ticket = _create(queue=queue, category=category)

    AuditEvent = support.model("core.AuditEvent")
    event = AuditEvent.objects.filter(action="ticket.assignee_skipped",
                                      object_type="ticket", object_id=str(ticket.number)).latest("id")
    assert ticket.assignee_id is None
    assert event.after.get("reason") == "not_participant"


def test_ticket_created_before_sla_binding_does_not_get_deadlines_retroactively():
    """Появление привязки после создания не меняет уже созданную заявку."""
    queue = sd.make_queue()
    category = sd.make_category(queue=queue)
    ticket = _create(queue=queue, category=category)
    level = sd.make_level(all_day=True)
    sd.bind_level(level, category=category)

    ticket.refresh_from_db()
    assert ticket.sla_id is None
    assert ticket.sla_reaction_due is None and ticket.sla_solution_due is None
    assert not support.model("servicedesk.SlaCycle").objects.filter(ticket=ticket).exists()
