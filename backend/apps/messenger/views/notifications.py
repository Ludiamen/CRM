"""Вкладка «Уведомления» мессенджера (срез 008, T-8218; CONTRACT-008, 3.3, 10.2, 12.2).

`GET /messenger/notifications/` — страница с вкладками «Чаты»/«Уведомления»; первая страница потока рисуется
серверно тем же телом `notify/_list_body.html`, что и прежний список, поэтому строки, фильтр, «Прочитать все» и
страницы совпадают. Смена фильтра и страницы идёт фрагментом `/notifications/list/` (T-8218 в `notify`).
"""
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

from apps.core.views.common import render_page
from apps.notify.views import pages as notify_pages

URL = "/messenger/notifications/"


@login_required
@require_GET
def notifications(request):
    """`GET /messenger/notifications/` — вкладка с первой страницей потока (50, фильтр `f`)."""
    context = notify_pages._list_context(request)
    return render_page(request, "messenger/notifications.html", context)