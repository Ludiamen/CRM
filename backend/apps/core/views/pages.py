"""Главная, проверка здоровья, отдача логотипа и страницы ошибок (T-250, T-223, FR-018, FR-049, NFR-007)."""
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connections
from django.http import Http404, HttpResponse
from django.views import defaults as django_defaults
from django.views.decorators.http import require_GET
from django.views.static import serve

from apps.core import extensions

from .common import render_page

# Из /media/ отдаётся только то, что принимает форма логотипа (PNG и JPEG, FR-049)
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg"}


@login_required
@require_GET
def home(request):
    notices = []
    for func in extensions.registered("home_notices"):
        notices.extend(func(request.user))
    return render_page(request, "home.html", {"notices": notices})


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


def release_db_connections(view):
    """Страница ошибки отдаёт соединения базы текущего потока сразу после отрисовки.

    Причина: в асинхронной цепочке Django (core/handlers/exception.py, convert_exception_to_response)
    ответ на исключение строится через sync_to_async(..., thread_sensitive=False), то есть в потоке
    общего пула, а не в потоке запроса. Страница ошибки с оболочкой читает базу (число уведомлений,
    настройки) и берёт соединение из пула в этом потоке; request_finished закрывает только соединения
    потока запроса, и слот пула терялся навсегда (4 одновременные ошибки вешали процесс).
    Ответ здесь полностью отрисован (не ленивый), поэтому соединение больше не нужно. Внутри
    транзакции (тесты в atomic) соединение не трогаем: close() сломал бы её. В потоке запроса
    это безвредно: следующий доступ откроет соединение заново, request_finished закроет его.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        finally:
            for conn in connections.all(initialized_only=True):
                if not conn.in_atomic_block:
                    conn.close()
    return wrapper


def _error(request, template: str, status: int):
    try:
        return render_page(request, template, status=status)
    except Exception:  # noqa: BLE001 — страница ошибки не должна падать сама
        return HttpResponse("Страница недоступна.", status=status, content_type="text/plain; charset=utf-8")


@release_db_connections
def forbidden(request, exception=None):
    """403: коротко и без подробностей (какое право нужно, какой путь)."""
    return _error(request, "errors/403.html", 403)


@release_db_connections
def not_found(request, exception=None):
    return _error(request, "errors/404.html", 404)


@release_db_connections
def csrf_failure(request, reason=""):
    """Не прошла проверка CSRF: причина наружу не уходит."""
    return _error(request, "errors/403.html", 403)


@release_db_connections
def server_error(request):
    return HttpResponse("Что-то пошло не так. Попробуйте позже.", status=500, content_type="text/plain; charset=utf-8")


@release_db_connections
def bad_request(request, exception=None):
    """400: стандартная страница Django (шаблона 400.html в проекте нет), с освобождением соединений."""
    return django_defaults.bad_request(request, exception)
