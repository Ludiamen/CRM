"""Страницы статьи: новая, чтение, правка, публикация, предпросмотр, действия корзины над одной статьёй (T-5214;
PLAN-005, «Создание, сохранение и публикация», «Корзина…», «Права и видимость»; CONTRACT-005, 10.1, 10.2, 10.3, 10.7, 11.3).

Представления тонкие: проверки и записи делают службы `knowledge.services`. Порядок отказов — шаги плана: корзина, затем
право. Отказ формы (`KnowledgeError`) и статья в корзине на POST — всегда 200 с сообщением и введённым (не 4xx); нет права —
`PermissionDenied` (403), нет статьи или она не видна — `Http404`; GET страниц статьи в корзине не-управляющему — 410.
"""
import functools

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.services import valkey
from apps.core.views.common import flash, is_fragment, render_page

from ..models import Article, Rubric
from ..services import KnowledgeError, VersionConflict, access, articles, files, links, rubrics
from ..services import render as markdown
from . import comments as comment_views

MAX_TEXT = 200_000
MAX_NUMBER = 2_147_483_647
PREVIEW_LIMIT_SECONDS = 10

TEXTS = {
    "title_empty": "Введите заголовок",
    "title_too_long": "Заголовок не длиннее 200 знаков",
    "text_too_long": "Текст не длиннее 200 000 знаков",
    "rubric_missing": "Выберите рубрику: такой рубрики нет",
    "comment_too_long": "Комментарий к правке не длиннее 200 знаков",
    "tags_too_many": "Не больше 10 тегов",
    "tag_too_long": "Тег не длиннее 40 знаков",
    "already_published": "Статья уже опубликована",
    "not_in_trash": "Статья не в корзине",
    "current_version": "Текущую версию удалить нельзя",
    "article_gone": "Статья удалена",
}
FLASH_SAVED = {"draft": "Черновик сохранён", "published": "Статья сохранена"}


# --- общие помощники (их используют и страницы истории) ----------------------------------------------------------

def pk_of(value):
    """Номер из поля формы: целое в пределах поля базы, иначе `None` (рубрики или статьи нет)."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= MAX_NUMBER else None


def int_of(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def fragment_response(request, template: str, context: dict, *, status: int = 200):
    response = render(request, template, context, status=status)
    response["Vary"] = "HX-Request"
    return response


def done(request, url: str, text: str):
    """Успех действия: флеш и переход; запрос HTMX — пустой ответ с `HX-Redirect` на тот же адрес."""
    flash(request, text)
    if is_fragment(request):
        response = HttpResponse("")
        response["HX-Redirect"] = url
        response["Vary"] = "HX-Request"
        return response
    return redirect(url)


def gone_page(request):
    """Страница 410: «Статья удалена» без заголовка и текста статьи."""
    return render_page(request, "knowledge/gone.html", {}, status=410)


def gone_guard(view):
    """GET-страницы статьи: статья в корзине у не-управляющего — 410 (решение 43 задач)."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except access.ArticleGone:
            return gone_page(request)

    return wrapper


def refusal(request, code: str, article_id=None, *, conflict=None):
    """Общий отказ действия без формы: 200 и `[role=alert][data-code]` (запрос HTMX — только сообщение)."""
    context = {"alert": {"code": code, "text": TEXTS.get(code, "Действие не выполнено")}, "conflict": conflict,
               "article_id": article_id, "back": f"/kb/{article_id}/" if article_id else "/kb/"}
    if is_fragment(request):
        return fragment_response(request, "knowledge/_alert.html", context)
    return render_page(request, "knowledge/refused.html", context)


def gone_refusal(request, article_id=None):
    return refusal(request, "article_gone", article_id)


def conflict_refusal(request, conflict: VersionConflict, article_id):
    return refusal(request, "stale_version", article_id, conflict={
        "who": conflict.who, "when": conflict.when, "base_version": conflict.base_version,
        "current_version": conflict.current_version})


