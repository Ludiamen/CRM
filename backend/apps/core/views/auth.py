"""Вход, выход, «Забыли пароль?» и восстановление (T-241, FR-012, FR-021, FR-025, FR-031…034).

Вход идёт в два шага: почта и пароль, затем код. После шага пароля id записи лежит в
сессии как «ожидает код» (`PENDING_*`) — это ещё не вход. Причина отказа наружу не
раскрывается: все отказы шага — один и тот же текст, и страница не повторяет введённую почту.
"""
import time
from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.core import extensions
from apps.core.models import User
from apps.core.services import backup_codes, devices, links, login, passwords, sessions

from .common import flash, render_page, safe_next, user_agent

PENDING_USER = "login_user_id"
PENDING_NEXT = "login_next"
PENDING_AT = "login_started_at"
PENDING_SECONDS = 15 * 60
RESET_LINK = "reset_link_id"

LOGIN_URL = "/login/"
CODE_URL = "/login/code/"
TOTP_URL = "/me/security/totp/"
PASSWORD_URL = "/me/security/password/"

LAST_CODE_REMINDER = ("Вы вошли по последнему резервному коду. Выпустите новый набор в разделе «Безопасность» — "
                      "без кодов при потере телефона войти не получится.")
LOGIN_FAILED = "Не удалось войти: проверьте почту и пароль и попробуйте ещё раз."
CODE_FAILED = "Код не подошёл. Проверьте код в приложении или введите резервный код и попробуйте ещё раз."
RESET_DEAD = ("Ссылка недействительна: срок её действия истёк (ссылка просрочена), она уже использована "
              "или заменена новой. Запросите восстановление пароля ещё раз.")
RESET_FORGOT_SENT = ("Если запись с такой почтой есть и она активна, мы отправили на неё письмо со ссылкой "
                     "для восстановления пароля.")


def set_device_cookie(response, raw_key: str) -> None:
    """Кука устройства: долгоживущая, HttpOnly, Secure, SameSite=Lax; в базе лежит только хеш значения."""
    if raw_key:
        response.set_cookie(devices.COOKIE_NAME, raw_key, max_age=devices.COOKIE_MAX_AGE, secure=True,
                            httponly=True, samesite="Lax")


def _redirect(url: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(url)


def _login_action(next_url: str) -> str:
    return f"{LOGIN_URL}?{urlencode({'next': next_url})}" if next_url else LOGIN_URL


def _forget_pending(session) -> None:
    for key in (PENDING_USER, PENDING_NEXT, PENDING_AT):
        session.pop(key, None)


def _pending_user(request) -> User | None:
    """Запись, у которой пройден шаг пароля и ждёт код (не дольше 15 минут)."""
    session = request.session
    user_id, started = session.get(PENDING_USER), session.get(PENDING_AT) or 0
    if not user_id or time.time() - started > PENDING_SECONDS:
        _forget_pending(session)
        return None
    return User.objects.filter(pk=user_id).first()


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Шаг 1: почта и пароль."""
    if request.user.is_authenticated and not sessions.is_limited(request):
        return _redirect(safe_next(request, request.GET.get("next")))
    next_url = request.GET.get("next", "")
    if next_url and safe_next(request, next_url, "") == "":
        next_url = ""
    links_for_login = [item for func in extensions.registered("login_links") for item in func()]
    context = {"action": _login_action(next_url), "idle": request.GET.get("idle") == "1",
               "login_links": links_for_login}
    if request.method == "POST":
        step = login.check_password(request.POST.get("email", ""), request.POST.get("password", ""),
                                    ip=request.client_ip, user_agent=user_agent(request))
        if not step.ok:
            context["error"] = LOGIN_FAILED
            return render_page(request, "auth/login.html", context)
        if step.limited:  # второго фактора нет: ограниченная сессия до его подключения
            done = login.complete(request, step.user, ip=request.client_ip, user_agent=user_agent(request),
                                  device_key=request.COOKIES.get(devices.COOKIE_NAME), via="password", limited=True)
            response = _redirect(TOTP_URL)
            set_device_cookie(response, done.device_key)
            return response
        request.session[PENDING_USER] = step.user.pk
        request.session[PENDING_NEXT] = next_url
        request.session[PENDING_AT] = time.time()
        return _redirect(CODE_URL)
    return render_page(request, "auth/login.html", context)


@require_http_methods(["GET", "POST"])
def login_code(request):
    """Шаг 2: код приложения или резервный код."""
    user = _pending_user(request)
    if user is None:
        return _redirect(LOGIN_URL)
    context = {}
    if request.method == "POST":
        step = login.check_code(user, code=request.POST.get("code", ""), backup_code=request.POST.get("backup_code", ""),
                                ip=request.client_ip, user_agent=user_agent(request))
        if step.ok:
            target = safe_next(request, request.session.get(PENDING_NEXT), "/")
            done = login.complete(request, user, ip=request.client_ip, user_agent=user_agent(request),
                                  device_key=request.COOKIES.get(devices.COOKIE_NAME), via=step.via)
            _forget_pending(request.session)
            if step.via == "backup" and backup_codes.remaining(user) == 0:  # сц. 6 п. 4: напомнить о новом наборе
                flash(request, LAST_CODE_REMINDER, link=("/me/security/", "Открыть «Безопасность»"))
            if passwords.must_change(user):  # срок пароля вышел: сначала новый пароль (FR-027)
                target = PASSWORD_URL
            response = _redirect(target)
            set_device_cookie(response, done.device_key)
            return response
        context["error"] = CODE_FAILED
        context["use_backup"] = bool(request.POST.get("backup_code"))
    return render_page(request, "auth/login_code.html", context)


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        login.logout(request, ip=request.client_ip)
    return _redirect(LOGIN_URL)


@require_http_methods(["GET", "POST"])
def forgot(request):
    """Запрос ссылки восстановления: ответ один и тот же для любого адреса (FR-031)."""
    context = {}
    if request.method == "POST":
        links.request_password_reset(request.POST.get("email", ""), ip=request.client_ip)
        context["sent"] = RESET_FORGOT_SENT
    return render_page(request, "auth/forgot.html", context)


def _reset_link(request):
    return links.get_live(request.session.get(RESET_LINK))


@require_POST
def reset_exchange(request):
    """Обмен кода из фрагмента на отметку «идёт восстановление» (код приходит только телом POST)."""
    link = links.exchange(request.POST.get("code", ""), "reset")
    if link is None:
        return render_page(request, "auth/reset_landing.html", {"error": RESET_DEAD})
    request.session[RESET_LINK] = link.pk
    return _redirect("/password/reset/")


@require_http_methods(["GET", "POST"])
def reset_password(request):
    """Страница нового пароля: пока кода не обменяли, показывает страницу, которая его обменяет."""
    link = _reset_link(request)
    if link is None:
        return render_page(request, "auth/reset_landing.html", {"error": RESET_DEAD if request.method == "POST" else ""})
    context = {}
    if request.method == "POST":
        first, second = request.POST.get("password1", ""), request.POST.get("password2", "")
        if first != second:
            context["errors"] = ["Пароли не совпадают."]
        else:
            try:
                passwords.reset_password(link.user, first, link=link, ip=request.client_ip)
            except passwords.PolicyError as error:
                context["errors"] = error.messages
            else:
                request.session.pop(RESET_LINK, None)
                flash(request, "Пароль изменён. Войдите с новым паролем и кодом из приложения.")
                return _redirect(LOGIN_URL)
    return render_page(request, "auth/reset_password.html", context)
