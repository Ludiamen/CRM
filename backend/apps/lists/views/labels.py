"""Представления: Этикетки и QR (T-6223; PLAN-006, «Этикетки»; CONTRACT-006, 10.2, 11.9, 15.6).

Читающий список видит этикетки; не читающий — 404, как у несуществующего. Записи в архиве печатаются, номера
несуществующих записей на листе пропускаются молча; одиночная этикетка несуществующей записи — 404. Журнал не пишется.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.decorators.http import require_GET

from apps.core.views.common import render_page
from apps.lists.services import access, labels
from apps.lists.services.errors import ListsError


def _numbers(request) -> list[int]:
    """Номера из повторяющегося `n`: только цифры 0–9, без повторов, порядок запроса."""
    seen: list[int] = []
    for raw in request.GET.getlist("n"):
        if raw.isascii() and raw.isdigit() and int(raw) not in seen:
            seen.append(int(raw))
    return seen


@login_required
@require_GET
def label(request, list_id: int, number: int):
    """Одна этикетка записи (лист с одной этикеткой)."""
    lst = access.get_list(request.user, list_id)
    found = labels.records_by_numbers(lst, [number])
    if not found:
        raise Http404("Запись не найдена")
    context = {"lst": lst, "page": "label", "items": labels.build(lst, found, request.user)}
    return render_page(request, "lists/labels.html", context)


@login_required
@require_GET
def sheet(request, list_id: int):
    """Лист этикеток отмеченных номеров: до 100, недоступные пропускаются."""
    lst = access.get_list(request.user, list_id)
    numbers = _numbers(request)
    context = {"lst": lst, "page": "labels", "items": []}
    if len(numbers) > labels.LIMIT:
        context["alert"] = ListsError("labels_too_many")
    else:
        context["items"] = labels.build(lst, labels.records_by_numbers(lst, numbers), request.user)
    return render_page(request, "lists/labels.html", context)
