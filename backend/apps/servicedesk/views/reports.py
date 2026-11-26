"""Страница отчёта по заявкам (T-11208, T-11216)."""
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page

from ..services import reports


def _error_response(exc):
    html = (f'<div role="alert" data-code="{exc.code}">{exc.message}</div>'
            f'<div data-error="{exc.field}" data-code="{exc.code}">{exc.message}</div>')
    return HttpResponse(html, status=400)


@require_permission("servicedesk.reports")
def report_list(request):
    try:
        context = reports.build(request.user, request.GET)
    except reports.ReportError as exc:
        if exc.code == "report_forbidden":
            raise PermissionDenied
        return _error_response(exc)
    context.update(reports.choices(request.user))
    context["metric_rows"] = [
        (key, title, (
            f"{context['numbers'][key]:.1f}"
            if key == "requester_rating" and context["numbers"][key] is not None
            else context["numbers"][key]
        ))
        for key, title in (
            ("created", "Создано"), ("closed", "Закрыто"),
            ("average_reaction_minutes", "Среднее время реакции, минут"),
            ("average_solution_minutes", "Среднее время решения, минут"),
            ("reaction_on_time", "Реакция в срок, %"),
            ("solution_on_time", "Решение в срок, %"),
            ("closed_without_response", "Закрыто без ответа"),
            ("requester_rating", "Оценка заявителей"),
            ("requester_rating_count", "Количество оценок заявителей"),
        )
    ]
    context["filter_fields"] = [
        ("queue", "Очередь", context["queues"]),
        ("sla", "Уровень", context["levels"]),
        ("category", "Категория", context["categories"]),
        ("assignee", "Исполнитель", context["assignees"]),
    ]
    return render_page(request, "servicedesk/reports/page.html", context)


@require_permission("servicedesk.reports")
def report_export(request):
    try:
        content = reports.export(request.user, request.GET)
    except reports.ReportError as exc:
        if exc.code == "report_forbidden":
            raise PermissionDenied
        return _error_response(exc)
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{reports.filename()}"'
    return response
