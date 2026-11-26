"""Публичный интерфейс сервис-деска: видимость заявок и участники (PLAN-003, «Где живёт код»; PLAN-012).

Видеть (`can_view`) и работать (`can_work`) — разные права: наблюдатель очереди читает её заявки, но не
действует. `get_for` (заявка по номеру среди видимых или 404) живёт в `tickets` (CONTRACT-003, 6.7), не здесь.
"""
from dataclasses import dataclass

from django.db.models import Q

from apps.core.services import permissions
from apps.core.widgets import moscow_today
from apps.org.services import availability, structure
from apps.org.services.refs import PersonRef

from ..models import Queue, QueueObserver, Ticket

ALL_PERMISSION = "servicedesk.all"


@dataclass(frozen=True)
class Scope:
    """Доступ человека к заявкам: держатель «Все заявки», узлы работы и наблюдаемые очереди."""

    has_all: bool
    work_units: frozenset[int]
    observe_units: frozenset[int] = frozenset()


_NO_SCOPE = Scope(False, frozenset())


def _blocked(user) -> bool:
    """Неавторизованный и уволенный доступа не имеют."""
    return not getattr(user, "is_authenticated", False) or getattr(user, "state", None) == "dismissed"


def scope(user, *, fresh: bool = False) -> Scope:
    """Доступ `user`; считается один раз на объект пользователя (`user._sd_scope`).

    `fresh=True` считает заново, права читает мимо кэша (`permissions_of(user, fresh=True)`). Уволенный и
    неавторизованный — без доступа.
    """
    if not fresh:
        cached = getattr(user, "_sd_scope", None)
        if cached is not None:
            return cached
    if _blocked(user):
        result = _NO_SCOPE
    else:
        has_all = ALL_PERMISSION in permissions.permissions_of(user, fresh=fresh)
        observe_units = frozenset(
            QueueObserver.objects.filter(user=user, removed_at__isnull=True)
            .values_list("queue__unit_id", flat=True))
        result = Scope(has_all, structure.work_units_of(user), observe_units)
    user._sd_scope = result
    return result


def visible_tickets(user):
    """Заявки, которые `user` видит: все — у «Все заявки»; иначе работа, наблюдение и свои по ответственности."""
    if _blocked(user):
        return Ticket.objects.none()
    access = scope(user)
    if access.has_all:
        return Ticket.objects.all()
    return Ticket.objects.filter(
        Q(queue_id__in=access.work_units) | Q(queue_id__in=access.observe_units) | Q(assignee=user))


def is_participant(user, unit_id: int) -> bool:
    """Держатель «Все заявки» или узел `unit_id` среди узлов работы (не зависит от отметки очереди)."""
    access = scope(user)
    return access.has_all or unit_id in access.work_units


def can_work(user, ticket) -> bool:
    """Заявка доступна для действий: очередь работы или ответственность; без запроса к базе."""
    if _blocked(user):
        return False
    access = scope(user)
    return access.has_all or ticket.queue_id in access.work_units or (
        ticket.assignee_id is not None and ticket.assignee_id == user.pk)


def can_view(user, ticket) -> bool:
    """Заявка видна: работа, ответственность или активное наблюдение очереди; без запроса к базе."""
    if _blocked(user):
        return False
    access = scope(user)
    return can_work(user, ticket) or ticket.queue_id in access.observe_units


def is_observer(user, unit_id: int) -> bool:
    """Активный наблюдатель очереди `unit_id` (наблюдателей снятых не считаем)."""
    return not _blocked(user) and unit_id in scope(user).observe_units


def eligible_assignees(unit_id: int) -> list[PersonRef]:
    """Кандидаты в ответственные: участники очереди и «Все заявки», без уволенных, недоступных и повторов."""
    today = moscow_today()
    people = {person.id: person for person in structure.queue_people(unit_id)}
    observed = set(QueueObserver.objects.filter(queue__unit_id=unit_id, removed_at__isnull=True)
                   .values_list("user_id", flat=True))
    for holder in permissions.users_with(ALL_PERMISSION):
        people.setdefault(holder.pk, PersonRef(id=holder.pk, full_name=holder.full_name, position=holder.position))
    # Недоступность — дата включительно; после неё сотрудник снова кандидат.
    unavailable = availability.unavailable_ids(people, on_date=today)
    return sorted((person for pk, person in people.items() if pk not in unavailable and pk not in observed),
                  key=lambda person: (person.full_name, person.id))


def suggest_assignees(unit_id: int, prefix: str) -> list[PersonRef]:
    """Подсказка ответственных: из кандидатов те, чьё имя начинается с `prefix` (без регистра и «ё/е»)."""
    key = structure.name_key(prefix)
    return [person for person in eligible_assignees(unit_id) if structure.name_key(person.full_name).startswith(key)]


def menu_visible(user) -> bool:
    """Виден ли пункт меню «Заявки»: держатель «Все заявки», участник очереди или ответственный по заявке.

    Не больше двух запросов сверх `work_units_of`, число не зависит от числа заявок и очередей.
    """
    if _blocked(user):
        return False
    access = scope(user)
    if access.has_all:
        return True
    units = access.work_units | access.observe_units
    if units and Queue.objects.filter(unit_id__in=units).exists():
        return True
    return Ticket.objects.filter(assignee=user).exists()


def can_create(user) -> bool:
    """Можно ли создавать заявки: держатель «Все заявки» или участник очереди (ответственного по заявке мало)."""
    access = scope(user)
    if access.has_all:
        return True
    return bool(access.work_units) and Queue.objects.filter(unit_id__in=access.work_units).exists()
