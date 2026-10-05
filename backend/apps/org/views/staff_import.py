"""Загрузка сотрудников из таблицы: файл, предпросмотр, подтверждение, образцы (FR-136…142; T-2236).

Нужны оба права: `accounts.manage` и `org.manage` (декораторы из T-2230a). Правила разбора, проверки и выполнения —
в службе `org.services.staff_import`; здесь только форма, ответ и тексты. Файл читается в память и нигде не хранится
(FR-141): представление отдаёт службе байты, а размер проверяет служба (`too_big`).
"""
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, render_page
from apps.org.models import StaffImport
from apps.org.services import staff_import as staff_import_service
from apps.org.services.errors import OrgError

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NO_FILE = "Выберите файл таблицы (CSV или XLSX)."
ROW_LABELS = {"will_create": "будет создан", "skipped": "пропущен", "error": "ошибка", "created": "создан"}
HINT_TEXTS = {"dismissed": "уволен: верните его из карточки"}


def _upload_page(request, *, error: str = "", status: int = 200):
    context = {"error": error, "required": staff_import_service.REQUIRED_COLUMNS,
               "optional": staff_import_service.OPTIONAL_COLUMNS,
               "max_mb": staff_import_service.MAX_BYTES // (1024 * 1024), "max_rows": staff_import_service.MAX_ROWS}
    return render_page(request, "org/import.html", context, status=status)


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def import_start(request):
    """`/structure/import/` — выбор файла; успех — 302 на предпросмотр, отказ — 200 с `[role=alert]`."""
    if request.method == "GET":
        return _upload_page(request)
    upload = request.FILES.get("file")
    if upload is None:
        return _upload_page(request, error=NO_FILE)
    content = upload.read(staff_import_service.MAX_BYTES + 1)
    try:
        item = staff_import_service.make_preview(content, file_name=upload.name, actor=request.user, ip=request.client_ip)
    except OrgError as error:
        return _upload_page(request, error=str(error))
    return HttpResponseRedirect(f"/structure/import/{item.pk}/")


def _rows(item: StaffImport) -> list[dict]:
    """Строки для таблицы: подпись итога и подсказка готовятся здесь, чтобы шаблон не искал по словарям."""
    return [{**row, "label": ROW_LABELS.get(row.get("result"), ""), "hint_text": HINT_TEXTS.get(row.get("hint", ""), "")}
            for row in item.rows]


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_http_methods(["GET", "POST"])
def import_preview(request, import_id: int):
    """`/structure/import/<id>/` — предпросмотр, подтверждение, итог."""
    item = get_object_or_404(StaffImport, pk=import_id)
    url = f"/structure/import/{item.pk}/"
    if request.method == "POST":
        if item.state == StaffImport.State.DONE:
            return HttpResponseRedirect(url)
        done = staff_import_service.confirm(item, send_invites=request.POST.get("send_invites") == "1",
                                            actor=request.user, ip=request.client_ip)
        summary = done.summary
        flash(request, f"Загрузка выполнена: создано {summary['created']}, пропущено {summary['skipped']}, "
                       f"с ошибками {summary['errors']}.")
        return HttpResponseRedirect(url)
    return render_page(request, "org/import_preview.html", {
        "item": item, "rows": _rows(item), "summary": item.summary, "done": item.state == StaffImport.State.DONE,
        "not_loaded": item.summary.get("not_loaded", []), "new_units": item.summary.get("new_units", [])})


def _download(content: bytes, content_type: str, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_GET
def sample_csv(request):
    """`/structure/import/sample.csv` — образец файла."""
    return _download(staff_import_service.sample_csv(), "text/csv; charset=utf-8", "staff-sample.csv")


@require_permission("accounts.manage")
@require_permission("org.manage")
@require_GET
def sample_xlsx(request):
    """`/structure/import/sample.xlsx` — образец файла."""
    return _download(staff_import_service.sample_xlsx(), XLSX_TYPE, "staff-sample.xlsx")
