"""Представления: файлы записи — прикрепить, скачать, удалить (T-6222; PLAN-006, «Файлы записи»; CONTRACT-006, 10.2, 11.7).

Прикрепить и удалить: обычный запрос — 302 на карточку, запрос HTMX — фрагмент блока файлов поля; отказ службы — 200 с
отказом внутри блока (у записи в архиве — общий `[role=alert]`). Скачать: «чистый» — `file_response.download`,
«проверяется» и «карантин» — 404, как несуществующий; файл ищется по паре с записью и списком.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from apps.core.services import file_response
from apps.core.views.common import is_fragment, render_page
from apps.core.models import StoredFile
from apps.lists.models import Field, Record, RecordFile
from apps.lists.services import access, files as files_service, schema
from apps.lists.services.errors import ListsError, RecordArchived

from .records import _card_context


def _card_url(lst, number: int) -> str:
    return f"/lists/{lst.pk}/{number}/"


def _block(request, lst, record, field, *, error=None, alert=None):
    """Фрагмент блока файлов одного поля (ответ HTMX): список файлов записи, отказ внутри блока или общий отказ."""
    all_files = RecordFile.objects.filter(record=record).select_related("file").order_by("uploaded_at", "pk")
    context = {"lst": lst, "record": record, "field": field, "all_files": all_files,
               "can_edit": access.can_edit(request.user, lst), "file_error": error, "block_alert": alert}
    return render_page(request, "lists/_record_file_block.html", context)


def _card_with_refusal(request, lst, record, refused: ListsError, field=None):
    """Полная страница карточки с отказом: у записи в архиве — общий отказ вверху, иначе — внутри блока файлов поля."""
    if isinstance(refused, RecordArchived):
        return render_page(request, "lists/record.html", _card_context(request, lst, record, alert=refused))
    context = _card_context(request, lst, record)
    target = field.pk if field is not None else (context["file_fields"][0].pk if context["file_fields"] else None)
    if target is None:
        return render_page(request, "lists/record.html", _card_context(request, lst, record, alert=refused))
    context.update(file_error=refused, file_error_field=target)
    return render_page(request, "lists/record.html", context)


def _refusal(request, lst, record, refused: ListsError, field):
    """Отказ службы: 200 — фрагмент блока поля (HTMX) или карточка с отказом (обычный запрос)."""
    if is_fragment(request) and field is not None:
        if isinstance(refused, RecordArchived):
            return _block(request, lst, record, field, alert=refused)
        return _block(request, lst, record, field, error=refused)
    return _card_with_refusal(request, lst, record, refused, field)


def _file_field_of(lst, code: str):
    """Видимое поле «файл» списка по коду для показа отказа или `None` (службы сами отвечают 404 на чужое поле)."""
    return next((f for f in schema.visible_fields(lst) if f.code == code and f.type == Field.Type.FILE), None)


@login_required
@require_POST
def attach(request, list_id: int, number: int):
    """Прикрепить файл (правящий): поле `field` — код поля «файл», `file` — файл."""
    lst = access.get_list(request.user, list_id)
    if not access.can_edit(request.user, lst):
        raise PermissionDenied
    upload = request.FILES.get("file")
    if upload is None:
        return HttpResponseBadRequest("Файл не передан")
    code = request.POST.get("field", "")
    record = Record.objects.filter(list=lst, number=number).first()
    field = _file_field_of(lst, code)
    try:
        files_service.attach(lst, number, field_code=code, name=upload.name, data=upload.read(), actor=request.user)
    except ListsError as refused:
        if record is None:
            raise Http404("Запись не найдена") from None
        return _refusal(request, lst, record, refused, field)
    if is_fragment(request):
        return _block(request, lst, record, field)
    return redirect(_card_url(lst, number))


@login_required
@require_GET
def download(request, list_id: int, number: int, file_id: int):
    """Скачать «чистый» файл (читающий список); остальные состояния и чужие файлы — 404."""
    record = access.get_record(request.user, list_id, number)
    item = RecordFile.objects.select_related("file").filter(pk=file_id, record=record).first()
    if item is None or item.file.status != StoredFile.Status.CLEAN:
        raise Http404("Файла нет")
    return file_response.download(item.file, item.name)


@login_required
@require_POST
def delete(request, list_id: int, number: int, file_id: int):
    """Удалить файл записи (правящий; запись не в архиве)."""
    lst = access.get_list(request.user, list_id)
    if not access.can_edit(request.user, lst):
        raise PermissionDenied
    record = Record.objects.filter(list=lst, number=number).first()
    item = RecordFile.objects.select_related("field").filter(pk=file_id, record=record).first() if record else None
    if item is None:
        raise Http404("Файла нет")
    try:
        files_service.remove(lst, number, file_id, actor=request.user)
    except ListsError as refused:
        return _refusal(request, lst, record, refused, item.field)
    if is_fragment(request):
        return _block(request, lst, record, item.field)
    return redirect(_card_url(lst, number))
