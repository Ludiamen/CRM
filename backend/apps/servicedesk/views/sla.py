"""Заглушки маршрутов уровней обслуживания (срез 011, этап 2)."""

from django.http import HttpResponse

from apps.core.services.permissions import require_permission


@require_permission("servicedesk.sla")
def sla_list(request):
    return HttpResponse(status=404)


@require_permission("servicedesk.sla")
def sla_new(request):
    return HttpResponse(status=404)


@require_permission("servicedesk.sla")
def sla_edit(request, pk: int):
    return HttpResponse(status=404)


@require_permission("servicedesk.sla")
def sla_archive(request, pk: int):
    return HttpResponse(status=404)
