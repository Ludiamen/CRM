"""Права: объединение прав ролей с кэшем в Valkey (T-217, FR-014, FR-017, FR-018).

Ключ кэша — `perms:<id>` (с приставкой Django-кэша). При изменении ролей, их прав
и назначений ключи затронутых держателей удаляются, право действует со следующего
запроса (сценарий 12.2). Потеря Valkey ведёт лишь к пересчёту из базы.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from apps.core.models import Permission, Role, User

CACHE_SECONDS = 12 * 3600

# Разделы меню и право, которое их открывает (FR-018, FR-050)
MENU = (
    ("accounts.manage", "/staff/", "Сотрудники"),
    ("roles.manage", "/roles/", "Роли и права"),
    ("audit.view", "/audit/", "Журнал событий"),
    ("settings.portal", "/settings/portal/", "Настройки портала"),
    ("settings.security", "/settings/security/", "Безопасность и политика"),
)


def _key(user_id) -> str:
    return f"perms:{user_id}"


def permissions_of(user) -> frozenset[str]:
    """Коды прав записи: объединение прав всех её ролей."""
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    cached = cache.get(_key(user.pk))
    if cached is not None:
        return frozenset(cached)
    codes = frozenset(Permission.objects.filter(roles__users=user).values_list("code", flat=True).distinct())
    cache.set(_key(user.pk), sorted(codes), CACHE_SECONDS)
    return codes


def has_permission(user, code: str) -> bool:
    return code in permissions_of(user)


def forget_users(user_ids) -> None:
    cache.delete_many([_key(pk) for pk in user_ids])


def menu_for(user) -> list[dict]:
    """Пункты левого меню, доступные по правам."""
    granted = permissions_of(user)
    return [{"permission": code, "url": url, "title": title} for code, url, title in MENU if code in granted]


def require_permission(code: str):
    """Декоратор представления: без входа — на страницу входа, без права — 403."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_permission(request.user, code):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


class PermissionRequiredMixin:
    """Миксин представления-класса: `required_permission = "<код>"`."""

    required_permission: str = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not has_permission(request.user, self.required_permission):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


@receiver(m2m_changed, sender=User.roles.through, dispatch_uid="core-perms-user-roles")
def _user_roles_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if not action.startswith(("post_", "pre_clear")):
        return
    if reverse:  # изменили role.users
        holders = list(instance.users.values_list("pk", flat=True)) + list(pk_set or [])
        forget_users(holders)
    else:
        forget_users([instance.pk])


@receiver(m2m_changed, sender=Role.permissions.through, dispatch_uid="core-perms-role-permissions")
def _role_permissions_changed(sender, instance, action, reverse, pk_set, **kwargs):
    if not action.startswith(("post_", "pre_clear")):
        return
    if reverse:  # изменили permission.roles
        roles = Role.objects.filter(pk__in=list(instance.roles.values_list("pk", flat=True)) + list(pk_set or []))
    else:
        roles = Role.objects.filter(pk=instance.pk)
    forget_users(list(User.objects.filter(roles__in=roles).values_list("pk", flat=True)))

