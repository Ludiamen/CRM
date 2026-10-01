"""Общее для представлений: полная страница или фрагмент HTMX, разовые сообщения, адрес и браузер клиента."""
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme

from apps.core.services import sessions

FLASH_KEY = "flashes"


def is_fragment(request) -> bool:
    """Ответ на запрос HTMX — фрагмент; обычный запрос и восстановление истории браузера — полная страница."""
    headers = request.headers
    return (headers.get("HX-Request") == "true" and not headers.get("HX-History-Restore-Request")
            and headers.get("HX-Boosted") != "true")


def layout_for(request) -> str:
    """Какой шаблон оборачивает страницу: фрагмент, оболочка вошедшего или публичная страница."""
    if is_fragment(request):
        return "layouts/fragment.html"
    user = request.user
    if user.is_authenticated and not sessions.is_limited(request):
        return "base.html"
    return "base_public.html"


def render_page(request, template: str, context: dict | None = None, *, status: int = 200):
    context = {**(context or {}), "layout": layout_for(request)}
    response = render(request, template, context, status=status)
    response["Vary"] = "HX-Request"
    return response


def flash(request, text: str, *, error: bool = False) -> None:
    """Разовое сообщение для следующей страницы: `[role=status]` или `[role=alert]`."""
    items = request.session.get(FLASH_KEY, [])
    items.append({"text": text, "level": "danger" if error else "success", "role": "alert" if error else "status"})
    request.session[FLASH_KEY] = items


def user_agent(request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")


def safe_next(request, value: str | None, default: str = "/") -> str:
    """Адрес возврата после входа: только свой хост, иначе `default`."""
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()},
                                                 require_https=request.is_secure()):
        return value
    return default
