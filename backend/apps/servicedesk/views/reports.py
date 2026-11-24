"""Заглушки маршрутов отчётов сервис-деска (срез 011, этап 2)."""

from django.http import HttpResponse

from apps.core.services.permissions import require_permission


@require_permission("servicedesk.reports")
def report_list(request):
    return HttpResponse(status=404)


@require_permission("servicedesk.reports")
def report_export(request):
    return HttpResponse(status=404)
