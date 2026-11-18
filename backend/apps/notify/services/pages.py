"""Данные страницы потока уведомлений: общая часть списка и вкладки мессенджера (T-8218).

`list_context` — фильтр `f` и страница `page` (50 на страницу, неверный номер — первая, за последней — последняя);
его зовут прежняя страница `/notifications/`, фрагмент `/notifications/list/` и вкладка `/messenger/notifications/`.
"""
from django.core.paginator import Paginator
from django.db.models import QuerySet

from apps.notify.models import Notification
from apps.notify.services import kinds

PAGE_SIZE = 50
UNREAD = "unread"


def filter_value(raw) -> str:
    """Фильтр из строки запроса: только `unread`, прочее — все."""
    return UNREAD if raw == UNREAD else ""


def page_number(raw) -> str:
    """Номер страницы для возврата: только целое от 1, иначе пусто."""
    return raw if isinstance(raw, str) and raw.isascii() and raw.isdigit() and int(raw) >= 1 else ""


def list_context(user, query) -> dict:
    """`{page, filter_value, page_number}` для тела потока; `query` — `request.GET`."""
    f = filter_value(query.get("f"))
    notes = Notification.objects.filter(user_id=user.pk)
    if f:
        notes = notes.filter(read_at__isnull=True)
    page = Paginator(notes.order_by("-created_at", "-pk"), PAGE_SIZE).get_page(
        page_number(query.get("page")) or 1)
    _with_titles(page.object_list)
    return {"page": page, "filter_value": f, "page_number": page.number}


def _with_titles(notes) -> list:
    """Подставить название вида из каталога (шаблон `_row.html` читает `kind_title`)."""
    titles = {kind.code: kind.title for kind in kinds.catalog()}
    for note in notes:
        note.kind_title = titles.get(note.kind, "")
    return notes
