"""Страница мессенджера и список чатов (срез 008, T-8207).

PLAN-008 «Список чатов и порядок», «Беседа и история порциями»; CONTRACT-008 § 10.1–10.2, 12.1–12.2. Страница
`GET /messenger/` собирает список одним запросом (`chats.rows`, порядок `COALESCE(last_message_at, created_at)
DESC, id DESC`), поля `q` (по названиям и ФИО) и `to` (страница «Написать», T-8203, в базу не пишет). Фрагмент
`GET /messenger/list/` отдаёт тот же список без оболочки; ключ `q` — из белого списка, прочие отбрасываются.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

from apps.core.views.common import render_page
from apps.messenger.services import chats
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
    """`GET /messenger/` — список чатов, вкладки и поле ввода; `?to=` — страница «Написать» (T-8203)."""
    if "to" in request.GET:
        return chat_views.write(request)
    query = _value(request, "q")
    return render_page(request, "messenger/page.html", {
        "mode": "list", "rows": chats.rows(request.user, query), "q": query, "errors": {}})


@login_required
@require_GET
def list_fragment(request):
    """`GET /messenger/list/` — фрагмент списка для HTMX и смены `q`."""
    query = _value(request, "q")
    return render_page(request, "messenger/_list.html",
                       {"rows": chats.rows(request.user, query), "q": query})