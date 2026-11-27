"""«Мои задания» (PLAN-014, T-14030)."""
from django.contrib.auth.decorators import login_required

from apps.core.views.common import render_page

from ..services import queue


@login_required
def my(request):
    return render_page(request, "approvals/my/page.html", {
        "rows": queue.rows(request.user), "nav_active": "approvals"})
