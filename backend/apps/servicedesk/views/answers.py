"""Заглушки маршрутов частых ответов (срез 011, этап 2)."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse

from ..services import access


def _menu_required(view):
    """Для раздела шаблонов достаточно права видимости пункта «Заявки»."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not access.menu_visible(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


@_menu_required
def answer_list(request):
    return HttpResponse(status=404)


@_menu_required
def answer_new(request):
    return HttpResponse(status=404)


@_menu_required
def answer_edit(request, pk: int):
    return HttpResponse(status=404)


@_menu_required
def answer_archive(request, pk: int):
    return HttpResponse(status=404)


@_menu_required
def answer_insert(request, pk: int):
    return HttpResponse(status=404)
