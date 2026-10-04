"""Роли и назначения (T-218, FR-015…017, FR-019, FR-020, FR-044).

Начальные роли (три) удалить нельзя, название их неизменно, набор прав правится.
Роль, назначенную хоть кому-то, не удалить. Последнему администратору нельзя снять
роль «Администратор портала» (и нельзя его заблокировать — см. `accounts.block`).
Кэш прав держателей сбрасывают сигналы на изменении ролей и назначений.
"""
from django.db import transaction

from apps.core import extensions
from apps.core.models import Permission, Role, User, UserState

from . import audit

ADMIN_ROLE_NAME = "Администратор портала"
MAX_NAME_LENGTH = 100


class RoleError(Exception):
    """Нарушено правило ролей; текст — для человека."""


def admin_role() -> Role | None:
    return Role.objects.filter(is_builtin=True, name=ADMIN_ROLE_NAME).first()


def permission_codes(role: Role) -> list[str]:
    return sorted(role.permissions.values_list("code", flat=True))


def is_active_admin(user) -> bool:
    return user.state == UserState.ACTIVE and user.roles.filter(is_builtin=True, name=ADMIN_ROLE_NAME).exists()


def guard_last_admin(user, *, action: str) -> None:
    """Бросает RoleError, если `user` — последний активный администратор."""
    if not is_active_admin(user):
        return
    others = User.objects.filter(state=UserState.ACTIVE, roles__is_builtin=True, roles__name=ADMIN_ROLE_NAME).exclude(pk=user.pk)
    if not others.exists():
        raise RoleError(f"Это последний администратор портала: {action} нельзя.")


def _clean(name: str, codes, *, role: Role | None = None) -> tuple[str, list[str]]:
    name = (name or "").strip()
    if not name:
        raise RoleError("Название роли не может быть пустым.")
    if len(name) > MAX_NAME_LENGTH:
        raise RoleError(f"Название роли: не больше {MAX_NAME_LENGTH} символов.")
    clash = Role.objects.filter(name__iexact=name)
    if role is not None:
        clash = clash.exclude(pk=role.pk)
    if clash.exists():
        raise RoleError("Роль с таким названием уже есть.")
    codes = sorted(set(codes or []))
    unknown = set(codes) - set(Permission.objects.filter(code__in=codes).values_list("code", flat=True))
    if unknown:
        raise RoleError("Неизвестные права: " + ", ".join(sorted(unknown)) + ".")
    return name, codes


def create_role(name: str, codes, *, actor, ip=None) -> Role:
    name, codes = _clean(name, codes)
    with transaction.atomic():
        role = Role.objects.create(name=name, is_builtin=False)
        role.permissions.set(Permission.objects.filter(code__in=codes))
        audit.record("role.created", actor=actor, object_type="role", object_id=role.pk,
                     after={"name": name, "permissions": codes}, ip=ip)
    return role


def update_role(role: Role, name: str, codes, *, actor, ip=None) -> Role:
    if role.is_builtin:
        name = role.name  # названия начальных ролей неизменны
    name, codes = _clean(name, codes, role=role)
    with transaction.atomic():
        before = {"name": role.name, "permissions": permission_codes(role)}
        role.name = name
        role.save(update_fields=["name"])
        role.permissions.set(Permission.objects.filter(code__in=codes))
        audit.record("role.updated", actor=actor, object_type="role", object_id=role.pk,
                     before=before, after={"name": name, "permissions": codes}, ip=ip)
    return role


def delete_role(role: Role, *, actor, ip=None) -> None:
    if role.is_builtin:
        raise RoleError("Начальную роль удалить нельзя.")
    if role.users.exists():
        raise RoleError("Роль назначена сотрудникам: сначала снимите её.")
    for func in extensions.registered("role_usage"):
        reason = func(role)
        if reason:
            raise RoleError(reason)
    with transaction.atomic():
        before = {"name": role.name, "permissions": permission_codes(role)}
        pk = role.pk
        role.delete()
        audit.record("role.deleted", actor=actor, object_type="role", object_id=pk, before=before, ip=ip)


def set_user_roles(user: User, roles, *, actor, ip=None) -> None:
    """Заменяет роли сотрудника; снять роль администратора с последнего администратора нельзя."""
    new_ids = {role.pk if isinstance(role, Role) else int(role) for role in roles}
    new_roles = list(Role.objects.filter(pk__in=new_ids))
    if len(new_roles) != len(new_ids):
        raise RoleError("Выбрана несуществующая роль.")
    with transaction.atomic():
        current = list(user.roles.order_by("name"))
        admin = admin_role()
        if admin is not None and admin in current and admin.pk not in new_ids:
            guard_last_admin(user, action="снять с него роль")
        user.roles.set(new_roles)
        audit.record("role.assigned", actor=actor, object_type="user", object_id=user.pk,
                     before={"roles": [r.name for r in current]},
                     after={"roles": sorted(r.name for r in new_roles)}, ip=ip)
