"""Страницы раздела «Задачи» (срез 009, каркас T-9009).

T-9009: страницы-заглушки списка и фрагмента списка — адрес и право работают, содержимое добавляет T-9204.
Доски, карточку и действия добавляют T-9203…T-9209.
"""
from django.views.decorators.http import require_GET

from apps.core.services import permissions
from apps.core.views.common import render_page


@require_GET
@permissions.require_permission("tasks.use")
def list_page(request):
    """GET `/tasks/` — список задач (каркас: заголовок и пресеты без строк)."""
    return render_page(request, "tasks/page.html", {"preset": request.GET.get("preset", "mine")})


@require_GET
@permissions.require_permission("tasks.use")
def list_fragment(request):
    """GET `/tasks/list/` — фрагмент списка (каркас: пустой список)."""
    return render_page(request, "tasks/_list.html", {"preset": request.GET.get("preset", "mine")})
