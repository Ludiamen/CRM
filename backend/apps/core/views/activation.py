"""Мастер активации по ссылке из приглашения (T-242, FR-008, FR-011…013, FR-021, FR-022, FR-026).

Шаги: профиль → пароль → второй фактор → резервные коды. Ссылка `/activate/#<код>`: страница
отдаёт скрипт, он читает фрагмент, стирает его из адресной строки и присылает код POST-запросом
на `/activate/exchange/`. Сервер кладёт в сессию отметку «идёт активация записи N»; дальше шаги
идут строго по порядку, пропустить нельзя. Ссылка гаснет после последнего шага.
"""
from django.http import Http404, HttpResponseRedirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import UserState
from apps.core.services import accounts, devices, links, login, passwords, security_settings, totp

from .auth import set_device_cookie
from .common import render_page, user_agent
from .factor import codes_step, totp_step

ACTIVATION_LINK = "activation_link_id"
PROFILE_DONE = "activation_profile_done"
PW_STEP_DONE = "activation_pw_done"
WIZARD_KEYS = (ACTIVATION_LINK, PROFILE_DONE, PW_STEP_DONE)
STEPS = ("profile", "password", "totp", "codes")
ACTIVATION_DEAD = ("Ссылка недействительна: срок её действия истёк (ссылка просрочена), она уже использована "
                   "или заменена новой. Обратитесь к администратору портала, чтобы получить новое приглашение. "
                   "Если вы уже активировали запись, войдите обычным способом.")


def _step_url(step: str) -> str:
    return f"/activate/{step}/"


def _redirect(url: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(url)


def _first_open(request, user) -> str:
    """Первый ещё не пройденный шаг."""
    session = request.session
    if not session.get(PROFILE_DONE):
        return "profile"
    if not session.get(PW_STEP_DONE):
        return "password"
    if not totp.has_confirmed(user):
        return "totp"
    return "codes"


def _landing(request, error: str = ""):
    return render_page(request, "activation/landing.html", {"error": error})


@require_http_methods(["GET"])
def start(request):
    """Страница ссылки: скрипт обменяет код из фрагмента; идущую активацию продолжает с текущего шага."""
    link = links.get_live(request.session.get(ACTIVATION_LINK))
    if link is not None and link.user.state == UserState.INVITED:
        return _redirect(_step_url(_first_open(request, link.user)))
    return _landing(request)


@require_POST
def exchange(request):
    link = links.exchange(request.POST.get("code", ""), "activation")
    if link is None:
        return _landing(request, ACTIVATION_DEAD)
    for key in WIZARD_KEYS:
        request.session.pop(key, None)
    request.session[ACTIVATION_LINK] = link.pk
    return _redirect(_step_url("profile"))


@require_http_methods(["GET", "POST"])
def step(request, step: str):
    if step not in STEPS:
        raise Http404
    link = links.get_live(request.session.get(ACTIVATION_LINK))
    if link is None or link.user.state != UserState.INVITED:
        return _redirect("/activate/")
    user = link.user
    open_step = _first_open(request, user)
    if STEPS.index(step) > STEPS.index(open_step):
        return _redirect(_step_url(open_step))
    handler = {"profile": _profile, "password": _password, "totp": _totp, "codes": _codes}[step]
    return handler(request, user, link)


def _profile(request, user, link):
    errors = []
    if request.method == "POST":
        phone, contacts = request.POST.get("phone", ""), request.POST.get("contacts", "")
        errors = profile_errors(phone, contacts)
        if not errors:
            accounts.set_profile_in_activation(user, phone=phone, contacts=contacts)
            request.session[PROFILE_DONE] = True
            return _redirect(_step_url("password"))
    return render_page(request, "activation/profile.html", {"user_obj": user, "errors": errors, "step": 1})


def profile_errors(phone: str, contacts: str) -> list[str]:
    """Проверка телефона и контактов (общая для мастера и страницы профиля)."""
    errors = []
    if len((phone or "").strip()) > 64:
        errors.append("Телефон: не больше 64 знаков.")
    lines = accounts.parse_contacts(contacts)
    if len(lines) > 10 or any(len(line) > 200 for line in lines):
        errors.append("Контакты: не больше 10 строк, каждая не длиннее 200 знаков.")
    return errors



def _password(request, user, link):
    errors = []
    if request.method == "POST":
        first, second = request.POST.get("password1", ""), request.POST.get("password2", "")
        if first != second:
            errors = ["Пароли не совпадают."]
        else:
            try:
                passwords.set_initial_password(user, first)
            except passwords.PolicyError as error:
                errors = error.messages
            else:
                request.session[PW_STEP_DONE] = True
                return _redirect(_step_url("totp"))
    return render_page(request, "activation/password.html", {
        "errors": errors, "step": 2, "min_length": security_settings.get().password_min_length})


def _totp(request, user, link):
    return totp_step(request, user, template="activation/totp.html", done_url=_step_url("codes"),
                     context={"step": 3, "post_url": _step_url("totp")})


def _codes(request, user, link):
    def finish(request, user):
        try:
            accounts.complete_activation(user, link, ip=request.client_ip)
        except accounts.AccountError:
            return _redirect(_step_url(_first_open(request, user)))
        done = login.complete(request, user, ip=request.client_ip, user_agent=user_agent(request),
                              device_key=request.COOKIES.get(devices.COOKIE_NAME), via="activation")
        for key in WIZARD_KEYS:
            request.session.pop(key, None)
        response = _redirect("/")
        set_device_cookie(response, done.device_key)
        return response

    return codes_step(request, user, template="activation/codes.html", self_url=_step_url("codes"),
                      finish=finish, context={"step": 4, "post_url": _step_url("codes")})
