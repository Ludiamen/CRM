"""Страницы управления: корзина, срок корзины, рубрики (T-5218; PLAN-005, «Корзина и ночная очистка», «Рубрики, теги,
главная»; CONTRACT-005, 10.3, 10.4, 11.7, 12.2).

Всё — только для управляющего (`knowledge.manage`): нет права — 403. Отказ формы — 200 с сообщением у поля и введённым;
запрос HTMX получает строку рубрики или форму создания, обычный — страницу целиком.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.views.common import is_fragment, render_page

from ..models import Article
from ..services import KnowledgeError, SettingsError, access, rubrics
from ..services import settings as kb_settings
from .articles import done, fragment_response, pk_of
from .navigation import offset_of

TRASH_PAGE = 50
RUBRICS_URL = "/kb/rubrics/"
RANGE_TEXT = "Срок корзины — от 7 до 365 суток"

TEXTS = {
    "name_empty": "Введите название рубрики",
    "name_too_long": "Название не длиннее 100 знаков",
    "name_duplicate": "Рубрика с таким названием уже есть на этом уровне",
    "too_deep": "Не глубже трёх уровней",
    "depth_exceeded": "Не глубже трёх уровней",
    "parent_missing": "Выбранной рубрики больше нет",
    "parent_self": "Нельзя перенести рубрику в саму себя",
    "parent_descendant": "Нельзя перенести рубрику в её подрубрику",
    "default_immovable": "Рубрику «Общее» нельзя перенести",
    "not_empty": "Сначала перенесите подрубрики и статьи, в том числе из корзины",
    "default_undeletable": "Рубрику «Общее» нельзя удалить",
    "out_of_range": RANGE_TEXT,
}


def _require_manage(request) -> None:
    if not access.can_manage(request.user):
        raise PermissionDenied


# --- корзина ------------------------------------------------------------------------------------------------------------

@login_required
@require_GET
def trash_list(request):
    _require_manage(request)
    offset = offset_of(request)
    rows = list(Article.objects.filter(state=Article.State.TRASH).select_related("rubric", "deleted_by")
                .order_by("-deleted_at", "-pk")[offset:offset + TRASH_PAGE + 1])
    context = {"rows": rows[:TRASH_PAGE], "offset": offset,
               "next_offset": offset + TRASH_PAGE if len(rows) > TRASH_PAGE else None}
    if is_fragment(request) and "offset" in request.GET:
        return fragment_response(request, "knowledge/_trash_rows.html", context)
    return render_page(request, "knowledge/trash.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def settings(request):
    _require_manage(request)
    value = str(kb_settings.get().trash_days)
    error = None
    if request.method == "POST":
        value = request.POST.get("trash_days", "")
        try:
            kb_settings.update(request.user, value)
        except SettingsError as refused:
            error = {"code": refused.code, "text": TEXTS.get(refused.code, RANGE_TEXT)}
        else:
            return done(request, "/kb/settings/", "Срок корзины сохранён")
    return render_page(request, "knowledge/settings.html", {"value": value, "error": error})


# --- рубрики --------------------------------------------------------------------------------------------------------------

def rubric_rows() -> list:
    """Дерево плоским списком: рубрика, уровень и варианты родителя для переноса (без неё самой и её потомков)."""
    flat: list = []

    def walk(nodes, depth):
        for node in nodes:
            flat.append({"rubric": node.rubric, "depth": depth, "label": "— " * (depth - 1) + node.rubric.name})
            walk(node.children, depth + 1)

    walk(rubrics.tree(), 1)
    for index, row in enumerate(flat):
        end = index + 1
        while end < len(flat) and flat[end]["depth"] > row["depth"]:
            end += 1
        excluded = {item["rubric"].pk for item in flat[index:end]}
        row["options"] = [{"id": item["rubric"].pk, "label": item["label"],
                           "selected": item["rubric"].pk == row["rubric"].parent_id}
                          for item in flat if item["rubric"].pk not in excluded]
    return flat


def _parent_of(post):
    """Поле `parent`: пусто — корень; число — номер; не число — номер несуществующей рубрики (отказ службы)."""
    raw = post.get("parent", "").strip()
    if not raw:
        return None
    return pk_of(raw) or 0


def _page_context(*, new_form=None, row_error=None) -> dict:
    flat = rubric_rows()
    options = [{"id": item["rubric"].pk, "label": item["label"]} for item in flat]
    return {"rows": flat, "all_options": options, "new_form": new_form or {"name": "", "parent": "", "error": None},
            "row_error": row_error or {}}


def _refusal_text(refused: KnowledgeError) -> dict:
    return {"code": refused.code, "field": refused.field, "text": TEXTS.get(refused.code, "Не удалось сохранить")}


def _row_refusal(request, rubric_id: int, kind: str, refused: KnowledgeError, values: dict):
    """Отказ над строкой рубрики: ошибка только у отправленной формы этой строки."""
    context = _page_context(row_error={"id": rubric_id, "kind": kind, "values": values, **_refusal_text(refused)})
    if is_fragment(request):
        row = next(item for item in context["rows"] if item["rubric"].pk == rubric_id)
        context.update({"row": row})
        return fragment_response(request, "knowledge/_rubric_row.html", context)
    return render_page(request, "knowledge/rubrics.html", context)


@login_required
@require_GET
def rubrics_page(request):
    _require_manage(request)
    return render_page(request, "knowledge/rubrics.html", _page_context())


@login_required
@require_POST
def rubric_new(request):
    _require_manage(request)
    name, parent_raw = request.POST.get("name", ""), request.POST.get("parent", "")
    try:
        rubrics.create(request.user, name, _parent_of(request.POST))
    except KnowledgeError as refused:
        form = {"name": name, "parent": parent_raw, "error": _refusal_text(refused)}
        if is_fragment(request):
            return fragment_response(request, "knowledge/_rubric_new.html", _page_context(new_form=form))
        return render_page(request, "knowledge/rubrics.html", _page_context(new_form=form))
    return done(request, RUBRICS_URL, "Рубрика создана")


@login_required
@require_POST
def rubric_rename(request, rubric_id):
    _require_manage(request)
    name = request.POST.get("name", "")
    try:
        rubrics.rename(request.user, rubric_id, name)
    except KnowledgeError as refused:
        return _row_refusal(request, rubric_id, "rename", refused, {"name": name})
    return done(request, RUBRICS_URL, "Рубрика переименована")


@login_required
@require_POST
def rubric_move(request, rubric_id):
    _require_manage(request)
    try:
        rubrics.move(request.user, rubric_id, _parent_of(request.POST))
    except KnowledgeError as refused:
        return _row_refusal(request, rubric_id, "move", refused, {})
    return done(request, RUBRICS_URL, "Рубрика перенесена")


@login_required
@require_POST
def rubric_delete(request, rubric_id):
    _require_manage(request)
    try:
        rubrics.delete(request.user, rubric_id)
    except KnowledgeError as refused:
        return _row_refusal(request, rubric_id, "delete", refused, {})
    return done(request, RUBRICS_URL, "Рубрика удалена")
