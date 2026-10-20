"""Представления поиска: всплывающая выдача, страница результатов, число группы и «Показать ещё» (PLAN-005, «Адреса»;
CONTRACT-005, 10.6).

Только `GET` и только для вошедших. Строка запроса нигде не сохраняется и не пишется в журнал; на любой запрос — 200:
короткий и длинный запрос дают подсказку (страница) или пустой ответ (окно, число, порция).
"""
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.core.views.common import render_page
from apps.search import parse as parsing
from apps.search import services

MAX_OFFSET = 1_000_000  # предел смещения: больше столбец `OFFSET` не нужен и переполнять его незачем
HINTS = {"short": "Введите не меньше 2 знаков", "long": "Запрос не длиннее 200 знаков"}


def _query(request) -> tuple[str, "parsing.ParsedQuery"]:
    q = request.GET.get("q", "")
    return q, parsing.parse(q)


def _offset(request) -> int:
    try:
        value = int(request.GET.get("offset", "0"))
    except ValueError:
        return 0
    return min(max(value, 0), MAX_OFFSET)


@login_required
@require_GET
def popup(request):
    """Окно выдачи: фрагмент `[data-search-popup]`, по 5 строк в группе, без чисел; на подсказку — пустой."""
    q, parsed = _query(request)
    groups = services.popup(request.user, parsed)
    return render(request, "search/_popup.html", {"groups": groups, "q": q, "q_url": quote(q.strip(), safe="")})


@login_required
@require_GET
def results(request):
    """Страница результатов: по 20 строк в группе; число группы подгружается отдельно."""
    q, parsed = _query(request)
    groups = services.page(request.user, parsed)
    return render_page(request, "search/results.html", {
        "groups": groups, "q": q, "q_url": quote(q.strip(), safe=""), "hint": parsed.hint,
        "hint_text": HINTS.get(parsed.hint, "")})


@login_required
@require_GET
def count(request):
    """Число группы: `span[data-search-count-value]`; неизвестная, недоступная или упавшая группа — пустое тело."""
    _, parsed = _query(request)
    found = services.count(request.user, parsed, request.GET.get("group", ""))
    if found is None:
        return HttpResponse("")
    return render(request, "search/_count.html", {"count": found})


@login_required
@require_GET
def more(request):
    """Следующие 20 строк группы и, если есть ещё, новая кнопка; за концом и неизвестная группа — пустой ответ."""
    q, parsed = _query(request)
    key = request.GET.get("group", "")
    group = services.more_group(request.user, parsed, key, _offset(request))
    if group is None:
        return HttpResponse("")
    return render(request, "search/_more.html", {"group": group, "q": q, "q_url": quote(q.strip(), safe="")})
