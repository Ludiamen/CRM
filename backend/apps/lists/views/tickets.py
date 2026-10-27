"""Представления: связи записей с заявками (срез 006; PLAN-006, «Связь с заявками»; CONTRACT-006, 10.2, 10.4, 11.8).

Представления тонкие: права и поиск — в `services.tickets`. Без сервис-деска, без видимой заявки, без записи или без
права чтения списка — 404 (один ответ). Отказ «запись в архиве» — 200 с разделом и `[role=alert]`. Ответ привязки и
отвязки — раздел целиком в оболочке `[data-card-part]` (`hx-swap="outerHTML"`), как у `knowledge`.
"""
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from apps.core.views.common import is_fragment, render_page
from apps.lists.services import tickets
from apps.lists.services.errors import ListsError

KEY = "lists-records"
MAX_NUMBER = 2_147_483_647


def _number(value) -> int:
    """Целое положительное из ASCII-цифр; иное — `Http404` (такой заявки или записи нет)."""
    text = str(value or "").strip()
    if not re.fullmatch(r"[0-9]+", text) or not 0 < int(text) <= MAX_NUMBER:
        raise Http404("Нет такого номера")
    return int(text)


def _gate() -> None:
    if not tickets.installed():
        raise Http404("Страница не найдена")


def _section(request, number: int, *, alert: ListsError | None = None) -> HttpResponse:
    """Раздел целиком в оболочке сервис-деска; обычный запрос — переход на карточку заявки."""
    if not is_fragment(request):
        return redirect(f"/tickets/{number}/")
    html = render_to_string("lists/_ticket_section.html", tickets.section_context(request.user, number, alert=alert),
                            request=request)
    response = HttpResponse(format_html('<div data-card-part="{}" data-part-kind="section">{}</div>', KEY,
                                        mark_safe(html)))
    response["Vary"] = "HX-Request"
    return response


@login_required
@require_GET
def pick(request):
    """GET `/lists/ticket-pick/?ticket=&q=`: до 10 записей — «Название — Список»; заявка не видна — 404."""
    _gate()
    found = tickets.pick(request.user, _number(request.GET.get("ticket")), request.GET.get("q", ""))
    rows = [{"id": record.pk, "title": f"{record.title} — {record.list.name}"} for record in found]
    return render_page(request, "lists/_pick.html", {"rows": rows, "kind": "tickets"})


@login_required
@require_POST
def link_add(request):
    """POST `/lists/ticket-links/` (`ticket`, `record`): привязать запись; ответ — раздел заявки целиком."""
    _gate()
    number, record_id = _number(request.POST.get("ticket")), _number(request.POST.get("record"))
    try:
        tickets.link(request.user, number, record_id)
    except ListsError as refusal:
        return _section(request, number, alert=refusal)
    return _section(request, number)


@login_required
@require_POST
def link_delete(request, link_id: int):
    """POST `/lists/ticket-links/<id>/delete/`: отвязать запись; ответ — раздел заявки целиком."""
    _gate()
    return _section(request, tickets.unlink(request.user, link_id))
