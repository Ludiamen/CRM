"""Промежуточное ПО ядра (T-219): адрес клиента, сессия, бездействие, ограниченная сессия."""
import re
from urllib.parse import urlencode

from django.core.handlers.exception import response_for_exception
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import Resolver404, resolve

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
# Выдача фото сотрудника — единственная страница среза 002, которую браузеру разрешено держать в кэше (решение 5):
# сопоставление точное по образцу маршрута, а не по префиксу `/staff/`
PHOTO_PATH = re.compile(r"/staff/\d+/photo/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/(?:512|96)/")


class ErrorResponseInRequestThreadMiddleware:
    """Страницу ошибки представления рисует поток запроса, а не поток общего пула (срез 004, пул соединений).

    Без этого `convert_exception_to_response` строит страницу ошибки в потоке `thread_sensitive=False`, которому
    нужно своё соединение базы, пока поток запроса держит своё: при числе одновременных ошибок не меньше размера
    пула страницы ошибок ждут тайм-аута пула. Django вызывает `process_exception` в потоке запроса
    (`thread_sensitive=True`) — там ответ строится на уже открытом соединении. Ответ тот же, что у Django
    (`response_for_exception`: обработчики 400/403/404/500, `got_request_exception`, журнал, DEBUG-страницы).
    Стоит последним в `MIDDLEWARE`: `process_exception` вызывается в обратном порядке списка, значит первым.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Адреса нет: `Resolver404` поднимается в `resolve_request` до `process_exception`, и страницу ошибки
        # Django рисовал бы в потоке пула. Разбираем адрес здесь заранее (цена ничтожна; `resolver_match`
        # ставит сам Django). `CommonMiddleware` (APPEND_SLASH) видит этот 404 в `process_response`, как раньше.
        try:
            resolve(request.path_info, urlconf=getattr(request, "urlconf", None))
        except Resolver404 as exc:
            return self._response(request, exc)
        return self.get_response(request)

    def process_exception(self, request, exception):
        return self._response(request, exception)

    @staticmethod
    def _response(request, exception):
        try:
            # поднимаем исключение заново, чтобы sys.exc_info() работал (журнал, DEBUG); в трассировке журнала
            # появляется строка этого `raise`
            raise exception
        except Exception:  # noqa: BLE001
            return response_for_exception(request, exception)
        finally:
            del exception  # без цикла «исключение → трассировка → этот кадр → исключение»


class ClientIPMiddleware:
    """`request.client_ip` — адрес клиента с учётом `TRUSTED_PROXIES` (решение Opus, CONTRACT.md)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.client_ip = clientip.client_ip(request.META)
        return self.get_response(request)


class ResponseHeadersMiddleware:
    """Заголовки по виду страницы (T-251, NFR-007, FR-012).

    - `Cache-Control: no-store` на всём, кроме статики, логотипа и проверки здоровья: защищённые
      страницы и страницы ввода секретов не должны оставаться в кэше («Назад» после выхода, сценарий 10);
      исключение — успешная выдача фото `/staff/<id>/photo/<uuid>/<512|96>/` (`private, max-age=86400` ставит
      представление; отказы по этому адресу остаются с `no-store`);
    Политика реферера везде одна — `same-origin` (SecurityMiddleware): код ссылки живёт только во
    фрагменте адреса, а фрагмент браузер в Referer не передаёт никогда, поэтому отдельная политика
    `no-referrer` для страниц ссылок не нужна — а с ней браузер слал бы `Origin: null`, и проверка
    CSRF отвергала бы формы (решение Opus 2026-10-01). Остальные заголовки (CSP, HSTS, nosniff)
    ставят django-csp и SecurityMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if path.startswith(PUBLIC_PREFIXES):
            return response
        if response.status_code == 200 and PHOTO_PATH.fullmatch(path):
            return response
        response["Cache-Control"] = "no-store"
        return response


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
