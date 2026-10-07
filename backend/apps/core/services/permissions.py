"""Права: объединение прав ролей с кэшем в Valkey (T-217, FR-014, FR-017, FR-018).

Ключ кэша — `perms:<id>` (с приставкой Django-кэша). При изменении ролей, их прав
и назначений ключи затронутых держателей удаляются, право действует со следующего
запроса (сценарий 12.2). Потеря Valkey ведёт лишь к пересчёту из базы.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from apps.core import events, extensions
from apps.core.models import Permission, Role, User, UserState

CACHE_SECONDS = 12 * 3600

# Пункты меню ядра (FR-018, FR-050): достаточно любого из прав в `permissions`
CORE_MENU = (
    {"permissions": ("staff.view", "accounts.manage"), "url": "/staff/", "title": "Сотрудники",
     "icon": "icons/people.html", "order": 10},
    {"permissions": ("roles.manage",), "url": "/roles/", "title": "Роли и права",
     "icon": "icons/roles.html", "order": 40},
    {"permissions": ("audit.view",), "url": "/audit/", "title": "Журнал событий",
     "icon": "icons/journal.html", "order": 50},
    {"permissions": ("settings.portal",), "url": "/settings/portal/", "title": "Настройки портала",
     "icon": "icons/gear.html", "order": 60},
    {"permissions": ("settings.security",), "url": "/settings/security/", "title": "Безопасность и политика",
     "icon": "icons/shield.html", "order": 70},
)


def _key(user_id) -> str:
    return f"perms:{user_id}"


def _role_ids(user) -> set[int]:
    ids = set(user.roles.values_list("pk", flat=True))
    for func in extensions.registered("role_sources"):
        ids.update(role.pk for role, _label in func(user))
    return ids


def permissions_of(user, *, fresh: bool = False) -> frozenset[str]:
    """Коды прав записи: права личных ролей и ролей из точки `role_sources`.

    При `fresh=True` кэш не читается и не пишется.
    """
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    if not fresh:
        cached = cache.get(_key(user.pk))
        if cached is not None:
            return frozenset(cached)
    codes = frozenset(Permission.objects.filter(roles__in=_role_ids(user)).values_list("code", flat=True).distinct())
    if not fresh:
        cache.set(_key(user.pk), sorted(codes), CACHE_SECONDS)
    return codes


def users_with(code: str) -> list[User]:
    """Неуволенные записи (заблокированные входят), у которых есть право `code`; по имени, затем по id."""
    candidates = User.objects.exclude(state=UserState.DISMISSED).order_by("full_name", "pk")
    return [user for user in candidates if code in permissions_of(user)]


def roles_by_source(user) -> list[tuple[str, list]]:
    """Роли записи по источникам: «лично», затем по группе на источник из `role_sources`."""
    groups = []
    personal = list(user.roles.order_by("name"))
    if personal:
        groups.append(("лично", personal))
    by_label: dict[str, list] = {}
    for func in extensions.registered("role_sources"):
        for role, label in func(user):
            bucket = by_label.setdefault(label, [])
            if role not in bucket:
                bucket.append(role)
    for label in sorted(by_label):
        groups.append((label, sorted(by_label[label], key=lambda r: r.name)))
    return groups


def has_permission(user, code: str) -> bool:
    return code in permissions_of(user)


def forget_users(user_ids, *, publish: bool = True) -> None:
    """Сбрасывает ключи прав держателей после фиксации (вне транзакции — сразу).

    Затем, если `publish` и список не пуст, публикует `access.changed` (подписчик видит сброшенный кэш).
    """
    ids = sorted(set(user_ids))
    if not ids:
        return
    keys = [_key(pk) for pk in ids]
    transaction.on_commit(lambda: cache.delete_many(keys))
    if publish:
        events.publish("access.changed", user_ids=ids)


def forget_all() -> None:
    """Сбрасывает ключи прав всех записей после фиксации."""
    keys = [_key(pk) for pk in User.objects.values_list("pk", flat=True)]
    transaction.on_commit(lambda: cache.delete_many(keys))
    events.publish("access.changed", user_ids=None)


def has_any_permission(user, codes) -> bool:
    return bool(permissions_of(user).intersection(codes))


def menu_for(user) -> list[dict]:
    """Пункты левого меню, доступные по правам: пункты ядра и точки `menu_items`."""
    granted = permissions_of(user)
    described = list(CORE_MENU)
    for func in extensions.registered("menu_items"):
        described.extend(func())
    items = []
    for item in described:
        # `visible` зовётся только если права нет и не больше раза за вызов
        if granted.intersection(item["permissions"]) or ("visible" in item and item["visible"](user)):
            items.append(item)
    items.sort(key=lambda item: (item["order"], item["title"]))
    result = []
    for i in items:
        entry = {"url": i["url"], "title": i["title"], "icon": i["icon"], "order": i["order"]}
        if "badge" in i:
            entry["badge"] = i["badge"](user)
        result.append(entry)
    return result


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


def require_any_permission(*codes: str):
    """Как `require_permission`, но достаточно любого из прав."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_any_permission(request.user, codes):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


class AnyPermissionRequiredMixin:
    """Миксин представления-класса: `required_permissions = ("<код>", ...)`, достаточно любого."""

    required_permissions: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not has_any_permission(request.user, self.required_permissions):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


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
    # держателей через узлы ядро не видит, поэтому сбрасываются ключи всех записей
    forget_all()

