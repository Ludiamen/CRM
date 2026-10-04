"""Страницы «Календарь»: год, настройки, загрузка года, правка дня (FR-143…148; T-2237).

Пока заглушки (T-2230a): проверка права окончательная, с правом ответ — 404; тело заменяет T-2237.
День в адресе — строка `<str:day>`: ГГГГ-ММ-ДД разбирает представление, неверная дата — 404.
"""
from django.http import Http404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.services.permissions import require_any_permission, require_permission


@require_any_permission("staff.view", "calendar.manage")
@require_GET
def calendar_year(request):
    """`/calendar/` — календарь года; `?year=`."""
    raise Http404


@require_permission("calendar.manage")
@require_POST
def calendar_settings(request):
    """`/calendar/settings/` — рабочие дни недели, начало и конец дня."""
    raise Http404


@require_permission("calendar.manage")
@require_http_methods(["GET", "POST"])
def calendar_upload(request):
    """`/calendar/upload/` — файл года."""
    raise Http404


@require_permission("calendar.manage")
@require_http_methods(["GET", "POST"])
def calendar_upload_preview(request, upload_id: int):
    """`/calendar/upload/<id>/` — предпросмотр и применение."""
    raise Http404


@require_permission("calendar.manage")
@require_http_methods(["GET", "POST"])
def calendar_day(request, day: str):
    """`/calendar/days/<ГГГГ-ММ-ДД>/` — правка вида дня."""
    raise Http404
