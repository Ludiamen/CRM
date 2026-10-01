"""Список сотрудников `/staff/`, карточка слайдером и страница входов (T-244, UX-03, UX-04, FR-004, FR-042).

Список — сетка с фильтром (состояние, роль, строка поиска), сортировкой по заголовку и страницами по 25 строк.
Запрос HTMX с целью `staff-results` получает только сетку: фильтр на странице остаётся тем же элементом.
Карточка открывается слайдером поверх списка (адрес меняется на `/staff/<id>/`); тот же адрес, открытый
напрямую, показывает список с открытой карточкой. Действия карточки — в `staff_actions.py`.
"""
import json
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.core.models import Role, User, UserState
from apps.core.services import accounts, devices, links, lockout, permissions
from apps.core.services.permissions import require_permission
from apps.integrations.mail import services as mail

from .common import is_fragment, render_page
from .me import RESULT_TITLES

PAGE_SIZE = 25
HISTORY_PAGE_SIZE = 50
SORT_COLUMNS = (("full_name", "ФИО"), ("email", "Почта"), ("position", "Должность"), ("state", "Состояние"))
STATE_CHIPS = (("", "Все"), ("active", "Активные"), ("invited", "Приглашённые"), ("blocked", "Заблокированные"))
MAIL_TITLES = {"queued": "в очереди на отправку", "sent": "отправлено", "failed": "не доставлено"}
ROLE_FIELD = "staff-results"


def _query(**params) -> str:
    """Строка запроса без пустых значений: `?state=blocked&q=иван` или пустая."""
    clean = {key: value for key, value in params.items() if value not in ("", None)}
    return "?" + urlencode(clean) if clean else ""


def _list_context(params) -> dict:
    state = params.get("state", "")
    if state not in {s.value for s in UserState}:
        state = ""
    role = params.get("role", "")
    query = (params.get("q") or "").strip()
    sort = params.get("sort", "")
    if sort.lstrip("-") not in accounts.SORTABLE:
        sort = "full_name"
    qs = accounts.list_staff(state=state or None, role_id=role or None, query=query or None, sort=sort)
    page = Paginator(qs, PAGE_SIZE).get_page(params.get("page"))
    base = dict(state=state, role=role, q=query, sort=sort)
    sort_links = {}
    for column, _ in SORT_COLUMNS:
        sort_links[column] = "/staff/" + _query(**{**base, "sort": "-" + column if sort == column else column})
    return {
        "page": page, "state": state, "role": role, "q": query, "sort": sort,
        "roles": Role.objects.order_by("name"),
        "columns": [{"name": name, "title": title, "url": sort_links[name],
                     "mark": "↑" if sort == name else "↓" if sort == "-" + name else ""}
                    for name, title in SORT_COLUMNS],
        "chips": [{"state": value, "title": title, "active": state == value,
                   "url": "/staff/" + _query(**{**base, "state": value})} for value, title in STATE_CHIPS],
        "prev_url": "/staff/" + _query(**base, page=page.previous_page_number()) if page.has_previous() else "",
        "next_url": "/staff/" + _query(**base, page=page.next_page_number()) if page.has_next() else "",
        "sync": json.dumps({"state": state, "role": role, "q": query, "sort": sort}, ensure_ascii=False),
        "total": page.paginator.count,
    }


@require_permission("accounts.manage")
@require_GET
def staff_list(request):
    if is_fragment(request):
        target = request.headers.get("HX-Target")
        if target == "slider-root":
            return HttpResponse("")  # «×» слайдера: список уже под ним
        if target == ROLE_FIELD:
            response = render(request, "staff/_results.html", _list_context(request.GET))
            response["Vary"] = "HX-Request"
            return response
    return render_page(request, "staff/list.html", _list_context(request.GET))


def slider_page(request, body: str, title: str, context: dict, *, with_list: bool = True):
    """Слайдер для HTMX; при прямом открытии — список со слайдером или самостоятельная страница."""
    context = {**context, "slider_body": body, "slider_title": title, "slider_close_url": "/staff/",
               "slider_flashes": True}
    if is_fragment(request):
        response = render(request, "staff/slider_fragment.html", context)
        response["Vary"] = "HX-Request"
        return response
    if with_list:
        return render_page(request, "staff/list.html", {**_list_context({}), **context})
    return render_page(request, "staff/standalone.html", context)


def _invitation(request, target) -> dict:
    """Ссылка активации и состояние письма в карточке приглашённого; показ ссылки пишется в журнал (FR-009)."""
    info = {"url": "", "mail": None}
    link = links.current_activation_link(target)
    if link is not None:
        code = links.reveal(link, actor=request.user, ip=request.client_ip)
        if code:
            info["url"] = links.invitation_url(code)
    message = mail.last_message(target, "invitation")
    if message is not None:
        info["mail"] = {"status": message.status, "title": MAIL_TITLES.get(message.status, message.status),
                        "error": message.last_error}
    return info


def card_context(request, target) -> dict:
    granted = permissions.permissions_of(request.user)
    is_self = target.pk == request.user.pk
    context = {
        "target": target, "is_self": is_self,
        "all_roles": Role.objects.order_by("name"),
        "target_role_ids": set(target.roles.values_list("pk", flat=True)),
        "can_reset_2fa": "accounts.reset_2fa" in granted and not is_self,
        "can_view_logins": "accounts.view_logins" in granted,
        "login_locked": lockout.is_account_locked(str(target.pk)),
        "invitation": _invitation(request, target) if target.state == UserState.INVITED else None,
    }
    return context


@require_permission("accounts.manage")
@require_GET
def staff_card(request, user_id: int):
    target = get_object_or_404(User, pk=user_id)
    return slider_page(request, "staff/_card.html", target.full_name, card_context(request, target))


@require_permission("accounts.view_logins")
@require_GET
def staff_logins(request, user_id: int):
    """Устройства и история входов сотрудника: только с правом `accounts.view_logins` (FR-042)."""
    target = get_object_or_404(User, pk=user_id)
    page = Paginator(devices.history(target), HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    for row in page:
        row.result_title = RESULT_TITLES.get(row.result, row.result)
    context = {"target": target, "devices": list(devices.known_devices(target)), "page": page,
               "can_manage": permissions.has_permission(request.user, "accounts.manage")}
    return slider_page(request, "staff/_logins.html", f"Входы: {target.full_name}", context,
                       with_list=context["can_manage"])
