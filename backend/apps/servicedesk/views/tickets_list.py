"""Список «Заявки» `/tickets/`, счётчик `/tickets/count/` и групповые действия `/tickets/bulk/` (CONTRACT-003, 12.2, 13.2).

Право — пункт меню «Заявки» (`access.menu_visible`): без него 403, без входа — переход на вход. Параметры показа читаются
мягко: неверное и неизвестное значение — как пустое, ни 400, ни 404. Запрос НХ с целью `tickets-grid` получает только
сетку; другой НХ — страницу без базового макета. Своих запросов к заявкам у представления нет: строки даёт
`listing.build`, число — `listing.count`, групповое действие — `assignment.bulk`.
"""
import re
from functools import wraps
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.core.views.common import is_fragment, render_page
from apps.core.widgets import PortalDateInput, parse_date

from ..models import Status
from ..services import access, assignment, dictionaries, listing, queues
from ..services.errors import ServiceDeskError
from ..services.letters import short_name

GRID_ID = "tickets-grid"
ID_FIELDS = ("queue", "category", "priority", "status", "client_unit", "source")
DATE_FIELDS = ("created_from", "created_to")
KINDS = tuple(code for code, _ in Status.Kind.choices if code in ("new", "in_progress", "waiting", "closed"))
PRESET_TITLES = {"mine": "Мои", "unassigned": "Без ответственного", "my_queues": "Мои очереди",
                 "waiting": "Ждут ответа заявителя", "closed": "Закрытые", "all": "Все"}
EMPTY_TEXTS = {
    "mine": "Здесь будут заявки, где вы назначены ответственным и которые ещё не закрыты",
    "unassigned": "Здесь будут открытые заявки ваших очередей, у которых нет ответственного",
    "my_queues": "Здесь будут открытые заявки ваших очередей",
    "waiting": "Здесь будут заявки, которые ждут ответа заявителя",
    "closed": "Здесь будут закрытые заявки",
    "all": "Здесь будут все заявки, которые вам доступны",
}
NOTHING_FOUND = "По вашему запросу заявок нет"
COLUMNS = (("number", "Номер"), ("created", "Создана"), ("last_message", "Последнее сообщение"),
           ("priority", "Критичность"))
KIND_TITLES = dict(Status.Kind.choices)
_DIGITS = re.compile(r"[0-9]{1,9}")
_LONG_DIGITS = re.compile(r"[0-9]{1,18}")


