"""Формы узлов: создать, изменить, удалить пустой (FR-101…107, FR-123; T-2231).

Формы — в слайдере `#slider-root`, подтверждение удаления — в диалоге `#dialog-root` (CONTRACT-002, § 9.8).
Отправка — обычным POST (без `hx-post`): успех — 302, отказ службы — 200 с `[role=alert]` и введёнными значениями.
Правила и журнал — в службе `org.services.structure`; здесь только разбор формы и тексты ответа.
Права проверяют декораторы (T-2230a); без права ответ 403 раньше проверки существования узла.
"""
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, is_fragment, render_page
from apps.org.models import Unit
from apps.org.services import structure as structure_service
from apps.org.services.errors import OrgError
from apps.org.views.structure import structure_page

KINDS = (("department", "Отдел"), ("team", "Команда"))
CONFIRM_REQUIRED = "Подтвердите удаление."  # дополнение 21


def _unit_options() -> list[dict]:
    """Все узлы дерева по `path` для поля «Подчиняется»; глубина показана отступом в названии."""
    return [{"id": u.pk, "label": f"{'— ' * u.depth}{u.name}"} for u in Unit.objects.order_by("path")]


def _slider_response(request, unit: Unit, extra: dict, *, status: int = 200):
    """Слайдер: фрагмент для HTMX, иначе страница «Структура» с формой в слайдере."""
    if is_fragment(request):
        response = render(request, "org/_slider.html", extra, status=status)
        response["Vary"] = "HX-Request"
        return response
    return structure_page(request, unit, extra={**extra, "slider_open": True}, status=status)


def _dialog_response(request, unit: Unit, extra: dict, *, status: int = 200):
    """Диалог: фрагмент для HTMX, иначе страница «Структура» с диалогом в `#dialog-root`."""
    if is_fragment(request):
        response = render(request, "org/_dialog.html", extra, status=status)
        response["Vary"] = "HX-Request"
        return response
    return structure_page(request, unit, extra={**extra, "dialog_open": True}, status=status)


def _parent_from(post) -> Unit:
    """Узел из поля `parent`; пустое, нечисловое и неизвестное значение — отказ с понятным текстом."""
    raw = (post.get("parent") or "").strip()
    try:
        return Unit.objects.get(pk=int(raw))
    except (ValueError, Unit.DoesNotExist):
        raise OrgError("kind_rules", "Выберите, кому подчиняется узел.") from None


def _values(unit: Unit | None, post=None, *, parent_id=None) -> dict:
    if post is not None:
        return {"kind": post.get("kind", ""), "name": post.get("name", ""),
                "description": post.get("description", ""), "parent": post.get("parent", "")}
    if unit is not None:
        return {"kind": unit.kind, "name": unit.name, "description": unit.description,
                "parent": str(unit.parent_id or "")}
    return {"kind": "department", "name": "", "description": "", "parent": str(parent_id or "")}


def _form_context(*, unit: Unit | None, values: dict, error: str = "") -> dict:
    root = unit is not None and unit.is_root
    title = "Изменить узел" if unit is not None else "Новый узел"
    action = f"/structure/{unit.pk}/edit/" if unit is not None else "/structure/new/"
    return {
        "slider_title": title, "form_name": "unit-edit" if unit is not None else "unit-new", "form_action": action,
        "unit_form": {"unit": unit, "values": values, "error": error, "kinds": KINDS,
                      "show_kind": unit is None, "show_parent": not root, "options": _unit_options()},
        "slider_close_url": f"/structure/{unit.pk}/" if unit is not None else "/structure/",
    }


@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def unit_new(request):
    """`/structure/new/` — создать узел: GET `parent` подставляет «Подчиняется»."""
    root = structure_service.root()
    if request.method == "GET":
        raw = request.GET.get("parent", "")
        parent = Unit.objects.filter(pk=int(raw)).first() if raw.isdigit() else None
        values = _values(None, parent_id=parent.pk if parent else root.pk)
        return _slider_response(request, parent or root, _form_context(unit=None, values=values))
    post = request.POST
    try:
        kind = post.get("kind", "")
        if kind not in dict(KINDS):
            raise OrgError("kind_rules", "Выберите вид узла: отдел или команда.")
        parent = _parent_from(post)
        unit = structure_service.create_unit(
            kind=kind, name=post.get("name", ""), description=post.get("description", ""), parent=parent,
            actor=request.user, ip=request.client_ip)
    except OrgError as error:
        context = _form_context(unit=None, values=_values(None, post), error=str(error))
        return _slider_response(request, root, context)
    flash(request, f"Узел «{unit.name}» создан.")
    return HttpResponseRedirect(f"/structure/{unit.pk}/")


@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def unit_edit(request, unit_id: int):
    """`/structure/<id>/edit/` — изменить узел; у корня поля «Подчиняется» нет."""
    unit = get_object_or_404(Unit.objects.select_related("parent"), pk=unit_id)
    if request.method == "GET":
        return _slider_response(request, unit, _form_context(unit=unit, values=_values(unit)))
    post = request.POST
    try:
        with transaction.atomic():
            if unit.is_root and "parent" in post:
                raise OrgError("root_protected", "Корневой отдел нельзя перенести: у него нет вышестоящего узла.")
            structure_service.update_unit(
                unit, name=post.get("name", ""), description=post.get("description", ""),
                actor=request.user, ip=request.client_ip)
            if not unit.is_root and "parent" in post:
                structure_service.move_unit(unit, _parent_from(post), actor=request.user, ip=request.client_ip)
    except OrgError as error:
        context = _form_context(unit=unit, values=_values(unit, post), error=str(error))
        return _slider_response(request, unit, context)
    flash(request, "Изменения сохранены.")
    return HttpResponseRedirect(f"/structure/{unit.pk}/")


def _delete_context(unit: Unit, error: str = "") -> dict:
    return {
        "dialog": "unit-delete", "dialog_title": f"Удалить узел «{unit.name}»?",
        "dialog_action": f"/structure/{unit.pk}/delete/", "dialog_error": error, "dialog_danger": True,
        "dialog_submit": "Удалить", "dialog_confirm": True,
        "consequences": ["Удалить можно только пустой узел: без участников и вложенных узлов.",
                         "Роли, назначенные узлу, уйдут вместе с ним; сами роли останутся.",
                         "Действие попадёт в журнал."],
    }


@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def unit_delete(request, unit_id: int):
    """`/structure/<id>/delete/` — диалог и удаление пустого узла (только с `confirm=1`)."""
    unit = get_object_or_404(Unit.objects.select_related("parent"), pk=unit_id)
    if request.method == "GET":
        return _dialog_response(request, unit, _delete_context(unit))
    if request.POST.get("confirm") != "1":
        return _dialog_response(request, unit, _delete_context(unit, CONFIRM_REQUIRED))
    try:
        structure_service.delete_unit(unit, actor=request.user, ip=request.client_ip)
    except OrgError as error:
        return _dialog_response(request, unit, _delete_context(unit, str(error)))
    flash(request, f"Узел «{unit.name}» удалён.")
    return HttpResponseRedirect("/structure/")
