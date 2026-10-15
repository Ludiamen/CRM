"""«Уведомления»: список, фрагмент колокольчика, «прочитано» и сервис-воркер (PLAN-004, «Контракты», «Колокольчик…»,
«Web Push» → «Сервис-воркер»; CONTRACT-004, 13.1, 14.1, 14.2).

Все маршруты, кроме `/sw.js`, требуют входа. Чужое или несуществующее уведомление даёт 404 (FR-342): проверка — в
службе `reading`. Тексты экранирует шаблонизатор (NFR-311).
"""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from apps.core.views.common import is_fragment, render_page

from ..models import Notification
from ..services import kinds, reading

PAGE_SIZE = 50
BELL_SIZE = 10
MAX_SHOWN = 99
LIST_URL = "/notifications/"
UNREAD = "unread"


def count_context(count: int, *, oob: bool = False) -> dict:
    """Контекст шаблона числа `#notify-count`: точное число, текст «99+» выше 99; общий для страницы и кадра."""
    return {"count": count, "shown": f"{MAX_SHOWN}+" if count > MAX_SHOWN else str(count), "oob": oob}


def toast_context(toast: dict, *, oob: bool = True) -> dict:
    """Контекст шаблона `#notify-toast` для кадра соединения."""
    return {"text": toast.get("text", ""), "url": toast.get("url", ""), "tag": toast.get("tag", ""),
            "show": "1" if toast.get("show") else "0", "oob": oob}


def render_count(count: int, *, oob: bool = True) -> str:
    return render_to_string("notify/_count.html", count_context(count, oob=oob))


def render_toast(toast: dict, *, oob: bool = True) -> str:
    return render_to_string("notify/_toast.html", toast_context(toast, oob=oob))


def top_bar_context(request) -> dict:
    """Контекст элемента `top_bar_items`: число непрочитанных (один запрос по частичному индексу)."""
    context = count_context(reading.unread_count(request.user.pk))
    return {"bell_count": context["count"], "bell_shown": context["shown"]}


def _titles() -> dict:
    return {kind.code: kind.title for kind in kinds.catalog()}


def _with_titles(notes) -> list:
    titles = _titles()
    for note in notes:
        note.kind_title = titles.get(note.kind, "")
    return notes


def _filter(value) -> str:
    return UNREAD if value == UNREAD else ""


def _page_number(value) -> str:
    """Номер страницы для возврата: только целое от 1, иначе пусто."""
    return value if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) >= 1 else ""


def _back_url(f: str, page: str = "") -> str:
    query = {key: value for key, value in (("f", f), ("page", page)) if value}
    return f"{LIST_URL}?{urlencode(query)}" if query else LIST_URL


@login_required
@require_GET
def notification_list(request):
    """Страница «Уведомления»: свои, новые сверху, 50 на страницу, фильтр `?f=unread`."""
    f = _filter(request.GET.get("f"))
    notes = Notification.objects.filter(user_id=request.user.pk)
    if f:
        notes = notes.filter(read_at__isnull=True)
    # не число и меньше 1 — первая страница; больше числа страниц — последняя (`get_page`)
    page = Paginator(notes.order_by("-created_at", "-pk"), PAGE_SIZE).get_page(
        _page_number(request.GET.get("page")) or 1)
    _with_titles(page.object_list)
    return render_page(request, "notify/list.html", {"page": page, "filter_value": f, "page_number": page.number})


@login_required
@require_GET
def bell_panel(request):
    """Фрагмент панели колокольчика: последние 10, «Все уведомления», «Настройки»; страницы у адреса нет."""
    notes = list(Notification.objects.filter(user_id=request.user.pk).order_by("-created_at", "-pk")[:BELL_SIZE])
    return render(request, "notify/_bell_panel.html", {"notes": notes})


@login_required
@require_GET
def notification_open(request, notification_id: int):
    """Отметить своё уведомление прочитанным и перейти по его ссылке."""
    return HttpResponseRedirect(reading.open(request.user, notification_id))


@login_required
@require_POST
def notification_read(request, notification_id: int):
    """Отметить прочитанным без перехода: на запрос HTMX — строка списка, иначе возврат на список."""
    reading.read(request.user, notification_id)
    f = _filter(request.POST.get("f"))
    page = _page_number(request.POST.get("page"))
    if not is_fragment(request):
        return HttpResponseRedirect(_back_url(f, page))
    note = _with_titles([Notification.objects.get(pk=notification_id, user_id=request.user.pk)])[0]
    return render(request, "notify/_row.html", {"note": note, "filter_value": f, "page_number": page or "1"})


@login_required
@require_POST
def notification_read_all(request):
    """Прочитать все свои: на запрос HTMX — пустой ответ с `HX-Redirect`, иначе возврат на список."""
    reading.read_all(request.user)
    url = _back_url(_filter(request.POST.get("f")))
    if not is_fragment(request):
        return HttpResponseRedirect(url)
    response = HttpResponse("")
    response["HX-Redirect"] = url
    return response


@require_GET
def service_worker(request):
    """Сервис-воркер Web Push; входа не требует: `no-store` ставит промежуточный слой ядра, истёкшую сессию он же
    перенаправляет на вход."""
    return render(request, "notify/sw.js", content_type="application/javascript")