# --- рубрики, поля формы, контекст страницы правки ------------------------------------------------------------------

def rubric_options(selected: str) -> list:
    """Дерево рубрик для `select[name=rubric]` в порядке обхода; в подписи отступ по глубине."""
    out: list = []

    def walk(nodes, depth):
        for node in nodes:
            out.append({"id": node.rubric.pk, "label": "  " * depth + node.rubric.name,
                        "selected": str(node.rubric.pk) == str(selected)})
            walk(node.children, depth + 1)

    walk(rubrics.tree(), 0)
    return out


def rubric_path(rubric_id) -> list:
    """Путь рубрики от корня: `[{id, name}, …]` (до трёх уровней)."""
    path: list = []
    current = Rubric.objects.filter(pk=rubric_id).first()
    while current is not None and len(path) < 4:
        path.append({"id": current.pk, "name": current.name})
        current = Rubric.objects.filter(pk=current.parent_id).first() if current.parent_id else None
    return list(reversed(path))


def posted_values(post) -> dict:
    return {"title": post.get("title", ""), "text": post.get("text", ""), "rubric": post.get("rubric", ""),
            "tags": post.get("tags", ""), "comment": post.get("comment", "")}


def article_form(values: dict) -> articles.ArticleForm:
    return articles.ArticleForm(title=values["title"], text=values["text"], rubric_id=pk_of(values["rubric"]),
                                tags=values["tags"], comment=values["comment"])


def errors_of(refused: KnowledgeError) -> dict:
    """Отказ службы для шаблона: у поля — `errors[поле]`, без поля — общий `alert`."""
    item = {"code": refused.code, "text": TEXTS.get(refused.code, "Не удалось сохранить")}
    return {"errors": {refused.field: item}} if refused.field else {"alert": item}


def refused_form_target(request, article_id):
    """Статья для повторного показа формы после отказа у поля.

    Служба проверяет поля формы раньше права (CONTRACT-005, B-3), поэтому отказ у поля может прийти и на статью, которую
    сотрудник не видит: тогда ответ — как у GET-правки (чужой черновик и несуществующий номер — 404, нет права — 403),
    без вложений, версии и заголовка чужой статьи. Статья в корзине показывается как прежде (вложения в ней скрыты)."""
    try:
        item = access.get_for(request.user, article_id)
    except access.ArticleGone:
        return Article.objects.filter(pk=article_id).first()
    if item.state != Article.State.TRASH and not access.can_change(request.user, item):
        raise PermissionDenied
    return item


def edit_context(request, article, values=None, extra=None) -> dict:
    """Контекст шаблона `knowledge/edit.html` (и фрагмента формы): введённое, дерево рубрик, вложения, отказы.

    `article` — `None` у новой статьи; `extra` перекрывает значения (так вызывает и `views/files.py::_list_response`).
    """
    if values is None:
        if article is None:
            values = {"title": "", "text": "", "rubric": "", "tags": "", "comment": ""}
        else:
            values = {"title": article.title, "text": article.text, "rubric": str(article.rubric_id),
                      "tags": ", ".join(articles.tag_names_of(article)), "comment": ""}
    in_trash = article is not None and article.state == Article.State.TRASH
    context = {
        "article": article, "page": "new" if article is None else "edit", "values": values,
        "rubric_options": rubric_options(values.get("rubric", "")),
        "base_version": "" if article is None else article.version_no,
        "errors": {}, "alert": None, "conflict": None, "notice": False, "pdn": [], "pdn_action": "",
        "files": [] if article is None or in_trash else files.list_for(article),
        "file_error": None, "editable": True,
        "can_publish": bool(article is not None and access.can_publish(request.user, article)),
    }
    context.update(extra or {})
    return context


