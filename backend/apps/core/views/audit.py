"""Журнал событий `/audit/` и выгрузка `/audit/export.csv` (T-248, UX-04, FR-047, NFR-002).

Только просмотр: ни изменения, ни удаления записей журнала нет (FR-045). Фильтры — период, действующее
лицо, вид действия, объект; пресеты «Сегодня», «Вход и доступ», «Права и роли», «Настройки»; сортировка по
заголовку. Запрос HTMX с целью `audit-results` обновляет только таблицу — форма фильтра остаётся на месте.
Количество событий выборки считается только по ссылке «показать количество» (`count=1`; UX-04, п. 6).
"""
import json
from urllib.parse import urlencode

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.core.services import audit_labels, audit_search
from apps.core.services.permissions import require_permission
from apps.core.widgets import PortalDateInput

from .common import is_fragment, render_page

RESULTS_ID = "audit-results"
FIELDS = ("date_from", "date_to", "user", "action", "object_type", "object_id", "preset")


def _params(request) -> dict:
    """Параметры фильтра без пустых значений (для ссылок сортировки, страниц и выгрузки)."""
    return {name: request.GET.get(name, "").strip() for name in FIELDS if request.GET.get(name, "").strip()}


def _link(params: dict, **extra) -> str:
    """Строка запроса: текущие параметры, поверх них `extra`; пустые значения убираются."""
    merged = {key: value for key, value in {**params, **extra}.items() if value}
    return "?" + urlencode(merged) if merged else ""


@require_permission("audit.view")
@require_GET
def audit_list(request):
    filters = audit_search.parse(request.GET)
    page = audit_search.page_of(filters, request.GET.get("page"))
    params = _params(request)
    sort = filters.sort
    shown_sort = "" if sort == audit_search.DEFAULT_SORT else sort
    params_no_preset = {key: value for key, value in params.items() if key != "preset"}
    context = {
        "page": page, "filters": filters, "actors": audit_search.actors(), "actions": audit_search.known_actions(),
        "action_codes": [code for code, _ in audit_search.known_actions()],
        "object_types": sorted(audit_labels.OBJECT_TYPES.items(), key=lambda item: item[1]), "object_type_codes": list(audit_labels.OBJECT_TYPES),
        "presets": [{"code": code, "title": title, "active": filters.preset == code,
                     "url": "/audit/" + _link(params_no_preset, sort=shown_sort,
                                              preset="" if filters.preset == code else code)}
                    for code, title in audit_search.PRESETS.items()],
        "sort_time": "/audit/" + _link(params, sort="at" if sort == "-at" else "-at"),
        "sort_action": "/audit/" + _link(params, sort="-action" if sort == "action" else "action"),
        "sort_mark": {"time": "↑" if sort == "at" else "↓" if sort == "-at" else "",
                      "action": "↑" if sort == "action" else "↓" if sort == "-action" else ""},
        "prev_url": "/audit/" + _link(params, sort=shown_sort, page=page.previous_page_number()) if page.has_previous() else "",
        "next_url": "/audit/" + _link(params, sort=shown_sort, page=page.next_page_number()) if page.has_next() else "",
        "total": audit_search.count(filters) if request.GET.get("count") == "1" else None,
        "count_url": "/audit/" + _link(params, sort=shown_sort, page=page.number if page.has_previous() else "", count="1"),
        "export_query": _link(params, sort=shown_sort),
        "date_from_field": PortalDateInput().render("date_from", filters.date_from, attrs={"id": "id_date_from"}),
        "date_to_field": PortalDateInput().render("date_to", filters.date_to, attrs={"id": "id_date_to"}),
        "sync": json.dumps({"preset": filters.preset, "sort": sort}, ensure_ascii=False),
    }
    if is_fragment(request) and request.headers.get("HX-Target") == RESULTS_ID:
        response = render(request, "audit/_results.html", context)
        response["Vary"] = "HX-Request"
        return response
    return render_page(request, "audit/list.html", context)


@require_permission("audit.view")
@require_GET
def audit_export(request):
    filters = audit_search.parse(request.GET)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit.csv"'
    response.write("﻿")  # метка порядка байтов: Excel открывает кириллицу правильно
    audit_search.write_csv(response, filters)
    return response
