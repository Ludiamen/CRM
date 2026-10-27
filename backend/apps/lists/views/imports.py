"""Представления: загрузка записей из таблицы и образец (T-6221; PLAN-006, «Загрузка из таблицы и образец»;
CONTRACT-006, 10.2, 10.4, 11.9, 12).

Шаги: файл (`import`) → сопоставление и предпросмотр (`import_job`) → подтверждение (`import_confirm`, POST) → итог;
всё правящему списка (читающему — 403, не читающему — 404). Задание ищется по паре «номер, список» и автору, не старше
суток (`imports.get_job`). Скачивание образца — `sample`.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.models import AuditEvent
from apps.core.views.common import render_page
from apps.lists.models import ImportJob
from apps.lists.services import imports, schema
from apps.lists.services.errors import ListsError
from apps.lists.views.home import done


def _list_for_edit(request, list_id: int):
    """Список или 404 (не читается) / 403 (не правит)."""
    return imports.require_edit(request.user, list_id)


def _upload_page(request, lst, refused=None):
    return render_page(request, "lists/import.html", {"lst": lst, "mode": "upload", "refused": refused})


def _job_page(request, lst, job):
    """Страница задания: сопоставление (и предпросмотр, если он построен) или итог."""
    if job.state == ImportJob.State.DONE:
        return _summary_page(request, lst, job, job.summary)
    chosen = job.mapping if job.state == ImportJob.State.PREVIEW else (
        job.mapping or imports.auto_mapping(lst, job.header))
    fields = [field for field in schema.visible_fields(lst) if field.type != "file"]
    options = [{"code": "", "name": "Не загружать"}, {"code": imports.TITLE, "name": "Название"}]
    options += [{"code": field.code, "name": field.name} for field in fields]
    columns = [{"index": number, "header": text, "selected": chosen.get(str(number), "")}
               for number, text in enumerate(job.header)]
    context = {"lst": lst, "mode": "job", "job": job, "columns": columns, "options": options}
    if job.state == ImportJob.State.PREVIEW:
        context.update(rows=job.rows, counts=imports.counts(job))
    return render_page(request, "lists/import.html", context)


def _summary_page(request, lst, job, summary):
    event = (AuditEvent.objects.filter(action="lists.import_done", object_id=str(job.pk))
             .order_by("-at").values_list("at", flat=True).first())
    return render_page(request, "lists/import_summary.html", {
        "lst": lst, "job": job, "summary": summary, "finished_at": event or timezone.now()})


@login_required
@require_http_methods(["GET", "POST"])
def upload(request, list_id: int):
    """Шаг 1: форма файла; POST — задание в состоянии `mapping` и переход к сопоставлению (302)."""
    lst = _list_for_edit(request, list_id)
    if request.method == "GET":
        return _upload_page(request, lst)
    sent = request.FILES.get("file")
    try:
        if sent is None:
            raise ListsError("import_bad_format", field="file")
        if sent.size > imports.MAX_BYTES:
            raise ListsError("import_too_big", field="file")
        job = imports.upload(lst, request.user, name=sent.name, content=sent.read())
    except ListsError as refused:
        return _upload_page(request, lst, refused)
    return done(request, f"/lists/{lst.pk}/import/{job.pk}/")


@login_required
@require_http_methods(["GET", "POST"])
def job(request, list_id: int, job: int):
    """Шаги 2–3: GET — сопоставление (и предпросмотр); POST `map.<N>` — проверка строк."""
    lst = _list_for_edit(request, list_id)
    current = imports.get_job(request.user, lst, job)
    if request.method == "POST" and current.state != ImportJob.State.DONE:
        mapping = {key[4:]: value for key, value in request.POST.items() if key.startswith("map.")}
        current = imports.preview(current, mapping, request.user)
    return _job_page(request, lst, current)


@login_required
@require_POST
def confirm(request, list_id: int, job: int):
    """Шаг 4: подтверждение автором; ответ — страница итога (повтор — тот же итог)."""
    lst = _list_for_edit(request, list_id)
    summary = imports.confirm(lst, job, request.user)
    return _summary_page(request, lst, ImportJob.objects.get(pk=job), summary)


@login_required
@require_GET
def sample(request, list_id: int):
    """Образец XLSX правящему списка."""
    lst = _list_for_edit(request, list_id)
    response = HttpResponse(imports.sample(lst), content_type=imports.XLSX_TYPE)
    response["Content-Disposition"] = f"attachment; filename*=UTF-8''{imports.sample_filename(lst)}"
    return response
