"""Участники узла, руководители, роли узла (FR-110…114, FR-120…121; T-2232).

Формы карточки узла — обычный POST без `hx-post`: успех — сообщение и 302 на карточку, отказ службы — 200 с
`[role=alert]` и страницей карточки целиком (CONTRACT-002, § 8.3, дополнения 51, 54). Правила и журнал — в службах
`org.services`; здесь разбор формы и тексты ответа. Права проверяют декораторы (T-2230a).
"""
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import User
from apps.core.services import accounts
from apps.core.services.permissions import require_permission
from apps.core.views.common import flash
from apps.org.models import Membership, Unit
from apps.org.services import membership
from apps.org.services import unit_roles as unit_roles_service
from apps.org.services.errors import OrgError
from apps.org.views.structure import structure_page

CANDIDATES_LIMIT = 20  # решение Opus, CONTRACT-002, дополнение 2


def _unit(unit_id: int) -> Unit:
    return get_object_or_404(Unit.objects.select_related("parent"), pk=unit_id)


def _ids(values) -> list[int]:
    """Числовые id из повторяющегося поля формы; нечисловое значение — отказ с понятным текстом."""
    try:
        return [int(value) for value in values]
    except (TypeError, ValueError):
        raise OrgError("bad_input", "Не удалось разобрать выбор: обновите страницу и повторите.") from None


def _users(values) -> list[User]:
    ids = _ids(values)
    found = list(User.objects.filter(pk__in=ids))
    if len(found) != len(set(ids)):
        raise OrgError("user_missing", "Сотрудника нет в списке: возможно, запись уже удалили.")
    return found


def _back(unit: Unit):
    return HttpResponseRedirect(f"/structure/{unit.pk}/")


def _refused(request, unit: Unit, error: OrgError):
    """Отказ службы: 200, страница карточки целиком с `[role=alert]`."""
    return structure_page(request, unit, extra={"card_error": str(error)})


@require_permission("org.manage")
@require_GET
def candidates(request, unit_id: int):
    """`/structure/<id>/candidates/` — подсказки людей для узла: не больше 20, уволенных нет."""
    unit = _unit(unit_id)
    found = list(accounts.pickable(request.GET.get("q", ""))[:CANDIDATES_LIMIT])
    already = set(Membership.objects.filter(unit=unit, user__in=found).values_list("user_id", flat=True)) if found else set()
    response = render(request, "org/_candidates.html", {"unit": unit, "candidates": found, "already": already})
    response["Vary"] = "HX-Request"
    return response


@require_permission("org.manage")
@require_POST
def members_add(request, unit_id: int):
    """`/structure/<id>/members/` — добавить участников; у отдела обязателен режим."""
    unit = _unit(unit_id)
    try:
        users = _users(request.POST.getlist("users"))
        if not users:
            raise OrgError("nobody", "Выберите хотя бы одного сотрудника.")
        mode = request.POST.get("mode") if unit.kind == Unit.Kind.DEPARTMENT else None
        result = membership.add_members(unit, users, mode=mode, actor=request.user, ip=request.client_ip)
    except Unit.DoesNotExist:
        raise Http404 from None
    except OrgError as error:
        return _refused(request, unit, error)
    if result.added:
        verb = "Переведено: " if mode == membership.TRANSFER else "Добавлено: "
        flash(request, verb + ", ".join(u.full_name for u in result.added) + ".")
    if result.already:
        flash(request, "Уже участник узла: " + ", ".join(u.full_name for u in result.already) + ". Ничего не изменено.", info=True)
    return _back(unit)


@require_permission("org.manage")
@require_POST
def member_transfer(request, unit_id: int, user_id: int):
    """`/structure/<id>/members/<user_id>/transfer/` — перевести в другой узел того же вида."""
    unit = _unit(unit_id)
    user = get_object_or_404(User, pk=user_id)
    try:
        (target_id,) = _ids([request.POST.get("target")])
        target = Unit.objects.filter(pk=target_id).first()
        if target is None:
            raise OrgError("unit_missing", "Выберите узел, в который перевести сотрудника.")
        done = membership.transfer_member(user, unit, target, actor=request.user, ip=request.client_ip)
    except Unit.DoesNotExist:
        raise Http404 from None
    except OrgError as error:
        return _refused(request, unit, error)
    if done:
        flash(request, f"{user.full_name} переведён в «{target.name}».")
    else:
        flash(request, f"{user.full_name} уже участник узла «{target.name}»: ничего не изменено.", info=True)
    return _back(unit)


@require_permission("org.manage")
@require_POST
def member_remove(request, unit_id: int, user_id: int):
    """`/structure/<id>/members/<user_id>/remove/` — удалить из узла."""
    unit = _unit(unit_id)
    user = get_object_or_404(User, pk=user_id)
    try:
        membership.remove_member(user, unit, actor=request.user, ip=request.client_ip)
    except OrgError as error:
        return _refused(request, unit, error)
    flash(request, f"{user.full_name} удалён из узла «{unit.name}».")
    return _back(unit)


@require_permission("org.manage")
@require_POST
def marks(request, unit_id: int):
    """`/structure/<id>/marks/` — руководители или заместители из участников; другой набор не меняется."""
    unit = _unit(unit_id)
    part = request.POST.get("part")
    try:
        if part not in ("heads", "deputies"):
            raise OrgError("bad_input", "Не удалось определить, какой набор менять: обновите страницу и повторите.")
        users = _users(request.POST.getlist("users"))
        membership.set_marks(unit, **{part: users}, actor=request.user, ip=request.client_ip)
    except Unit.DoesNotExist:
        raise Http404 from None
    except OrgError as error:
        return _refused(request, unit, error)
    flash(request, "Руководители сохранены." if part == "heads" else "Заместители сохранены.")
    return _back(unit)


@require_permission("roles.manage")
@require_POST
def unit_roles(request, unit_id: int):
    """`/structure/<id>/roles/` — заменить набор ролей узла."""
    unit = _unit(unit_id)
    try:
        unit_roles_service.set_unit_roles(unit, _ids(request.POST.getlist("roles")), actor=request.user, ip=request.client_ip)
    except Unit.DoesNotExist:
        raise Http404 from None
    except OrgError as error:
        return _refused(request, unit, error)
    flash(request, "Роли узла сохранены.")
    return _back(unit)
