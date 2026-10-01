"""Главная, проверка здоровья, отдача логотипа и страницы ошибок (T-250, T-223, FR-018, FR-049, NFR-007)."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET
from django.views.static import serve

from .common import render_page

# Из /media/ отдаётся только то, что принимает форма логотипа (PNG и JPEG, FR-049)
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg"}


@login_required
@require_GET
def home(request):
    return render_page(request, "home.html")


@require_GET
def health(request):
    """Открытая проверка здоровья: короткий ответ без версий и названий служб (NFR-23 из TGT-NFR)."""
    response = HttpResponse("ok", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def media(request, path: str):
    """Логотип портала: только PNG и JPEG, с `nosniff`; на странице он выводится лишь через <img>."""
    if Path(path).suffix.lower() not in MEDIA_SUFFIXES:
        raise Http404
    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _error(request, template: str, status: int):
    try:
        return render_page(request, template, status=status)
    except Exception:  # noqa: BLE001 — страница ошибки не должна падать сама
        return HttpResponse("Страница недоступна.", status=status, content_type="text/plain; charset=utf-8")


def forbidden(request, exception=None):
    """403: коротко и без подробностей (какое право нужно, какой путь)."""
    return _error(request, "errors/403.html", 403)


def not_found(request, exception=None):
    return _error(request, "errors/404.html", 404)


def csrf_failure(request, reason=""):
    """Не прошла проверка CSRF: причина наружу не уходит."""
    return _error(request, "errors/403.html", 403)


def server_error(request):
    return HttpResponse("Что-то пошло не так. Попробуйте позже.", status=500, content_type="text/plain; charset=utf-8")
