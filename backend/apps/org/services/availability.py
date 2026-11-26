"""Недоступность сотрудника для автораспределения заявок (SPEC-012, FR-765).

Сам сотрудник и администратор меняют отметку через `core.services.accounts.set_availability`; руководитель
узла, где сотрудник состоит, проверяется здесь и вызывает ту же службу с `allow_head=True`.
"""
import datetime

from apps.core.models import User
from apps.core.services import accounts
from apps.core.widgets import moscow_today
from apps.org.services import structure


def is_unavailable(user: User, on_date: datetime.date | None = None) -> bool:
    """Недоступен ли `user` на дату (по умолчанию сегодня по Москве); дата включительно."""
    until = getattr(user, "unavailable_until", None)
    return until is not None and until >= (on_date or moscow_today())


def unavailable_ids(ids, on_date: datetime.date | None = None) -> set[int]:
    """Номера недоступных сотрудников из `ids` на дату; один запрос."""
    wanted = list(ids)
    if not wanted:
        return set()
    return set(User.objects.filter(pk__in=wanted, unavailable_until__gte=on_date or moscow_today())
               .values_list("pk", flat=True))


def can_set_for(actor: User, target: User) -> bool:
    """Руководитель или заместитель узла, где состоит `target`; уволенный руководитель не считается."""
    if getattr(actor, "state", None) == "dismissed":
        return False
    return bool(structure.managed_units(actor) & {unit.id for unit in structure.units_of(target)})


def set_for_head(actor: User, target: User, until, note: str = "", ip=None) -> User:
    """Отметка недоступности руководителем узла; права проверяются здесь, запись — общей службой ядра."""
    if not (actor.pk == target.pk or can_set_for(actor, target)):
        raise accounts.AccountError("Отметить недоступность может сам сотрудник, администратор или руководитель узла.")
    return accounts.set_availability(target, until, note, actor=actor, ip=ip, allow_head=True)
