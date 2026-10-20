"""Комментарии под статьёй: добавить, удалить (PLAN-005, «Комментарии»; CONTRACT-005, 10.5, 11.5).

Представления тонкие: служба `articles.add_comment` / `articles.delete_comment` проверяет статью, право и пишет журнал
и событие; хранение и проверку текста делает служба ядра `core.comments`. Отказ формы — всегда 200; корзина — 200
«Статья удалена»; нет статьи, черновик или нет комментария — `Http404`; чужой комментарий не-управляющему — 403.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.core.models import Comment
from apps.core.services import comments, files
from apps.core.views.common import is_fragment, render_page

from ..services import access, articles

_PREFIX = "knowledge.article:"


def _row(user, comment, can_manage: bool) -> dict:
    """Строка списка: комментарий, фото или инициалы автора, показывать ли «Удалить» (автор или управляющий)."""
    author = comment.author
    return {"comment": comment, "photo_url": files.photo_url(author, 96), "initials": files.initials(author.full_name),
            "can_delete": can_manage or comment.author_id == user.pk}


def block_context(user, article) -> dict:
    """Контекст для `knowledge/_comments.html`: строки комментариев опубликованной статьи (страница статьи, T-5214)."""
    can_manage = access.can_manage(user)
    rows = [_row(user, comment, can_manage) for comment in comments.list_for(f"{_PREFIX}{article.pk}")]
    return {"article": article, "article_id": article.pk, "comment_rows": rows}


def _page(request, context: dict):
    return render_page(request, "knowledge/comment_page.html", context)


@login_required
@require_POST
def comment_add(request, article_id):
    """Добавляет комментарий: НХ — строка и очищенная форма; отказ — форма с введённым текстом и пометкой у поля."""
    text = request.POST.get("text", "")
    try:
        comment = articles.add_comment(request.user, article_id, text)
    except access.ArticleGone:
        return _page(request, {"gone": True})
    except comments.CommentError as refusal:
        context = {"article_id": article_id, "text": text,
                   "error": {"code": refusal.code, "message": refusal.message}}
        if is_fragment(request):
            response = render(request, "knowledge/_comment_refused.html", context)
            response["Vary"] = "HX-Request"
            return response
        return _page(request, context)
    if is_fragment(request):
        context = {"article_id": article_id, "row": _row(request.user, comment, access.can_manage(request.user))}
        response = render(request, "knowledge/_comment_added.html", context)
        response["Vary"] = "HX-Request"
        return response
    return redirect(f"/kb/{article_id}/#comments")


@login_required
@require_POST
def comment_delete(request, comment_id):
    """Удаляет комментарий (автор или управляющий): НХ — пустой ответ, иначе возврат к блоку комментариев статьи."""
    found = Comment.objects.filter(pk=comment_id, object_ref__startswith=_PREFIX).values_list("object_ref", flat=True).first()
    article_id = found[len(_PREFIX):] if found else ""
    try:
        articles.delete_comment(request.user, comment_id)
    except access.ArticleGone:
        return _page(request, {"gone": True})
    if is_fragment(request):
        return HttpResponse("")
    return redirect(f"/kb/{article_id}/#comments")
