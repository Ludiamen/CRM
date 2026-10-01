"""Подключение второго фактора и показ резервных кодов (T-242, T-243, FR-021, FR-022, FR-025, NFR-004).

Общая часть мастера активации и страниц «Безопасности». Резервные коды показываются один
раз и в базе лежат только хешем, поэтому открытые коды нигде, в том числе в сессии, не хранятся:
страница выпускает набор при показе, а повторное открытие выпускает новый (прежний гаснет).
После подтверждения «я сохранил коды» страница больше кодов не показывает.
"""
from django.http import HttpResponseRedirect

from apps.core.models import UserState
from apps.core.services import backup_codes, lockout, login, second_factor, totp

from .common import flash, render_page

CODES_PENDING = "codes_pending"
TOTP_FAILED = "Код не подошёл. Проверьте, что на телефоне верное время, и введите актуальный код из приложения."


def _blocked(user, ip: str) -> bool:
    """Запись или адрес заблокированы: код даже не проверяется (как при переборе пароля, FR-025)."""
    return lockout.is_account_locked(str(user.pk)) or lockout.is_ip_locked(ip)


def totp_step(request, user, *, template: str, done_url: str, context: dict | None = None):
    """Страница подключения TOTP: ключ, QR и поле кода. Неверный код — неудача в счётчиках."""
    ip, error = request.client_ip, ""
    if request.method == "POST":
        if _blocked(user, ip):
            error = TOTP_FAILED
        elif totp.confirm_enrollment(user, request.POST.get("code", ""), ip=ip):
            if backup_codes.device_of(user) is None:
                request.session[CODES_PENDING] = True  # коды выпустит следующая страница
            return HttpResponseRedirect(done_url)
        else:
            login.register_other_failure(user, ip=ip, step="totp_setup")
            error = TOTP_FAILED
    device = totp.begin_enrollment(user)
    page = {**(context or {}), "error": error, "secret": totp.secret_base32(device), "qr": totp.qr_data_uri(device)}
    return render_page(request, template, page, status=200)


def codes_step(request, user, *, template: str, self_url: str, finish, context: dict | None = None):
    """Показ резервных кодов; `finish(request, user)` вызывается после «Я сохранил коды»."""
    ip = request.client_ip
    if request.method == "POST":
        if request.POST.get("confirm") != "1" or backup_codes.device_of(user) is None:
            flash(request, "Отметьте, что сохранили резервные коды, чтобы продолжить.", error=True)
            return HttpResponseRedirect(self_url)
        request.session.pop(CODES_PENDING, None)
        return finish(request, user)
    must_issue = (request.session.get(CODES_PENDING) or user.state == UserState.INVITED
                  or backup_codes.device_of(user) is None)
    codes = second_factor.issue_backup_codes(user, ip=ip) if must_issue else None
    if codes is not None:
        request.session[CODES_PENDING] = True
    page = {**(context or {}), "codes": codes, "remaining": backup_codes.remaining(user)}
    return render_page(request, template, page)
