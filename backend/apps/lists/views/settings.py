"""Создание списка и настройка: вкладки «Основное» и «Права», удаление списка (T-6214a; PLAN-006, «Раздел и настройка
списка», «Права и видимость»; CONTRACT-006, 10.1, 10.2, 11.2, 15.4–15.5). Вкладка «Поля» — T-6214b.

Раздел закрыт — 404, раздел открыт, а настройки нет — 403 (FR-514). Отказ службы на POST — 200 со страницей, введённое
остаётся: у поля — `[data-error=<поле>][data-code=<код>]`, общий — `[role=alert][data-code=<код>]`.
"""
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import Role
from apps.core.views.common import render_page
from apps.lists.models import Access, List
from apps.lists.services import access, schema
from apps.lists.services.errors import ListsError

from .home import done

FORM_FIELDS = ("name", "description")


def _require_manage(request) -> None:
    """Раздел закрыт — 404, нет права управляющего — 403."""
    if not access.sees_section(request.user):
        raise Http404("Раздел не найден")
    if not access.can_manage(request.user):
        raise PermissionDenied


def _manage_list(request, list_id: int) -> List:
    """Список, который управляющий настраивает: не читается — 404, не управляет — 403."""
    lst = access.get_list(request.user, list_id)
    if not access.can_manage(request.user):
        raise PermissionDenied
    return lst


def _refusal(error: ListsError, fields=FORM_FIELDS) -> tuple[dict, ListsError | None]:
    """Отказ у поля формы (`errors`) или общий (`alert`)."""
    if error.field in fields:
        return {error.field: error}, None
    return {}, error


# --- новый список -----------------------------------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "POST"])
def new(request):
    """Форма нового списка; POST — список и переход на «Настройку списка» (наборов прав у нового списка нет)."""
    _require_manage(request)
    values, errors, alert = {"name": "", "description": ""}, {}, None
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in FORM_FIELDS}
        try:
            lst = schema.create_list(name=values["name"], description=values["description"], actor=request.user)
        except ListsError as refused:
            errors, alert = _refusal(refused)
        else:
            return done(request, f"/lists/{lst.pk}/settings/")
    return render_page(request, "lists/new.html", {"values": values, "errors": errors, "alert": alert})


# --- вкладка «Основное» и удаление ------------------------------------------------------------------------------------

def _main_page(request, lst: List, *, values=None, errors=None, alert=None):
    """Страница вкладки «Основное»: форма, кнопка удаления (недоступна, пока удалять нельзя) и пояснение."""
    blocker = schema.can_delete_list(lst)
    context = {"lst": lst, "tab": "main", "values": values or {"name": lst.name, "description": lst.description},
               "errors": errors or {}, "alert": alert, "delete_reason": blocker.message if blocker else ""}
    return render_page(request, "lists/settings_main.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def main(request, list_id: int):
    """Название и описание списка (`lists.list_changed`); успех — 302 на тот же адрес."""
    lst = _manage_list(request, list_id)
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in FORM_FIELDS}
        try:
            schema.update_list(lst, name=values["name"], description=values["description"], actor=request.user)
        except ListsError as refused:
            errors, alert = _refusal(refused)
            return _main_page(request, lst, values=values, errors=errors, alert=alert)
        return done(request, f"/lists/{lst.pk}/settings/")
    return _main_page(request, lst)


@login_required
@require_POST
def delete(request, list_id: int):
    """Удаляет пустой список; отказ (`list_has_records`, `list_referenced`) — 200 со страницей «Основное» и общим
    отказом; успех — 302 на `/lists/`."""
    lst = _manage_list(request, list_id)
    try:
        schema.delete_list(lst, actor=request.user)
    except ListsError as refused:
        return _main_page(request, lst, alert=refused)
    return done(request, "/lists/")


# --- вкладка «Права» --------------------------------------------------------------------------------------------------

def _pairs(values) -> list[tuple[str, int]]:
    """`role:<id>` и `unit:<id>` из формы -> пары; всё иное — 404 (как неизвестный субъект в службе)."""
    result = []
    for value in values:
        kind, _, pk = str(value).partition(":")
        if kind not in ("role", "unit") or not (pk.isascii() and pk.isdigit()):
            raise Http404("Субъект не найден")
        result.append((kind, int(pk)))
    return result


def _subjects(lst: List, level: str) -> list[dict]:
    """Строки набора: значение `role:<id>` или `unit:<id>`, название, вид; по названию без учёта регистра."""
    rows = list(Access.objects.filter(list=lst, level=level))
    roles = {role.pk: role.name for role in Role.objects.filter(pk__in=[r.role_id for r in rows if r.role_id])}
    refs = {}
    unit_ids = [r.unit_id for r in rows if r.unit_id]
    if unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure

        refs = structure.unit_refs(unit_ids)
    items = []
    for row in rows:
        if row.role_id:
            items.append({"value": f"role:{row.role_id}", "name": roles.get(row.role_id, ""), "kind": "role"})
        else:
            name = refs[row.unit_id].name if row.unit_id in refs else f"узел №{row.unit_id}"
            items.append({"value": f"unit:{row.unit_id}", "name": name, "kind": "unit"})
    return sorted(items, key=lambda item: (item["name"].casefold(), item["value"]))


def _access_page(request, lst: List, *, sets=None, alert=None):
    """Страница вкладки «Права»: наборы «Читают» и «Правят», выбор ролей; подразделения — подсказка `/lists/units/`."""
    sets = sets or {"read": _subjects(lst, Access.Level.READ), "edit": _subjects(lst, Access.Level.EDIT)}
    context = {"lst": lst, "tab": "access", "alert": alert, "roles": list(Role.objects.order_by("name", "pk")),
               "boxes": [{"level": "read", "title": "Читают", "field": "readers", "items": sets["read"]},
                         {"level": "edit", "title": "Правят", "field": "editors", "items": sets["edit"]}]}
    return render_page(request, "lists/settings_access.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def access_tab(request, list_id: int):
    """Наборы «Читают» и «Правят» (роли и подразделения); успех — 302 на тот же адрес."""
    lst = _manage_list(request, list_id)
    if request.method == "POST":
        readers, editors = request.POST.getlist("readers"), request.POST.getlist("editors")
        try:
            schema.save_access(lst, readers=_pairs(readers), editors=_pairs(editors), actor=request.user)
        except ListsError as refused:
            sets = {"read": _typed(readers), "edit": _typed(editors)}
            return _access_page(request, lst, sets=sets, alert=refused)
        return done(request, f"/lists/{lst.pk}/settings/access/")
    return _access_page(request, lst)


def _typed(values) -> list[dict]:
    """Присланные значения наборов как строки для повторного показа формы после отказа (названия — из базы)."""
    result = []
    for kind, pk in _pairs(values):
        if kind == "role":
            role = Role.objects.filter(pk=pk).first()
            result.append({"value": f"role:{pk}", "name": role.name if role else "", "kind": "role"})
        else:
            result.append({"value": f"unit:{pk}", "name": f"узел №{pk}", "kind": "unit"})
    return result
