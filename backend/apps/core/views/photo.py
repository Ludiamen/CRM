"""Фото сотрудника: выдача, загрузка, удаление (FR-132; T-2235).

Выдача отвечает пустым телом и заголовком `X-Accel-Redirect`: файл отдаёт nginx из закрытого тома (CONTRACT-002, § 8.2).
Загрузку и проверку формата делает служба `files`; постановка проверки антивирусом — после фиксации (в службе).
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import StoredFile, User
from apps.core.services import files
from apps.core.services.permissions import has_any_permission, require_permission

from .common import flash, render_page
from .me import profile_context


@login_required
@require_GET
def staff_photo(request, user_id: int, photo_id, size: int):
    """`/staff/<id>/photo/<uuid>/<512|96>/` — выдача чистого фото: `staff.view`, `accounts.manage` или сам."""
    if user_id != request.user.pk and not has_any_permission(request.user, ("staff.view", "accounts.manage")):
        raise PermissionDenied
    target = get_object_or_404(User.objects.select_related("photo"), pk=user_id)
    stored = target.photo
    if stored is None or stored.pk != photo_id or stored.status != StoredFile.Status.CLEAN or size not in files.SIZES:
        raise Http404
    response = HttpResponse(b"", content_type="image/jpeg")
    response["X-Accel-Redirect"] = f"/protected/photos/{stored.pk}-{size}.jpg"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=86400"
    return response


def _delete(request, target, back: str):
    """Удаляет фото (и ожидающую загрузку); фото нет — тихо, без события (доп. 49); уволенному тоже (ПДн)."""
    had = target.photo_id is not None or target.photo_pending_id is not None
    files.delete_photo(target, actor=request.user, ip=request.client_ip)
    if had:
        flash(request, "Фото удалено.")
    return HttpResponseRedirect(back)


@require_permission("accounts.manage")
@require_POST
def staff_photo_delete(request, user_id: int):
    """`/staff/<id>/photo/delete/` — удалить чужое фото."""
    target = get_object_or_404(User, pk=user_id)
    return _delete(request, target, f"/staff/{target.pk}/")


@login_required
@require_POST
def me_photo(request):
    """`/me/photo/` — загрузить своё фото: успех — переход на `/me/`, отказ — та же страница с `[role=alert]`."""
    uploaded = request.FILES.get("photo")
    if uploaded is None:
        error = "Выберите файл с фото."
    else:
        try:
            files.upload_photo(request.user, uploaded, actor=request.user, ip=request.client_ip)
        except files.PhotoError as caught:
            error = str(caught)
        else:
            flash(request, "Фото загружено и проверяется.")
            return HttpResponseRedirect("/me/")
    return render_page(request, "me/profile.html", {**profile_context(request.user), "errors": [error]})


@login_required
@require_POST
def me_photo_delete(request):
    """`/me/photo/delete/` — удалить своё фото."""
    return _delete(request, request.user, "/me/")
