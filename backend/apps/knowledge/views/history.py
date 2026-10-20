"""История, сравнение и просмотр версий, восстановление и удаление версии (T-5214; PLAN-005, «История, версии и
сравнение»; CONTRACT-005, 10.3, 11.6).

Версии не правятся: под `/kb/<id>/versions/` три адреса — просмотр, восстановление, удаление. Страницы чтения у статьи
в корзине не-управляющему отвечают 410; POST над статьёй в корзине — 200 «Статья удалена».
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.decorators.http import require_GET, require_POST

from apps.core.views.common import is_fragment, render_page

from ..models import Article, ArticleVersion
from ..services import KnowledgeError, VersionError, access, versions
from . import articles as article_views

CONTEXT_LINES = 3


def _blocks(lines: list) -> list:
    """Строки сравнения блоками: видны изменения и по 3 неизменённые строки вокруг, остальное — свёрнутые участки."""
    count = len(lines)
    visible = [False] * count
    for index, line in enumerate(lines):
        if line.kind != "same":
            for near in range(max(0, index - CONTEXT_LINES), min(count, index + CONTEXT_LINES + 1)):
                visible[near] = True
    if not any(visible):
        return []
    blocks, index = [], 0
    while index < count:
        end = index
        while end < count and visible[end] == visible[index]:
            end += 1
        blocks.append({"fold": not visible[index], "lines": lines[index:end], "count": end - index})
        index = end
    return blocks


def _readable(request, article_id) -> Article:
    """Статья для чтения: нет или не видна — `Http404`; корзина не-управляющему — `ArticleGone` (страница 410)."""
    return access.get_for(request.user, article_id)


@login_required
@require_GET
@article_views.gone_guard
def history(request, article_id):
    article = _readable(request, article_id)
    rows = ArticleVersion.objects.filter(article=article).select_related("author").order_by("-number")
    return render_page(request, "knowledge/history.html", {"article": article, "versions": list(rows)})


def _picked(request) -> list | None:
    """Две разные отмеченные версии `v` — числа; иначе `None` (подсказка «Отметьте две версии»)."""
    raw = request.GET.getlist("v")
    if len(raw) != 2:
        return None
    try:
        first, second = int(raw[0]), int(raw[1])
    except ValueError:
        return None
    return None if first == second else [first, second]


@login_required
@require_GET
@article_views.gone_guard
def compare(request, article_id):
    article = _readable(request, article_id)
    context = {"article": article, "hint": "", "comparison": None, "blocks": []}
    picked = _picked(request)
    if picked is None:
        context["hint"] = "pick-two"
    else:
        try:
            comparison = versions.compare(article, picked[0], picked[1])
        except VersionError:
            context["hint"] = "deleted"
        else:
            context.update({"comparison": comparison, "blocks": _blocks(comparison.lines)})
    return render_page(request, "knowledge/compare.html", context)


def version_context(request, article, number: int, extra=None) -> dict:
    version = ArticleVersion.objects.filter(article=article, number=number).first()
    if version is None:
        raise Http404("Версии нет")
    user = request.user
    in_trash = article.state == Article.State.TRASH
    current = number == article.version_no
    context = {
        "article": article, "version": version, "in_trash": in_trash, "pdn": [], "notice": False,
        "can_restore": not in_trash and not current and access.can_change(user, article),
        "can_delete": not in_trash and not current and access.can_manage(user),
    }
    context.update(extra or {})
    return context


@login_required
@require_GET
@article_views.gone_guard
def version(request, article_id, number):
    article = _readable(request, article_id)
    return render_page(request, "knowledge/version.html", version_context(request, article, number))


@login_required
@require_POST
def version_restore(request, article_id, number):
    confirmed = (request.POST.getlist("confirm_pdn") or [""])[-1] == "1"
    try:
        result = versions.restore(request.user, article_id, number, confirmed)
    except access.ArticleGone:
        return article_views.gone_refusal(request, article_id)
    if result.kind == "saved":
        return article_views.done(request, f"/kb/{article_id}/", "Версия восстановлена")
    extra = {"notice": True} if result.kind == "no_changes" else {"pdn": result.pdn}
    context = version_context(request, result.article, number, extra)
    if is_fragment(request):
        return article_views.fragment_response(request, "knowledge/_restore_form.html", context)
    return render_page(request, "knowledge/version.html", context)


@login_required
@require_POST
def version_delete(request, article_id, number):
    try:
        versions.delete(request.user, article_id, number)
    except access.ArticleGone:
        return article_views.gone_refusal(request, article_id)
    except KnowledgeError as refused:
        return article_views.refusal(request, refused.code, article_id)
    return article_views.done(request, f"/kb/{article_id}/history/", "Версия удалена")
