"""Выдача файлов заявок (CONTRACT-003, 12.5): вложение и исходное письмо.

Представление только пускает вошедшего пользователя, зовёт службу `attachments` и отвечает 200 с пустым телом:
сам файл отдаёт nginx по `X-Accel-Redirect`. Заявка не видна или файл не выдаётся — `Http404` из службы.
Маршруты объявляет `urls.py` (T-3230).
"""
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from ..services import attachments


def _response(download) -> HttpResponse:
    """Пустой ответ 200 с заголовками выдачи: файл — по `X-Accel-Redirect`, браузер ничего не открывает сам."""
    response = HttpResponse(b"", content_type=download.content_type)
    response["X-Accel-Redirect"] = download.accel_path
    response["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(download.filename, safe="")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_GET
def file_download(request, number, file_id):
    """Вложение заявки: `/tickets/<номер>/files/<id>/`."""
    return _response(attachments.download(request.user, number, file_id))


@login_required
@require_GET
def source_mail(request, number, inbound_id):
    """Исходное письмо заявки: `/tickets/<номер>/mail/<id>.eml`."""
    return _response(attachments.source_mail(request.user, number, inbound_id))
