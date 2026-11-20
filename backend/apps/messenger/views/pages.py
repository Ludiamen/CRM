"""Страница мессенджера, список чатов, беседа и история порциями (срез 008, T-8207/T-8208).

PLAN-008 «Список чатов и порядок», «Беседа и история порциями», «360 px и две колонки»; CONTRACT-008 § 10.1–10.2,
12.1–12.4. Список — один запрос `chats.rows` с порядком `COALESCE(last_message_at, created_at) DESC, id DESC`.
Беседа — `members.get_chat` (чужой чат — 404 как несуществующий), история последних 50, поле ввода и узел
соединения `/ws/messenger/?chat=<id>`; старые — `GET …/messages/?before=<ISO>,<id>` по курсору
`(created_at, id) < (%s, %s)` без `OFFSET`. Неверный `before` читается как отсутствующий.
"""
from datetime import datetime
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.models import User
from apps.core.services import permissions
from apps.core.views.common import render_page
from apps.messenger.models import Chat
from apps.messenger.services import chats, members, read, unread
from apps.messenger.services import page as page_service
from apps.messenger.services import text as text_service
from apps.messenger.views import chats as chat_views

# Ключи строки запроса страницы и списка — белый список (CONTRACT-008, 10.1).
PAGE_KEYS = ("q", "to")
LIST_KEYS = ("q",)


def _value(request, key: str) -> str:
    """Значение разрешённого ключа или пустая строка; прочие ключи в работу не идут."""
    return (request.GET.get(key) or "").strip()


@login_required
@require_GET
def page(request):
    """`GET /messenger/` — список чатов, вкладки и поле ввода; `?to=` — страница «Написать» (T-8203).

    На широком экране справа открыта первая беседа списка (CONTRACT-008 10.1, FR-673). Отметку прочтения
    показ списка не ставит: открытие беседы отмечается её собственной страницей и отметкой `read`.
    """
    if "to" in request.GET:
        return chat_views.write(request)
    query = _value(request, "q")
    rows = chats.rows(request.user, query)
    context = {"mode": "list", "rows": rows, "q": query, "errors": {}}
    if rows:
        try:
            first = members.get_chat(request.user, rows[0].id)
        except Http404:
            first = None
        if first is not None:
            messages, more = page_service.history(first)
            context.update(_chat_context(request, first, messages, more))
    return render_page(request, "messenger/page.html", context)


@login_required
@require_GET
def list_fragment(request):
    """`GET /messenger/list/` — фрагмент списка для HTMX и смены `q`."""
    query = _value(request, "q")
    return render_page(request, "messenger/_list.html",
                       {"rows": chats.rows(request.user, query), "q": query})


@login_required
@require_GET
def chat(request, chat_id: int):
    """`GET /messenger/chats/<id>/` — беседа: шапка, история 50, поле ввода и узел соединения (FR-658)."""
    found = members.get_chat(request.user, chat_id)
    read.mark(found, request.user)
    messages, more = page_service.history(found)
    return render_page(request, "messenger/chat.html", _chat_context(request, found, messages, more))


@login_required
@require_GET
def history(request, chat_id: int):
    """`GET /messenger/chats/<id>/messages/?before=<ISO>,<id>` — предыдущие 50 сообщений фрагментом (FR-658)."""
    found = members.get_chat(request.user, chat_id)
    before = _cursor(request.GET.get("before"))
    messages, more = page_service.history(found, before)
    return render_page(request, "messenger/_history.html", _chat_context(request, found, messages, more))


def _chat_context(request, chat, messages, more) -> dict:
    """Контекст беседы и фрагмента истории: название, участники, сообщения, курсор и адрес соединения."""
    last_own = read.last_own(chat, request.user)
    readers, audience = read.line(chat, last_own)
    return {
        "chat": chat,
        "title": page_service.chat_title(chat, request.user),
        "member_names": _member_names(chat),
        "items": message_items(messages, request.user, chat),
        "more_url": _more_url(chat, messages) if more else "",
        "ws_url": f"/ws/messenger/?chat={chat.pk}",
        "read_message_id": last_own.pk if last_own is not None else None,
        "read_text": f"Прочитали {readers} из {audience}" if last_own is not None and audience else "",
    }


def message_items(messages, user, chat=None) -> list[dict]:
    """Сообщения для шаблона: свой/чужой, готовый безопасный текст и цитата (5.2, 12.3).

    В беседе упоминание человека — всегда ссылка на карточку (`a[data-mention][href="/staff/<id>/"]`, 12.6).
    """
    items = []
    for message in messages:
        granted = permissions.has_permission(user, "staff.view") or message.author_id == getattr(user, "pk", None)
        items.append({
            "message": message,
            "own": message.author_id == getattr(user, "pk", None),
            "body_html": (text_service.render_plain(message.text, link_staff=granted,
                                                    chat=chat or message.chat, viewer=user)
                          if message.text else ""),
            "quote": message.quote,
            "quote_text": _quote_text(message.quote),
            "files": list(message.files.all()),
        })
    return items


def _quote_text(quote) -> str:
    """Текст цитаты: у удалённого исходного — «Сообщение удалено» (FR-654, 657)."""
    if quote is None:
        return ""
    return "Сообщение удалено" if quote.deleted_at is not None else quote.text


def _more_url(chat, messages) -> str:
    """Адрес предыдущей порции: курсор самого старого показанного сообщения, `+` кодируется `%2B` (10.1)."""
    if not messages:
        return ""
    oldest = messages[0]
    return "/messenger/chats/{}/messages/?{}".format(
        chat.pk, urlencode({"before": f"{oldest.created_at.isoformat()},{oldest.pk}", "chat": chat.pk}))


def _member_names(chat) -> list[str]:
    """ФИО участников для шапки: личный и групповой — состав `members.members`, иначе пусто."""
    if chat.kind == Chat.Kind.PERSONAL:
        return [page_service.chat_title(chat)]
    if chat.kind != Chat.Kind.GROUP:
        return []
    ids = members.members(chat)
    return list(User.objects.filter(pk__in=ids).order_by("full_name").values_list("full_name", flat=True))


def _cursor(raw):
    """`before=<ISO>,<id>` → `(datetime, id)`; пустое, неверное и без запятой — `None` (как отсутствующее)."""
    if not raw or "," not in raw:
        return None
    at_part, _, id_part = raw.rpartition(",")
    try:
        at = datetime.fromisoformat(at_part.replace("Z", "+00:00"))
        number = int(id_part)
    except (ValueError, TypeError):
        return None
    if timezone.is_naive(at):
        at = timezone.make_aware(at)
    return at, number