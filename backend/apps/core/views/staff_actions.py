"""Действия над сотрудником (T-245): создание с приглашением, правка, роли, блокировка, приглашение заново,
снятие блокировки входа, сброс второго фактора (FR-001, FR-005, FR-008…010, FR-019, FR-024, FR-038).

Правила и журнал — в сервисах; здесь только разбор формы и текст ответа. Отказ правила (последний
администратор, свою запись и т. п.) показывается сообщением `[role=alert]` на странице карточки.
"""
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import Role, User
from apps.core.services import accounts, roles
from apps.core.services.permissions import require_permission

from .common import flash, render_page

CARD = "/staff/{}/"
RULE_ERRORS = (accounts.AccountError, roles.RoleError)


def _card(user_id) -> HttpResponseRedirect:
    return HttpResponseRedirect(CARD.format(user_id))


def _role_ids(values) -> list[int]:
    try:
        return [int(value) for value in values]
    except (TypeError, ValueError):
        raise roles.RoleError("Выбрана несуществующая роль.") from None


@require_permission("accounts.manage")
@require_http_methods(["GET", "POST"])
def staff_new(request):
    """Короткая форма (UX-11): почта, ФИО, должность, телефон по желанию, роли; приглашение уходит сразу."""
    form = {"email": "", "full_name": "", "position": "", "phone": "", "roles": set()}
    errors = []
    if request.method == "POST":
        post = request.POST
        form = {name: post.get(name, "").strip() for name in ("email", "full_name", "position", "phone")}
        picked = post.getlist("roles")
        form["roles"] = {str(value) for value in picked}
        try:
            user = accounts.create_user(
                email=form["email"], full_name=form["full_name"], position=form["position"], phone=form["phone"],
                role_ids=_role_ids(picked), actor=request.user, ip=request.client_ip)
        except RULE_ERRORS as error:
            errors.append(str(error))
        else:
            flash(request, f"Запись создана, приглашение отправлено на {user.email}.")
            return _card(user.pk)
    context = {"form": form, "errors": errors, "all_roles": Role.objects.order_by("name")}
    return render_page(request, "staff/new.html", context, status=200)


@require_permission("accounts.manage")
@require_POST
def staff_edit(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    fields = {name: request.POST[name] for name in accounts.PROFILE_FIELDS if name in request.POST}
    try:
        accounts.update_profile(target, actor=request.user, ip=request.client_ip, **fields)
    except RULE_ERRORS as error:
        flash(request, str(error), error=True)
    else:
        flash(request, "Профиль сохранён.")
    return _card(user_id)


@require_permission("accounts.manage")
@require_POST
def staff_roles(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    try:
        roles.set_user_roles(target, _role_ids(request.POST.getlist("roles")), actor=request.user, ip=request.client_ip)
    except RULE_ERRORS as error:
        flash(request, str(error), error=True)
    else:
        flash(request, "Роли сохранены. Права изменятся со следующего действия сотрудника.")
    return _card(user_id)


@require_permission("accounts.manage")
@require_POST
def staff_block(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    try:
        accounts.block(target, request.POST.get("reason", ""), actor=request.user, ip=request.client_ip)
    except RULE_ERRORS as error:
        flash(request, str(error), error=True)
    else:
        flash(request, "Запись заблокирована, открытые сессии закрыты.")
    return _card(user_id)


@require_permission("accounts.manage")
@require_POST
def staff_unblock(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    accounts.unblock(target, actor=request.user, ip=request.client_ip)
    flash(request, "Запись разблокирована.")
    return _card(user_id)


@require_permission("accounts.manage")
@require_POST
def staff_invite(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    try:
        accounts.resend_invitation(target, actor=request.user, ip=request.client_ip)
    except RULE_ERRORS as error:
        flash(request, str(error), error=True)
    else:
        flash(request, "Новое приглашение отправлено, прежняя ссылка не действует.")
    return _card(user_id)


@require_permission("accounts.manage")
@require_POST
def staff_unlock(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    if accounts.unlock_login(target, actor=request.user, ip=request.client_ip):
        flash(request, "Блокировка входа снята.")
    else:
        flash(request, "Вход этой записи не заблокирован.")
    return _card(user_id)


@require_permission("accounts.reset_2fa")
@require_POST
def staff_reset_2fa(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    try:
        accounts.reset_second_factor(target, actor=request.user, ip=request.client_ip)
    except RULE_ERRORS as error:
        flash(request, str(error), error=True)
    else:
        flash(request, "Второй фактор сброшен, сотруднику отправлено письмо. При следующем входе он подключит его заново.")
    return _card(user_id)
