"""Профиль и «Безопасность» (T-243, UX-12, FR-006, FR-023, FR-029, FR-030, FR-039…041, FR-051).

«Безопасность» — один слайдер поверх профиля (UX-03): ссылки внутри него подгружают фрагмент
HTMX в боковую панель и меняют адрес (`hx-push-url`). Тот же адрес, открытый напрямую, показывает
полную страницу: профиль под слайдером. Страницы второго фактора (подключение, резервные коды)
открываются обычными страницами, потому что ими же пользуется ограниченная сессия без меню.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import UserSession
from apps.core.services import accounts, backup_codes, devices, lockout, login, passwords, sessions, totp

from .activation import profile_errors
from .auth import set_device_cookie
from .common import flash, is_fragment, render_page, user_agent
from .factor import codes_step, totp_step

SECURITY_URL = "/me/security/"
HISTORY_PAGE_SIZE = 50
RESULT_TITLES = dict([
    ("success", "Вход выполнен"),
    ("backup_code", "Вход по резервному коду"),
    ("bad_password", "Неверный пароль"),
    ("bad_code", "Неверный код"),
    ("locked", "Отказ: запись заблокирована"),
    ("ip_locked", "Отказ: адрес заблокирован"),
])


def _redirect(url: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(url)


def _profile_context(user) -> dict:
    return {"roles": list(user.roles.order_by("name").values_list("name", flat=True))}


def _slider(request, body: str, title: str, context: dict | None = None, *, status: int = 200):
    """Страница слайдера: фрагмент для HTMX или полная страница с профилем под панелью."""
    context = {**(context or {}), "slider_body": body, "slider_title": title}
    if is_fragment(request):
        response = render(request, "me/slider_fragment.html", context, status=status)
        response["Vary"] = "HX-Request"
        return response
    return render_page(request, "me/profile.html", {**_profile_context(request.user), **context}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    user = request.user
    if request.method == "GET" and is_fragment(request) and request.headers.get("HX-Target") == "slider-root":
        return HttpResponse("")  # «×» закрывает слайдер: профиль под ним уже на странице
    errors = []
    if request.method == "POST":
        phone, contacts = request.POST.get("phone", ""), request.POST.get("contacts", "")
        errors = profile_errors(phone, contacts)
        if not errors:
            accounts.update_own_contacts(user, phone=phone, contacts=contacts, ip=request.client_ip)
            flash(request, "Данные профиля сохранены.")
            return _redirect("/me/")
        user.phone, user.contacts = phone, accounts.parse_contacts(contacts)
    return render_page(request, "me/profile.html", {**_profile_context(user), "errors": errors})


@login_required
@require_http_methods(["GET"])
def security(request):
    user = request.user
    context = {"backup_remaining": backup_codes.remaining(user), "has_totp": totp.has_confirmed(user),
               "password_changed_at": passwords.changed_at(user)}
    return _slider(request, "me/_security.html", "Безопасность", context)


def _password_page(request, errors, *, forced: bool):
    context = {"errors": errors, "forced": forced}
    if forced:
        return render_page(request, "me/password_forced.html", context)
    return _slider(request, "me/_password.html", "Смена пароля", context)


@login_required
@require_http_methods(["GET", "POST"])
def password(request):
    user = request.user
    forced = passwords.must_change(user)
    errors = []
    if request.method == "POST":
        first, second = request.POST.get("password1", ""), request.POST.get("password2", "")
        if lockout.is_account_locked(str(user.pk)):
            errors = ["Сейчас пароль сменить нельзя: слишком много неудачных попыток. Попробуйте позже."]
        elif first != second:
            errors = ["Новые пароли не совпадают."]
        else:
            try:
                passwords.change_password(user, request.POST.get("current_password", ""), first,
                                          request=request, ip=request.client_ip)
            except passwords.BadCurrentPassword:
                errors = ["Текущий пароль указан неверно."]
            except passwords.PolicyError as error:
                errors = error.messages
            else:
                flash(request, "Пароль изменён. На других устройствах вы вышли из портала.")
                return _redirect(SECURITY_URL)
    return _password_page(request, errors, forced=forced)


@login_required
@require_POST
def logout_everywhere(request):
    closed = sessions.logout_everywhere(request, request.user, ip=request.client_ip)
    flash(request, f"Вы вышли на других устройствах (закрыто сессий: {closed}). Эта сессия осталась." if closed
          else "Других открытых сессий нет.")
    return _redirect(SECURITY_URL)


@login_required
@require_http_methods(["GET", "POST"])
def totp_page(request):
    """Подключение второго фактора (сюда ведёт ограниченная сессия); новое устройство заменяет прежнее."""
    return totp_step(request, request.user, template="me/totp.html", done_url=_after_totp(request),
                     context={"post_url": "/me/security/totp/"})


def _after_totp(request) -> str:
    """Без резервных кодов (сброшены) или в ограниченной сессии — к их показу, иначе в «Безопасность»."""
    if sessions.is_limited(request) or backup_codes.device_of(request.user) is None:
        return "/me/security/backup-codes/"
    return SECURITY_URL


@login_required
@require_http_methods(["GET", "POST"])
def backup_codes_page(request):
    return codes_step(request, request.user, template="me/codes.html", self_url="/me/security/backup-codes/",
                      finish=_finish_codes, context={"post_url": "/me/security/backup-codes/"})


def _finish_codes(request, user):
    """«Я сохранил коды»: ограниченная сессия получает полный доступ (и активацию, если мастер прерывали)."""
    if not sessions.is_limited(request):
        return _redirect(SECURITY_URL)
    ip = request.client_ip
    if user.state == "invited":
        accounts.complete_activation(user, None, ip=ip)
    done = login.finish_limited(request, user, ip=ip, user_agent=user_agent(request),
                                device_key=request.COOKIES.get(devices.COOKIE_NAME))
    response = _redirect("/")
    set_device_cookie(response, done.device_key)
    return response


@login_required
@require_POST
def new_backup_codes(request):
    """Новый набор из 10 кодов: прежний гаснет; коды показываются в этом ответе один раз."""
    from apps.core.services import second_factor

    codes = second_factor.issue_backup_codes(request.user, ip=request.client_ip)
    return render_page(request, "me/codes_new.html", {"codes": codes})


def _current_device_id(request):
    row = UserSession.objects.filter(session_key=request.session.session_key).only("device_id").first()
    return row.device_id if row else None


@login_required
@require_http_methods(["GET"])
def devices_page(request):
    rows = list(devices.known_devices(request.user))
    context = {"devices": rows, "current_id": _current_device_id(request)}
    return _slider(request, "me/_devices.html", "Устройства", context)


def _own_device_action(request, device_id: int, action):
    if not action(request.user, device_id):
        raise Http404
    return _redirect("/me/security/devices/")


@login_required
@require_POST
def device_close(request, device_id: int):
    return _own_device_action(request, device_id, devices.close_sessions)


@login_required
@require_POST
def device_forget(request, device_id: int):
    return _own_device_action(request, device_id, devices.forget)


@login_required
@require_http_methods(["GET"])
def history_page(request):
    page = Paginator(devices.history(request.user), HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    for row in page:
        row.result_title = RESULT_TITLES.get(row.result, row.result)
    return _slider(request, "me/_history.html", "История входов", {"page": page})
