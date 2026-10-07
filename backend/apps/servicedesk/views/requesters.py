"""Заявители и загрузка таблицы заявителей (CONTRACT-003, 12.6, 13.8, 14.2).

Все страницы — только с правом `servicedesk.manage` (без входа — переход на вход, без права — 403 одинаково для
существующей и несуществующей записи; потом уже 404). Правила записи и загрузки — в службах `requesters` и
`requester_import`; здесь только форма, ответ и тексты. Файл читается в память и нигде не хранится (FR-265).
Отказ службы на POST — ответ 200 с тем же шаблоном и текстом отказа в `[role=alert]`; база не меняется.
"""
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import is_fragment, render_page

from ..models import ClientUnit, Requester, RequesterImport
from ..services import requester_import as import_service
from ..services import requesters as requesters_service
from ..services.errors import ServiceDeskError

LIST_URL = "/servicedesk/requesters/"
IMPORT_URL = "/servicedesk/requesters/import/"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NO_FILE = "Выберите файл таблицы (CSV или XLSX)."
NOT_CONFIRMED = "Подтвердите действие"
ORIGIN_TITLES = dict(Requester.Origin.choices)
ROW_LABELS = {"will_add": "будет добавлен", "will_update": "будет обновлён", "unchanged": "без изменений",
              "added": "добавлен", "updated": "обновлён"}
FORMAT_HELP = ("ФИО, почта и подразделение работников общества хранятся, чтобы определять подразделение заявителя "
               "по адресу письма")
manage_required = require_permission("servicedesk.manage")


def _number(value) -> int | None:
    """Целое из строки только из цифр, иначе `None` (неверное значение — как пустое)."""
    text = str(value or "").strip()
    return int(text) if text.isascii() and text.isdigit() and len(text) <= 18 else None


def _unit_choices(current_id: int | None, selected_id: int | None, *, all_units: bool = False) -> list[dict]:
    """Подразделения для выбора: неархивные и текущее (пусть архивное); в фильтре — все, архивные с меткой."""
    units = ClientUnit.objects.order_by("name", "id")
    return [{"id": unit.pk, "name": unit.name, "archived": unit.archived, "selected": unit.pk == selected_id}
            for unit in units if all_units or not unit.archived or unit.pk == current_id]


def _list_context(request, **extra) -> dict:
    query = " ".join(request.GET.get("q", "").split())
    unit_id = _number(request.GET.get("client_unit"))
    number = _number(request.GET.get("page")) or 1
    page = requesters_service.page(query=query, client_unit_id=unit_id, number=number)
    params = {"q": query, "client_unit": unit_id or ""}
    base = "?" + "&".join(f"{key}={value}" for key, value in params.items() if value != "")
    glue = "&" if len(base) > 1 else "?"
    rows = [{"requester": row.requester, "tickets_count": row.tickets_count,
             "origin": ORIGIN_TITLES.get(row.requester.origin, ""),
             "unit": row.requester.client_unit.name if row.requester.client_unit_id else ""}
            for row in page.rows]
    return {"rows": rows, "page": page.page, "has_next": page.has_next, "q": query,
            "unit_choices": _unit_choices(None, unit_id, all_units=True), "filtered": bool(query or unit_id),
            "prev_url": f"{LIST_URL}{base}{glue}page={page.page - 1}" if page.page > 1 else "",
            "next_url": f"{LIST_URL}{base}{glue}page={page.page + 1}" if page.has_next else "", **extra}


@manage_required
@require_GET
def requester_list(request):
    """`/servicedesk/requesters/` — таблица заявителей: поиск, фильтр по подразделению, 50 строк на странице."""
    return render_page(request, "servicedesk/requesters/list.html", _list_context(request))


def _form_response(request, record, *, name=None, unit_id=None, error=None, code="", status=200):
    """Форма правки: НХ — только слайдер; обычный запрос — список со слайдером."""
    shown_unit = record.client_unit_id if unit_id is None else unit_id
    form = {"record": record, "name": record.full_name if name is None else name, "error": error, "code": code,
            "choices": _unit_choices(record.client_unit_id, shown_unit)}
    if is_fragment(request):
        return render_page(request, "servicedesk/requesters/edit.html", {"form": form}, status=status)
    return render_page(request, "servicedesk/requesters/list.html", _list_context(request, form=form), status=status)


@manage_required
@require_http_methods(["GET", "POST"])
def requester_edit(request, requester_id: int):
    """`/servicedesk/requesters/<id>/edit/` — форма правки ФИО и подразделения; успех — 302 на список."""
    record = get_object_or_404(Requester.objects.select_related("client_unit"), pk=requester_id)
    if request.method == "GET":
        return _form_response(request, record)
    name = request.POST.get("name", "")
    raw_unit = request.POST.get("client_unit", "").strip()
    unit_id = (_number(raw_unit) or -1) if raw_unit else None
    try:
        requesters_service.update(record, name=name, client_unit_id=unit_id, actor=request.user,
                                  ip=request.client_ip)
    except ServiceDeskError as error:
        return _form_response(request, record, name=name, unit_id=unit_id, error=str(error), code=error.code)
    return HttpResponseRedirect(LIST_URL)


