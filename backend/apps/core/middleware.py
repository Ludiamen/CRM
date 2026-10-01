"""Промежуточное ПО ядра (T-219): адрес клиента, сессия, бездействие, ограниченная сессия."""
from urllib.parse import urlencode

from django.http import HttpResponse, HttpResponseRedirect

from apps.core.models import UserSession
from apps.core.services import clientip, passwords, security_settings, sessions

LOGIN_URL = "/login/"
TOTP_URL = "/me/security/totp/"
PASSWORD_URL = "/me/security/password/"
# Ограниченная сессия (нет второго фактора) видит только эти страницы (FR-021, NFR-004)
LIMITED_ALLOWED = (TOTP_URL, "/me/security/backup-codes/", "/logout/")
# Истёкший срок пароля: только смена пароля и выход
EXPIRED_ALLOWED = (PASSWORD_URL, "/logout/")
PUBLIC_PREFIXES = ("/static/", "/media/", "/health/")


class ClientIPMiddleware:
    """`request.client_ip` — адрес клиента с учётом `TRUSTED_PROXIES` (решение Opus, CONTRACT.md)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.client_ip = clientip.client_ip(request.META)
        return self.get_response(request)


def _redirect(request, url: str):
    """Обычный запрос — перенаправление; запрос HTMX — заголовок HX-Redirect (страница целиком)."""
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=200)
        response["HX-Redirect"] = url
        return response
    return HttpResponseRedirect(url)


class SessionGuardMiddleware:
    """Следит за сессией вошедшего: запись `UserSession`, бездействие, ограничения доступа."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)
        key = request.session.session_key
        row = UserSession.objects.filter(session_key=key).first() if key else None
        if row is None or row.user_id != user.pk:
            sessions.end(request)  # сессию закрыли в другом месте
            return self.get_response(request)
        if sessions.idle_expired(row, request):
            sessions.end(request)
            query = {"idle": "1"}
            if request.method == "GET" and request.path != LOGIN_URL:
                query["next"] = request.get_full_path()
            return _redirect(request, f"{LOGIN_URL}?{urlencode(query)}")
        sessions.touch(row)
        path = request.path
        if not path.startswith(PUBLIC_PREFIXES):
            if sessions.is_limited(request):
                if path not in LIMITED_ALLOWED:
                    return _redirect(request, TOTP_URL)
            elif path not in EXPIRED_ALLOWED and passwords.must_change(user, security_settings.get()):
                return _redirect(request, PASSWORD_URL)
        return self.get_response(request)