def menu_required(view):
    """Вход обязателен; без пункта меню «Заявки» — 403 (одинаково для существующего и несуществующего)."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not access.menu_visible(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _number(value: str) -> int | None:
    """Целое из строки только из цифр (до девяти знаков), иначе `None`."""
    value = (value or "").strip()
    return int(value) if _DIGITS.fullmatch(value) else None


def _read(query) -> dict:
    """Параметры показа из GET: `params` — очищенные строки для ссылок, `filters` — `listing.Filters`, остальное."""
    params, values = {}, {}
    for name in ID_FIELDS:
        number = _number(query.get(name, ""))
        if number is not None:
            values[name] = number
            params[name] = str(number)
    kind = (query.get("kind") or "").strip()
    if kind in KINDS:
        values["kind"] = kind
        params["kind"] = kind
    assignee = (query.get("assignee") or "").strip()
    if assignee == "none":
        values["assignee"] = "none"
        params["assignee"] = "none"
    elif _number(assignee) is not None:
        values["assignee"] = _number(assignee)
        params["assignee"] = str(values["assignee"])
    for name in DATE_FIELDS:
        raw = (query.get(name) or "").strip()
        day = parse_date(raw)
        if day is not None:
            values[name] = day
            params[name] = raw
    text = (query.get("q") or "").strip()
    if text:
        values["q"] = text
        params["q"] = text
    sort = query.get("sort") if query.get("sort") in listing.SORTS else "number"
    direction = query.get("dir") if query.get("dir") in ("asc", "desc") else "desc"
    page = _number(query.get("page", "")) or 1
    return {"params": params, "filters": listing.Filters(**values), "values": values, "sort": sort, "dir": direction,
            "page": max(page, 1), "sort_given": query.get("sort") in listing.SORTS,
            "dir_given": query.get("dir") in ("asc", "desc"), "preset": query.get("preset")}


def _url(path: str, params: dict) -> str:
    """Адрес с непустыми параметрами."""
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return path + ("?" + urlencode(clean) if clean else "")


def _people() -> list:
    """Действующие сотрудники по ФИО (не заблокированные и не уволенные) для выбора ответственного."""
    users = get_user_model().objects.order_by("full_name", "pk")
    return [{"id": user.pk, "name": user.full_name} for user in users if user.is_active]


def _choices(kind: str, chosen) -> list:
    """Значения справочника для фильтра: действующие и архивные (с меткой); выбранное отмечено."""
    model = dictionaries.model_of(kind)
    ordering = ("name",) if kind == "client_unit" else ("order", "name")
    return [{"id": item.pk, "name": item.name, "archived": item.archived, "selected": item.pk == chosen}
            for item in model.objects.order_by(*ordering)]


def _context(request, bulk=None) -> dict:
    """Всё, что нужно странице списка и сетке."""
    read = _read(request.GET)
    user = request.user
    page = listing.build(user, preset=read["preset"], filters=read["filters"], sort=read["sort"],
                         descending=read["dir"] == "desc", page=read["page"])
    values = read["values"]
    show = {"preset": page.preset, **read["params"]}
    if read["sort_given"]:
        show["sort"] = read["sort"]
    if read["dir_given"]:
        show["dir"] = read["dir"]
    base = {key: value for key, value in show.items() if key not in ("sort", "dir")}
    link_base = {key: value for key, value in show.items() if key != "page"}
    presets = [{"code": code, "title": PRESET_TITLES[code], "active": code == page.preset,
                "url": _url("/tickets/", {**{k: v for k, v in show.items() if k not in ("preset", "page")},
                                          "preset": code})}
               for code in listing.PRESETS]
    columns = {}
    for code, title in COLUMNS:
        active = code == read["sort"]
        flipped = "asc" if read["dir"] == "desc" else "desc"
        columns[code] = {"title": title,
                         "aria_sort": ("descending" if read["dir"] == "desc" else "ascending") if active else "",
                         "url": _url("/tickets/", {**base, "sort": code, "dir": flipped if active else "desc"})}
    filtered = bool(read["params"])
    people = _people()
    assignee = values.get("assignee")
    extra_assignee = None
    if isinstance(assignee, int) and all(person["id"] != assignee for person in people):
        owner = get_user_model().objects.filter(pk=assignee).first()
        if owner is not None:
            extra_assignee = {"id": owner.pk, "name": owner.full_name}
    can_create = access.can_create(user)
    marked = queues.marked_units()
    shown_filters = {name: values.get(name) for name in ("queue", "category", "priority", "status", "client_unit",
                                                         "source")}
    rows = [{"ticket": ticket,
             "requester": ticket.requester_name or ticket.requester_email,
             "closed_by": short_name(ticket.closed_by.full_name) if ticket.closed_by_id else "",
             "closed_by_dismissed": bool(ticket.closed_by_id) and ticket.closed_by.state == "dismissed",
             "assignee_dismissed": bool(ticket.assignee_id) and ticket.assignee.state == "dismissed"}
            for ticket in page.rows]
    return {
        "page": page, "rows": rows, "presets": presets, "cols": columns, "current_sort": read["sort"],
        "current_dir": read["dir"], "sort_given": read["sort_given"], "dir_given": read["dir_given"],
        "values": values, "q": values.get("q", ""), "hint_short": page.hint == "short",
        "queue_choices": [{"id": unit.id, "name": unit.name, "selected": unit.id == values.get("queue")}
                          for unit in marked],
        "category_choices": _choices("category", shown_filters["category"]),
        "priority_choices": _choices("priority", shown_filters["priority"]),
        "status_choices": _choices("status", shown_filters["status"]),
        "client_unit_choices": _choices("client_unit", shown_filters["client_unit"]),
        "source_choices": _choices("source", shown_filters["source"]),
        "kind_choices": [{"code": code, "title": KIND_TITLES[code], "selected": code == values.get("kind")}
                         for code in KINDS],
        "people": people, "extra_assignee": extra_assignee, "assignee_value": assignee,
        "created_from_field": PortalDateInput().render(
            "created_from", read["params"].get("created_from", ""), attrs={"id": "id_created_from"}),
        "created_to_field": PortalDateInput().render(
            "created_to", read["params"].get("created_to", ""), attrs={"id": "id_created_to"}),
        "prev_url": _url("/tickets/", {**link_base, "page": page.page - 1}) if page.page > 1 else "",
        "next_url": _url("/tickets/", {**link_base, "page": page.page + 1}) if page.has_next else "",
        "count_url": _url("/tickets/count/", {key: value for key, value in show.items()
                                              if key not in ("sort", "dir", "page")}),
        "empty_text": NOTHING_FOUND if filtered else EMPTY_TEXTS[page.preset], "filtered": filtered,
        "can_create": can_create,
        "bulk_queues": [{"id": unit.id, "name": unit.name} for unit in marked],
        "bulk_priorities": list(dictionaries.offered("priority")),
        "bulk": bulk,
    }


@menu_required
@require_GET
def ticket_list(request):
    """Список заявок: страница, страница-фрагмент или только сетка (`HX-Target: tickets-grid`)."""
    context = _context(request)
    if is_fragment(request) and request.headers.get("HX-Target") == GRID_ID:
        response = render(request, "servicedesk/list/_grid.html", context)
        response["Vary"] = "HX-Request"
        return response
    return render_page(request, "servicedesk/list/page.html", context)


@menu_required
@require_GET
def ticket_count(request):
    """Общее число заявок по параметрам показа: всегда фрагмент `[data-total]`."""
    read = _read(request.GET)
    total = listing.count(request.user, preset=read["preset"], filters=read["filters"])
    return render(request, "servicedesk/list/_total.html", {"total": total})


def _bulk_numbers(values) -> list[int]:
    """Номера из формы: числа как есть, не число — уникальное отрицательное (такой заявки нет, будет пропуск)."""
    numbers, fake = [], 0
    for value in values:
        text = value.strip()
        if _LONG_DIGITS.fullmatch(text):
            numbers.append(int(text))
        else:
            fake -= 1
            numbers.append(fake)
    return numbers


def _bulk_params(post, action: str) -> dict:
    """Параметры действия по 6.8: `assign` — объект сотрудника или `None`; `transfer` — очередь и причина; `priority`."""
    if action == "assign":
        number = _number(post.get("user", ""))
        user = get_user_model().objects.filter(pk=number).first() if number is not None else None
        return {"user": user}
    if action == "transfer":
        return {"queue_id": _number(post.get("queue", "")), "reason": post.get("reason", "")}
    if action == "priority":
        number = _number(post.get("priority", ""))
        return {"priority_id": number} if number is not None else {}
    return {}


@menu_required
@require_POST
def ticket_bulk(request):
    """Групповое действие: итог «Выполнено: N; пропущено: M»; НХ — фрагмент блока, обычный запрос — страница списка."""
    action = request.POST.get("action", "")
    numbers = _bulk_numbers(request.POST.getlist("numbers"))
    try:
        result = assignment.bulk(numbers, action, actor=request.user, ip=request.client_ip,
                                 **_bulk_params(request.POST, action))
    except ServiceDeskError as refused:
        bulk = {"error": refused.message, "code": refused.code}
    else:
        bulk = {"done": len(result.done), "skipped": len(result.skipped),
                "items": [{"number": item.number, "code": item.code, "message": item.message}
                          for item in result.skipped]}
    if is_fragment(request):
        response = render(request, "servicedesk/list/_bulk_result.html", {"bulk": bulk})
        response["Vary"] = "HX-Request"
        return response
    return render_page(request, "servicedesk/list/page.html", _context(request, bulk=bulk))
