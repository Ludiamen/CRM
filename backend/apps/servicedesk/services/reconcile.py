"""Публичный интерфейс сервис-деска: сверка ответственных (PLAN-003, «Где живёт код»).

Правило FR-235: ответственный всегда участник очереди своей заявки. Сверка снимает ответственного с заявок
(открытых и закрытых), очередь которых не среди узлов его работы, если у него нет права «Все заявки».
`assignment.clear_assignee` здесь не зовётся: у сверки своё событие ленты `assignee_reconciled` (CONTRACT-003, 9.3).
"""
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.core.services import audit

from ..models import Ticket
from . import access, events, replies
from .errors import Batch


def _reconcile_user(user_id: int) -> int:
    """Сверка одного человека; возвращает число заявок, с которых он снят."""
    # Быстрый выход: один запрос по индексу, без транзакции и без загрузки пользователя.
    if not Ticket.objects.filter(assignee_id=user_id).exists():
        return 0
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return 0
    removed = 0
    with transaction.atomic():
        access_now = access.scope(user, fresh=True)
        if access_now.has_all:
            return 0
        tickets = (Ticket.objects.select_for_update()
                   .filter(assignee_id=user_id).exclude(queue_id__in=access_now.work_units).order_by("pk"))
        for ticket in tickets:
            ticket.assignee = None
            ticket.save(update_fields=["assignee", "updated_at"])
            replies.add_event(ticket, "assignee_reconciled", actor=None,
                              data={"before": user.full_name, "before_id": user.pk})
            audit.record("ticket.assignee_removed", actor=None, object_type="ticket", object_id=str(ticket.number),
                         before={"assignee": user.full_name, "assignee_id": user.pk},
                         after={"assignee": "", "assignee_id": None, "reason": "not_participant"})
            events.assignee_changed(ticket, before_id=user.pk, after_id=None)
            removed += 1
    return removed


def for_users(user_ids) -> int:
    """Снять ответственного с заявок тех, кто перестал быть участником очереди (6.12).

    `user_ids` — итерируемое номеров или `None` (все, у кого есть заявки с ответственным). Каждый человек — в своей
    транзакции. Возвращает, сколько заявок лишилось ответственного.
    """
    if user_ids is None:
        user_ids = list(Ticket.objects.filter(assignee_id__isnull=False).order_by("assignee_id")
                        .values_list("assignee_id", flat=True).distinct())
    return sum(_reconcile_user(user_id) for user_id in user_ids)


def on_access_changed(*, user_ids) -> None:
    """Обработчик шины `access.changed`: `user_ids` — список номеров или `None` (все)."""
    for_users(user_ids)


def batch(*, after_id: int = 0, size: int = 50) -> Batch:
    """Порция людей с заявками, где они ответственные: по возрастанию `id` после `after_id`, не больше `size`."""
    ids = list(Ticket.objects.filter(assignee_id__gt=after_id).order_by("assignee_id")
               .values_list("assignee_id", flat=True).distinct()[:size])
    for_users(ids)
    return Batch(done=len(ids), more=len(ids) == size, last_id=ids[-1] if ids else None)
