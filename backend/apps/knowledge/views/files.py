"""Файлы статьи: вложить, скачать, удалить, показать картинку (T-5210; CONTRACT-005, 10.5).

Право на статью проверяется на каждый запрос (FR-409). Выдача файла и картинки недоступной статьи отвечает как
несуществующая (404, не 410 и не заглушка).
"""
import pathlib

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.core.services import file_response
from apps.core.views.common import is_fragment, render_page
from apps.knowledge.models import Article, ArticleFile
from apps.knowledge.services import FileRefused, access
from apps.knowledge.services import files as file_service

REFUSALS = {
    "too_big": "Файл больше 20 МБ",
    "executable": "Исполняемые файлы не принимаются",
    "encrypted": "Архивы с паролем не принимаются",
    "limit_20": "У статьи уже 20 файлов",
    "image_too_large": "Картинка слишком большая",
    "write_failed": "Не удалось сохранить файл",
    "article_gone": "Статья удалена",
}
PLACEHOLDERS = {"checking": "placeholder-checking.svg", "removed": "placeholder-removed.svg",
                "unavailable": "placeholder-unavailable.svg"}
_STATIC = pathlib.Path(__file__).resolve().parents[1] / "static" / "knowledge"


def _article_for_download(user, article_id):
    """Статья для выдачи файла: недоступная (чужой черновик, корзина не-управляющему) — как несуществующая."""
    try:
        return access.get_for(user, article_id)
    except access.ArticleGone:
        raise Http404("Статьи нет") from None


def _list_response(request, article, *, code: str = "", status: int = 200):
    """Ответ о списке вложений: фрагмент `[data-kb-files]` для HTMX; обычный запрос — страница правки."""
    context = {"article": article, "files": file_service.list_for(article) if article.state != "trash" else [],
               "editable": True, "file_error": {"code": code, "text": REFUSALS[code]} if code else None}
    if is_fragment(request):
        response = render(request, "knowledge/_files.html", context, status=status)
        response["Vary"] = "HX-Request"
        return response
    if not code:
        return HttpResponseRedirect(f"/kb/{article.pk}/edit/")
    return render_page(request, "knowledge/edit.html", {**context, "page": "edit"}, status=status)


def _gone_response(request, article_id):
    """Статья ушла в корзину: 200 «Статья удалена» (`data-code="article_gone"`)."""
    article = Article.objects.filter(pk=article_id).first() or Article(pk=article_id, state="trash")
    return _list_response(request, article, code="article_gone")


@login_required
@require_POST
def file_attach(request, article_id):
    upload = request.FILES.get("file")
    if upload is None:
        return HttpResponseBadRequest("Файл не передан")
    try:
        file_service.attach(request.user, article_id, upload)
    except FileRefused as refused:
        return _list_response(request, Article.objects.get(pk=article_id), code=refused.code)
    except access.ArticleGone:
        return _gone_response(request, article_id)
    return _list_response(request, Article.objects.get(pk=article_id))


@login_required
@require_POST
def file_delete(request, article_id, number):
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise Http404("Статьи нет")
    item = ArticleFile.objects.filter(pk=number, article_id=article_id).first()
    try:
        if item is None:
            if article.state == Article.State.TRASH:
                raise access.ArticleGone
            raise Http404("Файла нет")
        file_service.remove(request.user, item.pk)
    except access.ArticleGone:
        return _gone_response(request, article_id)
    return _list_response(request, article)


@login_required
def file_download(request, article_id, number):
    article = _article_for_download(request.user, article_id)
    item = ArticleFile.objects.select_related("file").filter(pk=number, article=article).first()
    if item is None or item.file.status != "clean":
        raise Http404("Файла нет")
    return file_response.download(item.file, item.name)


def _placeholder(state: str) -> HttpResponse:
    svg = (_STATIC / PLACEHOLDERS[state]).read_bytes()
    response = HttpResponse(svg, content_type="image/svg+xml")
    response["X-KB-Placeholder"] = state
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


@login_required
def image(request, article_id, number):
    article = _article_for_download(request.user, article_id)
    item = ArticleFile.objects.select_related("file").filter(pk=number, article=article).first()
    if item is None:
        return _placeholder("removed")
    status = item.file.status
    if status == "pending":
        return _placeholder("checking")
    if status != "clean" or not item.image_format:
        return _placeholder("unavailable")
    return file_response.inline_image(item.file, item.image_format)
