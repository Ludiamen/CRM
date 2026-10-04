"""Фото сотрудника: выдача, загрузка, удаление (FR-132; T-2234).

Пока заглушки (T-2230a): проверки входа и прав окончательные, с правом ответ — 404; тело заменяет T-2234.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.decorators.http import require_GET, require_POST

from apps.core.services.permissions import has_any_permission, require_permission


@login_required
@require_GET
def staff_photo(request, user_id: int, photo_id, size: int):
    """`/staff/<id>/photo/<uuid>/<512|96>/` — выдача чистого фото: `staff.view`, `accounts.manage` или сам."""
    if user_id != request.user.pk and not has_any_permission(request.user, ("staff.view", "accounts.manage")):
        raise PermissionDenied
    raise Http404


@require_permission("accounts.manage")
@require_POST
def staff_photo_delete(request, user_id: int):
    """`/staff/<id>/photo/delete/` — удалить чужое фото."""
    raise Http404


@login_required
@require_POST
def me_photo(request):
    """`/me/photo/` — загрузить своё фото."""
    raise Http404


@login_required
@require_POST
def me_photo_delete(request):
    """`/me/photo/delete/` — удалить своё фото."""
    raise Http404
