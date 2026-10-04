"""Страница «Структура»: дерево и карточка узла (PLAN-002, «Страница „Структура“»; FR-108, FR-109; T-2230b).

Дерево читается одним запросом и собирается в памяти (NFR-101). Карточка узла — фрагмент HTMX или страница
целиком по одному адресу. Проверки прав стоят на представлениях (T-2230a).
"""
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.core.models import Role
from apps.core.services import files
from apps.core.services.permissions import has_permission, require_permission
from apps.core.views.common import is_fragment, render_page
from apps.org.models import Membership, Unit
from apps.org.services import structure as structure_service
from apps.org.services import unit_roles


def _fold(text: str) -> str:
    """Сравнение без учёта регистра и «е/ё»."""
    return (text or "").casefold().replace("ё", "е")


def _member_row(membership) -> dict:
    user = membership.user
    return {
        "user": user, "mark": membership.mark, "initials": files.initials(user.full_name),
        "photo_url": files.photo_url(user, 96),
    }


def _card_context(request, unit: Unit, q: str) -> dict:
    """Руководители, заместители, участники (с поиском по ФИО и должности), роли и права смотрящего."""
    rows = [_member_row(m) for m in Membership.objects.filter(unit=unit).select_related("user", "user__photo")
            .order_by("user__full_name", "user_id")]
    total = len(rows)
    everyone = rows
    needle = _fold(q.strip())
    if needle:
        rows = [r for r in rows if needle in _fold(r["user"].full_name) or needle in _fold(r["user"].position)]
    parent = None if unit.is_root else unit.parent
    can_manage = has_permission(request.user, "org.manage")
    can_roles = has_permission(request.user, "roles.manage")
    current_roles = unit_roles.roles_of(unit)
    context = {
        "unit": unit, "parent": parent, "q": q, "roles": current_roles,
        "heads": [r for r in rows if r["mark"] == "head"],
        "deputies": [r for r in rows if r["mark"] == "deputy"],
        "members": [r for r in rows if r["mark"] not in ("head", "deputy")],
        "total": total, "found": len(rows), "can_manage": can_manage, "can_roles": can_roles,
    }
    if can_manage:  # формы отметок и перенос: данные одним запросом на карточку, не на участника (T-2232)
        context["everyone"] = everyone
        context["transfer_targets"] = [
            {"id": u.pk, "label": f"{'— ' * u.depth}{u.name}"}
            for u in Unit.objects.filter(kind=unit.kind).exclude(pk=unit.pk).order_by("path")]
    if can_roles:
        chosen = {role.pk for role in current_roles}
        context["role_choices"] = [{"role": role, "checked": role.pk in chosen} for role in Role.objects.order_by("name", "pk")]
    return context


def _tree(selected: Unit, own_ids: set) -> tuple[list, int]:
    """Дерево узлов вложенными словарями за один запрос; раскрыты корень и предки выбранного узла."""
    units = list(Unit.objects.order_by("path"))
    nodes = {u.pk: {"unit": u, "children": [], "own": u.pk in own_ids,
                    "open": u.is_root or (u.pk != selected.pk and selected.path.startswith(u.path)),
                    "selected": u.pk == selected.pk} for u in units}
    top = []
    for u in units:
        (nodes[u.parent_id]["children"] if u.parent_id in nodes else top).append(nodes[u.pk])
    return top, len(units)


def structure_page(request, unit: Unit, *, extra: dict | None = None, status: int = 200, own_ids: set | None = None):
    """Полная страница «Структура»: карточка узла (`q` из запроса), дерево, свои узлы смотрящего.

    Единая точка сборки: её используют `_page` и structure_forms (слайдер и диалог на странице целиком).
    `own_ids` — уже известные свои узлы (без лишнего запроса); `extra` дополняет контекст шаблона.
    """
    if own_ids is None:
        own_ids = {ref.id for ref in structure_service.units_of(request.user)}
    top, count = _tree(unit, own_ids)
    context = {**_card_context(request, unit, request.GET.get("q", "")), "tree": top,
               "tree_only_root": count == 1, **(extra or {})}
    return render_page(request, "org/structure.html", context, status=status)


def _page(request, unit: Unit, own_ids: set):
    if is_fragment(request) and request.resolver_match.url_name == "unit":
        response = render(request, "org/_card.html", _card_context(request, unit, request.GET.get("q", "")))
        response["Vary"] = "HX-Request"
        return response
    return structure_page(request, unit, own_ids=own_ids)


@require_permission("staff.view")
@require_GET
def structure_home(request):
    """`/structure/` — дерево и карточка первого своего узла (по `path`) или корня."""
    own = structure_service.units_of(request.user)
    start = Unit.objects.select_related("parent").get(pk=own[0].id) if own else \
        Unit.objects.select_related("parent").get(is_root=True)
    return _page(request, start, {ref.id for ref in own})


@require_permission("staff.view")
@require_GET
def unit_card(request, unit_id: int):
    """`/structure/<id>/` — карточка узла; `?q=` — поиск внутри узла."""
    unit = get_object_or_404(Unit.objects.select_related("parent"), pk=unit_id)
    own = [] if is_fragment(request) else structure_service.units_of(request.user)
    return _page(request, unit, {ref.id for ref in own})
