"""Увольнение и возврат сотрудника: диалоги и действия (FR-124…129, FR-123; T-2231).

GET — диалог с последствиями и «Отменой» (фрагмент HTMX; без HTMX — страница целиком с диалогом, FR-108),
POST — действие службы `org.services.people`. Отказ службы — 200 с `[role=alert]`. Права проверяют декораторы (T-2230a).
"""
from urllib.parse import urlsplit

from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from apps.core.models import User
from apps.core.services import accounts, roles
from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, is_fragment, render_page
from apps.org.services import people as people_service

RULE_ERRORS = (accounts.AccountError, roles.RoleError)

DISMISS_CONSEQUENCES = (
    "Вход закрыт: пароль, открытые сессии и ссылки активации и восстановления перестанут действовать.",
    "Сотрудник уйдёт из всех подразделений; отметки руководителя и заместителя снимаются.",
    "Личные роли будут сняты.",
    "Карточка останется только для чтения; данные сотрудника сохраняются, письма ему не отправляются.",
)
REHIRE_CONSEQUENCES = (
    "Сотруднику уйдёт новое приглашение на 72 часа; запись станет «приглашён».",
    "Прежние пароль, второй фактор, резервные коды и запомненные устройства станут недействительными.",
    "Будет назначена роль «Сотрудник ИТ».",
    "Подразделения и остальные роли нужно вернуть вручную.",
)


def _safe_next(request, value: str) -> str:
    """Относительный путь этого сайта или пусто: чужой хост и `//…` игнорируются."""
    value = (value or "").strip()
    if value.startswith("/") and not value.startswith("//") and url_has_allowed_host_and_scheme(
            value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return ""


def _opened_from(request) -> str:
    """Путь страницы, откуда открыт диалог: `?next=`, иначе адрес страницы из `HX-Current-URL`."""
    explicit = _safe_next(request, request.GET.get("next", ""))
    if explicit:
        return explicit
    current = request.headers.get("HX-Current-URL", "")
    if current:
        parts = urlsplit(current)
        return _safe_next(request, parts.path + (f"?{parts.query}" if parts.query else ""))
    return ""


def _dialog_context(target: User, *, rehire: bool, next_url: str, error: str = "") -> dict:
    name = "rehire" if rehire else "dismiss"
    return {
        "dialog": name, "dialog_error": error, "dialog_next": next_url, "target": target,
        "dialog_title": f"Вернуть на работу: {target.full_name}?" if rehire else f"Уволить: {target.full_name}?",
        "dialog_action": f"/structure/people/{target.pk}/{name}/", "dialog_danger": not rehire,
        "dialog_submit": "Вернуть на работу" if rehire else "Уволить",
        "consequences": REHIRE_CONSEQUENCES if rehire else DISMISS_CONSEQUENCES,
        "dialog_back_url": f"/staff/{target.pk}/",
    }


def _respond(request, context: dict, *, status: int = 200):
    """Фрагмент диалога для HTMX; без HTMX — страница с диалогом внутри `#dialog-root`."""
    if is_fragment(request):
        response = render(request, "org/_dialog.html", context, status=status)
        response["Vary"] = "HX-Request"
        return response
    return render_page(request, "org/dialog_page.html", context, status=status)


@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def dismiss(request, user_id: int):
    """`/structure/people/<user_id>/dismiss/` — диалог и увольнение; `next` — куда вернуться."""
    target = get_object_or_404(User, pk=user_id)
    if request.method == "GET":
        return _respond(request, _dialog_context(target, rehire=False, next_url=_opened_from(request)))
    next_url = _safe_next(request, request.POST.get("next", ""))
    try:
        people_service.dismiss(target, actor=request.user, ip=request.client_ip)
    except RULE_ERRORS as error:
        return _respond(request, _dialog_context(target, rehire=False, next_url=next_url, error=str(error)))
    flash(request, f"{target.full_name} уволен.")
    return HttpResponseRedirect(next_url or f"/staff/{target.pk}/")


@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def rehire(request, user_id: int):
    """`/structure/people/<user_id>/rehire/` — диалог и возврат на работу."""
    target = get_object_or_404(User, pk=user_id)
    if request.method == "GET":
        return _respond(request, _dialog_context(target, rehire=True, next_url=""))
    try:
        people_service.rehire(target, actor=request.user, ip=request.client_ip)
    except RULE_ERRORS as error:
        return _respond(request, _dialog_context(target, rehire=True, next_url="", error=str(error)))
    flash(request, f"{target.full_name} возвращён на работу, приглашение отправлено.")
    return HttpResponseRedirect(f"/staff/{target.pk}/")
