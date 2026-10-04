"""Список сотрудников `/staff/`, карточка слайдером и страница входов (T-244, UX-03, UX-04, FR-004, FR-042).

Список — сетка с фильтром (состояние, роль, строка поиска), сортировкой по заголовку и страницами по 25 строк.
Запрос HTMX с целью `staff-results` получает только сетку: фильтр на странице остаётся тем же элементом.
Карточка открывается слайдером поверх списка (адрес меняется на `/staff/<id>/`); тот же адрес, открытый
напрямую, показывает список с открытой карточкой. Действия карточки — в `staff_actions.py`.
"""
import json
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.core import extensions
from apps.core.models import Role, User, UserState
from apps.core.services import accounts, devices, files, links, lockout, permissions
from apps.core.services.permissions import require_any_permission, require_permission
from apps.integrations.mail import services as mail

from .common import is_fragment, render_page
from .me import RESULT_TITLES

PAGE_SIZE = 25
HISTORY_PAGE_SIZE = 50
SORT_COLUMNS = (("full_name", "ФИО"), ("email", "Почта"), ("position", "Должность"), ("state", "Состояние"))
MAIL_NOTES = {
    "queued": "Последняя попытка не удалась: почтовый сервер недоступен. Портал повторит отправку сам.",
    "failed": "Письмо не доставлено. Проверьте адрес и отправьте приглашение заново.",
}
MAIL_TITLES = {"queued": "в очереди на отправку", "sent": "отправлено", "failed": "не доставлено"}
ROLE_FIELD = "staff-results"


def _query(**params) -> str:
    """Строка запроса без пустых значений: `?state=blocked&q=иван` или пустая."""
    clean = {key: value for key, value in params.items() if value not in ("", None)}
    return "?" + urlencode(clean) if clean else ""


CORE_PRESETS = (
    # (ключ, подпись, порядок, служебный ли — только для `accounts.manage`)
    ("", "В компании", 10, False), ("dismissed", "Уволены", 20, False), ("all", "Все", 40, False),
    ("invited", "Приглашены", 50, True), ("active", "Активные", 60, True), ("blocked", "Заблокированные", 70, True),
)
STATE_SERVICE = {"invited": UserState.INVITED, "active": UserState.ACTIVE, "blocked": UserState.BLOCKED}


def _core_preset_apply(key: str):
    """Функция пресета ядра: «В компании» — все, кроме уволенных; «Все» — без отбора; остальные — по состоянию."""
    if key == "":
        return lambda qs: qs.exclude(state=UserState.DISMISSED)
    if key == "all":
        return lambda qs: qs
    state = UserState.DISMISSED if key == "dismissed" else STATE_SERVICE[key]
    return lambda qs: qs.filter(state=state)


def _directory(viewer) -> dict:
    """Расширения списка (точка `staff_directory`): пресеты, фильтры, поиск, колонки, кнопки; без них — срез 001."""
    can_manage = permissions.has_permission(viewer, "accounts.manage")
    presets = [extensions.Preset(key, title, _core_preset_apply(key), order)
               for key, title, order, service in CORE_PRESETS if can_manage or not service]
    filters, columns, buttons, searches = [], [], [], []
    for func in extensions.registered("staff_directory"):
        found = func(viewer)
        presets += found.presets
        filters += found.filters
        columns += found.columns
        buttons += [b for b in found.buttons if all(permissions.has_permission(viewer, p) for p in b.permissions_all)]
        if found.search is not None:
            searches.append(found.search)
    presets.sort(key=lambda item: item.order)
    columns.sort(key=lambda item: item.order)

    def extra_search(text):
        condition = Q()
        for search in searches:
            condition |= search(text)
        return condition

    return {"can_manage": can_manage, "presets": presets, "filters": filters, "columns": columns,
            "buttons": buttons, "extra_search": extra_search if searches else None}


