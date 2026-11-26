"""Красные серверные контракты моделей среза 012 (T-12101).

Тесты намеренно проверяют ограничения базы, а не только ``full_clean``:
частичная уникальность активной строки и снимки рейтинга должны сохраняться
при конкурентной записи и прямом ORM-доступе.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Index
from django.utils import timezone

from tests import support
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db


def test_queue_rule_has_off_default_and_one_to_one_queue():
    """FR-759: у очереди одно явное правило, а новый режим по умолчанию off."""
    queue = sd.make_queue()
    Rule = model("servicedesk.QueueRule")
    rule = Rule.objects.create(queue=queue)
    assert rule.mode == "off", "режим новой очереди должен быть off"
    with pytest.raises(IntegrityError, match=""):
        with transaction.atomic():
            Rule.objects.create(queue=queue)


def test_queue_rule_rejects_unknown_mode():
    """FR-759: режим ограничен четырьмя значениями контракта."""
    rule = model("servicedesk.QueueRule")(queue=sd.make_queue(), mode="random")
    with pytest.raises(ValidationError, match="mode|режим"):
        rule.full_clean()


def test_observer_allows_removed_history_but_not_active_duplicate():
    """FR-766: активный дубль запрещён, снятая строка остаётся историей."""
    queue = sd.make_queue()
    user = support.make_employee()
    Observer = model("servicedesk.QueueObserver")
    active = Observer.objects.create(queue=queue, user=user)
    with pytest.raises(IntegrityError, match=""):
        with transaction.atomic():
            Observer.objects.create(queue=queue, user=user)
    active.removed_at = timezone.now()
    active.save(update_fields=["removed_at"])
    restored = Observer.objects.create(queue=queue, user=user)
    assert Observer.objects.filter(queue=queue, user=user).count() == 2
    assert restored.removed_at is None and active.removed_at is not None


def test_rating_has_cycle_current_score_and_token_constraints():
    """FR-771: цикл и текущая ссылка уникальны, балл — 1..5 или null, хеш уникален."""
    ticket = sd.make_ticket(queue=sd.make_queue())
    Rating = model("servicedesk.TicketRating")
    base = dict(
        ticket=ticket, cycle_number=1, closed_at_snapshot=timezone.now(),
        token_hash="a" * 64, expires_at=timezone.now() + timedelta(days=7),
    )
    Rating.objects.create(**base, score=None, is_current=True)
    for values in (
        {**base, "token_hash": "b" * 64, "score": 4, "is_current": True},
        {**base, "token_hash": "c" * 64, "score": 3, "is_current": False},
    ):
        with pytest.raises(IntegrityError, match=""):
            with transaction.atomic():
                Rating.objects.create(**values)
    invalid = Rating(**{**base, "token_hash": "d" * 64, "score": 6, "is_current": False})
    with pytest.raises(ValidationError, match="score|оцен"):
        invalid.full_clean()
    with pytest.raises(IntegrityError, match=""):
        with transaction.atomic():
            Rating.objects.create(**{**base, "ticket": sd.make_ticket(queue=sd.make_queue()),
                                     "cycle_number": 2, "token_hash": "a" * 64, "score": 1,
                                     "is_current": False})


def test_rating_preserves_reporting_snapshots_after_ticket_changes():
    """FR-771/772: снимки оценки не зависят от последующей передачи и смены справочников."""
    queue = sd.make_queue()
    assignee = support.make_employee(full_name="Снимок Исполнитель")
    ticket = sd.make_ticket(queue=queue, assignee=assignee)
    rating = sd.make_rating(ticket, score=5)
    old = (rating.queue_id, rating.queue_name, rating.assignee_id, rating.assignee_name)
    ticket.queue = sd.make_queue().unit
    ticket.assignee = support.make_employee(full_name="Другой Исполнитель")
    ticket.save(update_fields=["queue", "assignee", "updated_at"])
    rating.refresh_from_db()
    assert (rating.queue_id, rating.queue_name, rating.assignee_id, rating.assignee_name) == old


def test_task_ticket_number_is_nullable_positive_and_indexed_without_fk():
    """FR-776: слабая связь допускает null, но не ноль и не создаёт внешний ключ."""
    Task = model("tasks.Task")
    author = support.make_employee()
    task = Task.objects.create(title="Связь заявки", author=author, assignee=author, ticket_number=None)
    assert task.ticket_number is None
    invalid = Task(title="Нулевая связь", author=author, assignee=author, ticket_number=0)
    with pytest.raises(ValidationError, match="ticket_number|номер"):
        invalid.full_clean()
    names = {index.name for index in Task._meta.indexes if isinstance(index, Index)}
    assert any("ticket_number" in name for name in names), "для ticket_number нужен индекс"
    assert not any(field.name == "ticket" for field in Task._meta.fields)


def test_user_unavailable_fields_are_date_note_actor_and_timestamp():
    """FR-765: недоступность хранит дату включительно, примечание, автора и момент."""
    user = support.make_employee()
    actor = support.make_employee()
    until = timezone.localdate() + timedelta(days=1)
    sd.set_unavailable(user, until, "плановое отсутствие", actor)
    user.refresh_from_db()
    assert user.unavailable_until == until
    assert user.unavailable_note == "плановое отсутствие"
    assert user.unavailable_by_id == actor.pk
    assert user.unavailable_at is not None
