"""Загрузка файла, «убрать», выдача оригинала и эскиза (срез 008, T-8215/T-8216; CONTRACT-008, 10.2, 12.5).

Чат берётся `members.get_chat` (чужой — 404). Отказы службы — 200 с `[data-error]` у поля `file`; успех загрузки —
таблетка `[data-messenger-file]` со скрытым `files` и крестиком. «Убрать» — 200 с пустым телом. Оригинал и эскиз
отдаются через `X-Accel-Redirect` с `nosniff`/`no-store`; «проверяется» и «карантин» — 404 с понятным текстом, файл
чужого чата — «Не найдено», непривязанный видит только загрузивший (FR-662, 669).
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET, require_POST

import pathlib

from apps.core.services import file_response
from apps.core.views.common import render_page
from apps.messenger.models import MessageAttachment
from apps.messenger.services import files, members
from apps.messenger.services.errors import MessengerError
from apps.messenger.texts import TEXTS


@login_required
@require_POST
def upload(request):
    """`POST /messenger/files/` — один файл к сообщению (multipart: `file`, `chat`, `have`)."""
    chat = _chat(request, request.POST.get("chat"))
    try:
        item = files.upload(request.user, request.FILES.get("file"), chat, request.POST.getlist("have"))
    except MessengerError as exc:
        return render_page(request, "messenger/_file_error.html", {"error": exc})
    return render_page(request, "messenger/_file_pill.html", {"item": item})


@login_required
@require_POST
def remove(request, file_id: int):
    """`POST /messenger/files/<id>/delete/` — убрать свой непривязанный файл (200 с пустым телом)."""
    try:
        attachment = MessageAttachment.objects.select_related("file").get(pk=file_id)
    except MessageAttachment.DoesNotExist as exc:
        raise Http404("Файл не найден") from exc
    files.remove(attachment, request.user)
    return HttpResponse(status=200)


@login_required
@require_GET
def download(request, file_id: int):
    """`GET /messenger/files/<id>/` — оригинал своего файла; картинка показывается, прочее скачивается."""
    attachment, stored = _visible(request, file_id)
    if stored.status != "clean":
        return _state_page(request, "file_pending" if stored.status == "pending" else "file_quarantine")
    image_format = (stored.content_type or "").split("/")[-1]
    if image_format in file_response.IMAGE_TYPES:
        return file_response.inline_image(stored, image_format)
    return file_response.download(stored, attachment.name)


@login_required
@require_GET
def thumb(request, file_id: int):
    """`GET /messenger/files/<id>/thumb/` — эскиз ≤ 1280 px; у файла без эскиза — «Не найдено»."""
    attachment, stored = _visible(request, file_id)
    if stored.status != "clean":
        return _state_page(request, "file_pending" if stored.status == "pending" else "file_quarantine")
    if not attachment.thumb:
        raise Http404("Не найдено")
    name = pathlib.PurePosixPath(attachment.thumb).name
    response = HttpResponse(b"", content_type="image/jpeg")
    response["X-Accel-Redirect"] = f"/protected/attachments/thumbs/{name}"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "no-store"
    return response


def _state_page(request, code: str):
    """404 с текстом состояния файла: «Файл ещё проверяется» / «Файл в карантине» (CONTRACT-008, 10.2)."""
    return render_page(request, "messenger/_file_state.html", {"text": TEXTS[code]}, status=404)


def _visible(request, file_id: int):
    """Файл видимого чата или свой непривязанный; иначе `Http404` без подробностей (FR-669)."""
    try:
        attachment = MessageAttachment.objects.select_related("file").get(pk=file_id)
    except MessageAttachment.DoesNotExist as exc:
        raise Http404("Не найдено") from exc
    stored = attachment.file
    if attachment.message_id is None:
        if attachment.uploaded_by_id != request.user.pk:
            raise Http404("Не найдено")
    else:
        members.get_chat(request.user, attachment.message.chat_id)
    return attachment, stored


def _chat(request, raw):
    """Чат загрузки: номер из формы, иначе `Http404` (видимость проверяет `members.get_chat`)."""
    try:
        number = int(raw)
    except (TypeError, ValueError):
        raise Http404("Не найдено") from None
    return members.get_chat(request.user, number)