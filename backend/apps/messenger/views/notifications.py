"""Вкладка «Уведомления» мессенджера (срез 008, T-8218; CONTRACT-008, 3.3, 10.2, 12.2).

`GET /messenger/notifications/` — страница с вкладками «Чаты»/«Уведомления»; первая страница потока рисуется серверно
тем же телом `notify/_list_body.html`, что и прежний список. Данные страницы даёт общая служба
`notify.services.pages` (фильтр, 50 на страницу, названия видов), поэтому строки, «Прочитать все» и страницы
совпадают с прежним списком; смена фильтра и страницы идёт фрагментом `/notifications/list/`.
"""
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

from apps.core.views.common import render_page
from apps.notify.services import pages as notify_pages

URL = "/messenger/notifications/"


@login_required
@require_GET
def notifications(request):
    """`GET /messenger/notifications/` — вкладка с первой страницей потока (50, фильтр `f`)."""
    if not apps.is_installed("apps.notify"):
        from django.http import Http404

        raise Http404
    return render_page(request, "messenger/notifications.html",
                       notify_pages.list_context(request.user, request.GET))