def render_form(request, article, values=None, extra=None, *, status: int = 200):
    """Форма статьи: запрос HTMX — только `form[data-form="kb-article"]`, обычный — страница правки."""
    context = edit_context(request, article, values, extra)
    if is_fragment(request):
        return fragment_response(request, "knowledge/_form.html", context, status=status)
    return render_page(request, "knowledge/edit.html", context, status=status)


def _action_of(post) -> str:
    """Нажатая кнопка: последнее непустое `action` из `save`, `publish`; иначе `save`."""
    for value in reversed(post.getlist("action")):
        if value in ("save", "publish"):
            return value
    return "save"


def _confirmed(post) -> bool:
    return (post.getlist("confirm_pdn") or [""])[-1] == "1"


# --- новая статья ----------------------------------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "POST"])
def new(request):
    if not access.can_edit(request.user):
        raise PermissionDenied
    if request.method == "GET":
        return render_form(request, None)
    values = posted_values(request.POST)
    try:
        created = articles.create(request.user, article_form(values))
    except KnowledgeError as refused:
        return render_form(request, None, values, errors_of(refused))
    return done(request, f"/kb/{created.pk}/edit/", FLASH_SAVED["draft"])


# --- чтение ------------------------------------------------------------------------------------------------------------

def article_context(request, item) -> dict:
    """Контекст страницы статьи: поля, кнопки по праву, вложения, связанные заявки, комментарии (только опубликованная)."""
    user = request.user
    in_trash = item.state == Article.State.TRASH
    context = {
        "article": item, "article_id": item.pk, "tag_names": articles.tag_names_of(item),
        "rubric_path": rubric_path(item.rubric_id), "in_trash": in_trash,
        "can_change": access.can_change(user, item), "can_publish": access.can_publish(user, item),
        "can_manage": access.can_manage(user), "pdn": [], "pdn_action": "", "files": [], "editable": False,
        "file_error": None, "tickets": [],
    }
    if not in_trash:
        context["files"] = files.list_for(item)
        context["tickets"] = links.tickets_for(user, item)
    if item.state == Article.State.PUBLISHED:
        context.update(comment_views.block_context(user, item))
    return context


@login_required
@require_GET
def article(request, article_id):
    try:
        item = access.get_for(request.user, article_id)
    except access.ArticleGone:
        return gone_page(request)
    except Http404:
        return render_page(request, "knowledge/not_found.html", {}, status=404)
    articles.viewed(request.user, item)
    return render_page(request, "knowledge/article.html", article_context(request, item))


# --- правка и публикация -----------------------------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "POST"])
def edit(request, article_id):
    if request.method == "GET":
        try:
            item = access.get_for(request.user, article_id)
        except access.ArticleGone:
            return gone_page(request)
        if item.state == Article.State.TRASH:
            return redirect(f"/kb/{item.pk}/")
        if not access.can_change(request.user, item):
            raise PermissionDenied
        return render_form(request, item)
    values = posted_values(request.POST)
    base = int_of(request.POST.get("base_version"))
    action = _action_of(request.POST)
    confirmed = _confirmed(request.POST)
    try:
        form = article_form(values)
        if action == "publish":
            result = articles.publish(request.user, article_id, base, form, confirmed)
        else:
            result = articles.save(request.user, article_id, base, form, confirmed)
    except access.ArticleGone:
        item = Article.objects.filter(pk=article_id).first()
        alert = {"code": "article_gone", "text": TEXTS["article_gone"]}
        return render_form(request, item, values, {"alert": alert, "base_version": base})
    except VersionConflict as conflict:
        item = Article.objects.filter(pk=article_id).first()
        extra = {"conflict": {"who": conflict.who, "when": conflict.when, "base_version": conflict.base_version,
                              "current_version": conflict.current_version},
                 "base_version": conflict.current_version}
        return render_form(request, item, values, extra)
    except KnowledgeError as refused:
        item = refused_form_target(request, article_id)
        return render_form(request, item, values, {**errors_of(refused), "base_version": base})
    item = result.article
    if result.kind == "no_changes":
        return render_form(request, item, values, {"notice": True})
    if result.kind == "pdn_warning":
        return render_form(request, item, values, {"pdn": result.pdn, "pdn_action": action, "base_version": base})
    if action == "publish":
        text = "Статья опубликована"
    else:
        text = FLASH_SAVED["draft" if item.state == Article.State.DRAFT else "published"]
    return done(request, f"/kb/{item.pk}/", text)


