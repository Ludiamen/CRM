"""Люди: увольнение и возврат (PLAN-002, «Где живёт код»; CONTRACT-002, § 4.3)."""
from django.db import transaction

from apps.core.services import accounts, audit
from apps.core.services.permissions import forget_users
from apps.org.models import Membership
from apps.org.services import structure


def dismiss(user, *, actor, ip=None) -> None:
    """Увольнение: замок корня, `accounts.dismiss`, затем все членства удаляются с отметками (FR-125, FR-126, FR-150).

    По событию `membership.removed` с причиной `dismissal` на узел, по возрастанию `path`. Исключения ядра идут наружу как есть;
    писем нет. Ключи прав сбрасываются после фиксации.
    """
    with transaction.atomic():
        structure.lock_root()
        accounts.dismiss(user, actor=actor, ip=ip)
        memberships = list(Membership.objects.filter(user=user).select_related("unit").order_by("unit__path", "unit_id"))
        for membership in memberships:
            audit.record("membership.removed", actor=actor, object_type="user", object_id=user.pk,
                         before={"unit": membership.unit.name, "unit_id": membership.unit_id, "mark": membership.mark,
                                 "reason": "dismissal"},
                         after=None, ip=ip)
        Membership.objects.filter(user=user).delete()
        forget_users([user.pk])


def rehire(user, *, actor, ip=None) -> None:
    """Возврат на работу: `accounts.rehire` в транзакции; подразделений у возвращённого нет (FR-128)."""
    with transaction.atomic():
        accounts.rehire(user, actor=actor, ip=ip)
        forget_users([user.pk])
