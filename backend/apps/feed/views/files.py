"""Представления ленты: загрузка, «убрать», выдача оригинала и эскиза (T-7226, T-7227; CONTRACT-007, 10.2).

`POST /feed/files/` — один файл отдельным запросом: ответ — таблетка или отказ у поля `file`.
`POST /feed/files/<id>/delete/` — убрать свой непривязанный файл: 200 с пустым телом, чужой и
привязанный — 404. `GET /feed/files/<id>/` — оригинал: картинка — показ (`inline_image`), прочее —
вложение (`download`). `GET /feed/files/<id>/thumb/` — эскиз собственным ответом с
`X-Accel-Redirect: /protected/attachments/thumbs/<имя>` (функции ядра путь эскиза не строят).
Видимость записи файла проверяется всегда первой и только потом состояние файла (FR-606):
невидимая запись — тот же 404, что у несуществующего; «проверяется» и «карантин» — 404 с текстом
контракта; `nosniff` и `no-store` — на каждой выдаче.
"""
import pathlib

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import StoredFile
from apps.core.services import file_response
from apps.core.views.common import render_page
from apps.feed.models import FeedFile
from apps.feed.services import files, visibility
from apps.feed.services.errors import FeedError
from apps.feed.texts import TEXTS

_THUMB_TYPES = {".jpg": "image/jpeg", ".webp": "image/webp"}
_IMAGE_FORMATS = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


@login_required
@require_POST
def upload_file(request):
    """Таблетка загруженного файла со скрытым полем `files` или отказ с кодом у поля `file`."""
    try:
        feed_file = files.upload(
            request.user,
            request.FILES.get("file"),
            scope=request.POST.get("scope", "post"),
            post_id=request.POST.get("post"),
            comment_id=request.POST.get("comment"),
            have=request.POST.getlist("have"),
        )
    except FeedError as exc:
        message = TEXTS[exc.code].format(**dict(exc.params))
        return render(request, "feed/_file_error.html", {"code": exc.code, "message": message})
    return render(request, "feed/_file_pill.html", {"file": feed_file})


@login_required
@require_POST
def delete_file(request, file_id):
    """Убрать свой непривязанный файл: пустой ответ; чужой, привязанный и несуществующий — 404."""
    files.remove_unbound(request.user, file_id)
    return HttpResponse("")


def _load(file_id: int) -> FeedFile:
    """Строка `FeedFile` со связью `file`; несуществующий номер — обычный 404 «Не найдено»."""
    try:
        return FeedFile.objects.select_related("file").get(pk=file_id)
    except FeedFile.DoesNotExist as exc:
        raise Http404 from exc


def _visible(user, item: FeedFile) -> None:
    """Видимость записи файла: невидимая запись и чужой непривязанный файл — тот же 404, что у несуществующего.

    Непривязанный файл виден только загрузившему (план, «Выдача»). Проверка всегда первой —
    раньше состояния файла: иначе текст «Файл ещё проверяется» выдал бы чужому существование записи.
    """
    if item.post_id is None:
        if item.uploaded_by_id != user.pk:
            raise Http404
        return
    visibility.get_post(user, item.post_id)


def _state_page(request, code: str):
    """404 с текстом контракта: файл ещё проверяется или в карантине (FR-634, FR-642)."""
    return render_page(request, "feed/file_state.html", {"code": code, "message": TEXTS[code]}, status=404)


def _state_code(item: FeedFile) -> str:
    if item.file.status == StoredFile.Status.PENDING:
        return "file_pending"
    if item.file.status == StoredFile.Status.QUARANTINE:
        return "file_quarantine"
    return ""


@login_required
@require_GET
def download_file(request, file_id):
    """Оригинал «чистого» файла: картинка — показом, прочее — вложением; оба через `X-Accel-Redirect`."""
    item = _load(file_id)
    _visible(request.user, item)
    code = _state_code(item)
    if code:
        return _state_page(request, code)
    stored = item.file
    image_format = _IMAGE_FORMATS.get(stored.content_type, "")
    if image_format:
        return file_response.inline_image(stored, image_format)
    return file_response.download(stored, item.name)


@login_required
@require_GET
def thumb_file(request, file_id):
    """Эскиз «чистого» файла: собственный ответ `X-Accel-Redirect: /protected/attachments/thumbs/<имя>`.

    «Чистый» без эскиза — 404 «Не найдено», как у несуществующего (решение 51 задач).
    """
    item = _load(file_id)
    _visible(request.user, item)
    code = _state_code(item)
    if code:
        return _state_page(request, code)
    if not item.thumb:
        raise Http404
    name = pathlib.PurePosixPath(item.thumb).name
    content_type = _THUMB_TYPES.get(pathlib.PurePosixPath(name).suffix, "application/octet-stream")
    response = HttpResponse(b"", content_type=content_type)
    response["X-Accel-Redirect"] = f"/protected/attachments/thumbs/{name}"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response