@login_required
@require_POST
def publish(request, article_id):
    base = int_of(request.POST.get("base_version"))
    try:
        result = articles.publish(request.user, article_id, base, None, _confirmed(request.POST))
    except access.ArticleGone:
        return gone_refusal(request, article_id)
    except VersionConflict as conflict:
        return conflict_refusal(request, conflict, article_id)
    except KnowledgeError as refused:
        return refusal(request, refused.code, article_id)
    if result.kind == "pdn_warning":
        context = article_context(request, result.article)
        context.update({"pdn": result.pdn, "pdn_action": "publish"})
        if is_fragment(request):
            return fragment_response(request, "knowledge/_publish_form.html", context)
        return render_page(request, "knowledge/article.html", context)
    return done(request, f"/kb/{article_id}/", "Статья опубликована")


# --- предпросмотр ------------------------------------------------------------------------------------------------------

@login_required
@require_POST
def preview(request):
    """Предпросмотр Markdown: ничего не сохраняет; замок `kb:preview:<id>` — одна подготовка на сотрудника."""
    user = request.user
    if not access.can_edit(user):
        raise PermissionDenied
    text = request.POST.get("text", "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT:
        return fragment_response(request, "knowledge/_preview.html", {"error": {
            "code": "text_too_long", "text": TEXTS["text_too_long"]}})
    number = pk_of(request.POST.get("article"))
    target = access.visible_articles(user).filter(pk=number).first() if number else None
    key = f"kb:preview:{user.pk}"
    connection = valkey.conn()
    if not connection.set(key, "1", nx=True, ex=PREVIEW_LIMIT_SECONDS):
        return fragment_response(request, "knowledge/_preview.html", {"busy": True})
    try:
        attached = files.files_map(target) if target is not None else {}
        rendered = markdown.render(text, attached, target.pk if target is not None else None)
    finally:
        connection.delete(key)
    return fragment_response(request, "knowledge/_preview.html", {"html": rendered.html})


# --- корзина: действия над одной статьёй ---------------------------------------------------------------------------------

@login_required
@require_POST
def article_trash(request, article_id):
    try:
        articles.trash(request.user, article_id)
    except access.ArticleGone:
        return gone_refusal(request, article_id)
    return done(request, f"/kb/{article_id}/", "Статья перенесена в корзину")


@login_required
@require_POST
def article_restore(request, article_id):
    try:
        articles.restore(request.user, article_id)
    except access.ArticleGone:
        return gone_refusal(request, article_id)
    except KnowledgeError as refused:
        return refusal(request, refused.code, article_id)
    return done(request, f"/kb/{article_id}/", "Статья возвращена из корзины")


@login_required
@require_POST
def article_purge(request, article_id):
    """Удалить навсегда: только управляющий и только из корзины. Порядок: корзина (не-управляющему — «Статья удалена»),
    затем право (403), затем «Статья не в корзине»."""
    item = Article.objects.filter(pk=article_id).first()
    if item is None:
        raise Http404("Статьи нет")
    manager = access.can_manage(request.user)
    if item.state == Article.State.TRASH:
        if not manager:
            return gone_refusal(request, article_id)
    else:
        if not manager:
            raise PermissionDenied
        return refusal(request, "not_in_trash", article_id)
    articles.purge(item, request.user)
    return done(request, "/kb/trash/", "Статья удалена навсегда")