def _list_context(params, viewer) -> dict:
    directory = _directory(viewer)
    can_manage = directory["can_manage"]
    presets = {item.key: item for item in directory["presets"]}
    state = params.get("state", "")
    if state not in presets:
        state = ""
    role = (params.get("role", "") if can_manage else "")
    query = (params.get("q") or "").strip()
    sort = params.get("sort", "")
    # коллеге — только колонки, которые он видит: порядок по состоянию или датам выдал бы служебное (FR-119, R-2233-3)
    allowed = accounts.SORTABLE if can_manage else {"full_name", "position", "email"}
    if sort.lstrip("-") not in allowed:
        sort = "full_name"
    active = [(item, params.get(item.name, "")) for item in directory["filters"]]
    active = [(item, value) for item, value in active if value not in ("", None)]
    qs = accounts.directory_staff(
        apply_preset=presets[state].apply, role_id=role or None, query=query or None,
        extra_search=directory["extra_search"], filters=[(item.apply, value) for item, value in active], sort=sort)
    page = Paginator(qs, PAGE_SIZE).get_page(params.get("page"))
    for person in page:
        person.photo_src = files.photo_url(person, 96)
        person.initials = files.initials(person.full_name)
    filter_values = {item.name: params.get(item.name, "") for item in directory["filters"]}
    base = dict(state=state, role=role, q=query, sort=sort, **filter_values)
    sort_links = {}
    for column, _ in SORT_COLUMNS:
        sort_links[column] = "/staff/" + _query(**{**base, "sort": "-" + column if sort == column else column})
    sortable = {name: title for name, title in SORT_COLUMNS}
    heads = [{"key": "photo", "title": "Фото"},
             {"key": "name", "title": "ФИО", "sort": "full_name"},
             {"key": "position", "title": "Должность", "sort": "position"}]
    heads += [{"key": item.key, "title": item.title, "template": item.template} for item in directory["columns"]]
    heads += [{"key": "internal-phone", "title": "Внутренний телефон"},
              {"key": "email", "title": "Почта", "sort": "email"}]
    if can_manage:
        heads.append({"key": "state", "title": "Состояние", "sort": "state"})
    for head in heads:
        name = head.get("sort")
        if name in sortable:
            head["url"] = sort_links[name]
            head["mark"] = "↑" if sort == name else "↓" if sort == "-" + name else ""
    return {
        "page": page, "state": state, "role": role, "q": query, "sort": sort, "can_manage": can_manage,
        "roles": Role.objects.order_by("name") if can_manage else [],
        "heads": heads,
        "filters": [{"name": item.name, "label": item.label, "value": filter_values[item.name],
                     "choices": item.choices()} for item in directory["filters"]],
        "buttons": directory["buttons"],
        "chips": [{"state": item.key, "title": item.title, "active": state == item.key,
                   "url": "/staff/" + _query(**{**base, "state": item.key})} for item in directory["presets"]],
        "prev_url": "/staff/" + _query(**base, page=page.previous_page_number()) if page.has_previous() else "",
        "next_url": "/staff/" + _query(**base, page=page.next_page_number()) if page.has_next() else "",
        "sync": json.dumps({"state": state, "role": role, "q": query, "sort": sort, **filter_values},
                           ensure_ascii=False),
        "total": page.paginator.count,
    }


@require_any_permission("staff.view", "accounts.manage")
@require_GET
def staff_list(request):
    if is_fragment(request):
        target = request.headers.get("HX-Target")
        if target == "slider-root":
            return HttpResponse("")  # «×» слайдера: список уже под ним
        if target == ROLE_FIELD:
            response = render(request, "staff/_results.html", _list_context(request.GET, request.user))
            response["Vary"] = "HX-Request"
            return response
    return render_page(request, "staff/list.html", _list_context(request.GET, request.user))


def slider_page(request, body: str, title: str, context: dict, *, with_list: bool = True):
    """Слайдер для HTMX; при прямом открытии — список со слайдером или самостоятельная страница."""
    context = {**context, "slider_body": body, "slider_title": title, "slider_close_url": "/staff/",
               "slider_flashes": True}
    if is_fragment(request):
        response = render(request, "staff/slider_fragment.html", context)
        response["Vary"] = "HX-Request"
        return response
    if with_list:
        return render_page(request, "staff/list.html", {**_list_context({}, request.user), **context})
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
                        "note": MAIL_NOTES.get(message.status, "") if message.last_error else ""}
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


@require_any_permission("staff.view", "accounts.manage")
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
