"""Представления частых ответов (CONTRACT-011, §§ 3.4, 4, 5)."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.services import permissions
from apps.core.views.common import is_fragment, render_page

from ..models import Category, Ticket
from ..services import access, answers, tickets
from ..services.errors import ServiceDeskError


def _menu_required(view):
    """Для раздела шаблонов достаточно права видимости пункта «Заявки»."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not access.menu_visible(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _page(request, *, answer=None, values=None, error=None, status=200):
    context = {
        "rows": answers.visible(request.user),
        "form": None if answer is False else {
            "answer": answer, "values": values or _values(answer), "error": error,
            "categories": Category.objects.filter(archived=False).order_by("name"),
        },
    }
    return render_page(request, "servicedesk/answers/page.html", context, status=status)


def _values(answer=None):
    return {"title": answer.title if answer else "", "text": answer.text if answer else "",
            "kind": "common" if answer and answer.owner_id is None else "personal",
            "category": str(answer.category_id) if answer and answer.category_id else ""}


def _form_response(request, answer, values, error=None, status=200):
    context = {"form": {"answer": answer, "values": values, "error": error,
                        "categories": Category.objects.filter(archived=False).order_by("name")}}
    if is_fragment(request):
        response = render(request, "servicedesk/answers/_form.html", context, status=status)
        response["Vary"] = "HX-Request"
        return response
    return _page(request, answer=answer, values=values, error=error, status=status)


def _error_data(error):
    field = {"answer_title_range": "title", "answer_text_range": "text",
             "answer_category_personal": "category"}.get(error.code)
    return {"code": error.code, "message": error.message, "field": field}


def _post_values(post):
    kind = post.get("kind", "personal")
    owner = None if kind == "common" else post.user if hasattr(post, "user") else None
    category_id = post.get("category") or None
    category = Category.objects.filter(pk=category_id, archived=False).first() if category_id else None
    return {"title": post.get("title", ""), "text": post.get("text", ""), "owner": owner,
            "category": category, "kind": kind}


def _can_manage(request, answer, *, write=False):
    if answer.owner_id is not None and answer.owner_id == request.user.pk:
        return True
    return permissions.has_permission(request.user, "servicedesk.answers")


def _answer(request, pk, *, active=False):
    answer = answers.get_visible(request.user, pk, active_only=active)
    if answer is None:
        raise Http404
    return answer


@_menu_required
@require_http_methods(["GET"])
def answer_list(request):
    return _page(request, answer=False)


@_menu_required
@require_http_methods(["GET", "POST"])
def answer_new(request):
    if request.method == "GET":
        return _page(request, answer=None, values=_values())
    values = _post_values(request.POST)
    values["owner"] = request.user if request.POST.get("kind", "personal") != "common" else None
    if request.POST.get("kind") == "common" and not permissions.has_permission(request.user, "servicedesk.answers"):
        raise PermissionDenied
    try:
        answers.create(actor=request.user, ip=getattr(request, "client_ip", None), **{k: values[k] for k in ("title", "text", "owner", "category")})
    except ServiceDeskError as error:
        return _form_response(request, None, values, _error_data(error), 400)
    if is_fragment(request):
        response = render(request, "servicedesk/answers/_list.html", {"rows": answers.visible(request.user)}, status=200)
        response["Vary"] = "HX-Request"
        return response
    return HttpResponseRedirect("/servicedesk/answers/")


@_menu_required
@require_http_methods(["GET", "POST"])
def answer_edit(request, pk: int):
    answer = _answer(request, pk, active=True)
    if not _can_manage(request, answer):
        raise Http404
    if request.method == "GET":
        return _page(request, answer=answer, values=_values(answer))
    values = _post_values(request.POST)
    values["owner"] = answer.owner
    try:
        answer = answers.update(answer, actor=request.user, ip=getattr(request, "client_ip", None),
                                title=values["title"], text=values["text"], owner=answer.owner,
                                category=values["category"])
    except ServiceDeskError as error:
        return _form_response(request, answer, values, _error_data(error), 400)
    return HttpResponseRedirect("/servicedesk/answers/")


@_menu_required
@require_POST
def answer_archive(request, pk: int):
    try:
        answer = _answer(request, pk)
    except Http404:
        # Держатель права может вернуть архивный личный шаблон, не раскрывая
        # действующие чужие личные шаблоны в обычных операциях.
        if not permissions.has_permission(request.user, "servicedesk.answers"):
            raise
        answer = answers.AnswerTemplate.objects.filter(pk=pk, archived=True).first()
        if answer is None:
            raise
    if not _can_manage(request, answer):
        raise Http404
    answer = answers.archive(answer, actor=request.user, ip=getattr(request, "client_ip", None))
    if is_fragment(request):
        response = render(request, "servicedesk/answers/_list.html", {"rows": answers.visible(request.user)}, status=200)
        response["Vary"] = "HX-Request"
        return response
    return HttpResponseRedirect("/servicedesk/answers/")


@login_required
@require_http_methods(["GET"])
def answer_insert(request, pk: int):
    answer = _answer(request, pk, active=True)
    number = request.GET.get("ticket")
    try:
        ticket = tickets.get_for(request.user, int(number))
    except (TypeError, ValueError, Http404):
        raise Http404
    if not access.can_work(request.user, ticket):
        raise Http404
    return HttpResponse(answer.text, content_type="text/plain; charset=utf-8")
