"""Роли в отделах (PLAN-002, «Права и роли узлов»; CONTRACT-002, § 4.4).

Роль, назначенная узлу, действует на всех, кто состоит в узле или в любом его вложенном узле. Службы прав не
проверяют: это делают представления. Функции `role_sources` и `role_usage` — точки расширения ядра
(`apps.org.extensions`).
"""
from django.db import transaction
from django.db.models import Exists, OuterRef

from apps.core.models import Role
from apps.core.services import audit
from apps.core.services.permissions import forget_users
from apps.core.services.roles import ADMIN_ROLE_NAME
from apps.org.models import Membership, Unit, UnitRole
from apps.org.services.errors import OrgError
from apps.org.services.structure import lock_root

_USAGE_TEXT = "Роль назначена узлу структуры: сначала снимите её."


def roles_of(unit) -> list[Role]:
    """Роли, назначенные узлу, по названию."""
    return list(Role.objects.filter(unit_roles__unit=unit).order_by("name", "pk"))


def _resolve(roles) -> list[Role]:
    """`Role` или id -> роли из базы без повторов; несуществующая роль — `role_missing`."""
    wanted = {getattr(item, "pk", item) for item in roles}
    found = {role.pk: role for role in Role.objects.filter(pk__in=wanted)}
    if set(found) != wanted:
        raise OrgError("role_missing", "Такой роли нет: возможно, её уже удалили.")
    return list(found.values())


def set_unit_roles(unit, roles, *, actor, ip=None) -> None:
    """Заменяет набор ролей узла целиком; событие `unit.roles_changed` — только при изменении набора."""
    with transaction.atomic():
        lock_root()
        unit = Unit.objects.get(pk=unit.pk)  # путь свежий: переданный объект мог устареть после переноса
        wanted = _resolve(roles)
        if any(role.is_builtin and role.name == ADMIN_ROLE_NAME for role in wanted):
            raise OrgError("admin_role_forbidden", "Роль «Администратор портала»: администратор выдаётся только лично, узлу её назначить нельзя.")
        current = {role.pk: role for role in roles_of(unit)}
        target = {role.pk: role for role in wanted}
        if set(current) == set(target):
            return
        UnitRole.objects.filter(unit=unit).exclude(role_id__in=target).delete()
        UnitRole.objects.bulk_create([UnitRole(unit=unit, role=role) for pk, role in target.items() if pk not in current])
        audit.record(
            "unit.roles_changed", actor=actor, object_type="unit", object_id=unit.pk, ip=ip,
            before={"roles": sorted(role.name for role in current.values())},
            after={"roles": sorted(role.name for role in target.values())})
        forget_users(list(
            Membership.objects.filter(unit__path__startswith=unit.path).values_list("user_id", flat=True).distinct()))


def role_sources(user) -> list[tuple[Role, str]]:
    """Роли узлов членств `user` и всех их вышестоящих узлов — одним запросом по путям.

    Пара — (роль, «от подразделения <название узла, которому роль назначена>»); одна роль из двух узлов — две пары.
    """
    member_below = Membership.objects.filter(user=user, unit__path__startswith=OuterRef("unit__path"))
    rows = (UnitRole.objects.filter(Exists(member_below)).select_related("role", "unit")
            .order_by("unit__path", "role__name", "pk"))
    return [(row.role, f"от подразделения {row.unit.name}") for row in rows]


def role_usage(role) -> str | None:
    """Причина, по которой роль нельзя удалить: она назначена узлу; иначе `None`."""
    return _USAGE_TEXT if UnitRole.objects.filter(role=role).exists() else None
