"""Отправка, правка и удаление сообщения (срез 008, T-8209; CONTRACT-008, 10.1–10.2).

Права: «видит чат» — `members.get_chat` (чужой и несуществующий чат — одинаковый 404), «автор» — `author_id`.
Отказ службы — 200 с причиной у поля: HTMX получает форму, обычный запрос — страницу беседы с введённым текстом.
Успех: HTMX — сообщение `#m<id>` (правка/удаление — тот же узел на месте) и очищенная форма, обычный запрос —
302 в беседу. Цитата невидимого чата — 404, как несуществующий чат (FR-669).
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.views.common import is_fragment, render_page
from apps.messenger.models import Chat, Message
from apps.messenger.services import members, messages
from apps.messenger.services import page as page_service
from apps.messenger.services.errors import MessengerError
from apps.messenger.views import pages
from apps.messenger.services import search as search_service
from apps.search.parse import parse as parse_query


@login_required
@require_http_methods(["GET", "POST"])
def messages_view(request, chat_id: int):
    """`GET …/messages/` — история порциями (T-8208); `POST` — отправка (T-8209)."""
    if request.method == "GET":
        return pages.history(request, chat_id)
    return send(request, chat_id)


@login_required
@require_POST
def send(request, chat_id: int):
    """`POST /messenger/chats/<id>/messages/` — отправка с цитатой и файлами (FR-652–654)."""
    try:
        chat = members.get_chat(request.user, chat_id)
    except Http404:
        # Выключенный «Общий чат»: HTMX — 200 с причиной, обычный POST — тот же 404 (FR-651, 10.2).
        chat = Chat.objects.filter(pk=chat_id, kind=Chat.Kind.GENERAL).first()
        if chat is None or not is_fragment(request):
            raise
        return _error_response(request, chat, MessengerError("chat_disabled", field="chat"))
    if not members.can_write(request.user, chat):
        if chat.kind == Chat.Kind.GENERAL:
            if is_fragment(request):
                return _error_response(request, chat, MessengerError("chat_disabled", field="chat"))
            raise Http404
        raise PermissionDenied
    _check_quote_visibility(request)

    try:
        message = messages.send(chat, request.user, request.POST.get("text", ""),
                                quote=request.POST.get("quote"), files=request.POST.getlist("files"))
    except MessengerError as exc:
        return _error_response(request, chat, exc)
    if is_fragment(request):
        return render_page(request, "messenger/_send_response.html", {
            "chat": chat, "items": pages.message_items([message], request.user, message.chat), "errors": {}})
    return redirect(f"/messenger/chats/{chat.pk}/")


@login_required
@require_GET
def chat_search(request, chat_id: int):
    """`GET /messenger/chats/<id>/search/?q=` — сообщения беседы с подсветкой и якорем `#m<id>` (FR-668)."""
    chat = members.get_chat(request.user, chat_id)
    parsed = parse_query(request.GET.get("q"))
    rows = search_service.chat_search(request.user, chat, parsed)
    for row in rows:
        row["headline_html"] = _highlight(row["headline"])
    return render_page(request, "messenger/_chat_search.html", {"chat": chat, "rows": rows})


def _highlight(value: str) -> str:
    """Экранировать головку `ts_headline`, вернув только теги `<b>` подсветки."""
    from django.utils.html import escape

    return escape(value).replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


@login_required
@require_POST
def edit(request, message_id: int):
    """`POST /messenger/messages/<mid>/edit/` — правка автором (FR-656)."""
    message = _owned_message(request, message_id)
    if message.deleted_at is not None:
        raise Http404
    try:
        message = messages.edit(message, request.user, request.POST.get("text", ""))
    except MessengerError as exc:
        return _error_response(request, message.chat, exc)
    if is_fragment(request):
        return render_page(request, "messenger/_messages.html",
                           {"items": pages.message_items([message], request.user, message.chat)})
    return redirect(f"/messenger/chats/{message.chat_id}/")


@login_required
@require_POST
def delete(request, message_id: int):
    """`POST /messenger/messages/<mid>/delete/` — мягкое удаление автором (FR-657)."""
    message = _owned_message(request, message_id)
    if message.deleted_at is not None:
        raise Http404
    message = messages.delete(message, request.user)
    if is_fragment(request):
        return render_page(request, "messenger/_messages.html",
                           {"items": pages.message_items([message], request.user, message.chat)})
    return redirect(f"/messenger/chats/{message.chat_id}/")


def _owned_message(request, message_id: int) -> Message:
    """Сообщение живого/мягко удалённого чата автора: чужой чат и несуществующее сообщение — одинаковый 404."""
    try:
        message = Message.objects.select_related("chat", "quote").get(pk=message_id)
    except Message.DoesNotExist as exc:
        raise Http404 from exc
    members.get_chat(request.user, message.chat_id)
    if message.author_id != request.user.pk:
        raise PermissionDenied
    return message


def _check_quote_visibility(request) -> None:
    """Цитата сообщения чата, которого сотрудник не видит, — 404 (FR-669); видимого другого чата — отказ службы."""
    raw = request.POST.get("quote")
    if not raw:
        return
    try:
        target = Message.objects.filter(pk=int(raw)).only("chat_id").first()
    except (TypeError, ValueError):
        return
    if target is not None:
        members.get_chat(request.user, target.chat_id)


def _error_response(request, chat, error: MessengerError):
    """Отказ у поля: HTMX — форма с причиной, обычный запрос — страница беседы (10.1, 13.1)."""
    field = error.field or "text"
    if is_fragment(request):
        return render_page(request, "messenger/_form.html",
                           {"chat": chat, "errors": {field: error}, "text": request.POST.get("text", "")})
    history, more = page_service.history(chat)
    context = pages._chat_context(request, chat, history, more)
    context["errors"] = {field: error}
    return render_page(request, "messenger/chat.html", context)