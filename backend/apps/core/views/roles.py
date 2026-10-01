"""Роли и права `/roles/…` (T-247, FR-015…020): список, создание, правка набора прав флажками, удаление.

Назначение ролей сотруднику — в его карточке (`staff_actions.staff_roles`). Правила (начальные роли
неизменны и неудаляемы, назначенную роль не удалить) и журнал «было / стало» — в `services.roles`.
"""
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.models import Permission, Role
from apps.core.services import roles
from apps.core.services.permissions import require_permission

from .common import flash, render_page

LIST_URL = "/roles/"


@require_permission("roles.manage")
@require_GET
def role_list(request):
    rows = (Role.objects.annotate(holders=Count("users", distinct=True)).prefetch_related("permissions")
            .order_by("-is_builtin", "name"))
    return render_page(request, "roles/list.html", {"roles": rows})


def _form(request, role, *, action: str, title: str):
    """Общая форма создания и правки: название и флажки прав."""
    errors, name, picked = [], role.name if role else "", set(roles.permission_codes(role)) if role else set()
    if request.method == "POST":
        name, picked = request.POST.get("name", ""), set(request.POST.getlist("permissions"))
        try:
            if role is None:
                roles.create_role(name, picked, actor=request.user, ip=request.client_ip)
                flash(request, f"Роль «{name.strip()}» создана.")
            else:
                roles.update_role(role, name, picked, actor=request.user, ip=request.client_ip)
                flash(request, "Роль сохранена. Права держателей изменятся со следующего действия.")
        except roles.RoleError as error:
            errors.append(str(error))
        else:
            return HttpResponseRedirect(LIST_URL)
    context = {"role": role, "name": name, "picked": picked, "errors": errors, "action": action, "title": title,
               "permissions": Permission.objects.order_by("code")}
    return render_page(request, "roles/form.html", context)


@require_permission("roles.manage")
@require_http_methods(["GET", "POST"])
def role_new(request):
    return _form(request, None, action="/roles/new/", title="Новая роль")


@require_permission("roles.manage")
@require_http_methods(["GET", "POST"])
def role_edit(request, role_id: int):
    role = get_object_or_404(Role, pk=role_id)
    return _form(request, role, action=f"/roles/{role.pk}/", title=f"Роль «{role.name}»")


@require_permission("roles.manage")
@require_POST
def role_delete(request, role_id: int):
    role = get_object_or_404(Role, pk=role_id)
    try:
        roles.delete_role(role, actor=request.user, ip=request.client_ip)
    except roles.RoleError as error:
        flash(request, str(error), error=True)
        return HttpResponseRedirect(f"/roles/{role_id}/")
    flash(request, "Роль удалена.")
    return HttpResponseRedirect(LIST_URL)
