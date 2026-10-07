"""Заявка от исполнителя: `/tickets/new/` и выбор полей (CONTRACT-003, 12.3, 13.6).

Право — `executor.can_start`: без входа — переход на вход, без права — 403 (одинаково для любого адреса и метода).
`requester/` отвечает только на POST (адрес почты — в теле запроса, а не в адресе), `queue/` — на GET; оба всегда
отдают фрагмент-обёртку, которую страница заменяет целиком. Разбор строк формы: пусто — `None`, не число — `0`
(строки с таким номером нет), поэтому неизвестное значение не даёт 500, а отказ службы.
"""
import re
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.views.common import flash, render_page

from ..services import attachments, dictionaries, executor, queues, requesters, settings
from ..services.errors import ServiceDeskError

_DIGITS = re.compile(r"[0-9]{1,9}")
FIELD_OF_CODE = {
    "bad_email": "email", "requester_name_too_long": "name", "subject_required": "subject",
    "subject_too_long": "subject", "description_required": "text", "description_too_long": "text",
    "category_required": "category", "queue_required": "queue", "not_queue": "queue", "source_required": "source",
}
FIELDS = ("email", "name", "client_unit", "category", "queue", "priority", "source", "subject", "text")


def can_start_required(view):
    """Вход обязателен; без права заводить заявки — 403."""
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not executor.can_start(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _ident(raw) -> int | None:
    """Номер из поля формы: пусто — `None`, не число — `0` (такой строки нет)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    return int(raw) if _DIGITS.fullmatch(raw) else 0


def _text_id(raw) -> str:
    """Номер для сравнения с `option`: только цифры, иначе пусто."""
    raw = (raw or "").strip()
    return raw if _DIGITS.fullmatch(raw) else ""


def _queue_state(user, category_id, queue_id) -> dict:
    """Фрагмент выбора очереди: отмеченные узлы, выбранная очередь и состояние флажка «Взять себе»."""
    marked = queues.marked_units()
    ids = {unit.id for unit in marked}
    selected = queue_id if queue_id in ids else None
    if selected is None and queue_id is None:
        try:
            selected = executor.queue_for_category(category_id)
        except ServiceDeskError:
            selected = queues.default_unit_id()
        if selected not in ids:
            selected = queues.default_unit_id()
    enabled = executor.can_take(user, selected)
    return {"queue_choices": [{"id": unit.id, "name": unit.name, "selected": unit.id == selected} for unit in marked],
            "take_enabled": enabled, "take_checked": enabled}


def _page_context(request, values: dict, *, take, error=None) -> dict:
    """Контекст страницы: значения полей, выборы справочников, отказ службы (`error`)."""
    user = request.user
    category = _ident(values.get("category"))
    queue_value = values.get("queue")
    queue_id = _ident(queue_value) if queue_value is not None else None
    state = _queue_state(user, category, queue_id)
    if take is not None:
        state["take_checked"] = state["take_enabled"] and take
    unit = _text_id(values.get("client_unit"))
    priority = _text_id(values.get("priority")) or str(settings.get().default_priority_id)
    source = _text_id(values.get("source"))
    category_value = _text_id(values.get("category"))
    context = {
        "values": values, "state": state, "error": error, "field_error": None, "general_error": None,
        "category_choices": [{"id": c.pk, "name": c.name, "selected": str(c.pk) == category_value}
                             for c in dictionaries.offered("category")],
        "priority_choices": [{"id": p.pk, "name": p.name, "selected": str(p.pk) == priority}
                             for p in dictionaries.offered("priority")],
        "source_choices": [{"id": s.pk, "name": s.name, "selected": str(s.pk) == source}
                           for s in dictionaries.manual_sources()],
        "unit_choices": [{"id": u.pk, "name": u.name, "selected": str(u.pk) == unit}
                         for u in dictionaries.offered("client_unit")],
        "requester_name": values.get("name", ""),
    }
    if error is not None:
        field = FIELD_OF_CODE.get(error.code)
        if field:
            context["field_error"] = {"field": field, "code": error.code, "text": str(error)}
        else:
            context["general_error"] = {"code": error.code, "text": str(error)}
    return context


@can_start_required
@require_http_methods(["GET", "POST"])
def ticket_new(request):
    """Страница «Новая заявка»; POST создаёт заявку и переходит в карточку (видна) или в список (не видна)."""
    if request.method == "GET":
        return render_page(request, "servicedesk/new/page.html", _page_context(request, {}, take=None))
    post = request.POST
    values = {name: post.get(name, "") for name in FIELDS}
    take = bool(post.get("take"))
    try:
        parts = [attachments.from_upload(f) for f in request.FILES.getlist("files")]
        result = executor.create(
            actor=request.user, email=post.get("email", ""), name=post.get("name", ""),
            client_unit_id=_ident(post.get("client_unit")), category_id=_ident(post.get("category")),
            queue_id=_ident(post.get("queue")), priority_id=_ident(post.get("priority")),
            source_id=_ident(post.get("source")), subject=post.get("subject", ""), text=post.get("text", ""),
            take=take, parts=parts, ip=request.client_ip)
    except ServiceDeskError as error:
        return render_page(request, "servicedesk/new/page.html", _page_context(request, values, take=take, error=error))
    ticket = result.created.ticket
    if result.visible:
        target = f"/tickets/{ticket.number}/"
    else:
        target = "/tickets/"
        flash(request, f"Заявка #{ticket.number} создана в очереди «{ticket.queue.name}»")
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=200)
        response["HX-Redirect"] = target
        return response
    response = HttpResponse(status=302)
    response["Location"] = target
    return response


@can_start_required
@require_POST
def requester_fields(request):
    """Поля ФИО и подразделения, заполненные по адресу из тела запроса (только полный корпоративный известный адрес)."""
    hint = requesters.lookup(request.POST.get("email", ""))
    unit = str(hint.client_unit_id) if hint.found and hint.client_unit_id is not None else ""
    context = {"requester_name": hint.name if hint.found else "",
               "unit_choices": [{"id": u.pk, "name": u.name, "selected": str(u.pk) == unit}
                                for u in dictionaries.offered("client_unit")]}
    return render(request, "servicedesk/new/_requester_fields.html", context)


@can_start_required
@require_GET
def queue_fields(request):
    """Выбор очереди и флажок «Взять себе»: очередь из запроса, иначе очередь категории или по умолчанию."""
    category_id = _ident(_text_id(request.GET.get("category")))
    queue_id = _ident(request.GET.get("queue"))
    return render(request, "servicedesk/new/_queue_fields.html",
                  {"state": _queue_state(request.user, category_id, queue_id)})
