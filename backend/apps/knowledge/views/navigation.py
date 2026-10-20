"""Страницы навигации: главная, рубрика с подпиской, тег и подсказка тегов (T-5218; PLAN-005, «Рубрики, теги,
главная»; CONTRACT-005, 10.2, 10.4, 11.2).

Списки статей — только опубликованные (корзина и черновики не входят). Запрос HTMX с `offset` получает только строки
(и кнопку «Показать ещё»), обычный — полную страницу.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from apps.core.views.common import is_fragment, render_page

from ..models import Article, Rubric, RubricSubscription
from ..services import access, rubrics, subscriptions, tags
from .articles import fragment_response, int_of, rubric_path

PAGE_SIZE = 20
NEW_AND_CHANGED = 10
DRAFTS_LIMIT = 20  # «Мои черновики» и «Черновики»: не больше 20 строк (CONTRACT-005, раздел 17 п. 54)


def plural_articles(number: int) -> str:
    """«1 статья», «2 статьи», «5 статей»; 11–14 и 111 — «статей» (решение 15)."""
    last, two = number % 10, number % 100
    if last == 1 and two != 11:
        word = "статья"
    elif 2 <= last <= 4 and not 12 <= two <= 14:
        word = "статьи"
    else:
        word = "статей"
    return f"{number} {word}"


def offset_of(request) -> int:
    return max(int_of(request.GET.get("offset"), 0), 0)


def not_found(request):
    return render_page(request, "knowledge/not_found.html", {}, status=404)


def list_response(request, queryset, page_template: str, context: dict):
    """Порция списка: `PAGE_SIZE` строк с `offset`; «Показать ещё» — если есть следующая порция."""
    offset = offset_of(request)
    rows = list(queryset.select_related("rubric").prefetch_related("tags")[offset:offset + PAGE_SIZE + 1])
    more = len(rows) > PAGE_SIZE
    context = {**context, "show_tags": True, "rows": rows[:PAGE_SIZE], "next_offset": offset + PAGE_SIZE if more else None,
               "more_path": request.path, "more_query": context.get("more_query", "")}
    if is_fragment(request) and "offset" in request.GET:
        return fragment_response(request, "knowledge/_list_rows.html", context)
    return render_page(request, page_template, context)


# --- главная ------------------------------------------------------------------------------------------------------------

def tree_rows(counts: dict) -> list:
    """Дерево рубрик плоским списком в порядке обхода: рубрика, уровень, число статей вместе с подрубриками."""
    out: list = []

    def walk(nodes, depth):
        total = 0
        for node in nodes:
            row = {"rubric": node.rubric, "depth": depth, "count": 0}
            out.append(row)
            own = counts.get(node.rubric.pk, 0) + walk(node.children, depth + 1)
            row["count"] = own
            row["count_text"] = plural_articles(own)
            total += own
        return total

    walk(rubrics.tree(), 1)
    return out


@login_required
@require_GET
def home(request):
    user = request.user
    published = Article.objects.filter(state=Article.State.PUBLISHED)
    counts = dict(published.values_list("rubric_id").annotate(n=Count("pk")))
    new_and_changed = list(published.select_related("rubric").order_by("-updated_at", "-pk")[:NEW_AND_CHANGED])
    drafts = Article.objects.filter(state=Article.State.DRAFT).select_related("rubric").order_by("-updated_at", "-pk")
    manager, editor = access.can_manage(user), access.can_edit(user)
    context = {
        "tree": tree_rows(counts), "new_and_changed": new_and_changed, "empty": not counts,
        "can_edit": editor, "can_manage": manager,
        "my_drafts": list(drafts.filter(author_id=user.pk)[:DRAFTS_LIMIT]) if editor else None,
        "all_drafts": list(drafts[:DRAFTS_LIMIT]) if manager else None,
    }
    return render_page(request, "knowledge/home.html", context)


# --- рубрика и подписка ---------------------------------------------------------------------------------------------------

def _subtree_ids(rubric_id: int) -> list | None:
    """Номера рубрики и всех её подрубрик (дерево — в памяти); `None` — рубрики нет."""
    def find(nodes):
        for node in nodes:
            if node.rubric.pk == rubric_id:
                return node
            found = find(node.children)
            if found is not None:
                return found
        return None

    def collect(node, out):
        out.append(node.rubric.pk)
        for child in node.children:
            collect(child, out)
        return out

    node = find(rubrics.tree())
    return None if node is None else collect(node, [])


@login_required
@require_GET
def rubric_page(request, rubric_id):
    ids = _subtree_ids(rubric_id)
    if ids is None:
        return not_found(request)
    queryset = Article.objects.filter(state=Article.State.PUBLISHED, rubric_id__in=ids).order_by("-updated_at", "-pk")
    context = {"rubric": Rubric.objects.get(pk=rubric_id), "path": rubric_path(rubric_id),
               "subscribed": RubricSubscription.objects.filter(user=request.user, rubric_id=rubric_id).exists()}
    return list_response(request, queryset, "knowledge/rubric.html", context)


@login_required
@require_POST
def rubric_subscribe(request, rubric_id):
    """Подписаться / отписаться (только сам сотрудник; поля запроса игнорируются)."""
    subscribed = subscriptions.toggle(request.user, rubric_id)
    if is_fragment(request):
        return fragment_response(request, "knowledge/_subscribe.html",
                                 {"rubric": {"pk": rubric_id}, "subscribed": subscribed})
    return redirect(f"/kb/rubrics/{rubric_id}/")


# --- теги -----------------------------------------------------------------------------------------------------------------

@login_required
@require_GET
def tag_page(request):
    name = " ".join(request.GET.get("name", "").split()).lower()
    if not name:
        return not_found(request)
    queryset = Article.objects.filter(state=Article.State.PUBLISHED, tags__name=name).order_by("-updated_at", "-pk")
    offset = offset_of(request)
    if offset == 0 and not queryset.exists():
        return not_found(request)
    from urllib.parse import quote
    return list_response(request, queryset, "knowledge/tag.html",
                         {"tag_name": name, "more_query": "name=" + quote(name, safe="") + "&"})


@login_required
@require_GET
def tag_suggest(request):
    if not access.can_edit(request.user):
        raise PermissionDenied
    return fragment_response(request, "knowledge/_tag_suggest.html", {"names": tags.suggest(request.GET.get("q", ""))})