def _dialog_response(request, record, *, error=None, code=""):
    dialog = {"record": record, "error": error, "code": code}
    if is_fragment(request):
        return render_page(request, "servicedesk/requesters/delete.html", {"dialog": dialog})
    return render_page(request, "servicedesk/requesters/list.html", _list_context(request, dialog=dialog))


@manage_required
@require_http_methods(["GET", "POST"])
def requester_delete(request, requester_id: int):
    """`/servicedesk/requesters/<id>/delete/` — диалог и удаление записи без заявок (нужно `confirm=1`)."""
    record = get_object_or_404(Requester, pk=requester_id)
    if request.method == "GET":
        return _dialog_response(request, record)
    if request.POST.get("confirm") != "1":
        return _dialog_response(request, record, error=NOT_CONFIRMED)
    try:
        requesters_service.delete(record, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _dialog_response(request, record, error=str(error), code=error.code)
    return HttpResponseRedirect(LIST_URL)


def _upload_page(request, *, error: str = "", status: int = 200):
    context = {"error": error, "format_help": FORMAT_HELP, "columns": import_service.COLUMNS,
               "required": import_service.REQUIRED, "max_mb": import_service.MAX_BYTES // (1024 * 1024),
               "max_rows": import_service.MAX_ROWS}
    return render_page(request, "servicedesk/requesters/import.html", context, status=status)


@manage_required
@require_http_methods(["GET", "POST"])
def import_start(request):
    """`/servicedesk/requesters/import/` — выбор файла; успех — 302 на предпросмотр, отказ — 200 с `[role=alert]`."""
    if request.method == "GET":
        return _upload_page(request)
    upload = request.FILES.get("file")
    if upload is None:
        return _upload_page(request, error=NO_FILE)
    content = upload.read(import_service.MAX_BYTES + 1)
    try:
        item = import_service.make_preview(content, file_name=upload.name, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _upload_page(request, error=str(error))
    return HttpResponseRedirect(f"{IMPORT_URL}{item.pk}/")


def _download(content: bytes, content_type: str, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@manage_required
@require_GET
def import_sample_csv(request):
    """`/servicedesk/requesters/import/sample.csv` — образец файла."""
    return _download(import_service.sample_csv(), "text/csv; charset=utf-8", "requesters-sample.csv")


@manage_required
@require_GET
def import_sample_xlsx(request):
    """`/servicedesk/requesters/import/sample.xlsx` — образец файла."""
    return _download(import_service.sample_xlsx(), XLSX_TYPE, "requesters-sample.xlsx")


def _import_rows(item: RequesterImport) -> list[dict]:
    """Строки таблицы: подпись по `result` (14.2); причина — только у ошибок, там она и есть подпись."""
    rows, preview = [], item.state != RequesterImport.State.DONE
    for row in item.rows:
        result = row.get("result", "")
        is_error = result == "error"
        rows.append({"number": row.get("number"), "email": row.get("email", ""), "result": result,
                     "label": "" if is_error else ROW_LABELS.get(result, ""), "is_error": is_error,
                     "reason": row.get("reason", "") if is_error else "",
                     "detail": row.get("reason", "") if preview and not is_error else ""})
    return rows


def _summary_text(summary: dict) -> str:
    """«добавлено N, обновлено M, без изменений K, с ошибками L» и при ненулевых «; удалено D; сменили отметку…: E»."""
    text = (f"добавлено {summary.get('added', 0)}, обновлено {summary.get('updated', 0)}, "
            f"без изменений {summary.get('unchanged', 0)}, с ошибками {summary.get('errors', 0)}")
    if summary.get("deleted", 0):
        text += f"; удалено {summary['deleted']}"
    if summary.get("origin_changed", 0):
        text += f"; сменили отметку на «заявка»: {summary['origin_changed']}"
    return text


@manage_required
@require_http_methods(["GET", "POST"])
def import_preview(request, import_id: int):
    """`/servicedesk/requesters/import/<id>/` — предпросмотр, подтверждение, итог."""
    item = get_object_or_404(RequesterImport, pk=import_id)
    url = f"{IMPORT_URL}{item.pk}/"
    if request.method == "POST":
        if item.state != RequesterImport.State.DONE:
            import_service.confirm(item, delete_missing=bool(request.POST.get("delete_missing")),
                                   actor=request.user, ip=request.client_ip)
        return HttpResponseRedirect(url)
    done = item.state == RequesterImport.State.DONE
    rows = _import_rows(item)
    return render_page(request, "servicedesk/requesters/import_preview.html", {
        "item": item, "rows": rows, "summary": item.summary or {}, "done": done,
        "summary_text": _summary_text(item.summary or {}),
        "would_delete": (item.summary or {}).get("would_delete", 0),
        "not_loaded": (item.summary or {}).get("not_loaded", []), "new_units": item.new_units or []})
