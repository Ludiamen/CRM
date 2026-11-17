"""Подсказка «@» в беседе (срез 008, T-8210; CONTRACT-008, 5.2, 6 (V5), 10.2, 12.3).

`GET /messenger/mentions/?chat=<id>&q=` — до 20 строк участников и своих чатов. Чат берётся одной функцией
видимости `members.get_chat`: чужой и несуществующий — одинаковый 404 (FR-669). В личном диалоге и на запрос
короче двух знаков — пустой фрагмент.
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

from apps.core.views.common import render_page
from apps.messenger.services import members, mentions


@login_required
@require_GET
def suggest(request):
    """`GET /messenger/mentions/` — фрагмент подсказки «@» (строки `[data-mention-value]`)."""
    chat_id = request.GET.get("chat", "")
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        chat_id = 0
    chat = members.get_chat(request.user, chat_id) if chat_id else None
    if chat is None:
        from django.http import Http404

        raise Http404
    rows = mentions.suggest(request.user, chat, request.GET.get("q", ""))
    return render_page(request, "messenger/_mention_suggest.html", {"rows": rows})