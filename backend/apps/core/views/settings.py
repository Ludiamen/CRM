"""Настройки `/settings/…` (T-249, FR-027, FR-036, FR-039, FR-048, FR-049, FR-053).

Портал — название, логотип (только PNG и JPEG, FR-049) и «Вернуть по умолчанию»; безопасность — политика
паролей и сессий, пороги блокировки и срок хранения истории входов только в границах, которые не ослабляют
утверждённые значения; журнал доставки писем. Проверка и журнал событий — в сервисах.
"""
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.services import portal_settings, security_settings
from apps.core.services.permissions import require_permission
from apps.integrations.mail import services as mail

from .common import flash, render_page

PORTAL_URL = "/settings/portal/"
SECURITY_URL = "/settings/security/"

# Разделы формы политики: заголовок и поля в порядке показа
SECURITY_GROUPS = (
    ("Пароли", ("password_min_length", "password_history", "password_max_age_days")),
    ("Сессия", ("idle_timeout_minutes",)),
    ("Блокировка записи", ("account_lock_limit", "account_lock_minutes")),
    ("Блокировка адреса", ("ip_lock_limit", "ip_lock_min_accounts", "ip_lock_window_minutes", "ip_lock_minutes")),
    ("История входов", ("login_history_days",)),
)


@require_permission("settings.portal")
@require_http_methods(["GET", "POST"])
def portal(request):
    errors, name = {}, None
    if request.method == "POST":
        reset = request.POST.get("reset") == "1"
        name = request.POST.get("name")
        try:
            portal_settings.update(name=name, logo=request.FILES.get("logo"), reset=reset,
                                   actor=request.user, ip=request.client_ip)
        except portal_settings.PortalSettingsError as error:
            errors = error.errors
        else:
            flash(request, "Название и логотип возвращены по умолчанию." if reset else "Настройки портала сохранены.")
            return HttpResponseRedirect(PORTAL_URL)
    row = portal_settings.get()
    context = {"row": row, "name": name if name is not None else row.name, "errors": errors,
               "max_name": portal_settings.MAX_NAME_LENGTH, "default_name": portal_settings.DEFAULT_NAME}
    return render_page(request, "settings/portal.html", context)


def _security_fields(values: dict, errors: dict) -> list:
    rows = []
    for title, names in SECURITY_GROUPS:
        fields = []
        for field in names:
            bound = security_settings.BOUNDS[field]
            raw = values.get(field)
            fields.append({"name": field, "title": bound.title, "unit": bound.unit, "low": bound.low,
                           "high": bound.high, "optional": bound.optional,
                           "value": "" if raw is None else raw, "error": errors.get(field, "")})
        rows.append({"title": title, "fields": fields})
    return rows


@require_permission("settings.security")
@require_http_methods(["GET", "POST"])
def security(request):
    errors = {}
    values = security_settings.as_dict(security_settings.get())
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in security_settings.FIELDS}
        try:
            security_settings.update(values, actor=request.user, ip=request.client_ip)
        except security_settings.SettingsError as error:
            errors = error.errors
        else:
            flash(request, "Настройки безопасности сохранены. Новые правила действуют для новых паролей и сессий.")
            return HttpResponseRedirect(SECURITY_URL)
    return render_page(request, "settings/security.html",
                       {"groups": _security_fields(values, errors), "errors": list(errors.values())})


@require_permission("settings.portal")
@require_GET
def mail_log(request):
    return render_page(request, "settings/mail_log.html", {"page": mail.delivery_log(page=request.GET.get("page"))})
