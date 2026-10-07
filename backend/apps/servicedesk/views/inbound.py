"""Входящие письма: `/servicedesk/inbound/` и повторный разбор (CONTRACT-003, 12.6, 13.8).

Право — «Настройка сервис-деска» (`servicedesk.manage`): без входа — переход на вход, без права — 403, потом объект
(письма нет — 404). Параметры показа читаются мягко: неверное значение — как пустое. Состояние ящика даёт
`mailbox.status`, повторный разбор — `mailbox.reparse`; своих записей в базу у представления нет.
"""
from urllib.parse import urlencode

from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, render_page
from apps.core.widgets import PortalDateInput, parse_date

from ..models import InboundMail
from ..services import mailbox

PAGE_SIZE = 50
LIST_URL = "/servicedesk/inbound/"
TOTAL_ID = "inbound-total"
EMPTY_TEXT = "Писем пока нет"
NOTHING_FOUND = "По вашему запросу писем нет"
QUEUED = "Разбор поставлен в очередь"
NOT_WAITING = "Письмо не ждёт повторного разбора"
DASH = "—"
OUTCOMES = tuple(InboundMail.Outcome.values)


def _read(query) -> dict:
    """Параметры показа: `params` — очищенные строки для ссылок, `values` — разобранные значения."""
    params, values = {}, {}
    outcome = (query.get("outcome") or "").strip()
    if outcome in OUTCOMES:
        params["outcome"] = values["outcome"] = outcome
    for name in ("date_from", "date_to"):
        raw = (query.get(name) or "").strip()
        day = parse_date(raw)
        if day is not None:
            params[name] = raw
            values[name] = day
    page = (query.get("page") or "").strip()
    number = int(page) if page.isascii() and page.isdigit() and len(page) <= 9 else 1
    return {"params": params, "values": values, "page": max(number, 1)}


def _shown(values: dict, name: str) -> str:
    """Значение поля даты для показа: `ДД.ММ.ГГГГ` (ввод в ISO возвращается датой портала)."""
    day = values.get(name)
    return day.strftime("%d.%m.%Y") if day is not None else ""


def _url(params: dict) -> str:
    """Адрес списка с непустыми параметрами."""
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return LIST_URL + ("?" + urlencode(clean) if clean else "")


def _filtered(values: dict):
    """Письма по фильтру: итог и период по времени получения (дата Москвы, границы включены)."""
    rows = InboundMail.objects.all()
    if "outcome" in values:
        rows = rows.filter(outcome=values["outcome"])
    if "date_from" in values:
        rows = rows.filter(received_at__date__gte=values["date_from"])
    if "date_to" in values:
        rows = rows.filter(received_at__date__lte=values["date_to"])
    return rows


@require_permission("servicedesk.manage")
@require_GET
def inbound_list(request):
    """Страница «Входящие письма»: состояние ящика, фильтр, 50 строк на странице; число — только при `count=1`."""
    read = _read(request.GET)
    rows = _filtered(read["values"])
    if request.GET.get("count") == "1":
        if request.headers.get("HX-Target") == TOTAL_ID:
            return render(request, "servicedesk/inbound/_total.html", {"total": rows.count()})
    start = (read["page"] - 1) * PAGE_SIZE
    chunk = list(rows.select_related("ticket").order_by("-received_at", "-id")[start:start + PAGE_SIZE + 1])
    has_next = len(chunk) > PAGE_SIZE
    chunk = chunk[:PAGE_SIZE]
    params = read["params"]
    count_shown = request.GET.get("count") == "1"
    items = [{"mail": mail, "sender": mail.from_email or DASH, "subject": mail.subject or DASH,
              "failed": mail.status == InboundMail.Status.ERROR,
              "ticket_number": mail.ticket.number if mail.ticket_id else None}
             for mail in chunk]
    state = mailbox.status()
    filtered = bool(params)
    context = {
        "mailbox": state, "items": items, "params": params, "filtered": filtered,
        "outcome_choices": [{"code": code, "title": title, "selected": code == params.get("outcome")}
                            for code, title in InboundMail.Outcome.choices],
        "date_from_field": PortalDateInput().render("date_from", _shown(read["values"], "date_from"),
                                                    attrs={"id": "id_date_from"}),
        "date_to_field": PortalDateInput().render("date_to", _shown(read["values"], "date_to"),
                                                  attrs={"id": "id_date_to"}),
        "page": read["page"],
        "prev_url": _url({**params, "page": read["page"] - 1}) if read["page"] > 1 else "",
        "next_url": _url({**params, "page": read["page"] + 1}) if has_next else "",
        "count_url": _url({**params, "count": 1}),
        "total": rows.count() if count_shown else None, "total_id": TOTAL_ID,
        "empty_text": NOTHING_FOUND if filtered or read["page"] > 1 else EMPTY_TEXT,
    }
    return render_page(request, "servicedesk/inbound/page.html", context)


@require_permission("servicedesk.manage")
@require_POST
def inbound_retry(request, inbound_id):
    """«Разобрать снова»: письмо в `error` — разбор в очередь; иначе сообщение; письма нет — 404 (из службы)."""
    try:
        queued = mailbox.reparse(inbound_id, actor=request.user)
    except InboundMail.DoesNotExist:
        raise Http404
    flash(request, QUEUED if queued else NOT_WAITING)
    return HttpResponseRedirect(LIST_URL)
